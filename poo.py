# poo.py
import discord
from discord.ext import tasks
from discord import app_commands
import random
import datetime
import pytz

# ===== CONFIG =====
POO_ROLE_ID = 1429934009550373059    # poo role
PASSENGERS_ROLE_ID = 1404100554807971971 # passengers role
WILLIAM_ROLE_ID = 1404098545006546954  # test role
UK_TZ = pytz.timezone("Europe/London")

# Roles allowed to run commands (by ID)
ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ===== Helper Functions =====
def user_allowed(member: discord.Member, allowed_role_ids):
    return any(role.id in allowed_role_ids for role in member.roles)

async def get_role_safe(guild, role_id):
    role = guild.get_role(role_id)
    if not role:
        raise ValueError(f"Role ID {role_id} not found in guild {guild.name}")
    return role

async def clear_poo_role(guild):
    try:
        poo_role = await get_role_safe(guild, POO_ROLE_ID)
        for member in guild.members:
            if poo_role in member.roles:
                await member.remove_roles(poo_role)
    except ValueError as e:
        print(f"[clear_poo_role] {e}")

async def assign_random_poo(guild):
    try:
        poo_role = await get_role_safe(guild, POO_ROLE_ID)
        passengers_role = await get_role_safe(guild, PASSENGERS_ROLE_ID)
        general_channel = discord.utils.get(guild.text_channels, name="general")
        if not general_channel:
            general_channel = guild.text_channels[0]  # fallback to first channel

        if passengers_role.members:
            selected = random.choice(passengers_role.members)
            await selected.add_roles(poo_role)
            await general_channel.send(f"🎉 {selected.mention} is today’s poo!")
        else:
            await general_channel.send("No passengers available to assign poo!")
    except ValueError as e:
        print(f"[assign_random_poo] {e}")

async def test_poo(guild):
    try:
        poo_role = await get_role_safe(guild, POO_ROLE_ID)
        william_role = await get_role_safe(guild, WILLIAM_ROLE_ID)
        general_channel = discord.utils.get(guild.text_channels, name="general")
        if not general_channel:
            general_channel = guild.text_channels[0]

        if william_role.members:
            selected = random.choice(william_role.members)
            await selected.add_roles(poo_role)
            await general_channel.send(f"🧪 Test poo assigned to {selected.mention}!")
        else:
            await general_channel.send("No members in test role.")
    except ValueError as e:
        print(f"[test_poo] {e}")

# ===== Daily Poo Task =====
async def daily_poo_task(client, allowed_role_ids):
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.datetime.now(UK_TZ)
        if now.hour == 14 and now.minute == 30:  # 2:30 PM
            for guild in client.guilds:
                await clear_poo_role(guild)
                await assign_random_poo(guild)
        await discord.utils.sleep_until(datetime.datetime.now(UK_TZ) + datetime.timedelta(minutes=1))

# ===== Slash Commands Setup =====
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
        try:
            role = await get_role_safe(interaction.guild, POO_ROLE_ID)
            await member.add_roles(role)
            await interaction.response.send_message(f"🎉 {member.mention} has been manually assigned the poo role.")
        except ValueError as e:
            await interaction.response.send_message(f"❌ Error: {e}")

    @tree.command(name="removepoo", description="Remove the poo role from a member")
    @app_commands.describe(member="The member to remove the poo role from")
    async def removepoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        try:
            role = await get_role_safe(interaction.guild, POO_ROLE_ID)
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(f"✅ Removed the poo role from {member.mention}.")
            else:
                await interaction.response.send_message(f"ℹ️ {member.mention} does not have the poo role.")
        except ValueError as e:
            await interaction.response.send_message(f"❌ Error: {e}")

    @tree.command(name="testpoo", description="Test the poo automation using test role")
    async def testpoo_cmd(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await test_poo(interaction.guild)
        await interaction.response.send_message("🧪 Test poo completed!")

    # Schedule daily task inside setup_hook
    @client.event
    async def on_ready():
        client.loop.create_task(daily_poo_task(client, allowed_role_ids))
        print(f"Poo commands loaded for {len(client.guilds)} guild(s).")