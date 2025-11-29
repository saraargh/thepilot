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

# ------------------- GitHub helpers (warnings-bot style) -------------------
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
            # ensure keys
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

# ------------------- Utilities -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

# Count votes on a message for VOTE_A / VOTE_B
async def count_votes_from_message(guild, channel_id, message_id):
    """
    Returns (a_count, b_count). Counting rules:
    - Unique users per emoji.
    - If a user reacted to both, exclude them from both.
    - Ignore bots.
    """
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            return 0, 0
        msg = await channel.fetch_message(message_id)
    except Exception as e:
        print("Error fetching message for vote counting:", e)
        return 0, 0

    a_users = set()
    b_users = set()

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
            elif emoji == VOTE_B:
                b_users.add(u.id)

    common = a_users & b_users
    a_final = a_users - common
    b_final = b_users - common
    return len(a_final), len(b_final)

# ------------------- Main Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    async def post_next_match(channel, data, sha):
        """
        Pops two items from current_round, posts matchup with reactions,
        stores last_match in data and returns sha.
        """
        if len(data["current_round"]) < 2:
            return sha

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)

        # Persist popped state before posting (so if crash, state remains)
        sha = save_data(data, sha)

        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=f"{VOTE_A} {a}\n{VOTE_B} {b}",
            color=discord.Color.random()
        )
        embed.set_footer(text="Vote with the reactions above. Votes are counted when /nextwcround is run.")
        # announce @everyone then embed
        await channel.send("@everyone 🎯 Next matchup!")
        msg = await channel.send(embed=embed)
        try:
            await msg.add_reaction(VOTE_A)
            await msg.add_reaction(VOTE_B)
        except Exception:
            pass

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

        await interaction.channel.send("@everyone 🎉🥳 The tournament is starting! " +
                                       f"**{data['title']}** — good luck to all contenders!")
        sha = await post_next_match(interaction.channel, data, sha)
        await interaction.response.send_message("✅ World Cup started and first matchup posted.", ephemeral=True)

    # ---------------- /nextwcround ----------------
    @tree.command(name="nextwcround", description="Count votes for the previous match, announce winner, and post the next matchup")
    async def nextwcround(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        if not data.get("last_match"):
            await interaction.response.send_message("❌ There's no previous matchup to count votes for.", ephemeral=True)
            return

        lm = data["last_match"]
        guild = interaction.guild

        a_votes, b_votes = await count_votes_from_message(guild, lm["channel_id"], lm["message_id"])
        a_item = lm["a"]
        b_item = lm["b"]

        # Decide winner (tie unlikely; but favor A if equal)
        if a_votes >= b_votes:
            winner = a_item
        else:
            winner = b_item

        # record finished match
        fm = {
            "a": a_item,
            "b": b_item,
            "winner": winner,
            "a_votes": a_votes,
            "b_votes": b_votes
        }
        data["finished_matches"].append(fm)

        # update next_round & scores
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        data["last_match"] = None
        sha = save_data(data, sha)

        # announce winner
        embed = discord.Embed(
            title="🏆 Match Result",
            description=f"**{winner}** wins!\n\nVotes — {VOTE_A} {a_item}: {a_votes} | {VOTE_B} {b_item}: {b_votes}",
            color=discord.Color.gold()
        )
        await interaction.channel.send(embed=embed)

        # If there's another pair left in current_round, post next match
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)
            await interaction.response.send_message("✅ Winner recorded and next matchup posted.", ephemeral=True)
            return

        # If current_round is empty => round complete, promote next_round
        if not data["current_round"]:
            prev_stage = data.get("round_stage", "Round")
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            new_count = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_count, f"{new_count}-items round")
            sha = save_data(data, sha)

            # announce round completion
            contenders = ", ".join(data["current_round"]) if data["current_round"] else "No contenders"
            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"We are now in **{data['round_stage']}**.\nContenders:\n{contenders}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            # If only one left -> tournament winner
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

            # else post next matchup in the new round
            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)
                await interaction.response.send_message("✅ Round promoted and next matchup posted.", ephemeral=True)
                return

        await interaction.response.send_message("✅ Done processing the match.", ephemeral=True)

    # ---------------- /scoreboard ----------------
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data.get("scores"):
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return
        lines = sorted(data["scores"].items(), key=lambda x: -x[1])
        msg = "**📊 Tournament Scoreboard**\n"
        for item, score in lines:
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg, ephemeral=False)

    # ---------------- /lastwinner ----------------
    @tree.command(name="lastwinner", description="Show the last resolved match and its details")
    async def lastwinner(interaction: discord.Interaction):
        data, _ = load_data()
        if not data.get("finished_matches"):
            await interaction.response.send_message("No finished matches yet.", ephemeral=True)
            return
        last = data["finished_matches"][-1]
        embed = discord.Embed(
            title="🔁 Last Resolved Match",
            description=f"{VOTE_A} {last['a']} vs {VOTE_B} {last['b']}\n\n"
                        f"Winner: **{last['winner']}**\n"
                        f"Votes — {VOTE_A} {last['a_votes']} | {VOTE_B} {last['b_votes']}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    # ---------------- /showmatchups ----------------
    @tree.command(name="showmatchups", description="Show finished, current and upcoming matchups")
    async def showmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        # finished
        finished = data.get("finished_matches", [])
        lines_finished = []
        for i, f in enumerate(finished):
            lines_finished.append(f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})")
        # last match (if uncounted)
        last = data.get("last_match")
        current_pair = None
        if last:
            current_pair = f"{last['a']} vs {last['b']} (voting now)"
        # remaining in current_round (note: pairs will be formed in posting order)
        upcoming_pairs = []
        cr = data.get("current_round", []).copy()
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                upcoming_pairs.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming_pairs.append(f"{cr[i]} (auto-advance if odd)")

        embed = discord.Embed(title="📋 Matchup Overview", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
        embed.add_field(name="Round Stage", value=data.get("round_stage") or "N/A", inline=False)
        embed.add_field(name="Finished Matches", value="\n".join(lines_finished) if lines_finished else "None", inline=False)
        embed.add_field(name="Current Match (voting)", value=current_pair or "None", inline=False)
        embed.add_field(name="Upcoming Matchups", value="\n".join(upcoming_pairs) if upcoming_pairs else "None", inline=False)
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

        # determine winner if possible
        winner = None
        if data.get("current_round") and len(data["current_round"]) == 1:
            winner = data["current_round"][0]
        elif data.get("next_round") and len(data["next_round"]) == 1:
            winner = data["next_round"][0]
        elif data.get("last_winner"):
            winner = data["last_winner"]
        else:
            winner = "Unknown"

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

    # end setup_tournament_commands