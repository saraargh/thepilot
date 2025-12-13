import discord
from discord import app_commands
import random
import datetime
import pytz
from discord.ext import tasks

# ===== CONFIG =====
UK_TZ = pytz.timezone("Europe/London")

GOAT_ROLE_ID = 1448995127636000788
POO_ROLE_ID = 1429934009550373059
PASSENGERS_ROLE_ID = 1404100554807971971
GENERAL_CHANNEL_ID = 1398508734506078240

ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,  # serversorter
    1420817462290681936,  # kd
    1404105470204969000,  # greg
    1404104881098195015,  # sazzles
    1406242523952713820   # birthday
]

# ===== Helpers =====
def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or ALLOWED_ROLE_IDS
    return any(role.id in allowed_roles for role in member.roles)

async def clear_goat_role(guild: discord.Guild):
    goat_role = guild.get_role(GOAT_ROLE_ID)
    if not goat_role:
        return
    for member in guild.members:
        if goat_role in member.roles:
            await member.remove_roles(goat_role)

async def assign_random_goat(guild: discord.Guild):
    goat_role = guild.get_role(GOAT_ROLE_ID)
    poo_role = guild.get_role(POO_ROLE_ID)
    passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
    general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

    if not all([goat_role, poo_role, passengers_role, general_channel]):
        return

    eligible = [
        m for m in passengers_role.members
        if poo_role not in m.roles
    ]

    if eligible:
        chosen = random.choice(eligible)
        await chosen.add_roles(goat_role)
        await general_channel.send(f"🎉 {chosen.mention} is today’s goat!")
    else:
        await general_channel.send("No passengers available to assign goat!")

async def test_goat(guild: discord.Guild):
    goat_role = guild.get_role(GOAT_ROLE_ID)
    poo_role = guild.get_role(POO_ROLE_ID)
    passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
    general_channel = guild.get_channel(GENERAL_CHANNEL_ID)

    if not all([goat_role, poo_role, passengers_role, general_channel]):
        return

    eligible = [
        m for m in passengers_role.members
        if poo_role not in m.roles
    ]

    if eligible:
        chosen = random.choice(eligible)
        await chosen.add_roles(goat_role)
        await general_channel.send(f"🧪 Test goat assigned to {chosen.mention}!")
    else:
        await general_channel.send("No passengers available for test.")

# ============================================================
#  SETUP COMMANDS + RETURN DAILY TASK
# ============================================================
def setup_goat_commands(tree: app_commands.CommandTree, client: discord.Client, allowed_role_ids=None):
    allowed_role_ids = allowed_role_ids or ALLOWED_ROLE_IDS

    @tasks.loop(minutes=1)
    async def daily_goat_task():
        now = datetime.datetime.now(UK_TZ)

        guild = client.guilds[0] if client.guilds else None
        if not guild:
            return

        # 11am — clear goat
        if now.hour == 11 and now.minute == 0:
            await clear_goat_role(guild)

        # 1pm — clear + assign new goat
        if now.hour == 13 and now.minute == 0:
            await clear_goat_role(guild)
            await assign_random_goat(guild)

    @daily_goat_task.before_loop
    async def before_goat():
        await client.wait_until_ready()

    # ===== Slash Commands =====
    @tree.command(name="cleargoat", description="Clear the goat role from everyone")
    async def cleargoat(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        await clear_goat_role(interaction.guild)
        await interaction.response.send_message("✅ Cleared goat role from everyone.")

    @tree.command(name="assigngoat", description="Manually assign the goat role to a member")
    @app_commands.describe(member="The member to assign the goat role")
    async def assigngoat(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        await member.add_roles(interaction.guild.get_role(GOAT_ROLE_ID))
        await interaction.response.send_message(f"🎉 {member.mention} has been assigned the goat role.")

    @tree.command(name="removegoat", description="Remove the goat role from a member")
    @app_commands.describe(member="The member to remove the goat role from")
    async def removegoat(interaction: discord.Interaction, member: discord.Member):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        await member.remove_roles(interaction.guild.get_role(GOAT_ROLE_ID))
        await interaction.response.send_message(f"❌ {member.mention} has had the goat role removed.")

    @tree.command(name="testgoat", description="Test the goat automation")
    async def testgoat_command(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        await test_goat(interaction.guild)
        await interaction.response.send_message("🧪 Test goat completed!")

    return daily_goat_task