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

async def count_votes_from_message(guild, channel_id, message_id):
    """
    Returns dict of {user_id: vote} for last matchup message
    """
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            return {}
        msg = await channel.fetch_message(message_id)
    except Exception:
        return {}

    vote_map = {}  # user_id -> vote
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
            vote_map[u.id] = emoji  # only keep last vote (overwrite)
    return vote_map

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
        sha = save_data(data, sha)

        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=f"{VOTE_A} {a}\n{VOTE_B} {b}",
            color=discord.Color.random()
        )
        embed.set_footer(text="• use the wcscoreboard and showwcmatchups commands to keep track of the tournament!")
        
        # Custom message based on stage
        if data.get("round_stage") == "Finals":
            await channel.send(f"@everyone, the World Cup of {data['title']} final is upon us! 🗳️")
        else:
            await channel.send(f"@everyone, the next World Cup of {data['title']} fixture is upon us! 🗳️")

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
            "channel_id": channel.id,
            "votes": {}  # user_id -> emoji
        }
        sha = save_data(data, sha)
        return sha

    # ---------------- /startwc ----------------
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

        # Preview all matchups first
        cr_copy = data["current_round"].copy()
        upcoming_pairs = []
        for i in range(0, len(cr_copy), 2):
            if i + 1 < len(cr_copy):
                upcoming_pairs.append(f"{cr_copy[i]} vs {cr_copy[i+1]}")
            else:
                upcoming_pairs.append(f"{cr_copy[i]} (auto-advance if odd)")

        preview_embed = discord.Embed(
            title=f"📋 {data['title']} - Matchup Preview",
            description="\n".join(upcoming_pairs),
            color=discord.Color.blurple()
        )
        preview_embed.set_footer(text="• use the wcscoreboard and showwcmatchups commands to keep track of the tournament!")
        await interaction.channel.send(f"@everyone, the World Cup of {data['title']} is starting - view the match ups below and cast your votes now! 🤗🎉")
        await interaction.channel.send(embed=preview_embed)

        # Post first matchup
        sha = await post_next_match(interaction.channel, data, sha)
        await interaction.response.send_message("✅ World Cup started and first matchup posted.", ephemeral=True)
            # ---------------- /nextwcround ----------------
    @tree.command(name="nextwcround", description="Count votes, announce winner, and post next matchup")
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

        # Count votes ensuring only last vote per user counts
        a_users = set()
        b_users = set()
        try:
            channel = guild.get_channel(lm["channel_id"])
            msg = await channel.fetch_message(lm["message_id"])
            for reaction in msg.reactions:
                if str(reaction.emoji) not in (VOTE_A, VOTE_B):
                    continue
                users = [u async for u in reaction.users()]
                for u in users:
                    if u.bot:
                        continue
                    # track latest vote per user
                    lm["votes"][u.id] = str(reaction.emoji)
            for uid, emoji in lm["votes"].items():
                if emoji == VOTE_A:
                    a_users.add(uid)
                elif emoji == VOTE_B:
                    b_users.add(uid)
        except Exception:
            pass

        a_votes = len(a_users)
        b_votes = len(b_users)
        a_item = lm["a"]
        b_item = lm["b"]

        # Decide winner
        winner = a_item if a_votes >= b_votes else b_item

        # Record finished match
        fm = {"a": a_item, "b": b_item, "winner": winner, "a_votes": a_votes, "b_votes": b_votes}
        data["finished_matches"].append(fm)
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        data["last_match"] = None
        sha = save_data(data, sha)

        # Announce winner embed
        embed = discord.Embed(
            title="🏆 Match Result",
            description=f"{VOTE_A} {a_item}: {a_votes} votes\n{VOTE_B} {b_item}: {b_votes} votes\n\nWinner: **{winner}**",
            color=discord.Color.gold()
        )
        await interaction.channel.send(embed=embed)

        # Promote next round if current_round empty
        if not data["current_round"]:
            prev_stage = data.get("round_stage", "Round")
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            new_count = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_count, f"{new_count}-items round")
            sha = save_data(data, sha)

            # Round completion announcement
            contenders = ", ".join(data["current_round"]) if data["current_round"] else "No contenders"
            embed_round = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"We are now in **{data['round_stage']}**.\nContenders:\n{contenders}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed_round)

            # If only one left -> tournament winner
            if len(data["current_round"]) == 1:
                final = data["current_round"][0]
                data["running"] = False
                data["last_winner"] = final
                sha = save_data(data, sha)
                embed = discord.Embed(
                    title="🏁 Tournament Winner!",
                    description=f"🎉 {final} wins the **{data['title']}**! Thank you everyone for voting! 🥳",
                    color=discord.Color.green()
                )
                await interaction.channel.send(f"@everyone 🎊 The World Cup of {data['title']} has concluded!")
                await interaction.channel.send(embed=embed)
                await interaction.response.send_message("✅ Tournament concluded.", ephemeral=True)
                return

        # Post next matchup if available
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)
            await interaction.response.send_message("✅ Winner recorded and next matchup posted.", ephemeral=True)
            return

        await interaction.response.send_message("✅ Done processing the match.", ephemeral=True)

    # ---------------- /showwcmatchups ----------------
    @tree.command(name="showwcmatchups", description="Show finished, current, and upcoming matchups")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        finished = data.get("finished_matches", [])
        lines_finished = [f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})" for i, f in enumerate(finished)]
        last = data.get("last_match")
        current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else "None"
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
        embed = discord.Embed(title="📊 Tournament Scoreboard", color=discord.Color.dark_blue())
        for item, score in lines:
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------------- /wchelp ----------------
    @tree.command(name="wchelp", description="View instructions for using the World Cup commands")
    async def wchelp(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        embed = discord.Embed(title="📚 World Cup Commands Help", color=discord.Color.green())
        embed.add_field(name="/addwcitem", value="Add items to the World Cup (comma-separated)", inline=False)
        embed.add_field(name="/removewcitem", value="Remove items from the World Cup (comma-separated)", inline=False)
        embed.add_field(name="/listwcitems", value="List all items in the World Cup", inline=False)
        embed.add_field(name="/startwc", value="Start the World Cup with exactly 32 items", inline=False)
        embed.add_field(name="/nextwcround", value="Count votes for last matchup, announce winner, post next matchup", inline=False)
        embed.add_field(name="/resetwc", value="Reset the World Cup (clears items and scores)", inline=False)
        embed.add_field(name="/endwc", value="Announce winner and end the World Cup (does not clear items)", inline=False)
        embed.add_field(name="/showwcmatchups", value="Show finished, current, and upcoming matchups", inline=False)
        embed.add_field(name="/wcscoreboard", value="View current tournament scoreboard", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
            winner = data["last_winner"]
        else:
            winner = "Unknown"

        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 {winner} wins the **{data.get('title','World Cup')}**! Thank you everyone for voting! 🥳",
            color=discord.Color.green()
        )
        await interaction.channel.send(f"@everyone, we have a World Cup of {data.get('title','World Cup')} winner!")
        await interaction.channel.send(embed=embed)
        data["running"] = False
        sha = save_data(data, sha)
        await interaction.response.send_message("✅ Winner announced. (Data preserved)", ephemeral=True)