import discord
from discord.ext import tasks
from discord import app_commands
import random
import datetime
import pytz

# ===== CONFIG =====
POO_ROLE_ID = 1429934009550373059    # poo role
PASSENGERS_ROLE_ID = 1404100554807971971 # passengers role
GENERAL_CHANNEL_ID = 1398508734506078240 # general channel
UK_TZ = pytz.timezone("Europe/London")

ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ===== CLIENT SETUP =====
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

# ===== HELPERS =====
def user_allowed(member: discord.Member):
    return any(role.id in ALLOWED_ROLE_IDS for role in member.roles)

async def clear_poo_role(guild):
    poo_role = guild.get_role(POO_ROLE_ID)
    if not poo_role:
        return
    for member in guild.members:
        if poo_role in member.roles:
            await member.remove_roles(poo_role)

async def assign_random_poo(guild):
    poo_role = guild.get_role(POO_ROLE_ID)
    passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
    general_channel = guild.get_channel(GENERAL_CHANNEL_ID)
    
    if not poo_role or not passengers_role or not general_channel:
        return
    
    if passengers_role.members:
        selected = random.choice(passengers_role.members)
        await selected.add_roles(poo_role)
        await general_channel.send(f"🎉 {selected.mention} is today’s poo!")
    else:
        await general_channel.send("No passengers available to assign poo!")

# ===== AUTOMATION TASK =====
@tasks.loop(seconds=60)
async def scheduled_tasks(bot_client):
    if not bot_client.guilds:
        return
    guild = bot_client.guilds[0]  # assumes 1 server
    now = datetime.datetime.now(UK_TZ)
    
    # 11AM: clear poo
    if now.hour == 11 and now.minute == 0:
        await clear_poo_role(guild)
        print("11AM: Cleared poo role")
    
    # 1PM: assign daily poo
    if now.hour == 13 and now.minute == 0:
        await clear_poo_role(guild)
        await assign_random_poo(guild)
        print("1PM: Assigned daily poo")

# ===== SLASH COMMANDS =====
@client.tree.command(name="clearpoo", description="Clear the poo role from everyone")
async def clearpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    await clear_poo_role(interaction.guild)
    await interaction.response.send_message("✅ Cleared the poo role from everyone.")

@client.tree.command(name="assignpoo", description="Manually assign the poo role to a member")
@app_commands.describe(member="The member to assign the poo role")
async def assignpoo(interaction: discord.Interaction, member: discord.Member):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    role = interaction.guild.get_role(POO_ROLE_ID)
    if not role:
        await interaction.response.send_message("❌ Poo role not found.", ephemeral=True)
        return
    await member.add_roles(role)
    await interaction.response.send_message(f"🎉 {member.mention} has been manually assigned the poo role.")

@client.tree.command(name="removepoo", description="Remove the poo role from a member")
@app_commands.describe(member="The member to remove the poo role from")
async def removepoo(interaction: discord.Interaction, member: discord.Member):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    role = interaction.guild.get_role(POO_ROLE_ID)
    if not role:
        await interaction.response.send_message("❌ Poo role not found.", ephemeral=True)
        return
    await member.remove_roles(role)
    await interaction.response.send_message(f"✅ Removed the poo role from {member.mention}.")

# ===== TEST POOP COMMAND =====
@client.tree.command(name="testpoo", description="Test the poo automation on passengers")
async def testpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    await assign_random_poo(interaction.guild)
    await interaction.response.send_message("🧪 Test poo assigned!")

# ===== RUN CLIENT =====
client.run("YOUR_BOT_TOKEN_HERE")