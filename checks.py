from functools import wraps
import discord

from permissions import is_admin, is_gm


def require_admin(func):
    """Только Админ."""
    @wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "Команда доступна только администрации.",
                ephemeral=True
            )
            return
        return await func(interaction, *args, **kwargs)
    return wrapper


def require_gm(func):
    """ГМ или Админ."""
    @wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not is_gm(interaction.user):
            await interaction.response.send_message(
                "Команда доступна только ГМ или администрации.",
                ephemeral=True
            )
            return
        return await func(interaction, *args, **kwargs)
    return wrapper