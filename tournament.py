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

# ------------------- Default JSON -------------------
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
WINNER_GIF = "https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif"

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
            # ensure keys
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
    except:
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
    except:
        return sha

# ------------------- Utilities -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

async def count_votes_from_message(guild, channel_id, message_id):
    """Return (a_votes, b_votes)"""
    try:
        channel = guild.get_channel(channel_id)
        msg = await channel.fetch_message(message_id)
    except:
        return 0, 0

    a_users, b_users = set(), set()
    for reaction in msg.reactions:
        emoji = str(reaction.emoji)
        if emoji not in (VOTE_A, VOTE_B):
            continue
        users = [u async for u in reaction.users() if not u.bot]
        for u in users:
            if emoji == VOTE_A:
                a_users.add(u.id)
            else:
                b_users.add(u.id)
    common = a_users & b_users
    return len(a_users - common), len(b_users - common)

# ------------------- Main setup -------------------
def setup_tournament_commands(bot: discord.Bot, allowed_role_ids):

    tree = bot.tree

    async def post_next_match(channel, data, sha):
        if len(data["current_round"]) < 2:
            return sha
        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)
        sha = save_data(data, sha)

        desc = f"{VOTE_A} {a}\nVoters: None\n\n{VOTE_B} {b}\nVoters: None"
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage','Matchup')}",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="Vote with the reactions above. Votes are counted when /nextwcround is run.")
        await channel.send(f"@everyone, the next world cup of {data.get('title','Tournament')} fixture is upon us! 🗳️")
        msg = await channel.send(embed=embed)
        try:
            await msg.add_reaction(VOTE_A)
            await msg.add_reaction(VOTE_B)
        except:
            pass

        data["last_match"] = {
            "a": a,
            "b": b,
            "message_id": msg.id,
            "channel_id": channel.id
        }
        return save_data(data, sha)

    # ---------------- Commands ----------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup")
    @app_commands.describe(items="Comma-separated list of items")
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
        if added:
            await interaction.response.send_message(f"✅ Added: {', '.join(added)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No new items added (duplicates ignored).", ephemeral=False)

    @tree.command(name="removewcitem", description="Remove an item from the World Cup")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return
        data, sha = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            data["scores"].pop(item, None)
            sha = save_data(data, sha)
            await interaction.response.send_message(f"✅ Removed {item}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ Item not found", ephemeral=True)

    @tree.command(name="listwcitems", description="List all World Cup items")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added.", ephemeral=True)
            return
        await interaction.response.send_message("📋 Items:\n" + "\n".join(data["items"]), ephemeral=False)

    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="Title for the World Cup (e.g., Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ Already running.", ephemeral=True)
            return
        if len(data["items"]) != 32:
            await interaction.response.send_message("❌ Must have exactly 32 items.", ephemeral=True)
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

        # Announcement
        await interaction.channel.send(f"@everyone 🎉🥳 The tournament is starting! **{data['title']}**")
        # Preview of matchups
        preview_lines = []
        cr = data["current_round"].copy()
        for i in range(0, len(cr), 2):
            preview_lines.append(f"{cr[i]} vs {cr[i+1]}")
        preview_embed = discord.Embed(title="📋 Tournament Preview", description="\n".join(preview_lines), color=discord.Color.blue())
        await interaction.channel.send(embed=preview_embed)

        # First matchup
        sha = await post_next_match(interaction.channel, data, sha)
        await interaction.response.send_message("✅ World Cup started and first matchup posted.", ephemeral=True)

    # ---------------- /nextwcround ----------------
    @tree.command(name="nextwcround", description="Count votes and move to next matchup")
    async def nextwcround(interaction: discord.Interaction):
        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return
        if not data.get("last_match"):
            await interaction.response.send_message("❌ No previous match.", ephemeral=True)
            return

        lm = data["last_match"]
        guild = interaction.guild
        a_votes, b_votes = await count_votes_from_message(guild, lm["channel_id"], lm["message_id"])
        a_item, b_item = lm["a"], lm["b"]

        winner = a_item if a_votes >= b_votes else b_item
        data["next_round"].append(winner)
        data["scores"].setdefault(winner, 0)
        data["scores"][winner] += 1
        data["last_winner"] = winner
        data["finished_matches"].append({
            "a": a_item, "b": b_item, "winner": winner,
            "a_votes": a_votes, "b_votes": b_votes
        })
        data["last_match"] = None
        sha = save_data(data, sha)

        # Winner embed
        embed = discord.Embed(title="🏆 Match Result",
                              description=f"**{winner}** wins!\n\nVotes — {VOTE_A} {a_item}: {a_votes} | {VOTE_B} {b_item}: {b_votes}",
                              color=discord.Color.gold())
        await interaction.channel.send(embed=embed)

        # Next match or round promotion
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
            # Round announcement
            contenders = ", ".join(data["current_round"]) if data["current_round"] else "No contenders"
            embed = discord.Embed(title=f"✅ {prev_stage} complete!",
                                  description=f"We are now in **{data['round_stage']}**.\nContenders:\n{contenders}",
                                  color=discord.Color.purple())
            await interaction.channel.send(embed=embed)
            # Only one left => winner
            if len(data["current_round"]) == 1:
                final = data["current_round"][0]
                data["running"] = False
                data["last_winner"] = final
                sha = save_data(data, sha)
                embed = discord.Embed(title="🏁 Tournament Winner!",
                                      description=f"🎉 **{final}** wins the **{data['title']}**! Thank you everyone for voting! 🥳",
                                      color=discord.Color.green())
                embed.set_image(url=WINNER_GIF)
                await interaction.channel.send(f"@everyone, we have a world cup of {data['title']} winner")
                await interaction.channel.send(embed=embed)
                await interaction.response.send_message("✅ Tournament concluded.", ephemeral=True)
                return
            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)
                await interaction.response.send_message("✅ Round promoted and next matchup posted.", ephemeral=True)
                return

        await interaction.response.send_message("✅ Done processing match.", ephemeral=True)

    # ---------------- /wchelp ----------------
    @tree.command(name="wchelp", description="World Cup help")
    async def wchelp(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return
        embed = discord.Embed(title="📖 World Cup Help", color=discord.Color.teal())
        embed.add_field(name="Commands", value=(
            "✅ /addwcitem [item1, item2] – Add items\n"
            "✅ /removewcitem [item] – Remove item\n"
            "✅ /listwcitems – List all items\n"
            "✅ /startwc [title] – Start the tournament\n"
            "✅ /nextwcround – Record votes & next matchup\n"
            "✅ /resetwc – Reset tournament (clears items)\n"
            "✅ /endwc – End tournament (does not clear items)\n"
            "✅ /showmatchups – Show all matchups (public)\n"
            "✅ /scoreboard – Show scoreboard (public)\n"
            "✅ /lastwinner – Show last match winner"
        ), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- /showmatchups ----------------
    @tree.command(name="showmatchups", description="Show finished, current, upcoming matchups")
    async def showmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        finished = data.get("finished_matches", [])
        lines_finished = [f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
                          for i,f in enumerate(finished)]
        last = data.get("last_match")
        current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else None
        upcoming_pairs = []
        cr = data.get("current_round", []).copy()
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                upcoming_pairs.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming_pairs.append(f"{cr[i]} (auto-advance if odd)")
        embed = discord.Embed(title="📋 Matchup Overview", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title","No title"), inline=False)
        embed.add_field(name="Round Stage", value=data.get("round_stage","N/A"), inline=False)
        embed.add_field(name="Finished Matches", value="\n".join(lines_finished) if lines_finished else "None", inline=False)
        embed.add_field(name="Current Match (voting)", value=current_pair or "None", inline=False)
        embed.add_field(name="Upcoming Matchups", value="\n".join(upcoming_pairs) if upcoming_pairs else "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------------- /scoreboard ----------------
    @tree.command(name="scoreboard", description="Show tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        lines = sorted(data.get("scores", {}).items(), key=lambda x: -x[1])
        msg = "**📊 Tournament Scoreboard**\n" + "\n".join([f"{i}: {s}" for i,s in lines]) if lines else "No scores yet."
        await interaction.response.send_message(msg, ephemeral=False)

    # ---------------- /resetwc ----------------
    @tree.command(name="resetwc", description="Reset World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ No permission.", ephemeral=True)
            return
        _, sha = load_data()
        data = DEFAULT_DATA.copy()
        sha = save_data(data, sha)
        await interaction.response.send_message("🔄 World Cup reset.", ephemeral=False)

    # ---------------- /endwc ----------------
    @tree.command(name="endwc", description="Announce winner and end WC (does not clear items)")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return
        winner = data.get("last_winner","Unknown")
        embed = discord.Embed(title="🎉 World Cup Finished!",
                              description=f"🏆 **{winner}** wins the **{data.get('title','World Cup')}**! Thank you for voting! 🥳",
                              color=discord.Color.green())
        embed.set_image(url=WINNER_GIF)
        await interaction.channel.send(f"@everyone, we have a world cup of {data.get('title','Tournament')} winner")
        await interaction.channel.send(embed=embed)
        data["running"] = False
        sha = save_data(data, sha)
        await interaction.response.send_message("✅ Winner announced.", ephemeral=True)

    # ---------------- /lastwinner ----------------
    @tree.command(name="lastwinner", description="Show last resolved match")
    async def lastwinner(interaction: discord.Interaction):
        data