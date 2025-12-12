import discord
from discord import app_commands
import requests
import base64
import json
import os
import random
import asyncio
import time

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "tournament_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Auto-close config -------------------
AUTO_CLOSE_WARNING_SECONDS = 23 * 3600   # 23 hours
AUTO_CLOSE_LOCK_SECONDS = 24 * 3600      # 24 hours

# Optional pings for the 23h warning (defaults: NO ping)
CLOSE_WARN_PING_EVERYONE = False         # set True if you want @everyone
CLOSE_WARN_ROLE_ID = None                # set a role ID (int) if you want to ping a role

# ------------------- Default JSON structure -------------------
DEFAULT_DATA = {
    "items": [],
    "item_authors": {},          # item -> user_id (int)
    "user_added": {},            # user_id(str) -> item (str)  (non-admin 1-item rule)
    "current_round": [],
    "next_round": [],
    "scores": {},
    "running": False,
    "title": "",
    "last_winner": None,
    "last_match": None,          # dict with a/b/message/channel/closed/etc
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
            return r.json().get("content", {}).get("sha")
        return sha
    except Exception as e:
        print("Error saving data:", e)
        return sha

# ------------------- Utilities -------------------
def user_allowed(member: discord.Member, allowed_roles):
    return any(role.id in allowed_roles for role in member.roles)

async def count_votes_from_message(guild, channel_id, message_id):
    """Returns: (a_votes, b_votes, a_names, b_names) enforcing single-vote rule."""
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

    # single vote enforcement
    dupes = a_users & b_users
    for uid in dupes:
        # if they reacted both, remove from A by default
        if uid in a_users:
            a_users.discard(uid)
            a_names.pop(uid, None)

    return len(a_users), len(b_users), a_names, b_names

def _chunk_lines(lines, max_chars=950):
    """Chunk lines to stay under embed field limits (1024)."""
    chunks = []
    cur = []
    cur_len = 0
    for line in lines:
        ln = len(line) + 1
        if cur and (cur_len + ln) > max_chars:
            chunks.append(cur)
            cur = []
            cur_len = 0
        cur.append(line)
        cur_len += ln
    if cur:
        chunks.append(cur)
    return chunks if chunks else [["None"]]

# ------------------- Main Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ---------- INTERNAL: close match (lock votes) ----------
    async def close_match(channel: discord.abc.Messageable, data: dict, sha: str, reason: str = "🔒 Voting closed"):
        lm = data.get("last_match")
        if not lm or lm.get("closed"):
            return sha

        # snapshot votes so changes after lock don't matter
        guild = getattr(channel, "guild", None)
        if guild:
            a_votes, b_votes, _, _ = await count_votes_from_message(guild, lm["channel_id"], lm["message_id"])
        else:
            a_votes, b_votes = 0, 0

        lm["closed"] = True
        lm["closed_at"] = int(time.time())
        lm["locked_votes"] = {"a": a_votes, "b": b_votes}

        data["last_match"] = lm
        sha = save_data(data, sha)

        # edit matchup embed footer
        try:
            ch = guild.get_channel(lm["channel_id"]) if guild else None
            if ch:
                msg = await ch.fetch_message(lm["message_id"])
                if msg.embeds:
                    embed = msg.embeds[0]
                    embed.set_footer(text=reason)
                    await msg.edit(embed=embed)
        except Exception:
            pass

        return sha

    # ---------- INTERNAL: auto timers ----------
    async def _warn_then_autolock(channel_id: int, message_id: int):
        # Wait 23h, reply warning
        await asyncio.sleep(AUTO_CLOSE_WARNING_SECONDS)

        data, sha = load_data()
        lm = data.get("last_match")
        if not lm or lm.get("message_id") != message_id or lm.get("channel_id") != channel_id:
            return
        if lm.get("closed"):
            return

        try:
            guild = tree.client.get_guild(lm.get("guild_id")) if lm.get("guild_id") else None
            # Fallback: we can still fetch channel via client if we have it
            channel = tree.client.get_channel(channel_id)
            if channel is not None:
                msg = await channel.fetch_message(message_id)

                ping_bits = []
                if CLOSE_WARN_PING_EVERYONE:
                    ping_bits.append("@everyone")
                if isinstance(CLOSE_WARN_ROLE_ID, int):
                    ping_bits.append(f"<@&{CLOSE_WARN_ROLE_ID}>")

                ping_text = (" ".join(ping_bits) + " ") if ping_bits else ""

                await msg.reply(f"{ping_text}⏰ **Voting closes in 1 hour**")
        except Exception:
            pass

        # Wait final hour, then lock
        await asyncio.sleep(AUTO_CLOSE_LOCK_SECONDS - AUTO_CLOSE_WARNING_SECONDS)

        data, sha = load_data()
        lm = data.get("last_match")
        if not lm or lm.get("message_id") != message_id or lm.get("channel_id") != channel_id:
            return
        if lm.get("closed"):
            return

        try:
            channel = tree.client.get_channel(channel_id)
            if channel is not None:
                await close_match(channel, data, sha, reason="🔒 Voting closed (auto)")
        except Exception:
            pass

    # ---------- INTERNAL: post next match ----------
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
            "channel_id": channel.id,
            "guild_id": channel.guild.id,
            "closed": False,
            "closed_at": None,
            "locked_votes": None
        }
        sha = save_data(data, sha)

        # Live reaction updater (stops changing once closed)
        client = channel.guild._state._get_client()

        def check(reaction, user):
            return (
                user != channel.guild.me
                and reaction.message.id == msg.id
                and str(reaction.emoji) in (VOTE_A, VOTE_B)
            )

        async def reaction_loop():
            while True:
                # Refresh latest state from disk so "closed" is respected
                d, _ = load_data()
                lm = d.get("last_match")
                if not lm or lm.get("message_id") != msg.id:
                    break
                if lm.get("closed"):
                    break

                try:
                    await client.wait_for("reaction_add", check=check)

                    # Only update display if still open
                    d2, _ = load_data()
                    lm2 = d2.get("last_match")
                    if not lm2 or lm2.get("message_id") != msg.id or lm2.get("closed"):
                        break

                    a_count, b_count, a_names, b_names = await count_votes_from_message(
                        channel.guild, msg.channel.id, msg.id
                    )

                    desc = f"{VOTE_A} {a} — {a_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                    desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                    desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                    await msg.edit(embed=discord.Embed(
                        title=f"🎮 {d2.get('round_stage','Matchup')}",
                        description=desc,
                        color=discord.Color.random()
                    ))

                except Exception:
                    continue

        asyncio.create_task(reaction_loop())

        # Auto warning + auto lock
        asyncio.create_task(_warn_then_autolock(channel.id, msg.id))

        return sha

    # ------------------- /closematch -------------------
    @tree.command(name="closematch", description="Lock the current matchup (stop voting / freeze votes)")
    async def closematch(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        data, sha = load_data()
        if not data.get("running") or not data.get("last_match"):
            return await interaction.followup.send("❌ No active match to close.", ephemeral=True)

        sha = await close_match(interaction.channel, data, sha, reason="🔒 Voting closed")
        return await interaction.followup.send("🔒 Voting closed for this match.", ephemeral=True)

    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup")
    @app_commands.describe(items="Comma-separated list")
    async def addwcitem(interaction: discord.Interaction, items: str):
        data, sha = load_data()

        is_admin = user_allowed(interaction.user, allowed_role_ids)
        uid_str = str(interaction.user.id)

        requested = [x.strip() for x in items.split(",") if x.strip()]

        if not is_admin:
            # one-item rule
            if uid_str in data.get("user_added", {}):
                return await interaction.response.send_message(
                    "You can only add one item to the World Cup. Don’t be greedy 😌",
                    ephemeral=True
                )
            if len(requested) != 1:
                return await interaction.response.send_message(
                    "You can only add one item to the World Cup. Don’t be greedy 😌",
                    ephemeral=True
                )

        added = []
        for it in requested:
            if it not in data["items"]:
                data["items"].append(it)
                data["scores"].setdefault(it, 0)
                data.setdefault("item_authors", {})[it] = interaction.user.id
                added.append(it)

                # only track non-admin "used their one"
                if not is_admin:
                    data.setdefault("user_added", {})[uid_str] = it

        sha = save_data(data, sha)

        if added:
            return await interaction.response.send_message(f"✅ Added: {', '.join(added)}", ephemeral=False)
        return await interaction.response.send_message("⚠️ No new items added.", ephemeral=True)

    # ------------------- /removewcitem (STAFF ONLY) -------------------
    @tree.command(name="removewcitem", description="Remove item(s) (staff only)")
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
                orig = lower_map[key]
                data["items"].remove(orig)
                data["scores"].pop(orig, None)
                data.get("item_authors", {}).pop(orig, None)
                removed.append(orig)

        sha = save_data(data, sha)
        if removed:
            return await interaction.response.send_message(f"✅ Removed: {', '.join(removed)}", ephemeral=False)
        return await interaction.response.send_message("⚠️ No items removed.", ephemeral=True)

    # ------------------- /listwcitems (PAGINATED EMBED) -------------------
    @tree.command(name="listwcitems", description="List all items in a paginated embed")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items_list = data.get("items", [])
        if not items_list:
            return await interaction.response.send_message("No items added yet.", ephemeral=True)

        pages = [items_list[i:i+10] for i in range(0, len(items_list), 10)]
        total_pages = len(pages)
        page = 0

        def make_embed(idx: int):
            embed = discord.Embed(
                title="📋 World Cup Items",
                description="\n".join(f"{(idx*10)+i+1}. {item}" for i, item in enumerate(pages[idx])),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Page {idx+1}/{total_pages}")
            return embed

        await interaction.response.send_message(embed=make_embed(0))
        msg = await interaction.original_response()

        if total_pages > 1:
            await msg.add_reaction("⬅️")
            await msg.add_reaction("➡️")

        def check(reaction, user):
            return (
                user == interaction.user
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while total_pages > 1:
            try:
                reaction, user = await interaction.client.wait_for("reaction_add", timeout=60.0, check=check)
                if str(reaction.emoji) == "➡️" and page < total_pages - 1:
                    page += 1
                elif str(reaction.emoji) == "⬅️" and page > 0:
                    page -= 1

                await msg.edit(embed=make_embed(page))
                try:
                    await msg.remove_reaction(reaction.emoji, user)
                except Exception:
                    pass
            except asyncio.TimeoutError:
                break

    # ------------------- /startwc (STAFF ONLY) -------------------
    @tree.command(name="startwc", description="Start the World Cup (requires 32 items)")
    @app_commands.describe(title="World Cup title")
    async def startwc(interaction: discord.Interaction, title: str):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        if data.get("running"):
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
        data["round_stage"] = STAGE_BY_COUNT.get(32, "Round of 32")

        sha = save_data(data, sha)

        await interaction.channel.send(f"@everyone The World Cup of **{title}** is starting - cast your votes! 🏆")

        if len(data["current_round"]) >= 2:
            await post_next_match(interaction.channel, data, sha)

        return await interaction.followup.send("✅ Tournament started.", ephemeral=True)

    # ------------------- /nextwcround (STAFF ONLY) -------------------
    @tree.command(name="nextwcround", description="Process the current match → move on")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        if not data.get("running"):
            return await interaction.followup.send("❌ No active tournament.", ephemeral=True)

        guild = interaction.guild

        # If final match already processed, DO NOT post anything in channel; just the ❌ ephemeral
        if (
            data.get("round_stage") == "Finals"
            and not data.get("last_match")
            and data.get("last_winner") is not None
        ):
            return await interaction.followup.send(
                f"❌ No more rounds left.\nUse `/endwc` to announce the winner of **{data['title']}**.",
                ephemeral=True
            )

        # ----- PROCESS LAST MATCH -----
        if data.get("last_match"):
            lm = data["last_match"]

            # If closed, use locked votes snapshot; otherwise count live
            if lm.get("closed") and lm.get("locked_votes"):
                a_votes = int(lm["locked_votes"].get("a", 0))
                b_votes = int(lm["locked_votes"].get("b", 0))
            else:
                a_votes, b_votes, _, _ = await count_votes_from_message(
                    guild, lm["channel_id"], lm["message_id"]
                )

            a = lm["a"]
            b = lm["b"]

            is_final_match = (data.get("round_stage") == "Finals") and len(data.get("current_round", [])) == 0

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

            # ✅ FINAL: do NOT post final match result in channel (your request)
            if is_final_match:
                return await interaction.followup.send(
                    "✔ Final match processed.\n❌ No more matches left.\nUse `/endwc` to announce the winner.",
                    ephemeral=True
                )

            # Normal (non-final) flow: announce + post next match if available
            await interaction.channel.send(
                f"@everyone The next fixture in the World Cup of **{data['title']}** is ready - cast your votes below! 🗳️"
            )

            result_embed = discord.Embed(
                title="Previous Match Result! 🏆",
                description=(
                    f"**{winner}** won the previous match!\n\n"
                    f"{VOTE_A} {a}: {a_votes}\n"
                    f"{VOTE_B} {b}: {b_votes}"
                ),
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=result_embed)

            if len(data["current_round"]) >= 2:
                await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("✔ Match processed.", ephemeral=True)

        # ----- PROMOTE TO NEXT ROUND -----
        if not data["current_round"] and data.get("next_round"):
            prev_stage = data["round_stage"]

            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []

            new_len = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_len, f"{new_len}-items round")
            sha = save_data(data, sha)

            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"Now entering **{data['round_stage']}**.\nRemaining: {', '.join(data['current_round'])}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            if new_len >= 2:
                await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

        return await interaction.followup.send("⚠ Nothing to process.", ephemeral=True)

    # (PART 2 CONTINUES BELOW)
    
        # ------------------- /scoreboard -------------------
    @tree.command(name="scoreboard", description="Show finished matches, current match, and ALL upcoming matchups")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()

        finished = data.get("finished_matches", [])
        current = data.get("last_match")
        remaining = data.get("current_round", [])

        # finished lines
        finished_lines = []
        for i, f in enumerate(finished):
            finished_lines.append(
                f"{i+1}. {f['a']} vs {f['b']} → **{f['winner']}** ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
            )
        if not finished_lines:
            finished_lines = ["No matches played yet."]

        finished_pages = [finished_lines[i:i+10] for i in range(0, len(finished_lines), 10)]

        # current match
        if current:
            status = "🔒 closed" if current.get("closed") else "🗳️ voting"
            current_line = f"{current['a']} vs {current['b']} ({status})"
        else:
            current_line = "None"

        # upcoming FULL list
        upcoming_lines = []
        for i in range(0, len(remaining), 2):
            if i + 1 < len(remaining):
                upcoming_lines.append(f"• {remaining[i]} vs {remaining[i+1]}")
            else:
                upcoming_lines.append(f"• {remaining[i]} (auto-advance)")

        if not upcoming_lines:
            upcoming_lines = ["None"]

        upcoming_chunks = _chunk_lines(upcoming_lines, max_chars=950)

        page = 0
        total_pages = max(len(finished_pages), len(upcoming_chunks))

        def make_embed(page_index: int):
            embed = discord.Embed(title="🏆 World Cup Scoreboard", color=discord.Color.teal())
            embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
            embed.add_field(name="Stage", value=data.get("round_stage") or "N/A", inline=False)
            embed.add_field(name="Current Match", value=current_line, inline=False)

            fp = finished_pages[min(page_index, len(finished_pages) - 1)]
            up = upcoming_chunks[min(page_index, len(upcoming_chunks) - 1)]

            embed.add_field(name="Finished Matches", value="\n".join(fp), inline=False)
            embed.add_field(name="Upcoming Matchups", value="\n".join(up), inline=False)
            embed.set_footer(text=f"Page {page_index+1}/{total_pages}")
            return embed

        await interaction.response.send_message(embed=make_embed(0))
        msg = await interaction.original_response()

        if total_pages > 1:
            await msg.add_reaction("⬅️")
            await msg.add_reaction("➡️")

        def check(reaction, user):
            return (
                user == interaction.user
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("⬅️", "➡️")
            )

        while total_pages > 1:
            try:
                reaction, user = await interaction.client.wait_for("reaction_add", timeout=60.0, check=check)

                if str(reaction.emoji) == "➡️" and page < total_pages - 1:
                    page += 1
                elif str(reaction.emoji) == "⬅️" and page > 0:
                    page -= 1

                await msg.edit(embed=make_embed(page))

                try:
                    await msg.remove_reaction(reaction.emoji, user)
                except Exception:
                    pass

            except asyncio.TimeoutError:
                break

    # ------------------- /resetwc (STAFF ONLY) -------------------
    @tree.command(name="resetwc", description="Reset the tournament (staff only)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)
        return await interaction.response.send_message("🔄 Reset complete.", ephemeral=False)

    # ------------------- /endwc (STAFF ONLY) -------------------
    @tree.command(name="endwc", description="Announce the winner & end the tournament (staff only)")
    async def endwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = load_data()

        if not data.get("running"):
            return await interaction.response.send_message("❌ No active tournament.", ephemeral=True)

        winner = data.get("last_winner")
        if not winner:
            return await interaction.response.send_message(
                "⚠ No winner recorded yet. Process the final match with `/nextwcround` first.",
                ephemeral=True
            )

        author_id = data.get("item_authors", {}).get(winner)
        author_text = f"<@{author_id}>" if author_id else "Unknown"

        await interaction.channel.send("@everyone We have a World Cup Winner‼️🎉🏆")

        embed = discord.Embed(
            title="🎉 World Cup Winner!",
            description=f"🏆 **{winner}** wins the World Cup of **{data.get('title')}**!\n\n*Added by {author_text}*",
            color=discord.Color.green()
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1444274467864838207/1449046416453271633/IMG_8499.gif")

        await interaction.channel.send(embed=embed)

        data["running"] = False
        save_data(data, sha)

        return await interaction.response.send_message("✔ Winner announced.", ephemeral=True)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Help menu")
    async def wchelp(interaction: discord.Interaction):
        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())

        embed.add_field(name="/addwcitem", value="Everyone can add **ONE** item total. Staff can add multiple.", inline=False)
        embed.add_field(name="/removewcitem", value="Remove items (staff only).", inline=False)
        embed.add_field(name="/listwcitems", value="List items (paginated).", inline=False)
        embed.add_field(name="/startwc", value="Start tournament (staff only, requires 32 items).", inline=False)
        embed.add_field(name="/nextwcround", value="Process match / round (staff only).", inline=False)
        embed.add_field(name="/closematch", value="Lock current match (staff only). Also auto-locks at 24h.", inline=False)
        embed.add_field(name="/scoreboard", value="View progress + ALL upcoming matchups.", inline=False)
        embed.add_field(name="/resetwc", value="Reset tournament (staff only).", inline=False)
        embed.add_field(name="/endwc", value="Announce final winner (staff only).", inline=False)

        return await interaction.response.send_message(embed=embed, ephemeral=True)