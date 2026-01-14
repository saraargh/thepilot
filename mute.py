from __future__ import annotations
import discord
from discord import app_commands
from datetime import timedelta
import pytz

from permissions import has_app_access

UK_TZ = pytz.timezone("Europe/London")

# We no longer need the dictionary or the on_message listener! 
# Discord handles the timing and the blocking for us.

def setup_mute_commands(tree: app_commands.CommandTree):
    # Remove old versions
    for name in ["mute", "unmute"]:
        try:
            tree.remove_command(name)
        except:
            pass

    @tree.command(name="mute", description="Timeout a member using Discord's native system")
    @app_commands.describe(member="Member to timeout", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        if minutes <= 0:
            return await interaction.response.send_message("❌ Minutes must be greater than 0.", ephemeral=True)

        try:
            # Discord's timeout method
            duration = timedelta(minutes=minutes)
            await member.timeout(duration, reason=f"Muted by {interaction.user}")
            
            await interaction.response.send_message(
                f"🔇 {member.mention} has been timed out for **{minutes}** minute(s)."
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to timeout this member. (Check Role Hierarchy)", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @tree.command(name="unmute", description="Remove timeout from a member")
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        if not has_app_access(interaction.user, "mute"):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        try:
            # Passing None removes the timeout
            await member.timeout(None)
            await interaction.response.send_message(f"🔊 Timeout removed for {member.mention}.")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I cannot unmute this member.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

# You can keep this as an empty function so your main file doesn't crash
async def process_expired_mutes(client: discord.Client):
    pass

async def check_and_handle_message(client: discord.Client, message: discord.Message) -> bool:
    return False # Discord handles the blocking now
