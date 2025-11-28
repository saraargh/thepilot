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
        sha = save_data(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy(), sha

def save_data(data, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    encoded_content = base64.b64encode(json.dumps(data, indent=4).encode()).decode()
    payload = {
        "message": "Update tournament data",
        "content": encoded_content,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=HEADERS, data=json.dumps(payload))
    if r.status_code not in [200, 201]:
        print(f"GitHub save error: {r.status_code} {r.text}")
        return sha
    return r.json()["content"]["sha"]

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def run_next_match(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["current_round"] or not data["running"]:
            await interaction.response.send_message("❌ No active tournament. Start one with /startwc.", ephemeral=True)
            return

        last_winner_msg = f"🏆 Last winner: {data['last_winner']}" if data["last_winner"] else "No matches yet."
        await interaction.channel.send(last_winner_msg)

        items = data["current_round"]
        if len(items) == 1:
            winner = items[0]
            await interaction.channel.send(f"🎉 **{winner}** wins the **{data['title']}**!")
            data["running"] = False
            data["current_round"] = []
            data["last_winner"] = winner
            sha = save_data(data, sha)
            await interaction.response.send_message("Tournament completed!")
            return

        a_item, b_item = items[0], items[1]

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
        except Exception:
            pass

        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        data["scores"][winner] = data["scores"].get(winner, 0) + 1
        data["last_winner"] = winner
        data["current_round"] = items[2:] + [winner]  # winner advances
        sha = save_data(data, sha)

        await interaction.channel.send(f"🏆 {winner} wins this matchup!")

    # ------------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["items"]:
            await interaction.response.send_message("❌ No items added yet!", ephemeral=True)
            return
        title_text = f"Landing Strip World Cup Of {title}"
        data["title"] = title_text
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        sha = save_data(data, sha)
        await interaction.response.send_message(f"🏁 Starting **{title_text}**!")

    @tree.command(name="addwcitem", description="Add one or more items to the World Cup (comma separated)")
    @app_commands.describe(items="The items to add, separated by commas")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        new_items = [item.strip() for item in items.split(",") if item.strip()]
        if not new_items:
            await interaction.response.send_message("❌ No valid items provided.", ephemeral=True)
            return
        data, sha = load_data()
        for item in new_items:
            if item not in data["items"]:
                data["items"].append(item)
                data["scores"][item] = 0
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Added: {', '.join(new_items)}")

    @tree.command(name="removewcitem", description="Remove one or more items from the World Cup (comma separated)")
    @app_commands.describe(items="The items to remove, separated by commas")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        remove_items = [item.strip() for item in items.split(",") if item.strip()]
        data, sha = load_data()
        removed = []
        for item in remove_items:
            if item in data["items"]:
                data["items"].remove(item)
                data["scores"].pop(item, None)
                removed.append(item)
        sha = save_data(data, sha)
        if removed:
            await interaction.response.send_message(f"✅ Removed: {', '.join(removed)}")
        else:
            await interaction.response.send_message("❌ No items were removed.")

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

    @tree.command(name="resetwc", description="Reset the World Cup (clears all items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        sha = save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    @tree.command(name="nextwcround", description="Run the next match of the current World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_match(interaction)