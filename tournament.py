# tournament.py
import discord
from discord import app_commands
import requests
import base64
import json
import os
import random
import asyncio
from typing import Tuple, Optional

# ------------------- GitHub Config (env override possible) -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")  # owner/repo
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "tournament_data.json")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else "",
    "Accept": "application/vnd.github.v3+json"
}

# Giphy winner gif (you asked to use this for the final winner)
WINNER_GIF_URL = "https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyNnFjc3Bxc3AycXk0MHZmNTVwZnE5MHIycXZrbWp1a3pzM3ppdDhobiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ktHuiYG7qYCOrJCqG0/giphy.gif"

DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": ""
}

# ------------------- GitHub helpers -------------------
def _get_file_from_github() -> Tuple[Optional[dict], Optional[str]]:
    """
    Fetch the file metadata and return the parsed JSON and the file sha.
    Returns (data, sha) or (None, None) on error.
    """
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set — cannot use GitHub persistence.")
        return None, None

    try:
        r = requests.get(GITHUB_API_URL, headers=HEADERS, timeout=10)
    except Exception as e:
        print(f"[tournament] Error requesting GitHub file: {e}")
        return None, None

    if r.status_code == 200:
        j = r.json()
        content_b64 = j.get("content", "")
        try:
            data_str = base64.b64decode(content_b64).decode()
            data = json.loads(data_str)
            return data, j.get("sha")
        except Exception as e:
            print("[tournament] Error decoding GitHub content:", e)
            return None, j.get("sha")
    elif r.status_code == 404:
        # File doesn't exist yet
        return None, None
    else:
        print(f"[tournament] GitHub GET failed {r.status_code}: {r.text}")
        return None, None

def _save_file_to_github(data: dict, sha: Optional[str] = None, message: str = "Update tournament data") -> Optional[str]:
    """
    Save JSON to GitHub. If sha provided, use it. Returns new sha on success, None on failure.
    """
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set — cannot save to GitHub.")
        return None

    content_b64 = base64.b64encode(json.dumps(data, indent=4).encode()).decode()
    payload = {
        "message": message,
        "content": content_b64
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(GITHUB_API_URL, headers=HEADERS, json=payload, timeout=10)
    except Exception as e:
        print(f"[tournament] Error saving to GitHub: {e}")
        return None

    if r.status_code in (200, 201):
        resp = r.json()
        return resp.get("content", {}).get("sha")
    else:
        print(f"[tournament] GitHub save failed {r.status_code}: {r.text}")
        return None

def load_data() -> Tuple[dict, Optional[str]]:
    """
    Load tournament data from GitHub. If file missing, create a fresh one.
    Returns (data, sha).
    """
    data, sha = _get_file_from_github()
    if data is not None:
        # ensure structure completeness
        for k, v in DEFAULT_DATA.items():
            if k not in data:
                data[k] = v
        return data, sha

    # File missing or unreadable -> create default and save
    data = DEFAULT_DATA.copy()
    sha2 = _save_file_to_github(data, sha=None, message="Create tournament data (initial)")
    return data, sha2

def save_data(data: dict, known_sha: Optional[str] = None) -> Optional[str]:
    """
    Save tournament data, attempting to use known_sha; if that fails,
    fetch latest sha and try again. Returns new sha on success, None on failure.
    """
    # try with provided sha first
    new_sha = _save_file_to_github(data, sha=known_sha)
    if new_sha:
        return new_sha

    # If first attempt failed (stale sha or missing), try fetch latest sha and save again
    _, latest_sha = _get_file_from_github()
    new_sha = _save_file_to_github(data, sha=latest_sha)
    if new_sha:
        return new_sha

    print("[tournament] Failed to save data to GitHub after retry.")
    return None

# ------------------- Tournament logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member) -> bool:
        return any(role.id in allowed_role_ids for role in member.roles)

    async def start_match(interaction: discord.Interaction, a_item: str, b_item: str) -> str:
        """Send the matchup and collect votes. Short timeout, manual advancement expected."""
        embed = discord.Embed(
            title="Vote for the winner!",
            description=f"🇦 {a_item}\n🇧 {b_item}",
            color=discord.Color.blurple()
        )
        msg = await interaction.channel.send(embed=embed)
        try:
            await msg.add_reaction("🇦")
            await msg.add_reaction("🇧")
        except Exception:
            # adding reactions can fail if bot lacks perms — still continue
            pass

        def check(reaction, user):
            return str(reaction.emoji) in ["🇦", "🇧"] and not user.bot and reaction.message.id == msg.id

        votes = {"🇦": 0, "🇧": 0}
        try:
            while True:
                reaction, user = await interaction.client.wait_for("reaction_add", timeout=10, check=check)
                votes[str(reaction.emoji)] += 1
        except asyncio.TimeoutError:
            pass

        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        await interaction.channel.send(f"🏆 **{winner}** wins this matchup!")
        return winner

    async def run_next_round(interaction: discord.Interaction):
        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("❌ No tournament is currently running.", ephemeral=True)
            return

        if not data.get("current_round"):
            await interaction.response.send_message("❌ Current round is empty. Start a tournament first.", ephemeral=True)
            return

        items = data["current_round"]
        next_round = []

        for i in range(0, len(items), 2):
            if i + 1 < len(items):
                winner = await start_match(interaction, items[i], items[i + 1])
                next_round.append(winner)
                data.setdefault("scores", {})
                data["scores"][winner] = data["scores"].get(winner, 0) + 1
            else:
                # odd item advances automatically
                next_round.append(items[i])
                data.setdefault("scores", {})
                data["scores"][items[i]] = data["scores"].get(items[i], 0) + 1
                await interaction.channel.send(f"➡️ **{items[i]}** automatically advances due to odd number of items.")

        data["current_round"] = next_round
        new_sha = save_data(data, known_sha=sha)

        # If only one item remains, it's the overall winner
        if len(next_round) == 1:
            winner = next_round[0]
            title = data.get("title", "World Cup")
            # Announce with winner GIF embedded
            embed = discord.Embed(title=f"🎉 {winner} wins the {title}!", color=discord.Color.gold())
            embed.set_image(url=WINNER_GIF_URL)
            await interaction.channel.send(embed=embed)
            data["running"] = False
            save_data(data, known_sha=new_sha)
        else:
            await interaction.response.send_message(f"✅ Round complete — {len(next_round)} items advance to the next round.")

    # ------------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        # restricted
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to start tournaments.", ephemeral=True)
            return

        data, sha = load_data()
        if not data.get("items"):
            await interaction.response.send_message("❌ No items added yet. Use /addwcitem first.", ephemeral=True)
            return

        # Shuffle and set initial round
        title_text = f"Landing Strip World Cup Of {title}"
        round_items = data["items"].copy()
        random.shuffle(round_items)
        data["title"] = title_text
        data["current_round"] = round_items
        data["next_round"] = []
        data["scores"] = {item: 0 for item in round_items}
        data["running"] = True
        new_sha = save_data(data, known_sha=sha)
        await interaction.response.send_message(f"🏁 Starting **{title_text}**! Use /nextwcround to advance rounds.")

    @tree.command(name="addwcitem", description="Add an item to the World Cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to add items.", ephemeral=True)
            return

        data, sha = load_data()
        data.setdefault("items", [])
        data["items"].append(item)
        new_sha = save_data(data, known_sha=sha)
        await interaction.response.send_message(f"✅ Added **{item}** to the World Cup.")

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to remove items.", ephemeral=True)
            return

        data, sha = load_data()
        if item in data.get("items", []):
            data["items"].remove(item)
            new_sha = save_data(data, known_sha=sha)
            await interaction.response.send_message(f"✅ Removed **{item}** from the World Cup.")
        else:
            await interaction.response.send_message("❌ Item not found in the World Cup.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])
        if not items:
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=True)
            return
        # show indexed list for clarity
        lines = [f"{idx+1}. {it}" for idx, it in enumerate(items)]
        await interaction.response.send_message("📋 **World Cup Items:**\n" + "\n".join(lines))

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        # Sort by score desc, fallback alphabetical
        sorted_scores = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        msg_lines = [f"{item}: {score}" for item, score in sorted_scores]
        await interaction.response.send_message("📊 **Scoreboard:**\n" + "\n".join(msg_lines))

    @tree.command(name="resetwc", description="Reset the World Cup (clears all items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to reset the tournament.", ephemeral=True)
            return
        # Reset to default structure and save
        new_sha = save_data(DEFAULT_DATA.copy())
        if new_sha is None:
            await interaction.response.send_message("⚠️ Failed to reset tournament (GitHub save failed).", ephemeral=True)
        else:
            await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    @tree.command(name="nextwcround", description="Run the next round of the current World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_round(interaction)