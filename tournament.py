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

    a_users = {}
    b_users = {}

    for reaction in msg.reactions:
        emoji = str(reaction.emoji)
        if emoji not in (VOTE_A, VOTE_B):
            continue
        try:
            async for u in reaction.users():
                if u.bot:
                    continue
                if emoji == VOTE_A:
                    a_users[u.id] = u.display_name
                elif emoji == VOTE_B:
                    b_users[u.id] = u.display_name
        except Exception:
            pass

    # Enforce single vote: keep **last reaction**
    for uid in set(a_users.keys()) & set(b_users.keys()):
        if uid in b_users:
            a_users.pop(uid, None)
        else:
            b_users.pop(uid, None)

    return len(a_users), len(b_users), a_users, b_users

# ------------------- Main Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ------------------- Post Next Match -------------------
    async def post_next_match(channel, data, sha):
        if len(data["current_round"]) < 2:
            return sha

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)

        data["last_match"] = {"a": a, "b": b, "message_id": None, "channel_id": channel.id}
        sha = save_data(data, sha)

        # Embed with voter placeholders
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=f"{VOTE_A} {a}\n\n_No votes yet_\n\n{VOTE_B} {b}\n\n_No votes yet_",
            color=discord.Color.random()
        )
        embed.set_footer(text="_use /showwcmatchups to keep track of the World Cup!_", icon_url=None)

        await channel.send(f"@everyone, the next World Cup of {data['title']} fixture is upon us! 🗳️")
        msg = await channel.send(embed=embed)
        await msg.add_reaction(VOTE_A)
        await msg.add_reaction(VOTE_B)
        data["last_match"]["message_id"] = msg.id
        sha = save_data(data, sha)

        async def update_votes_loop():
            while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
                a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.channel.id, msg.id)
                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                embed = discord.Embed(
                    title=f"🎮 {data.get('round_stage','Matchup')}",
                    description=desc,
                    color=discord.Color.random()
                )
                embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*", icon_url=None)
                try:
                    await msg.edit(embed=embed)
                except Exception:
                    pass

                await asyncio.sleep(1)  # refresh every second

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
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        if not new_items:
            await interaction.response.send_message("❌ No valid items provided.", ephemeral=True)
            return
        data["items"].extend(new_items)
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s). Total now: {len(data['items'])}", ephemeral=True)

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to remove")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        rem_items = [i.strip() for i in items.split(",") if i.strip()]
        removed_count = 0
        for item in rem_items:
            if item in data["items"]:
                data["items"].remove(item)
                removed_count += 1
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Removed {removed_count} item(s). Total now: {len(data['items'])}", ephemeral=True)

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup with current items")
    @app_commands.describe(title="Optional tournament title")
    async def startwc(interaction: discord.Interaction, title: str = None):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ Tournament already running.", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Not enough items to start.", ephemeral=True)
            return

        random.shuffle(data["items"])
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {}
        data["running"] = True
        data["title"] = title or "World Cup"
        data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), f"{len(data['current_round'])}-item Round")
        sha = save_data(data, sha)

        await interaction.response.send_message(f"🏁 {data['title']} has started! First matchup will post now.", ephemeral=True)
        sha = await post_next_match(interaction.channel, data, sha)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Advance to the next round after a matchup finishes")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ Tournament is not running.", ephemeral=True)
            return

        # Winner from last match
        last_match = data.get("last_match")
        if last_match:
            channel = interaction.guild.get_channel(last_match["channel_id"])
            a_count, b_count, a_names, b_names = await count_votes_from_message(interaction.guild, last_match["channel_id"], last_match["message_id"])
            winner = last_match["a"] if a_count >= b_count else last_match["b"]
            data["next_round"].append(winner)
            data["finished_matches"].append({
                "a": last_match["a"],
                "b": last_match["b"],
                "winner": winner,
                "a_votes": a_count,
                "b_votes": b_count
            })
            data["last_winner"] = winner
            data["last_match"] = None
            sha = save_data(data, sha)
            await channel.send(f"🏆 **{winner}** wins and advances to the next round!")

        # Move to next round if current_round empty
        if not data["current_round"] and data["next_round"]:
            data["current_round"] = data["next_round"]
            data["next_round"] = []
            data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), f"{len(data['current_round'])}-item Round")
            sha = save_data(data, sha)

        # Post next match if available
        if len(data["current_round"]) >= 2:
            channel = interaction.channel
            sha = await post_next_match(channel, data, sha)
            await interaction.response.send_message(f"➡️ Next matchup posted.", ephemeral=False)
        else:
            data["running"] = False
            sha = save_data(data, sha)
            await interaction.response.send_message(f"🎉 Tournament finished! Winner: **{data['next_round'][0] if data['next_round'] else 'Unknown'}**", ephemeral=False)
            # ------------------- /listwcitems -------------------
@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    if not data["items"]:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return

    ITEMS_PER_PAGE = 10
    pages = [data["items"][i:i + ITEMS_PER_PAGE] for i in range(0, len(data["items"]), ITEMS_PER_PAGE)]
    current_page = 0

    embed = discord.Embed(
        title="📋 World Cup Items",
        description="\n".join([f"{i+1}. {item}" for i, item in enumerate(pages[current_page])]),
        color=discord.Color.teal()
    )
    embed.set_footer(text=f"Page {current_page + 1}/{len(pages)}")

    message = await interaction.response.send_message(embed=embed, ephemeral=False, fetch_response=True)

    if len(pages) == 1:
        return  # No need for buttons

    # Buttons for pagination
    class PageView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.page = current_page

        @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
        async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = (self.page - 1) % len(pages)
            embed.description = "\n".join([f"{i+1 + self.page*ITEMS_PER_PAGE}. {item}" for i, item in enumerate(pages[self.page])])
            embed.set_footer(text=f"Page {self.page + 1}/{len(pages)}")
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
        async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page = (self.page + 1) % len(pages)
            embed.description = "\n".join([f"{i+1 + self.page*ITEMS_PER_PAGE}. {item}" for i, item in enumerate(pages[self.page])])
            embed.set_footer(text=f"Page {self.page + 1}/{len(pages)}")
            await interaction.response.edit_message(embed=embed, view=self)

    await message.edit(view=PageView())

# ------------------- /resetwc -------------------
@tree.command(name="resetwc", description="Reset the World Cup tournament")
async def resetwc(interaction: discord.Interaction):
    if not user_allowed(interaction.user, allowed_role_ids):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    data, sha = load_data()
    data.update({
        "items": [],
        "current_round": [],
        "next_round": [],
        "scores": {},
        "running": False,
        "round_stage": "",
        "last_match": None,
        "finished_matches": [],
        "title": "",
        "last_winner": None
    })
    sha = save_data(data, sha)
    await interaction.response.send_message("✅ Tournament reset.", ephemeral=False)

# ------------------- /wchelp -------------------
@tree.command(name="wchelp", description="Show World Cup bot commands help")
async def wchelp(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 World Cup Commands", color=discord.Color.gold())
    embed.description = (
        "**/addwcitem <items>** - Add items to the tournament\n"
        "**/removewcitem <items>** - Remove items from the tournament\n"
        "**/listwcitems** - List all items (with pagination)\n"
        "**/startwc** - Start the tournament\n"
        "**/nextwcround** - Move to the next round\n"
        "**/resetwc** - Reset the tournament\n"
        "**/wchelp** - Show this help message"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)