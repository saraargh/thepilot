# tournament.py
import discord
from discord import app_commands
import asyncio
import json
import os

TOURNAMENT_JSON = "tournament_data.json"

# Load existing data or create empty
if os.path.exists(TOURNAMENT_JSON):
    with open(TOURNAMENT_JSON, "r") as f:
        tournament_data = json.load(f)
else:
    tournament_data = {
        "active": False,
        "name": "",
        "items": [],
        "matches": [],
        "current_match": (),
        "votes": {},
        "scoreboard": {},
        "test_mode": False
    }

def save_tournament_data():
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(tournament_data, f, indent=4)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    # ----- ITEM MANAGEMENT -----
    @tree.command(name="addwcitem", description="Add an item to the tournament")
    @app_commands.describe(item="The item name to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        tournament_data.setdefault("items", [])
        tournament_data["items"].append(item)
        save_tournament_data()
        await interaction.response.send_message(f"✅ Added `{item}` to the tournament.")

    @tree.command(name="removewcitem", description="Remove an item from the tournament")
    @app_commands.describe(item="The item name to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        if item in tournament_data.get("items", []):
            tournament_data["items"].remove(item)
            save_tournament_data()
            await interaction.response.send_message(f"✅ Removed `{item}` from the tournament.")
        else:
            await interaction.response.send_message(f"⚠️ `{item}` is not in the tournament items.")

    @tree.command(name="listwcitems", description="List all items in the tournament")
    async def listwcitems(interaction: discord.Interaction):
        items = tournament_data.get("items", [])
        if not items:
            await interaction.response.send_message("⚠️ No items added yet.")
        else:
            await interaction.response.send_message("🏆 Tournament Items:\n" + "\n".join(f"- {i}" for i in items))

    # ----- START TOURNAMENT -----
    @tree.command(name="startwc", description="Start a new Landing Strip World Cup tournament")
    @app_commands.describe(
        name="The name of the tournament (bot prepends 'Landing Strip World Cup Of')",
        test="Enable test mode (10-second matches for quick testing)"
    )
    async def startwc(interaction: discord.Interaction, name: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        if tournament_data.get("active", False):
            await interaction.response.send_message("❌ A tournament is already running!", ephemeral=True)
            return

        tournament_data["active"] = True
        tournament_data["name"] = f"Landing Strip World Cup Of {name}"
        tournament_data["matches"] = []
        tournament_data["votes"] = {}
        tournament_data["scoreboard"] = {}
        tournament_data["test_mode"] = test
        save_tournament_data()

        await interaction.response.send_message(
            f"🏁 Tournament started: **{tournament_data['name']}**\n"
            f"{'⚡ Test mode enabled: matches last 10 seconds!' if test else ''}"
        )

        if len(tournament_data["items"]) < 2:
            await interaction.followup.send("⚠️ Need at least 2 items to start a match.")
            return

        # Start first match
        await start_match(interaction.channel)

    # ----- SCOREBOARD -----
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        scores = tournament_data.get("scoreboard", {})
        if not scores:
            await interaction.response.send_message("⚠️ No matches played yet.")
            return
        msg = "🏆 **Scoreboard**\n" + "\n".join(f"{item}: {score}" for item, score in scores.items())
        await interaction.response.send_message(msg)

# ----- MATCH LOGIC -----
async def start_match(channel: discord.TextChannel):
    items = tournament_data.get("items", [])
    if len(items) < 2:
        await channel.send("⚠️ Not enough items for a match.")
        return

    item1, item2 = items[:2]
    tournament_data["current_match"] = (item1, item2)
    tournament_data["votes"] = {item1: 0, item2: 0}
    save_tournament_data()

    match_msg = await channel.send(
        f"🏆 **{tournament_data['name']}** — First Match!\n"
        f"Vote for your favorite:\n"
        f"A️⃣ {item1}\n"
        f"B️⃣ {item2}\n"
        f"React with A or B to vote!"
    )

    await match_msg.add_reaction("🇦")
    await match_msg.add_reaction("🇧")

    duration = 10 if tournament_data.get("test_mode") else 86400
    await asyncio.sleep(duration)

    match_msg = await channel.fetch_message(match_msg.id)
    counts = {"A": 0, "B": 0}
    for reaction in match_msg.reactions:
        if reaction.emoji == "🇦":
            counts["A"] = reaction.count - 1
        elif reaction.emoji == "🇧":
            counts["B"] = reaction.count - 1

    winner = item1 if counts["A"] >= counts["B"] else item2
    tournament_data.setdefault("scoreboard", {})
    tournament_data["scoreboard"][winner] = tournament_data["scoreboard"].get(winner, 0) + 1
    save_tournament_data()

    await channel.send(f"✅ Match finished! **{winner}** won the round!")

    # Prepare next match
    # Simple rotation: remove losing item from the first two
    items.remove(item1 if winner == item2 else item2)
    tournament_data["items"] = items
    save_tournament_data()

    if len(items) >= 2:
        await start_match(channel)
    else:
        tournament_data["active"] = False
        save_tournament_data()
        await channel.send(f"🎉 Tournament **{tournament_data['name']}** completed!")