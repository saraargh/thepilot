import discord
from discord import app_commands
import random
import asyncio
from github_helpers import load_data, save_data, DEFAULT_DATA  # import helpers

# ------------------- Tournament Logic -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    def user_allowed(member: discord.Member):
        return any(role.id in allowed_role_ids for role in member.roles)

    async def run_next_match(interaction: discord.Interaction):
        # Load data from GitHub
        data, sha = load_data()
        if not data["running"]:
            await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
            return

        current = data["current_round"]
        if not current or len(current) < 2:
            await interaction.response.send_message("❌ Not enough items to run a matchup.", ephemeral=True)
            return

        # Run single matchup (first two items)
        a_item = current.pop(0)
        b_item = current.pop(0)

        embed = discord.Embed(
            title=f"Vote for the winner!",
            description=f"🇦 {a_item}\n🇧 {b_item}"
        )
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("🇦")
        await msg.add_reaction("🇧")

        def check(reaction, user):
            return str(reaction.emoji) in ["🇦", "🇧"] and not user.bot

        votes = {"🇦": 0, "🇧": 0}

        try:
            while True:
                reaction, user = await interaction.client.wait_for(
                    "reaction_add", timeout=10, check=check
                )
                votes[str(reaction.emoji)] += 1
        except asyncio.TimeoutError:
            pass

        winner = a_item if votes["🇦"] >= votes["🇧"] else b_item
        data["last_winner"] = winner
        data["scores"][winner] = data["scores"].get(winner, 0) + 1
        await interaction.channel.send(f"🏆 {winner} wins this matchup!")

        # Save back updated round and data
        data["current_round"] = current
        save_data(data, sha)

        # Check if round is over
        if not current:
            # Move winners to next round
            data["current_round"] = data.get("next_round", [])
            data["next_round"] = []
            save_data(data, sha)
            if not data["current_round"]:
                # Tournament finished
                await interaction.channel.send(f"🎉 **{winner}** is the overall winner of **{data['title']}**!")
                data["running"] = False
                save_data(data, sha)

    # ------------------- Commands -------------------

    @tree.command(name="addwcitem", description="Add one or multiple items to the World Cup")
    @app_commands.describe(item="The item(s) to add, separated by commas")
    async def addwcitem(interaction: discord.Interaction, item: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()
        items = [x.strip() for x in item.split(",") if x.strip()]
        data["items"].extend(items)
        save_data(data, sha)
        await interaction.response.send_message(f"✅ Added: {', '.join(items)}")

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items in the World Cup yet.", ephemeral=True)
            return
        await interaction.response.send_message("📋 World Cup Items:\n" + "\n".join(data["items"]))

    @tree.command(name="resetwc", description="Reset the World Cup (clears all items and scores)")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        save_data(DEFAULT_DATA.copy())
        await interaction.response.send_message("🔄 World Cup reset. All items and scores cleared.")

    @tree.command(name="startwc", description="Start the World Cup of something")
    @app_commands.describe(title="The World Cup title (e.g. Pizza)")
    async def startwc(interaction: discord.Interaction, title: str):
        if not user_allowed(interaction.user):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, sha = load_data()
        if data["running"]:
            await interaction.response.send_message("❌ A World Cup is already running.", ephemeral=True)
            return
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ Add at least 2 items before starting.", ephemeral=True)
            return
        if len(data["items"]) % 2 != 0:
            await interaction.response.send_message("❌ Number of items must be even to start.", ephemeral=True)
            return

        data["title"] = f"Landing Strip World Cup Of {title}"
        data["current_round"] = data["items"].copy()
        random.shuffle(data["current_round"])
        data["next_round"] = []
        data["scores"] = {item: 0 for item in data["items"]}
        data["running"] = True
        data["last_winner"] = None
        save_data(data, sha)
        await interaction.response.send_message(f"🏁 Starting **{data['title']}**!")

    @tree.command(name="nextwcround", description="Run the next matchup of the current World Cup")
    async def nextwcround(interaction: discord.Interaction):
        await run_next_match(interaction)

    @tree.command(name="scoreboard", description="View the current tournament scoreboard")
    async def scoreboard(interaction: discord.Interaction):
        data, _ = load_data()
        scores = data.get("scores", {})
        if not scores:
            await interaction.response.send_message("No scoreboard yet.", ephemeral=True)
            return
        msg = "📊 **Scoreboard:**\n"
        for item, score in scores.items():
            msg += f"{item}: {score}\n"
        await interaction.response.send_message(msg)