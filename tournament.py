import discord
from discord import app_commands
import requests
import base64
import json
import os
import random
import asyncio

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

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

# ------------------- Helpers -------------------
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
    except Exception:
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
            return r.json().get("content", {}).get("sha")
        return sha
    except Exception:
        return sha

def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

# ------------------- Tournament Commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    async def send_next_matchup(interaction: discord.Interaction):
        """Send the next matchup with reactions"""
        data, sha = load_data()
        if not data["current_round"]:
            await interaction.channel.send("❌ No active World Cup round. Use /startwc to begin.")
            return

        # Get next pair
        if len(data["current_round"]) < 2:
            winner = data["current_round"][0]
            embed = discord.Embed(
                title=f"🏆 World Cup Winner!",
                description=f"@everyone, we have a World Cup of {data['title']} winner!\n**{winner}** 🎉",
                color=discord.Color.gold()
            )
            embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
            await interaction.channel.send(f"@everyone, we have a world cup of {data['title']} winner!")
            await interaction.channel.send(embed=embed)
            data["running"] = False
            data["last_winner"] = winner
            save_data(data, sha)
            return

        item_a = data["current_round"].pop(0)
        item_b = data["current_round"].pop(0)

        embed = discord.Embed(
            title=f"🗳️ Vote for the winner!",
            description=f"🔴 {item_a}\n🔵 {item_b}",
            color=discord.Color.blue()
        )
        msg = await interaction.channel.send(f"@everyone, the next World Cup of {data['title']} fixture is upon us! 🗳️", embed=embed)
        await msg.add_reaction("🔴")
        await msg.add_reaction("🔵")

        votes = {}

        def check(reaction, user):
            return str(reaction.emoji) in ["🔴", "🔵"] and not user.bot

        try:
            while True:
                reaction, user = await interaction.client.wait_for("reaction_add", timeout=60*60, check=check)
                votes[user.id] = str(reaction.emoji)
                # remove previous reactions
                user_msg = await msg.channel.fetch_message(msg.id)
                for react in user_msg.reactions:
                    if react.emoji != votes[user.id]:
                        users = await react.users().flatten()
                        if user in users:
                            await user_msg.remove_reaction(react.emoji, user)
        except asyncio.TimeoutError:
            pass

        # Determine winner
        counts = {"🔴": 0, "🔵": 0}
        for v in votes.values():
            counts[v] += 1
        winner = item_a if counts["🔴"] >= counts["🔵"] else item_b
        data["next_round"].append(winner)
        data["scores"][winner] = data["scores"].get(winner, 0) + 1

        # Save data
        save_data(data, sha)
        await interaction.channel.send(f"✅ {winner} wins this matchup!")

        # If round complete, rotate rounds
        if not data["current_round"]:
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            rounds_left = len(data["current_round"])
            if rounds_left == 16:
                await interaction.channel.send(f"🎉 Round of 32 complete! We are in the Round of 16.\nContenders: {', '.join(data['current_round'])}")
            elif rounds_left == 8:
                await interaction.channel.send(f"🎉 Round of 16 complete! Quarter Finals begin.\nContenders: {', '.join(data['current_round'])}")
            elif rounds_left == 4:
                await interaction.channel.send(f"🎉 Quarter Finals complete! Semi Finals begin.\nContenders: {', '.join(data['current_round'])}")
            elif rounds_left == 2:
                await interaction.channel.send(f"🎉 Semi Finals complete! Finals begin.\nContenders: {', '.join(data['current_round'])}")

            save_data(data, sha)

    # ------------------- Commands -------------------
    @tree.command(name="addwcitem", description="Add one or multiple items to the World Cup")
    @app_commands.describe(items="Comma-separated list of items")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        for item in [i.strip() for i in items.split(",")]:
            data["items"].append(item)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {items} to the World Cup.")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user, allowed_role_ids):
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
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=False)
            return
        await interaction.response.send_message("📋 World Cup Items:\n" + "\n".join(data["items"]))

    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="Title of this World Cup")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running.", ephemeral=True)
            return
        if len(data["items"]) < 32:
            await interaction.response.send_message("❌ At least 32 items are required to start.", ephemeral=True)
            return
        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        save_data(data, sha)
        await interaction.response.send_message(f"@everyone 🎉 The World Cup of {title} is starting! 🎉", ephemeral=False)
        # show bracket preview
        await interaction.channel.send("📊 **Tournament Preview:**\n" + "\n".join(data["current_round"]))
        # start first matchup automatically
        await send_next_matchup(interaction)

    @tree.command(name="nextwcround", description="Run the next matchup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await send_next_matchup(interaction)

    @tree.command(name="resetwc", description="Reset the World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("✅ World Cup has been reset.", ephemeral=False)

    @tree.command(name="endwc", description="Announce the winner without clearing the data")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        winner = data.get("last_winner")
        if not winner:
            await interaction.response.send_message("❌ No winner to announce.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🏆 World Cup Winner!",
            description=f"@everyone, we have a World Cup of {data['title']} winner!\n**{winner}** 🎉",
            color=discord.Color.gold()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
        await interaction.channel.send(f"@everyone, we have a world cup of {data['title']} winner!")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("Winner announced! Use /resetwc to start a new tournament.", ephemeral=True)

    @tree.command(name="showwcmatchup", description="Show upcoming matchups")
    async def showwcmatchup(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["current_round"]:
            await interaction.response.send_message("No active World Cup.", ephemeral=False)
            return
        await interaction.response.send_message("📊 **Current Round Matchups:**\n" + "\n".join(data["current_round"]))

    @tree.command(name="wcscoreboard", description="Show current scores")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=False)
            return
        embed = discord.Embed(title=f"📊 {data['title']} Scoreboard", color=discord.Color.green())
        for item, score in scores.items():
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed)

    @tree.command(name="wchelp", description="Show help for World Cup commands")
    async def wchelp(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📝 World Cup Commands",
            description=(
                "/addwcitem <items> – Add comma-separated items\n"
                "/removewcitem <item> – Remove an item\n"
                "/listwcitems – List all items\n"
                "/startwc <title> – Start the tournament\n"
                "/nextwcround – Run next matchup\n"
                "/showwcmatchup – Show current matchups\n"
                "/wcscoreboard – Show scores\n"
                "/endwc – Announce winner\n"
                "/resetwc – Reset tournament"
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
