# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import json
import os

TOURNAMENT_JSON = "tournament_data.json"

def load_data():
    if not os.path.exists(TOURNAMENT_JSON):
        with open(TOURNAMENT_JSON, "w") as f:
            json.dump({
                "items": [],
                "current_round": [],
                "next_round": [],
                "scores": {},
                "running": False,
                "title": "",
                "test_mode": False
            }, f)
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=4)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    async def run_round(channel, data, test_mode=False):
        current = data["current_round"]
        next_round = []

        while len(current) > 1:
            round_pairs = [current[i:i+2] for i in range(0, len(current), 2)]
            for pair in round_pairs:
                if len(pair) < 2:
                    next_round.append(pair[0])
                    continue

                embed = discord.Embed(title=f"Vote for your favorite", description=f"A: {pair[0]} vs B: {pair[1]}")
                message = await channel.send(embed=embed)
                await message.add_reaction("🇦")
                await message.add_reaction("🇧")

                if test_mode:
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(86400)

                message = await channel.fetch_message(message.id)
                a_votes = sum(reaction.count - 1 for reaction in message.reactions if str(reaction.emoji) == "🇦")
                b_votes = sum(reaction.count - 1 for reaction in message.reactions if str(reaction.emoji) == "🇧")

                winner = pair[0] if a_votes >= b_votes else pair[1]
                next_round.append(winner)
                data["scores"][winner] = data["scores"].get(winner, 0) + 1
                save_data(data)

            current = next_round
            data["current_round"] = current
            data["next_round"] = []
            save_data(data)
            next_round = []

        winner = current[0]
        embed = discord.Embed(title=f"🏆 {data['title']} Winner!", description=f"The champion is **{winner}**!")
        embed.set_image(url="YOUR_WINNER_GIF_URL_HERE")
        await channel.send(embed=embed)
        data["running"] = False
        save_data(data)

    @tree.command(name="addwcitem", description="Add an item to the world cup")
    @app_commands.describe(item="Item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added item: {item}")

    @tree.command(name="removewcitem", description="Remove an item from the world cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed item: {item}")
        else:
            await interaction.response.send_message(f"❌ Item not found: {item}")

    @tree.command(name="listwcitems", description="List current world cup items")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        items = data["items"]
        if items:
            await interaction.response.send_message("\n".join(items))
        else:
            await interaction.response.send_message("No items added yet.")

    @tree.command(name="startwc", description="Start the Landing Strip World Cup")
    @app_commands.describe(title="Custom World Cup title", test="Test mode? (10 sec rounds)")
    async def startwc(interaction: discord.Interaction, title: str, test: bool=False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Not enough items to start a tournament.")
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even to start.")
            return
        data["current_round"] = data["items"][:]
        data["next_round"] = []
        data["scores"] = {}
        data["running"] = True
        data["title"] = f"Landing Strip World Cup Of {title}"
        data["test_mode"] = test
        save_data(data)
        await interaction.response.send_message(f"🏁 Tournament started: {data['title']}\nTest mode: {test}")
        await run_round(interaction.channel, data, test_mode=test)

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scores yet.")
            return
        text = "\n".join(f"{k}: {v}" for k, v in sorted(scores.items(), key=lambda x: x[1], reverse=True))
        await interaction.response.send_message(f"📊 Scoreboard:\n{text}")

    @tree.command(name="resetwc", description="Reset the world cup")
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
        await interaction.response.send_message("♻️ World Cup data reset.")