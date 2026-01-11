# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):
    @tree.command(
        name="mute",
        description="Hard mute a member by deleting their messages"
    )
    @app_commands.describe(user="The user to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, user: discord.User, minutes: int):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)

        if minutes <= 0:
            return await interaction.response.send_message("❌ Mute duration must be greater than 0.", ephemeral=True)

        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message("❌ Use this in a server channel.", ephemeral=True)

        # Resolve to a guild member (works even if Discord didn't resolve Member)
        member = interaction.guild.get_member(user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except discord.NotFound:
                return await interaction.response.send_message("❌ That user is not in this server.", ephemeral=True)
            except discord.Forbidden:
                return await interaction.response.send_message("❌ I can’t fetch that member.", ephemeral=True)
            except discord.HTTPException:
                return await interaction.response.send_message("❌ Discord error fetching that member.", ephemeral=True)

        muted_users[member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }

        await interaction.response.send_message(
            f"🔇 {member.mention} has been muted for **{minutes}** minutes."
        )

    @tree.command(
        name="unmute",
        description="Remove a hard mute from a member"
    )
    @app_commands.describe(user="The user to unmute")
    async def unmute(interaction: discord.Interaction, user: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)

        if not interaction.guild:
            return await interaction.response.send_message("❌ Use this in a server.", ephemeral=True)

        # Resolve to member for mention (optional)
        member = interaction.guild.get_member(user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except Exception:
                member = None

        info = muted_users.pop(user.id, None)
        if info is None:
            return await interaction.response.send_message(
                f"❌ {(member.mention if member else user.mention)} is not muted.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"🔊 {(member.mention if member else user.mention)} has been unmuted."
        )

        # Optional: also announce in original channel if different
        try:
            ch = client.get_channel(info["channel_id"])
            if ch and interaction.channel and ch.id != interaction.channel.id:
                await ch.send(f"🔊 {(member.mention if member else user.mention)} has been unmuted.")
        except Exception:
            pass


async def handle_hard_mute_message(client: discord.Client, message: discord.Message) -> bool:
    """
    Call this from your bot's on_message.
    Returns True if we deleted the message (blocked).
    """
    if message.author.bot:
        return False

    info = muted_users.get(message.author.id)
    if not info:
        return False

    until = info.get("until")
    if not until:
        muted_users.pop(message.author.id, None)
        return False

    # expired -> auto unmute + announce once
    if datetime.utcnow() >= until:
        muted_users.pop(message.author.id, None)
        try:
            ch = client.get_channel(info.get("channel_id"))
            if ch:
                await ch.send(f"🔊 {message.author.mention} has been automatically unmuted.")
        except Exception:
            pass
        return False

    # still muted -> delete message
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False