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

    # Enforce single vote: last vote counts
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

        # Embed with voter placeholders
        desc = f"{VOTE_A} {a}\n\n_No votes yet_\n\n{VOTE_B} {b}\n\n_No votes yet_"
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=desc,
            color=discord.Color.random()
        )
        # Permanent italic footer
        embed.set_footer(text="_use /showwcmatchups to keep track of the World Cup!_")

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

        # Task to update embed dynamically with voters
        async def update_votes_loop():
            while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
                a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.channel.id, msg.id)
                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"
                try:
                    new_embed = discord.Embed(title=f"🎮 {data.get('round_stage','Matchup')}", description=desc, color=discord.Color.random())
                    new_embed.set_footer(text="_use /showwcmatchups to keep track of the World Cup!_")
                    await msg.edit(embed=new_embed)
                except Exception:
                    pass
                await asyncio.sleep(10)

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

# ------------------- /listwcitems -------------------
@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    if not data["items"]:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return
    embed = discord.Embed(title="📋 World Cup Items", color=discord.Color.blue())
    for idx, item in enumerate(data["items"], 1):
        embed.add_field(name=f"{idx}.", value=item, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=False)

# ------------------- /startwc -------------------
@tree.command(name="startwc", description="Start the World Cup (requires exactly 32 items)")
@app_commands.describe(title="The 'of' part (e.g. Pizza) — bot will create 'World Cup of {title}'")
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
    for it in data["items"]:
        data["scores"].setdefault(it, 0)
    data["running"] = True
    data["last_winner"] = None
    data["last_match"] = None
    data["finished_matches"] = []
    data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), "Round")
    sha = save_data(data, sha)

    # Start announcement only
    await interaction.channel.send(f"@everyone, the World Cup of {data['title']} is starting - view the match ups below and cast your votes now! 🤗🎉")

    # First matchup quietly (no extra message)
    sha = await post_next_match(interaction.channel, data, sha)
    await interaction.response.send_message("✅ World Cup started and first matchup posted.", ephemeral=True)

# ------------------- /nextwcround -------------------
@tree.command(name="nextwcround", description="Count votes for previous match, announce winner, and post next matchup")
async def nextwcround(interaction: discord.Interaction):
    data, sha = load_data()
    if not data.get("running"):
        await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
        return
    if not data.get("last_match"):
        await interaction.response.send_message("❌ There's no previous matchup to count votes for.", ephemeral=True)
        return

    lm = data["last_match"]
    guild = interaction.guild

    a_votes, b_votes, _, _ = await count_votes_from_message(guild, lm["channel_id"], lm["message_id"])
    a_item = lm["a"]
    b_item = lm["b"]

    winner = a_item if a_votes >= b_votes else b_item

    fm = {"a": a_item, "b": b_item, "winner": winner, "a_votes": a_votes, "b_votes": b_votes}
    data["finished_matches"].append(fm)
    data["next_round"].append(winner)
    data["scores"].setdefault(winner, 0)
    data["scores"][winner] += 1
    data["last_winner"] = winner
    data["last_match"] = None
    sha = save_data(data, sha)

    # Announce winner
    embed = discord.Embed(title="🏆 Match Result",
                          description=f"**{winner}** wins!\n\nVotes — {VOTE_A} {a_item}: {a_votes} | {VOTE_B} {b_item}: {b_votes}",
                          color=discord.Color.gold())
    await interaction.channel.send(embed=embed)

    # Post next matchup with @everyone
    if len(data["current_round"]) >= 2:
        sha = await post_next_match(interaction.channel, data, sha)

        await interaction.channel.send(f"@everyone, the next World Cup of {data['title']} fixture is upon us! 🗳️")
        await interaction.response.send_message("✅ Winner recorded and next matchup posted.", ephemeral=True)
        return

# ------------------- Internal Show Matchups -------------------
async def showwcmatchups_internal(channel, data):
    finished = data.get("finished_matches", [])
    lines_finished = [f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
                      for i, f in enumerate(finished)]
    last = data.get("last_match")
    current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else None
    upcoming_pairs = []
    cr = data.get("current_round", []).copy()
    for i in range(0, len(cr), 2):
        if i + 1 < len(cr):
            upcoming_pairs.append(f"{cr[i]} vs {cr[i+1]}")
        else:
            upcoming_pairs.append(f"{cr[i]} (auto-advance if odd)")
    embed = discord.Embed(title="📋 World Cup Matchup Overview", color=discord.Color.teal())
    embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
    embed.add_field(name="Round Stage", value=data.get("round_stage") or "N/A", inline=False)
    embed.add_field(name="Finished Matches", value="\n".join(lines_finished) if lines_finished else "None", inline=False)
    embed.add_field(name="Current Match (voting)", value=current_pair or "None", inline=False)
    embed.add_field(name="Upcoming Matchups", value="\n".join(upcoming_pairs) if upcoming_pairs else "None", inline=False)
    await channel.send(embed=embed)

# ------------------- /showwcmatchups -------------------
@tree.command(name="showwcmatchups", description="Show finished, current, and upcoming World Cup matchups")
async def showwcmatchups(interaction: discord.Interaction):
    data, _ = load_data()
    await showwcmatchups_internal(interaction.channel, data)
    await interaction.response.send_message("✅ Matchups displayed.", ephemeral=True)

# ------------------- /resetwc -------------------
@tree.command(name="resetwc", description="Reset the World Cup (clears items and scores)")
async def resetwc(interaction: discord.Interaction):
    if not user_allowed(interaction.user, allowed_role_ids):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    _, sha = load_data()
    data = DEFAULT_DATA.copy()
    sha = save_data(data, sha)
    await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.", ephemeral=False)

# ------------------- /endwc -------------------
@tree.command(name="endwc", description="Announce the winner and end the World Cup (does NOT clear items)")
async def endwc(interaction: discord.Interaction):
    data, sha = load_data()
    if not data.get("running"):
        await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
        return

    winner = data.get("last_winner") or "Unknown"

    embed = discord.Embed(title="🎉 World Cup Finished!",
                          description=f"🏆 **{winner}** wins the **{data.get('title','World Cup')}**! Thank you everyone for voting! 🥳🎊",
                          color=discord.Color.green())
    embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
    await interaction.channel.send(f"@everyone, we have a World Cup of {data.get('title')} winner")
    await interaction.channel.send(embed=embed)
    data["running"] = False
    sha = save_data(data, sha)
    await interaction.response.send_message("✅ Winner announced. (Data preserved)", ephemeral=True)

# ------------------- /wchelp -------------------
@tree.command(name="wchelp", description="Show World Cup command instructions")
async def wchelp(interaction: discord.Interaction):
    if not user_allowed(interaction.user, allowed_role_ids):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    embed = discord.Embed(title="📝 World Cup Command Help", color=discord.Color.blue())
    embed.add_field(name="/addwcitem", value="Add item(s) to the World Cup (comma-separated) 🎯", inline=False)
    embed.add_field(name="/removewcitem", value="Remove item(s) from the World Cup (comma-separated) 🗑️", inline=False)
    embed.add_field(name="/listwcitems", value="List all items in the World Cup 📋", inline=False)
    embed.add_field(name="/startwc", value="Start the World Cup (requires 32 items) 🏁", inline=False)
    embed.add_field(name="/nextwcround", value="Record votes, announce winner, post next matchup 🏆", inline=False)
    embed.add_field(name="/showwcmatchups", value="Show finished, current, and upcoming matchups 📊", inline=False)
    embed.add_field(name="/resetwc", value="Reset the World Cup (clears all data) 🔄", inline=False)
    embed.add_field(name="/endwc", value="Announce the winner (does not clear items) 🎉", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ------------------- Post Next Match Helper -------------------
async def post_next_match(channel, data, sha):
    if len(data["current_round"]) < 2:
        return sha

    a = data["current_round"].pop(0)
    b = data["current_round"].pop(0)
    sha = save_data(data, sha)

    # Embed with voter placeholders and permanent italic footer
    desc = f"{VOTE_A} {a}\n\n_No votes yet_\n\n{VOTE_B} {b}\n\n_No votes yet_"
    embed = discord.Embed(title=f"🎮 {data.get('round_stage','Matchup')}", description=desc, color=discord.Color.random())
    embed.set_footer(text="_use /showwcmatchups to keep track of the World Cup!_")  # permanent italic

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

    # Task to update embed dynamically with voters
    async def update_votes_loop():
        while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
            a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.channel.id, msg.id)
            desc = f"{VOTE_A} {a} — {a_count} votes\n"
            desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
            desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
            desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"
            try:
                new_embed = discord.Embed(title=f"🎮 {data.get('round_stage','Matchup')}", description=desc, color=discord.Color.random())
                new_embed.set_footer(text="_use /showwcmatchups to keep track of the World Cup!_")
                await msg.edit(embed=new_embed)
            except Exception:
                pass
            await asyncio.sleep(10)

    asyncio.create_task(update_votes_loop())
    return sha