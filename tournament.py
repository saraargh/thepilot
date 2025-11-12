# tournament.py
import discord
from discord import app_commands
import asyncio
import json
import random
import os

TOURNAMENT_JSON = "tournament_data.json"
VOTE_EMOJIS = ["🇦", "🇧"]
WINNER_GIF_URL = "https://media.giphy.com/media/3oEjI6SIIHBdRxXI40/giphy.gif"  # replace with your GIF

# Helper functions for JSON
def load_data():
    if not os.path.exists(TOURNAMENT_JSON):
        return {
            "items": [],
            "current_round": [],
            "next_round": [],
            "scores": {},
            "running": False,
            "title": "",
            "test_mode": False
        }
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=4)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    # Add item
    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="Name of the item")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added **{item}** to the World Cup.")

    # Remove item
    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Name of the item")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed **{item}** from the World Cup.")
        else:
            await interaction.response.send_message(f"⚠️ Item **{item}** not found.", ephemeral=True)

    # List items
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.")
            return
        await interaction.response.send_message("📜 Current World Cup items:\n" + "\n".join(data["items"]))

    # Reset tournament
    @tree.command(name="resetwc", description="Reset the World Cup completely (all items cleared)")
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
        await interaction.response.send_message("♻️ Tournament fully reset. All items cleared!")

    # Start tournament
    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="Name for the World Cup", test="Use test mode (10 seconds per round)")
    async def startwc(interaction: discord.Interaction, title: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        if len(data["items"]) < 2:
            await interaction.response.send_message("⚠️ Need at least 2 items to start the World Cup.", ephemeral=True)
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("⚠️ Number of items must be even to start the tournament.", ephemeral=True)
            return

        data["running"] = True
        data["title"] = title
        data["test_mode"] = test
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        save_data(data)

        await interaction.response.send_message(f"🏆 **Landing Strip World Cup Of {title}** has started! {'(Test mode)' if test else ''}")
        await run_tournament(interaction.channel, test)

    async def run_tournament(channel: discord.TextChannel, test_mode: bool):
        data = load_data()
        while len(data["current_round"]) > 1:
            random.shuffle(data["current_round"])
            data["next_round"] = []
            save_data(data)

            for i in range(0, len(data["current_round"]), 2):
                a = data["current_round"][i]
                b = data["current_round"][i+1]

                msg = await channel.send(f"🏁 **Vote!**\n🇦 {a}\n🇧 {b}")
                await msg.add_reaction(VOTE_EMOJIS[0])
                await msg.add_reaction(VOTE_EMOJIS[1])

                # Wait for votes
                wait_time = 10 if test_mode else 86400  # 10 sec for test, 24h for real
                await asyncio.sleep(wait_time)

                msg = await channel.fetch_message(msg.id)
                a_votes = sum(r.count for r in msg.reactions if str(r.emoji) == VOTE_EMOJIS[0])
                b_votes = sum(r.count for r in msg.reactions if str(r.emoji) == VOTE_EMOJIS[1])
                winner = a if a_votes >= b_votes else b

                data["scores"][winner] += 1
                data["next_round"].append(winner)
                await channel.send(f"🎉 {winner} wins this match up!")

                save_data(data)

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            save_data(data)

        winner = data["current_round"][0]
        embed = discord.Embed(title=f"🏆 **Landing Strip World Cup Of {data['title']}** Winner!", description=f"🥇 {winner}", color=discord.Color.gold())
        embed.set_image(url=WINNER_GIF_URL)
        await channel.send(embed=embed)

        data["running"] = False
        save_data(data)

    # Scoreboard
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        if not data["scores"]:
            await interaction.response.send_message("No tournament has started yet.")
            return
        msg = "📊 **Scoreboard:**\n"
        for item, score in data["scores"].items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)