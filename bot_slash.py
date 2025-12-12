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

# Roles allowed to run restricted commands (tournament/poo & mute)
ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ===== Discord Client =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Needed for on_message deletion

class ThePilot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Start scheduled tasks
        scheduled_tasks.start(self)

        # Load command modules
        from plane import setup_plane_commands
        from tournament import setup_tournament_commands
        from poo import setup_poo_commands
        from goat import setup_goat_commands
        from bot_warnings import setup_warnings_commands
        from mute import setup_mute_commands  # Hard-mute commands

        # Setup commands
        setup_plane_commands(self.tree)
        setup_tournament_commands(self.tree, allowed_role_ids=ALLOWED_ROLE_IDS)

        # ==== FIXED DAILY POO ====
        poo_task = setup_poo_commands(self.tree, self, allowed_role_ids=ALLOWED_ROLE_IDS)
        poo_task.start()   # <-- START THE TASK PROPERLY

        # ==== DAILY GOAT ====
        goat_task = setup_goat_commands(self.tree, self, allowed_role_ids=ALLOWED_ROLE_IDS)
        goat_task.start()  # <-- START GOAT TASK

        # Warnings
        ALLOWED_WARNROLE_IDS = [
            1420817462290681936,
            1413545658006110401,
            1404105470204969000,
            1404098545006546954
        ]
        setup_warnings_commands(self.tree, allowed_role_ids=ALLOWED_WARNROLE_IDS)

        # Setup hard-mute commands and listener
        setup_mute_commands(self, self.tree)

        # Sync all slash commands
        await self.tree.sync()

client = ThePilot()

# ===== Automation Tasks =====
@tasks.loop(minutes=1)
async def scheduled_tasks(bot_client):
    """Placeholder for automated tasks"""
    now = discord.utils.utcnow().astimezone(UK_TZ)
    guild = bot_client.guilds[0] if bot_client.guilds else None
    if guild:
        # Add more scheduled tasks here if needed
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