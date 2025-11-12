# tournament.py
import discord
from discord import app_commands
from discord.ext import tasks
import json
import random
import asyncio
import os

TOURNAMENT_JSON = "tournament_data.json"

def load_data():
    if not os.path.exists(TOURNAMENT_JSON):
        with open(TOURNAMENT_JSON, "w") as f:
            json.dump({
                "items": [],
                "current_round": [],
                "next_round": [],
                "scores": {},
                "running": False,
                "title": "",
                "test_mode": False
            }, f)
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=4)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    # ===== Item Commands =====
    @tree.command(name="addwcitem", description="Add an item to the world cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            await interaction.response.send_message(f"⚠️ '{item}' is already in the list.")
            return
        data["items"].append(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Added '{item}' to the items list.")

    @tree.command(name="removewcitem", description="Remove an item from the world cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data = load_data()
        if item not in data["items"]:
            await interaction.response.send_message(f"⚠️ '{item}' not found in the list.")
            return
        data["items"].remove(item)
        save_data(data)
        await interaction.response.send_message(f"✅ Removed '{item}' from the items list.")

    @tree.command(name="listwcitems", description="List current items for the world cup")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        items = data["items"]
        if not items:
            await interaction.response.send_message("📋 No items in the list yet.")
        else:
            await interaction.response.send_message("📋 Items:\n" + "\n".join(f"- {i}" for i in items))

    # ===== Reset Command =====
    @tree.command(name="resetwc", description="Reset the world cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data = {
            "items": [],
            "current_round": [],
            "next_round": [],
            "scores": {},
            "running": False,
            "title": "",
            "test_mode": False
        }
        save_data(data)
        await interaction.response.send_message("🔄 World Cup has been reset.")

    # ===== Start Tournament =====
    @tree.command(name="startwc", description="Start the world cup tournament")
    @app_commands.describe(title="Name of the tournament", test="Enable test mode for quick rounds")
    async def startwc(interaction: discord.Interaction, title: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
            return
        data = load_data()
        if data["running"]:
            await interaction.response.send_message("⚠️ Tournament already running.")
            return
        if len(data["items"]) < 2 or len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even and ≥2 to start.")
            return

        data["running"] = True
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {i: 0 for i in data["items"]}
        data["title"] = title
        data["test_mode"] = test
        save_data(data)

        await interaction.response.send_message(f"🏆 **Landing Strip World Cup of {title}** started!\nTest mode: {'ON' if test else 'OFF'}")

        # Start first round
        await run_round(interaction.channel, test)

    # ===== Round Logic =====
    async def run_round(channel: discord.TextChannel, test: bool):
        data = load_data()
        current = data["current_round"]

        if len(current) == 1:
            winner = current[0]
            embed = discord.Embed(
                title=f"🏆 Landing Strip World Cup Winner!",
                description=f"The champion is **{winner}**!",
                color=discord.Color.gold()
            )
            embed.set_image(url="https://media.giphy.com/media/3ohzdIuqJoo8QdKlnW/giphy.gif")  # winner GIF
            await channel.send(embed=embed)
            data["running"] = False
            save_data(data)
            return

        random.shuffle(current)
        pairs = [current[i:i+2] for i in range(0, len(current), 2)]

        for a, b in pairs:
            if len(pairs[-1]) == 1:
                # Odd number safety
                await channel.send(f"⚠️ Odd number of items, last item moves automatically: {a}")
                data["next_round"].append(a)
                continue

            # Voting embed
            embed = discord.Embed(
                title=f"Vote for your favorite!",
                description=f"React with 🇦 for **{a}** or 🇧 for **{b}**",
                color=discord.Color.blue()
            )
            msg = await channel.send(embed=embed)
            await msg.add_reaction("🇦")
            await msg.add_reaction("🇧")

            # Wait for votes
            wait_time = 10 if test else 60 * 60 * 24  # 10s for test, 24h normally
            await asyncio.sleep(wait_time)

            # Fetch reactions
            msg = await channel.fetch_message(msg.id)
            a_votes = discord.utils.get(msg.reactions, emoji="🇦").count - 1
            b_votes = discord.utils.get(msg.reactions, emoji="🇧").count - 1

            if a_votes >= b_votes:
                winner = a
            else:
                winner = b
            data["next_round"].append(winner)
            data["scores"][winner] += 1
            save_data(data)

        # Prepare next round
        data["current_round"] = data["next_round"]
        data["next_round"] = []
        save_data(data)
        await run_round(channel, test)

    # ===== Scoreboard =====
    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        if not data["running"]:
            await interaction.response.send_message("⚠️ No tournament currently running.")
            return
        scores = data["scores"]
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        description = "\n".join([f"**{k}**: {v} points" for k, v in sorted_scores])
        embed = discord.Embed(
            title=f"📊 {data['title']} Scoreboard",
            description=description,
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)