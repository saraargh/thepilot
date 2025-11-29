import discord
from discord import app_commands
import random
import asyncio
import os
import json
import base64
import requests

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
            return data, sha
        else:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
    except Exception as e:
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
        else:
            return sha
    except Exception as e:
        return sha

# ------------------- Role Check -------------------
DEFAULT_ALLOWED_ROLES = [
    1420817462290681936,
    1413545658006110401,
    1404098545006546954,
    1406242523952713820
]

def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or DEFAULT_ALLOWED_ROLES
    return any(role.id in allowed_roles for role in member.roles)

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    allowed_roles = allowed_role_ids or DEFAULT_ALLOWED_ROLES

    def can_use(interaction: discord.Interaction):
        return user_allowed(interaction.user, allowed_roles)

    async def nextwcmatch(interaction: discord.Interaction):
        """Run next match, announce previous winner if any, and post matchup embed"""
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup is currently running.", ephemeral=True)
            return

        # Announce previous match winner if available
        if data["match_history"]:
            last_match = data["match_history"][-1]
            winner = last_match["winner"]
            embed_prev = discord.Embed(
                title=f"🏆 Last Match Winner",
                description=f"🔴 {last_match['a_item']} vs 🔵 {last_match['b_item']}\n**Winner:** {winner}",
                color=discord.Color.green()
            )
            embed_prev.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
            await interaction.channel.send(f"@everyone, the last match is complete!", embed=embed_prev)

        # Pick next matchup
        if len(data["current_round"]) < 2:
            # Tournament ended
            winner = data["current_round"][0] if data["current_round"] else None
            data["last_winner"] = winner
            data["running"] = False
            save_data(data, sha)
            await interaction.channel.send(f"@everyone, we have a World Cup of **{data['title']}** winner: **{winner}**! 🎉 Use `/resetwc` to start a new cup.")
            return

        a_item = data["current_round"].pop(0)
        b_item = data["current_round"].pop(0)
        data["votes"] = {}  # reset votes for this match
        save_data(data, sha)

        embed = discord.Embed(
            title=f"🗳️ {data['title']} - {data['round_name']} Matchup",
            description=f"🔴 {a_item}\n🔵 {b_item}",
            color=discord.Color.blue()
        )
        msg = await interaction.channel.send(f"@everyone, the next world cup of **{data['title']}** fixture is upon us! 🗳️", embed=embed)
        await msg.add_reaction("🔴")
        await msg.add_reaction("🔵")

        # Wait for votes
        def check(reaction, user):
            return str(reaction.emoji) in ["🔴", "🔵"] and not user.bot

        votes = {"🔴": set(), "🔵": set()}

        while True:
            try:
                reaction, user = await interaction.client.wait_for("reaction_add", timeout=60, check=check)
                # enforce only one vote per user
                for key in votes:
                    votes[key].discard(user.id)
                votes[str(reaction.emoji)].add(user.id)

                # Update embed with who voted
                vote_text = f"🔴 {a_item} - {len(votes['🔴'])} votes\n🔵 {b_item} - {len(votes['🔵'])} votes"
                embed.description = vote_text
                await msg.edit(embed=embed)
            except asyncio.TimeoutError:
                break

        winner = a_item if len(votes["🔴"]) >= len(votes["🔵"]) else b_item
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["match_history"].append({"a_item": a_item, "b_item": b_item, "winner": winner})
        save_data(data, sha)

        await interaction.channel.send(f"✅ **{winner}** wins this match! Use `/nextwcmatch` for the next matchup.")

        # Update round name if done with current round
        if not data["current_round"]:
            data["current_round"] = data["next_round"]
            data["next_round"] = []
            # update round name
            length = len(data["current_round"])
            if length == 16:
                data["round_name"] = "Round of 16"
                title_announcement = "Round of 32 complete! Here are the contenders:"
            elif length == 8:
                data["round_name"] = "Quarter Finals"
                title_announcement = "Round of 16 complete! Quarter Finals:"
            elif length == 4:
                data["round_name"] = "Semi Finals"
                title_announcement = "Quarter Finals complete! Semi Finals:"
            elif length == 2:
                data["round_name"] = "Finals"
                title_announcement = "Semi Finals complete! Finals:"
            else:
                title_announcement = ""
            save_data(data, sha)
            if title_announcement:
                await interaction.channel.send(title_announcement + "\n" + "\n".join(data["current_round"]))

    # ---------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        if not can_use(interaction):
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

        # Show all first round matchups
        matchups = []
        for i in range(0, len(data["current_round"]), 2):
            if i + 1 < len(data["current_round"]):
                matchups.append(f"🔴 {data['current_round'][i]} vs 🔵 {data['current_round'][i+1]}")
            else:
                matchups.append(f"🔴 {data['current_round'][i]} advances automatically")
        embed = discord.Embed(
            title=f"🏁 {title} - First Round Matchups",
            description="\n".join(matchups),
            color=discord.Color.gold()
        )
        await interaction.channel.send(embed=embed)

    @tree.command(name="addwcitem", description="Add items to the World Cup")
    @app_commands.describe(items="Comma-separated list of items")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        for item in [i.strip() for i in items.split(",")]:
            if item and item not in data["items"]:
                data["items"].append(item)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added items: {items}", ephemeral=False)

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}", ephemeral=False)
        else:
            await interaction.response.send_message("❌ Item not found.", ephemeral=True)

    @tree.command(name="resetwc", description="Reset the World Cup completely")
    async def resetwc(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup has been reset.", ephemeral=False)

    @tree.command(name="nextwcmatch", description="Run the next matchup")
    async def nextwcmatch_cmd(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await nextwcmatch(interaction)

    @tree.command(name="showwcmatchup", description="Show current matchups")
    async def showwcmatchup(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup is running.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"{data['title']} - {data['round_name']}",
            description="\n".join(data["current_round"]),
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tree.command(name="wcscoreboard", description="Show tournament scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["scores"]:
            await interaction.response.send_message("❌ No scores yet.", ephemeral=True)
            return
        embed = discord.Embed(title=f"{data['title']} - Scoreboard", color=discord.Color.orange())
        for item, score in sorted(data["scores"].items(), key=lambda x: -x[1]):
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @tree.command(name="wchelp", description="Show World Cup instructions")
    async def wchelp(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📝 World Cup Bot Instructions",
            description=(
                "/addwcitem <item1, item2,...> - Add items\n"
                "/removewcitem <item> - Remove an item\n"
                "/startwc <title> - Start the World Cup\n"
                "/nextwcmatch - Run next matchup\n"
                "/showwcmatchup - Show current round items\n"
                "/wcscoreboard - Show scoreboard\n"
                "/resetwc - Reset tournament\n"
            ),
            color=discord.Color.teal()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)