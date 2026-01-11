# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}


def setup_mute_commands(tree: app_commands.CommandTree):

    # -------------------------
    # /mute
    # -------------------------
    @tree.command(
        name="mute",
        description="Cosmetic mute (deletes a member’s messages)"
    )
    @app_commands.describe(
        member="Member to mute",
        minutes="Duration in minutes"
    )
    async def mute(
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: int
    ):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to use /mute."
            )

        if minutes <= 0:
            return await interaction.response.send_message(
                "❌ Minutes must be greater than 0."
            )

        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message(
                "❌ This command must be used in a server channel."
            )

        muted_users[member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }

        await interaction.response.send_message(
            f"🔇 {member.mention} has been **cosmetically muted** for **{minutes}** minute(s)."
        )

    # -------------------------
    # /unmute
    # -------------------------
    @tree.command(
        name="unmute",
        description="Remove a cosmetic mute"
    )
    @app_commands.describe(member="Member to unmute")
    async def unmute(
        interaction: discord.Interaction,
        member: discord.Member
    ):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message(
                "❌ You don’t have permission to use /unmute."
            )

        if member.id not in muted_users:
            return await interaction.response.send_message(
                f"❌ {member.mention} is not muted."
            )

        muted_users.pop(member.id, None)

        await interaction.response.send_message(
            f"🔊 {member.mention} has been unmuted."
        )


# =====================================================
# MESSAGE HANDLER (called from bot_slash.py on_message)
# =====================================================
async def check_and_handle_message(
    client: discord.Client,
    message: discord.Message
) -> bool:
    """
    Returns True if the message was deleted (blocked).
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

    # expired → auto-unmute + announce
    if datetime.utcnow() >= until:
        muted_users.pop(message.author.id, None)
        try:
            ch = client.get_channel(info.get("channel_id"))
            if ch:
                await ch.send(f"🔊 {message.author.mention} has been automatically unmuted.")
        except Exception:
            pass
        return False

    # still muted → delete
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False