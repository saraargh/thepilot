import discord
from discord.ext import tasks, commands
from discord import app_commands
import pytz
import os
from flask import Flask
from threading import Thread

from joinleave import WelcomeSystem
from adminsettings import setup_admin_settings
from image_linker import setup as image_linker_setup
from snipe import setup as snipe_setup

# ✅ SELF ROLES
from selfroles import setup as selfroles_setup
from selfroles import apply_auto_roles

# ✅ ROLE + EMOJI TOOLS
from role_tools import setup as role_tools_setup

# 🎂 BIRTHDAYS
from birthdays import setup as birthdays_setup

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")
UK_TZ = pytz.timezone("Europe/London")

# ===== Discord Client =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True


class ThePilot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.joinleave = WelcomeSystem(self)

    # ---------------- MEMBER JOIN ----------------
    async def on_member_join(self, member: discord.Member):
        await self.joinleave.on_member_join(member)

        # ✅ Auto roles (humans vs bots)
        await apply_auto_roles(member)

    # ---------------- MEMBER REMOVE ----------------
    async def on_member_remove(self, member: discord.Member):
        await self.joinleave.on_member_remove(member)

    # ---------------- MEMBER BAN ----------------
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self.joinleave.on_member_ban(guild, user)

    # ---------------- BOOST EVENTS ----------------
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        await self.joinleave.on_member_update(before, after)

    # ---------------- SETUP ----------------
    async def setup_hook(self):
        # Start scheduled loop (safe to keep even if empty)
        scheduled_tasks.start(self)

        from plane import setup_plane_commands
        from poo import setup_poo_commands
        from goat import setup_goat_commands
        from bot_warnings import setup_warnings_commands
        from mute import setup_mute_commands

        # Commands
        setup_plane_commands(self.tree)

        poo_task = setup_poo_commands(self.tree, self)
        poo_task.start()

        goat_task = setup_goat_commands(self.tree, self)
        goat_task.start()

        setup_warnings_commands(self.tree)
        setup_mute_commands(self, self.tree)

        # Admin settings (Pilot source of truth)
        setup_admin_settings(self.tree)

        # 🎂 Birthdays
        birthdays_setup(self)

        # Image linker
        await image_linker_setup(self.tree)

        # Snipe
        snipe_setup(self, self.tree)

        # ✅ Self roles
        selfroles_setup(self.tree, self)

        # ✅ Role / Emoji tools
        role_tools_setup(self.tree)

        # ✅ NEW: POO / GOAT TRACKER (listener + boards)
        await self.load_extension("poo_goat_tracker")

        # Sync once
        await self.tree.sync()


client = ThePilot()

# ===== Scheduled tasks =====
@tasks.loop(minutes=1)
async def scheduled_tasks(bot_client: ThePilot):
    now = discord.utils.utcnow().astimezone(UK_TZ)
    guild = bot_client.guilds[0] if bot_client.guilds else None
    if guild:
        pass


# ===== Flask keep-alive =====
app = Flask("pilot")

@app.route("/")
def home():
    return "✈️ The Pilot Bot is alive!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


Thread(target=run_flask, daemon=True).start()

client.run(TOKEN)