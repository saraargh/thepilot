    # ------------------- /addwcitem -------------------
    @tree.command(name="addwcitem", description="Add item(s) to the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to add")
    async def addwcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        items_in = [x.strip() for x in items.split(",") if x.strip()]
        added = []
        for it in items_in:
            if it not in data["items"]:
                data["items"].append(it)
                data["scores"].setdefault(it, 0)
                added.append(it)
        sha = save_data(data, sha)
        if added:
            await interaction.response.send_message(f"✅ Added {len(added)} item(s): {', '.join(added)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No new items added (duplicates ignored).", ephemeral=False)

    # ------------------- /removewcitem -------------------
    @tree.command(name="removewcitem", description="Remove item(s) from the World Cup (comma-separated)")
    @app_commands.describe(items="Comma-separated list of items to remove")
    async def removewcitem(interaction: discord.Interaction, items: str):
        if not user_allowed(interaction.user, allowed_role_ids):
            await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)
            return
        data, sha = load_data()
        items_out = [x.strip() for x in items.split(",") if x.strip()]
        removed = []
        for it in items_out:
            if it in data["items"]:
                data["items"].remove(it)
                data["scores"].pop(it, None)
                removed.append(it)
        sha = save_data(data, sha)
        if removed:
            await interaction.response.send_message(f"✅ Removed {len(removed)} item(s): {', '.join(removed)}", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No items removed.", ephemeral=False)

    # ------------------- /listwcitems with pagination -------------------
    @tree.command(name="listwcitems", description="List all items in the World Cup")
    async def listwcitems(interaction: discord.Interaction):
        data, _ = load_data()
        if not data["items"]:
            await interaction.response.send_message("No items added yet.", ephemeral=True)
            return

        ITEMS_PER_PAGE = 25
        pages = [data["items"][i:i+ITEMS_PER_PAGE] for i in range(0, len(data["items"]), ITEMS_PER_PAGE)]
        current_page = 0

        def create_embed(page_idx):
            embed = discord.Embed(title=f"📋 World Cup Items (Page {page_idx+1}/{len(pages)})", color=discord.Color.teal())
            for i, item in enumerate(pages[page_idx], start=page_idx*ITEMS_PER_PAGE+1):
                embed.add_field(name=f"{i}.", value=item, inline=False)
            return embed

        msg = await interaction.response.send_message(embed=create_embed(current_page), ephemeral=False)
        msg = await interaction.original_response()

        if len(pages) <= 1:
            return  # No need for buttons

        from discord.ui import View, Button

        class PaginationView(View):
            def __init__(self):
                super().__init__()
                self.page = 0

            @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
            async def prev(self, interaction2, button):
                self.page = (self.page - 1) % len(pages)
                await interaction2.response.edit_message(embed=create_embed(self.page), view=self)

            @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
            async def next(self, interaction2, button):
                self.page = (self.page + 1) % len(pages)
                await interaction2.response.edit_message(embed=create_embed(self.page), view=self)

        await msg.edit(view=PaginationView())

    # ------------------- /showwcmatchups -------------------
    async def showwcmatchups_internal(channel, data):
        finished = data.get("finished_matches", [])
        lines_finished = [f"{i+1}. {f['a']} vs {f['b']} → {f['winner']} ({VOTE_A} {f['a_votes']} | {VOTE_B} {f['b_votes']})"
                          for i, f in enumerate(finished)]
        last = data.get("last_match")
        current_pair = f"{last['a']} vs {last['b']} (voting now)" if last else None
        upcoming_pairs = []
        cr = data.get("current_round", []).copy()
        for i in range(0, len(cr), 2):
            if i + 1 < len(cr):
                upcoming_pairs.append(f"{cr[i]} vs {cr[i+1]}")
            else:
                upcoming_pairs.append(f"{cr[i]} (auto-advance if odd)")
        embed = discord.Embed(title="📋 World Cup Matchup Overview", color=discord.Color.teal())
        embed.add_field(name="Tournament", value=data.get("title") or "No title", inline=False)
        embed.add_field(name="Round Stage", value=data.get("round_stage") or "N/A", inline=False)
        embed.add_field(name="Finished Matches", value="\n".join(lines_finished) if lines_finished else "None", inline=False)
        embed.add_field(name="Current Match (voting)", value=current_pair or "None", inline=False)
        embed.add_field(name="Upcoming Matchups", value="\n".join(upcoming_pairs) if upcoming_pairs else "None", inline=False)
        await channel.send(embed=embed)

    @tree.command(name="showwcmatchups", description="Show finished, current, and upcoming World Cup matchups")
    async def showwcmatchups(interaction: discord.Interaction):
        data, _ = load_data()
        await showwcmatchups_internal(interaction.channel, data)
        await interaction.response.send_message("✅ Matchups displayed.", ephemeral=True)