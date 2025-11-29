import discord
from discord import app_commands
import random
import os
import json
import base64
import requests
import asyncio

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Allowed Roles -------------------
DEFAULT_ALLOWED_ROLES = [
    1413545658006110401,  # William/Admin
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ------------------- Default JSON -------------------
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
            if "items" not in data:
                data = DEFAULT_DATA.copy()
            return data, sha
        elif r.status_code == 404:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
        else:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
    except Exception as e:
        print("🔴 Exception in load_data:", e)
        sha = save_data(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy(), sha

def save_data(data, sha=None):
    try:
        payload = {
            "message": "Update tournament_data.json",
            "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode()
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload))
        if r.status_code in (200, 201):
            new_sha = r.json().get("content", {}).get("sha")
            return new_sha
        else:
            return sha
    except Exception as e:
        print("🔴 Exception in save_data:", e)
        return sha

# ------------------- Helper Functions -------------------
def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or DEFAULT_ALLOWED_ROLES
    return any(role.id in allowed_roles for role in member.roles)

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def get_round_name(remaining):
    if remaining == 32:
        return "Round of 32"
    elif remaining == 16:
        return "Round of 16"
    elif remaining == 8:
        return "Quarter Finals"
    elif remaining == 4:
        return "Semi Finals"
    elif remaining == 2:
        return "Final"
    else:
        return "Unknown Round"

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    allowed_role_ids = allowed_role_ids or DEFAULT_ALLOWED_ROLES
    voting_sessions = {}  # Track votes per message {message_id: {user_id: choice}}

    def can_use(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def start_match(interaction: discord.Interaction, a_item, b_item, title, final=False):
        embed = discord.Embed(
            title=f"🗳️ Vote for the winner! {'🏆 Final!' if final else ''}",
            description=f"🔴 {a_item}\n🔵 {b_item}",
            color=discord.Color.random()
        )
        msg = await interaction.channel.send(f"@everyone, {'the world cup of ' + title + ' final is upon us!' if final else 'the next world cup of ' + title + ' fixture is upon us! 🗳️'}", embed=embed)
        await msg.add_reaction("🔴")
        await msg.add_reaction("🔵")

        votes = {"🔴": None, "🔵": None}  # track one vote per user

        def check(reaction, user):
            return str(reaction.emoji) in ["🔴", "🔵"] and not user.bot and user.id not in votes.values()

        # Wait for 15 seconds for demo (replace with longer if needed)
        try:
            while True:
                reaction, user = await interaction.client.wait_for("reaction_add", timeout=15)
                if str(reaction.emoji) in ["🔴", "🔵"]:
                    # Remove previous vote
                    for r in votes:
                        if votes[r] == user.id and r != str(reaction.emoji):
                            votes[r] = None
                    votes[str(reaction.emoji)] = user.id
        except asyncio.TimeoutError:
            pass

        count_a = 1 if votes["🔴"] else 0
        count_b = 1 if votes["🔵"] else 0
        winner = a_item if count_a >= count_b else b_item
        await interaction.channel.send(f"🏆 {winner} wins this matchup!")
        return winner

    async def run_next_match(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"] or not data["current_round"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        items = data["current_round"]
        if len(items) < 2:
            await interaction.response.send_message("❌ Not enough items for a match.", ephemeral=True)
            return

        a_item = items.pop(0)
        b_item = items.pop(0)
        final = len(items) == 0 and len(data["next_round"]) == 1
        winner = await start_match(interaction, a_item, b_item, data["title"], final=final)

        data["next_round"].append(winner)
        data["last_winner"] = winner
        data["current_round"] = items
        # Auto advance round if current round empty
        if not data["current_round"]:
            data["current_round"] = data["next_round"]
            data["next_round"] = []
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Match complete! {winner} won. Use `/nextwcround` for the next match.", ephemeral=True)

    # ------------------- Commands -------------------
    @tree.command(name="addwcitem", description="Add one or more items (comma separated)")
    @app_commands.describe(items="Comma separated list of items")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added items: {', '.join(new_items)}")

    @tree.command(name="removewcitem", description="Remove an item")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}")
        else:
            await interaction.response.send_message(f"❌ Item not found")

    @tree.command(name="listwcitems", description="List all World Cup items")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 Items:\n" + "\n".join(data["items"]))

    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="World Cup title")
    async def startwc(interaction: discord.Interaction, title: str):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running!", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Add at least 2 items to start.", ephemeral=True)
            return
        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        save_data(data, sha)
        await interaction.channel.send(f"@everyone 🎉 The World Cup of **{title}** is starting! 🎉")
        await interaction.channel.send("📋 First matchups coming up!")

    @tree.command(name="nextwcround", description="Run the next match of the World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_match(interaction)

    @tree.command(name="endwc", description="Announce the World Cup winner")
    async def endwc(interaction: discord.Interaction):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"] or not data["last_winner"]:
            await interaction.response.send_message("❌ No World Cup in progress.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🏆 World Cup Winner: {data['last_winner']} 🏆",
            description=f"Thank you all for voting! Use `/resetwc` to reset the tournament.",
            color=discord.Color.gold()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
        await interaction.channel.send(f"@everyone 🎉 We have a World Cup of {data['title']} winner!", embed=embed)
        data["running"] = False
        save_data(data, sha)

    @tree.command(name="wcscoreboard", description="Show the World Cup scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📊 {data['title']} Scoreboard", color=discord.Color.blue())
        for item, score in scores.items():
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed)

    @tree.command(name="showwcmatchup", description="Show the next World Cup matchup")
    async def showwcmatchup(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["current_round"]:
            await interaction.response.send_message("No current matchup.", ephemeral=True)
            return
        next_items = data["current_round"][:2]
        await interaction.response.send_message("Next matchup: " + " vs ".join(next_items))

    @tree.command(name="resetwc", description="Reset World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. Add new items to start again.")

    @tree.command(name="wchelp", description="Show World Cup help")
    async def wchelp(interaction: discord.Interaction):
        if not can_use(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎉 World Cup Commands",
            description=(
                "🟢 /addwcitem [item1, item2,...] – Add one or more items\n"
                "🔴 /removewcitem [item] – Remove a single item\n"
                "📋 /listwcitems – List all items\n"
                "🏁 /startwc [title] – Start the World Cup\n"
                "🗳️ /nextwcround – Run the next match\n"
                "👀 /showwcmatchup – Show the next matchup\n"
                "📊 /wcscoreboard – View the scoreboard\n"
                "🏆 /endwc – Announce winner (does not reset)\n"
                "🔄 /resetwc – Reset all items and scores"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)