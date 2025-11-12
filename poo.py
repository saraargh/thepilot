# poo.py
import discord
from discord import app_commands
import random

POO_ROLE_ID = 1429934009550373059
PASSENGERS_ROLE_ID = 1404100554807971971
WILLIAM_ROLE_ID = 1404098545006546954
GENERAL_CHANNEL_ID = 1398508734506078240

def setup_poo_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def clear_poo_role(guild):
        poo_role = guild.get_role(POO_ROLE_ID)
        for member in guild.members:
            if poo_role in member.roles:
                await member.remove_roles(poo_role)

    async def assign_random_poo(guild):
        poo_role = guild.get_role(POO_ROLE_ID)
        passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
        general_channel = guild.get_channel(GENERAL_CHANNEL_ID)
        
        if passengers_role.members:
            selected = random.choice(passengers_role.members)
            await selected.add_roles(poo_role)
            await general_channel.send(f"🎉 {selected.mention} is today’s poo!")
        else:
            await general_channel.send("No passengers available to assign poo!")

    async def test_poo(guild):
        poo_role = guild.get_role(POO_ROLE_ID)
        william_role = guild.get_role(WILLIAM_ROLE_ID)
        general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

        if william_role.members:
            selected = random.choice(william_role.members)
            await selected.add_roles(poo_role)
            await general_channel.send(f"🧪 Test poo assigned to {selected.mention}!")
        else:
            await general_channel.send("No members in allocated role for test.")

    @tree.command(name="clearpoo", description="Clear the poo role from everyone")
    async def clearpoo(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await clear_poo_role(interaction.guild)
        await interaction.response.send_message("✅ Cleared the poo role from everyone.")

    @tree.command(name="assignpoo", description="Manually assign the poo role to a member")
    @app_commands.describe(member="The member to assign the poo role")
    async def assignpoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        poo_role = interaction.guild.get_role(POO_ROLE_ID)
        await member.add_roles(poo_role)
        await interaction.response.send_message(f"🎉 {member.mention} has been manually assigned the poo role.")

    @tree.command(name="testpoo", description="Test the poo automation using server sorter outer role")
    async def testpoo(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await test_poo(interaction.guild)
        await interaction.response.send_message("🧪 Test poo completed!")