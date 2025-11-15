# bot_slash.py
import discord
from discord.ext import tasks
from discord import app_commands
import pytz
import os
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TOKEN")
UK_TZ = pytz.timezone("Europe/London")

ALLOWED_ROLE_IDS = [
    1413545658006110401,
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

intents = discord.Intents.default()
intents.members = True

class ThePilot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

        # START DAILY TASK PROPERLY HERE
        from poo import daily_poo_run
        @tasks.loop(minutes=1)
        async def daily_task():
            await daily_poo_run(self, ALLOWED_ROLE_IDS)

        daily_task.start()

client = ThePilot()

# Imports AFTER client exists
from plane import setup_plane_commands
from tournament import setup_tournament_commands
from poo import setup_poo_commands

# Register slash commands
setup_plane_commands(client.tree)
setup_tournament_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)
setup_poo_commands(client.tree, client, allowed_role_ids=ALLOWED_ROLE_IDS)

# Keep-alive server
app = Flask("")

@app.route("/")
def home():
    return "The Pilot Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run).start()

client.run(TOKEN)