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

    common = a_users & b_users
    for uid in common:
        if uid in b_users:
            a_users.remove(uid)
            a_names.pop(uid, None)
        else:
            b_users.remove(uid)
            b_names.pop(uid, None)

    return len(a_users), len(b_users), a_names, b_names

# ------------------- Main Command Setup -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ------------------- Internal Show Matchups -------------------
    async def showwcmatchups_internal(channel, data):
        finished = data.get("finished_matches", [])
        lines_finished = [
            f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
            for i, f in enumerate(finished)
        ]

        last = data.get("last_match")
        current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else None

        upcoming_pairs = []
        cr = data.get("current_round", []).copy()
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                upcoming_pairs.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming_pairs.append(f"{cr[i]} (auto-advance if odd)")

        embed = discord.Embed(title="📋 World Cup Matchup Overview", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
        embed.add_field(name="Round Stage", value=data.get("round_stage") or "N/A", inline=False)
        embed.add_field(name="Finished Matches", value="\n".join(lines_finished) if lines_finished else "None", inline=False)
        embed.add_field(name="Current Match (voting)", value=current_pair or "None", inline=False)
        embed.add_field(name="Upcoming Matchups", value="\n".join(upcoming_pairs) if upcoming_pairs else "None", inline=False)

        await channel.send(embed=embed)

    # ------------------- Post Next Match -------------------
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
            "channel_id": channel.id
        }
        sha = save_data(data, sha)

        # ------------------ FIXED VOTING LOOP -------------------
        def check(reaction, user):
            return (
                user != channel.guild.me
                and reaction.message.id == msg.id
                and str(reaction.emoji) in [VOTE_A, VOTE_B]
            )

        async def reaction_loop():
            client = channel.guild._state.client  # ✅ correct way to reach bot

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

                    await msg.edit(
                        embed=discord.Embed(
                            title=f"🎮 {data.get('round_stage', 'Matchup')}",
                            description=desc,
                            color=discord.Color.random()
                        )
                    )

                except Exception:
                    continue

        asyncio.create_task(reaction_loop())
        return sha
            # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
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
                f"✅ Added {len(added)} item(s): {', '.join(added)}", ephemeral=False
            )
        else:
            return await interaction.response.send_message("⚠️ No new items added.", ephemeral=False)

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (comma-separated, case-insensitive)")
    @app_commands.describe(items="Comma-separated items to remove")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

        data, sha = load_data()
        items_out = [x.strip() for x in items.split(",") if x.strip()]
        removed = []

        lower_items = {i.lower(): i for i in data["items"]}

        for it in items_out:
            key = it.lower()
            if key in lower_items:
                original = lower_items[key]
                data["items"].remove(original)
                data["scores"].pop(original, None)
                removed.append(original)

        sha = save_data(data, sha)

        if removed:
            return await interaction.response.send_message(
                f"✅ Removed: {', '.join(removed)}", ephemeral=False
            )
        else:
            return await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)

    # ------------------- /listwcitems (TEXT ONLY) -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()

        if not data["items"]:
            return await interaction.response.send_message("No items added yet.", ephemeral=True)

        text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(data["items"])])
        return await interaction.response.send_message(f"📋 **World Cup Items:**\n{text}", ephemeral=False)

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup (requires exactly 32 items)")
    @app_commands.describe(title="World Cup of ___")
    async def startwc(interaction: discord.Interaction, title: str):
        await interaction.response.defer(ephemeral=True)

        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.followup.send("❌ You do not have permission.", ephemeral=True)

        data, sha = load_data()

        if data["running"]:
            return await interaction.followup.send("❌ A World Cup is already running.", ephemeral=True)

        if len(data["items"]) != 32:
            return await interaction.followup.send("❌ You need exactly 32 items.", ephemeral=True)

        data["title"] = title
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []

        for it in data["items"]:
            data["scores"].setdefault(it, 0)

        data["running"] = True
        data["last_winner"] = None
        data["last_match"] = None
        data["finished_matches"] = []

        data["round_stage"] = STAGE_BY_COUNT.get(32, "Round")
        sha = save_data(data, sha)

        await interaction.channel.send(
            f"@everyone, the World Cup of {data['title']} is starting! 🏆"
        )
        await showwcmatchups_internal(interaction.channel, data)

        if len(data["current_round"]) >= 2:
            sha = await post_next_match(interaction.channel, data, sha)

        return await interaction.followup.send("✅ World Cup started!", ephemeral=True)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Count votes, announce winner, post next match")
    async def nextwcround(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data, sha = load_data()

        if not data.get("running"):
            return await interaction.followup.send("❌ No active World Cup.", ephemeral=True)

        guild = interaction.guild

        # ------------------ If there is a pending match ------------------
        if data.get("last_match"):
            lm = data["last_match"]

            a_votes, b_votes, _, _ = await count_votes_from_message(
                guild, lm["channel_id"], lm["message_id"]
            )

            a_item = lm["a"]
            b_item = lm["b"]

            # Winner or random tiebreak
            if a_votes > b_votes:
                winner = a_item
            elif b_votes > a_votes:
                winner = b_item
            else:
                winner = random.choice([a_item, b_item])

            data["finished_matches"].append({
                "a": a_item,
                "b": b_item,
                "winner": winner,
                "a_votes": a_votes,
                "b_votes": b_votes
            })

            data["next_round"].append(winner)
            data["scores"].setdefault(winner, 0)
            data["scores"][winner] += 1

            data["last_winner"] = winner
            data["last_match"] = None
            sha = save_data(data, sha)

            await interaction.channel.send(f"@everyone, the next fixture is ready!")

            embed = discord.Embed(
                title="🏆 Match Result",
                description=f"**{winner}** wins!\n\nVotes — {VOTE_A} {a_item}: {a_votes} | {VOTE_B} {b_item}: {b_votes}",
                color=discord.Color.gold()
            )
            await interaction.channel.send(embed=embed)

            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("✔️ Match processed.", ephemeral=True)

        # ------------------- Promote to next round -------------------
        if not data["current_round"] and data["next_round"]:

            prev_stage = data.get("round_stage", "Round")
            data["current_round"] = data["next_round"].copy()
            data["next_round"] = []

            new_count = len(data["current_round"])
            data["round_stage"] = STAGE_BY_COUNT.get(new_count, f"{new_count}-items round")

            sha = save_data(data, sha)

            contenders = ", ".join(data["current_round"])

            embed = discord.Embed(
                title=f"✅ {prev_stage} complete!",
                description=f"We are now in **{data['round_stage']}**.\nContenders:\n{contenders}",
                color=discord.Color.purple()
            )
            await interaction.channel.send(embed=embed)

            if len(data["current_round"]) == 1:
                final = data["current_round"][0]
                data["running"] = False
                data["last_winner"] = final
                sha = save_data(data, sha)

                embed = discord.Embed(
                    title="🏁 Tournament Winner!",
                    description=f"🎉 **{final}** wins the World Cup of {data['title']}! 🥳",
                    color=discord.Color.green()
                )
                embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")

                await interaction.channel.send(f"@everyone, We have a winner!")
                await interaction.channel.send(embed=embed)

                return

            if len(data["current_round"]) >= 2:
                sha = await post_next_match(interaction.channel, data, sha)

            return await interaction.followup.send("🔁 Next round posted.", ephemeral=True)

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show finished, current, upcoming matches")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        await showwcmatchups_internal(interaction.channel, data)
        return await interaction.response.send_message("📊 Matchups shown.", ephemeral=True)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        _, sha = load_data()
        data = DEFAULT_DATA.copy()
        save_data(data, sha)

        return await interaction.response.send_message("🔄 World Cup reset.", ephemeral=False)

    # ------------------- /endwc -------------------
    @tree.command(name="endwc", description="End the World Cup now")
    async def endwc(interaction: discord.Interaction):
        data, sha = load_data()

        if not data.get("running"):
            return await interaction.response.send_message("❌ No running tournament.", ephemeral=True)

        winner = data.get("last_winner") or "Unknown"

        embed = discord.Embed(
            title="🎉 World Cup Finished!",
            description=f"🏆 **{winner}** wins the **World Cup of {data.get('title')}**!",
            color=discord.Color.green()
        )
        embed.set_image(url="https://media1.tenor.com/m/XU8DIUrUZaoAAAAd/happy-dance.gif")

        await interaction.channel.send(f"@everyone, We have a winner!")
        await interaction.channel.send(embed=embed)

        data["running"] = False
        save_data(data, sha)

        return await interaction.response.send_message("✔️ Winner announced.", ephemeral=True)

    # ------------------- /wchelp -------------------
    @tree.command(name="wchelp", description="Show help for World Cup commands")
    async def wchelp(interaction: discord.Interaction):
        embed = discord.Embed(title="📝 World Cup Help", color=discord.Color.blue())
        embed.add_field(name="/addwcitem", value="Add items (comma-separated)", inline=False)
        embed.add_field(name="/removewcitem", value="Remove items (case-insensitive)", inline=False)
        embed.add_field(name="/listwcitems", value="List items", inline=False)
        embed.add_field(name="/startwc", value="Start tournament", inline=False)
        embed.add_field(name="/nextwcround", value="Count votes + next match", inline=False)
        embed.add_field(name="/showwcmatchups", value="Show all matchups", inline=False)
        embed.add_field(name="/resetwc", value="Reset everything", inline=False)
        embed.add_field(name="/endwc", value="Force end + announce winner", inline=False)

        return await interaction.response.send_message(embed=embed, ephemeral=True)