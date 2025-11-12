# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import random
import asyncio

TOURNAMENT_JSON = "tournament.json"
WORLD_CUP_CHANNEL_ID = None  # optional: set a channel ID to always post there
ROUND_DURATION = 24 * 60 * 60  # 24 hours
TEST_ROUND_DURATION = 60  # 1 minute for test mode rounds

# ===== JSON Persistence =====
def load_data():
    if not os.path.exists(TOURNAMENT_JSON):
        data = {
            "items": [],
            "current_round": [],
            "next_round": [],
            "votes": {},
            "scoreboard": {}
        }
        save_data(data)
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=4)

# ===== Command Setup =====
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    # ----- Add Item -----
    @tree.command(name="addwcitem", description="Add an item to the World Cup list")
    @app_commands.describe(item="Item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            await interaction.response.send_message(f"⚠️ `{item}` is already in the list.")
            return
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ `{item}` added to the World Cup list.")

    # ----- Remove Item -----
    @tree.command(name="removewcitem", description="Remove an item from the World Cup list")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item not in data["items"]:
            await interaction.response.send_message(f"⚠️ `{item}` not found in the list.")
            return
        data["items"].remove(item)
        save_data(data)
        await interaction.response.send_message(f"✅ `{item}` removed from the list.")

    # ----- List Items -----
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.")
            return
        item_list = "\n".join(f"- {i}" for i in data["items"])
        await interaction.response.send_message(f"🏆 Current World Cup Items:\n{item_list}")

    # ----- Reset Tournament -----
    @tree.command(name="resetwc", description="Reset the World Cup tournament completely")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = {
            "items": [],
            "current_round": [],
            "next_round": [],
            "votes": {},
            "scoreboard": {}
        }
        save_data(data)
        await interaction.response.send_message("✅ Tournament has been fully reset.")

    # ----- Start Tournament -----
    @tree.command(name="start_tournament", description="Start the World Cup tournament")
    @app_commands.describe(test="Run in test mode (fast rounds, 1 min each)")
    async def start_tournament(interaction: discord.Interaction, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Need at least 2 items to start the tournament.")
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Cannot start tournament with an odd number of items.")
            return

        # Prepare first round
        data["current_round"] = data["items"][:]
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["votes"] = {}
        save_data(data)

        channel = interaction.guild.get_channel(WORLD_CUP_CHANNEL_ID) if WORLD_CUP_CHANNEL_ID else interaction.channel
        duration = TEST_ROUND_DURATION if test else ROUND_DURATION

        await interaction.response.send_message(f"🏆 Tournament started{' in TEST MODE' if test else ''}! First round will last {duration} seconds.")

        # Start first round
        await run_round(channel, duration)

    # ----- Scoreboard -----
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        if not data["scoreboard"]:
            await interaction.response.send_message("No scores yet.")
            return
        sorted_scores = sorted(data["scoreboard"].items(), key=lambda x: x[1], reverse=True)
        msg = "\n".join(f"{item}: {score}" for item, score in sorted_scores)
        await interaction.response.send_message(f"🏆 Current Scores:\n{msg}")

# ===== Round Runner =====
async def run_round(channel: discord.TextChannel, duration: int):
    data = load_data()
    if not data["current_round"]:
        await channel.send("⚠️ No items to run this round.")
        return

    pairs = [data["current_round"][i:i+2] for i in range(0, len(data["current_round"]), 2)]
    for pair in pairs:
        options = "\n".join(f"{i+1}. {item}" for i, item in enumerate(pair))
        msg = await channel.send(f"Vote for your favorite:\n{options}")
        data["votes"][str(msg.id)] = {item: 0 for item in pair}
        save_data(data)

    await asyncio.sleep(duration)

    # Tally votes randomly for now (replace with real reactions later if needed)
    for pair in pairs:
        winner = random.choice(pair)
        data["next_round"].append(winner)
        data["scoreboard"][winner] = data["scoreboard"].get(winner, 0) + 1
    data["current_round"] = data["next_round"]
    data["next_round"] = []
    data["votes"] = {}
    save_data(data)

    if len(data["current_round"]) == 1:
        await channel.send(f"🎉 Tournament Winner: {data['current_round'][0]} 🏆")
    else:
        await channel.send(f"➡️ Next round starting with {len(data['current_round'])} items...")
        await run_round(channel, duration)