# tournament.py
import discord
from discord import app_commands
from discord.ui import Button, View
import json
import asyncio
import os

DATA_FILE = "tournament_data.json"
VOTE_A = "🔴"
VOTE_B = "🔵"

# ===== Helper functions =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"items": [], "matches": [], "votes": {}}, None
    with open(DATA_FILE, "r") as f:
        return json.load(f), None

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def user_allowed(user, allowed_role_ids):
    return any(r.id in allowed_role_ids for r in user.roles)

def get_current_match(data):
    if "current_match" not in data:
        return None
    idx = data["current_match"]
    if idx >= len(data.get("matches", [])):
        return None
    return data["matches"][idx]

# ===== Setup function =====
def setup_tournament_commands(tree, allowed_role_ids):
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

    # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])
        if not items:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return

        # Pagination logic
        items_per_page = 10
        pages = [items[i:i+items_per_page] for i in range(0, len(items), items_per_page)]
        current_page = 0

        embed = discord.Embed(
            title=f"📋 World Cup Items (Page {current_page+1}/{len(pages)})",
            description="\n".join([f"{i+1+current_page*items_per_page}. {item}" for i, item in enumerate(pages[current_page])]),
            color=discord.Color.teal()
        )

        view = View()

        class Pagination(Button):
            def __init__(self, label, disabled=False):
                super().__init__(label=label, style=discord.ButtonStyle.primary, disabled=disabled)

            async def callback(self, interaction: discord.Interaction):
                nonlocal current_page, embed
                if self.label == "◀️" and current_page > 0:
                    current_page -= 1
                elif self.label == "▶️" and current_page < len(pages)-1:
                    current_page += 1
                embed.description = "\n".join([f"{i+1+current_page*items_per_page}. {item}" for i, item in enumerate(pages[current_page])])
                embed.title = f"📋 World Cup Items (Page {current_page+1}/{len(pages)})"
                await interaction.response.edit_message(embed=embed, view=view)

        view.add_item(Pagination("◀️", disabled=(current_page==0)))
        view.add_item(Pagination("▶️", disabled=(current_page==len(pages)-1)))

        await interaction.response.send_message(embed=embed, view=view)
            # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, _ = load_data()
        if not data.get("items"):
            await interaction.response.send_message("No items available. Add items first with /addwcitem.", ephemeral=True)
            return

        # Shuffle items and create matches
        import random
        items = data["items"][:]
        random.shuffle(items)
        matches = []
        for i in range(0, len(items)-1, 2):
            matches.append([items[i], items[i+1]])
        data["matches"] = matches
        data["current_match"] = 0
        data["votes"] = {}
        save_data(data)

        await interaction.response.send_message(f"🌎 World Cup started! Use /nextwcround to view the first matchup.", ephemeral=False)

    # ------------------- Voting Logic -------------------
    async def send_match(interaction, match_idx):
        data, _ = load_data()
        match = data["matches"][match_idx]
        a, b = match
        a_names = {}
        b_names = {}

        embed = discord.Embed(
            title=f"🎮 Match {match_idx+1}",
            description=f"{VOTE_A} {a} — 0 votes\n{VOTE_B} {b} — 0 votes",
            color=discord.Color.random()
        )
        embed.set_footer(text="use /showwcmatchups to keep track of the World Cup!")

        view = View()

        class VoteButton(Button):
            def __init__(self, label, vote_type):
                super().__init__(label=label, style=discord.ButtonStyle.secondary)
                self.vote_type = vote_type

            async def callback(self, interaction: discord.Interaction):
                nonlocal a_names, b_names, embed
                uid = str(interaction.user.id)
                if self.vote_type == "A":
                    # Remove from B if exists
                    b_names.pop(uid, None)
                    a_names[uid] = interaction.user.display_name
                elif self.vote_type == "B":
                    # Remove from A if exists
                    a_names.pop(uid, None)
                    b_names[uid] = interaction.user.display_name

                a_count = len(a_names)
                b_count = len(b_names)
                desc = f"{VOTE_A} {a} — {a_count} votes\n"
                desc += "\n".join(a_names.values()) or "_No votes yet_"
                desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
                desc += "\n".join(b_names.values()) or "_No votes yet_"
                embed.description = desc
                await interaction.response.edit_message(embed=embed, view=view)

        view.add_item(VoteButton(VOTE_A, "A"))
        view.add_item(VoteButton(VOTE_B, "B"))

        await interaction.response.send_message(embed=embed, view=view)
            # ------------------- /nextwcround -------------------
    @tree.command(name="nextwcround", description="Move to the next World Cup matchup")
    async def nextwcround(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, _ = load_data()
        current = data.get("current_match", 0)
        if current >= len(data.get("matches", [])):
            await interaction.response.send_message("🏆 The World Cup has ended!", ephemeral=False)
            return

        await send_match(interaction, current)
        data["current_match"] += 1
        save_data(data)

    # ------------------- /resetwc -------------------
    @tree.command(name="resetwc", description="Reset the World Cup")
    async def resetwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data = {
            "items": [],
            "matches": [],
            "current_match": 0,
            "votes": {}
        }
        save_data(data)
        await interaction.response.send_message("⚠️ World Cup data reset.", ephemeral=False)

    # ------------------- /showwcmatchups -------------------
    @tree.command(name="showwcmatchups", description="Show current World Cup matchups")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        embed = discord.Embed(title="📊 Current World Cup Matchups", color=discord.Color.green())
        matches = data.get("matches", [])
        for idx, m in enumerate(matches, start=1):
            a, b = m
            embed.add_field(name=f"{idx}.", value=f"{a} vs {b}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)

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
        await interaction.response.send_message(f"✅ Added {len(new_items)} item(s) to the World Cup.", ephemeral=False)

    # ------------------- /listwcitems -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        items = data.get("items", [])
        if not items:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return

        # Split into pages of 25 items max
        pages = [items[i:i+25] for i in range(0, len(items), 25)]
        current_page = 0

        embed = discord.Embed(
            title=f"📋 World Cup Items (Page {current_page+1}/{len(pages)})",
            description="\n".join([f"{idx+1}. {item}" for idx, item in enumerate(pages[current_page])]),
            color=discord.Color.teal()
        )

        view = View()

        class PageButton(Button):
            def __init__(self, label, style, direction):
                super().__init__(label=label, style=style)
                self.direction = direction

            async def callback(self, interaction: discord.Interaction):
                nonlocal current_page, embed
                if self.direction == "next":
                    current_page = (current_page + 1) % len(pages)
                else:
                    current_page = (current_page - 1) % len(pages)
                embed.description = "\n".join([f"{idx+1}. {item}" for idx, item in enumerate(pages[current_page])])
                embed.title = f"📋 World Cup Items (Page {current_page+1}/{len(pages)})"
                await interaction.response.edit_message(embed=embed, view=view)

        if len(pages) > 1:
            view.add_item(PageButton("⬅️", discord.ButtonStyle.secondary, "prev"))
            view.add_item(PageButton("➡️", discord.ButtonStyle.secondary, "next"))

        await interaction.response.send_message(embed=embed, view=view)

# ==================== Helper Functions ====================
def user_allowed(user, role_ids):
    return any(r.id in role_ids for r in getattr(user, "roles", []))

def load_data():
    import json
    if not os.path.exists("tournament_data.json"):
        return {"items": [], "matches": [], "current_match": 0, "votes": {}}, None
    with open("tournament_data.json", "r") as f:
        return json.load(f), f

def save_data(data):
    import json
    with open("tournament_data.json", "w") as f:
        json.dump(data, f, indent=4)