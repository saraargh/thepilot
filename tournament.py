import discord
from discord import app_commands
import json
import os
import asyncio
import random

# ------------------- CONFIG -------------------
TOURNAMENT_JSON = "/mnt/data/tournament_data.json"
DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "test_mode": False
}

# ------------------- JSON Helpers -------------------
def ensure_json():
    """Ensure the JSON file exists; create if missing."""
    os.makedirs(os.path.dirname(TOURNAMENT_JSON), exist_ok=True)
    if not os.path.exists(TOURNAMENT_JSON):
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

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def start_match(interaction: discord.Interaction, a_item, b_item):
        """Send the matchup and collect votes."""
        embed = discord.Embed(
            title="Vote for the winner!",
            description=f"🇦 {a_item}\n🇧 {b_item}"
        )
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("🇦")
        await msg.add_reaction("🇧")

        def check(reaction, user):
            return str(reaction.emoji) in ["🇦", "🇧"] and not user.bot

        votes = {"🇦": 0, "🇧": 0}
        timeout = 10 if load_data().get("test_mode") else 86400  # 10s for test, 24h normal

        try:
            while True:
                reaction, user = await interaction.client.wait_for(
                    "reaction_add", timeout=timeout, check=check
                )
                votes[str(reaction.emoji)] += 1
        except asyncio.TimeoutError:
            pass

        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        await interaction.channel.send(f"🏆 {winner} wins this match up!")
        return winner

    async def run_tournament(interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("❌ No items in the World Cup!", ephemeral=True)
            return

        title = data.get("title") or "Landing Strip World Cup"
        await interaction.response.send_message(f"🏁 Starting **{title}**!")

        round_items = data["items"].copy()
        random.shuffle(round_items)
        data["current_round"] = round_items
        data["next_round"] = []
        data["scores"] = {item: 0 for item in round_items}
        data["running"] = True
        save_data(data)

        while len(data["current_round"]) > 1:
            next_round = []
            items = data["current_round"]
            for i in range(0, len(items), 2):
                if i + 1 < len(items):
                    winner = await start_match(interaction, items[i], items[i + 1])
                    next_round.append(winner)
                    data["scores"][winner] += 1
                else:
                    # Odd item advances automatically
                    next_round.append(items[i])
                    data["scores"][items[i]] += 1
                    await interaction.channel.send(f"{items[i]} automatically advances due to odd number of items.")
            data["current_round"] = next_round
            save_data(data)

        winner = data["current_round"][0]
        await interaction.channel.send(f"🎉 **{winner}** wins the **{title}**!")
        data["running"] = False
        save_data(data)

    # ------------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        data = load_data()
        data["title"] = f"Landing Strip World Cup Of {title}"
        save_data(data)
        await run_tournament(interaction)

    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added {item} to the World Cup.")

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
            await interaction.response.send_message(f"✅ Removed {item} from the World Cup.")
        else:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        items = data["items"]
        if not items:
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 World Cup Items:\n" + "\n".join(items))

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        msg = "📊 **Scoreboard:**\n"
        for item, score in scores.items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)

    @tree.command(name="resetwc", description="Reset the World Cup (clears all items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")