# poo.py
import discord
from discord import app_commands
from discord.ext import tasks
import random
import datetime
import pytz

# ===== CONFIG =====
POO_ROLE_ID = 1429934009550373059    # poo role
PASSENGERS_ROLE_ID = 1404100554807971971 # passengers role
GENERAL_CHANNEL_ID = 1398508734506078240 # general channel
UK_TZ = pytz.timezone("Europe/London")

# ===== Helper Functions =====
def user_allowed(member: discord.Member, allowed_role_ids):
    """Check if user has one of the allowed roles by ID."""
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

# ===== Scheduled Daily Poo Task =====
async def daily_poo_task(client, allowed_role_ids):
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.datetime.now(UK_TZ)
        if client.guilds:
            guild = client.guilds[0]
            # 11 AM: Clear poo role
            if now.hour == 11 and now.minute == 0:
                await clear_poo_role(guild)
            # 1 PM: Assign poo
            if now.hour == 13 and now.minute == 15:
                await assign_random_poo(guild)
        await discord.utils.sleep_until(now + datetime.timedelta(minutes=1))

# ===== Setup Function =====
def setup_poo_commands(tree, client, allowed_role_ids):
    @tree.command(name="clearpoo", description="Clear the poo role from everyone")
    async def clearpoo(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await clear_poo_role(interaction.guild)
        await interaction.response.send_message("✅ Cleared the poo role from everyone.")

    @tree.command(name="assignpoo", description="Manually assign the poo role to a member")
    @app_commands.describe(member="The member to assign the poo role")
    async def assignpoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        poo_role = interaction.guild.get_role(POO_ROLE_ID)
        await member.add_roles(poo_role)
        await interaction.response.send_message(f"🎉 {member.mention} has been manually assigned the poo role.")

    @tree.command(name="removepoo", description="Remove the poo role from a member")
    @app_commands.describe(member="The member to remove the poo role from")
    async def removepoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        poo_role = interaction.guild.get_role(POO_ROLE_ID)
        await member.remove_roles(poo_role)
        await interaction.response.send_message(f"✅ Removed the poo role from {member.mention}.")

    # Start the daily poo task
    client.loop.create_task(daily_poo_task(client, allowed_role_ids))