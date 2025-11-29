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

class ThePilot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Load scheduled tasks
        scheduled_tasks.start(self)

        # Load command modules
        from plane import setup_plane_commands
        from tournament import setup_tournament_commands
        from poo import setup_poo_commands
        from bot_warnings import setup_warnings_commands

        # Setup commands
        setup_plane_commands(self.tree)
        setup_tournament_commands(self.tree, allowed_role_ids=ALLOWED_ROLE_IDS)
        setup_poo_commands(self.tree, self, allowed_role_ids=ALLOWED_ROLE_IDS)

        # Warnings
        ALLOWED_WARNROLE_IDS = [
            1420817462290681936,
            1413545658006110401,
            1404105470204969000,
            1404098545006546954
        ]
        setup_warnings_commands(self.tree, allowed_role_ids=ALLOWED_WARNROLE_IDS)

        # ===== Setup Mute/Unmute (Discord timeout) =====
        from datetime import timedelta

        @self.tree.command(name="mute", description="Temporarily mute a member using Discord timeout")
        @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
        async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
            if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
                await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)
                return

            if interaction.guild.me.top_role <= member.top_role:
                await interaction.response.send_message("❌ I cannot mute this member because their role is higher than mine.", ephemeral=True)
                return

            duration = timedelta(minutes=minutes)
            await member.timeout(duration, reason=f"Muted by {interaction.user}")
            await interaction.response.send_message(f"✅ {member.mention} has been muted for {minutes} minutes.")

        @self.tree.command(name="unmute", description="Remove a timeout from a member")
        @app_commands.describe(member="The member to unmute")
        async def unmute(interaction: discord.Interaction, member: discord.Member):
            if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
                await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)
                return

            await member.timeout(None, reason=f"Unmuted by {interaction.user}")
            await interaction.response.send_message(f"✅ {member.mention} has been unmuted.")

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