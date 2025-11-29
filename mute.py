import discord
from discord import app_commands
from datetime import datetime, timedelta

# Roles allowed to mute/unmute
ALLOWED_ROLE_IDS = [
    1404104881098195015,
    1420817462290681936,
    1404105470204969000,
    1413545658006110401
]

# Store currently muted users
# Format: {user_id: unmute_datetime}
muted_users = {}

def setup_mute_commands(client: discord.Client, tree: app_commands.CommandTree):

    @tree.command(name="mute", description="Hard mute a member by deleting messages automatically")
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes")
    async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You cannot mute anyone.", ephemeral=True)
            return

        unmute_time = datetime.utcnow() + timedelta(minutes=minutes)
        muted_users[member.id] = unmute_time

        await interaction.response.send_message(f"✅ {member.mention} has been hard-muted for {minutes} minutes.")

    @tree.command(name="unmute", description="Remove a hard mute from a member")
    @app_commands.describe(member="The member to unmute")
    async def unmute(interaction: discord.Interaction, member: discord.Member):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You cannot unmute anyone.", ephemeral=True)
            return

        if member.id in muted_users:
            del muted_users[member.id]
            await interaction.response.send_message(f"✅ {member.mention} has been unmuted.")
        else:
            await interaction.response.send_message(f"❌ {member.mention} is not muted.", ephemeral=True)

    # Message listener to delete messages from muted users
    @client.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return

        if message.author.id in muted_users:
            unmute_time = muted_users[message.author.id]
            if datetime.utcnow() >= unmute_time:
                del muted_users[message.author.id]
            else:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass  # Cannot delete messages