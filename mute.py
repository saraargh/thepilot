# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}

_LISTENER_INSTALLED = False


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):
    global _LISTENER_INSTALLED

    # -------------------------
    # Install stacked on_message listener (cannot be overridden)
    # -------------------------
    if not _LISTENER_INSTALLED:
        _LISTENER_INSTALLED = True

        async def hard_mute_on_message(message: discord.Message):
            if message.author.bot:
                return

            info = muted_users.get(message.author.id)
            if not info:
                return

            until = info.get("until")
            if not until:
                muted_users.pop(message.author.id, None)
                return

            # Expired -> just clear (scheduled loop will announce)
            if datetime.utcnow() >= until:
                muted_users.pop(message.author.id, None)
                return

            # Still muted -> delete message
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                # If this ever fails, it's perms or a transient Discord error.
                # You said mutetest works, so perms should be fine.
                return

        # discord.py internal stacked events list
        if not hasattr(client, "extra_events") or client.extra_events is None:
            client.extra_events = {}

        client.extra_events.setdefault("on_message", []).append(hard_mute_on_message)

    # -------------------------
    # /mute
    # -------------------------
    @tree.command(
        name="mute",
        description="Hard mute a member by deleting their messages"
    )
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.User, minutes: int):
        # Acknowledge instantly so the interaction doesn't expire
        try:
            await interaction.response.defer(thinking=False)  # NOT ephemeral
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You cannot mute anyone.")

        if minutes <= 0:
            return await interaction.followup.send("❌ Mute duration must be greater than 0.")

        if not interaction.guild or not interaction.channel:
            return await interaction.followup.send("❌ Use this in a server channel.")

        # Resolve to guild member (robust)
        guild_member = interaction.guild.get_member(member.id)
        if guild_member is None:
            try:
                guild_member = await interaction.guild.fetch_member(member.id)
            except discord.NotFound:
                return await interaction.followup.send("❌ That user is not in this server.")
            except discord.Forbidden:
                return await interaction.followup.send("❌ I can’t fetch that member.")
            except discord.HTTPException:
                return await interaction.followup.send("❌ Discord error fetching that member.")

        muted_users[guild_member.id] = {
            "until": datetime.utcnow() + timedelta(minutes=minutes),
            "channel_id": interaction.channel.id,
            "guild_id": interaction.guild.id,
        }

        return await interaction.followup.send(
            f"🔇 {guild_member.mention} has been muted for **{minutes}** minutes."
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
            await interaction.response.defer(thinking=False)  # NOT ephemeral
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You cannot unmute anyone.")

        info = muted_users.pop(member.id, None)
        if info is None:
            return await interaction.followup.send(f"❌ {member.mention} is not muted.")

        return await interaction.followup.send(f"🔊 {member.mention} has been unmuted.")

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
            await interaction.response.defer(thinking=False)  # NOT ephemeral
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ No access.")

        if not interaction.channel:
            return await interaction.followup.send("❌ Not a message channel.")

        try:
            async for msg in interaction.channel.history(limit=50):
                if msg.author.id == member.id and not msg.author.bot:
                    try:
                        await msg.delete()
                        return await interaction.followup.send("✅ Delete test: **SUCCESS**")
                    except discord.Forbidden:
                        return await interaction.followup.send("❌ Delete test: **FORBIDDEN**")
                    except discord.HTTPException as e:
                        return await interaction.followup.send(f"❌ Delete test: HTTPException: {e}")

            return await interaction.followup.send("⚠️ No recent message from that member found.")
        except Exception as e:
            return await interaction.followup.send(f"❌ Delete test error: {e}")


# -------------------------
# Scheduled expiry announcer (call from your scheduled loop)
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