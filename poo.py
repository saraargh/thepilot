## poo.py
import discord
from discord.ext import tasks
from discord import app_commands
import random
import datetime
import pytz

# ===== CONFIG =====
POO_ROLE_ID = 1429934009550373059    # poo role
PASSENGERS_ROLE_ID = 1404100554807971971 # passengers role
WILLIAM_ROLE_ID = 1404098545006546954  # William role for test
GENERAL_CHANNEL_ID = 1398508734506078240 # general channel
UK_TZ = pytz.timezone("Europe/London")

ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]
# ==================

intents = discord.Intents.default()
intents.members = True

class PooBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        scheduled_tasks.start(self)

client = PooBot()

# ===== Helper Functions =====
def user_allowed(member: discord.Member):
    return any(role.id in ALLOWED_ROLE_IDS for role in member.roles)

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

# ===== Scheduled Task =====
@tasks.loop(seconds=60)
async def scheduled_tasks(bot_client):
    now = datetime.datetime.now(UK_TZ)
    if not bot_client.guilds:
        return
    guild = bot_client.guilds[0]
    # 11AM: clear poo role
    if now.hour == 11 and now.minute == 0:
        await clear_poo_role(guild)
    # 2:30PM: assign poo role
    if now.hour == 14 and now.minute == 30:
        await clear_poo_role(guild)
        await assign_random_poo(guild)

# ===== Slash Commands =====
@client.tree.command(name="clearpoo", description="Clear the poo role from everyone")
async def clearpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    await clear_poo_role(interaction.guild)
    await interaction.response.send_message("✅ Cleared the poo role.")

@client.tree.command(name="assignpoo", description="Manually assign the poo role to a member")
@app_commands.describe(member="The member to assign the poo role")
async def assignpoo(interaction: discord.Interaction, member: discord.Member):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    poo_role = interaction.guild.get_role(POO_ROLE_ID)
    await member.add_roles(poo_role)
    await interaction.response.send_message(f"🎉 {member.mention} has been assigned the poo role.")

@client.tree.command(name="removepoo", description="Remove the poo role from a member")
@app_commands.describe(member="The member to remove the poo role from")
async def removepoo(interaction: discord.Interaction, member: discord.Member):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    poo_role = interaction.guild.get_role(POO_ROLE_ID)
    if poo_role in member.roles:
        await member.remove_roles(poo_role)
        await interaction.response.send_message(f"✅ {member.mention} had the poo role removed.")
    else:
        await interaction.response.send_message(f"ℹ️ {member.mention} does not have the poo role.")

@client.tree.command(name="testpoo", description="Test the poo automation using test role")
async def testpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    await test_poo(interaction.guild)
    await interaction.response.send_message("🧪 Test poo completed!")
    
    # poo.py (at the very end)
def setup_poo_commands(tree: discord.app_commands.CommandTree, allowed_role_ids=None):
    """Register poo commands with the bot tree."""
    # Nothing extra needed — all @tree.command decorators are already applied
    # Just store allowed roles if passed
    global ALLOWED_ROLE_IDS
    if allowed_role_ids is not None:
        ALLOWED_ROLE_IDS = allowed_role_ids