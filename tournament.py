import discord
from discord.ext import tasks
from discord import app_commands
import asyncio
import json
import os

DATA_FILE = "tournament_data.json"
VOTE_A = "🔴"
VOTE_B = "🔵"

# ------------------- Helpers -------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"items": [], "rounds": [], "votes": {}}, False
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f), True

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def user_allowed(user, allowed_role_ids):
    return any(role.id in allowed_role_ids for role in user.roles)

# ------------------- Setup function -------------------
def setup_tournament_commands(tree, allowed_role_ids):

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["rounds"]:
            await interaction.response.send_message("No matchups available. Add items first.", ephemeral=True)
            return
        data["current_matchup"] = 0
        data["votes"] = {}
        save_data(data)
        matchup = data["rounds"][0]
        embed = discord.Embed(
            title=f"🎮 {matchup.get('round_stage','Matchup')}",
            description=f"{VOTE_A} {matchup['a']} vs {VOTE_B} {matchup['b']}",
            color=discord.Color.random()
        )
        msg = await interaction.channel.send(embed=embed)
        await interaction.response.send_message("World Cup started!", ephemeral=True)

        # Start vote update loop
        async def update_votes_loop():
            while True:
                data, _ = load_data()
                if "current_matchup" not in data:
                    break
                idx = data["current_matchup"]
                matchup = data["rounds"][idx]
                a_count = len([v for v in data["votes"].values() if v == "a"])
                b_count = len([v for v in data["votes"].values() if v == "b"])
                a_names = {k: k for k,v in data["votes"].items() if v == "a"}
                b_names = {k: k for k,v in data["votes"].items() if v == "b"}
                desc = f"{VOTE_A} {matchup['a']} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {matchup['b']} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"
                embed.description = desc
                embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")
                try:
                    await msg.edit(embed=embed)
                except Exception:
                    pass
                await asyncio.sleep(2)

        asyncio.create_task(update_votes_loop())
            # ------------------- Voting Buttons -------------------
    class VoteView(discord.ui.View):
        def __init__(self, matchup_idx):
            super().__init__(timeout=None)
            self.matchup_idx = matchup_idx

        @discord.ui.button(label="Red", style=discord.ButtonStyle.danger)
        async def vote_red(self, interaction: discord.Interaction, button: discord.ui.Button):
            data, _ = load_data()
            uid = str(interaction.user.id)
            prev_vote = data["votes"].get(uid)
            data["votes"][uid] = "a"
            save_data(data)
            await interaction.response.defer()

        @discord.ui.button(label="Blue", style=discord.ButtonStyle.primary)
        async def vote_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
            data, _ = load_data()
            uid = str(interaction.user.id)
            prev_vote = data["votes"].get(uid)
            data["votes"][uid] = "b"
            save_data(data)
            await interaction.response.defer()

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Move to the next World Cup matchup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, _ = load_data()
        if "current_matchup" not in data:
            await interaction.response.send_message("No World Cup in progress.", ephemeral=True)
            return
        idx = data["current_matchup"] + 1
        if idx >= len(data["rounds"]):
            await interaction.channel.send("@everyone The World Cup has ended!")
            del data["current_matchup"]
            del data["votes"]
            save_data(data)
            await interaction.response.send_message("World Cup finished!", ephemeral=True)
            return
        data["current_matchup"] = idx
        data["votes"] = {}
        save_data(data)
        matchup = data["rounds"][idx]
        embed = discord.Embed(
            title=f"🎮 {matchup.get('round_stage','Matchup')}",
            description=f"{VOTE_A} {matchup['a']} vs {VOTE_B} {matchup['b']}",
            color=discord.Color.random()
        )
        msg = await interaction.channel.send(embed=embed, view=VoteView(idx))
        await interaction.response.send_message(f"Next matchup posted: {matchup['a']} vs {matchup['b']}", ephemeral=False)

    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, _ = load_data()
        new_items = [x.strip() for x in items.split(",") if x.strip()]
        data.setdefault("items", []).extend(new_items)
        save_data(data)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s).", ephemeral=True)
            # ------------------- /listwcitems -------------------
    class ItemListView(discord.ui.View):
        def __init__(self, items):
            super().__init__(timeout=None)
            self.items = items
            self.page = 0
            self.items_per_page = 10

        def get_page_content(self):
            start = self.page * self.items_per_page
            end = start + self.items_per_page
            page_items = self.items[start:end]
            desc = "\n".join([f"{i+1+start}. {item}" for i, item in enumerate(page_items)])
            return desc or "_No items_"

        @discord.ui.button(label="⬅", style=discord.ButtonStyle.secondary)
        async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page > 0:
                self.page -= 1
                embed = discord.Embed(title="📋 World Cup Items", description=self.get_page_content(), color=discord.Color.teal())
                await interaction.message.edit(embed=embed, view=self)

        @discord.ui.button(label="➡", style=discord.ButtonStyle.secondary)
        async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if (self.page + 1) * self.items_per_page < len(self.items):
                self.page += 1
                embed = discord.Embed(title="📋 World Cup Items", description=self.get_page_content(), color=discord.Color.teal())
                await interaction.message.edit(embed=embed, view=self)

    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])
        if not items:
            await interaction.response.send_message("_No items added yet._", ephemeral=True)
            return
        view = ItemListView(items)
        embed = discord.Embed(title="📋 World Cup Items", description=view.get_page_content(), color=discord.Color.teal())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the entire World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = {"rounds": [], "items": [], "votes": {}, "current_matchup": -1}
        save_data(data)
        await interaction.response.send_message("✅ World Cup has been reset.", ephemeral=True)

    # ------------------- /helpwc -------------------
    @tree.command(name="helpwc", description="Show help for World Cup commands")
    async def helpwc(interaction: discord.Interaction):
        help_text = (
            "/startwc — Start the World Cup\n"
            "/nextwcround — Post next matchup\n"
            "/addwcitem — Add items (comma-separated)\n"
            "/listwcitems — List all items\n"
            "/resetwc — Reset World Cup\n"
            "/helpwc — Show this help message"
        )
        await interaction.response.send_message(help_text, ephemeral=True)