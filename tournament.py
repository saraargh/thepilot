import discord
from discord import app_commands
import requests
import base64
import json
import os
import random
import asyncio

# ------------------- GitHub Config -------------------
GITHUB_REPO = "saraargh/the-pilot"  # owner/repo
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"}

DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None
}

# ------------------- GitHub Helpers -------------------
def load_data():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        content = r.json()
        data = base64.b64decode(content["content"]).decode()
        return json.loads(data), content["sha"]
    else:
        # File missing → create it
        save_data(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy(), None

def save_data(data, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    encoded_content = base64.b64encode(json.dumps(data, indent=4).encode()).decode()
    payload = {
        "message": "Update tournament data",
        "content": encoded_content
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=HEADERS, data=json.dumps(payload))
    if r.status_code not in [200, 201]:
        print(f"GitHub save error: {r.status_code} {r.text}")
    # Return latest SHA after saving
    resp_json = r.json()
    return resp_json.get("content", {}).get("sha")

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def start_match(interaction: discord.Interaction, a_item, b_item):
        """Send matchup and collect votes"""
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

        try:
            while True:
                reaction, user = await interaction.client.wait_for(
                    "reaction_add", timeout=10, check=check
                )
                votes[str(reaction.emoji)] += 1
        except asyncio.TimeoutError:
            pass

        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        await interaction.channel.send(f"🏆 {winner} wins this matchup!")
        return winner

    async def next_match(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        if len(data["current_round"]) < 2:
            await interaction.response.send_message("❌ Not enough items for a match.", ephemeral=True)
            return

        a_item, b_item = data["current_round"][:2]
        winner = await start_match(interaction, a_item, b_item)
        data["last_winner"] = winner
        data["scores"][winner] += 1

        # Remove matched items
        data["current_round"] = data["current_round"][2:]
        data["next_round"].append(winner)
        sha = save_data(data, sha)

        # Check if round finished
        if not data["current_round"]:
            data["current_round"] = data["next_round"]
            data["next_round"] = []
            if len(data["current_round"]) == 1:
                final_winner = data["current_round"][0]
                await interaction.channel.send(f"🎉 **{final_winner}** wins the **{data['title']}**!")
                data["running"] = False
                data["current_round"] = []
                data["next_round"] = []
            sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Match recorded. Last winner: {winner}")

    # ------------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running.", ephemeral=True)
            return
        if not data["items"]:
            await interaction.response.send_message("❌ No items added yet!", ephemeral=True)
            return
        data["title"] = f"Landing Strip World Cup Of {title}"
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        sha = save_data(data, sha)
        await interaction.response.send_message(f"🏁 Starting **{data['title']}**!")

    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        for item in [i.strip() for i in items.split(",")]:
            if item and item not in data["items"]:
                data["items"].append(item)
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Added items: {items}")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            # Also remove from current/next rounds if present
            if item in data["current_round"]:
                data["current_round"].remove(item)
            if item in data["next_round"]:
                data["next_round"].remove(item)
            if item in data["scores"]:
                del data["scores"][item]
            sha = save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}")
        else:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 World Cup Items:\n" + "\n".join(data["items"]))

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        msg = "📊 **Scoreboard:**\n"
        for item, score in scores.items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)

    @tree.command(name="resetwc", description="Reset the World Cup completely")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        sha = save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    @tree.command(name="nextwc", description="Run the next match in the current World Cup")
    async def nextwc(interaction: discord.Interaction):
        await next_match(interaction)