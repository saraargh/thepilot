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
        return sha

    except Exception as e:
        print("SAVE ERROR:", e)
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

    except Exception:
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
        except:
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

    # Enforce 1 vote only
    dupes = a_users & b_users
    for uid in dupes:
        a_users.discard(uid)
        a_names.pop(uid, None)
        b_users.discard(uid)
        b_names.pop(uid, None)

    return len(a_users), len(b_users), a_names, b_names

# ------------------- MAIN COMMAND SETUP -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ---------- SCOREBOARD INTERNAL ----------
    async def scoreboard_internal(channel, data):
        finished = data.get("finished_matches", [])
        pages = [finished[i:i+10] for i in range(0, len(finished), 10)]

        if not finished:
            await channel.send("No matches played yet.")
            return

        async def make_embed(page_index):
            embed = discord.Embed(
                title=f"📊 Scoreboard – Page {page_index+1}/{len(pages)}",
                color=discord.Color.teal()
            )
            block = pages[page_index]

            desc = ""
            for m in block:
                desc += f"**{m['a']}** vs **{m['b']}** → **{m['winner']}**\n"
                desc += f"{VOTE_A} {m['a_votes']} | {VOTE_B} {m['b_votes']}\n\n"

            embed.description = desc[:4090]
            return embed

        # First page
        msg = await channel.send(embed=await make_embed(0))

        if len(pages) == 1:
            return

        await msg.add_reaction("⬅️")
        await msg.add_reaction("➡️")

        current_page = 0
        client = channel.guild._state._get_client()

        def check(reaction, user):
            return (
                user != channel.guild.me
                and user.bot is False
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while True:
            try:
                reaction, user = await client.wait_for("reaction_add", timeout=90, check=check)
                if str(reaction.emoji) == "➡️" and current_page < len(pages) - 1:
                    current_page += 1
                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                    current_page -= 1

                await msg.edit(embed=await make_embed(current_page))

                try:
                    await msg.remove_reaction(reaction.emoji, user)
                except:
                    pass

            except asyncio.TimeoutError:
                break

    # ---------- SHOW MATCHUPS INTERNAL ----------
    async def showwcmatchups_internal(channel, data):
        finished = data.get("finished_matches", [])
        finished_text = "\n".join(
            f"{i+1}. {m['a']} vs {m['b']} → {m['winner']} ({VOTE_A}{m['a_votes']} | {VOTE_B}{m['b_votes']})"
            for i, m in enumerate(finished)
        )[:1020] or "None"

        last = data.get("last_match")
        current_text = f"{last['a']} vs {last['b']} (voting now)" if last else "None"

        cr = data.get("current_round", [])
        upcoming = []
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                upcoming.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming.append(f"{cr[i]} (auto-advance)")
        upcoming_text = "\n".join(upcoming)[:1020] or "None"

        embed = discord.Embed(
            title="📋 Tournament Overview",
            color=discord.Color.blue()
        )
        embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
        embed.add_field(name="Stage", value=data.get("round_stage") or "N/A", inline=False)
        embed.add_field(name="Finished", value=finished_text, inline=False)
        embed.add_field(name="Current Match", value=current_text, inline=False)
        embed.add_field(name="Upcoming", value=upcoming_text, inline=False)

        await channel.send(embed=embed)
            # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup")
    @app_commands.describe(items="Comma-separated list")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

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
                f"✅ Added: {', '.join(added)}",
                ephemeral=False
            )
        return await interaction.response.send_message("⚠️ No new items added.", ephemeral=False)

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (case-insensitive)")
    @app_commands.describe(items="Comma-separated list")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

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
                f"✅ Removed: {', '.join(removed)}",
                ephemeral=False
            )
        return await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)

    # ------------------- /listwcitems (PAGINATED EMBED) -------------------
    @tree.command(name="listwcitems", description="List all items in a paginated menu")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])

        if not items:
            return await interaction.response.send_message("No items added yet.", ephemeral=True)

        pages = [items[i:i + 10] for i in range(0, len(items), 10)]
        total_pages = len(pages)
        current_page = 0

        def make_embed(page_index: int) -> discord.Embed:
            embed = discord.Embed(
                title="📋 World Cup Items",
                description="\n".join(
                    f"{(page_index * 10) + i + 1}. {item}"
                    for i, item in enumerate(pages[page_index])
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Page {page_index + 1}/{total_pages}")
            return embed

        await interaction.response.send_message(embed=make_embed(0))
        msg = await interaction.original_response()

        if total_pages > 1:
            await msg.add_reaction("⬅️")
            await msg.add_reaction("➡️")

        client = interaction.client

        def check(reaction: discord.Reaction, user: discord.User | discord.Member):
            return (
                user == interaction.user
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while True:
            try:
                reaction, user = await client.wait_for("reaction_add", timeout=120.0, check=check)

                if str(reaction.emoji) == "➡️" and current_page < total_pages - 1:
                    current_page += 1
                elif str(reaction.emoji) == "⬅️" and current_page > 0:
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
    @app_commands.describe(title="World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ You do not have permission.", ephemeral=True)

        data, sha = load_data()

        if data["running"]:
            return await interaction.followup.send("❌ A World Cup is already running.", ephemeral=True)

        if len(data["items"]) != 32:
            return await interaction.followup.send("❌ You must have exactly 32 items to start.", ephemeral=True)

        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["finished_matches"] = []
        data["last_match"] = None
        data["last_winner"] = None
        data["running"] = True
        data["round_stage"] = STAGE_BY_COUNT.get(32, "Round")

        sha = save_data(data, sha)

        await interaction.channel.send(
            f"@everyone The World Cup of **{title}** is starting — see the matchups and start voting! 🏆"
        )
        await scoreboard_internal(interaction.channel, data)

        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)

        return await interaction.followup.send("✅ World Cup started.", ephemeral=True)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Count votes → move to the next match/round")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data, sha = load_data()
        if not data.get("running"):
            return await interaction.followup.send(
                "❌ No active World Cup. Use `/startwc` to begin one.",
                ephemeral=True
            )

        guild = interaction.guild

        # ----- SPECIAL HANDLING: FINALS -----
        if data.get("round_stage") == "Finals":
            # If there is still an unprocessed final match, process it silently
            if data.get("last_match"):
                lm = data["last_match"]

                a_votes, b_votes, _, _ = await count_votes_from_message(
                    guild, lm["channel_id"], lm["message_id"]
                )

                a = lm["a"]
                b = lm["b"]

                # Decide winner (with random tiebreaker)
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

                data["scores"][winner] = data["scores"].get(winner, 0) + 1
                data["last_winner"] = winner
                data["last_match"] = None
                # we don't create another round; Finals is the last one
                sha = save_data(data, sha)

            # Whether we just processed it or it was already done, tell user to use /endwc
            return await interaction.followup.send(
                "❌ No more rounds left — use `/endwc` to announce the winner.",
                ephemeral=True
            )

        # ----- NORMAL STAGES (Round of 32/16/QF/SF) -----
        # 1) Process the last match of the current stage, if any
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

            await interaction.channel.send(
                f"@everyone The next fixture in the World Cup of **{data['title']}** is ready — cast your votes below! 🗳️"
            )

            result_embed = discord.Embed(
                title="Previous Match Result! 🏆",
                description=(
                    f"**{winner}** won the previous match!\n\n"
                    f"{VOTE_A} {a}: {a_votes} votes\n"
                    f"{VOTE_B} {b}: {b_votes} votes"
                ),
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=result_embed)

            # If there are still matches left in this round, just post the next one
            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)
                return await interaction.followup.send("✔️ Match processed.", ephemeral=True)

        # 2) If the current_round is empty and we have collected winners in next_round,
        #    promote to the next stage (this is where the "double /nextwcround" happens)
        if not data["current_round"] and data["next_round"]:
            prev_stage = data.get("round_stage") or "Round"

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []

            new_len = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_len, f"{new_len}-items round")
            sha = save_data(data, sha)

            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=(
                    f"Now entering **{data['round_stage']}**\n\n"
                    f"Remaining contenders: {', '.join(data['current_round'])}"
                ),
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            # If new_len == 2, we've just moved into Finals; the next call to /nextwcround
            # will be handled by the Finals branch above.
            if new_len >= 2:
                # Post the first matchup of the new round
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

        # If nothing else applied:
        return await interaction.followup.send(
            "⚠️ Nothing to process right now.",
            ephemeral=True
        )

    # ------------------- /scoreboard -------------------
    @tree.command(name="scoreboard", description="Show finished, current and upcoming matchups")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        await scoreboard_internal(interaction.channel, data)
        return await interaction.response.send_message("📊 Scoreboard posted.", ephemeral=True)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup data")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)

        return await interaction.response.send_message("🔄 World Cup reset.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="Announce the winner and end the World Cup")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()

        if not data.get("running"):
            return await interaction.response.send_message(
                "❌ No active World Cup to end.",
                ephemeral=True
            )

        winner = data.get("last_winner") or "Unknown"

        await interaction.channel.send(
            f"@everyone We have a winner of the World Cup of **{data.get('title', 'Something')}**! 🏆"
        )

        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 **{winner}** wins the **World Cup of {data.get('title', 'World Cup')}**! 🎊",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")

        await interaction.channel.send(embed=embed)

        data["running"] = False
        save_data(data, sha)

        return await interaction.response.send_message("✔️ Winner announced and tournament ended.", ephemeral=True)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Show World Cup command help")
    async def wchelp(interaction: discord.Interaction):
        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())
        embed.add_field(name="/addwcitem", value="Add items to the World Cup (comma-separated).", inline=False)
        embed.add_field(name="/removewcitem", value="Remove items from the World Cup (comma-separated, case-insensitive).", inline=False)
        embed.add_field(name="/listwcitems", value="List all items in a paginated embed.", inline=False)
        embed.add_field(name="/startwc", value="Start the World Cup (requires exactly 32 items).", inline=False)
        embed.add_field(name="/nextwcround", value="Count votes and move to next match/round.", inline=False)
        embed.add_field(name="/scoreboard", value="Show finished, current and upcoming matchups + scores.", inline=False)
        embed.add_field(name="/resetwc", value="Reset all World Cup data.", inline=False)
        embed.add_field(name="/endwc", value="Announce the winner and end the World Cup.", inline=False)

        return await interaction.response.send_message(embed=embed, ephemeral=True)