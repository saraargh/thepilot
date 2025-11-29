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

DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None
}

# ------------------- Roles -------------------
DEFAULT_ALLOWED_ROLES = [
    1420817462290681936,
    1413545658006110401,
    1404105470204969000,
    1404098545006546954
]

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
        print("Exception in load_data:", e)
        sha = save_data(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy(), sha

def save_data(data, sha=None):
    try:
        payload = {
            "message": "Update tournament data",
            "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode()
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload))
        if r.status_code in (200, 201):
            new_sha = r.json().get("content", {}).get("sha")
            return new_sha
        return sha
    except Exception as e:
        print("Exception in save_data:", e)
        return sha

# ------------------- Bot -------------------
intents = discord.Intents.default()
intents.members = True

class TournamentBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

client = TournamentBot()

# ------------------- Helper Functions -------------------
def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or DEFAULT_ALLOWED_ROLES
    return any(role.id in allowed_roles for role in member.roles)

def get_round_name(length):
    if length == 32: return "Round of 32"
    if length == 16: return "Round of 16"
    if length == 8: return "Quarterfinals"
    if length == 4: return "Semifinals"
    if length == 2: return "Finals"
    return f"{length}-item round"

# ------------------- Tournament Commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids=DEFAULT_ALLOWED_ROLES):

    # ---------- Start WC ----------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running!", ephemeral=True)
            return
        if len(data["items"]) < 32:
            await interaction.response.send_message("❌ You must have at least 32 items to start!", ephemeral=True)
            return

        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        sha = save_data(data, sha)

        await interaction.channel.send(f"@everyone 🎉 The World Cup of **{title}** is starting! 🎉")
        await asyncio.sleep(1)

        # show first matchup
        await run_next_matchup(interaction)

    # ---------- Add WC Item ----------
    @tree.command(name="addwcitem", description="Add one or multiple items (comma-separated) to the World Cup")
    @app_commands.describe(item="Comma-separated list of items")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [x.strip() for x in item.split(",") if x.strip()]
        data["items"].extend(new_items)
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Added items: {', '.join(new_items)}")

    # ---------- Remove WC Item ----------
    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            sha = save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}")
        else:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)

    # ---------- List WC Items ----------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 World Cup Items:\n" + "\n".join(data["items"]))

    # ---------- Next WC Round ----------
    @tree.command(name="nextwcround", description="Run the next matchup of the World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_matchup(interaction)

    # ---------- Show Matchups ----------
    @tree.command(name="showwcmatchup", description="Show the current matchups")
    async def showwcmatchup(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup is currently running.", ephemeral=True)
            return
        matches = []
        items = data["current_round"]
        for i in range(0, len(items), 2):
            a = items[i]
            b = items[i+1] if i+1 < len(items) else "(bye)"
            matches.append(f"🔴 {a} vs 🔵 {b}")
        embed = discord.Embed(title=f"Matchups for {data['title']}", description="\n".join(matches))
        await interaction.response.send_message(embed=embed)

    # ---------- WC Scoreboard ----------
    @tree.command(name="wcscoreboard", description="Show the World Cup scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["scores"]:
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Scoreboard for {data['title']}", color=discord.Color.blue())
        for item, score in data["scores"].items():
            embed.add_field(name=item, value=f"{score} points", inline=True)
        await interaction.response.send_message(embed=embed)

    # ---------- End WC ----------
    @tree.command(name="endwc", description="Announce the winner after the final vote")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"] or not data["last_winner"]:
            await interaction.response.send_message("❌ No completed World Cup to announce.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🏆 World Cup of {data['title']} Winner!",
            description=f"🎉 Congratulations to **{data['last_winner']}**! Thank you everyone for voting! 🎉",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
        await interaction.channel.send(f"@everyone, we have a world cup of {data['title']} winner!")
        await interaction.channel.send(embed=embed)
        data["running"] = False
        sha = save_data(data, sha)

    # ---------- WC Help ----------
    @tree.command(name="wchelp", description="Show World Cup instructions")
    async def wchelp(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        embed = discord.Embed(title="🏆 World Cup Commands", color=discord.Color.gold())
        embed.add_field(name="/startwc", value="Start the World Cup", inline=False)
        embed.add_field(name="/addwcitem", value="Add items (comma-separated)", inline=False)
        embed.add_field(name="/removewcitem", value="Remove an item", inline=False)
        embed.add_field(name="/listwcitems", value="List all items", inline=False)
        embed.add_field(name="/nextwcround", value="Run the next matchup", inline=False)
        embed.add_field(name="/showwcmatchup", value="Show current matchups", inline=False)
        embed.add_field(name="/wcscoreboard", value="Show the scoreboard", inline=False)
        embed.add_field(name="/resetwc", value="Reset the World Cup", inline=False)
        embed.add_field(name="/endwc", value="Announce the final winner", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ------------------- Matchup Logic -------------------
async def run_next_matchup(interaction: discord.Interaction):
    data, sha = load_data()
    if not data["running"]:
        await interaction.response.send_message("❌ No World Cup is currently running.", ephemeral=True)
        return

    items = data["current_round"]
    if len(items) < 2:
        await interaction.response.send_message("❌ Not enough items for a matchup.", ephemeral=True)
        return

    a_item = items.pop(0)
    b_item = items.pop(0)
    data["current_round"] = items
    data["next_round"].append(a_item)  # temporarily store winner later

    sha = save_data(data, sha)

    embed = discord.Embed(
        title=f"🏆 Next Matchup for {data['title']}",
        description=f"🔴 {a_item} vs 🔵 {b_item}",
        color=discord.Color.orange()
    )
    msg = await interaction.channel.send(f"@everyone, the next world cup of {data['title']} fixture is upon us! 🗳️", embed=embed)
    await msg.add_reaction("🔴")
    await msg.add_reaction("🔵")

    # Collect reactions
    votes = {}
    def check(reaction, user):
        return str(reaction.emoji) in ["🔴","🔵"] and not user.bot

    try:
        while True:
            reaction, user = await interaction.client.wait_for("reaction_add", timeout=20.0, check=check)
            # enforce one vote
            votes[user.id] = str(reaction.emoji)
            # optionally edit the embed to show voters (not implemented here)
    except asyncio.TimeoutError:
        pass

    winner = a_item if votes.get(a_item, "🔴") else b_item  # simplified, you can make better
    data["next_round"].append(winner)
    data["last_winner"] = winner
    sha = save_data(data, sha)

    await interaction.channel.send(f"🏆 **{winner}** wins this matchup! Use /nextwcround to continue.")

# ------------------- Register Commands -------------------
@client.event
async def on_ready():
    setup_tournament_commands(client.tree)
    await client.tree.sync()
    print(f"Logged in as {client.user}")

# ------------------- Run -------------------
TOKEN = os.getenv("TOKEN")
client.run(TOKEN)
