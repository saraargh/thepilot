# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import random
import asyncio

# Persistent JSON path
TOURNAMENT_JSON = "/mnt/data/tournament_data.json"

# Ensure JSON exists
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
        }, f, indent=2)

def load_data():
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=2)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    # ----- ITEM COMMANDS -----
    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            await interaction.response.send_message(f"❌ `{item}` is already in the list.", ephemeral=True)
            return
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
        if item not in data["items"]:
            await interaction.response.send_message(f"❌ `{item}` is not in the list.", ephemeral=True)
            return
        data["items"].remove(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Removed `{item}` from the World Cup items.")

    @tree.command(name="listwcitems", description="List all World Cup items")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        items = data["items"]
        if not items:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return
        item_list = "\n".join(f"{i+1}. {itm}" for i, itm in enumerate(items))
        await interaction.response.send_message(f"📜 **World Cup Items:**\n{item_list}")

    # ----- RESET TOURNAMENT -----
    @tree.command(name="resetwc", description="Reset the tournament (deletes all items, rounds, and scores)")
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
        await interaction.response.send_message("✅ Tournament reset (all data cleared).")

    # ----- START TOURNAMENT -----
    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="Name of the tournament", test="Run in test mode for 10 seconds per vote")
    async def startwc(interaction: discord.Interaction, title: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        items = data["items"].copy()

        if len(items) % 2 != 0:
            await interaction.response.send_message("❌ Cannot start tournament with an odd number of items.", ephemeral=True)
            return
        if len(items) < 2:
            await interaction.response.send_message("❌ Add at least 2 items to start the tournament.", ephemeral=True)
            return

        data["running"] = True
        data["current_round"] = items
        data["next_round"] = []
        data["scores"] = {itm: 0 for itm in items}
        data["title"] = title
        data["test_mode"] = test
        save_data(data)

        await interaction.response.send_message(f"🏆 **Landing Strip World Cup of {title}** started! Test mode: {test}")

        await run_round(interaction.channel, test=test)

    # ----- ROUND LOGIC -----
    async def run_round(channel: discord.TextChannel, test=False):
        data = load_data()
        current = data["current_round"]

        while len(current) > 1:
            next_round = []
            for i in range(0, len(current), 2):
                item_a = current[i]
                item_b = current[i+1]
                vote_msg = await channel.send(
                    f"⚔️ **Match-up:**\nA: {item_a}\nB: {item_b}\nVote with 🇦 or 🇧!"
                )
                await vote_msg.add_reaction("🇦")
                await vote_msg.add_reaction("🇧")

                # Collect votes
                votes = {"A": 0, "B": 0}

                def check(reaction, user):
                    return str(reaction.emoji) in ["🇦", "🇧"] and not user.bot and reaction.message.id == vote_msg.id

                try:
                    if test:
                        await asyncio.sleep(10)  # test mode duration
                    else:
                        await asyncio.sleep(60)  # normal voting duration
                except asyncio.TimeoutError:
                    pass

                vote_msg = await channel.fetch_message(vote_msg.id)  # refresh reactions
                for reaction in vote_msg.reactions:
                    if str(reaction.emoji) == "🇦":
                        votes["A"] = reaction.count - 1
                    elif str(reaction.emoji) == "🇧":
                        votes["B"] = reaction.count - 1

                winner = item_a if votes["A"] >= votes["B"] else item_b
                data["scores"][winner] += 1
                next_round.append(winner)
                await channel.send(f"✅ {winner} wins this match-up!")
                data["next_round"] = next_round
                save_data(data)

            current = next_round
            data["current_round"] = current
            data["next_round"] = []
            save_data(data)

        # Tournament finished
        winner = current[0]
        await channel.send(
            f"🎉 **Winner of Landing Strip World Cup of {data['title']}: {winner}!** 🏆\n"
            f"https://media.giphy.com/media/3o7TKy3kSeIYp6cOYk/giphy.gif"
        )
        data["running"] = False
        save_data(data)

    # ----- SCOREBOARD -----
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        scores = data["scores"]
        if not scores:
            await interaction.response.send_message("No tournament running.", ephemeral=True)
            return
        scoreboard_text = "\n".join(f"{item}: {score}" for item, score in scores.items())
        await interaction.response.send_message(f"📊 **Scoreboard:**\n{scoreboard_text}")