# tournament.py — Part 1/3
import discord
from discord.ext import tasks
from discord import app_commands
import json
import asyncio
import os

DATA_FILE = "tournament_data.json"

# Emoji constants
VOTE_A = "🔴"
VOTE_B = "🔵"

def load_data():
    if not os.path.exists(DATA_FILE):
        data = {
            "items": [],
            "current_matchup": {},
            "votes": {},
            "round_stage": "Round 1"
        }
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
    else:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    return data, True

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def user_allowed(user, allowed_role_ids):
    return any(r.id in allowed_role_ids for r in user.roles)

def setup_tournament_commands(tree: app_commands.CommandTree, allowed_role_ids):

    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("❌ No items added yet.", ephemeral=True)
            return

        # Initialize matchup
        data["current_matchup"] = {
            "a": data["items"][0],
            "b": data["items"][1],
            "a_names": {},
            "b_names": {}
        }
        data["round_stage"] = "Round 1"
        save_data(data)

        desc = f"{VOTE_A} {data['current_matchup']['a']} — 0 votes\n{VOTE_B} {data['current_matchup']['b']} — 0 votes"
        embed = discord.Embed(
            title=f"🎮 {data['round_stage']}",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="use /showwcmatchups to keep track of the World Cup!", icon_url=None)

        msg = await interaction.response.send_message(embed=embed)
        # tournament.py — Part 2/3

        msg = await interaction.original_response()

        async def update_votes_loop():
            while True:
                data, _ = load_data()
                matchup = data.get("current_matchup", {})
                if not matchup:
                    break

                a = matchup.get("a")
                b = matchup.get("b")
                a_names = matchup.get("a_names", {})
                b_names = matchup.get("b_names", {})

                a_count = len(a_names)
                b_count = len(b_names)

                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

                embed = discord.Embed(
                    title=f"🎮 {data.get('round_stage','Matchup')}",
                    description=desc,
                    color=discord.Color.random()
                )
                embed.set_footer(text="use /showwcmatchups to keep track of the World Cup!", icon_url=None)

                try:
                    await msg.edit(embed=embed)
                except Exception:
                    pass

                await asyncio.sleep(2)  # Refresh every 2 seconds

        asyncio.create_task(update_votes_loop())

    # ------------------- Voting Buttons -------------------
    class VoteView(discord.ui.View):
        def __init__(self, msg_id):
            super().__init__(timeout=None)
            self.msg_id = msg_id

        @discord.ui.button(label="Red", style=discord.ButtonStyle.danger)
        async def vote_red(self, interaction: discord.Interaction, button: discord.ui.Button):
            data, _ = load_data()
            matchup = data.get("current_matchup", {})
            uid = str(interaction.user.id)
            a_names = matchup.get("a_names", {})
            b_names = matchup.get("b_names", {})

            # Remove from B if present
            b_names.pop(uid, None)
            # Add/Update A
            a_names[uid] = interaction.user.display_name

            matchup["a_names"] = a_names
            matchup["b_names"] = b_names
            data["current_matchup"] = matchup
            save_data(data)
            await interaction.response.defer()

        @discord.ui.button(label="Blue", style=discord.ButtonStyle.primary)
        async def vote_blue(self, interaction: discord.Interaction, button: discord.ui.Button):
            data, _ = load_data()
            matchup = data.get("current_matchup", {})
            uid = str(interaction.user.id)
            a_names = matchup.get("a_names", {})
            b_names = matchup.get("b_names", {})

            # Remove from A if present
            a_names.pop(uid, None)
            # Add/Update B
            b_names[uid] = interaction.user.display_name

            matchup["a_names"] = a_names
            matchup["b_names"] = b_names
            data["current_matchup"] = matchup
            save_data(data)
            await interaction.response.defer()

    # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Move to the next World Cup matchup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, _ = load_data()
        items = data.get("items", [])
        matchup = data.get("current_matchup", {})

        # Simple example: just rotate next two items
        if not items or len(items) < 2:
            await interaction.response.send_message("Not enough items for next matchup.", ephemeral=True)
            return

        # Move first two items to next matchup
        items.append(items.pop(0))
        items.append(items.pop(0))

        data["current_matchup"] = {
            "a": items[0],
            "b": items[1],
            "a_names": {},
            "b_names": {}
        }
        data["items"] = items
        save_data(data)

        desc = f"{VOTE_A} {items[0]} — 0 votes\n{VOTE_B} {items[1]} — 0 votes"
        embed = discord.Embed(
            title=f"🎮 Next Round",
            description=desc,
            color=discord.Color.random()
        )
        embed.set_footer(text="use /showwcmatchups to keep track of the World Cup!", icon_url=None)

        await interaction.response.send_message(embed=embed, view=VoteView(interaction.id))
        # tournament.py — Part 3/3

import json
import asyncio

DATA_FILE = "tournament_data.json"
VOTE_A = "🔴"
VOTE_B = "🔵"

# ------------------- Helpers -------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"items": [], "current_matchup": {}, "round_stage": ""}, False
    with open(DATA_FILE, "r") as f:
        return json.load(f), True

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def user_allowed(user, allowed_role_ids):
    return any(role.id in allowed_role_ids for role in user.roles)

# ------------------- /addwcitem -------------------
@tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
@app_commands.describe(items="Comma-separated list of items to add")
async def addwcitem(interaction: discord.Interaction, items: str):
    if not user_allowed(interaction.user, allowed_role_ids):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return

    data, _ = load_data()
    new_items = [i.strip() for i in items.split(",") if i.strip()]
    data.setdefault("items", []).extend(new_items)
    save_data(data)
    await interaction.response.send_message(f"✅ Added {len(new_items)} item(s).", ephemeral=True)

# ------------------- /listwcitems with pagination -------------------
class ItemListView(discord.ui.View):
    def __init__(self, items, per_page=10):
        super().__init__(timeout=None)
        self.items = items
        self.per_page = per_page
        self.current_page = 0

    def get_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.items[start:end]
        desc = "\n".join(f"{i+1}. {item}" for i, item in enumerate(page_items, start=start))
        embed = discord.Embed(title="📋 World Cup Items", description=desc, color=discord.Color.teal())
        embed.set_footer(text=f"Page {self.current_page+1}/{(len(self.items)-1)//self.per_page +1}")
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.current_page+1)*self.per_page < len(self.items):
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    items = data.get("items", [])
    if not items:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return
    await interaction.response.send_message(embed=ItemListView(items).get_embed(), view=ItemListView(items))

# ------------------- /resetwc -------------------
@tree.command(name="resetwc", description="Reset all World Cup data")
async def resetwc(interaction: discord.Interaction):
    if not user_allowed(interaction.user, allowed_role_ids):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    save_data({"items": [], "current_matchup": {}, "round_stage": ""})
    await interaction.response.send_message("✅ World Cup has been reset.", ephemeral=True)

# ------------------- /helpwc -------------------
@tree.command(name="helpwc", description="Show help for World Cup commands")
async def helpwc(interaction: discord.Interaction):
    desc = (
        "**World Cup Commands**\n"
        "/startwc — Start the World Cup\n"
        "/nextwcround — Move to next matchup\n"
        "/addwcitem — Add items (comma-separated)\n"
        "/listwcitems — Show all items (paginated)\n"
        "/resetwc — Reset all data\n"
        "/helpwc — Show this help"
    )
    embed = discord.Embed(title="🎮 World Cup Help", description=desc, color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)