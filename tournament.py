# tournament.py
import discord
from discord import app_commands
import json
import random
import asyncio

TOURNAMENT_JSON = "tournament_data.json"

def load_data():
    with open(TOURNAMENT_JSON, "r") as f:
        return json.load(f)

def save_data(data):
    with open(TOURNAMENT_JSON, "w") as f:
        json.dump(data, f, indent=2)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def reset_tournament():
        data = load_data()
        data["items"] = []
        data["current_round"] = []
        data["next_round"] = []
        data["scores"] = {}
        data["running"] = False
        data["title"] = ""
        data["test_mode"] = False
        save_data(data)

    @tree.command(name="addwcitem", description="Add an item to the tournament")
    @app_commands.describe(item="Item name to add")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item not in data["items"]:
            data["items"].append(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Added {item} to the tournament.")
        else:
            await interaction.response.send_message("⚠️ Item already exists.", ephemeral=True)

    @tree.command(name="removewcitem", description="Remove an item from the tournament")
    @app_commands.describe(item="Item name to remove")
    async def removewcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = load_data()
        if item in data["items"]:
            data["items"].remove(item)
            save_data(data)
            await interaction.response.send_message(f"✅ Removed {item} from the tournament.")
        else:
            await interaction.response.send_message("⚠️ Item not found.", ephemeral=True)

    @tree.command(name="listwcitems", description="List all items in the tournament")
    async def listwcitems(interaction: discord.Interaction):
        data = load_data()
        if data["items"]:
            await interaction.response.send_message("🏆 Tournament items:\n" + "\n".join(data["items"]))
        else:
            await interaction.response.send_message("No items added yet.")

    @tree.command(name="resetwc", description="Reset the entire tournament")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        await reset_tournament()
        await interaction.response.send_message("♻️ Tournament has been reset.")

    @tree.command(name="startwc", description="Start the tournament")
    @app_commands.describe(title="Custom World Cup title", test="Run in test mode (10 sec rounds)")
    async def startwc(interaction: discord.Interaction, title: str, test: bool = False):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = load_data()
        if len(data["items"]) < 2:
            await interaction.response.send_message("⚠️ Need at least 2 items to start a tournament.")
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Tournament cannot start with an odd number of items.")
            return

        data["running"] = True
        data["title"] = f"Landing Strip World Cup Of {title}"
        data["test_mode"] = test
        data["current_round"] = data["items"].copy()
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        save_data(data)

        await interaction.response.send_message(f"🏁 Tournament **{data['title']}** started!" + (" (Test mode 10s rounds)" if test else ""))

        await run_round(interaction.channel, data)

    async def run_round(channel, data):
        # Voting per round
        current = data["current_round"]
        next_round = []

        while len(current) > 1:
            round_pairs = [current[i:i+2] for i in range(0, len(current), 2)]
            for pair in round_pairs:
                if len(pair) < 2:
                    next_round.append(pair[0])
                    continue

                embed = discord.Embed(title=f"Vote for your favorite", description=f"A: {pair[0]} vs B: {pair[1]}")
                message = await channel.send(embed=embed)
                await message.add_reaction("🇦")
                await message.add_reaction("🇧")

                def check(reaction, user):
                    return str(reaction.emoji) in ["🇦", "🇧"] and not user.bot and reaction.message.id == message.id

                # Wait for votes
                if data["test_mode"]:
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(86400)  # 24 hours

                message = await channel.fetch_message(message.id)
                a_votes = sum(1 for r in message.reactions if str(r.emoji) == "🇦" for u in await r.users().flatten() if not u.bot)
                b_votes = sum(1 for r in message.reactions if str(r.emoji) == "🇧" for u in await r.users().flatten() if not u.bot)

                winner = pair[0] if a_votes >= b_votes else pair[1]
                next_round.append(winner)
                data["scores"][winner] += 1
                save_data(data)

            current = next_round
            next_round = []
            data["current_round"] = current
            save_data(data)

        # Tournament winner
        winner = current[0]
        embed = discord.Embed(title=f"🏆 {winner} wins the {data['title']}!")
        embed.set_image(url="https://media.giphy.com/media/3o6Zt6ML6BklcajjsA/giphy.gif")  # winning GIF
        await channel.send(embed=embed)
        data["running"] = False
        save_data(data)

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data = load_data()
        if not data["scores"]:
            await interaction.response.send_message("No scores yet.")
            return
        sorted_scores = sorted(data["scores"].items(), key=lambda x: x[1], reverse=True)
        embed = discord.Embed(title=f"📊 {data['title']} Scoreboard")
        for item, score in sorted_scores:
            embed.add_field(name=item, value=str(score), inline=False)
        await interaction.response.send_message(embed=embed)