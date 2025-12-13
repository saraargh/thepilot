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

# ------------------- Auto Lock Timers (UNCHANGED) -------------------
AUTO_WARN_SECONDS = 23 * 60 * 60
AUTO_LOCK_SECONDS = 24 * 60 * 60

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
    "round_stage": "",

    # item authors (already in happy file)
    "item_authors": {},   # item -> user_id (str)
    "user_items": {},     # user_id -> item

    # 🆕 persistent history (NOT wiped by /resetwc)
    "cup_history": []     # [{title, winner, author_id, timestamp}]
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

            # ensure all expected keys exist
            for k in DEFAULT_DATA:
                if k not in data:
                    data[k] = DEFAULT_DATA[k]

            if not isinstance(data.get("item_authors"), dict):
                data["item_authors"] = {}
            if not isinstance(data.get("user_items"), dict):
                data["user_items"] = {}
            if not isinstance(data.get("cup_history"), list):
                data["cup_history"] = []

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
    except Exception:
        return 0, 0, {}, {}

    a_users, b_users = set(), set()
    a_names, b_names = {}, {}

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

    # single vote rule
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

    # ---------- INTERNAL: lock match (UNCHANGED) ----------
    async def _lock_match(guild, channel, data, sha, reason, ping_everyone, reply_msg):
        if not data.get("last_match"):
            return data, sha

        lm = data["last_match"]
        if lm.get("locked"):
            return data, sha

        a_votes, b_votes, _, _ = await count_votes_from_message(
            guild, lm["channel_id"], lm["message_id"]
        )

        lm["locked"] = True
        lm["locked_at"] = int(time.time())
        lm["locked_counts"] = {"a": a_votes, "b": b_votes}
        lm["lock_reason"] = reason

        sha = save_data(data, sha)

        try:
            msg = await channel.fetch_message(lm["message_id"])
            if msg.embeds:
                emb = msg.embeds[0]
                new = discord.Embed(
                    title=emb.title,
                    description=(emb.description or "") + "\n\n🔒 **Voting closed**",
                    color=emb.color
                )
                await msg.edit(embed=new)
        except:
            pass

        try:
            ping = "@everyone " if ping_everyone else ""
            text = f"{ping}🔒 **Voting is now closed.** ({reason})"
            if reply_msg:
                await reply_msg.reply(text)
            else:
                await channel.send(text)
        except:
            pass

        return data, sha


    # ---------- INTERNAL: auto lock scheduler (UNCHANGED) ----------
    async def _schedule_auto_lock(channel, message_id):
        try:
            await asyncio.sleep(AUTO_WARN_SECONDS)
            data, sha = load_data()
            lm = data.get("last_match")
            if not lm or lm.get("message_id") != message_id or lm.get("locked"):
                return

            try:
                msg = await channel.fetch_message(message_id)
                await msg.reply("@everyone ⏰ **Voting closes soon!** (auto-lock at 24h)")
            except:
                pass

            await asyncio.sleep(AUTO_LOCK_SECONDS - AUTO_WARN_SECONDS)
            data, sha = load_data()
            lm = data.get("last_match")
            if not lm or lm.get("message_id") != message_id or lm.get("locked"):
                return

            try:
                reply_msg = await channel.fetch_message(message_id)
            except:
                reply_msg = None

            await _lock_match(
                channel.guild,
                channel,
                data,
                sha,
                "Auto-locked after 24h",
                True,
                reply_msg
            )

        except Exception as e:
            print("Auto-lock error:", e)


    # ---------- INTERNAL: POST NEXT MATCH (UNCHANGED) ----------
    async def post_next_match(channel, data, sha):
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
            "channel_id": channel.id,
            "locked": False,
            "locked_at": None,
            "locked_counts": None,
            "lock_reason": None
        }
        sha = save_data(data, sha)

        asyncio.create_task(_schedule_auto_lock(channel, msg.id))

        client = channel.guild._state._get_client()

        def check(reaction, user):
            return (
                user != channel.guild.me
                and reaction.message.id == msg.id
                and str(reaction.emoji) in (VOTE_A, VOTE_B)
            )

        async def reaction_loop():
            while True:
                latest, _ = load_data()
                lm = latest.get("last_match")
                if not lm or lm.get("message_id") != msg.id or lm.get("locked"):
                    return

                await client.wait_for("reaction_add", check=check)

                a_count, b_count, a_names, b_names = await count_votes_from_message(
                    channel.guild, msg.channel.id, msg.id
                )

                desc = (
                    f"{VOTE_A} {a} — {a_count} votes\n" +
                    ("\n".join(f"• {n}" for n in a_names.values()) or "_No votes yet_") +
                    f"\n\n{VOTE_B} {b} — {b_count} votes\n" +
                    ("\n".join(f"• {n}" for n in b_names.values()) or "_No votes yet_")
                )

                await msg.edit(embed=discord.Embed(
                    title=f"🎮 {latest.get('round_stage', 'Matchup')}",
                    description=desc,
                    color=discord.Color.random()
                ))

        asyncio.create_task(reaction_loop())
        return sha
            # ------------------- /nextwcround (ADMIN ONLY) -------------------
    @tree.command(name="nextwcround", description="Process the current match or advance rounds")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        if not data.get("running"):
            return await interaction.followup.send("❌ No active tournament.", ephemeral=True)

        guild = interaction.guild

        # FINAL SAFETY
        if (
            data.get("round_stage") == "Finals"
            and not data.get("last_match")
            and not data.get("current_round")
            and data.get("last_winner")
        ):
            return await interaction.followup.send(
                f"❌ Tournament finished.\nUse `/endwc` for **{data['title']}**.",
                ephemeral=True
            )

        # PROCESS CURRENT MATCH
        if data.get("last_match"):
            lm = data["last_match"]
            is_final = data["round_stage"] == "Finals" and not data["current_round"]

            if lm.get("locked") and lm.get("locked_counts"):
                a_votes = lm["locked_counts"]["a"]
                b_votes = lm["locked_counts"]["b"]
            else:
                a_votes, b_votes, _, _ = await count_votes_from_message(
                    guild, lm["channel_id"], lm["message_id"]
                )

            a, b = lm["a"], lm["b"]

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

            if is_final:
                return await interaction.followup.send(
                    "✔ Final match processed.\nUse `/endwc` to announce the winner.",
                    ephemeral=True
                )

            result = discord.Embed(
                title="Previous Match Result 🏆",
                description=(
                    f"**{winner}** advances!\n\n"
                    f"{VOTE_A} {a}: {a_votes}\n"
                    f"{VOTE_B} {b}: {b_votes}"
                ),
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=result)

            if len(data["current_round"]) >= 2:
                await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("✔ Match processed.", ephemeral=True)

        # ADVANCE ROUND
        if not data["current_round"] and data["next_round"]:
            prev = data["round_stage"]
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []
            data["round_stage"] = STAGE_BY_COUNT.get(len(data["current_round"]), "Round")
            sha = save_data(data, sha)

            await interaction.channel.send(
                f"✅ **{prev} complete!**\nNow entering **{data['round_stage']}**"
            )

            await post_next_match(interaction.channel, data, sha)
            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

        await interaction.followup.send("⚠ Nothing to process.", ephemeral=True)


    # ------------------- /scoreboard -------------------
    @tree.command(name="scoreboard", description="View tournament progress")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()

        finished = data.get("finished_matches", [])
        current = data.get("last_match")
        upcoming = data.get("current_round", [])

        embed = discord.Embed(title="🏆 World Cup Scoreboard", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title") or "N/A", inline=False)
        embed.add_field(name="Stage", value=data.get("round_stage") or "N/A", inline=False)

        if current:
            lock = " 🔒" if current.get("locked") else ""
            embed.add_field(
                name="Current Match",
                value=f"{current['a']} vs {current['b']}{lock}",
                inline=False
            )
        else:
            embed.add_field(name="Current Match", value="None", inline=False)

        if finished:
            embed.add_field(
                name="Finished Matches",
                value="\n".join(
                    f"{f['a']} vs {f['b']} → **{f['winner']}**"
                    for f in finished[-10:]
                ),
                inline=False
            )

        if upcoming:
            embed.add_field(
                name="Upcoming",
                value="\n".join(
                    f"{upcoming[i]} vs {upcoming[i+1]}"
                    for i in range(0, len(upcoming)-1, 2)
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed)


    # ------------------- /resetwc (ADMIN ONLY) -------------------
    @tree.command(name="resetwc", description="Reset the tournament (history preserved)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        history = data.get("cup_history", [])

        fresh = DEFAULT_DATA.copy()
        fresh["cup_history"] = history

        save_data(fresh, sha)
        await interaction.response.send_message("🔄 Tournament reset.", ephemeral=False)


    # ------------------- /endwc (ADMIN ONLY) -------------------
    @tree.command(name="endwc", description="Announce the winner & save history")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        winner = data.get("last_winner")
        if not winner:
            return await interaction.response.send_message("⚠ No winner yet.", ephemeral=True)

        author_id = data["item_authors"].get(winner)
        mention = f"<@{author_id}>" if author_id else "Unknown"

        data["cup_history"].append({
            "title": data["title"],
            "winner": winner,
            "author_id": author_id,
            "timestamp": int(time.time())
        })

        data["running"] = False
        save_data(data, sha)

        embed = discord.Embed(
            title="🎉 World Cup Winner!",
            description=f"🏆 **{winner}**\n✨ Added by: {mention}",
            color=discord.Color.green()
        )

        await interaction.channel.send("@everyone WE HAVE A WINNER 🎉")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✔ World Cup ended.", ephemeral=True)


    # ------------------- /cuphistory -------------------
    @tree.command(name="cuphistory", description="View past World Cups")
    async def cuphistory(interaction: discord.Interaction):
        data, _ = load_data()
        hist = data.get("cup_history", [])

        if not hist:
            return await interaction.response.send_message("No history yet.")

        pages = [hist[i:i+5] for i in range(0, len(hist), 5)]
        page = 0

        def make_embed(p):
            e = discord.Embed(title="📜 World Cup History")
            for h in pages[p]:
                e.add_field(
                    name=h["title"],
                    value=f"🏆 {h['winner']} — <@{h['author_id']}>",
                    inline=False
                )
            e.set_footer(text=f"Page {p+1}/{len(pages)}")
            return e

        await interaction.response.send_message(embed=make_embed(0))
        msg = await interaction.original_response()

        if len(pages) == 1:
            return

        await msg.add_reaction("⬅️")
        await msg.add_reaction("➡️")

        def check(r, u):
            return u == interaction.user and r.message.id == msg.id

        while True:
            try:
                r, u = await interaction.client.wait_for("reaction_add", timeout=60, check=check)
                if str(r.emoji) == "➡️" and page < len(pages) - 1:
                    page += 1
                elif str(r.emoji) == "⬅️" and page > 0:
                    page -= 1
                await msg.edit(embed=make_embed(page))
                await msg.remove_reaction(r.emoji, u)
            except asyncio.TimeoutError:
                break


    # ------------------- /deletehistory (ADMIN ONLY) -------------------
    @tree.command(name="deletehistory", description="Delete a World Cup from history")
    async def deletehistory(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        data, sha = load_data()
        before = len(data["cup_history"])
        data["cup_history"] = [h for h in data["cup_history"] if h["title"] != title]

        if len(data["cup_history"]) == before:
            return await interaction.response.send_message("⚠ Not found.", ephemeral=True)

        save_data(data, sha)
        await interaction.response.send_message("🗑 History entry deleted.", ephemeral=True)


    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="World Cup commands")
    async def wchelp(interaction: discord.Interaction):
        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())
        embed.add_field(name="/addwcitem", value="Add item (1 per user; admins unlimited)", inline=False)
        embed.add_field(name="/removewcitem", value="Remove item (admin)", inline=False)
        embed.add_field(name="/listwcitems", value="List items", inline=False)
        embed.add_field(name="/startwc", value="Start tournament", inline=False)
        embed.add_field(name="/closematch", value="Lock voting", inline=False)
        embed.add_field(name="/nextwcround", value="Advance match / round", inline=False)
        embed.add_field(name="/scoreboard", value="View progress", inline=False)
        embed.add_field(name="/endwc", value="Announce winner", inline=False)
        embed.add_field(name="/resetwc", value="Reset tournament", inline=False)
        embed.add_field(name="/cuphistory", value="View past cups", inline=False)
        embed.add_field(name="/deletehistory", value="Delete cup (admin)", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)