import discord
from discord import app_commands
import os
import json
import base64
import requests
import random
import asyncio

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Default Data -------------------
DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None,
    "round_name": "",
    "match_history": [],
    "votes": {}
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
    except Exception:
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
    else:
        return sha

# ------------------- Tournament Commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def post_matchup(interaction, a_item, b_item, data, sha):
        """Send matchup embed and track votes"""
        embed = discord.Embed(
            title=f"🗳️ World Cup Matchup",
            description=f"🔴 {a_item}\n🔵 {b_item}",
            color=discord.Color.random()
        )
        msg = await interaction.channel.send("@everyone, the next world cup of **{}** fixture is upon us! 🗳️".format(data["title"]))
        await interaction.channel.send(embed=embed)
        await msg.add_reaction("🔴")
        await msg.add_reaction("🔵")

        # Track votes
        data["votes"][msg.id] = {"🔴": [], "🔵": []}
        save_data(data, sha)

        def check(reaction, user):
            return str(reaction.emoji) in ["🔴", "🔵"] and not user.bot

        while True:
            try:
                reaction, user = await interaction.client.wait_for(
                    "reaction_add", timeout=30, check=check
                )
                # remove other votes if user has voted
                for emoji in ["🔴", "🔵"]:
                    if user.id in data["votes"].get(msg.id, {}).get(emoji, []):
                        if str(reaction.emoji) != emoji:
                            data["votes"][msg.id][emoji].remove(user.id)
                if user.id not in data["votes"][msg.id][str(reaction.emoji)]:
                    data["votes"][msg.id][str(reaction.emoji)].append(user.id)
                # update embed with who voted
                voted_text = "\n".join([f"🔴: {len(data['votes'][msg.id]['🔴'])} votes\n🔵: {len(data['votes'][msg.id]['🔵'])} votes"])
                embed.description = f"🔴 {a_item}\n🔵 {b_item}\n\n{voted_text}"
                await msg.edit(content="@everyone, the next world cup of **{}** fixture is upon us! 🗳️".format(data["title"]), embed=embed)
                save_data(data, sha)
            except asyncio.TimeoutError:
                break

        red_votes = len(data["votes"][msg.id]["🔴"])
        blue_votes = len(data["votes"][msg.id]["🔵"])
        winner = a_item if red_votes >= blue_votes else b_item
        data["match_history"].append((a_item, b_item, winner))
        data["last_winner"] = winner
        if winner not in data["scores"]:
            data["scores"][winner] = 0
        data["scores"][winner] += 1
        save_data(data, sha)
        await interaction.channel.send(f"🏆 **{winner}** wins this matchup! Use /nextwcmatch to continue.")
        return winner

    # ------------------- /startwc -------------------
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
        if len(data["items"]) < 32:
            await interaction.response.send_message("❌ You need 32 items to start!", ephemeral=True)
            return
        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["round_name"] = "Round of 32"
        data["match_history"] = []
        data["votes"] = {}
        save_data(data, sha)
        await interaction.response.send_message(f"@everyone 🎉 The World Cup of **{title}** is starting!", ephemeral=False)
        # start first match automatically
        await nextwcmatch(interaction)

    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add items to the World Cup")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s) to the World Cup: {', '.join(new_items)}", ephemeral=False)

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item} from the World Cup.", ephemeral=False)
        else:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)

    # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup.", ephemeral=True)
            return
        await interaction.response.send_message("📋 World Cup Items:\n" + "\n".join(data["items"]), ephemeral=False)

    # ------------------- /nextwcmatch -------------------
    @tree.command(name="nextwcmatch", description="Run the next World Cup matchup")
    async def nextwcmatch(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup is active.", ephemeral=True)
            return
        if len(data["current_round"]) < 2:
            await interaction.response.send_message("❌ Not enough items for a matchup.", ephemeral=True)
            return
        a_item = data["current_round"].pop(0)
        b_item = data["current_round"].pop(0)
        save_data(data, sha)
        winner = await post_matchup(interaction, a_item, b_item, data, sha)

        # Update round names based on remaining items
        remaining = len(data["current_round"]) + len(data["next_round"]) + 1  # including this winner
        if remaining == 16:
            data["round_name"] = "Round of 16"
        elif remaining == 8:
            data["round_name"] = "Quarterfinals"
        elif remaining == 4:
            data["round_name"] = "Semifinals"
        elif remaining == 2:
            data["round_name"] = "Finals"
        save_data(data, sha)

    # ------------------- /showwcmatchup -------------------
    @tree.command(name="showwcmatchup", description="Show all remaining matchups")
    async def showwcmatchup(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup active.", ephemeral=True)
            return
        content = f"**{data['round_name']}**\nCurrent items:\n" + "\n".join(data["current_round"])
        await interaction.response.send_message(content, ephemeral=False)

    # ------------------- /wcscoreboard -------------------
    @tree.command(name="wcscoreboard", description="Show the tournament scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["scores"]:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📊 {data['title']} Scoreboard", color=discord.Color.blurple())
        for item, score in data["scores"].items():
            embed.add_field(name=item, value=f"{score} pts", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup completely")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        sha = save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup has been reset.", ephemeral=False)
