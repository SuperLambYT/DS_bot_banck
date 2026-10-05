import os
import asyncio
import threading

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import init_db
from commands import setup_commands

from fastapi import FastAPI
import uvicorn


app = FastAPI()


@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "pong"}


# ==== ENV ====
load_dotenv()

TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))


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


# ==== FASTAPI THREAD ====
def run_fastapi():
    """Запускает FastAPI в отдельном потоке с собственным event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = uvicorn.Config(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())


# ==== SETUP ====
init_db()
setup_commands(bot)


# ==== RUN ====
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN не найден в переменных окружения")

    # Запускаем FastAPI в фоновом потоке
    api_thread = threading.Thread(target=run_fastapi, daemon=True)
    api_thread.start()
    print(f"FastAPI запущен на http://{API_HOST}:{API_PORT}")

    # Бот работает в главном потоке
    bot.run(TOKEN)
