# bot_slash.py
import discord
from discord.ext import tasks
from discord import app_commands
import os
import json
import datetime
import pytz
from flask import Flask
from threading import Thread

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")  # Render environment variable
UK_TZ = pytz.timezone("Europe/London")
POO_ROLE_ID = 1429934009550373059
PASSENGERS_ROLE_ID = 1404100554807971971
WILLIAM_ROLE_ID = 1404098545006546954
GENERAL_CHANNEL_ID = 1398508734506078240

# Roles allowed to manage tournaments
ALLOWED_ROLE_IDS = [
    1413545658006110401,  # Admin/William
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ===== Bot Setup =====
intents = discord.Intents.default()
intents.members = True

class PilotBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        scheduled_tasks.start(self)

client = PilotBot()

# ===== Helper Functions =====
def user_allowed(member: discord.Member):
    return any(role.id in ALLOWED_ROLE_IDS for role in member.roles)

# ===== JSON Storage =====
DATA_FILE = "tournament.json"

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"tournament": None}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ===== Scheduled Tasks =====
@tasks.loop(seconds=60)
async def scheduled_tasks(bot_client):
    now = datetime.datetime.now(UK_TZ)
    if not bot_client.guilds:
        return
    guild = bot_client.guilds[0]

    # 11AM clear poo
    if now.hour == 11 and now.minute == 0:
        poo_role = guild.get_role(POO_ROLE_ID)
        for member in guild.members:
            if poo_role in member.roles:
                await member.remove_roles(poo_role)
        print("Cleared poo role")

    # 12PM assign poo
    if now.hour == 12 and now.minute == 0:
        poo_role = guild.get_role(POO_ROLE_ID)
        passengers_role = guild.get_role(PASSENGERS_ROLE_ID)
        general_channel = guild.get_channel(GENERAL_CHANNEL_ID)
        if passengers_role.members:
            selected = random.choice(passengers_role.members)
            await selected.add_roles(poo_role)
            await general_channel.send(f"🎉 {selected.mention} is today’s poo!")
        else:
            await general_channel.send("No passengers available to assign poo!")

# ===== Module Imports =====
from plane import setup_plane_commands
from poo import setup_poo_commands
from tournament import setup_tournament_commands

setup_plane_commands(client.tree)
setup_poo_commands(client.tree, ALLOWED_ROLE_IDS, POO_ROLE_ID, PASSENGERS_ROLE_ID, GENERAL_CHANNEL_ID)
setup_tournament_commands(client.tree, ALLOWED_ROLE_IDS, DATA_FILE)

# ===== Keep-alive Web Server =====
app = Flask("")

@app.route("/")
def home():
    return "The Pilot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

t = Thread(target=run)
t.start()

# ===== Run Bot =====
client.run(TOKEN)