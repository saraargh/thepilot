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

DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None,
    "matchups": [],
    "current_match_index": 0
}

# ------------------- Helpers -------------------
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
            for key in DEFAULT_DATA.keys():
                if key not in data:
                    data[key] = DEFAULT_DATA[key]
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
    return sha

def user_allowed(member: discord.Member, allowed_role_ids):
    return any(role.id in allowed_role_ids for role in member.roles)

def format_matchup(a, b):
    return f"🔴 {a}  VS  🔵 {b}"

def get_round_name(num_items):
    if num_items == 32: return "Round of 32"
    if num_items == 16: return "Round of 16"
    if num_items == 8: return "Quarter Finals"
    if num_items == 4: return "Semi Finals"
    if num_items == 2: return "Final"
    return "Round"

# ------------------- Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    vote_tracker = {}  # {user_id: current_choice}

    async def send_matchup_embed(channel, a, b, title, round_name):
        embed = discord.Embed(
            title=f"🏆 {title} - {round_name}",
            description=f"{format_matchup(a,b)}\n\nReact to vote!",
            color=discord.Color.random()
        )
        embed.set_footer(text="You can change your vote by reacting again.")
        msg = await channel.send(embed=embed)
        await msg.add_reaction("🔴")
        await msg.add_reaction("🔵")
        return msg

    async def process_votes(msg, a, b, data):
        nonlocal vote_tracker
        votes = {a: [], b: []}

        def check(reaction, user):
            return str(reaction.emoji) in ["🔴","🔵"] and not user.bot and user in msg.guild.members

        while True:
            try:
                reaction, user = await msg.client.wait_for("reaction_add", timeout=0.1, check=check)
                prev_vote = vote_tracker.get(user.id)
                current_vote = a if str(reaction.emoji)=="🔴" else b
                if prev_vote and prev_vote!=current_vote:
                    # remove previous reaction
                    for r in msg.reactions:
                        users = await r.users().flatten()
                        if user in users and ((r.emoji=="🔴" and prev_vote==a) or (r.emoji=="🔵" and prev_vote==b)):
                            await msg.remove_reaction(r.emoji,user)
                vote_tracker[user.id] = current_vote
                # rebuild votes
                votes = {a: [], b: []}
                for uid, choice in vote_tracker.items():
                    member = msg.guild.get_member(uid)
                    if member:
                        votes[choice].append(member.display_name)
                # edit embed
                vote_text = f"🔴 {a}: {', '.join(votes[a]) or 'No votes yet'}\n🔵 {b}: {', '.join(votes[b]) or 'No votes yet'}"
                embed = discord.Embed(title=msg.embeds[0].title, description=f"{format_matchup(a,b)}\n\n{vote_text}", color=discord.Color.random())
                embed.set_footer(text="You can change your vote by reacting again.")
                await msg.edit(embed=embed)
            except asyncio.TimeoutError:
                break
            except Exception:
                await asyncio.sleep(0.1)
                continue

    async def run_next_match(interaction: discord.Interaction):
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup!", ephemeral=True)
            return
        if data["current_match_index"] >= len(data["matchups"]):
            await interaction.response.send_message("✅ All matches done! Use /endwc to finish.", ephemeral=True)
            return

        # previous match winner announcement
        if data["current_match_index"] > 0:
            last_a, last_b = data["matchups"][data["current_match_index"]-1]
            winner = last_a if last_a in vote_tracker and vote_tracker[last_a] else last_b
            if not winner: winner = last_a  # fallback
            data["last_winner"] = winner
            if winner not in data["scores"]:
                data["scores"][winner] = 0
            data["scores"][winner] += 1
            await interaction.channel.send(f"🏆 Previous match winner: {winner}! (Use /nextwcmatch for next match)")

        # next matchup
        a,b = data["matchups"][data["current_match_index"]]
        round_name = get_round_name(len(data["current_round"]))
        await interaction.channel.send(f"@everyone, the next world cup of {data['title']} {round_name} fixture is upon us! 🗳️")
        msg = await send_matchup_embed(interaction.channel,a,b,data["title"],round_name)

        data["current_match_index"] += 1
        save_data(data, sha)

    # ------------------- Commands -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    @app_commands.describe(title="World Cup title")
    async def startwc(interaction: discord.Interaction, title:str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if len(data["items"]) < 32:
            await interaction.response.send_message("❌ Need 32 items to start.", ephemeral=True)
            return
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running.", ephemeral=True)
            return
        data["title"] = title
        data["current_round"] = data["items"].copy()
        data["scores"] = {item:0 for item in data["items"]}
        random.shuffle(data["current_round"])
        # create matchups
        data["matchups"] = [(data["current_round"][i],data["current_round"][i+1]) for i in range(0,len(data["current_round"]),2)]
        data["current_match_index"] = 0
        data["running"] = True
        save_data(data, sha)
        await interaction.response.send_message(f"@everyone 🎉 Starting **{title}** World Cup! Matchups to follow!")
        # show first matchup automatically
        await run_next_match(interaction)

    @tree.command(name="addwcitem", description="Add items (comma separated)")
    @app_commands.describe(items="Comma separated list")
    async def addwcitem(interaction: discord.Interaction, items:str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added: {', '.join(new_items)}")

    @tree.command(name="resetwc", description="Reset the World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = DEFAULT_DATA.copy()
        save_data(data)
        await interaction.response.send_message("✅ World Cup has been reset.")

    @tree.command(name="showwcmatchup", description="Show the next matchup")
    async def showwcmatchup(interaction: discord.Interaction):
        data,_ = load_data()
        if not data["running"] or data["current_match_index"]>=len(data["matchups"]):
            await interaction.response.send_message("❌ No active matchups.", ephemeral=True)
            return
        a,b = data["matchups"][data["current_match_index"]]
        round_name = get_round_name(len(data["current_round"]))
        await interaction.response.send_message(embed=discord.Embed(title=f"{round_name} Matchup", description=format_matchup(a,b), color=discord.Color.random()))

    @tree.command(name="wcscoreboard", description="Show scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data,_ = load_data()
        embed = discord.Embed(title=f"{data['title']} - Scoreboard", color=discord.Color.gold())
        for item, score in data["scores"].items():
            embed.add_field(name=item,value=str(score),inline=True)
        await interaction.response.send_message(embed=embed)

    @tree.command(name="endwc", description="Announce winner of the World Cup")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data,_ = load_data()
        winner = data.get("last_winner")
        if not winner:
            await interaction.response.send_message("❌ No winner to announce yet.", ephemeral=True)
            return
        embed = discord.Embed(title=f"🎉 {data['title']} World Cup Winner!", description=f"🏆 {winner}", color=discord.Color.green())
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
        await interaction.response.send_message("@everyone, we have a World Cup winner!", embed=embed)

    @tree.command(name="listwcitems", description="List all items")
    async def listwcitems(interaction: discord.Interaction):
        data,_ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 Items:\n" + "\n".join(data["items"]))

    @tree.command(name="wchelp", description="Show World Cup instructions")
    async def wchelp(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        text = (
            "🎮 **World Cup Instructions** 🎮\n"
            "/addwcitem item1,item2,... → Add items (32 needed to start)\n"
            "/listwcitems → List all items\n"
            "/startwc title → Start the World Cup\n"
            "/nextwcmatch → Run the next matchup\n"
            "/showwcmatchup → Show current matchup\n"
            "/wcscoreboard → Show current scores\n"
            "/endwc → Announce the winner\n"
            "/resetwc → Reset the World Cup"
        )
        await interaction.response.send_message(text, ephemeral=True)
