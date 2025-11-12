# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import json
import random
import datetime
import os
import asyncio

JSON_FILE = "tournament.json"
VOTING_DURATION = 24 * 3600  # seconds (24h) default

# Load / Save JSON
def load_data():
    if not os.path.exists(JSON_FILE):
        with open(JSON_FILE, "w") as f:
            json.dump({"items":[],"current_round":[],"next_round":[],"scores":{},"running":False,"title":"","test_mode":False}, f)
    with open(JSON_FILE,"r") as f:
        return json.load(f)

def save_data(data):
    with open(JSON_FILE,"w") as f:
        json.dump(data,f,indent=4)

# ===== Commands Setup =====
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids=None):

    # Helper
    def user_allowed(member):
        return allowed_role_ids and any(role.id in allowed_role_ids for role in member.roles)

    # ===== Add / Remove / List Items =====
    @tree.command(name="addwcitem", description="Add an item to the tournament")
    @app_commands.describe(item="Name of the item")
    async def addwcitem(interaction: discord.Interaction, item: str):
        data = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ Tournament is running, cannot add items.", ephemeral=True)
            return
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added `{item}` to the tournament.")

    @tree.command(name="removewcitem", description="Remove an item from the tournament")
    @app_commands.describe(item="Name of the item")
    async def removewcitem(interaction: discord.Interaction, item: str):
        data = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ Tournament is running, cannot remove items.", ephemeral=True)
            return
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed `{item}` from the tournament.")
        else:
            await interaction.response.send_message(f"❌ `{item}` not found.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all items in the tournament")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        items = data["items"]
        if not items:
            await interaction.response.send_message("⚠️ No items in the tournament yet.")
        else:
            await interaction.response.send_message("🏆 Tournament Items:\n" + "\n".join(items))

    # ===== Start Tournament =====
    @tree.command(name="startwc", description="Start the World Cup tournament")
    @app_commands.describe(title="Tournament title", test_mode="Enable short voting for testing")
    async def startwc(interaction: discord.Interaction, title: str, test_mode: bool=False):
        data = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ Tournament already running.", ephemeral=True)
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even to start.", ephemeral=True)
            return

        data["running"] = True
        data["title"] = title
        data["test_mode"] = test_mode
        data["current_round"] = data["items"][:]
        data["next_round"] = []
        data["scores"] = {item:0 for item in data["items"]}
        save_data(data)

        await interaction.response.send_message(f"🏆 **{title}** World Cup started! {'(Test mode)' if test_mode else ''}")
        asyncio.create_task(run_rounds(interaction.channel, test_mode))

    # ===== Scoreboard =====
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        if not data["scores"]:
            await interaction.response.send_message("⚠️ No scores yet.")
            return
        msg = "**🏆 Tournament Scoreboard:**\n"
        for item, score in data["scores"].items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)

# ===== Round Handling =====
async def run_rounds(channel, test_mode=False):
    data = load_data()
    round_items = data["current_round"][:]

    while len(round_items) > 1:
        next_round = []
        random.shuffle(round_items)
        for i in range(0, len(round_items), 2):
            item1 = round_items[i]
            item2 = round_items[i+1]

            # Create embed for voting
            embed = discord.Embed(
                title=f"Vote for your favorite! 🏆",
                description=f"1️⃣ {item1}\n2️⃣ {item2}\nReact with 1️⃣ or 2️⃣",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"{data['title']} World Cup")
            msg = await channel.send("@everyone", embed=embed)

            # Add reactions
            await msg.add_reaction("1️⃣")
            await msg.add_reaction("2️⃣")

            # Wait for votes
            duration = 10 if test_mode else 24*3600
            await asyncio.sleep(duration)

            # Fetch message again to count reactions
            msg = await channel.fetch_message(msg.id)
            count1 = discord.utils.get(msg.reactions, emoji="1️⃣").count - 1
            count2 = discord.utils.get(msg.reactions, emoji="2️⃣").count - 1
            winner = item1 if count1 >= count2 else item2

            # Update scores
            data = load_data()
            data["scores"][winner] += 1
            next_round.append(winner)
            save_data(data)

            await channel.send(f"✅ **{winner}** wins this match!")

        round_items = next_round
        data["current_round"] = round_items
        save_data(data)

    # Tournament finished
    winner = round_items[0]
    await channel.send(f"🏆 **{winner}** is the **{data['title']} World Cup** champion! 🎉")
    data = load_data()
    data["running"] = False
    save_data(data)