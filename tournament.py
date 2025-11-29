import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os

TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID", 0))

client = commands.Bot(command_prefix="/", intents=discord.Intents.all())
tree = client.tree

DATA_FILE = "wc_data.json"

VOTE_A = "🔴"
VOTE_B = "🔵"

# ------------------- Data Load/Save -------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"items": [], "current_match": None, "votes": {}}
        save_data(data)
    else:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    return data, None

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ------------------- Voting logic -------------------
vote_state = {}  # {message_id: {"a": set(user_ids), "b": set(user_ids), "msg": message}}
vote_lock = asyncio.Lock()

async def update_votes_loop():
    while True:
        await asyncio.sleep(2)  # update every 2 seconds
        async with vote_lock:
            for msg_id, vote in vote_state.items():
                a_count = len(vote["a"])
                b_count = len(vote["b"])
                a_names = vote.get("a_names", {})
                b_names = vote.get("b_names", {})
                a = vote["a_label"]
                b = vote["b_label"]
                msg = vote["msg"]

                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                embed = discord.Embed(
                    title=f"🎮 {vote.get('round_stage','Matchup')}",
                    description=desc,
                    color=discord.Color.random()
                )
                embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*")

                try:
                    await msg.edit(embed=embed)
                except Exception:
                    pass
                    # ------------------- Button Views -------------------
class VoteView(discord.ui.View):
    def __init__(self, a_label, b_label, msg, round_stage):
        super().__init__(timeout=None)
        self.a_label = a_label
        self.b_label = b_label
        self.msg = msg
        self.round_stage = round_stage

        vote_state[msg.id] = {
            "a": set(),
            "b": set(),
            "a_names": {},
            "b_names": {},
            "msg": msg,
            "a_label": a_label,
            "b_label": b_label,
            "round_stage": round_stage,
        }

    @discord.ui.button(label="🔴", style=discord.ButtonStyle.danger)
    async def vote_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with vote_lock:
            uid = interaction.user.id
            state = vote_state[self.msg.id]
            if uid in state["b"]:
                state["b"].remove(uid)
                state["b_names"].pop(str(uid), None)
            state["a"].add(uid)
            state["a_names"][str(uid)] = interaction.user.display_name
        await interaction.response.defer()

    @discord.ui.button(label="🔵", style=discord.ButtonStyle.primary)
    async def vote_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with vote_lock:
            uid = interaction.user.id
            state = vote_state[self.msg.id]
            if uid in state["a"]:
                state["a"].remove(uid)
                state["a_names"].pop(str(uid), None)
            state["b"].add(uid)
            state["b_names"][str(uid)] = interaction.user.display_name
        await interaction.response.defer()


# ------------------- /startwc -------------------
@tree.command(name="startwc", description="Start the World Cup")
async def startwc(interaction: discord.Interaction):
    data, _ = load_data()
    if not data["items"]:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return

    # First matchup
    a = data["items"][0]
    b = data["items"][1] if len(data["items"]) > 1 else "TBD"
    embed = discord.Embed(
        title="🎮 Matchup 1",
        description=f"{VOTE_A} {a}\n\n{VOTE_B} {b}",
        color=discord.Color.random()
    )
    msg = await interaction.channel.send(embed=embed, view=VoteView(a, b, None, "Round 1"))
    vote_state[msg.id]["msg"] = msg
    await interaction.response.send_message("World Cup started!", ephemeral=True)


# ------------------- /nextwcround -------------------
@tree.command(name="nextwcround", description="Advance to the next World Cup matchup")
async def nextwcround(interaction: discord.Interaction):
    data, _ = load_data()
    # Determine winner from current matchup
    for vs in vote_state.values():
        a_votes = len(vs["a"])
        b_votes = len(vs["b"])
        winner = vs["a_label"] if a_votes >= b_votes else vs["b_label"]
        await interaction.channel.send(f"🏆 {winner} wins this round! @everyone")
        break
    # Logic to post next matchup goes here (simplified)
    await interaction.response.send_message("Next matchup posted.", ephemeral=True)


# ------------------- /addwcitem -------------------
@tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
@app_commands.describe(items="Comma-separated list of items to add")
async def addwcitem(interaction: discord.Interaction, items: str):
    data, _ = load_data()
    new_items = [i.strip() for i in items.split(",") if i.strip()]
    data["items"].extend(new_items)
    save_data(data)
    await interaction.response.send_message(f"Added {len(new_items)} item(s).", ephemeral=True)


# ------------------- /resetwc -------------------
@tree.command(name="resetwc", description="Reset the World Cup")
async def resetwc(interaction: discord.Interaction):
    data = {"items": [], "current_match": None, "votes": {}}
    save_data(data)
    vote_state.clear()
    await interaction.response.send_message("World Cup reset.", ephemeral=True)
    # ------------------- /listwcitems (paginated) -------------------
class ListItemsView(discord.ui.View):
    def __init__(self, items):
        super().__init__(timeout=None)
        self.items = items
        self.page = 0
        self.max_per_page = 10
        self.message = None

    def get_page_text(self):
        start = self.page * self.max_per_page
        end = start + self.max_per_page
        page_items = self.items[start:end]
        text = "\n".join([f"{i+start+1}. {item}" for i, item in enumerate(page_items)])
        return text or "_No items_"

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await self.message.edit(content=self.get_page_text(), view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * self.max_per_page < len(self.items):
            self.page += 1
            await self.message.edit(content=self.get_page_text(), view=self)


@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    if not data["items"]:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return

    view = ListItemsView(data["items"])
    text = view.get_page_text()
    msg = await interaction.response.send_message(content=text, view=view, ephemeral=False)
    view.message = await interaction.original_response()


# ------------------- Help command -------------------
@tree.command(name="helpwc", description="Show World Cup commands help")
async def helpwc(interaction: discord.Interaction):
    text = (
        "📋 **World Cup Commands:**\n"
        "/startwc - Start the World Cup\n"
        "/nextwcround - Go to next matchup\n"
        "/addwcitem <items> - Add item(s) to the World Cup\n"
        "/listwcitems - List all items (paginated)\n"
        "/resetwc - Reset the World Cup\n"
        "/helpwc - Show this help message"
    )
    await interaction.response.send_message(text, ephemeral=True)


# ------------------- Data utils -------------------
def load_data():
    if os.path.exists("wc_data.json"):
        with open("wc_data.json", "r") as f:
            return json.load(f), True
    return {"items": [], "current_match": None, "votes": {}}, False


def save_data(data):
    with open("wc_data.json", "w") as f:
        json.dump(data, f, indent=4)


# ------------------- Global vote state -------------------
vote_state = {}
vote_lock = asyncio.Lock()
VOTE_A = "🔴"
VOTE_B = "🔵"