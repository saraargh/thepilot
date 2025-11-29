import discord
from discord import app_commands
from datetime import timedelta

# Roles allowed to mute/unmute anyone
ALLOWED_ROLE_IDS = [
    1404104881098195015,
    1420817462290681936,
    1404105470204969000,
    1413545658006110401
]

def setup_mute_commands(tree: app_commands.CommandTree):

    @tree.command(name="mute", description="Temporarily mute a member using Discord timeout")
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)
            return

        # Check if bot can mute the member
        if interaction.guild.me.top_role <= member.top_role:
            await interaction.response.send_message("❌ I cannot mute this member because their role is higher than mine.", ephemeral=True)
            return

        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=f"Muted by {interaction.user}")
        await interaction.response.send_message(f"✅ {member.mention} has been muted for {minutes} minutes.")

    @tree.command(name="unmute", description="Remove a timeout from a member")
    @app_commands.describe(member="The member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)
            return

        # Remove timeout
        await member.timeout(None, reason=f"Unmuted by {interaction.user}")
        await interaction.response.send_message(f"✅ {member.mention} has been unmuted.")