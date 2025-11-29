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

# ------------------- Utilities -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

# Count votes from message, return (a_count, b_count, voters_a, voters_b)
async def count_votes_from_message(guild, channel_id, message_id):
    try:
        channel = guild.get_channel(channel_id)
        if not channel:
            return 0, 0, [], []
        msg = await channel.fetch_message(message_id)
    except Exception:
        return 0, 0, [], []

    a_users = {}
    b_users = {}

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
                a_users[u.id] = u.display_name
            elif emoji == VOTE_B:
                b_users[u.id] = u.display_name

    # Remove users who voted for both
    common = set(a_users.keys()) & set(b_users.keys())
    for uid in common:
        del a_users[uid]
        del b_users[uid]

    return len(a_users), len(b_users), list(a_users.values()), list(b_users.values())

# ------------------- Tournament Commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):
    
    # ---------------- Post matchup ----------------
    async def post_next_match(channel, data, sha):
        if len(data["current_round"]) < 2:
            return sha

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)
        sha = save_data(data, sha)

        # Voting embed with live voter list
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage','Matchup')}",
            description=f"{VOTE_A} {a}\n{VOTE_B} {b}",
            color=discord.Color.random()
        )
        embed.set_footer(text="Vote with the reactions above. Only your latest vote counts!")

        msg = await channel.send("@everyone, the next world cup of "
                                 f"{data['title'].replace('Landing Strip World Cup Of ','')} fixture is upon us! 🗳️")
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
        return sha

    # ---------------- /addwcitem ----------------
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

    # ---------------- /removewcitem ----------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to remove")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        items_in = [x.strip() for x in items.split(",") if x.strip()]
        removed = []
        for it in items_in:
            if it in data["items"]:
                data["items"].remove(it)
                data["scores"].pop(it, None)
                removed.append(it)
        sha = save_data(data, sha)
        if removed:
            await interaction.response.send_message(f"✅ Removed {len(removed)} item(s): {', '.join(removed)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)

    # ---------------- /listwcitems ----------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return
        lines = [f"{i+1}. {v}" for i, v in enumerate(data["items"])]
        await interaction.response.send_message("📋 **World Cup Items:**\n" + "\n".join(lines), ephemeral=False)

    # ---------------- /startwc ----------------
    @tree.command(name="startwc", description="Start the World Cup (requires exactly 32 items)")
    @app_commands.describe(title="The 'of' part (e.g. Pizza) — bot will create 'Landing Strip World Cup Of {title}'")
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
        for it in data["items"]:
            data["scores"].setdefault(it, 0)
        data["running"] = True
        data["last_winner"] = None
        data["last_match"] = None
        data["finished_matches"] = []
        data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), "Round")
        sha = save_data(data, sha)

        # Announce start + preview
        await interaction.channel.send(f"@everyone 🎉🥳 The tournament is starting! **{data['title']}** — good luck to all contenders!")

        # Preview of all matchups
        cr = data["current_round"].copy()
        preview_lines = []
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                preview_lines.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                preview_lines.append(f"{cr[i]} (auto-advance)")
        preview_embed = discord.Embed(title="📋 Tournament Preview", description="\n".join(preview_lines), color=discord.Color.teal())
        await interaction.channel.send(embed=preview_embed)

        # Post first matchup
        sha = await post_next_match(interaction.channel, data, sha)
        await interaction.response.send_message("✅ World Cup started, preview and first matchup posted.", ephemeral=True)

    # ---------------- /nextwcround ----------------
    @tree.command(name="nextwcround", description="Count votes for previous match, announce winner, post next matchup")
    async def nextwcround(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return
        if not data.get("last_match"):
            await interaction.response.send_message("❌ No previous matchup to count votes for.", ephemeral=True)
            return

        lm = data["last_match"]
        guild = interaction.guild
        a_votes, b_votes, voters_a, voters_b = await count_votes_from_message(guild, lm["channel_id"], lm["message_id"])
        a_item = lm["a"]
        b_item = lm["b"]

        winner = a_item if a_votes >= b_votes else b_item

        fm = {
            "a": a_item,
            "b": b_item,
            "winner": winner,
            "a_votes": a_votes,
            "b_votes": b_votes
        }
        data["finished_matches"].append(fm)
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        data["last_match"] = None
        sha = save_data(data, sha)

        # Announce winner
        embed = discord.Embed(
            title="🏆 Match Result",
            description=f"**{winner}** wins!\n\nVotes — {VOTE_A} {a_item}: {a_votes} | {VOTE_B} {b_item}: {b_votes}",
            color=discord.Color.gold()
        )
        await interaction.channel.send(embed=embed)

        # Next matchup or next round
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)
            await interaction.response.send_message("✅ Winner recorded and next matchup posted.", ephemeral=True)
            return
        if not data["current_round"]:
            prev_stage = data.get("round_stage", "Round")
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            new_count = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_count, f"{new_count}-items round")
            sha = save_data(data, sha)

            contenders = ", ".join(data["current_round"]) if data["current_round"] else "No contenders"
            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"We are now in **{data['round_stage']}**.\nContenders:\n{contenders}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            # If final winner
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
                embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
                await interaction.channel.send(f"@everyone, we have a world cup of {data['title'].replace('Landing Strip World Cup Of ','')} winner")
                await interaction.channel.send(embed=embed)
                await interaction.response.send_message("✅ Tournament concluded.", ephemeral=True)
                return

            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)
                await interaction.response.send_message("✅ Round promoted and next matchup posted.", ephemeral=True)
                return

        await interaction.response.send_message("✅ Done processing the match.", ephemeral=True)

    # ---------------- /showmatchups ----------------
    @tree.command(name="showwcmatchup", description="Show finished, current, and upcoming matchups")
    async def showmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        finished = data.get("finished_matches", [])
        lines_finished = [f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})" for i,f in enumerate(finished)]
        last = data.get("last_match")
        current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else "None"
        upcoming_pairs = []
        cr = data.get("current_round", []).copy()
        for i in range(0,len(cr),2):
            if i+1<len(cr):
                upcoming_pairs.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming_pairs.append(f"{cr[i]} (auto-advance)")
        embed = discord.Embed(title="📋 Matchup Overview", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
        embed.add_field(name="Round Stage", value=data.get("round_stage") or "N/A", inline=False)
        embed.add_field(name="Finished Matches", value="\n".join(lines_finished) if lines_finished else "None", inline=False)
        embed.add_field(name="Current Match (voting)", value=current_pair, inline=False)
        embed.add_field(name="Upcoming Matchups", value="\n".join(upcoming_pairs) if upcoming_pairs else "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------------- /wcscoreboard ----------------
    @tree.command(name="wcscoreboard", description="View the current tournament scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data.get("scores"):
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return
        lines = sorted(data["scores"].items(), key=lambda x: -x[1])
        embed = discord.Embed(title="📊 Tournament Scoreboard", color=discord.Color.blue())
        for item, score in lines:
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------------- /resetwc ----------------
    @tree.command(name="resetwc", description="Reset the World Cup (clears items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        _, sha = load_data()
        data = DEFAULT_DATA.copy()
        sha = save_data(data, sha)
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.", ephemeral=False)

    # ---------------- /endwc ----------------
    @tree.command(name="endwc", description="Announce the winner and end the World Cup (does NOT clear items)")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        winner = None
        if data.get("current_round") and len(data["current_round"]) == 1:
            winner = data["current_round"][0]
        elif data.get("next_round") and len(data["next_round"]) == 1:
            winner = data["next_round"][0]
        elif data.get("last_winner"):
           
