from __future__ import annotations

import json
import os
from typing import Dict, Any, List, Optional

import discord
from discord import app_commands

from permissions import has_global_access

CONFIG_FILE = "selfroles.json"

# =========================================================
# CONFIG IO
# =========================================================

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError("selfroles.json missing")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def ensure_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("selfroles_channel_id", None)
    cfg.setdefault("selfroles_message_id", None)

    cfg.setdefault("logging", {})
    cfg["logging"].setdefault("enabled", False)
    cfg["logging"].setdefault("channel_id", None)

    cfg.setdefault("auto_roles", {})
    cfg["auto_roles"].setdefault("humans", [])
    cfg["auto_roles"].setdefault("bots", [])

    cfg.setdefault("categories", {})
    return cfg

# =========================================================
# HELPERS
# =========================================================

def guild_me(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id)

def parse_emoji(raw: Optional[str]):
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return None

def role_manageable(role: discord.Role, me: discord.Member) -> bool:
    if role.is_default():
        return False
    if role.managed:
        return False
    if role.permissions.administrator:
        return False
    if role >= me.top_role:
        return False
    return True

# =========================================================
# AUTO ROLES
# =========================================================

async def apply_auto_roles(member: discord.Member):
    cfg = ensure_shape(load_config())
    auto = cfg.get("auto_roles", {})
    role_ids = auto.get("bots" if member.bot else "humans", [])

    me = guild_me(member.guild)
    if not me:
        return

    for rid in role_ids:
        role = member.guild.get_role(int(rid))
        if not role:
            continue
        if role in member.roles:
            continue
        if not role_manageable(role, me):
            continue
        try:
            await member.add_roles(role, reason="Auto role")
        except Exception:
            pass

# =========================================================
# PUBLIC SELF-ROLES (CATEGORY + ROLE LIST — NO BUTTONS)
# =========================================================

def public_embed() -> discord.Embed:
    return discord.Embed(
        title="✨ Choose Your Roles",
        description=(
            "Select a category, then pick your roles.\n"
            "You can change these any time ✈️"
        ),
        color=discord.Color.blurple(),
    )

def role_embed(cat: dict) -> discord.Embed:
    return discord.Embed(
        title=cat.get("title", "Roles"),
        description="Select your roles from the list below.",
        color=discord.Color.blurple(),
    )

class CategorySelect(discord.ui.Select):
    def __init__(self, selected: Optional[str] = None):
        cfg = ensure_shape(load_config())
        categories = cfg.get("categories", {}) or {}

        options: List[discord.SelectOption] = []
        for key, cat in categories.items():
            options.append(
                discord.SelectOption(
                    label=(cat.get("title") or key)[:100],
                    value=key,
                    emoji=parse_emoji(cat.get("emoji")),
                    default=(key == selected),
                )
            )

        super().__init__(
            placeholder="Select a category…",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        cfg = ensure_shape(load_config())
        cat = cfg.get("categories", {}).get(key)

        if not cat:
            return await interaction.response.send_message(
                "❌ Category no longer exists.",
                ephemeral=True,
            )

        view = PublicSelfRolesView(active_category=key)
        await interaction.response.edit_message(
            embed=role_embed(cat),
            view=view,
        )

class RoleSelect(discord.ui.Select):
    def __init__(self, category_key: str, category: dict):
        self.category_key = category_key

        options: List[discord.SelectOption] = []
        for rid, meta in category.get("roles", {}).items():
            options.append(
                discord.SelectOption(
                    label=(meta.get("label") or "Role")[:100],
                    value=str(rid),
                    emoji=parse_emoji(meta.get("emoji")),
                )
            )

        multi = bool(category.get("multi_select", True))

        super().__init__(
            placeholder="Select your roles…",
            min_values=0,
            max_values=len(options) if multi else 1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        cfg = ensure_shape(load_config())
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return

        me = guild_me(interaction.guild)
        if not me:
            return

        valid_ids = {int(r) for r in cat.get("roles", {}).keys()}
        selected = {int(v) for v in self.values}

        added, removed = [], []

        for rid in valid_ids:
            role = interaction.guild.get_role(rid)
            if not role or not role_manageable(role, me):
                continue

            if rid in selected and role not in member.roles:
                await member.add_roles(role, reason="Self-role")
                added.append(role)
            elif rid not in selected and role in member.roles:
                await member.remove_roles(role, reason="Self-role")
                removed.append(role)

        lines = ["✨ **Your roles have been updated**"]
        if added:
            lines.append("✅ Added: " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ Removed: " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

class PublicSelfRolesView(discord.ui.View):
    def __init__(self, active_category: Optional[str] = None):
        super().__init__(timeout=None)

        cfg = ensure_shape(load_config())
        categories = cfg.get("categories", {}) or {}

        # Category selector ALWAYS visible
        self.add_item(CategorySelect(selected=active_category))

        # Role selector ONLY if a category is active
        if active_category and active_category in categories:
            cat = categories[active_category]
            if cat.get("roles"):
                self.add_item(RoleSelect(active_category, cat))

# =========================================================
# ADMIN PANELS + DEPLOY/UPDATE MENU + EDITORS + LOGGING
# =========================================================

def save_config_safe(cfg: Dict[str, Any]) -> None:
    save_config(ensure_shape(cfg))

async def send_log(guild: discord.Guild, embed: discord.Embed):
    cfg = ensure_shape(load_config())
    lg = cfg.get("logging") or {}
    if not lg.get("enabled"):
        return
    cid = lg.get("channel_id")
    if not cid:
        return
    ch = guild.get_channel(int(cid))
    if isinstance(ch, discord.TextChannel):
        try:
            await ch.send(embed=embed)
        except Exception:
            pass

# =========================================================
# DEPLOY / UPDATE PUBLIC MENU MESSAGE
# =========================================================

async def deploy_or_update_menu(guild: discord.Guild) -> str:
    cfg = ensure_shape(load_config())

    cid = cfg.get("selfroles_channel_id")
    if not cid:
        return "❌ Self-roles channel not set."

    ch = guild.get_channel(int(cid))
    if not isinstance(ch, discord.TextChannel):
        return "❌ Configured self-roles channel is missing or not a text channel."

    # Persistent list-based view (NO buttons)
    em = public_embed()
    view = PublicSelfRolesView(active_category=None)

    mid = cfg.get("selfroles_message_id")
    if mid:
        try:
            msg = await ch.fetch_message(int(mid))
            await msg.edit(embed=em, view=view)
            return "✅ Updated existing self-role menu."
        except Exception:
            pass

    sent = await ch.send(embed=em, view=view)
    cfg["selfroles_message_id"] = sent.id
    save_config_safe(cfg)
    return "✅ Posted a new self-role menu."

# =========================================================
# ADMIN: SET CHANNEL PICKERS (USES SELECT VALUES PROPERLY)
# =========================================================

class SetSelfRolesChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

        self.sel = discord.ui.ChannelSelect(
            placeholder="Select the self-roles channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.sel.callback = self.pick  # type: ignore
        self.add_item(self.sel)

    async def pick(self, interaction: discord.Interaction):
        channel: discord.abc.GuildChannel = self.sel.values[0]
        cfg = ensure_shape(load_config())
        cfg["selfroles_channel_id"] = channel.id
        save_config_safe(cfg)
        await interaction.response.send_message(f"📍 Self-roles channel set to {channel.mention}", ephemeral=True)

class SetLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

        self.sel = discord.ui.ChannelSelect(
            placeholder="Select the log channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.sel.callback = self.pick  # type: ignore
        self.add_item(self.sel)

    async def pick(self, interaction: discord.Interaction):
        channel: discord.abc.GuildChannel = self.sel.values[0]
        cfg = ensure_shape(load_config())
        cfg["logging"]["channel_id"] = channel.id
        save_config_safe(cfg)
        await interaction.response.send_message(f"🧾 Log channel set to {channel.mention}", ephemeral=True)

# =========================================================
# ADMIN: CATEGORY MODAL (custom emoji supported via emoji field)
# =========================================================

class CategoryModal(discord.ui.Modal, title="Category Settings"):
    def __init__(self, mode: str, existing_key: Optional[str] = None, existing: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.mode = mode
        self.existing_key = existing_key
        existing = existing or {}

        self.key_in = discord.ui.TextInput(
            label="Category key (unique, no spaces) e.g. colours",
            required=True,
            max_length=50,
            default=existing_key or "",
        )
        self.title_in = discord.ui.TextInput(
            label="Title (shows to users) e.g. Colour Roles",
            required=True,
            max_length=150,
            default=str(existing.get("title") or ""),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Category emoji (optional) unicode or <:name:id>",
            required=False,
            max_length=80,
            default=str(existing.get("emoji") or ""),
        )
        self.multi_in = discord.ui.TextInput(
            label="Multi-select? (yes/no)",
            required=True,
            max_length=5,
            default=("yes" if existing.get("multi_select", True) else "no"),
        )

        self.add_item(self.key_in)
        self.add_item(self.title_in)
        self.add_item(self.emoji_in)
        self.add_item(self.multi_in)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = ensure_shape(load_config())
        cats = cfg.get("categories") or {}

        key = self.key_in.value.strip().lower().replace(" ", "_")
        if not key:
            return await interaction.response.send_message("❌ Category key required.", ephemeral=True)

        emoji_raw = self.emoji_in.value.strip()
        if emoji_raw and not parse_emoji(emoji_raw):
            return await interaction.response.send_message("❌ Emoji format invalid.", ephemeral=True)

        multi_raw = self.multi_in.value.strip().lower()
        multi = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if key in cats:
                return await interaction.response.send_message("❌ That category key already exists.", ephemeral=True)
            cats[key] = {"title": self.title_in.value.strip(), "emoji": emoji_raw or None, "multi_select": multi, "roles": {}}
        else:
            if not self.existing_key or self.existing_key not in cats:
                return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

            if key != self.existing_key:
                if key in cats:
                    return await interaction.response.send_message("❌ New key already exists.", ephemeral=True)
                cats[key] = cats.pop(self.existing_key)

            cats[key].setdefault("roles", {})
            cats[key]["title"] = self.title_in.value.strip()
            cats[key]["emoji"] = emoji_raw or None
            cats[key]["multi_select"] = multi

        cfg["categories"] = cats
        save_config_safe(cfg)
        await interaction.response.send_message("✅ Category saved.", ephemeral=True)

# =========================================================
# ADMIN: CATEGORY PICKER
# =========================================================

def category_options(cfg: Dict[str, Any]) -> List[discord.SelectOption]:
    cats = (cfg.get("categories") or {})
    if not cats:
        return [discord.SelectOption(label="(No categories)", value="__none__", default=True)]
    opts = []
    for k, v in list(cats.items())[:25]:
        opts.append(discord.SelectOption(
            label=(v.get("title") or k)[:100],
            value=k,
            emoji=parse_emoji(v.get("emoji")),
        ))
    return opts

class CategoryPicker(discord.ui.Select):
    def __init__(self, placeholder: str):
        cfg = ensure_shape(load_config())
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=category_options(cfg))

# =========================================================
# ADMIN: CATEGORY MANAGER
# =========================================================

class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected: Optional[str] = None

        self.sel = CategoryPicker("Select category to edit/delete…")
        self.sel.callback = self.on_pick  # type: ignore
        self.add_item(self.sel)

    async def on_pick(self, interaction: discord.Interaction):
        v = self.sel.values[0]
        if v == "__none__":
            self.selected = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.selected = v
        await interaction.response.send_message(f"✅ Selected `{v}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Category", style=discord.ButtonStyle.success)
    async def add_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(CategoryModal("add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = ensure_shape(load_config())
        cat = (cfg.get("categories") or {}).get(self.selected)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)
        await interaction.response.send_modal(CategoryModal("edit", existing_key=self.selected, existing=cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = ensure_shape(load_config())
        cats = cfg.get("categories") or {}
        if self.selected in cats:
            del cats[self.selected]
            cfg["categories"] = cats
            save_config_safe(cfg)
            self.selected = None
            return await interaction.response.send_message("✅ Category deleted.", ephemeral=True)
        await interaction.response.send_message("❌ Category missing.", ephemeral=True)

# =========================================================
# ADMIN: ROLES IN CATEGORIES (multi-add up to 25)
# - IMPORTANT: Discord UI limits are 25 per select. That's the max.
# =========================================================

class RoleMetaModal(discord.ui.Modal, title="Role Display (Optional Override)"):
    def __init__(self, category_key: str, role_id: int, existing: Dict[str, Any]):
        super().__init__()
        self.category_key = category_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label (users see this) — you CAN include <:custom:123>",
            required=True,
            max_length=100,
            default=str(existing.get("label") or "Role"),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji override (optional) unicode or <:name:id>",
            required=False,
            max_length=80,
            default=str(existing.get("emoji") or ""),
        )
        self.add_item(self.label_in)
        self.add_item(self.emoji_in)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = ensure_shape(load_config())
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles = cat.get("roles") or {}
        rid = str(self.role_id)
        if rid not in roles:
            return await interaction.response.send_message("❌ Role not found in category.", ephemeral=True)

        emoji_raw = self.emoji_in.value.strip()
        if emoji_raw and not parse_emoji(emoji_raw):
            return await interaction.response.send_message("❌ Emoji format invalid.", ephemeral=True)

        roles[rid]["label"] = self.label_in.value.strip()
        roles[rid]["emoji"] = emoji_raw or None
        cat["roles"] = roles
        save_config_safe(cfg)
        await interaction.response.send_message("✅ Updated role display.", ephemeral=True)

class RolesCategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        self.cat_sel = CategoryPicker("Select category to manage roles…")
        self.cat_sel.callback = self.pick_cat  # type: ignore
        self.add_item(self.cat_sel)

    async def pick_cat(self, interaction: discord.Interaction):
        v = self.cat_sel.values[0]
        if v == "__none__":
            self.category_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.category_key = v
        await interaction.response.send_message(f"✅ Selected `{v}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Roles (up to 25)", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        v = discord.ui.View(timeout=180)
        rs = discord.ui.RoleSelect(placeholder="Pick roles to add", min_values=1, max_values=25)

        async def on_pick(i: discord.Interaction):
            assert i.guild is not None
            me = guild_me(i.guild)
            if not me:
                return await i.response.send_message("❌ Bot member missing.", ephemeral=True)

            cfg = ensure_shape(load_config())
            cat = (cfg.get("categories") or {}).get(self.category_key)
            if not cat:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            roles_cfg = cat.get("roles") or {}
            added = []

            for role in rs.values:
                if not role_manageable(role, me):
                    continue
                rid = str(role.id)
                if rid in roles_cfg:
                    continue

                roles_cfg[rid] = {"label": role.name, "emoji": None}
                added.append(role)

            cat["roles"] = roles_cfg
            save_config_safe(cfg)

            if added:
                await i.response.send_message("✅ Added: " + ", ".join(r.mention for r in added), ephemeral=True)
            else:
                await i.response.send_message("ℹ️ No roles added (blocked / already present).", ephemeral=True)

        rs.callback = on_pick  # type: ignore
        v.add_item(rs)
        await interaction.response.send_message("Pick roles to add:", view=v, ephemeral=True)

    @discord.ui.button(label="➖ Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = ensure_shape(load_config())
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles_cfg = cat.get("roles") or {}
        if not roles_cfg:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        options = []
        for rid, meta in list(roles_cfg.items())[:25]:
            options.append(discord.SelectOption(
                label=(meta.get("label") or str(rid))[:100],
                value=str(rid),
                emoji=parse_emoji(meta.get("emoji")),
            ))

        sel = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            cfg2 = ensure_shape(load_config())
            cat2 = (cfg2.get("categories") or {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            roles2 = cat2.get("roles") or {}
            rid = sel.values[0]
            if rid in roles2:
                del roles2[rid]
                cat2["roles"] = roles2
                save_config_safe(cfg2)
                return await i.response.send_message("✅ Role removed.", ephemeral=True)
            await i.response.send_message("❌ Role missing.", ephemeral=True)

        sel.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Pick a role to remove:", view=v, ephemeral=True)

    @discord.ui.button(label="😀 Edit Label / Emoji", style=discord.ButtonStyle.primary)
    async def edit_meta(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = ensure_shape(load_config())
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles_cfg = cat.get("roles") or {}
        if not roles_cfg:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        options = []
        for rid, meta in list(roles_cfg.items())[:25]:
            options.append(discord.SelectOption(
                label=(meta.get("label") or str(rid))[:100],
                value=str(rid),
                emoji=parse_emoji(meta.get("emoji")),
            ))

        sel = discord.ui.Select(placeholder="Pick a role to edit", min_values=1, max_values=1, options=options)

        async def on_pick(i: discord.Interaction):
            rid = sel.values[0]
            cfg2 = ensure_shape(load_config())
            cat2 = (cfg2.get("categories") or {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            meta = (cat2.get("roles") or {}).get(rid)
            if not meta:
                return await i.response.send_message("❌ Role missing.", ephemeral=True)

            await i.response.send_modal(RoleMetaModal(self.category_key, int(rid), meta))

        sel.callback = on_pick  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Pick a role to edit:", view=v, ephemeral=True)

# =========================================================
# ADMIN: LOGGING VIEW
# =========================================================

class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = ensure_shape(load_config())
        cfg["logging"]["enabled"] = not bool(cfg["logging"].get("enabled"))
        save_config_safe(cfg)
        await interaction.response.send_message(
            f"🧾 Logging is now **{'ON' if cfg['logging']['enabled'] else 'OFF'}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_chan(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a log channel:", view=SetLogChannelView(), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear_chan(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = ensure_shape(load_config())
        cfg["logging"]["channel_id"] = None
        save_config_safe(cfg)
        await interaction.response.send_message("✅ Log channel cleared.", ephemeral=True)

# =========================================================
# ADMIN: AUTO ROLES
# =========================================================

class AutoRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Add Human Auto-Role", style=discord.ButtonStyle.success)
    async def add_human(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._pick(interaction, "humans")

    @discord.ui.button(label="➕ Add Bot Auto-Role", style=discord.ButtonStyle.success)
    async def add_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._pick(interaction, "bots")

    @discord.ui.button(label="➖ Remove Human Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_human(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._remove(interaction, "humans")

    @discord.ui.button(label="➖ Remove Bot Auto-Role", style=discord.ButtonStyle.danger)
    async def rem_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._remove(interaction, "bots")

    async def _pick(self, interaction: discord.Interaction, target: str):
        assert interaction.guild is not None
        me = guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        v = discord.ui.View(timeout=180)
        rs = discord.ui.RoleSelect(placeholder="Pick an auto-role", min_values=1, max_values=1)

        async def on_pick(i: discord.Interaction):
            role = rs.values[0]
            if not role_manageable(role, me):
                return await i.response.send_message("❌ That role is blocked / not manageable.", ephemeral=True)

            cfg = ensure_shape(load_config())
            arr = (cfg.get("auto_roles") or {}).get(target, [])
            rid = str(role.id)
            if rid not in arr:
                arr.append(rid)
            cfg["auto_roles"][target] = arr
            save_config_safe(cfg)
            await i.response.send_message(f"✅ Added {role.mention} to auto-roles ({target}).", ephemeral=True)

        rs.callback = on_pick  # type: ignore
        v.add_item(rs)
        await interaction.response.send_message("Pick a role:", view=v, ephemeral=True)

    async def _remove(self, interaction: discord.Interaction, target: str):
        cfg = ensure_shape(load_config())
        arr = (cfg.get("auto_roles") or {}).get(target, [])
        if not arr:
            return await interaction.response.send_message("ℹ️ None set.", ephemeral=True)

        options = []
        for rid in arr[:25]:
            role = interaction.guild.get_role(int(rid)) if interaction.guild else None
            options.append(discord.SelectOption(label=(role.name if role else str(rid))[:100], value=str(rid)))

        sel = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            rid = sel.values[0]
            cfg2 = ensure_shape(load_config())
            arr2 = (cfg2.get("auto_roles") or {}).get(target, [])
            if rid in arr2:
                arr2.remove(rid)
            cfg2["auto_roles"][target] = arr2
            save_config_safe(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        sel.callback = on_remove  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Pick one:", view=v, ephemeral=True)

# =========================================================
# ADMIN: ASSIGN / REMOVE ROLES FOR USERS (manageable roles only)
# =========================================================

class AdminUserRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Assign Role to User", style=discord.ButtonStyle.success)
    async def assign(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Pick a user:", view=PickUserView(mode="assign"), ephemeral=True)

    @discord.ui.button(label="➖ Remove Role from User", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Pick a user:", view=PickUserView(mode="remove"), ephemeral=True)

class PickUserView(discord.ui.View):
    def __init__(self, mode: str):
        super().__init__(timeout=180)
        self.mode = mode
        self.us = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        self.us.callback = self.pick  # type: ignore
        self.add_item(self.us)

    async def pick(self, interaction: discord.Interaction):
        user: discord.User = self.us.values[0]
        uid = user.id

        if self.mode == "assign":
            await interaction.response.send_message("Pick a role to assign:", view=PickRoleAssignView(uid), ephemeral=True)
        else:
            view = PickRoleRemoveView(uid)
            await view.populate(interaction.guild)
            await interaction.response.send_message("Pick a role to remove:", view=view, ephemeral=True)

class PickRoleAssignView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.rs = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)
        self.rs.callback = self.pick  # type: ignore
        self.add_item(self.rs)

    async def pick(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        me = guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        role: discord.Role = self.rs.values[0]
        if not role_manageable(role, me):
            return await interaction.response.send_message("❌ That role is blocked / not manageable.", ephemeral=True)

        if role in member.roles:
            return await interaction.response.send_message("ℹ️ They already have that role.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Admin assign by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to assign (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Assigned {role.mention} to {member.mention}", ephemeral=True)

        emb = discord.Embed(title="🛂 Role Assigned", color=discord.Color.green())
        emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
        emb.add_field(name="User", value=member.mention, inline=False)
        emb.add_field(name="Role", value=role.mention, inline=False)
        await send_log(interaction.guild, emb)

class PickRoleRemoveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.sel = discord.ui.Select(placeholder="Pick a role", min_values=1, max_values=1, options=[])
        self.sel.callback = self.pick  # type: ignore
        self.add_item(self.sel)

    async def populate(self, guild: discord.Guild):
        member = guild.get_member(self.user_id) if guild else None
        me = guild_me(guild) if guild else None
        if not member or not me:
            self.sel.options = [discord.SelectOption(label="(Not available)", value="__none__", default=True)]
            return

        manageable = [r for r in member.roles if role_manageable(r, me)]
        manageable.sort(key=lambda r: r.position, reverse=True)
        if not manageable:
            self.sel.options = [discord.SelectOption(label="(No removable roles)", value="__none__", default=True)]
            return

        self.sel.options = [discord.SelectOption(label=r.name[:100], value=str(r.id)) for r in manageable[:25]]

    async def pick(self, interaction: discord.Interaction):
        assert interaction.guild is not None

        if self.sel.values[0] == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)

        me = guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User missing.", ephemeral=True)

        role = interaction.guild.get_role(int(self.sel.values[0]))
        if not role or not role_manageable(role, me):
            return await interaction.response.send_message("❌ Role blocked / not manageable.", ephemeral=True)

        if role not in member.roles:
            return await interaction.response.send_message("ℹ️ They don’t have that role.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Admin remove by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed to remove (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)

        emb = discord.Embed(title="🛂 Role Removed", color=discord.Color.red())
        emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
        emb.add_field(name="User", value=member.mention, inline=False)
        emb.add_field(name="Role", value=role.mention, inline=False)
        await send_log(interaction.guild, emb)

# =========================================================
# ADMIN: MAIN DASHBOARD (/rolesettings)
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_selfroles_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select the self-roles channel:", view=SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        msg = await deploy_or_update_menu(interaction.guild)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def categories(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Category manager:", view=CategoryManagerView(), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles_in_categories(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Role manager:", view=RolesCategoryManagerView(), ephemeral=True)

    @discord.ui.button(label="👥 Auto Roles", style=discord.ButtonStyle.secondary)
    async def autoroles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Auto-roles:", view=AutoRolesView(), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = ensure_shape(load_config())
        state = "ON" if cfg["logging"]["enabled"] else "OFF"
        chan = cfg["logging"].get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{chan}>' if chan else 'Not set'}"
        await interaction.response.send_message("Logging settings:" + extra, view=LoggingView(), ephemeral=True)

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("User role management:", view=AdminUserRoleView(), ephemeral=True)

@app_commands.command(name="rolesettings", description="Admin panel for self-roles + role tools")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission to use this.", ephemeral=True)

    cfg = ensure_shape(load_config())
    ch = cfg.get("selfroles_channel_id")
    mid = cfg.get("selfroles_message_id")

    lg = cfg.get("logging") or {}
    log_state = "ON" if lg.get("enabled") else "OFF"

    desc = []
    desc.append(f"📍 **Self-roles channel:** {f'<#{ch}>' if ch else 'Not set'}")
    desc.append(f"📌 **Menu posted:** {'Yes' if mid else 'No'}")
    desc.append(f"🧾 **Logging:** {log_state}")
    if lg.get("channel_id"):
        desc.append(f"🧾 **Log channel:** <#{lg['channel_id']}>")

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description="\n".join(desc),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)

# =========================================================
# SETUP
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)

    # Register persistent public view so it survives restarts
    try:
        client.add_view(PublicSelfRolesView(active_category=None))
    except Exception:
        pass