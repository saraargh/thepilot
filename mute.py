import discord
from discord import app_commands
import asyncio

# Roles allowed to mute/unmute anyone
ALLOWED_ROLE_IDS = [
    1404104881098195015,
    1420817462290681936,
    1404105470204969000,
    1413545658006110401
]

def setup_mute_commands(tree: app_commands.CommandTree):
    @tree.command(
        name="mute",
        description="Mute a member for a specified number of minutes."
    )
    @app_commands.describe(
        member="The member you want to mute",
        minutes="Duration of mute in minutes"
    )
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)
            return

        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await interaction.guild.create_role(name="Muted")
            for channel in interaction.guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False)

        await member.add_roles(muted_role)
        await interaction.response.send_message(f"✅ {member.mention} has been muted for {minutes} minutes.")

        await asyncio.sleep(minutes * 60)
        if muted_role in member.roles:
            await member.remove_roles(muted_role)
            await interaction.followup.send(f"✅ {member.mention} has been unmuted automatically.")

    @tree.command(
        name="unmute",
        description="Manually unmute a member."
    )
    @app_commands.describe(
        member="The member you want to unmute"
    )
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)
            return

        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if muted_role in member.roles:
            await member.remove_roles(muted_role)
            await interaction.response.send_message(f"✅ {member.mention} has been unmuted.")
        else:
            await interaction.response.send_message(f"❌ {member.mention} is not muted.", ephemeral=True)