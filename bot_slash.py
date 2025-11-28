import discord
from discord.ext import tasks
from discord import app_commands
import pytz
import os
from flask import Flask
from threading import Thread

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")  # Render environment variable
UK_TZ = pytz.timezone("Europe/London")

# Roles allowed to run restricted commands (tournament/poo)
ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ===== Discord Client =====
intents = discord.Intents.default()
intents.members = True

class ThePilot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        scheduled_tasks.start(self)

client = ThePilot()

# ===== Import Command Modules =====
from plane import setup_plane_commands
from tournament import setup_tournament_commands
from poo import setup_poo_commands

# ===== Register Commands =====
setup_plane_commands(client.tree)
setup_tournament_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)
setup_poo_commands(client.tree, client, allowed_role_ids=ALLOWED_ROLE_IDS)

setup_warnings_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)

# ===== Automation Tasks =====
@tasks.loop(minutes=1)
async def scheduled_tasks(bot_client):
    """Placeholder for automated tasks"""
    now = discord.utils.utcnow().astimezone(UK_TZ)
    guild = bot_client.guilds[0] if bot_client.guilds else None
    if guild:
        # You can add more scheduled tasks here
        pass

# ===== Flask Keep-Alive =====
app = Flask("")

@app.route("/")
def home():
    return "The Pilot Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_flask).start()

# ===== Run Bot =====
client.run(TOKEN)