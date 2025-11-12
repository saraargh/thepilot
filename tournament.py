# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import json
import random
import os

DATA_FILE = "tournament_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"items": [], "votes": {}, "scores": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="The item to add")
    async def add_wc_item(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            await interaction.response.send_message("⚠️ Item already exists.", ephemeral=True)
            return
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added item: {item}")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="The item to remove")
    async def remove_wc_item(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item not in data["items"]:
            await interaction.response.send_message("⚠️ Item not found.", ephemeral=True)
            return
        data["items"].remove(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Removed item: {item}")

    @tree.command(name="listwcitems", description="List all World Cup items")
    async def list_wc_items(interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("⚠️ No items added yet.", ephemeral=True)
            return
        await interaction.response.send_message(f"🏆 Current items:\n" + "\n".join(f"- {i}" for i in data["items"]))

    @tree.command(name="starttournament", description="Start the World Cup tournament")
    @app_commands.describe(
        cup_name="Name of the cup (e.g., Landing Strip World Cup Of Fun)",
        test="Enable test mode with 10-second rounds"
    )
    async def start_tournament(interaction: discord.Interaction, cup_name: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        items = data.get("items", [])
        if len(items) < 2 or len(items) % 2 != 0:
            await interaction.response.send_message("⚠️ You need an even number of items (≥2) to start the tournament.", ephemeral=True)
            return

        await interaction.response.send_message(f"🏁 Starting **{cup_name}** {'in TEST mode (10s rounds)' if test else ''}!")

        scores = {item: 0 for item in items}
        round_num = 1
        current_items = items[:]
        random.shuffle(current_items)

        tournament_channel = interaction.channel

        while len(current_items) > 1:
            await tournament_channel.send(f"🔹 **Round {round_num}**")
            winners = []

            # Pair items
            pairs = [current_items[i:i+2] for i in range(0, len(current_items), 2)]

            for a, b in pairs:
                vote_msg = await tournament_channel.send(f"Vote A️⃣ for **{a}** or B️⃣ for **{b}**?")
                await vote_msg.add_reaction("🇦")
                await vote_msg.add_reaction("🇧")

                votes = {"A": 0, "B": 0}

                def check(reaction, user):
                    return reaction.message.id == vote_msg.id and str(reaction.emoji) in ["🇦","🇧"] and not user.bot

                try:
                    # Voting duration
                    vote_duration = 10 if test else 60*60*24  # 10s test, 24h normal
                    while True:
                        reaction, user = await interaction.client.wait_for("reaction_add", timeout=vote_duration, check=check)
                        if str(reaction.emoji) == "🇦":
                            votes["A"] += 1
                        else:
                            votes["B"] += 1
                except asyncio.TimeoutError:
                    # pick winner
                    winner = a if votes["A"] >= votes["B"] else b
                    scores[winner] += 1
                    winners.append(winner)
                    await tournament_channel.send(f"✅ **{winner}** wins this matchup! ({votes['A']}A / {votes['B']}B)")
                    continue

            current_items = winners
            round_num += 1

        # Tournament finished
        winner = current_items[0]
        scores[winner] += 1
        data["scores"] = scores
        save_data(data)

        winner_gif_url = "https://media.giphy.com/media/3o6Zt481isNVuQI1l6/giphy.gif"
        embed = discord.Embed(
            title=f"🏆 {winner} Wins the {cup_name}!",
            description=f"🎉 Congratulations to **{winner}** for being the champion!",
            color=discord.Color.gold()
        )
        embed.set_image(url=winner_gif_url)
        await tournament_channel.send(embed=embed)

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("⚠️ No scores yet.")
            return
        text = "\n".join(f"**{item}**: {points}" for item, points in scores.items())
        await interaction.response.send_message(f"📊 **Tournament Scoreboard:**\n{text}")