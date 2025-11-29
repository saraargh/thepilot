# tournament.py (Part 1)

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
            return r.json().get("content", {}).get("sha")
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

    # Ensure last reaction counts
    for uid in a_users & b_users:
        # If user reacted to both, keep only last emoji (VOTE_B if reacted last)
        if uid in b_users:
            a_users.discard(uid)
            a_names.pop(uid, None)
        else:
            b_users.discard(uid)
            b_names.pop(uid, None)

    return len(a_users), len(b_users), a_names, b_names

# ------------------- Main setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

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
        from discord.ui import View, Button

        data, _ = load_data()
        items = data.get("items", [])
        if not items:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return

        # Pagination view
        class ItemsView(View):
            def __init__(self, items_list, per_page=10):
                super().__init__(timeout=None)
                self.items_list = items_list
                self.per_page = per_page
                self.page = 0

            def get_page_embed(self):
                start = self.page * self.per_page
                end = start + self.per_page
                page_items = self.items_list[start:end]
                desc = "\n".join(f"{i+1}. {item}" for i, item in enumerate(page_items, start=start))
                embed = discord.Embed(title="📋 World Cup Items", description=desc, color=discord.Color.teal())
                embed.set_footer(text=f"Page {self.page+1}/{(len(self.items_list)-1)//self.per_page+1}")
                return embed

            @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
            async def prev_page(self, interaction2: discord.Interaction, button: Button):
                self.page = max(self.page - 1, 0)
                await interaction2.response.edit_message(embed=self.get_page_embed(), view=self)

            @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
            async def next_page(self, interaction2: discord.Interaction, button: Button):
                max_page = (len(self.items_list)-1)//self.per_page
                self.page = min(self.page + 1, max_page)
                await interaction2.response.edit_message(embed=self.get_page_embed(), view=self)

        view = ItemsView(items)
        await interaction.response.send_message(embed=view.get_page_embed(), view=view, ephemeral=False)
        # tournament.py (Part 2)

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup tournament")
    async def startwc(interaction: discord.Interaction):
        data, sha = load_data()
        if data.get("running"):
            await interaction.response.send_message("⚠️ Tournament already running.", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Need at least 2 items to start.", ephemeral=True)
            return

        # Shuffle and create first round
        items = data["items"].copy()
        random.shuffle(items)
        data["current_round"] = []
        while len(items) >= 2:
            a = items.pop()
            b = items.pop()
            data["current_round"].append({"a": a, "b": b, "winner": None, "message_id": None, "channel_id": None})
        data["next_round"] = []
        data["running"] = True
        data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"])*2, "Matchup")
        sha = save_data(data, sha)
        await interaction.response.send_message("✅ Tournament started! First matchup posted quietly.", ephemeral=False)

        # Post first matchup quietly
        await post_next_matchup(interaction.channel, data, sha, announce=False)

    # ------------------- Voting logic -------------------
    async def post_next_matchup(channel, data, sha, announce=True):
        if not data["current_round"]:
            await channel.send("🏆 Tournament finished!")
            data["running"] = False
            save_data(data, sha)
            return

        match = data["current_round"].pop(0)
        a = match["a"]
        b = match["b"]
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage','Matchup')}",
            description=f"{VOTE_A} {a}\n{VOTE_B} {b}",
            color=discord.Color.random()
        )
        embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*", icon_url=None)

        msg = await channel.send(embed=embed)
        match["message_id"] = msg.id
        match["channel_id"] = channel.id
        data["last_match"] = match
        save_data(data, sha)

        await msg.add_reaction(VOTE_A)
        await msg.add_reaction(VOTE_B)

        # Start vote update loop
        async def update_votes_loop():
            while True:
                a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.id, msg.id)
                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                embed.description = desc
                try:
                    await msg.edit(embed=embed)
                except Exception:
                    pass
                await asyncio.sleep(2)

        asyncio.create_task(update_votes_loop())

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="End current matchup and post next round")
    async def nextwcround(interaction: discord.Interaction):
        data, sha = load_data()
        last_match = data.get("last_match")
        if not last_match:
            await interaction.response.send_message("⚠️ No active matchup.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(last_match["channel_id"])
        msg = await channel.fetch_message(last_match["message_id"])
        a_count, b_count, _, _ = await count_votes_from_message(channel.guild, msg.id, msg.id)
        winner = last_match["a"] if a_count >= b_count else last_match["b"]
        last_match["winner"] = winner
        data["next_round"].append(winner)
        data["finished_matches"].append(last_match)
        data["last_winner"] = winner
        data["last_match"] = None
        sha = save_data(data, sha)

        await interaction.response.send_message(f"✅ Winner: **{winner}**. Next matchup posted!", ephemeral=False)
        await post_next_matchup(channel, data, sha, announce=True)

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show the current World Cup matchups")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        embed = discord.Embed(title="🎮 World Cup Matchups", color=discord.Color.gold())
        desc = ""
        if data.get("current_round"):
            desc += "**Current Round:**\n"
            for m in data["current_round"]:
                desc += f"{m['a']} vs {m['b']}\n"
        if data.get("next_round"):
            desc += "\n**Next Round Winners:**\n"
            desc += ", ".join(data["next_round"])
        if not desc:
            desc = "_No matchups currently_"
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=False)
        # tournament.py (Part 3)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup tournament")
    async def resetwc(interaction: discord.Interaction):
        data, sha = load_data()
        data["current_round"] = []
        data["next_round"] = []
        data["finished_matches"] = []
        data["last_match"] = None
        data["running"] = False
        data["items"] = []
        data["round_stage"] = "Matchup"
        sha = save_data(data, sha)
        await interaction.response.send_message("♻️ Tournament reset.", ephemeral=False)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Show World Cup commands and usage")
    async def wchelp(interaction: discord.Interaction):
        help_text = (
            "**World Cup Commands:**\n"
            "/addwcitem — Add item(s) to the World Cup\n"
            "/listwcitems — List all items in the World Cup\n"
            "/startwc — Start the tournament\n"
            "/nextwcround — End current matchup & post next\n"
            "/showwcmatchups — Show current matchups\n"
            "/resetwc — Reset the tournament\n"
            "/wchelp — Show this help"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="Force end the World Cup tournament")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()
        if not data.get("running"):
            await interaction.response.send_message("⚠️ Tournament not running.", ephemeral=True)
            return
        data["running"] = False
        save_data(data, sha)
        await interaction.response.send_message("🏁 Tournament ended.", ephemeral=False)

    # ------------------- Count votes from message -------------------
    async def count_votes_from_message(guild, message_id, channel_id):
        channel = guild.get_channel(channel_id)
        msg = await channel.fetch_message(message_id)
        a_count = 0
        b_count = 0
        a_names = {}
        b_names = {}
        for reaction in msg.reactions:
            users = await reaction.users().flatten()
            for user in users:
                if user.bot:
                    continue
                if str(reaction.emoji) == VOTE_A:
                    a_count += 1
                    a_names[user.id] = user.display_name
                elif str(reaction.emoji) == VOTE_B:
                    b_count += 1
                    b_names[user.id] = user.display_name

        # Ensure vote switching is reflected immediately
        common_users = set(a_names.keys()) & set(b_names.keys())
        for uid in common_users:
            # Keep only the latest vote (removes from first)
            if msg.reactions[0].emoji == VOTE_A:
                b_count -= 1
                b_names.pop(uid, None)
            else:
                a_count -= 1
                a_names.pop(uid, None)

        return a_count, b_count, a_names, b_names

    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        sha = save_data(data, sha)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s).", ephemeral=False)

    # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    if not data["items"]:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return

    # Chunk into pages of max 25 items for Discord embed limit
    chunks = [data["items"][i:i + 25] for i in range(0, len(data["items"]), 25)]
    page = 0

    embed = discord.Embed(title="📋 World Cup Items", color=discord.Color.teal())
    embed.description = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(chunks[page], start=page*25))
    msg = await interaction.response.send_message(embed=embed, ephemeral=False)
    msg = await interaction.original_response()

    # Add arrow reactions for navigation if multiple pages
    if len(chunks) > 1:
        await msg.add_reaction("⬅️")
        await msg.add_reaction("➡️")

        def check(reaction, user):
            return (
                reaction.message.id == msg.id
                and str(reaction.emoji) in ["⬅️", "➡️"]
                and not user.bot
            )

        while True:
            try:
                reaction, user = await client.wait_for("reaction_add", timeout=120.0, check=check)
            except asyncio.TimeoutError:
                break  # stop listening after timeout
            else:
                if str(reaction.emoji) == "➡️" and page < len(chunks) - 1:
                    page += 1
                elif str(reaction.emoji) == "⬅️" and page > 0:
                    page -= 1

                # Update embed
                new_embed = discord.Embed(title="📋 World Cup Items", color=discord.Color.teal())
                new_embed.description = "\n".join(
                    f"{i + 1}. {item}" for i, item in enumerate(chunks[page], start=page*25)
                )
                await msg.edit(embed=new_embed)

                # Remove user's reaction to allow repeated clicks
                try:
                    await msg.remove_reaction(reaction, user)
                except:
                    pass
        