import discord
from discord import app_commands
import random
import datetime
import pytz
from discord.ext import tasks

# ===== CONFIG =====
UK_TZ = pytz.timezone("Europe/London")

POO_ROLE_ID = 1429934009550373059
GOAT_ROLE_ID = 1448995127636000788
PASSENGERS_ROLE_ID = 1404100554807971971
GENERAL_CHANNEL_ID = 1398508734506078240

ALLOWED_ROLE_IDS = [
    1413545658006110401,
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ===== Helpers =====
def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or ALLOWED_ROLE_IDS
    return any(role.id in allowed_roles for role in member.roles)

async def clear_poo_role(guild: discord.Guild):
    poo_role = guild.get_role(POO_ROLE_ID)
    for member in guild.members:
        if poo_role in member.roles:
            await member.remove_roles(poo_role)

async def assign_random_poo(guild: discord.Guild):
    poo_role = guild.get_role(POO_ROLE_ID)
    goat_role = guild.get_role(GOAT_ROLE_ID)
    passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
    general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

    eligible = [
        m for m in passengers_role.members
        if goat_role not in m.roles
    ]

    if eligible:
        chosen = random.choice(eligible)
        await chosen.add_roles(poo_role)
        await general_channel.send(f"🎉 {chosen.mention} is today’s poo!")
    else:
        await general_channel.send("No passengers available to assign poo!")

async def test_poo(guild: discord.Guild):
    passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
    goat_role = guild.get_role(GOAT_ROLE_ID)
    poo_role = guild.get_role(POO_ROLE_ID)
    general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

    eligible = [
        m for m in passengers_role.members
        if goat_role not in m.roles
    ]

    if eligible:
        chosen = random.choice(eligible)
        await chosen.add_roles(poo_role)
        await general_channel.send(f"🧪 Test poo assigned to {chosen.mention}!")
    else:
        await general_channel.send("No passengers available for test.")

# ============================================================
#  SETUP COMMANDS + RETURN DAILY TASK (NO setup_hook changes)
# ============================================================
def setup_poo_commands(tree: app_commands.CommandTree, client: discord.Client, allowed_role_ids=None):
    allowed_role_ids = allowed_role_ids or ALLOWED_ROLE_IDS

    # ===== Daily Task =====
    @tasks.loop(minutes=1)
    async def daily_poo_task():
        now = datetime.datetime.now(UK_TZ)

        if client.guilds:
            guild = client.guilds[0]

            # 11am — clear poo
            if now.hour == 11 and now.minute == 0:
                await clear_poo_role(guild)
                print("11AM: Cleared poo role")

            # 12pm — clear + assign new poo
            if now.hour == 12 and now.minute == 0:
                await clear_poo_role(guild)
                await assign_random_poo(guild)
                print("12PM: Assigned random poo")

    # ===== Slash Commands =====
    @tree.command(name="clearpoo", description="Clear the poo role from everyone")
    async def clearpoo(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await clear_poo_role(interaction.guild)
        await interaction.response.send_message("✅ Cleared poo role from everyone.")

    @tree.command(name="assignpoo", description="Manually assign the poo role to a member")
    @app_commands.describe(member="The member to assign the poo role")
    async def assignpoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        role = interaction.guild.get_role(POO_ROLE_ID)
        await member.add_roles(role)
        await interaction.response.send_message(f"🎉 {member.mention} has been assigned the poo role.")

    @tree.command(name="removepoo", description="Remove the poo role from a member")
    @app_commands.describe(member="The member to remove the poo role from")
    async def removepoo(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        role = interaction.guild.get_role(POO_ROLE_ID)
        await member.remove_roles(role)
        await interaction.response.send_message(f"❌ {member.mention} has had the poo role removed.")

    @tree.command(name="testpoo", description="Test the poo automation")
    async def testpoo_command(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await test_poo(interaction.guild)
        await interaction.response.send_message("🧪 Test poo completed!")

    # RETURN THE TASK FOR botslash.py TO START
    return daily_poo_task