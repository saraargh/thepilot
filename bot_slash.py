import discord
from discord.ext import tasks
from discord import app_commands
import pytz
import os
from flask import Flask
from threading import Thread

from joinleave import WelcomeSystem
from adminsettings import setup_admin_settings

from image_linker import setup as image_linker_setup
await image_linker_setup(self.tree)

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")
UK_TZ = pytz.timezone("Europe/London")

# ===== Discord Client =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class ThePilot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.joinleave = WelcomeSystem(self)

    async def on_member_join(self, member: discord.Member):
        await self.joinleave.on_member_join(member)

    async def on_member_remove(self, member: discord.Member):
        await self.joinleave.on_member_remove(member)

    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self.joinleave.on_member_ban(guild, user)

    async def setup_hook(self):
        scheduled_tasks.start(self)

        from plane import setup_plane_commands
        from poo import setup_poo_commands
        from goat import setup_goat_commands
        from bot_warnings import setup_warnings_commands
        from mute import setup_mute_commands

        setup_plane_commands(self.tree)

        poo_task = setup_poo_commands(self.tree, self)
        poo_task.start()

        goat_task = setup_goat_commands(self.tree, self)
        goat_task.start()

        setup_warnings_commands(self.tree)
        setup_mute_commands(self, self.tree)

        # ✅ ONLY /pilotsettings
        setup_admin_settings(self.tree)

        await self.tree.sync()
        


client = ThePilot()

@tasks.loop(minutes=1)
async def scheduled_tasks(bot_client):
    now = discord.utils.utcnow().astimezone(UK_TZ)
    guild = bot_client.guilds[0] if bot_client.guilds else None
    if guild:
        pass

# ===== Flask keep-alive =====
app = Flask("")

@app.route("/")
def home():
    return "The Pilot Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_flask).start()

client.run(TOKEN)