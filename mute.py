# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# =========================
# Store muted users
# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
# =========================
muted_users: dict[int, dict] = {}


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):
    # =========================
    # /mute
    # =========================
    @tree.command(
        name="mute",
        description="Hard mute a member by deleting their messages"
    )
    @app_commands.describe(
        member="The member to mute",
        minutes="Duration in minutes"
    )
    async def mute(
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: int
    ):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message(
                "❌ You cannot mute anyone.",
                ephemeral=True
            )

        if minutes <= 0:
            return await interaction.response.send_message(
                "❌ Mute duration must be greater than 0.",
                ephemeral=True
            )

        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message(
                "❌ This command can only be used in a server channel.",
                ephemeral=True
            )

        muted_users[member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id
        }

        await interaction.response.send_message(
            f"🔇 {member.mention} has been muted for **{minutes}** minutes."
        )

    # =========================
    # /unmute
    # =========================
    @tree.command(
        name="unmute",
        description="Remove a hard mute from a member"
    )
    @app_commands.describe(member="The member to unmute")
    async def unmute(
        interaction: discord.Interaction,
        member: discord.Member
    ):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message(
                "❌ You cannot unmute anyone.",
                ephemeral=True
            )

        info = muted_users.pop(member.id, None)
        if info is None:
            return await interaction.response.send_message(
                f"❌ {member.mention} is not muted.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"🔊 {member.mention} has been unmuted."
        )

        # Optional: also announce in the original channel (if different)
        try:
            ch = client.get_channel(info["channel_id"])
            if ch and interaction.channel and ch.id != interaction.channel.id:
                await ch.send(f"🔊 {member.mention} has been unmuted.")
        except Exception:
            pass

    # =========================
    # Listener: delete messages while muted + auto-unmute announce
    # =========================
    async def hard_mute_listener(message: discord.Message):
        if message.author.bot:
            return

        info = muted_users.get(message.author.id)
        if not info:
            return

        until = info.get("until")
        if not until:
            muted_users.pop(message.author.id, None)
            return

        # Expired -> auto-unmute + announce once
        if datetime.utcnow() >= until:
            muted_users.pop(message.author.id, None)

            # Announce in the channel where mute was issued
            try:
                ch = client.get_channel(info.get("channel_id"))
                if ch:
                    await ch.send(f"🔊 {message.author.mention} has been automatically unmuted.")
            except Exception:
                pass

            return

        # Still muted -> delete their message
        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

    # IMPORTANT: add_listener STACKS (doesn't overwrite other on_message handlers)
    client.add_listener(hard_mute_listener, "on_message")