# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import json
import os
import random

TOURNAMENT_FILE = "tournament_data.json"

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

def load_data():
    if os.path.exists(TOURNAMENT_FILE):
        with open(TOURNAMENT_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_DATA.copy()

def save_data(data):
    with open(TOURNAMENT_FILE, "w") as f:
        json.dump(data, f, indent=2)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):
    data = load_data()

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    # -------------------- Item Management --------------------
    @tree.command(name="addwcitem", description="Add an item to the tournament")
    @app_commands.describe(item="Name of the item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added `{item}` to the tournament.")

    @tree.command(name="removewcitem", description="Remove an item from the tournament")
    @app_commands.describe(item="Name of the item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed `{item}` from the tournament.")
        else:
            await interaction.response.send_message(f"⚠️ `{item}` not found in the tournament.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all tournament items")
    async def listwcitems(interaction: discord.Interaction):
        if data["items"]:
            await interaction.response.send_message("📋 Tournament items:\n" + "\n".join(data["items"]))
        else:
            await interaction.response.send_message("No items in the tournament yet.")

    # -------------------- Reset --------------------
    @tree.command(name="resetwc", description="Reset the tournament")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        for key in DEFAULT_DATA:
            data[key] = DEFAULT_DATA[key] if key != "items" else data["items"]
        save_data(data)
        await interaction.response.send_message("✅ Tournament reset (items kept).")

    # -------------------- Start Tournament --------------------
    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="Tournament title", test="Enable test mode (quick voting)")
    async def startwc(interaction: discord.Interaction, title: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("⚠️ Need at least 2 items to start.")
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Cannot start tournament with odd number of items.")
            return

        data["running"] = True
        data["title"] = f"Landing Strip World Cup Of {title}"
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["test_mode"] = test
        save_data(data)

        await interaction.response.send_message(f"🏆 Tournament **{data['title']}** started! Test mode: {test}")

        await run_round(interaction.channel)

    # -------------------- Round Logic --------------------
    async def run_round(channel: discord.TextChannel):
        while len(data["current_round"]) > 1:
            random.shuffle(data["current_round"])
            pairs = [data["current_round"][i:i + 2] for i in range(0, len(data["current_round"]), 2)]
            data["next_round"] = []
            save_data(data)

            for pair in pairs:
                if len(pair) < 2:
                    data["next_round"].append(pair[0])
                    continue

                winner = await run_vote(channel, pair)
                data["next_round"].append(winner)
                save_data(data)

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            save_data(data)

        # Tournament finished
        winner = data["current_round"][0]
        await channel.send(f"🏆 **{winner}** wins **{data['title']}**! 🎉")
        # Winner GIF
        await channel.send("https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif")
        data["running"] = False
        save_data(data)

    # -------------------- Voting Logic --------------------
    async def run_vote(channel: discord.TextChannel, pair):
        item_a, item_b = pair
        embed = discord.Embed(title=f"Vote: {item_a} vs {item_b}")
        msg = await channel.send(embed=embed)
        await msg.add_reaction("🇦")
        await msg.add_reaction("🇧")

        if data["test_mode"]:
            # Auto-select randomly after 10 seconds
            await asyncio.sleep(10)
            winner = random.choice(pair)
            await channel.send(f"🧪 Test mode: **{winner}** wins this matchup!")
            return winner
        else:
            # Real mode: wait for reactions (60 seconds)
            def check(reaction, user):
                return str(reaction.emoji) in ["🇦", "🇧"] and not user.bot and reaction.message.id == msg.id

            votes = {item_a: 0, item_b: 0}
            try:
                while sum(votes.values()) < 1:  # Wait for at least one vote
                    reaction, user = await interaction.client.wait_for("reaction_add", timeout=60.0, check=check)
                    if str(reaction.emoji) == "🇦":
                        votes[item_a] += 1
                    elif str(reaction.emoji) == "🇧":
                        votes[item_b] += 1
            except asyncio.TimeoutError:
                # If no votes, pick randomly
                winner = random.choice(pair)
                await channel.send(f"⏱️ Timeout! **{winner}** wins this matchup randomly.")
                return winner

            winner = item_a if votes[item_a] >= votes[item_b] else item_b
            await channel.send(f"**{winner}** wins this matchup!")
            return winner

    # -------------------- Scoreboard --------------------
    @tree.command(name="wcscoreboard", description="View the current tournament scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        if not data["scores"]:
            await interaction.response.send_message("No scores yet.")
            return
        msg = "\n".join([f"{item}: {score}" for item, score in data["scores"].items()])
        await interaction.response.send_message(f"📊 **Scoreboard:**\n{msg}")