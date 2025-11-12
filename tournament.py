# tournament.py
import discord
from discord import app_commands
import asyncio
import json
import os
import random

# -------------------------
# Config / Paths
# -------------------------
TOURNAMENT_JSON = "/mnt/data/tournament_data.json"

# Default structure
DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "test_mode": False
}

# Allowed roles (IDs)
ALLOWED_ROLE_IDS = [123456789012345678, 987654321098765432]  # replace with real IDs

# -------------------------
# JSON Handling
# -------------------------
def ensure_json():
    """Ensure the JSON file exists; create if missing."""
    if not os.path.exists(TOURNAMENT_JSON):
        os.makedirs(os.path.dirname(TOURNAMENT_JSON), exist_ok=True)
        with open(TOURNAMENT_JSON, "w") as f:
            json.dump(DEFAULT_DATA, f, indent=4)

def load_data():
    ensure_json()
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    ensure_json()
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=4)

# -------------------------
# Permissions
# -------------------------
def user_allowed(member: discord.Member):
    return any(role.id in ALLOWED_ROLE_IDS for role in member.roles)

# -------------------------
# Tournament Logic
# -------------------------
async def start_test_tournament(interaction: discord.Interaction, title: str):
    data = load_data()
    data["title"] = title
    data["test_mode"] = True
    data["running"] = True
    save_data(data)

    await interaction.response.send_message(f"🏁 Test Tournament **{title}** started! Each match will last 10 seconds.")

    while data["running"]:
        data = load_data()
        if not data["items"] or len(data["items"]) < 2:
            await interaction.followup.send("❌ Not enough items to run a tournament.")
            break

        data["current_round"] = random.sample(data["items"], len(data["items"]))
        save_data(data)

        for i in range(0, len(data["current_round"]), 2):
            item_a = data["current_round"][i]
            item_b = data["current_round"][i+1] if i+1 < len(data["current_round"]) else None
            if not item_b:
                winner = item_a
            else:
                await interaction.followup.send(f"Vote: 🅰 {item_a} or 🅱 {item_b} (React to vote)")
                await asyncio.sleep(10)  # test vote duration
                winner = random.choice([item_a, item_b])
                await interaction.followup.send(f"✅ {winner} wins this matchup!")
            data["next_round"].append(winner)
            save_data(data)

        # Prepare next round
        if len(data["next_round"]) == 1:
            winner = data["next_round"][0]
            await interaction.followup.send(f"🏆 Tournament finished! Winner: {winner}")
            # Here you can send your winner GIF embed
            data["running"] = False
            data["next_round"] = []
        else:
            data["current_round"] = data["next_round"]
            data["next_round"] = []
        save_data(data)

# -------------------------
# Command Setup
# -------------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):
    # Permissions check
    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added `{item}` to the World Cup items.")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed `{item}` from World Cup items.")
        else:
            await interaction.response.send_message(f"❌ `{item}` not found in items.")

    @tree.command(name="listwcitems", description="List all World Cup items")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.")
            return
        msg = "\n".join(f"{idx+1}: {itm}" for idx, itm in enumerate(data["items"]))
        await interaction.response.send_message(f"📋 **World Cup Items:**\n{msg}")

    @tree.command(name="resettournament", description="Reset the tournament completely")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        # Reset everything
        data = DEFAULT_DATA.copy()
        save_data(data)
        await interaction.response.send_message("🔄 Tournament has been fully reset.")

    @tree.command(name="testtournament", description="Start a quick test tournament (10s per match)")
    @app_commands.describe(title="Name of the tournament")
    async def testtournament(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await start_test_tournament(interaction, title)