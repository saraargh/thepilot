# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int, "warned": bool} }
muted_users: dict[int, dict] = {}


def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):
    @tree.command(name="mute", description="Hard mute a member by deleting their messages")
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.User, minutes: int):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)

        if minutes <= 0:
            return await interaction.response.send_message("❌ Mute duration must be greater than 0.", ephemeral=True)

        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message("❌ Use this in a server channel.", ephemeral=True)

        # Resolve to actual guild member (robust)
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
            "warned": False,  # used to avoid spam if we can’t delete
        }

        await interaction.response.send_message(
            f"🔇 {guild_member.mention} has been muted for **{minutes}** minutes."
        )

    @tree.command(name="unmute", description="Remove a hard mute from a member")
    @app_commands.describe(member="The member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)

        if not interaction.guild:
            return await interaction.response.send_message("❌ Use this in a server.", ephemeral=True)

        info = muted_users.pop(member.id, None)
        if info is None:
            return await interaction.response.send_message(f"❌ {member.mention} is not muted.", ephemeral=True)

        await interaction.response.send_message(f"🔊 {member.mention} has been unmuted.")

        # Optional: announce in original channel (if different)
        try:
            ch = client.get_channel(info["channel_id"])
            if ch and interaction.channel and ch.id != interaction.channel.id:
                await ch.send(f"🔊 {member.mention} has been unmuted.")
        except Exception:
            pass

    # ✅ Debug: check if a user is muted + when it ends
    @tree.command(name="mutestatus", description="Check if a member is currently hard-muted")
    @app_commands.describe(member="The member to check")
    async def mutestatus(interaction: discord.Interaction, member: discord.User):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No access.", ephemeral=True)

        info = muted_users.get(member.id)
        if not info:
            return await interaction.response.send_message(f"✅ {member.mention} is **not** muted.", ephemeral=True)

        until = info.get("until")
        mins_left = None
        if until:
            delta = (until - datetime.utcnow()).total_seconds()
            mins_left = max(0, int(delta // 60))

        await interaction.response.send_message(
            f"🔇 {member.mention} is muted. Time left: **{mins_left}** min(s).",
            ephemeral=True
        )

    # ✅ Debug: list currently muted users (small)
    @tree.command(name="mutelist", description="List currently hard-muted users")
    async def mutelist(interaction: discord.Interaction):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No access.", ephemeral=True)

        if not muted_users:
            return await interaction.response.send_message("✅ No one is muted.", ephemeral=True)

        lines = []
        now = datetime.utcnow()
        for uid, info in list(muted_users.items()):
            until = info.get("until")
            if not until:
                continue
            mins_left = max(0, int((until - now).total_seconds() // 60))
            lines.append(f"<@{uid}> — {mins_left} min(s) left")

        await interaction.response.send_message("🔇 Muted:\n" + "\n".join(lines[:25]), ephemeral=True)


async def handle_hard_mute_message(client: discord.Client, message: discord.Message) -> bool:
    """Call this from your bot's on_message. Returns True if we blocked/deleted the message."""
    if message.author.bot:
        return False

    info = muted_users.get(message.author.id)
    if not info:
        return False

    until = info.get("until")
    if not until:
        muted_users.pop(message.author.id, None)
        return False

    # expired -> auto unmute + announce once (via scheduler OR next message)
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
    except discord.Forbidden:
        # IMPORTANT: if we can't delete, tell admins ONCE so you know it's perms, not logic
        if not info.get("warned"):
            info["warned"] = True
            try:
                ch = client.get_channel(info.get("channel_id")) or message.channel
                await ch.send(
                    f"⚠️ Hard-mute is active for {message.author.mention} but I **can’t delete messages** here. "
                    f"Grant me **Manage Messages** in this channel/category."
                )
            except Exception:
                pass
        return False
    except discord.HTTPException:
        return False


async def process_expired_mutes(client: discord.Client):
    """Call this from a loop so auto-unmute message fires even if they don’t speak again."""
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