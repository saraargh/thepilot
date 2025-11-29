# tournament.py
import discord
from discord import app_commands
import asyncio
import json

DATA_FILE = "tournament_data.json"
VOTE_A = "🔴"
VOTE_B = "🔵"
ITEMS_PER_PAGE = 10

# ------------------- Helper functions -------------------
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f), True
    except FileNotFoundError:
        return {"items": [], "current_match": None, "rounds": [], "votes": {}}, False

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def user_allowed(user, allowed_role_ids):
    return any(r.id in allowed_role_ids for r in user.roles)

# ------------------- Setup tournament commands -------------------
def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids: list[int]):

    # ------------------- /wc_help -------------------
    @tree.command(name="wc_help", description="Show World Cup command help")
    async def wc_help(interaction: discord.Interaction):
        help_text = (
            "**World Cup Commands:**\n"
            "/startwc - Start the World Cup\n"
            "/nextwcround - Go to next matchup\n"
            "/vote - Vote for current matchup\n"
            "/addwcitem - Add items to World Cup\n"
            "/listwcitems - List all items\n"
            "/resetwc - Reset World Cup\n"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup data")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data = {"items": [], "current_match": None, "rounds": [], "votes": {}}
        save_data(data)
        await interaction.response.send_message("✅ World Cup data has been reset.", ephemeral=False)
            # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, _ = load_data()
        new_items = [i.strip() for i in items.split(",") if i.strip()]
        data["items"].extend(new_items)
        save_data(data)
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s) to the World Cup.", ephemeral=False)

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        data, _ = load_data()
        if len(data["items"]) < 2:
            await interaction.response.send_message("❌ You need at least 2 items to start.", ephemeral=True)
            return
        # Initialize rounds
        data["rounds"] = [(data["items"][i], data["items"][i+1]) for i in range(0, len(data["items"])-1, 2)]
        data["current_match"] = 0
        data["votes"] = {}
        save_data(data)
        a, b = data["rounds"][data["current_match"]]
        desc = f"{VOTE_A} {a} — 0 votes\n{VOTE_B} {b} — 0 votes"
        embed = discord.Embed(
            title=f"🎮 Matchup 1",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")
        msg = await interaction.response.send_message(embed=embed)
        data["last_msg_id"] = (interaction.channel_id, (await msg.original_response()).id)
        save_data(data)

    # ------------------- Voting logic -------------------
    async def update_vote(message, a, b, a_names, b_names):
        a_count = len(a_names)
        b_count = len(b_names)
        desc = f"{VOTE_A} {a} — {a_count} votes\n"
        desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
        desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
        desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"
        embed = discord.Embed(
            title=f"🎮 Matchup",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")
        await message.edit(embed=embed)

    @tree.command(name="vote", description="Vote for the current matchup")
    @app_commands.describe(choice="Choose red 🔴 or blue 🔵")
    async def vote(interaction: discord.Interaction, choice: str):
        choice = choice.lower()
        data, _ = load_data()
        if "current_match" not in data or data["current_match"] is None:
            await interaction.response.send_message("❌ No active matchup.", ephemeral=True)
            return
        channel_id, msg_id = data.get("last_msg_id", (None, None))
        channel = interaction.guild.get_channel(channel_id)
        msg = await channel.fetch_message(msg_id)

        a, b = data["rounds"][data["current_match"]]
        votes = data.get("votes", {})
        a_names = {uid: name for uid, (vote_choice, name) in votes.items() if vote_choice == "a"}
        b_names = {uid: name for uid, (vote_choice, name) in votes.items() if vote_choice == "b"}

        prev_choice = votes.get(str(interaction.user.id), (None, None))[0]

        # Update vote correctly for both directions
        if choice == "red":
            a_names[str(interaction.user.id)] = interaction.user.display_name
            b_names.pop(str(interaction.user.id), None)
            votes[str(interaction.user.id)] = ("a", interaction.user.display_name)
        elif choice == "blue":
            b_names[str(interaction.user.id)] = interaction.user.display_name
            a_names.pop(str(interaction.user.id), None)
            votes[str(interaction.user.id)] = ("b", interaction.user.display_name)
        else:
            await interaction.response.send_message("❌ Invalid choice, use 'red' or 'blue'.", ephemeral=True)
            return

        data["votes"] = votes
        save_data(data)
        await update_vote(msg, a, b, a_names, b_names)
        await interaction.response.send_message(f"✅ Your vote for {choice} has been recorded.", ephemeral=True)
        from discord.ui import View, Button

# ------------------- /nextwcround -------------------
@tree.command(name="nextwcround", description="Move to the next World Cup matchup")
async def nextwcround(interaction: discord.Interaction):
    data, _ = load_data()
    if "current_match" not in data or data["current_match"] is None:
        await interaction.response.send_message("❌ No active World Cup.", ephemeral=True)
        return

    data["current_match"] += 1
    data["votes"] = {}
    if data["current_match"] >= len(data["rounds"]):
        await interaction.response.send_message("🏆 The World Cup is over!", ephemeral=False)
        data["current_match"] = None
        save_data(data)
        return

    save_data(data)
    a, b = data["rounds"][data["current_match"]]
    desc = f"{VOTE_A} {a} — 0 votes\n{VOTE_B} {b} — 0 votes"
    embed = discord.Embed(title=f"🎮 Matchup {data['current_match']+1}", description=desc, color=discord.Color.random())
    embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")
    msg = await interaction.response.send_message(embed=embed)
    data["last_msg_id"] = (interaction.channel_id, (await msg.original_response()).id)
    save_data(data)

# ------------------- /listwcitems with pagination -------------------
class ItemsPaginator(View):
    def __init__(self, items, per_page=10):
        super().__init__(timeout=None)
        self.items = items
        self.per_page = per_page
        self.current = 0
        self.total_pages = (len(items) - 1) // per_page + 1

        self.prev_btn = Button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
        self.next_btn = Button(label="Next ➡️", style=discord.ButtonStyle.secondary)

        self.prev_btn.callback = self.prev_page
        self.next_btn.callback = self.next_page

        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)

    async def prev_page(self, interaction: discord.Interaction):
        self.current = max(self.current - 1, 0)
        await interaction.response.edit_message(embed=self.get_embed())

    async def next_page(self, interaction: discord.Interaction):
        self.current = min(self.current + 1, self.total_pages - 1)
        await interaction.response.edit_message(embed=self.get_embed())

    def get_embed(self):
        start = self.current * self.per_page
        end = start + self.per_page
        page_items = self.items[start:end]
        desc = "\n".join([f"{i+start+1}. {item}" for i, item in enumerate(page_items)])
        embed = discord.Embed(title=f"📋 World Cup Items (Page {self.current+1}/{self.total_pages})", description=desc, color=discord.Color.teal())
        return embed

@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    if not data["items"]:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return
    paginator = ItemsPaginator(data["items"])
    await interaction.response.send_message(embed=paginator.get_embed(), view=paginator, ephemeral=False)

# ------------------- Helper functions -------------------
def load_data():
    import json
    try:
        with open("tournament_data.json", "r") as f:
            return json.load(f), True
    except FileNotFoundError:
        return {"items": [], "rounds": [], "current_match": None, "votes": {}, "last_msg_id": None}, False

def save_data(data):
    import json
    with open("tournament_data.json", "w") as f:
        json.dump(data, f, indent=2)

def user_allowed(user, allowed_role_ids):
    return any(role.id in allowed_role_ids for role in user.roles)
    