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
            if emoji == VOTE_B:
                b_users.add(u.id)
                b_names[u.id] = u.display_name

    # single-vote enforcement
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

    # ---------- INTERNAL: SCOREBOARD / OVERVIEW (used by /scoreboard) ----------
    def _build_finished_lines(data):
        finished = data.get("finished_matches", [])
        if not finished:
            return ["No finished matches yet."]

        lines = []
        for i, f in enumerate(finished):
            line = (
                f"{i+1}. {f['a']} vs {f['b']} → **{f['winner']}** "
                f"({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
            )
            lines.append(line)
        return lines

    # ---------- INTERNAL: POST NEXT MATCH & LIVE UPDATE EMBED ----------
    async def post_next_match(channel, data, sha):
        if len(data["current_round"]) < 2:
            return sha

        a = data["current_round"].pop(0)
        b = data["current_round"].pop(0)
        sha = save_data(data, sha)

        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage','Matchup')}",
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
                    await client.wait_for("reaction_add", check=check)

                    a_count, b_count, a_names, b_names = await count_votes_from_message(
                        channel.guild, msg.channel.id, msg.id
                    )

                    desc = f"{VOTE_A} {a} — {a_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                    desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                    await msg.edit(embed=discord.Embed(
                        title=f"🎮 {data.get('round_stage','Matchup')}",
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
            if it.lower() in lower_map:
                original = lower_map[it.lower()]
                data["items"].remove(original)
                data["scores"].pop(original, None)
                removed.append(original)

        sha = save_data(data, sha)

        if removed:
            return await interaction.response.send_message(
                f"✅ Removed: {', '.join(removed)}", ephemeral=False
            )
        return await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)

    # ------------------- /listwcitems (PAGINATED EMBED) -------------------
    @tree.command(name="listwcitems", description="List all items in a paginated embed")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])

        if not items:
            return await interaction.response.send_message("No items added yet.", ephemeral=True)

        pages = [items[i:i+10] for i in range(0, len(items), 10)]
        total_pages = len(pages)
        current_page = 0

        def make_embed(page_index: int):
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

        if total_pages > 1:
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
                reaction, user = await client.wait_for(
                    "reaction_add", timeout=60.0, check=check
                )

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
    @app_commands.describe(title="World Cup title")
    async def startwc(interaction: discord.Interaction, title: str):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ No permission.", ephemeral=True)

        data, sha = load_data()

        if data["running"]:
            return await interaction.followup.send("❌ Already running.", ephemeral=True)

        if len(data["items"]) != 32:
            return await interaction.followup.send("❌ Must have exactly 32 items.", ephemeral=True)

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
            f"@everyone The World Cup of **{title}** is starting - cast your votes! 🏆"
        )

        # 🔹 ONLY post first matchup – no scoreboard at start
        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)

        return await interaction.followup.send("✅ Tournament started.", ephemeral=True)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Process current match → move on")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data, sha = load_data()
        if not data.get("running"):
            return await interaction.followup.send("❌ No active tournament.", ephemeral=True)

        guild = interaction.guild

        # 🔹 HARD PROTECT when finals are already done (no last_match, no current_round but we have a winner)
        if (
            data.get("round_stage") == "Finals"
            and not data.get("last_match")
            and not data.get("current_round")
            and data.get("last_winner") is not None
        ):
            return await interaction.followup.send(
                f"❌ No more rounds left.\nUse `/endwc` to announce the winner of the World Cup of **{data['title']}**.",
                ephemeral=True
            )

        # ----- PROCESS LAST MATCH -----
        if data.get("last_match"):
            lm = data["last_match"]

            a_votes, b_votes, _, _ = await count_votes_from_message(
                guild, lm["channel_id"], lm["message_id"]
            )

            a = lm["a"]
            b = lm["b"]

            # is this the actual final match?
            is_final_match = (data.get("round_stage") == "Finals") and len(data["current_round"]) == 0

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

            # If it was the final, DO NOT announce winner here – just tell them to use /endwc
            if is_final_match:
                result_embed = discord.Embed(
                    title="Final Match Result! 🏆",
                    description=(
                        f"**{winner}** won the final match!\n\n"
                        f"{VOTE_A} {a}: {a_votes} votes\n"
                        f"{VOTE_B} {b}: {b_votes} votes\n\n"
                        f"Use `/endwc` to announce the winner of the World Cup of **{data['title']}**."
                    ),
                    color=discord.Color.gold()
                )
                await interaction.channel.send(embed=result_embed)

                return await interaction.followup.send(
                    f"✔️ Final match processed.\n❌ No more rounds left — use `/endwc` to announce the winner.",
                    ephemeral=True
                )

            # Normal (non-final) result flow
            await interaction.channel.send(
                f"@everyone The next fixture in The World Cup of **{data['title']}** is ready - cast your votes below! 🗳️"
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

            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("✔️ Match processed.", ephemeral=True)

        # ----- PROMOTE TO NEXT ROUND (not finals) -----
        if not data["current_round"] and data["next_round"]:
            prev_stage = data["round_stage"]

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []

            new_len = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_len, f"{new_len}-items round")
            sha = save_data(data, sha)

            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=(
                    f"Now entering **{data['round_stage']}**\n\n"
                    f"Remaining: {', '.join(data['current_round'])}"
                ),
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            if new_len >= 2:
                await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

        # Fallback
        return await interaction.followup.send("⚠️ Nothing to process right now.", ephemeral=True)

    # ------------------- /scoreboard -------------------
    @tree.command(name="scoreboard", description="Show finished matches & current status (paginated)")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()

        finished_lines = _build_finished_lines(data)
        pages = [finished_lines[i:i+10] for i in range(0, len(finished_lines), 10)]
        total_pages = len(pages)
        current_page = 0

        # build current + upcoming preview (short, to avoid length errors)
        last = data.get("last_match")
        if last:
            current_line = f"{last['a']} vs {last['b']} (voting now)"
        else:
            current_line = "None"

        upcoming = []
        cr = data.get("current_round", []).copy()
        for i in range(0, min(len(cr), 10), 2):
            if i + 1 < len(cr):
                upcoming.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming.append(f"{cr[i]} (auto-advance)")

        def make_embed(page_index: int):
            embed = discord.Embed(
                title="🏆 World Cup Scoreboard",
                color=discord.Color.teal()
            )
            embed.add_field(
                name="Tournament",
                value=data.get("title") or "No title",
                inline=False
            )
            stage = data.get("round_stage") or "N/A"
            status = "Running" if data.get("running") else "Ended / Not started"
            embed.add_field(
                name="Status",
                value=f"{stage} — {status}",
                inline=False
            )

            page_lines = pages[page_index]
            embed.add_field(
                name=f"Finished Matches (Page {page_index+1}/{total_pages})",
                value="\n".join(page_lines),
                inline=False
            )

            embed.add_field(
                name="Current Match",
                value=current_line,
                inline=False
            )

            upcoming_text = "\n".join(upcoming) if upcoming else "None"
            embed.add_field(
                name="Upcoming (preview)",
                value=upcoming_text,
                inline=False
            )

            return embed

        await interaction.response.send_message(embed=make_embed(0))
        msg = await interaction.original_response()

        if total_pages > 1:
            await msg.add_reaction("⬅️")
            await msg.add_reaction("➡️")

        client = interaction.client

        def check(reaction, user):
            return (
                user == interaction.user
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while total_pages > 1:
            try:
                reaction, user = await client.wait_for(
                    "reaction_add", timeout=60.0, check=check
                )

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

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset everything")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)

        return await interaction.response.send_message("🔄 Reset complete.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="Announce the winner & end the tournament")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()

        if not data.get("running"):
            return await interaction.response.send_message("❌ No running tournament.", ephemeral=True)

        winner = data.get("last_winner")
        if not winner:
            return await interaction.response.send_message(
                "⚠️ No winner recorded yet. Process the final match with `/nextwcround` first.",
                ephemeral=True
            )

        await interaction.channel.send(f"@everyone Tournament has ended!")

        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 **{winner}** wins the World Cup of {data.get('title')}!",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")

        await interaction.channel.send(embed=embed)

        data["running"] = False
        save_data(data, sha)

        return await interaction.response.send_message("✔️ Winner announced.", ephemeral=True)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Help menu")
    async def wchelp(interaction: discord.Interaction):

        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())
        embed.add_field(name="/addwcitem", value="Add items (staff only)", inline=False)
        embed.add_field(name="/removewcitem", value="Remove items (staff only)", inline=False)
        embed.add_field(name="/listwcitems", value="List all items (paginated)", inline=False)
        embed.add_field(name="/startwc", value="Start tournament (32 items, staff only)", inline=False)
        embed.add_field(name="/nextwcround", value="Process match / round (staff only)", inline=False)
        embed.add_field(name="/scoreboard", value="View finished matches & status", inline=False)
        embed.add_field(name="/resetwc", value="Reset tournament (staff only)", inline=False)
        embed.add_field(name="/endwc", value="Announce winner & end (staff only)", inline=False)

        return await interaction.response.send_message(embed=embed, ephemeral=True)