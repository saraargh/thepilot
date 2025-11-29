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

    # Enforce last vote wins logic
    final_a = {}
    final_b = {}
    for uid, name in {**a_users, **b_users}.items():
        if uid in a_users and uid in b_users:
            # get last reaction in order (discord may not guarantee)
            final_b[uid] = name  # assume last is B if exists
        elif uid in a_users:
            final_a[uid] = name
        elif uid in b_users:
            final_b[uid] = name

    return len(final_a), len(final_b), final_a, final_b
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
        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*", icon_url=None)

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
            while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
                a_count, b_count, a_names, b_names = await count_votes_from_message(channel.guild, msg.channel.id, msg.id)
                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"{n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"{n}" for n in b_names.values()]) or "_No votes yet_"

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

                await asyncio.sleep(2)  # Update every 2 seconds

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

    # ------------------- /listwcitems (with pagination and correct numbering) -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return

        # Paginate 25 items per page (Discord field limit)
        items_per_page = 25
        pages = [data["items"][i:i + items_per_page] for i in range(0, len(data["items"]), items_per_page)]
        current_page = 0

        embed = discord.Embed(title=f"📋 World Cup Items (Page {current_page+1}/{len(pages)})", color=discord.Color.teal())
        for idx, item in enumerate(pages[current_page], start=current_page*items_per_page+1):
            embed.add_field(name=f"{idx}. {item}", value="\u200b", inline=False)

        msg = await interaction.response.send_message(embed=embed, ephemeral=False)

        # Add navigation reactions if multiple pages
        if len(pages) > 1:
            msg = await interaction.original_response()
            await msg.add_reaction("◀️")
            await msg.add_reaction("▶️")

            def check(reaction, user):
                return user != msg.author and str(reaction.emoji) in ["◀️","▶️"] and reaction.message.id == msg.id

            async def paginate():
                nonlocal current_page
                while True:
                    try:
                        reaction, user = await interaction.client.wait_for("reaction_add", check=check, timeout=120)
                    except asyncio.TimeoutError:
                        break
                    if str(reaction.emoji) == "▶️" and current_page+1 < len(pages):
                        current_page += 1
                    elif str(reaction.emoji) == "◀️" and current_page > 0:
                        current_page -= 1
                    else:
                        continue

                    embed = discord.Embed(title=f"📋 World Cup Items (Page {current_page+1}/{len(pages)})", color=discord.Color.teal())
                    for idx, item in enumerate(pages[current_page], start=current_page*items_per_page+1):
                        embed.add_field(name=f"{idx}. {item}", value="\u200b", inline=False)
                    await msg.edit(embed=embed)
                    try:
                        await msg.remove_reaction(reaction, user)
                    except:
                        pass

            asyncio.create_task(paginate())
                # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()
        if len(data["items"]) < 2:
            await interaction.response.send_message("⚠️ Not enough items to start the World Cup.", ephemeral=True)
            return

        random.shuffle(data["items"])
        data["current_round"] = data["items"].copy()
        data["round_stage"] = "Round 1"
        sha = save_data(data, sha)

        channel = interaction.channel
        sha = await post_next_match(channel, data, sha)
        await interaction.response.send_message("✅ World Cup started!", ephemeral=False)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Post the next World Cup matchup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()
        channel = interaction.channel
        if not data.get("current_round") or len(data["current_round"]) < 2:
            await interaction.response.send_message("⚠️ No more matchups left.", ephemeral=True)
            return

        sha = await post_next_match(channel, data, sha)
        await interaction.response.send_message("✅ Next matchup posted!", ephemeral=False)

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show current World Cup matchups")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        if not data.get("current_round"):
            await interaction.response.send_message("No matchups in progress.", ephemeral=True)
            return
        desc = "\n".join(f"{i+1}. {item}" for i, item in enumerate(data["current_round"]))
        embed = discord.Embed(title="📋 Current World Cup Matchups", description=desc, color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        data["current_round"] = []
        data["last_match"] = {}
        data["scores"] = {k: 0 for k in data["items"]}
        data["round_stage"] = ""
        sha = save_data(data, sha)
        await interaction.response.send_message("✅ World Cup reset.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="End the World Cup and show results")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, _ = load_data()
        if not data["scores"]:
            await interaction.response.send_message("No results to show.", ephemeral=True)
            return
        sorted_scores = sorted(data["scores"].items(), key=lambda x: x[1], reverse=True)
        desc = "\n".join(f"{i+1}. {item} — {score} votes" for i, (item, score) in enumerate(sorted_scores))
        embed = discord.Embed(title="🏆 World Cup Results", description=desc, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Show World Cup command help")
    async def wchelp(interaction: discord.Interaction):
        embed = discord.Embed(title="📚 World Cup Commands", color=discord.Color.blue())
        cmds = [
            "/startwc — Start the World Cup",
            "/nextwcround — Post the next matchup",
            "/showwcmatchups — Show current matchups",
            "/addwcitem — Add item(s) to the World Cup",
            "/removewcitem — Remove item(s) from the World Cup",
            "/listwcitems — List all items in the World Cup",
            "/resetwc — Reset the World Cup",
            "/endwc — End the World Cup and show results",
            "/wchelp — Show this help embed"
        ]
        embed.description = "\n".join(cmds)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ------------------- Voting Toggle Fix -------------------
    async def count_votes_from_message(guild, channel_id, message_id):
        channel = guild.get_channel(channel_id)
        msg = await channel.fetch_message(message_id)
        a_count = b_count = 0
        a_names = {}
        b_names = {}
        for reaction in msg.reactions:
            if str(reaction.emoji) == VOTE_A:
                async for user in reaction.users():
                    if user.bot: continue
                    uid = user.id
                    a_names[uid] = user.display_name
            elif str(reaction.emoji) == VOTE_B:
                async for user in reaction.users():
                    if user.bot: continue
                    uid = user.id
                    b_names[uid] = user.display_name

        # Ensure toggle: remove opposite vote
        for uid in set(a_names.keys()) & set(b_names.keys()):
            # Decide which one to keep: most recent reaction stays
            if msg.reactions[VOTE_A].count > msg.reactions[VOTE_B].count:
                b_names.pop(uid, None)
            else:
                a_names.pop(uid, None)

        return len(a_names), len(b_names), a_names, b_names