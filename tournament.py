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
    "last_match": None,          # {a, b, message_id, channel_id}
    "finished_matches": [],      # list of {a, b, winner, a_votes, b_votes}
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

    # Enforce single vote: last reaction counts
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

        desc = f"{VOTE_A} {a}\n\n_No votes yet_\n\n{VOTE_B} {b}\n\n_No votes yet_"
        embed = discord.Embed(title=f"🎮 {data.get('round_stage', 'Matchup')}", description=desc, color=discord.Color.random())
        embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")

        await channel.send(f"@everyone, the next World Cup of {data['title']} fixture is upon us! 🗳️")
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

        async def update_votes_loop():
            last_a_count = last_b_count = -1
            while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
                a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.channel.id, msg.id)
                if a_count != last_a_count or b_count != last_b_count:
                    last_a_count, last_b_count = a_count, b_count
                    desc = f"{VOTE_A} {a} — {a_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                    desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"
                    new_embed = discord.Embed(
                        title=f"🎮 {data.get('round_stage','Matchup')}",
                        description=desc,
                        color=discord.Color.random()
                    )
                    new_embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")
                    try:
                        await msg.edit(embed=new_embed)
                    except:
                        pass
                await asyncio.sleep(2)

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

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to remove")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        items_out = [x.strip() for x in items.split(",") if x.strip()]
        removed = []
        for it in items_out:
            if it in data["items"]:
                data["items"].remove(it)
                data["scores"].pop(it, None)
                removed.append(it)
        sha = save_data(data, sha)
        if removed:
            await interaction.response.send_message(f"✅ Removed {len(removed)} item(s): {', '.join(removed)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)
                # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup with all added items")
    @app_commands.describe(title="Title for this World Cup")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("⚠️ A World Cup is already running.", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("⚠️ Not enough items to start (minimum 2).", ephemeral=True)
            return

        random.shuffle(data["items"])
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {it: 0 for it in data["items"]}
        data["running"] = True
        data["title"] = title
        data["finished_matches"] = []
        data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), f"Round of {len(data['current_round'])}")

        sha = save_data(data, sha)
        await interaction.response.send_message(f"🏁 World Cup '{title}' started with {len(data['items'])} items!", ephemeral=False)

        # Post first match automatically
        sha = await post_next_match(interaction.channel, data, sha)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Progress to the next match in the World Cup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("⚠️ No World Cup is currently running.", ephemeral=True)
            return
        if not data.get("last_match"):
            await interaction.response.send_message("⚠️ No match is currently posted.", ephemeral=True)
            return

        # Count votes from last match
        last = data["last_match"]
        a_votes, b_votes, _, _ = await count_votes_from_message(interaction.guild, last["channel_id"], last["message_id"])
        winner = last["a"] if a_votes >= b_votes else last["b"]
        data["finished_matches"].append({
            "a": last["a"], "b": last["b"], "winner": winner,
            "a_votes": a_votes, "b_votes": b_votes
        })
        data["next_round"].append(winner)
        data["last_winner"] = winner
        data["last_match"] = None

        # If more matches left in current round, post next
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)
            await interaction.response.send_message(f"✅ Match completed. Next match posted.", ephemeral=False)
        else:
            # Round finished
            data["current_round"] = data["next_round"]
            data["next_round"] = []
            if len(data["current_round"]) == 1:
                # Tournament finished
                winner = data["current_round"][0]
                data["running"] = False
                sha = save_data(data, sha)
                await interaction.response.send_message(f"🏆 World Cup finished! Winner: {winner}", ephemeral=False)
            else:
                data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), f"Round of {len(data['current_round'])}")
                sha = save_data(data, sha)
                await interaction.response.send_message(f"✅ Round finished. {len(data['current_round'])} items advancing to next round.", ephemeral=False)
                sha = await post_next_match(interaction.channel, data, sha)

    # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all World Cup items")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data["items"]
        if not items:
            await interaction.response.send_message("⚠️ No items added yet.", ephemeral=True)
            return

        # Paginate embeds for large lists
        page_size = 20
        pages = [items[i:i+page_size] for i in range(0, len(items), page_size)]
        embeds = []
        for idx, page in enumerate(pages, 1):
            embed = discord.Embed(title=f"World Cup Items (Page {idx}/{len(pages)})", description="\n".join(page), color=discord.Color.blurple())
            embeds.append(embed)

        current_page = 0
        msg = await interaction.response.send_message(embed=embeds[current_page], ephemeral=False)
        # Navigation buttons could be added here if desired

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show last match or ongoing match")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        last = data.get("last_match")
        if not last:
            await interaction.response.send_message("⚠️ No match currently posted.", ephemeral=True)
            return
        desc = f"{VOTE_A} {last['a']}\n{VOTE_B} {last['b']}\n\n*Votes updating in real-time in original message*"
        embed = discord.Embed(title=f"🎮 Current Match", description=desc, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup completely")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        sha = save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("♻️ World Cup reset.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="End the World Cup early")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        data["running"] = False
        sha = save_data(data, sha)
        await interaction.response.send_message("🛑 World Cup ended early.", ephemeral=False)