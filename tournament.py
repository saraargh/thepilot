# tournament.py
import discord
from discord import app_commands
import json
import asyncio
import random
from typing import List

TOURNAMENT_JSON = "tournament_data.json"

def load_data():
    try:
        with open(TOURNAMENT_JSON, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "items": [],
            "current_round": [],
            "next_round": [],
            "scores": {},
            "running": False,
            "title": "",
            "test_mode": False
        }

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=4)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def run_round(interaction: discord.Interaction):
        data = load_data()
        current = data["current_round"]
        next_round = []

        # Voting for each match
        for i in range(0, len(current), 2):
            a = current[i]
            b = current[i+1]

            embed = discord.Embed(title=f"Vote: {a} vs {b}", description="React with 🇦 or 🇧 to vote!", color=0x00ff00)
            message = await interaction.channel.send(embed=embed)
            await message.add_reaction("🇦")
            await message.add_reaction("🇧")

            if data.get("test_mode", False):
                # Wait 10 seconds in test mode
                await asyncio.sleep(10)
            else:
                # Wait 24 hours in normal mode
                await asyncio.sleep(86400)

            # Fetch reactions
            message = await interaction.channel.fetch_message(message.id)
            counts = {"🇦": 0, "🇧": 0}
            for reaction in message.reactions:
                if reaction.emoji in counts:
                    counts[reaction.emoji] = reaction.count - 1  # subtract bot's own reaction

            winner = a if counts["🇦"] >= counts["🇧"] else b
            next_round.append(winner)
            await interaction.channel.send(f"✅ Winner: {winner}")

        data["current_round"] = next_round
        data["next_round"] = []
        save_data(data)

        if len(next_round) == 1:
            # Tournament complete
            embed = discord.Embed(title=f"🏆 {data['title']} Winner!", description=f"The champion is {next_round[0]}!", color=0xffd700)
            # Add GIF for winner
            embed.set_image(url="https://media.giphy.com/media/3o6ZtaO9BZHcOjmErm/giphy.gif")
            await interaction.channel.send(embed=embed)
            data["running"] = False
            save_data(data)
            return

        # Prepare next round
        data["current_round"] = next_round
        save_data(data)

    @tree.command(name="startwc", description="Start a new Landing Strip World Cup")
    @app_commands.describe(title="The name of the World Cup")
    async def startwc(interaction: discord.Interaction, title: str, test_mode: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ Tournament already running.", ephemeral=True)
            return

        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even to start.", ephemeral=True)
            return

        data["running"] = True
        data["title"] = f"Landing Strip World Cup Of {title}"
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["test_mode"] = test_mode
        # Shuffle items for initial round
        random.shuffle(data["current_round"])
        save_data(data)

        await interaction.response.send_message(f"🏁 {data['title']} started! Test mode: {test_mode}")
        await run_round(interaction)

    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="Item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            await interaction.response.send_message("⚠️ Item already in tournament.", ephemeral=True)
            return
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added: {item}")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item not in data["items"]:
            await interaction.response.send_message("⚠️ Item not found.", ephemeral=True)
            return
        data["items"].remove(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Removed: {item}")

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("⚠️ No items in the tournament yet.")
            return
        items_str = "\n".join(data["items"])
        await interaction.response.send_message(f"📋 Tournament Items:\n{items_str}")

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        if not data["scores"]:
            await interaction.response.send_message("⚠️ No scores yet.")
            return
        embed = discord.Embed(title=f"{data['title']} Scoreboard", color=0x00ff00)
        for item, score in data["scores"].items():
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed)

    @tree.command(name="resetwc", description="Reset the current World Cup tournament")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = {
            "items": [],
            "current_round": [],
            "next_round": [],
            "scores": {},
            "running": False,
            "title": "",
            "test_mode": False
        }
        save_data(data)
        await interaction.response.send_message("♻️ Tournament reset.")