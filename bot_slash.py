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
POO_ROLE_ID = 1429934009550373059    # poo role
PASSENGERS_ROLE_ID = 1404100554807971971 # passengers role
WILLIAM_ROLE_ID = 1404098545006546954  # William role for test
GENERAL_CHANNEL_ID = 1398508734506078240 # general channel
UK_TZ = pytz.timezone("Europe/London")

# Roles allowed to run commands (by ID)
ALLOWED_ROLE_IDS = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1404105470204969000,
    1420817462290681936
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
    """Check if user has one of the allowed roles by ID."""
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

# ===== Savage / Funny Messages =====
upgrade_messages = [
    "💺 {user} has been upgraded to First Class because the pilot lost a bet and no one can stop them.",
    "First Class achieved! Congratulations, {user}, you now have more space than your personality deserves.",
    "{user} has been upgraded for loud whining and an inflated sense of self. Enjoy legroom, champ.",
    "Flight attendants collectively groaned when {user} sat down. Welcome to First Class.",
    "{user} upgraded! Your ego was too big for economy anyway.",
    "Seatbelt check: {user} strapped in… but still falling for their own bad ideas.",
    "First Class unlocked. Your personality still smells like the cargo hold.",
    "{user} upgraded because chaos doesn’t travel coach.",
    "Congratulations {user}! You’re now closer to the snacks and farther from being likable.",
    "Enjoy First Class, {user} — it’s the only place where people won’t notice how bad you are at life.",
    "Pilot says: 'If {user} survives this upgrade, miracles exist.'",
    "You now have a seat next to someone who actually understands social cues. Good luck.",
    "Upgraded for reasons no human or God can explain. Welcome aboard, {user}."
]

downgrade_messages = [
    "{user} downgraded to cargo. Enjoy your eternal suffering with the luggage.",
    "Middle seat eternity activated. Hope you like being elbowed and ignored, {user}.",
    "{user}, your seat has 0 legroom, 100% regret, and a complimentary crying baby.",
    "Pilot just laughed at {user}’s face. Downgrade complete.",
    "You now sit between someone’s smelly socks and a guy who just sneezed. Enjoy.",
    "Emergency exit denied. You’re the human pretzel now.",
    "Congratulations, {user} — your downgrade comes with bonus humiliation.",
    "{user} has been assigned the window that won’t open, the snack cart that won’t stop, and eternal sadness.",
    "Middle seat: where your dreams go to die. Have fun, {user}.",
    "{user}, if you die of boredom, the pilot is not liable.",
    "Seat folds if you cry. Warning: tears expected.",
    "{user} now travels with 0 dignity and 100% elbow abuse.",
    "Downgraded because the universe hates you. Don’t fight it."
]

turbulence_messages = [
    "⚠️ Mild turbulence: {user} just blinked and broke physics.",
    "Moderate turbulence: {user} sneezed. Cabin lost structural integrity.",
    "Severe turbulence: {user} posted a hot take. Plane is spinning out of orbit.",
    "Extreme turbulence: {user} just typed 'hello'. Everyone panic.",
    "Server shaking! {user} clearly violates the Geneva Conventions of Chat.",
    "Brace yourselves — {user} just hit enter and destroyed 3 servers simultaneously.",
    "Turbulence intensifies: {user} laughed at someone’s misfortune.",
    "Passenger {user} activated 'chaotic evil mode.' All seats unsafe.",
    "Cabin crew reports: {user} is on fire. Figuratively, maybe literally.",
    "The plane is trembling because {user} exists.",
    "Server integrity compromised. Blame {user} and their existential dread.",
    "Warning: {user} flapped their arms and shattered the concept of gravity.",
    "Turbulence upgrade: {user} just posted a controversial opinion AND a meme at the same time."
]

securitycheck_messages = [
    "🛃 Security finds: {user} smuggling 3 lies, 2 bad decisions, and a cursed emoji.",
    "Contraband detected: {user}’s ego and expired personality.",
    "Threat level: {user} is chaotic evil. Boarding allowed at your own risk.",
    "Security confiscated: {user}’s dignity. Flight may proceed.",
    "Pat-down complete: {user} is suspiciously ridiculous.",
    "Found in carry-on: 0 self-awareness, 100% stupidity.",
    "Security flags: {user} may cause turbulence and emotional distress.",
    "Dangerous materials: {user}’s past tweets and bad memes.",
    "Contraband includes: sense of direction, sense of humor, and {user}.",
    "Security recommends therapy before allowing {user} to breathe near passengers.",
    "{user} attempted to smuggle drama. Detected and roasted.",
    "Warning: {user} laughed at turbulence. Immediate interrogation required.",
    "Confiscated: {user}’s life choices. Remain seated for embarrassment."
]

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

@client.tree.command(name="testpoo", description="Test the poo automation using server sorter outer role")
async def testpoo(interaction: discord.Interaction):
    if not user_allowed(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    await test_poo(interaction.guild)
    await interaction.response.send_message("🧪 Test poo completed!")

# Savage/Funny Commands
@client.tree.command(name="upgrade", description="Savagely upgrade a member to First Class")
@app_commands.describe(member="The member to upgrade")
async def upgrade(interaction: discord.Interaction, member: discord.Member):
    msg = random.choice(upgrade_messages).format(user=member.mention)
    await interaction.response.send_message(msg)

@client.tree.command(name="downgrade", description="Savagely downgrade a member to cargo/middle seat")
@app_commands.describe(member="The member to downgrade")
async def downgrade(interaction: discord.Interaction, member: discord.Member):
    msg = random.choice(downgrade_messages).format(user=member.mention)
    await interaction.response.send_message(msg)

@client.tree.command(name="turbulence", description="Cause chaotic turbulence for a member")
@app_commands.describe(member="The member to target")
async def turbulence(interaction: discord.Interaction, member: discord.Member):
    msg = random.choice(turbulence_messages).format(user=member.mention)
    await interaction.response.send_message(msg)

@client.tree.command(name="securitycheck", description="Perform a savage security check on a member")
@app_commands.describe(member="The member to check")
async def securitycheck(interaction: discord.Interaction, member: discord.Member):
    msg = random.choice(securitycheck_messages).format(user=member.mention)
    await interaction.response.send_message(msg)

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
