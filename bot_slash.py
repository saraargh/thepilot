import discord
from discord.ext import tasks
from discord import app_commands
import pytz
import os

# ===== CONFIG =====
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

client = ThePilot()

# ===== Import Command Modules =====
from plane import setup_plane_commands
from tournament import setup_tournament_commands
from poo import setup_poo_commands

# ===== Register Commands =====
setup_plane_commands(client.tree)
setup_tournament_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)
setup_poo_commands(client.tree, client, allowed_role_ids=ALLOWED_ROLE_IDS)

# ===== Run Bot =====
client.run(TOKEN)