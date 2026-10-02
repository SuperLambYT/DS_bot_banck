import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import init_db
from commands import setup_commands

# ==== ENV ====
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))


# ==== BOT ====
intents = discord.Intents.default()
intents.message_content = False
intents.members = False

bot = commands.Bot(command_prefix="!", intents=intents)


# ==== READY ====
@bot.event
async def on_ready():
    print(f"Бот {bot.user} запущен!")

    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
        else:
            synced = await bot.tree.sync()

        print(f"Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")


# ==== SETUP ====
init_db()
setup_commands(bot)


# ==== RUN ====
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN не найден в .env")
    bot.run(TOKEN)