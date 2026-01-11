# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):

    # -------------------------
    # /mute
    # -------------------------
    @tree.command(
        name="mute",
        description="Hard mute a member by deleting their messages"
    )
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.User, minutes: int):
        # Acknowledge fast to avoid Unknown interaction
        try:
            await interaction.response.defer(thinking=False, ephemeral=True)
        except Exception:
            # If already responded somehow, just continue and use followup
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You cannot mute anyone.", ephemeral=True)

        if minutes <= 0:
            return await interaction.followup.send("❌ Mute duration must be greater than 0.", ephemeral=True)

        if not interaction.guild or not interaction.channel:
            return await interaction.followup.send("❌ Use this in a server channel.", ephemeral=True)

        # Resolve member (prefer cache first, then fetch)
        guild_member = interaction.guild.get_member(member.id)
        if guild_member is None:
            try:
                guild_member = await interaction.guild.fetch_member(member.id)
            except discord.NotFound:
                return await interaction.followup.send("❌ That user is not in this server.", ephemeral=True)
            except discord.Forbidden:
                return await interaction.followup.send("❌ I can’t fetch that member.", ephemeral=True)
            except discord.HTTPException:
                return await interaction.followup.send("❌ Discord error fetching that member.", ephemeral=True)

        muted_users[guild_member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id
        }

        return await interaction.followup.send(
            f"🔇 {guild_member.mention} has been muted for **{minutes}** minutes.",
            ephemeral=True
        )

    # -------------------------
    # /unmute
    # -------------------------
    @tree.command(
        name="unmute",
        description="Remove a hard mute from a member"
    )
    @app_commands.describe(member="The member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.User):
        try:
            await interaction.response.defer(thinking=False, ephemeral=True)
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You cannot unmute anyone.", ephemeral=True)

        info = muted_users.pop(member.id, None)
        if info is None:
            return await interaction.followup.send(f"❌ {member.mention} is not muted.", ephemeral=True)

        return await interaction.followup.send(f"🔊 {member.mention} has been unmuted.", ephemeral=True)

    # -------------------------
    # /mutetest (debug)
    # -------------------------
    @tree.command(
        name="mutetest",
        description="Debug: attempt to delete the most recent message from a member in this channel"
    )
    @app_commands.describe(member="Member to test deletion against")
    async def mutetest(interaction: discord.Interaction, member: discord.User):
        try:
            await interaction.response.defer(thinking=False, ephemeral=True)
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ No access.", ephemeral=True)

        if not interaction.channel:
            return await interaction.followup.send("❌ Not a message channel.", ephemeral=True)

        try:
            async for msg in interaction.channel.history(limit=50):
                if msg.author.id == member.id and not msg.author.bot:
                    try:
                        await msg.delete()
                        return await interaction.followup.send("✅ Delete test: **SUCCESS**", ephemeral=True)
                    except discord.Forbidden:
                        return await interaction.followup.send("❌ Delete test: **FORBIDDEN**", ephemeral=True)
                    except discord.HTTPException as e:
                        return await interaction.followup.send(f"❌ Delete test: HTTPException: {e}", ephemeral=True)

            return await interaction.followup.send("⚠️ No recent message from that member found.", ephemeral=True)

        except Exception as e:
            return await interaction.followup.send(f"❌ Delete test error: {e}", ephemeral=True)


# -------------------------
# Scheduled expiry announcer (called from your scheduled loop)
# -------------------------
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