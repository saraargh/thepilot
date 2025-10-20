# bot_slash.py
import discord
from discord.ext import tasks
from discord import app_commands
import random
import datetime
import pytz
import os
from flask import Flask
from threading import Thread

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")  # use Render environment variable
POO_ROLE_ID = 1428350046323347589        # poo role
PASSENGERS_ROLE_ID = 1404100554807971971 # passengers role
WILLIAM_ROLE_ID = 1413545658006110401    # William role for test
GENERAL_CHANNEL_ID = 1404103684069265519 # general channel
UK_TZ = pytz.timezone("Europe/London")
ALLOWED_ROLE_NAMES = ["William", "KD", "Greg", "server sorter outerer"]  # roles allowed to run commands
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
    """Check if user has one of the allowed roles."""
    for role in member.roles:
        if role.name in ALLOWED_ROLE_NAMES:
            return True
    return False

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
        await general_channel.send("No members in William role for test.")

# ===== Automation Task =====
@tasks.loop(seconds=60)
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

# ===== Slash Commands =====
@client.tree.command(name="clearpoo", description="Clear the poo role from everyone")
async def clearpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    await clear_poo_role(interaction.guild)
    await interaction.response.send_message("✅ Cleared the poo role from everyone.")

@client.tree.command(name="assignpoo", description="Manually assign the poo role to a member")
@app_commands.describe(member="The member to assign the poo role")
async def assignpoo(interaction: discord.Interaction, member: discord.Member):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    poo_role = interaction.guild.get_role(POO_ROLE_ID)
    await member.add_roles(poo_role)
    await interaction.response.send_message(f"🎉 {member.mention} has been manually assigned the poo role.")

@client.tree.command(name="testpoo", description="Test the poo automation using William role")
async def testpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    await test_poo(interaction.guild)
    await interaction.response.send_message("🧪 Test poo completed!")

# ===== Keep-alive web server for Uptime Robot =====
app = Flask("")

@app.route("/")
def home():
    return "Poo Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

t = Thread(target=run)
t.start()

# ===== Run Bot =====
client.run(TOKEN)
