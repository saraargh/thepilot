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
        except:
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

    async def showwcmatchups_internal(channel, data):
        finished = data.get("finished_matches", [])
        lines_finished = [
            f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
            for i, f in enumerate(finished)
        ]

        last = data.get("last_match")
        current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else None

        upcoming = []
        cr = data.get("current_round", []).copy()
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                upcoming.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming.append(f"{cr[i]} (auto-advance)")

        embed = discord.Embed(title="📋 World Cup Matchups", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
        embed.add_field(name="Stage", value=data.get("round_stage"), inline=False)
        embed.add_field(name="Finished", value="\n".join(lines_finished) or "None", inline=False)
        embed.add_field(name="Current Match", value=current_pair or "None", inline=False)
        embed.add_field(name="Upcoming", value="\n".join(upcoming) or "None", inline=False)

        await channel.send(embed=embed)

    # ------------------- Post Next Match -------------------
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
                    reaction, user = await client.wait_for("reaction_add", check=check)

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

    # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all items")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            return await interaction.response.send_message("No items added yet.", ephemeral=True)

        text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(data["items"])])
        return await interaction.response.send_message(f"📋 **Items:**\n{text}", ephemeral=False)

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

        await interaction.channel.send(f"@everyone The World Cup of **{title}** is starting - See the matchups and start voting! 🏆")
        await showwcmatchups_internal(interaction.channel, data)

        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)

        return await interaction.followup.send("✅ Started.", ephemeral=True)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Process current match → move on")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data, sha = load_data()
        if not data.get("running"):
            return await interaction.followup.send("❌ No active tournament.", ephemeral=True)

        guild = interaction.guild

        # ----- PROCESS LAST MATCH -----
        if data.get("last_match"):
            lm = data["last_match"]

            a_votes, b_votes, _, _ = await count_votes_from_message(
                guild, lm["channel_id"], lm["message_id"]
            )

            a = lm["a"]
            b = lm["b"]

            winner = a if a_votes > b_votes else b
            if a_votes == b_votes:
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

            await interaction.channel.send("@everyone The next fixture in The World Cup of **{title}** is ready - Cast your votes below!🗳️")

            result_embed = discord.Embed(
                title="Previous Match Result! 🏆",
                description=f"**{winner}** won the previous match!\n\n"
                            f"{VOTE_A} {a}: {a_votes} votes\n"
                            f"{VOTE_B} {b}: {b_votes} votes",
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=result_embed)

            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("✔️ Match processed.", ephemeral=True)

        # ----- PROMOTE TO NEXT ROUND ONLY WHEN SAFE -----
        if not data["current_round"] and data["next_round"]:
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

            if new_len == 1:
                final = data["current_round"][0]
                data["running"] = False
                data["last_winner"] = final
                save_data(data, sha)

                await interaction.channel.send(f"@everyone We have a winner of The World Cup of **{title}** ‼️👀")

                winner_embed = discord.Embed(
                    title="🏁 Tournament Winner!",
                    description=f"🎉 **{final}** wins the World Cup of {data['title']}!",
                    color=discord.Color.green()
                )
                winner_embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")
                await interaction.channel.send(embed=winner_embed)
                return

            if new_len >= 2:
                await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show tournament overview")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        await showwcmatchups_internal(interaction.channel, data)
        return await interaction.response.send_message("📊 Done.", ephemeral=True)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset everything")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        _, sha = load_data()
        save_data(DEFAULT_DATA.copy(), sha)

        return await interaction.response.send_message("🔄 Reset complete.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="Force end the tournament")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()

        if not data.get("running"):
            return await interaction.response.send_message("❌ No running tournament.", ephemeral=True)

        winner = data.get("last_winner") or "Unknown"

        await interaction.channel.send(f"@everyone Tournament has ended early!")

        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 **{winner}** wins the World Cup of {data.get('title')}!",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")

        await interaction.channel.send(embed=embed)

        data["running"] = False
        save_data(data, sha)

        return await interaction.response.send_message("✔️ Announced.", ephemeral=True)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Help menu")
    async def wchelp(interaction: discord.Interaction):

        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())
        embed.add_field(name="/addwcitem", value="Add items", inline=False)
        embed.add_field(name="/removewcitem", value="Remove items", inline=False)
        embed.add_field(name="/listwcitems", value="List items", inline=False)
        embed.add_field(name="/startwc", value="Start tournament (32 items)", inline=False)
        embed.add_field(name="/nextwcround", value="Process match + next match", inline=False)
        embed.add_field(name="/showwcmatchups", value="Show overview", inline=False)
        embed.add_field(name="/resetwc", value="Reset", inline=False)
        embed.add_field(name="/endwc", value="Force end", inline=False)

        return await interaction.response.send_message(embed=embed, ephemeral=True)