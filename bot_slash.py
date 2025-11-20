# bot_slash.py
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

ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ==================

intents = discord.Intents.default()
intents.members = True

class ThePilot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Sync commands and start scheduled tasks
        await self.tree.sync()
        scheduled_tasks.start(self)

client = ThePilot()

# ===== Import Command Modules =====
from plane import setup_plane_commands
from tournament import setup_tournament_commands
from poo import setup_poo_commands

# ===== Register Commands =====
setup_plane_commands(client.tree)  # Everyone can use plane commands
setup_tournament_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)  # Restricted
setup_poo_commands(client.tree, client, allowed_role_ids=ALLOWED_ROLE_IDS)  # Restricted

# ===== Automation Tasks =====
@tasks.loop(minutes=1)
async def scheduled_tasks(bot_client):
    """Daily/periodic tasks can go here."""
    now = discord.utils.utcnow().astimezone(UK_TZ)
    guild = bot_client.guilds[0] if bot_client.guilds else None
    if guild:
        # Example: automatic Poo assignment
        # Only run at 1pm UK time
        if now.hour == 13 and now.minute == 0:
            # If your poo.py has a function like assign_daily_poo(), call it here
            try:
                from poo import assign_daily_poo
                await assign_daily_poo(bot_client, ALLOWED_ROLE_IDS)
            except Exception as e:
                print("Error running daily poo task:", e)

# ===== Flask Keep-Alive for Render =====
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