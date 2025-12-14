# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# =========================
# Store currently muted users
# Format: {user_id: unmute_datetime}
# =========================

muted_users = {}


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):

    # =========================
    # /mute
    # =========================
    @tree.command(
        name="mute",
        description="Hard mute a member by deleting messages automatically"
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

        unmute_time = datetime.utcnow() + timedelta(minutes=minutes)
        muted_users[member.id] = unmute_time

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
    @app_commands.describe(
        member="The member to unmute"
    )
    async def unmute(
        interaction: discord.Interaction,
        member: discord.Member
    ):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message(
                "❌ You cannot unmute anyone.",
                ephemeral=True
            )

        if member.id in muted_users:
            del muted_users[member.id]
            await interaction.response.send_message(
                f"🔊 {member.mention} has been unmuted."
            )
        else:
            await interaction.response.send_message(
                f"❌ {member.mention} is not muted.",
                ephemeral=True
            )

    # =========================
    # Message listener
    # =========================
    @client.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return

        if message.author.id in muted_users:
            unmute_time = muted_users.get(message.author.id)

            if not unmute_time:
                return

            if datetime.utcnow() >= unmute_time:
                del muted_users[message.author.id]
                return

            try:
                await message.delete()
            except discord.Forbidden:
                pass  # Bot cannot delete messages
            except discord.HTTPException:
                pass