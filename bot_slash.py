import discord
from discord import app_commands
import os
from poo import setup_poo_commands
from plane import setup_plane_commands
from tournament import setup_tournament_commands

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
        # start poo background task safely
        import poo
        self.loop.create_task(poo.daily_poo_task(self, ALLOWED_ROLE_IDS))

client = ThePilot()

# ===== Register Commands =====
setup_plane_commands(client.tree)
setup_tournament_commands(client.tree, allowed_role_ids=ALLOWED_ROLE_IDS)
setup_poo_commands(client.tree, client, allowed_role_ids=ALLOWED_ROLE_IDS)

# ===== Run Bot =====
TOKEN = os.getenv("TOKEN")
client.run(TOKEN)