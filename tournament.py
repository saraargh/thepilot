import discord
from discord import app_commands
import os
import requests
import base64
import json
import random
import asyncio

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Roles -------------------
DEFAULT_ALLOWED_ROLES = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ------------------- Default JSON structure -------------------
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
def _gh_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

def load_data():
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            data = json.loads(raw) if raw.strip() else DEFAULT_DATA.copy()
            sha = content.get("sha")
            return data, sha
        elif r.status_code == 404:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
        else:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
    except Exception as e:
        sha = save_data(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy(), sha

def save_data(data, sha=None):
    payload = {
        "message": "Update tournament data",
        "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode()
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload))
    if r.status_code in (200, 201):
        return r.json().get("content", {}).get("sha")
    return sha

# ------------------- Helper Functions -------------------
def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or DEFAULT_ALLOWED_ROLES
    return any(role.id in allowed_roles for role in member.roles)

# ------------------- Tournament Commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    allowed_role_ids = allowed_role_ids or DEFAULT_ALLOWED_ROLES

    def can_use(member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def start_next_match(interaction: discord.Interaction):
        data, sha = load_data()

        if not data["running"] or not data["current_round"]:
            await interaction.response.send_message("❌ No active World Cup or no current round.", ephemeral=True)
            return

        items = data["current_round"]

        # Check if only one item left → tournament complete
        if len(items) == 1:
            await interaction.response.send_message(f"🏆 **{items[0]}** has already won the **{data['title']}**!")
            data["running"] = False
            save_data(data, sha)
            return

        # Take the first two for the matchup
        a_item = items.pop(0)
        b_item = items.pop(0)
        data["current_round"] = items
        save_data(data, sha)

        # Send matchup embed
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
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        save_data(data, sha)

        await interaction.channel.send(f"🏆 **{winner}** wins this matchup!")

        # If no more matches in current round, promote next_round to current_round
        if not data["current_round"]:
            data["current_round"] = data["next_round"]
            data["next_round"] = []
            save_data(data, sha)
            if len(data["current_round"]) == 1:
                winner = data["current_round"][0]
                data["running"] = False
                save_data(data, sha)
                await interaction.channel.send(f"🎉 **{winner}** wins the **{data['title']}**!")

    # ---------------- /addwcitem ----------------
    @tree.command(name="addwcitem", description="Add items to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        for item in [i.strip() for i in items.split(",") if i.strip()]:
            if item not in data["items"]:
                data["items"].append(item)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added items: {items}")

    # ---------------- /removewcitem ----------------
    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}")
        else:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)

    # ---------------- /listwcitems ----------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 Items:\n" + "\n".join(data["items"]))

    # ---------------- /startwc ----------------
    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="Title of the World Cup")
    async def startwc(interaction: discord.Interaction, title: str):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running!", ephemeral=True)
            return
        if not data["items"]:
            await interaction.response.send_message("❌ No items added yet!", ephemeral=True)
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Cannot start with an odd number of items!", ephemeral=True)
            return
        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        save_data(data, sha)
        await interaction.response.send_message(f"🏁 Started **{title}** World Cup!")

    # ---------------- /nextwcround ----------------
    @tree.command(name="nextwcround", description="Run the next match of the World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await start_next_match(interaction)

    # ---------------- /scoreboard ----------------
    @tree.command(name="scoreboard", description="Show tournament scores")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["scores"]:
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return
        msg = "📊 **Scoreboard:**\n"
        for item, score in data["scores"].items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)

    # ---------------- /resetwc ----------------
    @tree.command(name="resetwc", description="Reset the World Cup (clears all items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        _, sha = load_data()
        data = DEFAULT_DATA.copy()
        save_data(data, sha)
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")