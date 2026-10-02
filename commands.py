import discord
from discord import app_commands

from database import (
    get_balance,
    get_history,
    transfer_money,
    add_money,
    remove_money,
)
from checks import require_admin, require_gm


def setup_commands(bot: discord.ext.commands.Bot):


    # ИГРОК

    @bot.tree.command(
        name="balance",
        description="Вывести баланс пользователя"
    )
    async def balance(interaction: discord.Interaction):
        amount = get_balance(interaction.user.id)
        await interaction.response.send_message(
            f"Ваш баланс: **{amount} кредитов**",
            ephemeral=True
        )

    @bot.tree.command(
        name="history",
        description="Вывести историю переводов"
    )
    async def history(interaction: discord.Interaction):
        records = get_history(interaction.user.id, limit=10)

        if not records:
            await interaction.response.send_message(
                "История операций пока пуста.",
                ephemeral=True
            )
            return

        lines = []
        for record in records:
            transaction_type = record["transaction_type"]
            amount = record["amount"]
            reason = record["reason"] or "Без причины"

            if transaction_type == "transfer":
                if record["sender_id"] == str(interaction.user.id):
                    text = f"Перевод → <@{record['receiver_id']}>: **-{amount}**"
                else:
                    text = f"Получение ← <@{record['sender_id']}>: **+{amount}**"
            elif transaction_type == "bank_add":
                text = f"Начисление банком: **+{amount}**"
            elif transaction_type == "bank_remove":
                text = f"Списание банком: **-{amount}**"
            else:
                text = f"Операция: **{amount}**"

            lines.append(f"`#{record['id']}` {text} — {reason}")

        await interaction.response.send_message(
            "**Последние операции:**\n" + "\n".join(lines),
            ephemeral=True
        )

    @bot.tree.command(
        name="pay",
        description="Перевести деньги другому игроку"
    )
    @app_commands.describe(
        user="Получатель",
        amount="Сумма перевода",
        reason="Комментарий к переводу"
    )
    async def pay(
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
        reason: str = "Перевод между игроками"
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя переводить деньги боту.",
                ephemeral=True
            )
            return

        success, result = transfer_money(
            sender_id=interaction.user.id,
            receiver_id=user.id,
            amount=amount,
            reason=reason
        )

        if not success:
            await interaction.response.send_message(
                f"{result}",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{interaction.user.mention} перевёл "
            f"**{amount} кредитов** пользователю {user.mention}.\n"
            f"Причина: {reason}",
            ephemeral=True
        )


    # ГМ + АДМИН

    @bot.tree.command(
        name="bank-pay",
        description="[Банк] Начислить деньги игроку"
    )
    @require_gm
    @app_commands.describe(
        user="Получатель",
        amount="Сумма начисления",
        reason="Причина начисления"
    )
    async def bank_pay(
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
        reason: str = "Начисление банком"
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя начислять деньги боту.",
                ephemeral=True
            )
            return

        success, result = add_money(
            user_id=user.id,
            amount=amount,
            reason=reason
        )

        if not success:
            await interaction.response.send_message(
                f"{result}",
                ephemeral=True
            )
            return

        new_balance = result
        await interaction.response.send_message(
            f"{user.mention} начислено **{amount} кредитов**.\n"
            f"Новый баланс: **{new_balance} кредитов**\n"
            f"Причина: {reason}",
            ephemeral=True
        )

    @bot.tree.command(
        name="bank-take",
        description="[Банк] Списать деньги со счёта игрока"
    )
    @require_gm
    @app_commands.describe(
        user="Игрок",
        amount="Сумма списания",
        reason="Причина списания"
    )
    async def bank_take(
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
        reason: str = "Списание банком"
    ):
        if user.bot:
            await interaction.response.send_message(
                "Нельзя списывать деньги у бота.",
                ephemeral=True
            )
            return

        success, result = remove_money(
            user_id=user.id,
            amount=amount,
            reason=reason
        )

        if not success:
            await interaction.response.send_message(
                f"{result}",
                ephemeral=True
            )
            return

        new_balance = result
        await interaction.response.send_message(
            f"Со счёта {user.mention} списано **{amount} кредитов**.\n"
            f"Новый баланс: **{new_balance} кредитов**\n"
            f"Причина: {reason}",
            ephemeral=True
        )


    # ТОЛЬКО АДМИН

    @bot.tree.command(
        name="bank-balance",
        description="[Банк] Посмотреть баланс игрока"
    )
    @require_admin
    @app_commands.describe(user="Игрок")
    async def bank_balance(
        interaction: discord.Interaction,
        user: discord.Member
    ):
        amount = get_balance(user.id)
        await interaction.response.send_message(
            f"Баланс {user.mention}: **{amount} кредитов**",
            ephemeral=True
        )

    @bot.tree.command(
        name="bank-history",
        description="[Банк] Посмотреть историю операций игрока"
    )
    @require_admin
    @app_commands.describe(
        user="Игрок",
        limit="Сколько последних операций показать (1–50)"
    )
    async def bank_history(
        interaction: discord.Interaction,
        user: discord.Member,
        limit: int = 20
    ):
        limit = max(1, min(limit, 50))
        records = get_history(user.id, limit=limit)

        if not records:
            await interaction.response.send_message(
                f" У пользователя {user.mention} нет операций.",
                ephemeral=True
            )
            return

        lines = []
        for record in records:
            transaction_type = record["transaction_type"]
            amount = record["amount"]
            reason = record["reason"] or "Без причины"

            if transaction_type == "transfer":
                if record["sender_id"] == str(user.id):
                    text = f"Перевод → <@{record['receiver_id']}>: **-{amount}**"
                else:
                    text = f"Получение ← <@{record['sender_id']}>: **+{amount}**"
            elif transaction_type == "bank_add":
                text = f"Начисление банком: **+{amount}**"
            elif transaction_type == "bank_remove":
                text = f"Списание банком: **-{amount}**"
            else:
                text = f"Операция: **{amount}**"

            lines.append(f"`#{record['id']}` {text} — {reason}")

        header = f"** История {user.display_name} (последние {len(records)}):**\n"
        body = "\n".join(lines)

        if len(header) + len(body) > 1900:
            body = body[:1900] + "\n…обрезано"

        await interaction.response.send_message(
            header + body,
            ephemeral=True
        )


    # HELP

    @bot.tree.command(
        name="help",
        description="Список доступных команд"
    )
    async def help_command(interaction: discord.Interaction):
        from permissions import is_admin, is_gm

        text = (
            "## Банковский бот\n"
            "Управление игровой валютой, переводами и историей операций.\n\n"

            "### Команды игрока\n"
            "`/balance` — посмотреть свой баланс.\n"
            "`/history` — история своих операций.\n"
            "`/pay` — перевести деньги другому игроку.\n"
        )

        if is_gm(interaction.user):
            text += (
                "\n### Команды ГМ\n"
                "`/bank-pay` — начислить кредиты игроку.\n"
                "`/bank-take` — списать кредиты у игрока.\n"
            )

        if is_admin(interaction.user):
            text += (
                "\n### Команды Админа\n"
                "`/bank-balance` — баланс любого игрока.\n"
                "`/bank-history` — история операций любого игрока.\n"
            )

        text += "\n Валюта: **кредиты**"

        await interaction.response.send_message(text, ephemeral=True)