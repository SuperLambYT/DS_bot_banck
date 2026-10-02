import discord
from discord import app_commands

from database import (
    MAX_CHARACTERS_PER_USER,
    create_character,
    delete_character,
    find_character_by_name,   # ← добавить
    get_all_characters,
    get_balance,
    get_characters,
    get_character,
    get_history,
    transfer_money,
    add_money,
    remove_money,
)
from checks import require_admin, require_gm


def setup_commands(bot: discord.ext.commands.Bot):


    # ХЕЛПЕРЫ

    async def resolve_character(
        interaction: discord.Interaction,
        user: discord.Member,
        name: str
    ):
        """
        Ищет персонажа user с именем name.
        При неудаче отвечает пользователю и возвращает None.
        """
        ch = get_character(user.id, name)
        if not ch:
            await interaction.response.send_message(
                f"У {user.mention} нет персонажа с именем «{name}».",
                ephemeral=True
            )
            return None
        return ch


    # ИГРОК: /balance

    @bot.tree.command(
        name="balance",
        description="Показать баланс персонажа"
    )
    @app_commands.describe(
        character="Имя вашего персонажа (если не указать — покажет всех)"
    )
    async def balance(
        interaction: discord.Interaction,
        character: str = None
    ):
        chars = get_characters(interaction.user.id)

        if not chars:
            await interaction.response.send_message(
                "У вас ещё нет персонажей. Обратитесь к администрации.",
                ephemeral=True
            )
            return

        if character is None:
            lines = [
                f"• **{c['name']}** — {get_balance(c['id'])} кредитов"
                for c in chars
            ]
            await interaction.response.send_message(
                "**Ваши персонажи:**\n" + "\n".join(lines),
                ephemeral=True
            )
            return

        ch = get_character(interaction.user.id, character)
        if not ch:
            await interaction.response.send_message(
                f"У вас нет персонажа с именем «{character}».",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"**{ch['name']}**: {get_balance(ch['id'])} кредитов",
            ephemeral=True
        )


    # ИГРОК: /history

    @bot.tree.command(
        name="history",
        description="История операций персонажа"
    )
    @app_commands.describe(
        character="Имя вашего персонажа",
        limit="Сколько последних операций показать (1–50)"
    )
    async def history(
        interaction: discord.Interaction,
        character: str,
        limit: int = 10
    ):
        limit = max(1, min(limit, 50))
        ch = get_character(interaction.user.id, character)
        if not ch:
            await interaction.response.send_message(
                f"У вас нет персонажа с именем «{character}».",
                ephemeral=True
            )
            return

        records = get_history(ch["id"], limit=limit)
        if not records:
            await interaction.response.send_message(
                f"У персонажа «{ch['name']}» пока нет операций.",
                ephemeral=True
            )
            return

        lines = []
        for r in records:
            ttype = r["transaction_type"]
            amount = r["amount"]
            reason = r["reason"] or "Без причины"

            if ttype == "transfer":
                if r["sender_character_id"] == ch["id"]:
                    text = f"→ **{r['receiver_name'] or '?'}**: -{amount}"
                else:
                    text = f"← **{r['sender_name'] or '?'}**: +{amount}"
            elif ttype == "bank_add":
                text = f"Начисление банком: +{amount}"
            elif ttype == "bank_remove":
                text = f"Списание банком: -{amount}"
            else:
                text = f"{ttype}: {amount}"

            lines.append(f"`#{r['id']}` {text} — {reason}")

        await interaction.response.send_message(
            f"**{ch['name']} — последние операции:**\n" + "\n".join(lines),
            ephemeral=True
        )


    
    # ИГРОК: /pay — перевод другому игроку (по имени персонажа)

    @bot.tree.command(
        name="pay",
        description="Перевести кредиты персонажу другого игрока"
    )
    @app_commands.describe(
        from_character="Имя вашего персонажа-отправителя",
        to_character="Имя персонажа-получателя (другого игрока)",
        amount="Сумма перевода",
        reason="Комментарий к переводу"
    )
    async def pay(
        interaction: discord.Interaction,
        from_character: str,
        to_character: str,
        amount: int,
        reason: str = "Перевод между персонажами"
    ):
        
        sender = get_character(interaction.user.id, from_character)
        if not sender:
            await interaction.response.send_message(
                f"У вас нет персонажа с именем «{from_character}».",
                ephemeral=True
            )
            return

        candidates = find_character_by_name(to_character)

        if not candidates:
            await interaction.response.send_message(
                f"Персонаж с именем «{to_character}» не найден.",
                ephemeral=True
            )
            return

        foreign = [c for c in candidates if c["user_id"] != str(interaction.user.id)]

        if not foreign:
            await interaction.response.send_message(
                "Нельзя переводить своим же персонажам. "
                "Используйте `/pay-self` для переводов между своими персонажами.",
                ephemeral=True
            )
            return

        if len(foreign) > 1:
            lines = [
                f"• <@{c['user_id']}> → **{c['name']}** (id `{c['id']}`)"
                for c in foreign
            ]
            await interaction.response.send_message(
                "Найдено несколько персонажей с именем "
                f"«{to_character}»:\n" + "\n".join(lines) +
                "\n\nПопросите администрацию переименовать одного из них "
                "или используйте `/pay-user`, указав Discord-игрока явно.",
                ephemeral=True
            )
            return

        receiver = foreign[0]

        success, result = transfer_money(
            sender_character_id=sender["id"],
            receiver_character_id=receiver["id"],
            amount=amount,
            reason=reason
        )

        if not success:
            await interaction.response.send_message(f"{result}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"**{sender['name']}** → **{receiver['name']}** "
            f"(<@{receiver['user_id']}>): **{amount} кредитов**\n"
            f"{reason}",
            ephemeral=True
        )


    # ИГРОК: /pay-user — перевод с явным Discord-тегом получателя
    #           (на случай коллизий имён персонажей)

    @bot.tree.command(
        name="pay-user",
        description="Перевести кредиты игроку (с указанием Discord-тега)"
    )
    @app_commands.describe(
        user="Discord-игрок получателя",
        from_character="Имя вашего персонажа-отправителя",
        to_character="Имя персонажа-получателя",
        amount="Сумма перевода",
        reason="Комментарий к переводу"
    )
    async def pay_user(
        interaction: discord.Interaction,
        user: discord.Member,
        from_character: str,
        to_character: str,
        amount: int,
        reason: str = "Перевод между персонажами"
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя переводить боту.", ephemeral=True
            )
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "Для переводов между своими персонажами используйте `/pay-self`.",
                ephemeral=True
            )
            return

        sender = get_character(interaction.user.id, from_character)
        if not sender:
            await interaction.response.send_message(
                f"У вас нет персонажа с именем «{from_character}».",
                ephemeral=True
            )
            return

        receiver = get_character(user.id, to_character)
        if not receiver:
            await interaction.response.send_message(
                f"У {user.mention} нет персонажа с именем «{to_character}».",
                ephemeral=True
            )
            return

        success, result = transfer_money(
            sender_character_id=sender["id"],
            receiver_character_id=receiver["id"],
            amount=amount,
            reason=reason
        )

        if not success:
            await interaction.response.send_message(f"❌ {result}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"**{sender['name']}** → **{receiver['name']}** "
            f"({user.mention}): **{amount} кредитов**\n"
            f"{reason}",
            ephemeral=True
        )


    # ИГРОК: /pay-self — перевод между своими персонажами

    @bot.tree.command(
        name="pay-self",
        description="Перевести кредиты между своими персонажами"
    )
    @app_commands.describe(
        from_character="С чьего персонажа списать",
        to_character="Кому из своих персонажей зачислить",
        amount="Сумма перевода",
        reason="Комментарий"
    )
    async def pay_self(
        interaction: discord.Interaction,
        from_character: str,
        to_character: str,
        amount: int,
        reason: str = "Перевод между своими персонажами"
    ):
        if from_character.strip() == to_character.strip():
            await interaction.response.send_message(
                "Нельзя переводить на тот же счёт.", ephemeral=True
            )
            return

        sender = get_character(interaction.user.id, from_character)
        if not sender:
            await interaction.response.send_message(
                f"У вас нет персонажа с именем «{from_character}».",
                ephemeral=True
            )
            return

        receiver = get_character(interaction.user.id, to_character)
        if not receiver:
            await interaction.response.send_message(
                f"У вас нет персонажа с именем «{to_character}».",
                ephemeral=True
            )
            return

        success, result = transfer_money(
            sender_character_id=sender["id"],
            receiver_character_id=receiver["id"],
            amount=amount,
            reason=reason
        )

        if not success:
            await interaction.response.send_message(f"❌ {result}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"**{sender['name']}** → **{receiver['name']}** "
            f"(оба ваши): **{amount} кредитов**\n"
            f"{reason}",
            ephemeral=True
        )


    # ГМ + АДМИН: /bank-pay, /bank-take

    @bot.tree.command(
        name="bank-pay",
        description="[Банк] Начислить кредиты персонажу"
    )
    @require_gm
    @app_commands.describe(
        user="Discord-игрок",
        character="Имя персонажа",
        amount="Сумма начисления",
        reason="Причина"
    )
    async def bank_pay(
        interaction: discord.Interaction,
        user: discord.Member,
        character: str,
        amount: int,
        reason: str = "Начисление банком"
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя начислять боту.", ephemeral=True
            )
            return

        ch = await resolve_character(interaction, user, character)
        if not ch:
            return

        success, result = add_money(ch["id"], amount, reason)
        if not success:
            await interaction.response.send_message(f"{result}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"**{ch['name']}** ({user.mention}) начислено "
            f"**{amount} кредитов**.\n"
            f"Новый баланс: **{result}**\n"
            f"{reason}",
            ephemeral=True
        )

    @bot.tree.command(
        name="bank-take",
        description="[Банк] Списать кредиты у персонажа"
    )
    @require_gm
    @app_commands.describe(
        user="Discord-игрок",
        character="Имя персонажа",
        amount="Сумма списания",
        reason="Причина"
    )
    async def bank_take(
        interaction: discord.Interaction,
        user: discord.Member,
        character: str,
        amount: int,
        reason: str = "Списание банком"
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя списывать у бота.", ephemeral=True
            )
            return

        ch = await resolve_character(interaction, user, character)
        if not ch:
            return

        success, result = remove_money(ch["id"], amount, reason)
        if not success:
            await interaction.response.send_message(f"{result}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Со счёта **{ch['name']}** ({user.mention}) списано "
            f"**{amount} кредитов**.\n"
            f"Новый баланс: **{result}**\n"
            f"{reason}",
            ephemeral=True
        )


    # ТОЛЬКО АДМИН: регистрация / удаление персонажа

    @bot.tree.command(
        name="admin-create-character",
        description="[Админ] Зарегистрировать персонажа игроку"
    )
    @require_admin
    @app_commands.describe(
        user="Discord-игрок",
        name="Имя персонажа (уникально у игрока, до 32 символов)"
    )
    async def admin_create_character(
        interaction: discord.Interaction,
        user: discord.Member,
        name: str
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя создать персонажа боту.", ephemeral=True
            )
            return

        success, result = create_character(user.id, name)
        if not success:
            await interaction.response.send_message(f"{result}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Персонаж **{name}** создан для {user.mention}.\n"
            f"character_id: `{result}`",
            ephemeral=True
        )

    @bot.tree.command(
        name="admin-delete-character",
        description="[Админ] Удалить персонажа игрока"
    )
    @require_admin
    @app_commands.describe(
        user="Discord-игрок",
        name="Имя персонажа"
    )
    async def admin_delete_character(
        interaction: discord.Interaction,
        user: discord.Member,
        name: str
    ):
        success, message = delete_character(user.id, name)
        if not success:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"{message} (игрок {user.mention})",
            ephemeral=True
        )

    @bot.tree.command(
        name="admin-characters",
        description="[Админ] Список персонажей игрока или всех"
    )
    @require_admin
    @app_commands.describe(user="Discord-игрок (пусто — показать всех)")
    async def admin_characters(
        interaction: discord.Interaction,
        user: discord.Member = None
    ):
        if user is not None:
            chars = get_characters(user.id)
            if not chars:
                await interaction.response.send_message(
                    f"У {user.mention} нет персонажей.", ephemeral=True
                )
                return
            lines = [
                f"• **{c['name']}** — {get_balance(c['id'])} кредитов (id `{c['id']}`)"
                for c in chars
            ]
            await interaction.response.send_message(
                f"**Персонажи {user.mention}:**\n" + "\n".join(lines),
                ephemeral=True
            )
            return

        rows = get_all_characters()
        if not rows:
            await interaction.response.send_message(
                "Персонажей пока нет.", ephemeral=True
            )
            return

        lines = [
            f"• <@{r['user_id']}> → **{r['name']}** — "
            f"{r['balance'] if r['balance'] is not None else 0} кредитов"
            for r in rows
        ]

        header = "**Все персонажи:**\n"
        body = "\n".join(lines)
        if len(header) + len(body) > 1900:
            body = body[:1900] + "\n…обрезано"

        await interaction.response.send_message(header + body, ephemeral=True)


    # ТОЛЬКО АДМИН: просмотр чужих счетов и истории

    @bot.tree.command(
        name="bank-balance",
        description="[Админ] Баланс персонажа игрока"
    )
    @require_admin
    @app_commands.describe(user="Discord-игрок", character="Имя персонажа")
    async def bank_balance(
        interaction: discord.Interaction,
        user: discord.Member,
        character: str
    ):
        ch = await resolve_character(interaction, user, character)
        if not ch:
            return

        await interaction.response.send_message(
            f"**{ch['name']}** ({user.mention}): "
            f"**{get_balance(ch['id'])} кредитов**",
            ephemeral=True
        )

    @bot.tree.command(
        name="bank-history",
        description="[Админ] История операций персонажа"
    )
    @require_admin
    @app_commands.describe(
        user="Discord-игрок",
        character="Имя персонажа",
        limit="Сколько последних операций (1–50)"
    )
    async def bank_history(
        interaction: discord.Interaction,
        user: discord.Member,
        character: str,
        limit: int = 20
    ):
        limit = max(1, min(limit, 50))
        ch = await resolve_character(interaction, user, character)
        if not ch:
            return

        records = get_history(ch["id"], limit=limit)
        if not records:
            await interaction.response.send_message(
                f"У персонажа «{ch['name']}» нет операций.",
                ephemeral=True
            )
            return

        lines = []
        for r in records:
            ttype = r["transaction_type"]
            amount = r["amount"]
            reason = r["reason"] or "Без причины"

            if ttype == "transfer":
                if r["sender_character_id"] == ch["id"]:
                    text = f"→ **{r['receiver_name'] or '?'}**: -{amount}"
                else:
                    text = f"← **{r['sender_name'] or '?'}**: +{amount}"
            elif ttype == "bank_add":
                text = f"Начисление банком: +{amount}"
            elif ttype == "bank_remove":
                text = f"Списание банком: -{amount}"
            else:
                text = f"{ttype}: {amount}"

            lines.append(f"`#{r['id']}` {text} — {reason}")

        header = f"**{ch['name']} — последние {len(records)}:**\n"
        body = "\n".join(lines)
        if len(header) + len(body) > 1900:
            body = body[:1900] + "\n…обрезано"

        await interaction.response.send_message(header + body, ephemeral=True)


    # HELP

    @bot.tree.command(
        name="help",
        description="Список доступных команд"
    )
    async def help_command(interaction: discord.Interaction):
        from permissions import is_admin, is_gm

        text = (
            "## Банковский бот (РП)\n"
            "Экономика привязана к **персонажам**, а не к Discord-аккаунту.\n\n"

            "### Команды игрока\n"
            "`/balance <персонаж>` — баланс.\n"
            "`/history <персонаж>` — история операций.\n"
            "`/pay <мой_персонаж> <персонаж_получателя> <сумма>` — перевод другому.\n"
            "`/pay-user @игрок <мой_персонаж> <персонаж> <сумма>` — перевод с явным тегом.\n"
            "`/pay-self <мой_персонаж> <мой_персонаж> <сумма>` — между своими.\n\n"

            "### Команды ГМ\n"
            "`/bank-pay <@игрок> <персонаж> <сумма>` — начислить кредиты.\n"
            "`/bank-take <@игрок> <персонаж> <сумма>` — списать кредиты.\n"
        )

        if is_admin(interaction.user):
            text += (
                "\n### Команды Админа\n"
                "`/admin-create-character <@игрок> <имя>` — создать персонажа.\n"
                "`/admin-delete-character <@игрок> <имя>` — удалить персонажа.\n"
                "`/admin-characters <@игрок>` — список персонажей.\n"
                "`/bank-balance <@игрок> <персонаж>` — баланс любого персонажа.\n"
                "`/bank-history <@игрок> <персонаж>` — история любого персонажа.\n"
            )

        text += f"\nВалюта: **кредиты**. Лимит персонажей: **{MAX_CHARACTERS_PER_USER}** на игрока."

        await interaction.response.send_message(text, ephemeral=True)