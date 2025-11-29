import discord
from discord import app_commands
import asyncio
import random
import base64
import json
import requests
import os

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Allowed Roles -------------------
DEFAULT_ALLOWED_ROLES = [
    1413545658006110401,
    1404098545006546954,
    1420817462290681936,
    1406242523952713820
]

# ------------------- Default Data -------------------
DEFAULT_DATA = {
    "items": [],
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None
}

# ------------------- GitHub Helpers -------------------
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
            return data, sha
        elif r.status_code == 404:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
        else:
            sha = save_data(DEFAULT_DATA.copy())
            return DEFAULT_DATA.copy(), sha
    except Exception:
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
        return r.json().get("content", {}).get("sha")
    return sha

# ------------------- Helper Functions -------------------
def user_allowed(member: discord.Member, allowed_roles=None):
    allowed_roles = allowed_roles or DEFAULT_ALLOWED_ROLES
    return any(role.id in allowed_roles for role in member.roles)

def get_round_name(num_items):
    return {
        32: "Round of 32",
        16: "Round of 16",
        8: "Quarter Finals",
        4: "Semi Finals",
        2: "Final"
    }.get(num_items, "Unknown Round")

# ------------------- Tournament Commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids=None):
    allowed_role_ids = allowed_role_ids or DEFAULT_ALLOWED_ROLES

    def can_use(interaction: discord.Interaction):
        return user_allowed(interaction.user, allowed_role_ids)

    async def run_match(interaction: discord.Interaction, a_item, b_item, data, sha):
        votes = {"🔴": [], "🔵": []}
        embed = discord.Embed(
            title=f"🗳️ Vote for the winner!",
            description=f"🔴 {a_item}\n🔵 {b_item}",
            color=discord.Color.random()
        )
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("🔴")
        await msg.add_reaction("🔵")

        def check(reaction, user):
            return str(reaction.emoji) in ["🔴", "🔵"] and not user.bot

        while True:
            try:
                reaction, user = await interaction.client.wait_for(
                    "reaction_add", timeout=300, check=check
                )
                other_emoji = "🔵" if str(reaction.emoji) == "🔴" else "🔴"
                if user.id in votes[other_emoji]:
                    votes[other_emoji].remove(user.id)
                    await msg.remove_reaction(other_emoji, user)
                if user.id not in votes[str(reaction.emoji)]:
                    votes[str(reaction.emoji)].append(user.id)

                desc = (
                    f"🔴 {a_item}\n" + "\n".join(f"- <@{uid}>" for uid in votes["🔴"]) + "\n\n"
                    f"🔵 {b_item}\n" + "\n".join(f"- <@{uid}>" for uid in votes["🔵"])
                )
                embed.description = desc
                await msg.edit(embed=embed)
            except asyncio.TimeoutError:
                break

        winner = a_item if len(votes["🔴"]) >= len(votes["🔵"]) else b_item
        data["scores"][winner] += 1
        data["last_winner"] = winner
        save_data(data, sha)
        await interaction.channel.send(f"🏆 {winner} wins this match!")
        return winner

    # ---------------- /startwc ----------------
    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running.", ephemeral=True)
            return
        if len(data["items"]) < 32:
            await interaction.response.send_message("❌ You must have 32 items to start.", ephemeral=True)
            return
        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        save_data(data, sha)
        await interaction.response.send_message(f"@everyone 🎉 The World Cup of {title} is starting! 🏁", ephemeral=False)
        if len(data["current_round"]) >= 2:
            await run_match(interaction, data["current_round"][0], data["current_round"][1], data, sha)

    # ---------------- /nextwcround ----------------
    @tree.command(name="nextwcround", description="Run the next match in the World Cup")
    async def nextwcround(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup is active.", ephemeral=True)
            return
        if len(data["current_round"]) < 2:
            if data["next_round"]:
                data["current_round"] = data["next_round"].copy()
                data["next_round"] = []
                save_data(data, sha)
                round_name = get_round_name(len(data["current_round"]))
                await interaction.channel.send(f"✅ Previous round complete! {round_name} starts now with {len(data['current_round'])} items.")
            else:
                await interaction.response.send_message("❌ No matches left.", ephemeral=True)
                return
        a_item = data["current_round"].pop(0)
        b_item = data["current_round"].pop(0)
        winner = await run_match(interaction, a_item, b_item, data, sha)
        data["next_round"].append(winner)
        save_data(data, sha)
        if not data["current_round"]:
            round_name = get_round_name(len(data["next_round"]))
            await interaction.channel.send(f"✅ This round is complete! {round_name} will start next with {len(data['next_round'])} items.")

    # ---------------- /endwc ----------------
    @tree.command(name="endwc", description="Announce the winner of the World Cup")
    async def endwc(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No World Cup is active.", ephemeral=True)
            return
        winner = data.get("last_winner")
        if not winner:
            await interaction.response.send_message("❌ No winner has been decided yet.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🏆 The World Cup of {data['title']} has ended!",
            description=f"🎉 Congratulations to **{winner}**! Thank you everyone for voting! \n\nUse `/resetwc` to reset the World Cup.",
            color=discord.Color.gold()
        )
        await interaction.channel.send(f"@everyone, we have a World Cup of {data['title']} winner 🏆", embed=embed)
        data["running"] = False
        save_data(data, sha)

    # ---------------- /showwcmatchup ----------------
    @tree.command(name="showwcmatchup", description="Show the current World Cup match")
    async def showwcmatchup(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["running"] or len(data["current_round"]) < 2:
            await interaction.response.send_message("❌ No active match at the moment.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Next World Cup Match",
            description=f"🔴 {data['current_round'][0]}\n🔵 {data['current_round'][1]}",
            color=discord.Color.random()
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------------- /wcscoreboard ----------------
    @tree.command(name="wcscoreboard", description="Show the current World Cup scoreboard")
    async def wcscoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["scores"]:
            await interaction.response.send_message("❌ No scoreboard available.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📊 Scoreboard for {data['title']}", color=discord.Color.blue())
        for item, score in data["scores"].items():
            embed.add_field(name=item, value=str(score), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------------- /resetwc ----------------
    @tree.command(name="resetwc", description="Reset the World Cup (clears items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.", ephemeral=False)

    # ---------------- /wchelp ----------------
    @tree.command(name="wchelp", description="Show World Cup instructions")
    async def wchelp(interaction: discord.Interaction):
        if not can_use(interaction):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        embed = discord.Embed(title="📖 World Cup Commands Help", color=discord.Color.green())
        embed.add_field(name="/startwc <title>", value="Start the World Cup. Must have 32 items added first.", inline=False)
        embed.add_field(name="/nextwcround", value="Run the next match. Announces previous winner.", inline=False)
        embed.add_field(name="/showwcmatchup", value="Shows the current match.", inline=False)
        embed.add_field(name="/wcscoreboard", value="View the current scores.", inline=False)
        embed.add_field(name="/endwc", value="Announce winner of the World Cup.", inline=False)
        embed.add_field(name="/resetwc", value="Reset the World Cup data.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)