# mute.py
from __future__ import annotations

import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}

_LISTENER_INSTALLED = False


# =====================================================
# MESSAGE HANDLER (single source of truth)
# =====================================================
async def check_and_handle_message(client: discord.Client, message: discord.Message) -> bool:
    """Returns True if the message was deleted (blocked)."""
    if message.author.bot:
        return False

    info = muted_users.get(message.author.id)
    if not info:
        return False

    # Only enforce in same guild
    if message.guild is None or info.get("guild_id") != message.guild.id:
        return False

    until = info.get("until")
    if not until:
        muted_users.pop(message.author.id, None)
        return False

    # expired -> clear silently (scheduled loop can announce)
    if datetime.utcnow() >= until:
        muted_users.pop(message.author.id, None)
        return False

    # still muted -> delete
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


# =====================================================
# STACKED LISTENER (runs even if other modules override on_message)
# =====================================================
def install_mute_listener(client: discord.Client):
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED:
        return
    _LISTENER_INSTALLED = True

    async def _on_message(message: discord.Message):
        try:
            await check_and_handle_message(client, message)
        except Exception:
            pass

    # discord.py internal stacked events list
    if not hasattr(client, "extra_events") or client.extra_events is None:
        client.extra_events = {}

    client.extra_events.setdefault("on_message", []).append(_on_message)


# =====================================================
# COMMANDS
# =====================================================
def setup_mute_commands(tree: app_commands.CommandTree):
    # Prevent duplicate registration (fixes “mute msg posted twice”)
    for cmd_name in ("mute", "unmute"):
        try:
            tree.remove_command(cmd_name)
        except Exception:
            pass

    @tree.command(name="mute", description="Cosmetic mute (deletes a member’s messages)")
    @app_commands.describe(member="Member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        # Acknowledge quickly to avoid “Unknown interaction”
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You don’t have permission to use /mute.")

        if minutes <= 0:
            return await interaction.followup.send("❌ Minutes must be greater than 0.")

        if not interaction.guild or not interaction.channel:
            return await interaction.followup.send("❌ This command must be used in a server channel.")

        muted_users[member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }

        return await interaction.followup.send(
            f"🔇 {member.mention} has been **cosmetically muted** for **{minutes}** minute(s)."
        )

    @tree.command(name="unmute", description="Remove a cosmetic mute")
    @app_commands.describe(member="Member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You don’t have permission to use /unmute.")

        if member.id not in muted_users:
            return await interaction.followup.send(f"❌ {member.mention} is not muted.")

        muted_users.pop(member.id, None)
        return await interaction.followup.send(f"🔊 {member.mention} has been unmuted.")


# =====================================================
# AUTO-UNMUTE ANNOUNCER (call from scheduled loop)
# =====================================================
async def process_expired_mutes(client: discord.Client):
    now = datetime.utcnow()
    expired_ids = [
        uid for uid, info in muted_users.items()
        if info.get("until") and now >= info["until"]
    ]

    for uid in expired_ids:
        info = muted_users.pop(uid, None)
        if not info:
            continue
        try:
            ch = client.get_channel(info.get("channel_id"))
            if ch:
                await ch.send(f"🔊 <@{uid}> has been automatically unmuted.")
        except Exception:
            pass