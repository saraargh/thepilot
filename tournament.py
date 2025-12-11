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
            # ensure all keys exist
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
            "content": base64.b64encode(
                json.dumps(data, indent=4).encode()
            ).decode()
        }
        if sha:
            payload["sha"] = sha

        r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload))
        if r.status_code in (200, 201):
            new_sha = r.json().get("content", {}).get("sha")
            return new_sha
        return sha
    except Exception as e:
        print("Error saving data:", e)
        return sha

# ------------------- Utilities -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

async def count_votes_from_message(guild, channel_id, message_id):
    """Count unique voters for 🔴 and 🔵, removing double-voters."""
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            return 0, 0, {}, {}
        msg = await channel.fetch_message(message_id)
    except Exception as e:
        print("Error fetching message:", e)
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

    # remove people who voted on both
    dupes = a_users & b_users
    for uid in dupes:
        if uid in b_users:
            a_users.remove(uid)
            a_names.pop(uid, None)
        else:
            b_users.remove(uid)
            b_names.pop(uid, None)

    return len(a_users), len(b_users), a_names, b_names

# ------------------- Main Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ------------------- Scoreboard (paginated) -------------------
    async def scoreboard_internal(interaction: discord.Interaction, data: dict):
        """Post a paginated scoreboard with arrows, visible to everyone."""

        channel = interaction.channel
        user = interaction.user
        client = interaction.client

        finished = data.get("finished_matches", [])
        running = data.get("running", False)
        title = data.get("title") or "No active cup"
        stage = data.get("round_stage") or (
            "Finished" if (not running and data.get("last_winner")) else "Not started"
        )

        # Build finished match lines
        finished_lines = [
            f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} "
            f"({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
            for i, f in enumerate(finished)
        ]

        if not finished_lines:
            finished_lines = ["No matches played yet."]

        # Chunk finished into pages of 10 lines
        finished_pages = [finished_lines[i:i+10] for i in range(0, len(finished_lines), 10)]

        # Build upcoming lines (all on their own page type)
        current_round = data.get("current_round", []).copy()
        upcoming_lines = []
        for i in range(0, len(current_round), 2):
            if i + 1 < len(current_round):
                upcoming_lines.append(f"{current_round[i]} vs {current_round[i+1]}")
            else:
                upcoming_lines.append(f"{current_round[i]} (auto-advance)")

        if not upcoming_lines:
            upcoming_lines = ["No upcoming matches."]

        upcoming_pages = [upcoming_lines[i:i+10] for i in range(0, len(upcoming_lines), 10)]

        # Page list: tuples (kind, lines)
        pages = []

        # First page MUST be finished matches (first chunk)
        for idx, chunk in enumerate(finished_pages):
            pages.append(("finished", chunk))

        # Upcoming pages added afterwards (own page type)
        for chunk in upcoming_pages:
            pages.append(("upcoming", chunk))

        total_pages = len(pages)
        current_index = 0

        def make_embed(page_index: int) -> discord.Embed:
            kind, lines = pages[page_index]

            embed = discord.Embed(
                title=f"📊 World Cup Scoreboard — {title}",
                color=discord.Color.teal()
            )
            # Header on every page
            embed.add_field(name="Stage", value=stage, inline=False)

            # Current match only on page 1
            if page_index == 0:
                lm = data.get("last_match")
                if lm:
                    current_val = f"{lm['a']} vs {lm['b']} (voting now)"
                elif (not running) and data.get("last_winner"):
                    current_val = f"Tournament finished. Winner: **{data['last_winner']}**"
                else:
                    current_val = "No match currently in progress."
                embed.add_field(name="Current Match", value=current_val, inline=False)

            if kind == "finished":
                name = "Finished Matches"
            else:
                name = "Upcoming Matches"

            value = "\n".join(lines)
            if not value:
                value = "None."

            # Discord limit safe-guard
            if len(value) > 1024:
                value = value[:1021] + "..."

            embed.add_field(name=name, value=value, inline=False)
            embed.set_footer(text=f"Page {page_index+1}/{total_pages}")
            return embed

        # Send first page
        msg = await channel.send(embed=make_embed(0))

        # If only one page, no arrows
        if total_pages == 1:
            return

        await msg.add_reaction("⬅️")
        await msg.add_reaction("➡️")

        def check(reaction, u):
            return (
                u == user
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while True:
            try:
                reaction, u = await client.wait_for("reaction_add", timeout=120, check=check)

                emoji = str(reaction.emoji)
                if emoji == "➡️" and current_index < total_pages - 1:
                    current_index += 1
                elif emoji == "⬅️" and current_index > 0:
                    current_index -= 1

                await msg.edit(embed=make_embed(current_index))

                try:
                    await msg.remove_reaction(reaction.emoji, u)
                except Exception:
                    pass

            except asyncio.TimeoutError:
                break

    # ------------------- Post Next Match -------------------
    async def post_next_match(channel, data, sha):
        """Pop next pair from current_round and post the voting embed, with live updating."""
        if len(data["current_round"]) < 2:
            return sha

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)
        sha = save_data(data, sha)

        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage', 'Matchup')}",
            description=f"{VOTE_A} {a}\n\n_No votes yet_\n\n{VOTE_B} {b}\n\n_No votes yet_",
            color=discord.Color.random()
        )
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

        # live update loop
        client = channel.guild._state._get_client()

        def check(reaction, user):
            return (
                user != channel.guild.me
                and reaction.message.id == msg.id
                and str(reaction.emoji) in (VOTE_A, VOTE_B)
            )

        async def reaction_loop():
            while data.get("last_match") and data["last_match"]["message_id"] == msg.id:
                try:
                    reaction, user = await client.wait_for("reaction_add", check=check)

                    a_count, b_count, a_names, b_names = await count_votes_from_message(
                        channel.guild, msg.channel.id, msg.id
                    )

                    desc = f"{VOTE_A} {a} — {a_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                    desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                    await msg.edit(embed=discord.Embed(
                        title=f"🎮 {data.get('round_stage', 'Matchup')}",
                        description=desc,
                        color=discord.Color.random()
                    ))
                except Exception:
                    continue

        asyncio.create_task(reaction_loop())
        return sha

    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup")
    @app_commands.describe(items="Comma-separated list")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

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
            return await interaction.response.send_message(
                f"✅ Added: {', '.join(added)}", ephemeral=False
            )
        return await interaction.response.send_message("⚠️ No new items added.", ephemeral=False)

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove item(s) (case-insensitive)")
    @app_commands.describe(items="Comma-separated list")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        remove_list = [x.strip() for x in items.split(",") if x.strip()]
        removed = []

        lower_map = {i.lower(): i for i in data["items"]}

        for it in remove_list:
            key = it.lower()
            if key in lower_map:
                original = lower_map[key]
                data["items"].remove(original)
                data["scores"].pop(original, None)
                removed.append(original)

        sha = save_data(data, sha)

        if removed:
            return await interaction.response.send_message(
                f"✅ Removed: {', '.join(removed)}", ephemeral=False
            )
        return await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)

    # ------------------- /listwcitems (paginated) -------------------
    @tree.command(name="listwcitems", description="List all items in a paginated menu")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])

        if not items:
            return await interaction.response.send_message("No items added yet.", ephemeral=True)

        pages = [items[i:i+10] for i in range(0, len(items), 10)]
        total_pages = len(pages)
        current_page = 0

        def make_embed(page_index: int) -> discord.Embed:
            embed = discord.Embed(
                title="📋 World Cup Items",
                description="\n".join(
                    f"{(page_index*10)+i+1}. {item}"
                    for i, item in enumerate(pages[page_index])
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Page {page_index+1}/{total_pages}")
            return embed

        await interaction.response.send_message(embed=make_embed(0))
        msg = await interaction.original_response()

        if total_pages == 1:
            return

        await msg.add_reaction("⬅️")
        await msg.add_reaction("➡️")

        client = interaction.client

        def check(reaction, user):
            return (
                user == interaction.user
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while True:
            try:
                reaction, user = await client.wait_for("reaction_add", timeout=120, check=check)

                emoji = str(reaction.emoji)
                if emoji == "➡️" and current_page < total_pages - 1:
                    current_page += 1
                elif emoji == "⬅️" and current_page > 0:
                    current_page -= 1

                await msg.edit(embed=make_embed(current_page))

                try:
                    await msg.remove_reaction(reaction.emoji, user)
                except Exception:
                    pass

            except asyncio.TimeoutError:
                break

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup (requires 32 items)")
    @app_commands.describe(title="World Cup title")
    async def startwc(interaction: discord.Interaction, title: str):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ No permission.", ephemeral=True)

        data, sha = load_data()

        if data["running"]:
            return await interaction.followup.send("❌ A World Cup is already running.", ephemeral=True)

        if len(data["items"]) != 32:
            return await interaction.followup.send("❌ You must have exactly 32 items.", ephemeral=True)

        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["finished_matches"] = []
        data["last_match"] = None
        data["last_winner"] = None
        data["running"] = True
        data["round_stage"] = STAGE_BY_COUNT.get(32, "Round of 32")

        sha = save_data(data, sha)

        await interaction.channel.send(
            f"@everyone The World Cup of **{title}** is starting — see the matchups and start voting! 🏆"
        )

        # Post initial scoreboard with pagination
        await scoreboard_internal(interaction, data)

        # Post first matchup
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)

        return await interaction.followup.send("✅ World Cup started.", ephemeral=True)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Process current match → move on")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        if not data.get("running"):
            return await interaction.followup.send("❌ No active World Cup.", ephemeral=True)

        guild = interaction.guild

        # ----- PROCESS LAST MATCH (if any) -----
        if data.get("last_match"):
            lm = data["last_match"]

            a_votes, b_votes, _, _ = await count_votes_from_message(
                guild, lm["channel_id"], lm["message_id"]
            )

            a = lm["a"]
            b = lm["b"]

            if a_votes > b_votes:
                winner = a
            elif b_votes > a_votes:
                winner = b
            else:
                winner = random.choice([a, b])

            data["finished_matches"].append({
                "a": a,
                "b": b,
                "winner": winner,
                "a_votes": a_votes,
                "b_votes": b_votes
            })

            data["next_round"].append(winner)
            data["scores"][winner] = data["scores"].get(winner, 0) + 1

            data["last_match"] = None
            data["last_winner"] = winner

            sha = save_data(data, sha)

            # Announce match result (same for all rounds, including finals)
            result_embed = discord.Embed(
                title="Previous Match Result! 🏆",
                description=f"**{winner}** won the previous match!\n\n"
                            f"{VOTE_A} {a}: {a_votes} votes\n"
                            f"{VOTE_B} {b}: {b_votes} votes",
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=result_embed)

            # If this was the FINAL (no more pairs, and only one contender in next_round),
            # we do NOT auto-promote. User must /endwc to announce the winner.
            if len(data["current_round"]) == 0 and len(data["next_round"]) == 1 and data.get("round_stage") == "Finals":
                sha = save_data(data, sha)
                return await interaction.followup.send(
                    "✔️ Match processed.\n❌ No more rounds left.\nUse `/endwc` to announce the winner.",
                    ephemeral=True
                )

            # Otherwise, if more pairs left in THIS round, post next matchup
            if len(data["current_round"]) >= 2:
                await interaction.channel.send(
                    f"@everyone The next fixture in The World Cup of **{data['title']}** is ready — cast your votes below! 🗳️"
                )
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("✔️ Match processed.", ephemeral=True)

        # ----- NO last_match: maybe time to move to the next round or we are done -----
        if not data["current_round"] and data["next_round"]:
            # If exactly one contender is left, finals have been played already.
            if len(data["next_round"]) == 1:
                data["last_winner"] = data["next_round"][0]
                sha = save_data(data, sha)
                return await interaction.followup.send(
                    "❌ No more rounds left.\nUse `/endwc` to announce the winner.",
                    ephemeral=True
                )

            # Normal promotion (32→16, 16→8, etc). Double /nextwcround behaviour stays.
            prev_stage = data["round_stage"]
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []

            new_len = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_len, f"{new_len}-items round")
            sha = save_data(data, sha)

            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"Now entering **{data['round_stage']}**\n\n"
                            f"Remaining: {', '.join(data['current_round'])}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            if new_len >= 2:
                await interaction.channel.send(
                    f"@everyone The next fixture in The World Cup of **{data['title']}** is ready — cast your votes below! 🗳️"
                )
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

        # Nothing to do
        return await interaction.followup.send("ℹ️ Nothing to process right now.", ephemeral=True)

    # ------------------- /scoreboard -------------------
    @tree.command(name="scoreboard", description="Show tournament scoreboard (paginated)")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        await interaction.response.defer(ephemeral=True)
        await scoreboard_internal(interaction, data)
        return await interaction.followup.send("📊 Scoreboard posted.", ephemeral=True)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset everything")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)

        return await interaction.response.send_message("🔄 World Cup reset.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="Announce the winner and end the World Cup")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = load_data()

        if not data.get("running"):
            return await interaction.response.send_message("❌ No active World Cup to end.", ephemeral=True)

        winner = data.get("last_winner")
        if not winner and data.get("next_round"):
            # Fallback: if finals were processed but last_winner somehow missing
            winner = data["next_round"][0]
            data["last_winner"] = winner
            sha = save_data(data, sha)

        if not winner:
            return await interaction.response.send_message(
                "❌ No winner found yet. Make sure the final match has been processed with `/nextwcround`.",
                ephemeral=True
            )

        await interaction.channel.send(f"@everyone We have a winner of The World Cup of **{data.get('title')}** ‼️👀")

        embed = discord.Embed(
            title="🏁 Tournament Winner!",
            description=f"🎉 **{winner}** wins the **World Cup of {data.get('title')}**!",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")

        await interaction.channel.send(embed=embed)

        data["running"] = False
        save_data(data, sha)

        return await interaction.response.send_message("✔️ Winner announced and World Cup ended.", ephemeral=True)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Help menu")
    async def wchelp(interaction: discord.Interaction):
        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())
        embed.add_field(name="/addwcitem", value="(Mod only) Add items", inline=False)
        embed.add_field(name="/removewcitem", value="(Mod only) Remove items", inline=False)
        embed.add_field(name="/listwcitems", value="List all items (paginated)", inline=False)
        embed.add_field(name="/startwc", value="(Mod only) Start World Cup (needs 32 items)", inline=False)
        embed.add_field(name="/nextwcround", value="(Mod only) Process match / move to next", inline=False)
        embed.add_field(name="/scoreboard", value="Show scoreboard (paginated)", inline=False)
        embed.add_field(name="/resetwc", value="(Mod only) Reset everything", inline=False)
        embed.add_field(name="/endwc", value="(Mod only) Announce winner and end", inline=False)

        return await interaction.response.send_message(embed=embed, ephemeral=True)