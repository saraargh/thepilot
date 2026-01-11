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
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.User, minutes: int):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)

        if minutes <= 0:
            return await interaction.response.send_message("❌ Mute duration must be greater than 0.", ephemeral=True)

        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message("❌ Use this in a server channel.", ephemeral=True)

        # Resolve member (robust)
        guild_member = interaction.guild.get_member(member.id)
        if guild_member is None:
            try:
                guild_member = await interaction.guild.fetch_member(member.id)
            except discord.NotFound:
                return await interaction.response.send_message("❌ That user is not in this server.", ephemeral=True)
            except discord.Forbidden:
                return await interaction.response.send_message("❌ I can’t fetch that member.", ephemeral=True)
            except discord.HTTPException:
                return await interaction.response.send_message("❌ Discord error fetching that member.", ephemeral=True)

        muted_users[guild_member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }

        await interaction.response.send_message(
            f"🔇 {guild_member.mention} has been muted for **{minutes}** minutes."
        )

    @tree.command(
        name="unmute",
        description="Remove a hard mute from a member"
    )
    @app_commands.describe(member="The member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)

        info = muted_users.pop(member.id, None)
        if info is None:
            return await interaction.response.send_message(f"❌ {member.mention} is not muted.", ephemeral=True)

        await interaction.response.send_message(f"🔊 {member.mention} has been unmuted.")

    # Optional debug command (since you said mutetest works)
    @tree.command(
        name="mutetest",
        description="Debug: attempt to delete the most recent message from a member in this channel"
    )
    @app_commands.describe(member="Member to test")
    async def mutetest(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No access.", ephemeral=True)

        if not interaction.channel:
            return await interaction.response.send_message("❌ Not a message channel.", ephemeral=True)

        try:
            async for msg in interaction.channel.history(limit=50):
                if msg.author.id == member.id and not msg.author.bot:
                    try:
                        await msg.delete()
                        return await interaction.response.send_message("✅ Delete test: **SUCCESS**", ephemeral=True)
                    except discord.Forbidden:
                        return await interaction.response.send_message("❌ Delete test: **FORBIDDEN**", ephemeral=True)
                    except discord.HTTPException as e:
                        return await interaction.response.send_message(f"❌ Delete test: HTTPException: {e}", ephemeral=True)

            return await interaction.response.send_message("⚠️ No recent message from that member found (last 50).", ephemeral=True)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Delete test failed: {e}", ephemeral=True)


async def process_expired_mutes(client: discord.Client):
    """Auto-unmute announcements even if the muted user never speaks again."""
    now = datetime.utcnow()
    expired = [uid for uid, info in muted_users.items() if info.get("until") and now >= info["until"]]

    for uid in expired:
        info = muted_users.pop(uid, None)
        if not info:
            continue
        try:
            ch = client.get_channel(info.get("channel_id"))
            if ch:
                await ch.send(f"🔊 <@{uid}> has been automatically unmuted.")
        except Exception:
            pass