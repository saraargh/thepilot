# mute.py
import discord
from discord import app_commands
from datetime import datetime, timedelta

from permissions import has_app_access

# { user_id: {"until": datetime_utc, "channel_id": int, "guild_id": int, "warned": bool} }
muted_users: dict[int, dict] = {}


def setup_mute_commands(tree: app_commands.CommandTree):
    # ✅ prevent double-registration (this is why you saw the mute message twice)
    try:
        tree.remove_command("mute")
    except Exception:
        pass
    try:
        tree.remove_command("unmute")
    except Exception:
        pass

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
        # ✅ acknowledge quickly to avoid Unknown interaction
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
            "warned": False,
        }

        await interaction.followup.send(
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
        try:
            await interaction.response.defer(thinking=False)
        except Exception:
            pass

        if not has_app_access(interaction.user, "mute"):
            return await interaction.followup.send("❌ You don’t have permission to use /unmute.")

        if member.id not in muted_users:
            return await interaction.followup.send(f"❌ {member.mention} is not muted.")

        muted_users.pop(member.id, None)

        await interaction.followup.send(f"🔊 {member.mention} has been unmuted.")


# =====================================================
# MESSAGE HANDLER (called from bot_slash.py on_message)
# =====================================================
async def check_and_handle_message(client: discord.Client, message: discord.Message) -> bool:
    """Returns True if the message was deleted (blocked)."""
    if message.author.bot:
        return False

    info = muted_users.get(message.author.id)
    if not info:
        return False

    # ✅ ensure we only enforce in the same guild
    if message.guild is None or info.get("guild_id") != message.guild.id:
        return False

    until = info.get("until")
    if not until:
        muted_users.pop(message.author.id, None)
        return False

    # expired → just clear (scheduled loop can announce if you want)
    if datetime.utcnow() >= until:
        muted_users.pop(message.author.id, None)
        return False

    # still muted → delete
    try:
        await message.delete()
        return True

    except discord.Forbidden:
        # ✅ DO NOT FAIL SILENTLY — warn once so you SEE the real problem
        if not info.get("warned"):
            info["warned"] = True
            try:
                await message.channel.send(
                    f"⚠️ I’m trying to cosmetic-mute {message.author.mention} but I **can’t delete messages here**.\n"
                    f"Check channel/category overwrites for the bot’s role: **Manage Messages** must be allowed."
                )
            except Exception:
                pass
        return False

    except discord.HTTPException:
        return False


# =====================================================
# OPTIONAL: auto-unmute announcement loop hook
# (only needed if you want unmute message even if they don't talk again)
# =====================================================
async def process_expired_mutes(client: discord.Client):
    now = datetime.utcnow()
    expired_ids = [uid for uid, info in muted_users.items() if info.get("until") and now >= info["until"]]

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