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

# ------------------- Default JSON structure -------------------
DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None,
    # holds last posted matchup so we can count votes on that message later
    "last_match": None,
    # human readable stage e.g. "Round of 32", "Round of 16", "Quarter Finals", ...
    "round_stage": ""
}

STAGE_BY_COUNT = {
    32: "Round of 32",
    16: "Round of 16",
    8: "Quarter Finals",
    4: "Semi Finals",
    2: "Finals",
}

# ------------------- GitHub helpers (same pattern as warnings bot) -------------------
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
            # ensure keys exist
            for k in DEFAULT_DATA:
                if k not in data:
                    data[k] = DEFAULT_DATA[k]
            print(f"✅ Loaded tournament_data.json, SHA={sha}")
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

# ------------------- Utility -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

# ------------------- Main setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ---------- helper: post a matchup (pops two items from current_round) ----------
    async def post_next_match(channel, data, sha):
        """
        Pops two items from data['current_round'], posts a matchup embed to the
        provided channel, stores last_match info in data and returns updated sha.
        """
        if len(data["current_round"]) < 2:
            return sha  # nothing to post

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)
        save_data(data, sha)  # persist the popped state before posting

        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=f"🇦 {a}\n🇧 {b}",
            color=discord.Color.random()
        )
        embed.set_footer(text="React with 🇦 or 🇧 to vote — votes are counted when /nextwcround is run.")
        # announce @everyone then embed
        await channel.send("@everyone 🎯 Next matchup!")
        msg = await channel.send(embed=embed)
        try:
            await msg.add_reaction("🇦")
            await msg.add_reaction("🇧")
        except Exception:
            pass

        # store last_match
        data["last_match"] = {
            "a": a,
            "b": b,
            "message_id": msg.id,
            "channel_id": channel.id
        }
        sha = save_data(data, sha)
        return sha

    # ---------- helper: count reactions on a message for 🇦 and 🇧 ----------
    async def count_votes_from_message(guild, channel_id, message_id):
        """
        Fetch message and return (count_a, count_b).
        Counting rules:
          - Count unique users per emoji.
          - If a user reacted to BOTH emojis we exclude them from both (ambiguous).
          - Ignore bots.
        """
        try:
            channel = guild.get_channel(channel_id)
            if channel is None:
                return 0, 0
            msg = await channel.fetch_message(message_id)
        except Exception:
            return 0, 0

        a_users = set()
        b_users = set()

        for reaction in msg.reactions:
            if str(reaction.emoji) not in ("🇦", "🇧"):
                continue
            users = [u async for u in reaction.users()]
            for u in users:
                if u.bot:
                    continue
                if str(reaction.emoji) == "🇦":
                    a_users.add(u.id)
                else:
                    b_users.add(u.id)

        # exclude users who reacted to both
        common = a_users & b_users
        a_final = a_users - common
        b_final = b_users - common

        return len(a_final), len(b_final)

    # ---------- /addwcitem (comma separated) ----------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        added = []
        for it in [x.strip() for x in items.split(",") if x.strip()]:
            if it not in data["items"]:
                data["items"].append(it)
                data["scores"].setdefault(it, 0)
                added.append(it)
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {len(added)} items.", ephemeral=False)

    # ---------- /listwcitems ----------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return
        # show as numbered list
        lines = [f"{i+1}. {v}" for i, v in enumerate(data["items"])]
        await interaction.response.send_message("📋 **World Cup Items:**\n" + "\n".join(lines), ephemeral=False)

    # ---------- /startwc ----------
    @tree.command(name="startwc", description="Start the World Cup (requires exactly 32 items)")
    @app_commands.describe(title="The 'of' part (e.g. Pizza) — bot will prefix with Landing Strip World Cup Of")
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

        data["title"] = f"Landing Strip World Cup Of {title}"
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        # init scores if missing
        for it in data["items"]:
            data["scores"].setdefault(it, 0)
        data["running"] = True
        data["last_winner"] = None
        data["last_match"] = None
        data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), "Round")

        sha = save_data(data, sha)

        # Announce start with @everyone then post first matchup (post_next_match pops two)
        await interaction.channel.send("@everyone 🎉🥳 The tournament is starting! " +
                                       f"**{data['title']}** — good luck to all contenders!")
        sha = await post_next_match(interaction.channel, data, sha)

        await interaction.response.send_message("✅ World Cup started and first matchup posted.", ephemeral=True)

    # ---------- /nextwcround ----------
    @tree.command(name="nextwcround", description="Count votes for the previous match, announce the winner, and post the next matchup")
    async def nextwcround(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        # Ensure there is a last_match to count
        if not data.get("last_match"):
            # no last match — possibly first call after start (shouldn't happen) or user forgot
            await interaction.response.send_message("❌ No previous matchup to count votes for.", ephemeral=True)
            return

        lm = data["last_match"]
        guild = interaction.guild
        # Count votes on stored message
        a_votes, b_votes = await count_votes_from_message(guild, lm["channel_id"], lm["message_id"])
        a_item = lm["a"]
        b_item = lm["b"]

        # Determine winner (tie -> a_item wins)
        if a_votes >= b_votes:
            winner = a_item
        else:
            winner = b_item

        # Update next_round and scores
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        # Clear last_match now that counted
        data["last_match"] = None
        sha = save_data(data, sha)

        # Announce previous winner
        embed = discord.Embed(
            title="🏆 Match Result",
            description=f"**{winner}** wins this matchup!\n\nVotes — 🇦 {a_item}: {a_votes} | 🇧 {b_item}: {b_votes}",
            color=discord.Color.gold()
        )
        await interaction.channel.send(embed=embed)

        # If there are more matches in current_round, post next match (this pops two)
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)
            await interaction.response.send_message("✅ Winner recorded and next matchup posted.", ephemeral=True)
            return

        # If current_round is empty => round completed, promote next_round
        if not data["current_round"]:
            prev_stage = data.get("round_stage", "Round")
            # promote next_round -> current_round
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            # determine new stage
            new_count = len(data["current_round"])
            if new_count in STAGE_BY_COUNT:
                data["round_stage"] = STAGE_BY_COUNT[new_count]
            else:
                data["round_stage"] = f"{new_count}-items round"

            sha = save_data(data, sha)

            # Announce round completion and list contenders
            contenders = ", ".join(data["current_round"]) if data["current_round"] else "No contenders"
            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"We are now in **{data['round_stage']}**.\nContenders:\n{contenders}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            # If only one contender left -> final winner
            if len(data["current_round"]) == 1:
                final = data["current_round"][0]
                data["running"] = False
                data["last_winner"] = final
                sha = save_data(data, sha)
                embed = discord.Embed(
                    title="🏁 Tournament Winner!",
                    description=f"🎉 **{final}** wins the **{data['title']}**! Thank you everyone for voting! 🥳",
                    color=discord.Color.green()
                )
                await interaction.channel.send("@everyone 🎊 The World Cup has concluded!")
                await interaction.channel.send(embed=embed)
                await interaction.response.send_message("✅ Tournament concluded.", ephemeral=True)
                return

            # Otherwise post the next matchup of the new round (if 2+)
            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)
                await interaction.response.send_message("✅ Round promoted and next matchup posted.", ephemeral=True)
                return

        # fallback
        await interaction.response.send_message("✅ Done processing this round.", ephemeral=True)

    # ---------- /scoreboard ----------
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data.get("scores"):
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return
        # sort by score desc
        lines = sorted(data["scores"].items(), key=lambda x: -x[1])
        msg = "**📊 Tournament Scoreboard**\n"
        for item, score in lines:
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg, ephemeral=False)

    # ---------- /resetwc ----------
    @tree.command(name="resetwc", description="Reset the World Cup (clears items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        _, sha = load_data()
        data = DEFAULT_DATA.copy()
        sha = save_data(data, sha)
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.", ephemeral=False)

    # ---------- /endwc (announce winner but do NOT reset JSON) ----------
    @tree.command(name="endwc", description="Announce the winner and end the World Cup (does NOT clear items)")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        # Figure possible winner
        winner = None
        if data.get("last_match"):
            # if last match exists but not counted yet, prefer last_winner if exists, else unknown
            winner = data.get("last_winner") or "Unknown"
        elif data.get("current_round") and len(data["current_round"]) == 1:
            winner = data["current_round"][0]
        elif data.get("next_round") and len(data["next_round"]) == 1:
            winner = data["next_round"][0]
        else:
            winner = data.get("last_winner") or "Unknown"

        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 **{winner}** wins the **{data.get('title','World Cup')}**! Thank you everyone for voting! 🥳🎊",
            color=discord.Color.green()
        )
        await interaction.channel.send("@everyone The World Cup has ended!")
        await interaction.channel.send(embed=embed)
        data["running"] = False
        sha = save_data(data, sha)
        await interaction.response.send_message("✅ Winner announced. (Data preserved)", ephemeral=True)

    # end of setup_tournament_commands