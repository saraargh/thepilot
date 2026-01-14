from __future__ import annotations
import discord
from discord import app_commands
from datetime import datetime, timedelta
import pytz

from permissions import has_app_access

UK_TZ = pytz.timezone("Europe/London")

# { user_id: {"until": datetime, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}

async def check_and_handle_message(client: discord.Client, message: discord.Message) -> bool:
    """Returns True if the message was deleted (blocked)."""
    if message.author.bot or not message.guild:
        return False

    info = muted_users.get(message.author.id)
    if not info:
        return False

    if info.get("guild_id") != message.guild.id:
        return False

    until = info.get("until")
    if not until:
        muted_users.pop(message.author.id, None)
        return False

    # Comparison using London Time
    now = datetime.now(UK_TZ)
    if now >= until:
        muted_users.pop(message.author.id, None)
        return False

    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False

def setup_mute_commands(tree: app_commands.CommandTree):
    for cmd_name in ("mute", "unmute"):
        try:
            tree.remove_command(cmd_name)
        except: pass

    @tree.command(name="mute", description="Mute a member (deletes their messages)")
    @app_commands.describe(member="Member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        try:
            await interaction.response.defer(thinking=False)
        except: pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You don’t have permission.")

        if minutes <= 0:
            return await interaction.followup.send("❌ Minutes must be > 0.")

        muted_users[member.id] = {
            "until": datetime.now(UK_TZ) + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }
        return await interaction.followup.send(f"🔇 {member.mention} muted for **{minutes}** min(s).")

    @tree.command(name="unmute", description="Unmute a member")
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ No permission.")
        muted_users.pop(member.id, None)
        return await interaction.followup.send(f"🔊 {member.mention} unmuted.")

async def process_expired_mutes(client: discord.Client):
    now = datetime.now(UK_TZ)
    expired_ids = [uid for uid, info in muted_users.items() if info.get("until") and now >= info["until"]]
    for uid in expired_ids:
        info = muted_users.pop(uid, None)
        if info:
            ch = client.get_channel(info.get("channel_id"))
            if ch: await ch.send(f"🔊 <@{uid}> has been automatically unmuted.")
