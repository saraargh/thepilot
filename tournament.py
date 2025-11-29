import discord
from discord import app_commands
import json
import asyncio
import os

DATA_FILE = "tournament_data.json"

VOTE_A = "🔴"
VOTE_B = "🔵"

def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"items": [], "current_match": {}, "votes": {}}
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
        return data, False
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
    return data, True

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def user_allowed(user, allowed_role_ids):
    return any(r.id in allowed_role_ids for r in user.roles)

def setup_tournament_commands(tree, allowed_role_ids):
    # ------------------- /startwc -------------------
    @tree.command(name="startwc", description="Start the World Cup")
    async def startwc(interaction: discord.Interaction):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return

        data, _ = load_data()
        if "current_match" not in data or not data["current_match"]:
            # Start first matchup
            if len(data["items"]) < 2:
                await interaction.response.send_message("Not enough items to start the World Cup.", ephemeral=True)
                return
            a, b = data["items"][:2]
            data["current_match"] = {"a": a, "b": b, "a_names": {}, "b_names": {}, "round_stage": "Round 1"}
            save_data(data)
        await interaction.response.send_message(f"Started World Cup! First matchup: {data['current_match']['a']} vs {data['current_match']['b']}", ephemeral=True)
            # ------------------- Voting -------------------
    async def update_votes_loop(msg):
        while True:
            data, _ = load_data()
            match = data.get("current_match")
            if not match:
                return
            a = match["a"]
            b = match["b"]
            a_names = match.get("a_names", {})
            b_names = match.get("b_names", {})
            a_count = len(a_names)
            b_count = len(b_names)

            desc = f"{VOTE_A} {a} — {a_count} votes\n"
            desc += "\n".join([f"• {n}" for n in a_names.values()]) or "_No votes yet_"
            desc += f"\n\n{VOTE_B} {b} — {b_count} votes\n"
            desc += "\n".join([f"• {n}" for n in b_names.values()]) or "_No votes yet_"

            embed = discord.Embed(
                title=f"🎮 {match.get('round_stage','Matchup')}",
                description=desc,
                color=discord.Color.random()
            )
            embed.set_footer(text="*use /showwcmatchups to keep track of the World Cup!*", icon_url=None)

            try:
                await msg.edit(embed=embed)
            except Exception:
                pass
            await asyncio.sleep(1)  # Update every 1 second

    # ------------------- /vote -------------------
    @tree.command(name="vote", description="Vote for an item in the current matchup")
    @app_commands.describe(choice="Choose 🔴 or 🔵")
    async def vote(interaction: discord.Interaction, choice: str):
        data, _ = load_data()
        match = data.get("current_match")
        if not match:
            await interaction.response.send_message("No matchup is active.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        a_names = match.setdefault("a_names", {})
        b_names = match.setdefault("b_names", {})

        # Remove from both sides first
        a_names.pop(uid, None)
        b_names.pop(uid, None)

        # Add to selected vote
        if choice == "🔴":
            a_names[uid] = interaction.user.display_name
        elif choice == "🔵":
            b_names[uid] = interaction.user.display_name
        else:
            await interaction.response.send_message("Invalid choice! Use 🔴 or 🔵.", ephemeral=True)
            return

        match["a_names"] = a_names
        match["b_names"] = b_names
        save_data(data)

        await interaction.response.send_message(f"Your vote for {choice} has been counted!", ephemeral=True)
        # ------------------- /listwcitems -------------------
ITEMS_PER_PAGE = 10

@tree.command(name="listwcitems", description="List all items in the World Cup")
async def listwcitems(interaction: discord.Interaction):
    data, _ = load_data()
    items = data.get("items", [])
    if not items:
        await interaction.response.send_message("No items added yet.", ephemeral=True)
        return

    pages = [items[i:i + ITEMS_PER_PAGE] for i in range(0, len(items), ITEMS_PER_PAGE)]
    current_page = 0

    def create_embed(page_idx):
        page_items = pages[page_idx]
        desc = "\n".join([f"{i + 1 + page_idx*ITEMS_PER_PAGE}. {item}" for i, item in enumerate(page_items)])
        embed = discord.Embed(title=f"📋 World Cup Items (Page {page_idx + 1}/{len(pages)})",
                              description=desc, color=discord.Color.teal())
        return embed

    msg = await interaction.response.send_message(embed=create_embed(current_page), ephemeral=False)
    msg = await interaction.original_response()

    if len(pages) <= 1:
        return  # No need for navigation

    # Add arrow reactions for navigation
    await msg.add_reaction("◀️")
    await msg.add_reaction("▶️")

    def check(reaction, user):
        return user != msg.author and str(reaction.emoji) in ["◀️", "▶️"] and reaction.message.id == msg.id

    while True:
        try:
            reaction, user = await client.wait_for("reaction_add", timeout=120.0, check=check)
        except asyncio.TimeoutError:
            break

        if str(reaction.emoji) == "▶️":
            current_page = (current_page + 1) % len(pages)
        elif str(reaction.emoji) == "◀️":
            current_page = (current_page - 1) % len(pages)

        await msg.edit(embed=create_embed(current_page))
        await msg.remove_reaction(reaction, user)

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
    await interaction.response.send_message(f"✅ Added items: {', '.join(new_items)}", ephemeral=True)

# ------------------- /resetwc -------------------
@tree.command(name="resetwc", description="Reset all World Cup data")
async def resetwc(interaction: discord.Interaction):
    if not user_allowed(interaction.user, allowed_role_ids):
        await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
        return
    data = {"items": [], "current_match": None, "rounds": []}
    save_data(data)
    await interaction.response.send_message("✅ World Cup data has been reset.", ephemeral=True)

# ------------------- Help command -------------------
@tree.command(name="wc_help", description="Show help for World Cup commands")
async def wc_help(interaction: discord.Interaction):
    help_text = (
        "/startwc - Start the World Cup\n"
        "/nextwcround - Move to next matchup\n"
        "/vote - Vote for an item in the current matchup\n"
        "/listwcitems - List all items\n"
        "/addwcitem - Add new items\n"
        "/resetwc - Reset all WC data\n"
        "/showwcmatchups - Show current matchups"
    )
    await interaction.response.send_message(help_text, ephemeral=True)
