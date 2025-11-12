# tournament.py
import discord
from discord import app_commands
import asyncio
import json
import random
from datetime import datetime, timedelta

WC_DATA_FILE = "tournament_data.json"

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_roles):

    # ===== Helpers =====
    def user_allowed(member: discord.Member):
        return any(role.id in allowed_roles for role in member.roles)

    def load_wc_data():
        try:
            with open(WC_DATA_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            data = {"items": [], "scores": {}, "current_matches": []}
            with open(WC_DATA_FILE, "w") as f:
                json.dump(data, f, indent=4)
            return data

    def save_wc_data(data):
        with open(WC_DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)

    async def post_match_embed(channel, match):
        item1, item2 = match
        embed = discord.Embed(
            title=f"🏆 Landing Strip World Cup Match",
            description=f"Vote for your favorite! 24h to vote.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Option 1", value=item1, inline=True)
        embed.add_field(name="Option 2", value=item2, inline=True)
        msg = await channel.send("@everyone", embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        return msg

    # ===== Commands =====
    @tree.command(name="addwcitem", description="Add an item to the world cup")
    @app_commands.describe(item="The item to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_wc_data()
        if item in data["items"]:
            await interaction.response.send_message("⚠️ Item already exists.", ephemeral=True)
            return
        data["items"].append(item)
        data["scores"][item] = 0
        save_wc_data(data)
        await interaction.response.send_message(f"✅ Added `{item}` to the tournament.")

    @tree.command(name="removewcitem", description="Remove an item from the world cup")
    @app_commands.describe(item="The item to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_wc_data()
        if item not in data["items"]:
            await interaction.response.send_message("⚠️ Item does not exist.", ephemeral=True)
            return
        data["items"].remove(item)
        data["scores"].pop(item, None)
        save_wc_data(data)
        await interaction.response.send_message(f"✅ Removed `{item}` from the tournament.")

    @tree.command(name="listwcitems", description="List all items in the world cup")
    async def listwcitems(interaction: discord.Interaction):
        data = load_wc_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return
        await interaction.response.send_message("🏆 Tournament Items:\n" + "\n".join(data["items"]))

    @tree.command(name="resettournament", description="Reset the tournament")
    async def resettournament(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = {"items": [], "scores": {}, "current_matches": []}
        save_wc_data(data)
        await interaction.response.send_message("✅ Tournament reset.")

    @tree.command(name="starttournament", description="Start the Landing Strip World Cup")
    @app_commands.describe(channel_id="Optional channel ID for posting matches", test_mode="Enable fast test mode")
    async def starttournament(interaction: discord.Interaction, channel_id: str = None, test_mode: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_wc_data()
        items = data["items"]
        if len(items) < 2:
            await interaction.response.send_message("⚠️ Not enough items to start a tournament.", ephemeral=True)
            return
        if len(items) % 2 != 0:
            await interaction.response.send_message("⚠️ Cannot start tournament with odd number of items.", ephemeral=True)
            return

        # Use provided channel or current
        channel = interaction.channel
        if channel_id:
            try:
                channel = interaction.guild.get_channel(int(channel_id))
            except:
                await interaction.response.send_message("⚠️ Invalid channel ID. Using current channel.")
                channel = interaction.channel

        await interaction.response.send_message(f"✅ Tournament started in {'test mode' if test_mode else 'normal mode'}!")

        # Shuffle and start rounds
        items_shuffled = items.copy()
        random.shuffle(items_shuffled)

        while len(items_shuffled) > 1:
            matches = []
            for i in range(0, len(items_shuffled), 2):
                matches.append((items_shuffled[i], items_shuffled[i+1]))
            data["current_matches"] = matches
            save_wc_data(data)

            # Post matches and collect votes (simplified)
            for match in matches:
                msg = await post_match_embed(channel, match)
                # Wait for voting period
                await asyncio.sleep(5 if test_mode else 24*3600)  # 5s for test mode, 24h normal

                # Tally votes
                message = await channel.fetch_message(msg.id)
                thumbs_up = discord.utils.get(message.reactions, emoji="👍")
                thumbs_down = discord.utils.get(message.reactions, emoji="👎")
                up_count = thumbs_up.count-1 if thumbs_up else 0
                down_count = thumbs_down.count-1 if thumbs_down else 0
                winner = match[0] if up_count >= down_count else match[1]
                data["scores"][winner] += 1
                items_shuffled.remove(match[0])
                items_shuffled.remove(match[1])
                items_shuffled.append(winner)
                save_wc_data(data)

        # Announce winner
        winner = items_shuffled[0]
        embed = discord.Embed(
            title=f"🎉 Landing Strip World Cup Winner: {winner}",
            description="Congratulations! 🏆",
            color=discord.Color.gold()
        )
        embed.set_image(url="https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyNnFjc3Bxc3AycXk0MHZmNTVwZnE5MHIycXZrbWp1a3pzM3ppdDhobiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ktHuiYG7qYCOrJCqG0/giphy.gif")
        await channel.send("@everyone", embed=embed)
        data["current_matches"] = []
        save_wc_data(data)

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_wc_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scores yet.", ephemeral=True)
            return
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        lines = [f"{item}: {score}" for item, score in sorted_scores]
        embed = discord.Embed(
            title="📊 Tournament Scoreboard",
            description="\n".join(lines),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)