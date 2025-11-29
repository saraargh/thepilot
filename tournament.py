import discord
from discord import app_commands
from discord.ui import Button, View
import asyncio
import json
import os

DATA_FILE = "tournament_data.json"

# Emoji for votes
VOTE_A = "🔴"
VOTE_B = "🔵"

def load_data():
    if not os.path.exists(DATA_FILE):
        data = {
            "items": [],
            "round_stage": "",
            "current_matchup": [],
            "votes": {}
        }
        save_data(data)
    else:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    return data

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)
        # ------------------- Voting Button View -------------------
class VoteView(View):
    def __init__(self, a_name, b_name, msg):
        super().__init__(timeout=None)
        self.a_name = a_name
        self.b_name = b_name
        self.msg = msg

        self.add_item(Button(label=a_name, style=discord.ButtonStyle.danger, custom_id="vote_a"))
        self.add_item(Button(label=b_name, style=discord.ButtonStyle.primary, custom_id="vote_b"))

        self.task = asyncio.create_task(self.update_votes_loop())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True  # All users can vote

    async def on_timeout(self):
        self.task.cancel()

    async def update_votes_loop(self):
        while True:
            await self.update_votes()
            await asyncio.sleep(2)  # Update every 2 seconds

    async def update_votes(self):
        data = load_data()
        votes = data.get("votes", {})
        a_count = len([uid for uid, vote in votes.items() if vote == "A"])
        b_count = len([uid for uid, vote in votes.items() if vote == "B"])

        a_names = {uid: name for uid, vote in votes.items() if vote == "A" for name in [vote["name"]]} if votes else {}
        b_names = {uid: name for uid, vote in votes.items() if vote == "B" for name in [vote["name"]]} if votes else {}

        desc = f"{VOTE_A} {self.a_name} — {a_count} votes\n"
        desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
        desc += f"\n\n{VOTE_B} {self.b_name} — {b_count} votes\n"
        desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

        embed = discord.Embed(
            title=f"🎮 {data.get('round_stage','Matchup')}",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*", icon_url=None)

        try:
            await self.msg.edit(embed=embed, view=self)
        except Exception:
            pass
            async def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):
    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        data = load_data()
        if not data["current_matchup"]:
            await interaction.response.send_message("No matchups found.", ephemeral=True)
            return
        matchup = data["current_matchup"][0]
        data["round_stage"] = "Round 1"
        save_data(data)

        msg = await interaction.channel.send(
            embed=discord.Embed(
                title=f"🎮 {data['round_stage']}",
                description=f"{VOTE_A} {matchup[0]} vs {VOTE_B} {matchup[1]}",
                color=discord.Color.random()
            ),
            view=VoteView(matchup[0], matchup[1], None)
        )
        # Assign the msg to view
        msg.view.msg = msg
        await interaction.response.send_message("First matchup started!", ephemeral=True)

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Go to next round and announce winner")
    async def nextwcround(interaction: discord.Interaction):
        data = load_data()
        if not data["current_matchup"]:
            await interaction.response.send_message("No current matchup.", ephemeral=True)
            return
        matchup = data["current_matchup"].pop(0)
        votes = data.get("votes", {})
        a_votes = len([v for v in votes.values() if v == "A"])
        b_votes = len([v for v in votes.values() if v == "B"])
        winner = matchup[0] if a_votes >= b_votes else matchup[1]
        await interaction.channel.send(f"🏆 The winner is **{winner}**! @everyone")
        save_data(data)
        # ------------------- /addwcitem -------------------
@tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
@app_commands.describe(items="Comma-separated list of items to add")
async def addwcitem(interaction: discord.Interaction, items: str):
    if not any(role.id in allowed_role_ids for role in interaction.user.roles):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return

    data = load_data()
    new_items = [item.strip() for item in items.split(",") if item.strip()]
    data["items"].extend(new_items)
    save_data(data)
    await interaction.response.send_message(f"✅ Added {len(new_items)} item(s)!", ephemeral=True)

# ------------------- /listwcitems with pagination -------------------
class ItemListView(View):
    def __init__(self, items):
        super().__init__(timeout=None)
        self.items = items
        self.index = 0
        self.max_per_page = 25
        self.embed = self.create_embed()

        self.prev_btn = Button(label="⬅️", style=discord.ButtonStyle.secondary)
        self.next_btn = Button(label="➡️", style=discord.ButtonStyle.secondary)
        self.prev_btn.callback = self.prev_page
        self.next_btn.callback = self.next_page
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)

    def create_embed(self):
        start = self.index * self.max_per_page
        end = start + self.max_per_page
        page_items = self.items[start:end]
        desc = "\n".join([f"{i+1+start}. {item}" for i, item in enumerate(page_items)]) or "_No items yet_"
        embed = discord.Embed(title="📋 World Cup Items", description=desc, color=discord.Color.teal())
        embed.set_footer(text=f"Page {self.index+1}/{(len(self.items)-1)//self.max_per_page +1}")
        return embed

    async def prev_page(self, interaction: discord.Interaction):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        if (self.index+1)*self.max_per_page < len(self.items):
            self.index += 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data = load_data()
    if not data["items"]:
        await interaction.response.send_message("_No items added yet._", ephemeral=True)
        return
    view = ItemListView(data["items"])
    await interaction.response.send_message(embed=view.embed, view=view, ephemeral=False)

# ------------------- /resetwc -------------------
@tree.command(name="resetwc", description="Reset the World Cup data")
async def resetwc(interaction: discord.Interaction):
    if not any(role.id in allowed_role_ids for role in interaction.user.roles):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    data = {
        "current_matchup": [],
        "votes": {},
        "items": [],
        "round_stage": ""
    }
    save_data(data)
    await interaction.response.send_message("✅ World Cup data reset!", ephemeral=True)

# ------------------- /help -------------------
@tree.command(name="help", description="Show all tournament commands")
async def help(interaction: discord.Interaction):
    commands_list = [
        "/startwc — start the World Cup",
        "/nextwcround — announce winner and next matchup",
        "/addwcitem — add items to the World Cup",
        "/listwcitems — view items (paginated)",
        "/resetwc — reset all WC data",
        "/help — show this message"
    ]
    desc = "\n".join(commands_list)
    await interaction.response.send_message(f"📌 Tournament Commands:\n{desc}", ephemeral=True)

# ------------------- Utility functions -------------------
import json
import os

DATA_FILE = "tournament_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"current_matchup": [], "votes": {}, "items": [], "round_stage": ""}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)
