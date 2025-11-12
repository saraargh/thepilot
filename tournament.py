# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import json
import random

DATA_FILE = "tournament_data.json"

# ----- JSON helpers -----
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
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
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ----- Command setup -----
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    data = load_data()

    # ----- Add / remove / list items -----
    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
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
        try:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed `{item}` from the World Cup items.")
        except ValueError:
            await interaction.response.send_message("❌ That item is not in the World Cup list.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all World Cup items")
    async def listwcitems(interaction: discord.Interaction):
        if not data["items"]:
            await interaction.response.send_message("No items have been added yet.")
            return
        items_text = "\n".join(f"- {i}" for i in data["items"])
        await interaction.response.send_message(f"🏆 **World Cup Items:**\n{items_text}")

    # ----- Reset tournament -----
    @tree.command(name="resetwc", description="Reset the World Cup tournament")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data.update({
            "current_round": [],
            "next_round": [],
            "scores": {},
            "running": False,
            "title": "",
            "test_mode": False
        })
        save_data(data)
        await interaction.response.send_message("♻️ World Cup has been reset.")

    # ----- Start tournament -----
    @tree.command(name="startwc", description="Start the World Cup tournament")
    @app_commands.describe(title="The World Cup title", test="Run in test mode with 10s rounds")
    async def startwc(interaction: discord.Interaction, title: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Not enough items to start the tournament.", ephemeral=True)
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even.", ephemeral=True)
            return

        data["title"] = f"Landing Strip World Cup Of {title}"
        data["running"] = True
        data["test_mode"] = test
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        save_data(data)
        await interaction.response.send_message(f"🏁 Tournament started: **{data['title']}**\nTest mode: {test}")

        await run_round(interaction.channel)

    # ----- Voting / round logic -----
    async def run_round(channel: discord.TextChannel):
        while len(data["current_round"]) > 1:
            pairs = [data["current_round"][i:i+2] for i in range(0, len(data["current_round"]), 2)]
            data["next_round"] = []
            save_data(data)

            for a, b in pairs:
                embed = discord.Embed(title="Vote now!", description=f"React with 🅰️ for **{a}** or 🅱️ for **{b}**")
                msg = await channel.send(embed=embed)
                await msg.add_reaction("🅰️")
                await msg.add_reaction("🅱️")

                # Wait for votes
                duration = 10 if data["test_mode"] else 86400  # 10s for test, 24h normally
                await asyncio.sleep(duration)

                # Tally votes
                msg = await channel.fetch_message(msg.id)  # Refresh reactions
                a_votes = sum(r.count - 1 for r in msg.reactions if str(r.emoji) == "🅰️")
                b_votes = sum(r.count - 1 for r in msg.reactions if str(r.emoji) == "🅱️")
                winner = a if a_votes >= b_votes else b
                data["next_round"].append(winner)
                data["scores"][winner] += 1
                save_data(data)

                await channel.send(f"✅ {winner} wins this matchup! ({a_votes}-{b_votes})")

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            save_data(data)

        # Tournament winner
        winner = data["current_round"][0]
        embed = discord.Embed(title=f"🏆 {data['title']} Winner!", description=f"Congratulations **{winner}**!")
        embed.set_image(url="https://media.giphy.com/media/26tOZ42Mg6pbTUPHW/giphy.gif")  # Winning GIF
        await channel.send(embed=embed)

        data["running"] = False
        save_data(data)

    # ----- Scoreboard -----
    @tree.command(name="scoreboard", description="View current World Cup scores")
    async def scoreboard(interaction: discord.Interaction):
        if not data["scores"]:
            await interaction.response.send_message("No scores yet.")
            return
        scores_text = "\n".join(f"{k}: {v}" for k, v in data["scores"].items())
        await interaction.response.send_message(f"📊 **Scoreboard:**\n{scores_text}")