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

    sha = save_data(DEFAULT_DATA.copy())
    return DEFAULT_DATA.copy(), sha


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
        return sha

    return r.json().get("content", {}).get("sha")

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def run_next_match(interaction: discord.Interaction):
        data, sha = load_data()

        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup running.", ephemeral=True)
            return

        # Tournament finished?
        if not data["current_round"]:
            winner = data["next_round"][0]
            data["last_winner"] = winner
            data["running"] = False
            save_data(data, sha)
            await interaction.response.send_message(f"🎉 **{winner}** wins the **{data['title']}**!")
            return

        items = data["current_round"]

        # Odd leftover auto-advance
        if len(items) < 2:
            data["next_round"].append(items[0])
            data["last_winner"] = items[0]
            data["current_round"] = []
            save_data(data, sha)

            await interaction.response.send_message(
                f"🏆 {items[0]} automatically moves to next round."
            )
            return

        # Do a match
        a_item, b_item = items[0], items[1]

        embed = discord.Embed(
            title=f"{data['title']}",
            description=f"🇦 {a_item}\n🇧 {b_item}"
        )

        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("🇦")
        await msg.add_reaction("🇧")

        def check(reaction, user):
            return (
                str(reaction.emoji) in ["🇦", "🇧"]
                and reaction.message.id == msg.id
                and not user.bot
            )

        votes = {"🇦": 0, "🇧": 0}

        try:
            while True:
                reaction, user = await interaction.client.wait_for(
                    "reaction_add",
                    timeout=10,
                    check=check
                )
                votes[str(reaction.emoji)] += 1

        except asyncio.TimeoutError:
            pass

        # Decide match winner
        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        data["last_winner"] = winner

        # Score update
        data["scores"][winner] = data["scores"].get(winner, 0) + 1

        # Advance winner
        data["next_round"].append(winner)
        data["current_round"] = items[2:]

        # Round done → move next_round to current_round
        if not data["current_round"]:
            data["current_round"] = data["next_round"]
            data["next_round"] = []

        save_data(data, sha)

        await interaction.channel.send(f"🏆 **{winner}** wins this matchup!")

    # ------------------- Commands -------------------

    @tree.command(name="startwc", description="Start the World Cup of something")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()

        # 🔥 BLOCK IF ODD NUMBER OF ITEMS
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message(
                f"❌ You must have an **even number** of items to start.\n"
                f"Current count: **{len(data['items'])}**",
                ephemeral=True
            )
            return

        if not data["items"]:
            await interaction.response.send_message("❌ No items added yet.", ephemeral=True)
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

    @tree.command(name="addwcitem", description="Add multiple items (comma separated)")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        data, sha = load_data()

        added = []
        for item in [i.strip() for i in items.split(",") if i.strip()]:
            if item not in data["items"]:
                data["items"].append(item)
                data["scores"][item] = 0
                added.append(item)

        save_data(data, sha)

        await interaction.response.send_message(f"✅ Added: {', '.join(added)}")

    @tree.command(name="removewcitem", description="Remove multiple items (comma separated)")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=True)
            return

        data, sha = load_data()

        removed = []
        for item in [i.strip() for i in items.split(",") if i.strip()]:
            if item in data["items"]:
                data["items"].remove(item)
                data["scores"].pop(item, None)
                removed.append(item)

        save_data(data, sha)

        if removed:
            await interaction.response.send_message(f"🗑 Removed: {', '.join(removed)}")
        else:
            await interaction.response.send_message("❌ No matching items found.")

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()

        if not data["items"]:
            await interaction.response.send_message("No items added.", ephemeral=True)
            return

        msg = "📋 **World Cup Items:**\n" + "\n".join(data["items"])
        await interaction.response.send_message(msg)

    @tree.command(name="scoreboard", description="Show the scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()

        if not data["scores"]:
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return

        msg = "📊 **Scoreboard:**\n"
        for item, score in data["scores"].items():
            msg += f"{item}: {score}\n"

        await interaction.response.send_message(msg)

    @tree.command(name="lastwinner", description="Show the last match winner")
    async def lastwinner(interaction: discord.Interaction):
        data, _ = load_data()

        if not data["last_winner"]:
            await interaction.response.send_message("No match played yet.", ephemeral=True)
            return

        await interaction.response.send_message(f"🏆 Last winner: **{data['last_winner']}**")

    @tree.command(name="resetwc", description="Reset the entire World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return

        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)

        await interaction.response.send_message("🔄 World Cup reset.")

    @tree.command(name="nextwcround", description="Run the next match")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_match(interaction)