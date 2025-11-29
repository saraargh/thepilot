import os
import json
import base64
import requests
import discord
from discord import app_commands
import random
import asyncio
from datetime import datetime

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
    print("🔍 Loading tournament_data.json from GitHub...")
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        print("GET status:", r.status_code)
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            data = json.loads(raw) if raw.strip() else DEFAULT_DATA.copy()
            sha = content.get("sha")
            print(f"✅ Loaded tournament_data.json, SHA={sha}")
            for key in DEFAULT_DATA:
                if key not in data:
                    data[key] = DEFAULT_DATA[key]
            return data, sha
        elif r.status_code == 404:
            print("⚠️ tournament_data.json not found, creating new.")
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
        else:
            print("❌ Unexpected GET status:", r.status_code, r.text)
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
    except Exception as e:
        print("❌ Exception in load_data:", e)
        sha = save_data(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy(), sha

def save_data(data, sha=None):
    print("🔧 Saving tournament_data.json to GitHub...")
    try:
        payload = {
            "message": "Update tournament data",
            "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode()
        }
        if sha:
            payload["sha"] = sha
            print(f"Using SHA: {sha}")
        r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload))
        print(f"PUT status: {r.status_code}")
        print(f"PUT response: {r.text}")
        if r.status_code in (200, 201):
            new_sha = r.json().get("content", {}).get("sha")
            print(f"✅ Saved tournament_data.json, new SHA={new_sha}")
            return new_sha
        else:
            print("❌ Failed to save tournament_data.json")
            return sha
    except Exception as e:
        print("❌ Exception in save_data:", e)
        return sha

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def run_next_match(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"] or not data["current_round"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        items = data["current_round"]

        if len(items) < 2:
            winner = items[0]
            await interaction.response.send_message(f"🎉 **{winner}** wins the **{data['title']}**!")
            data["running"] = False
            data["last_winner"] = winner
            save_data(data, sha)
            return

        # Take first two items for the match
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
        except asyncio.TimeoutError:
            pass

        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        data["next_round"].append(winner)
        data["scores"][winner] += 1
        data["current_round"] = items[2:]
        data["last_winner"] = winner
        save_data(data, sha)
        await interaction.channel.send(f"🏆 {winner} wins this match!")

        if not data["current_round"]:
            # Round finished, promote next_round
            data["current_round"] = data["next_round"]
            data["next_round"] = []
            save_data(data, sha)
            if len(data["current_round"]) == 1:
                final_winner = data["current_round"][0]
                await interaction.channel.send(f"🎉 **{final_winner}** wins the **{data['title']}**!")
                data["running"] = False
                data["last_winner"] = final_winner
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
        save_data(data, sha)
        await interaction.response.send_message(f"🏁 Starting **{title_text}**!")

    @tree.command(name="addwcitem", description="Add one or more items to the World Cup (comma separated)")
    @app_commands.describe(items="Comma separated list of items")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        for item in [i.strip() for i in items.split(",") if i.strip()]:
            if item not in data["items"]:
                data["items"].append(item)
                data["scores"][item] = 0
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added items: {items}")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            if item in data["scores"]:
                del data["scores"][item]
            save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}")
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

    @tree.command(name="resetwc", description="Reset the World Cup (clears all items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    @tree.command(name="nextwcround", description="Run the next match of the current World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_match(interaction)