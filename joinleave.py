import discord
import random
import asyncio
from datetime import datetime

# ===== CHANNEL CONFIG =====
WELCOME_CHANNEL_ID = 1444274467864838207
LEAVE_LOG_CHANNEL_ID = 1404500058375717056

# ===== ARRIVAL IMAGES =====
ARRIVALS_IMAGES = [
    "https://cdn.discordapp.com/attachments/1444274467864838207/1449039978205155448/IMG_8494.jpg",
    "https://cdn.discordapp.com/attachments/1444274467864838207/1449040274499174451/IMG_8497.jpg",
    "https://cdn.discordapp.com/attachments/1444274467864838207/1449040298482073770/IMG_8498.jpg",
]

class WelcomeSystem:
    def __init__(self, client: discord.Client):
        self.client = client

    # ======================
    # JOIN (HUMANS ONLY)
    # ======================
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        human_count = len([m for m in guild.members if not m.bot])

        channel = self.client.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title=f"**Welcome to the server, {member.name}! 👋🏼**",
            description=(
                f"Welcome to the server, {member.mention}!\n\n"
                "Regardless of how you found us, we hope you enjoy your time here! ✨🎮\n\n"
                "Don’t forget to visit:\n"
                "• **#self-roles** to pick your roles\n"
                "• **#birthday-set** to get your birthday announcement 🎂"
            ),
            color=discord.Color.from_rgb(255, 200, 220),
            timestamp=datetime.utcnow()
        )

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url=random.choice(ARRIVALS_IMAGES))
        embed.set_footer(text=f"You are member #{human_count}")

        await channel.send(embed=embed)

    # ======================
    # LEAVE / KICK (PLAIN TEXT)
    # ======================
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        channel = self.client.get_channel(LEAVE_LOG_CHANNEL_ID)
        if not channel:
            return

        kicked_by = None

        # Allow audit logs to update
        await asyncio.sleep(1.5)

        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                kicked_by = entry.user
                break

        if kicked_by:
            if member.bot:
                msg = f"🤖 {member.name} (bot) was kicked from the server by {kicked_by}"
            else:
                msg = f"👢 {member.name} was kicked from the server by {kicked_by}"
        else:
            if member.bot:
                msg = f"🤖 {member.name} (bot) left the server"
            else:
                msg = f"👋 {member.name} left the server"

        await channel.send(msg)