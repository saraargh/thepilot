# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int} }
muted_users: dict[int, dict] = {}

# prevent double-wrapping on reloads
_MUTE_ON_MESSAGE_WRAPPED = False


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):
    global _MUTE_ON_MESSAGE_WRAPPED

    # -------------------------
    # /mute
    # -------------------------
    @tree.command(name="mute", description="Hard mute a member by deleting their messages")
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.User, minutes: int):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)

        if minutes <= 0:
            return await interaction.response.send_message("❌ Mute duration must be greater than 0.", ephemeral=True)

        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message("❌ Use this in a server channel.", ephemeral=True)

        # Resolve to guild member (robust)
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

        await interaction.response.send_message(f"🔇 {guild_member.mention} has been muted for **{minutes}** minutes.")

    # -------------------------
    # /unmute
    # -------------------------
    @tree.command(name="unmute", description="Remove a hard mute from a member")
    @app_commands.describe(member="The member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)

        info = muted_users.pop(member.id, None)
        if info is None:
            return await interaction.response.send_message(f"❌ {member.mention} is not muted.", ephemeral=True)

        await interaction.response.send_message(f"🔊 {member.mention} has been unmuted.")

        # Optional: announce in original channel if different
        try:
            ch = client.get_channel(info["channel_id"])
            if ch and interaction.channel and ch.id != interaction.channel.id:
                await ch.send(f"🔊 {member.mention} has been unmuted.")
        except Exception:
            pass

    # -------------------------
    # /mutestatus (debug)
    # -------------------------
    @tree.command(name="mutestatus", description="Check if a member is currently hard-muted")
    @app_commands.describe(member="Member to check")
    async def mutestatus(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No access.", ephemeral=True)

        info = muted_users.get(member.id)
        if not info or not info.get("until"):
            return await interaction.response.send_message(f"✅ {member.mention} is **not** muted.", ephemeral=True)

        seconds_left = (info["until"] - datetime.utcnow()).total_seconds()
        mins_left = max(0, int(seconds_left // 60))
        await interaction.response.send_message(
            f"🔇 {member.mention} is muted. **{mins_left}** min(s) left.",
            ephemeral=True
        )

    # -------------------------
    # /mutetest (debug) attempts a delete right now
    # -------------------------
    @tree.command(name="mutetest", description="Debug: try deleting the most recent message from a member in this channel")
    @app_commands.describe(member="Member to test deletion against")
    async def mutetest(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No access.", ephemeral=True)
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.Messageable):
            return await interaction.response.send_message("❌ Not a message channel.", ephemeral=True)

        try:
            async for msg in interaction.channel.history(limit=50):
                if msg.author.id == member.id and not msg.author.bot:
                    try:
                        await msg.delete()
                        return await interaction.response.send_message("✅ Delete test: **SUCCESS**", ephemeral=True)
                    except discord.Forbidden:
                        return await interaction.response.send_message("❌ Delete test: **FORBIDDEN** (perm issue)", ephemeral=True)
                    except discord.HTTPException as e:
                        return await interaction.response.send_message(f"❌ Delete test: HTTPException: {e}", ephemeral=True)

            return await interaction.response.send_message("⚠️ No recent message from that member found in last 50.", ephemeral=True)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Delete test failed: {e}", ephemeral=True)

    # -------------------------
    # AUTO-HOOK on_message (no bot_slash.py changes required)
    # -------------------------
    if not _MUTE_ON_MESSAGE_WRAPPED:
        _MUTE_ON_MESSAGE_WRAPPED = True

        original_on_message = getattr(client, "on_message", None)

        async def wrapped_on_message(message: discord.Message):
            try:
                blocked = await handle_hard_mute_message(client, message)
                if blocked:
                    return
            except Exception:
                # never break the rest of your bot
                pass

            if original_on_message is not None:
                await original_on_message(message)

        # Replace instance handler
        client.on_message = wrapped_on_message


async def handle_hard_mute_message(client: discord.Client, message: discord.Message) -> bool:
    if message.author.bot:
        return False

    info = muted_users.get(message.author.id)
    if not info:
        return False

    until = info.get("until")
    if not until:
        muted_users.pop(message.author.id, None)
        return False

    # Expired -> auto unmute + announce once
    if datetime.utcnow() >= until:
        muted_users.pop(message.author.id, None)
        try:
            ch = client.get_channel(info.get("channel_id"))
            if ch:
                await ch.send(f"🔊 {message.author.mention} has been automatically unmuted.")
        except Exception:
            pass
        return False

    # Still muted -> delete message
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def process_expired_mutes(client: discord.Client):
    """Optional: call this from a loop if you want expiry announcements even with no further messages."""
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