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
    "last_match": None,
    "finished_matches": [],
    "round_stage": ""
}

STAGE_BY_COUNT = {
    32: "Round of 32",
    16: "Round of 16",
    8:  "Quarter Finals",
    4:  "Semi Finals",
    2:  "Finals"
}

VOTE_A = "🔴"
VOTE_B = "🔵"

# ------------------- GitHub helpers -------------------
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
            for k in DEFAULT_DATA:
                if k not in data:
                    data[k] = DEFAULT_DATA[k]
            return data, sha
        elif r.status_code == 404:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
        else:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
    except Exception as e:
        print("Error loading data:", e)
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
        print("Error saving data:", e)
        return sha

# ------------------- Utilities -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

async def count_votes_from_message(guild, channel_id, message_id):
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            return 0, 0, {}, {}
        msg = await channel.fetch_message(message_id)
    except Exception as e:
        print("Error fetching message for vote counting:", e)
        return 0, 0, {}, {}

    a_users = set()
    b_users = set()
    a_names = {}
    b_names = {}

    for reaction in msg.reactions:
        emoji = str(reaction.emoji)
        if emoji not in (VOTE_A, VOTE_B):
            continue
        try:
            users = [u async for u in reaction.users()]
        except Exception:
            users = []
        for u in users:
            if u.bot:
                continue
            if emoji == VOTE_A:
                a_users.add(u.id)
                a_names[u.id] = u.display_name
            elif emoji == VOTE_B:
                b_users.add(u.id)
                b_names[u.id] = u.display_name

    # Enforce single vote: if user reacted to both, keep only last reaction
    common = a_users & b_users
    for uid in common:
        if uid in b_users:
            a_users.remove(uid)
            a_names.pop(uid, None)
        else:
            b_users.remove(uid)
            b_names.pop(uid, None)

    return len(a_users), len(b_users), a_names, b_names

# ------------------- Main Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ------------------- Post Next Match -------------------
    async def post_next_match(channel, data, sha):
        if len(data["current_round"]) < 2:
            return sha

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)

        sha = save_data(data, sha)

        # Voting embed (no footer)
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=f"{VOTE_A} {a}\n\n_No votes yet_\n\n{VOTE_B} {b}\n\n_No votes yet_",
            color=discord.Color.random()
        )

        msg = await channel.send(embed=embed)
        await msg.add_reaction(VOTE_A)
        await msg.add_reaction(VOTE_B)

        data["last_match"] = {
            "a": a,
            "b": b,
            "message_id": msg.id,
            "channel_id": channel.id
        }
        sha = save_data(data, sha)

        # Task to update embed dynamically with voters every 2 seconds
        async def update_votes_loop():
            while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
                a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.channel.id, msg.id)
                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"
                try:
                    await msg.edit(embed=discord.Embed(title=f"🎮 {data.get('round_stage','Matchup')}", description=desc, color=discord.Color.random()))
                except Exception:
                    pass
                await asyncio.sleep(2)  # Update every 2s

        asyncio.create_task(update_votes_loop())

        return sha

    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        items_in = [x.strip() for x in items.split(",") if x.strip()]
        added = []
        for it in items_in:
            if it not in data["items"]:
                data["items"].append(it)
                data["scores"].setdefault(it, 0)
                added.append(it)
        sha = save_data(data, sha)
        if added:
            await interaction.response.send_message(f"✅ Added {len(added)} item(s): {', '.join(added)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No new items added (duplicates ignored).", ephemeral=False)

    # ------------------- /removewcitem (case-insensitive) -------------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (comma-separated, case-insensitive)")
    @app_commands.describe(items="Comma-separated list of items to remove")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        items_out = [x.strip() for x in items.split(",") if x.strip()]
        removed = []
        lower_items = {it.lower(): it for it in data["items"]}
        for it in items_out:
            key = it.lower()
            if key in lower_items:
                original = lower_items[key]
                data["items"].remove(original)
                data["scores"].pop(original, None)
                removed.append(original)
        sha = save_data(data, sha)
        if removed:
            await interaction.response.send_message(f"✅ Removed {len(removed)} item(s): {', '.join(removed)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)
                # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, _ = load_data()
        items = data.get("items", [])
        if items:
            await interaction.response.send_message("📝 **World Cup Items:**\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(items)), ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No items currently in the World Cup.", ephemeral=False)

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup tournament")
    async def startwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data.get("running"):
            await interaction.response.send_message("⚠️ Tournament is already running.", ephemeral=False)
            return
        if len(data.get("items", [])) < 2:
            await interaction.response.send_message("⚠️ Not enough items to start.", ephemeral=False)
            return
        random.shuffle(data["items"])
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["running"] = True
        data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), f"{len(data['current_round'])}-item Round")
        sha = save_data(data, sha)
        await interaction.response.send_message(f"🏁 Tournament started with {len(data['current_round'])} items! Use /nextwcround to post the first matchup.", ephemeral=False)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Post the next matchup in the World Cup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("⚠️ Tournament is not running.", ephemeral=False)
            return

        channel = interaction.channel

        # 1️⃣ @everyone notification
        try:
            await channel.send("@everyone **Next World Cup matchup!**")
        except Exception:
            pass

        # 2️⃣ Previous winner embed
        last_winner = data.get("last_winner")
        if last_winner:
            embed = discord.Embed(
                title="🏆 Previous Winner",
                description=f"**{last_winner}**",
                color=discord.Color.gold()
            )
            await channel.send(embed=embed)

        # 3️⃣ Voting embed via post_next_match
        sha = await post_next_match(channel, data, sha)

        await interaction.response.send_message("✅ Next matchup posted.", ephemeral=True)

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show the current matchups")
    async def showwcmatchups(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, _ = load_data()
        matchups = [f"{a} vs {b}" for a, b in zip(data.get("current_round", [])[::2], data.get("current_round", [])[1::2])]
        if matchups:
            await interaction.response.send_message("🎮 **Current Matchups:**\n" + "\n".join(matchups), ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No current matchups.", ephemeral=False)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup tournament")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        data.update(DEFAULT_DATA.copy())
        sha = save_data(data, sha)
        await interaction.response.send_message("🔄 Tournament has been reset.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="End the World Cup tournament early")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        data["running"] = False
        sha = save_data(data, sha)
        await interaction.response.send_message("⏹️ Tournament has been ended.", ephemeral=False)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Show help for World Cup commands")
    async def wchelp(interaction: discord.Interaction):
        help_text = (
            "📌 **World Cup Commands:**\n"
            "/addwcitem [items] - Add items to the tournament\n"
            "/removewcitem [items] - Remove items (case-insensitive)\n"
            "/listwcitems - List all items\n"
            "/startwc - Start the tournament\n"
            "/nextwcround - Post the next matchup\n"
            "/showwcmatchups - Show current matchups\n"
            "/resetwc - Reset the tournament\n"
            "/endwc - End the tournament early\n"
            "/wchelp - Show this help message"
        )
        await interaction.response.send_message(help_text, ephemeral=False)