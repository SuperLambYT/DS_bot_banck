import os
from dotenv import load_dotenv
import discord

load_dotenv()

ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
GM_ROLE_ID = int(os.getenv("GM_ROLE_ID", "0"))


def _has_role(member: discord.Member, role_id: int) -> bool:
    if role_id == 0:
        return False
    return any(r.id == role_id for r in member.roles)


def is_admin(member: discord.Member) -> bool:
    """Админ: право administrator ИЛИ роль ADMIN_ROLE_ID."""
    return (
        member.guild_permissions.administrator
        or _has_role(member, ADMIN_ROLE_ID)
    )


def is_gm(member: discord.Member) -> bool:
    """ГМ: роль GM_ROLE_ID. Админ автоматически проходит."""
    return is_admin(member) or _has_role(member, GM_ROLE_ID)


def is_bank_staff(member: discord.Member) -> bool:
    """Любой сотрудник банка: ГМ или Админ."""
    return is_gm(member)