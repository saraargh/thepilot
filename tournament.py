import discord
from discord import app_commands
import requests
import base64
import json
import os
import random

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

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def start_match(interaction: discord.Interaction, a_item, b_item):
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

    async def run_next_round(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        if not data["current_round"]:
            await interaction.response.send_message("❌ Current round is empty.", ephemeral=True)
            return

        # Pop first two items for this match
        if len(data["current_round"]) < 2:
            await interaction.response.send_message("❌ Not enough items for a match.", ephemeral=True)
            return

        a_item = data["current_round"].pop(0)
        b_item = data["current_round"].pop(0)
        winner = await start_match(interaction, a_item, b_item)

        data["next_round"].append(winner)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        save_data(data, sha)

        # Notify previous match winner if exists
        if data.get("last_winner"):
            await interaction.channel.send(f"✅ Last match winner: {data['last_winner']}")

        # If current round is empty, promote next_round
        if not data["current_round"]:
            if len(data["next_round"]) > 1:
                data["current_round"] = data["next_round"].copy()
                data["next_round"] = []
                save_data(data, sha)
                await interaction.channel.send(f"➡️ Round complete! Next round ready with {len(data['current_round'])} items.")
            else:
                # Tournament over
                data["running"] = False
                await interaction.channel.send(f"🎉 **{data['next_round'][0]}** wins the **{data['title']}**!")
                data["current_round"] = []
                data["next_round"] = []
                data["scores"] = {}
                data["title"] = ""
                data["last_winner"] = None
                save_data(data, sha)

    # ------------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        data, sha = load_data()
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running!", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Need at least 2 items to start!", ephemeral=True)
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even to start!", ephemeral=True)
            return

        title_text = f"Landing Strip World Cup Of {title}"
        data["title"] = title_text
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        save_data(data, sha)
        await interaction.response.send_message(f"🏁 Starting **{title_text}**!")

    @tree.command(name="addwcitem", description="Add items to the World Cup (comma separated)")
    @app_commands.describe(items="Comma separated list of items")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s) to the World Cup.")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item} from the World Cup.")
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

    @tree.command(name="resetwc", description="Reset the World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    @tree.command(name="nextwcround", description="Run the next match of the current World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_round(interaction)