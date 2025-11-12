# poo.py
import discord
from discord import app_commands
from discord.ext import tasks
import random
import datetime
import pytz

UK_TZ = pytz.timezone("Europe/London")

def setup_poo_commands(tree: app_commands.CommandTree, allowed_ids: list, POO_ROLE_ID: int, PASSENGERS_ROLE_ID: int, GENERAL_CHANNEL_ID: int, WILLIAM_ROLE_ID: int):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_ids for role in member.roles)

    # ===== Helper Functions =====
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

    # ===== Slash Commands =====
    @tree.command(name="clearpoo", description="Clear the poo role from everyone")
    async def clearpoo(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        await clear_poo_role(interaction.guild)
        await interaction.response.send_message("✅ Cleared the poo role from everyone.")

    @tree.command(name="assignpoo", description="Manually assign the poo role to a member")
    @app_commands.describe(member="The member to assign the poo role")
    async def assignpoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        poo_role = interaction.guild.get_role(POO_ROLE_ID)
        await member.add_roles(poo_role)
        await interaction.response.send_message(f"🎉 {member.mention} has been manually assigned the poo role.")

    @tree.command(name="testpoo", description="Test the poo automation using server sorter outer role")
    async def testpoo_command(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        await test_poo(interaction.guild)
        await interaction.response.send_message("🧪 Test poo completed!")

    # ===== Automation Task =====
    @tasks.loop(minutes=1)
    async def scheduled_tasks(bot_client):
        now = datetime.datetime.now(UK_TZ)
        if not bot_client.guilds:
            return
        guild = bot_client.guilds[0]  # assumes 1 server
        # 11AM: Clear poo role
        if now.hour == 11 and now.minute == 0:
            await clear_poo_role(guild)
            print("11AM: Cleared poo role")
        # 12PM: Assign poo randomly and announce
        if now.hour == 12 and now.minute == 0:
            await clear_poo_role(guild)
            await assign_random_poo(guild)
            print("12PM: Assigned random poo and announced")

    return scheduled_tasks