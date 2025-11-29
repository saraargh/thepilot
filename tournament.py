# tournament.py
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

DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None,
    "round_stage": ""
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
            for key in DEFAULT_DATA:
                if key not in data:
                    data[key] = DEFAULT_DATA[key]
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

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ---------------- Add items (multiple via comma) ----------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup")
    @app_commands.describe(items="Comma-separated items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s) to the World Cup.")

    # ---------------- List items ----------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 **World Cup Items:**\n" + "\n".join(data["items"]))

    # ---------------- Start World Cup ----------------
    @tree.command(name="startwc", description="Start the World Cup tournament")
    @app_commands.describe(title="Title of the World Cup")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running.", ephemeral=True)
            return
        if len(data["items"]) != 32:
            await interaction.response.send_message("❌ You must have exactly 32 items to start.", ephemeral=True)
            return

        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        data["round_stage"] = "Round of 32"
        save_data(data, sha)

        await interaction.channel.send("@everyone 🎉🎉🎉 The World Cup of **{}** is starting! 🏆🥳".format(title))
        # announce first matchup
        first_match = data["current_round"][:2]
        embed = discord.Embed(
            title="🏁 First Matchup!",
            description=f"🇦 {first_match[0]}\n🇧 {first_match[1]}",
            color=discord.Color.random()
        )
        match_msg = await interaction.channel.send(embed=embed)
        await match_msg.add_reaction("🇦")
        await match_msg.add_reaction("🇧")
        await interaction.response.send_message("✅ World Cup started!", ephemeral=True)

    # ---------------- Next Round / Next Match ----------------
    @tree.command(name="nextwcround", description="Proceed to the next match and announce previous winner")
    async def nextwcround(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return
        if not data["current_round"]:
            await interaction.response.send_message("❌ No more matchups in this round.", ephemeral=True)
            return

        # If previous match exists, announce last winner
        if data["last_winner"]:
            embed = discord.Embed(
                title="🏆 Match Result",
                description=f"**{data['last_winner']}** won the previous matchup! 🎉",
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=embed)

        # Check for next matchup
        if len(data["current_round"]) == 1:
            # Round over
            winner = data["current_round"][0]
            data["next_round"].append(winner)
            data["last_winner"] = winner
            # Move to next stage
            stages = ["Round of 32", "Round of 16", "Quarter Finals", "Semi Finals", "Finals"]
            if data["round_stage"] in stages and data["round_stage"] != "Finals":
                next_stage_index = stages.index(data["round_stage"]) + 1
                data["round_stage"] = stages[next_stage_index]
                contenders = ", ".join(data["next_round"])
                embed = discord.Embed(
                    title=f"✅ {stages[next_stage_index-1]} complete!",
                    description=f"We are now in **{data['round_stage']}**!\nContenders:\n{contenders}",
                    color=discord.Color.purple()
                )
                await interaction.channel.send(embed=embed)

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []

        # Get next matchup
        if len(data["current_round"]) >= 2:
            matchup = data["current_round"][:2]
            embed = discord.Embed(
                title=f"🎮 {data['round_stage']} Matchup",
                description=f"🇦 {matchup[0]}\n🇧 {matchup[1]}",
                color=discord.Color.random()
            )
            match_msg = await interaction.channel.send("@everyone Next Matchup!")
            match_msg2 = await interaction.channel.send(embed=embed)
            await match_msg2.add_reaction("🇦")
            await match_msg2.add_reaction("🇧")
            # remove these from current_round temporarily
            data["current_round"] = data["current_round"][2:]
        save_data(data, sha)
        await interaction.response.send_message("✅ Next matchup posted.", ephemeral=True)

    # ---------------- Scoreboard ----------------
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        msg = "**📊 Current Scores:**\n"
        for item, score in scores.items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)

    # ---------------- Reset World Cup ----------------
    @tree.command(name="resetwc", description="Reset the World Cup (clears items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    # ---------------- End World Cup ----------------
    @tree.command(name="endwc", description="Announce the winner and end the World Cup")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return
        winner = None
        if len(data["current_round"]) == 1:
            winner = data["current_round"][0]
        elif len(data["next_round"]) == 1:
            winner = data["next_round"][0]
        else:
            winner = data["last_winner"] or "Unknown"
        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 **{winner}** wins the **{data['title']}**! Thank you everyone for voting! 🥳🎊",
            color=discord.Color.green()
        )
        await interaction.channel.send("@everyone The World Cup has ended!")
        await interaction.channel.send(embed=embed)
        data["running"] = False
        save_data(data, sha)
        await interaction.response.send_message("✅ World Cup ended.", ephemeral=True)