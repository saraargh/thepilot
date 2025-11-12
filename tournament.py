# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import asyncio
import json
import random

# ===== CONFIG =====
VOTE_DURATION_PROD = 24*60*60  # 24 hours in seconds
WINNER_GIF = "https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyNnFjc3Bxc3AycXk0MHZmNTVwZnE5MHIycXZrbWp1a3pzM3ppdDhobiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ktHuiYG7qYCOrJCqG0/giphy.gif"

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles, data_file):

    # ===== Helper Functions =====
    def load_data():
        try:
            with open(data_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"tournament": None, "items_pool": [], "scoreboard": {}}

    def save_data(data):
        with open(data_file, "w") as f:
            json.dump(data, f, indent=4)

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    # ===== Tournament Commands =====
    @tree.command(name="addwcitem", description="Add an item to the tournament pool")
    @app_commands.describe(item="Item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        pool = data.get("items_pool", [])
        if item in pool:
            await interaction.response.send_message("❌ Item already in the pool.", ephemeral=True)
            return
        pool.append(item)
        data["items_pool"] = pool
        save_data(data)
        await interaction.response.send_message(f"✅ Added **{item}** to the pool.")

    @tree.command(name="removewcitem", description="Remove an item from the tournament pool")
    @app_commands.describe(item="Item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        pool = data.get("items_pool", [])
        if item not in pool:
            await interaction.response.send_message("❌ Item not in the pool.", ephemeral=True)
            return
        pool.remove(item)
        data["items_pool"] = pool
        save_data(data)
        await interaction.response.send_message(f"✅ Removed **{item}** from the pool.")

    @tree.command(name="listwcitems", description="List all items currently in the tournament pool")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        pool = data.get("items_pool", [])
        if not pool:
            await interaction.response.send_message("⚠️ The tournament pool is empty.", ephemeral=True)
            return
        item_list = "\n".join(f"- {i}" for i in pool)
        embed = discord.Embed(title="📋 Tournament Pool", description=item_list, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @tree.command(name="start_tournament", description="Start a tournament from the pool")
    @app_commands.describe(test_mode="Run in fast test mode (10s per match)")
    async def start_tournament(interaction: discord.Interaction, test_mode: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        pool = data.get("items_pool", [])

        if len(pool) < 2:
            await interaction.response.send_message("❌ Not enough items to start.", ephemeral=True)
            return
        if len(pool) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even!", ephemeral=True)
            return

        VOTE_DURATION = 10 if test_mode else VOTE_DURATION_PROD

        # Initialize scoreboard
        data["scoreboard"] = {item: 0 for item in pool}
        save_data(data)

        await interaction.response.send_message(f"🏆 Tournament started! Test mode: {test_mode}")

        # Start first round
        await run_round(interaction.channel, pool, VOTE_DURATION, data_file)

# ===== Tournament Round Logic =====
async def run_round(channel: discord.TextChannel, items, vote_duration, data_file):
    data = json.load(open(data_file))
    scoreboard = data.get("scoreboard", {})

    round_num = 1
    current_items = items.copy()

    while len(current_items) > 1:
        random.shuffle(current_items)
        next_round = []

        # Pair up items
        for i in range(0, len(current_items), 2):
            item1 = current_items[i]
            item2 = current_items[i+1]

            embed = discord.Embed(
                title=f"🏆 Round {round_num}: Vote Now!",
                description=f"React with ✅ for **{item1}** or ❌ for **{item2}**",
                color=discord.Color.gold()
            )
            embed.set_footer(text="Voting lasts 24h (or test duration)")
            msg = await channel.send("@everyone", embed=embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")

            # Wait for votes
            await asyncio.sleep(vote_duration)

            # Refresh reactions
            msg = await channel.fetch_message(msg.id)
            count1 = sum(r.count for r in msg.reactions if str(r.emoji) == "✅") - 1
            count2 = sum(r.count for r in msg.reactions if str(r.emoji) == "❌") - 1

            winner = item1 if count1 >= count2 else item2
            next_round.append(winner)
            scoreboard[winner] += 1

        current_items = next_round
        round_num += 1

    # Announce winner
    winner_item = current_items[0]
    embed = discord.Embed(
        title="🎉 Tournament Winner!",
        description=f"🏆 **{winner_item}** has won the tournament!",
        color=discord.Color.green()
    )
    embed.set_image(url=WINNER_GIF)
    await channel.send("@everyone", embed=embed)

    # Save final scoreboard
    data["scoreboard"] = scoreboard
    with open(data_file, "w") as f:
        json.dump(data, f, indent=4)

# ===== Scoreboard Command =====
@tree.command(name="scoreboard", description="View the current tournament scoreboard")
async def scoreboard(interaction: discord.Interaction):
    data = json.load(open("tournament_data.json"))
    scoreboard = data.get("scoreboard", {})
    if not scoreboard:
        await interaction.response.send_message("⚠️ No tournament has started yet.", ephemeral=True)
        return
    lines = [f"**{item}**: {score}" for item, score in scoreboard.items()]
    embed = discord.Embed(
        title="📊 Tournament Scoreboard",
        description="\n".join(lines),
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed)