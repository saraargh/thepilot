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
    "Flight attendants collectively groaned when {user} sat down. Welcome to First Class, {user}.",
    "{user} upgraded! Your ego was too big for economy anyway, {user}.",
    "Seatbelt check: {user} strapped in… but still falling for their own bad ideas, {user}.",
    "First Class unlocked. {user}'s personality still smells like the cargo hold.",
    "{user} upgraded because chaos doesn’t travel coach.",
    "Congratulations {user}! You’re now closer to the snacks and farther from being likable, {user}.",
    "Enjoy First Class, {user} — it’s the only place where people won’t notice how bad you are at life, {user}.",
    "Pilot says: 'If {user} survives this upgrade, miracles exist.'",
    "You now have a seat next to someone who actually understands social cues, {user}. Good luck!",
    "Upgraded for reasons no human or God can explain, {user}. Welcome aboard.",
    "{user} upgraded because the pilot lost a bet… and honestly, nobody else deserves First Class either.",
    "First Class welcomes {user} — try not to scream at the staff about your imaginary problems.",
    "{user} upgraded! Finally, a seat as inflated as your ego.",
    "Congratulations {user}, you now have legroom and zero social skills.",
    "{user} upgraded… the pilot is crying quietly in the cockpit.",
    "First Class unlocked for {user}. Warning: your personality still stinks like luggage.",
    "{user} now has a window seat to watch your dignity fly out the door.",
    "Emergency exit reserved for {user} — not that you’ll ever escape your own bad decisions.",
    "Pilot notes: {user} is dangerous but at least comfortable now.",
    "Upgraded, {user}. Try not to ruin the cabin like you ruin conversations."
]

downgrade_messages = [
    "{user} downgraded to cargo. Enjoy your eternal suffering with the luggage, {user}.",
    "Middle seat eternity activated. Hope you like being elbowed and ignored, {user}.",
    "{user}, your seat has 0 legroom, 100% regret, and a complimentary crying baby.",
    "Pilot just laughed at {user}’s face. Downgrade complete, {user}.",
    "You now sit between someone’s smelly socks and a guy who just sneezed, {user}. Enjoy.",
    "Emergency exit denied. You’re the human pretzel now, {user}.",
    "Congratulations, {user} — your downgrade comes with bonus humiliation.",
    "{user} has been assigned the window that won’t open, the snack cart that won’t stop, and eternal sadness.",
    "Middle seat: where {user}’s dreams go to die. Have fun!",
    "{user}, if you die of boredom, the pilot is not liable.",
    "Seat folds if you cry, {user}. Warning: tears expected.",
    "{user} now travels with 0 dignity and 100% elbow abuse.",
    "Downgraded because the universe hates you, {user}. Don’t fight it.",
    "{user} downgraded to economy… and yes, your life choices are also economy class.",
    "Middle seat eternity granted to {user} — may your knees ache forever.",
    "{user}, enjoy elbow battles with strangers and zero personal space. Literally zero.",
    "Congratulations {user}, your seat is collapsing faster than your social life.",
    "Pilot declares {user} a human pretzel — no escape, no dignity.",
    "{user}, your downgrade includes a crying baby and a window that won’t open.",
    "Seatbelt locked. {user}, your embarrassment is mandatory.",
    "Middle seat horror: {user}, you now sit between people who hate you politely.",
    "{user}, enjoy 0 legroom and infinite regret for the next 6 hours.",
    "Downgraded, {user}. No upgrade will save you — just like your personality."
]

turbulence_messages = [
    "⚠️ Mild turbulence: {user} just blinked and broke physics.",
    "Moderate turbulence: {user} sneezed. Cabin lost structural integrity.",
    "Severe turbulence: {user} posted a hot take. Plane is spinning out of orbit.",
    "Extreme turbulence: {user} just typed 'hello'. Everyone panic!",
    "Server shaking! {user} clearly violates the Geneva Conventions of Chat.",
    "Brace yourselves — {user} just hit enter and destroyed 3 servers simultaneously.",
    "Turbulence intensifies: {user} laughed at someone’s misfortune.",
    "Passenger {user} activated 'chaotic evil mode.' All seats unsafe.",
    "Cabin crew reports: {user} is on fire. Figuratively, maybe literally.",
    "The plane is trembling because {user} exists.",
    "Server integrity compromised. Blame {user} and their existential dread.",
    "Warning: {user} flapped their arms and shattered the concept of gravity.",
    "Turbulence upgrade: {user} just posted a controversial opinion AND a meme at the same time.",
    "⚠️ {user} caused turbulence by existing. Buckle up, everyone else is doomed.",
    "Severe turbulence triggered by {user}. Gravity is suing for damages.",
    "Extreme chaos: {user} just posted a hot take and now the plane is spinning.",
    "Passenger {user} flapped their arms. Physics resigned immediately.",
    "{user} laughed at turbulence. The cabin is filing a restraining order.",
    "Brace yourselves — {user} just sneezed and broke structural integrity.",
    "{user} activated maximum panic mode. No one survives emotionally.",
    "Cabin crew report: {user} is on fire figuratively. Literally may follow.",
    "Turbulence intensifies: {user} just disagreed with someone. Everyone suffers.",
    "{user} typed 'oops'. The plane is now orbiting a trash fire."
]

securitycheck_messages = [
    "🛃 Security finds: {user} smuggling 3 lies, 2 bad decisions, and a cursed emoji.",
    "Contraband detected: {user}’s ego and expired personality.",
    "Threat level: {user} is chaotic evil. Boarding allowed at your own risk.",
    "Security confiscated: {user}’s dignity. Flight may proceed.",
    "Pat-down complete: {user} is suspiciously ridiculous.",
    "Found in carry-on: 0 self-awareness, 100% stupidity. Thanks, {user}.",
    "Security flags: {user} may cause turbulence and emotional distress.",
    "Dangerous materials: {user}’s past tweets and bad memes.",
    "Contraband includes: sense of direction, sense of humor, and {user}.",
    "Security recommends therapy before allowing {user} to breathe near passengers, {user}.",
    "{user} attempted to smuggle drama. Detected and roasted.",
    "Warning: {user} laughed at turbulence. Immediate interrogation required.",
    "Confiscated: {user}’s life choices. Remain seated for embarrassment, {user}.",
    "🛃 Security finds {user} smuggling bad takes and expired memes. Confiscated.",
    "Contraband detected: {user}’s ego, incompetence, and general uselessness.",
    "{user} failed the personality check. Security recommends permanent grounding.",
    "Pat-down complete: {user} is carrying 100% chaos and 0 self-awareness.",
    "{user} attempted to smuggle opinions. All confiscated, plus shame added.",
    "Security confiscates: {user}’s dignity, lunch, and last shred of credibility.",
    "Warning: {user} laughed at a rule. Immediate emotional destruction incoming.",
    "{user} is too dangerous to board. Cabin may collapse just from breathing near them.",
    "Security recommends therapy before allowing {user} to speak again.",
    "{user} is carrying lethal levels of sarcasm, attitude, and general misery."
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

# ===== /wingmates command (embed-friendly) =====
from PIL import Image, ImageDraw
import io
import random

@client.tree.command(name="wingmates", description="Pair two members together (meme-style poster)")
@app_commands.describe(user1="First member", user2="Second member")
async def wingmates(interaction: discord.Interaction, user1: discord.Member, user2: discord.Member):
    if not user1 or not user2:
        await interaction.response.send_message("❌ You must tag exactly two users!", ephemeral=True)
        return

    # ===== Ship Lists =====
    good_ships = ["Power Couple of Turbulence","Snack Cart Soulmates","Window Seat Sweethearts",
                  "In-Flight Romance Legends","Legroom Lovers","Frequent Flyer Lovebirds"]
    bad_ships = ["Middle Seat Misery","Elbow Battle Partners","Screaming Baby Survivors",
                 "Lost Luggage Lovers","Coffee Spill Conspirators","Legroom Losers"]
    chaos_ships = ["Flight Attendant's Worst Nightmare","Oxygen Mask Enthusiasts","Black Hole of Drama",
                   "Emergency Exit Elopers","Snack Cart Sabotage Squad","Cockpit Chaos Crew"]
    in_flight_comments = ["Pilot says: don't talk to each other ever.",
                          "Flight attendants are filing a restraining order.",
                          "Brace for turbulence, the cabin fears you.",
                          "Your compatibility is low… but your chaos is high.",
                          "Cabin crew recommends therapy before boarding again."]

    # ===== Random Ship Type & Result =====
    ship_type = random.choice(["good", "bad", "chaos"])
    if ship_type == "good":
        result = random.choice(good_ships)
        percent = random.randint(70, 100)
        emoji = "❤️"
        border_color = (255, 182, 193)
    elif ship_type == "bad":
        result = random.choice(bad_ships)
        percent = random.randint(0, 40)
        emoji = "💔"
        border_color = (255, 0, 0)
    else:
        result = random.choice(chaos_ships)
        percent = random.randint(30, 80)
        emoji = "⚡"
        border_color = (255, 255, 0)

    comment = random.choice(in_flight_comments)

    # ===== Load Avatars =====
    avatar1_bytes = await user1.display_avatar.read()
    avatar2_bytes = await user2.display_avatar.read()
    avatar1 = Image.open(io.BytesIO(avatar1_bytes)).convert("RGBA").resize((256, 256))
    avatar2 = Image.open(io.BytesIO(avatar2_bytes)).convert("RGBA").resize((256, 256))

    # ===== Create Base Image =====
    width, height = 512, 256
    combined = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    combined.paste(avatar1, (0, 0))
    combined.paste(avatar2, (256, 0))

    # ===== Draw Border & Emoji =====
    draw = ImageDraw.Draw(combined)
    for i in range(8):
        draw.rectangle([i, i, width-i-1, height-i-1], outline=border_color)
    draw.text((width//2 - 10, height//2 - 20), emoji, fill=(255,0,0))

    # ===== Save to Buffer =====
    buffer = io.BytesIO()
    combined.save(buffer, format="PNG")
    buffer.seek(0)
    file = discord.File(fp=buffer, filename="wingmates.png")

    # ===== Send Embed =====
    embed = discord.Embed(
        title=f"{emoji} Wingmate Result",
        description=f"{user1.mention} + {user2.mention}",
        color=random.randint(0, 0xFFFFFF)
    )
    embed.add_field(name="Ship Name", value=result, inline=False)
    embed.add_field(name="Compatibility", value=f"{percent}%", inline=False)
    embed.add_field(name="In-Flight Commentary", value=comment, inline=False)
    embed.set_image(url="attachment://wingmates.png")
    embed.set_footer(text="Generated by The Pilot 🚀")

    await interaction.response.send_message(embed=embed, file=file)

# ===== Pilot Advice Command (GitHub JSON) =====
@client.tree.command(name="pilotadvice", description="Receive the captain's inspirational advice ✈️")
async def pilotadvice(interaction: discord.Interaction):
    """Fetch a random inspirational quote from GitHub for PA-style embed."""
    import requests
    import random

    URL = "https://raw.githubusercontent.com/JamesFT/Database-Quotes-JSON/master/quotes.json"

    try:
        response = requests.get(URL, timeout=5)
        response.raise_for_status()
        data = response.json()  # JSON is a list of objects with 'quote' and 'author'

        # Pick a random quote
        quote = random.choice(data)
        text = quote.get("quote", "Keep calm and fly on!")
        author = quote.get("author", "The Captain")

        # Create embed
        embed = discord.Embed(
            title="✈️ Captain's Advice",
            description=f'📢 Ladies and gentlemen, here’s today’s captain’s advice:\n\n"***{text}***"',
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"- {author} | Brought to you by The Pilot 🚀")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        await interaction.response.send_message(f"❌ Captain can't give advice right now.\nError: {e}")
    
# ===== /boardingpass Command (Styled Flight Boarding Pass) =====
from PIL import Image, ImageDraw, ImageFont
import io, random, datetime
import discord

@client.tree.command(name="boardingpass", description="Get your pilot-style boarding pass ✈️")
async def boardingpass(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user  # default to command user
    await interaction.response.defer()

    # ==== Profile Info ====
    nickname = member.display_name
    join_date = member.joined_at.strftime("%d/%m/%y")
    days_in_server = (datetime.datetime.utcnow() - member.joined_at.replace(tzinfo=None)).days

    # Roles / Class (exclude @everyone)
    roles = [role.name for role in member.roles if role.name != "@everyone"]
    role_text = ", ".join(roles) if roles else "No special roles"

    # Seat assignment
    rows = range(1, 31)
    seats = ["A","B","C","D","E","F"]
    seat = f"Seat {random.choice(rows)}{random.choice(seats)}"

    # ==== Create Image ====
    width, height = 512, 256
    img = Image.new("RGBA", (width, height), (245, 245, 245, 255))
    draw = ImageDraw.Draw(img)

    # Draw avatar
    avatar_bytes = await member.display_avatar.read()
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((256, 256))
    img.paste(avatar, (0,0))

    # Draw right-hand side box background
    draw.rectangle([256, 0, width, height], fill=(230, 230, 250, 255))  # lavender light purple

    # Draw text
    font = ImageFont.load_default()
    text_x = 270
    text_y = 20
    line_height = 28

    # Boxes / separators
    draw.line([text_x, text_y-5, width-10, text_y-5], fill="purple", width=2)
    draw.text((text_x, text_y), f"Call Sign: {nickname}", fill="black", font=font)
    text_y += line_height

    draw.line([text_x, text_y-5, width-10, text_y-5], fill="purple", width=2)
    draw.text((text_x, text_y), f"Joined Server: {join_date}", fill="black", font=font)
    text_y += line_height

    draw.line([text_x, text_y-5, width-10, text_y-5], fill="purple", width=2)
    draw.text((text_x, text_y), f"Days in Server: {days_in_server}", fill="black", font=font)
    text_y += line_height

    draw.line([text_x, text_y-5, width-10, text_y-5], fill="purple", width=2)
    draw.text((text_x, text_y), f"Roles: {role_text}", fill="black", font=font)
    text_y += line_height

    draw.line([text_x, text_y-5, width-10, text_y-5], fill="purple", width=2)
    draw.text((text_x, text_y), f"{seat}", fill="black", font=font)

    # ==== Save image to buffer ====
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    file = discord.File(fp=buffer, filename="boardingpass.png")

    # ==== Create Embed ====
    embed = discord.Embed(
        title=f"🛫 Boarding Pass: {nickname}",
        description="Here’s your personal boarding pass!",
        color=discord.Color.purple()
    )
    embed.set_image(url="attachment://boardingpass.png")
    embed.set_footer(text="Generated by The Pilot 🚀")

    await interaction.followup.send(embed=embed, file=file)

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
