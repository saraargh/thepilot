# selfroles.py
from __future__ import annotations

import os
import json
import base64
import requests
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands

from permissions import has_global_access

# =========================================================
# GitHub config (same pattern as Pilot)
# =========================================================

GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "selfroles.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# =========================================================
# Default structure (ENSURED, never wiped)
# =========================================================

DEFAULT_DATA: Dict[str, Any] = {
    "selfroles_channel_id": None,
    "selfroles_message_ids": [],
    "logging": {
        "enabled": False,
        "channel_id": None
    },
    "auto_roles": {
        "humans": [],
        "bots": []
    },
    "categories": {}
}

def _ensure_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg.setdefault("selfroles_channel_id", None)
    cfg.setdefault("selfroles_message_ids", [])
    cfg.setdefault("logging", {"enabled": False, "channel_id": None})
    cfg.setdefault("auto_roles", {"humans": [], "bots": []})
    cfg.setdefault("categories", {})
    return cfg

def load_selfroles() -> Dict[str, Any]:
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            raw = base64.b64decode(r.json()["content"]).decode()
            data = json.loads(raw) if raw.strip() else DEFAULT_DATA.copy()
            return _ensure_shape(data)
        save_selfroles(DEFAULT_DATA.copy())
        return DEFAULT_DATA.copy()
    except Exception:
        return DEFAULT_DATA.copy()

def save_selfroles(cfg: Dict[str, Any]) -> None:
    cfg = _ensure_shape(cfg)
    try:
        sha = None
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": "Update selfroles settings",
            "content": base64.b64encode(
                json.dumps(cfg, indent=2, ensure_ascii=False).encode()
            ).decode()
        }
        if sha:
            payload["sha"] = sha

        requests.put(_gh_url(), headers=HEADERS, json=payload, timeout=10)
    except Exception:
        pass

# =========================================================
# Helpers
# =========================================================

def _get_bot_member(guild: discord.Guild) -> Optional[discord.Member]:
    return guild.me or guild.get_member(guild.client.user.id)

def _parse_emoji(raw: Optional[str]) -> Optional[discord.PartialEmoji]:
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:
        return None

def _role_default_emoji(role: discord.Role) -> Optional[discord.PartialEmoji]:
    if role.icon:
        return discord.PartialEmoji.from_str(str(role.icon))
    return None

def _is_assignable(role: discord.Role, bot: discord.Member) -> bool:
    if role.is_default():
        return False
    if role.managed:
        return False
    if role.permissions.administrator:
        return False
    if role >= bot.top_role:
        return False
    return True

# =========================================================
# Auto roles (humans vs bots)
# =========================================================

async def apply_auto_roles(member: discord.Member) -> None:
    cfg = load_selfroles()
    targets = cfg["auto_roles"]["bots" if member.bot else "humans"]

    bot = _get_bot_member(member.guild)
    if not bot:
        return

    for rid in targets:
        role = member.guild.get_role(int(rid))
        if not role:
            continue
        if role in member.roles:
            continue
        if not _is_assignable(role, bot):
            continue
        try:
            await member.add_roles(role, reason="Auto role")
        except Exception:
            pass

# =========================================================
# PUBLIC SELF-ROLES VIEW (OPTION B – FLAT)
# =========================================================

class CategoryRoleSelect(discord.ui.RoleSelect):
    def __init__(self, category_key: str, category: Dict[str, Any], guild: discord.Guild):
        self.category_key = category_key
        self.category = category

        roles_cfg = category.get("roles", {})
        role_ids = [int(rid) for rid in roles_cfg.keys()]

        super().__init__(
            placeholder=category.get("title", category_key),
            min_values=0,
            max_values=min(25, len(role_ids)),
            custom_id=f"selfroles:{category_key}"
        )

    async def callback(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("⚠️ Member not found.", ephemeral=True)

        cfg = load_selfroles()
        cat = cfg["categories"].get(self.category_key)
        if not cat:
            return await interaction.response.send_message("⚠️ Category missing.", ephemeral=True)

        bot = _get_bot_member(interaction.guild)
        if not bot:
            return await interaction.response.send_message("⚠️ Bot error.", ephemeral=True)

        allowed_ids = {int(r) for r in cat["roles"].keys()}
        chosen = {r.id for r in self.values}

        added, removed = [], []

        for rid in allowed_ids:
            role = interaction.guild.get_role(rid)
            if not role or not _is_assignable(role, bot):
                continue

            if rid in chosen and role not in member.roles:
                try:
                    await member.add_roles(role)
                    added.append(role)
                except Exception:
                    pass
            elif rid not in chosen and role in member.roles:
                try:
                    await member.remove_roles(role)
                    removed.append(role)
                except Exception:
                    pass

        lines = ["✨ **Your roles have been updated**"]
        if added:
            lines.append("✅ Added: " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ Removed: " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        log = cfg["logging"]
        if log["enabled"] and log["channel_id"] and (added or removed):
            ch = interaction.guild.get_channel(int(log["channel_id"]))
            if isinstance(ch, discord.TextChannel):
                emb = discord.Embed(title="🧩 Self-role update", colour=discord.Colour.blurple())
                emb.add_field(name="User", value=member.mention, inline=False)
                emb.add_field(name="Category", value=cat.get("title", self.category_key), inline=False)
                if added:
                    emb.add_field(name="Added", value=", ".join(r.mention for r in added), inline=False)
                if removed:
                    emb.add_field(name="Removed", value=", ".join(r.mention for r in removed), inline=False)
                try:
                    await ch.send(embed=emb)
                except Exception:
                    pass

class PublicSelfRolesView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        cfg = load_selfroles()

        for key, cat in cfg["categories"].items():
            if not cat.get("roles"):
                continue
            self.add_item(CategoryRoleSelect(key, cat, guild))

# =========================================================
# PUBLIC MENU BUILD + DEPLOY/UPDATE (GitHub-backed)
# =========================================================

def _public_embed() -> discord.Embed:
    return discord.Embed(
        title="✨ Choose Your Roles",
        description="Use the menus below to update your roles.\nYou can change these at any time ✈️",
        colour=discord.Colour.blurple(),
    )

async def deploy_or_update_public_menu(guild: discord.Guild) -> tuple[bool, str]:
    cfg = load_selfroles()
    ch_id = cfg.get("selfroles_channel_id")
    if not ch_id:
        return False, "Self-roles channel not set."

    channel = guild.get_channel(int(ch_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "Configured self-roles channel is missing or not a text channel."

    # Build a fresh view from current JSON
    view = PublicSelfRolesView(guild)
    embed = _public_embed()

    # Discord limit: 5 action rows per message => 5 RoleSelects max per message
    # If you have >5 categories, we split into multiple messages cleanly.
    items = list(view.children)
    chunks: List[List[discord.ui.Item]] = []
    cur: List[discord.ui.Item] = []
    for it in items:
        if len(cur) >= 5:
            chunks.append(cur)
            cur = []
        cur.append(it)
    if cur:
        chunks.append(cur)

    # If no categories, still post a simple embed with no components
    if not chunks:
        chunks = [[]]

    # Try to edit existing messages if known
    msg_ids: List[int] = [int(x) for x in (cfg.get("selfroles_message_ids") or []) if str(x).isdigit()]
    existing_msgs: List[discord.Message] = []
    for mid in msg_ids:
        try:
            existing_msgs.append(await channel.fetch_message(mid))
        except Exception:
            pass

    new_ids: List[int] = []

    # Edit or create per chunk
    for idx, chunk_items in enumerate(chunks):
        chunk_view = discord.ui.View(timeout=None)
        for it in chunk_items:
            chunk_view.add_item(it)

        if idx < len(existing_msgs):
            try:
                await existing_msgs[idx].edit(embed=embed, view=chunk_view)
                new_ids.append(existing_msgs[idx].id)
                continue
            except Exception:
                pass

        try:
            sent = await channel.send(embed=embed, view=chunk_view)
            new_ids.append(sent.id)
        except Exception as e:
            return False, f"Failed to post menu: {e}"

    # If we had more old messages than needed, try to delete extras (optional; ignore failures)
    for extra in existing_msgs[len(chunks):]:
        try:
            await extra.delete()
        except Exception:
            pass

    cfg["selfroles_message_ids"] = new_ids
    save_selfroles(cfg)
    return True, "✅ Posted/updated self-role menu."

# =========================================================
# ADMIN HELPERS / UI BUILDERS
# =========================================================

def _clean_title_for_select(label: str) -> str:
    # Discord SelectOption.label cannot render custom server emoji codes reliably.
    # For titles, we keep it plain text. (You can still use emojis in placeholder.)
    return (label or "").replace("\n", " ").strip()[:100] or "Category"

def _role_option_label_with_custom_emoji(meta: Dict[str, Any], fallback_name: str) -> str:
    # This is the "role name in menus" requirement.
    # Discord SelectOption.label DOES NOT render custom emoji, BUT:
    # we show the emoji via SelectOption.emoji and keep label text clean.
    return (str(meta.get("label") or fallback_name)[:100]) or "Role"

def _role_option_emoji(meta: Dict[str, Any], role: Optional[discord.Role]) -> Optional[discord.PartialEmoji]:
    # Priority:
    # 1) explicit override in JSON
    # 2) role icon emoji (if exists)
    # 3) nothing
    override = meta.get("emoji")
    if override:
        pe = _parse_emoji(override)
        if pe:
            return pe
    if role:
        pe2 = _role_default_emoji(role)
        if pe2:
            return pe2
    return None

def _status_embed() -> discord.Embed:
    cfg = load_selfroles()
    ch = cfg.get("selfroles_channel_id")
    posted = bool(cfg.get("selfroles_message_ids"))
    log = cfg.get("logging", {}) or {}
    embed = discord.Embed(title="⚙️ Role Settings", colour=discord.Colour.blurple())
    embed.add_field(name="📍 Channel", value=(f"<#{ch}>" if ch else "Not set"), inline=False)
    embed.add_field(name="📌 Menu posted", value=("Yes" if posted else "No"), inline=False)
    embed.add_field(name="🧾 Logging", value=("ON" if log.get("enabled") else "OFF"), inline=False)
    if log.get("channel_id"):
        embed.add_field(name="🧾 Log channel", value=f"<#{log['channel_id']}>", inline=False)
    return embed

# =========================================================
# ADMIN: CHANNEL PICKERS
# =========================================================

class SetSelfRolesChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        sel.callback = self.pick  # type: ignore
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = int(interaction.data["values"][0])
        cfg = load_selfroles()
        cfg["selfroles_channel_id"] = cid
        save_selfroles(cfg)
        await interaction.response.send_message(f"✅ Self-roles channel set to <#{cid}>", ephemeral=True)

class SetLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        sel.callback = self.pick  # type: ignore
        self.add_item(sel)

    async def pick(self, interaction: discord.Interaction):
        cid = int(interaction.data["values"][0])
        cfg = load_selfroles()
        cfg.setdefault("logging", {"enabled": False, "channel_id": None})
        cfg["logging"]["channel_id"] = cid
        save_selfroles(cfg)
        await interaction.response.send_message(f"✅ Log channel set to <#{cid}>", ephemeral=True)

# =========================================================
# ADMIN: CATEGORY EDITOR (modal add/edit, select + delete)
# =========================================================

class CategoryModal(discord.ui.Modal, title="Category Settings"):
    key = discord.ui.TextInput(label="Category key (unique, no spaces) e.g. colours", max_length=50)
    title_in = discord.ui.TextInput(label="Title (shows to users) e.g. 🎨 Colour Roles", max_length=150)
    desc = discord.ui.TextInput(label="Description (optional, admin notes)", required=False, style=discord.TextStyle.paragraph, max_length=200)
    multi = discord.ui.TextInput(label="Multi-select? (yes/no)", max_length=5, default="yes")

    def __init__(self, mode: str, existing_key: Optional[str] = None):
        super().__init__()
        self.mode = mode
        self.existing_key = existing_key
        if existing_key:
            cfg = load_selfroles()
            cat = (cfg.get("categories", {}) or {}).get(existing_key) or {}
            self.key.default = existing_key
            self.title_in.default = str(cat.get("title") or "")
            self.desc.default = str(cat.get("description") or "")
            self.multi.default = "yes" if cat.get("multi_select", True) else "no"

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_selfroles()
        cats = cfg.get("categories", {}) or {}

        new_key = self.key.value.strip().lower().replace(" ", "_")
        if not new_key:
            return await interaction.response.send_message("❌ Key required.", ephemeral=True)

        multi_raw = self.multi.value.strip().lower()
        multi_select = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if new_key in cats:
                return await interaction.response.send_message("❌ That key already exists.", ephemeral=True)
            cats[new_key] = {
                "title": self.title_in.value.strip(),
                "description": self.desc.value.strip(),
                "multi_select": multi_select,
                "roles": {}
            }
        else:
            if not self.existing_key or self.existing_key not in cats:
                return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

            # rename if changed
            if new_key != self.existing_key:
                if new_key in cats:
                    return await interaction.response.send_message("❌ New key already exists.", ephemeral=True)
                cats[new_key] = cats.pop(self.existing_key)

            cats[new_key]["title"] = self.title_in.value.strip()
            cats[new_key]["description"] = self.desc.value.strip()
            cats[new_key]["multi_select"] = multi_select
            cats[new_key].setdefault("roles", {})

        cfg["categories"] = cats
        save_selfroles(cfg)
        await interaction.response.send_message("✅ Category saved.", ephemeral=True)

class CategorySelect(discord.ui.Select):
    def __init__(self, placeholder: str):
        cfg = load_selfroles()
        cats = cfg.get("categories", {}) or {}
        opts: List[discord.SelectOption] = []
        for k, c in list(cats.items())[:25]:
            opts.append(discord.SelectOption(label=_clean_title_for_select(c.get("title") or k), value=k))
        if not opts:
            opts = [discord.SelectOption(label="(No categories)", value="__none__", default=True)]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=opts)

class CategoryManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.selected: Optional[str] = None
        self.sel = CategorySelect("Select category to edit/delete")
        self.sel.callback = self.on_sel  # type: ignore
        self.add_item(self.sel)

    async def on_sel(self, interaction: discord.Interaction):
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
        await interaction.response.send_modal(CategoryModal("edit", existing_key=self.selected))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def del_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)
        cfg = load_selfroles()
        cats = cfg.get("categories", {}) or {}
        if self.selected in cats:
            del cats[self.selected]
            cfg["categories"] = cats
            save_selfroles(cfg)
            self.selected = None
            return await interaction.response.send_message("✅ Deleted.", ephemeral=True)
        await interaction.response.send_message("❌ Not found.", ephemeral=True)

# =========================================================
# ADMIN: ROLE EDITOR (ADD up to 25 at once, REMOVE, EDIT label/emoji)
# =========================================================

class RoleDisplayModal(discord.ui.Modal, title="Role Display Settings"):
    label_in = discord.ui.TextInput(label="Label (users see this)", max_length=100)
    emoji_in = discord.ui.TextInput(label="Emoji override (optional). Unicode or <:name:id>", required=False, max_length=80)

    def __init__(self, category_key: str, role_id: int):
        super().__init__()
        self.category_key = category_key
        self.role_id = role_id

        cfg = load_selfroles()
        meta = (((cfg.get("categories", {}) or {}).get(category_key) or {}).get("roles", {}) or {}).get(str(role_id), {}) or {}
        self.label_in.default = str(meta.get("label") or "")
        self.emoji_in.default = str(meta.get("emoji") or "")

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_selfroles()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        roles = cat.get("roles", {}) or {}
        rk = str(self.role_id)
        if rk not in roles:
            return await interaction.response.send_message("❌ Role missing in category.", ephemeral=True)

        emoji_str = self.emoji_in.value.strip()
        if emoji_str and not _parse_emoji(emoji_str):
            return await interaction.response.send_message("❌ Emoji format invalid.", ephemeral=True)

        roles[rk]["label"] = self.label_in.value.strip() or roles[rk].get("label") or "Role"
        roles[rk]["emoji"] = emoji_str or None
        cat["roles"] = roles
        save_selfroles(cfg)
        await interaction.response.send_message("✅ Updated role display.", ephemeral=True)

class RoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        self.cat_select = CategorySelect("Select category to manage roles")
        self.cat_select.callback = self._on_cat  # type: ignore
        self.add_item(self.cat_select)

    async def _on_cat(self, interaction: discord.Interaction):
        v = self.cat_select.values[0]
        if v == "__none__":
            self.category_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)
        self.category_key = v
        await interaction.response.send_message(f"✅ Selected `{v}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Roles (up to 25)", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        assert interaction.guild is not None
        bot = _get_bot_member(interaction.guild)
        if not bot:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        sel = discord.ui.RoleSelect(placeholder="Pick roles…", min_values=1, max_values=25)

        async def picked(i: discord.Interaction):
            cfg = load_selfroles()
            cat = (cfg.get("categories", {}) or {}).get(self.category_key)
            if not cat:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            roles_cfg = cat.get("roles", {}) or {}
            added = 0

            for role in sel.values:
                if not _is_assignable(role, bot):
                    continue
                rid = str(role.id)
                if rid in roles_cfg:
                    continue

                # Default meta: label = role.name, emoji = None (auto-pull at render time)
                roles_cfg[rid] = {"label": role.name, "emoji": None}
                added += 1

            cat["roles"] = roles_cfg
            save_selfroles(cfg)

            await i.response.send_message(f"✅ Added **{added}** role(s) to `{self.category_key}`.", ephemeral=True)

        sel.callback = picked  # type: ignore
        view.add_item(sel)
        await interaction.response.send_message("Select roles to add:", view=view, ephemeral=True)

    @discord.ui.button(label="➖ Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = load_selfroles()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key) or {}
        roles_cfg = cat.get("roles", {}) or {}
        if not roles_cfg:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        opts: List[discord.SelectOption] = []
        for rid_str, meta in list(roles_cfg.items())[:25]:
            role = interaction.guild.get_role(int(rid_str)) if interaction.guild else None
            name = role.name if role else rid_str
            opts.append(discord.SelectOption(label=_role_option_label_with_custom_emoji(meta, name), value=rid_str))

        sel = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=opts)

        async def picked(i: discord.Interaction):
            cfg2 = load_selfroles()
            cat2 = (cfg2.get("categories", {}) or {}).get(self.category_key) or {}
            roles2 = cat2.get("roles", {}) or {}
            rid = sel.values[0]
            if rid in roles2:
                del roles2[rid]
            cat2["roles"] = roles2
            save_selfroles(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        sel.callback = picked  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Select a role to remove:", view=v, ephemeral=True)

    @discord.ui.button(label="😀 Edit Label/Emoji Override", style=discord.ButtonStyle.primary)
    async def edit_display(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = load_selfroles()
        cat = (cfg.get("categories", {}) or {}).get(self.category_key) or {}
        roles_cfg = cat.get("roles", {}) or {}
        if not roles_cfg:
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        opts: List[discord.SelectOption] = []
        for rid_str, meta in list(roles_cfg.items())[:25]:
            role = interaction.guild.get_role(int(rid_str)) if interaction.guild else None
            name = role.name if role else rid_str
            # show emoji as option.emoji if available (override or role icon)
            opts.append(
                discord.SelectOption(
                    label=_role_option_label_with_custom_emoji(meta, name),
                    value=rid_str,
                    emoji=_role_option_emoji(meta, role)
                )
            )

        sel = discord.ui.Select(placeholder="Pick one to edit", min_values=1, max_values=1, options=opts)

        async def picked(i: discord.Interaction):
            rid = int(sel.values[0])
            await i.response.send_modal(RoleDisplayModal(self.category_key, rid))

        sel.callback = picked  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Select a role to edit:", view=v, ephemeral=True)

# =========================================================
# ADMIN: LOGGING
# =========================================================

class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = load_selfroles()
        cfg.setdefault("logging", {"enabled": False, "channel_id": None})
        cfg["logging"]["enabled"] = not bool(cfg["logging"].get("enabled"))
        save_selfroles(cfg)
        await interaction.response.send_message(
            f"🧾 Logging is now **{'ON' if cfg['logging']['enabled'] else 'OFF'}**.",
            ephemeral=True
        )

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a log channel:", view=SetLogChannelView(), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = load_selfroles()
        cfg.setdefault("logging", {"enabled": False, "channel_id": None})
        cfg["logging"]["channel_id"] = None
        save_selfroles(cfg)
        await interaction.response.send_message("✅ Cleared log channel.", ephemeral=True)

# =========================================================
# ADMIN: AUTO ROLES (humans vs bots)
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
        bot = _get_bot_member(interaction.guild)
        if not bot:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        sel = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)

        async def picked(i: discord.Interaction):
            role = sel.values[0]
            if not _is_assignable(role, bot):
                return await i.response.send_message("❌ That role is blocked or not manageable.", ephemeral=True)

            cfg = load_selfroles()
            cfg.setdefault("auto_roles", {"humans": [], "bots": []})
            arr = cfg["auto_roles"].get(target, [])
            rid = str(role.id)
            if rid not in arr:
                arr.append(rid)
            cfg["auto_roles"][target] = arr
            save_selfroles(cfg)
            await i.response.send_message(f"✅ Added {role.mention} to auto roles ({target}).", ephemeral=True)

        sel.callback = picked  # type: ignore
        view.add_item(sel)
        await interaction.response.send_message("Select a role:", view=view, ephemeral=True)

    async def _remove(self, interaction: discord.Interaction, target: str):
        cfg = load_selfroles()
        arr = (cfg.get("auto_roles", {}) or {}).get(target, []) or []
        if not arr:
            return await interaction.response.send_message("ℹ️ None set.", ephemeral=True)

        opts = []
        for rid_str in arr[:25]:
            r = interaction.guild.get_role(int(rid_str)) if interaction.guild else None
            opts.append(discord.SelectOption(label=(r.name if r else rid_str), value=rid_str))

        sel = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=opts)

        async def picked(i: discord.Interaction):
            cfg2 = load_selfroles()
            arr2 = (cfg2.get("auto_roles", {}) or {}).get(target, []) or []
            v = sel.values[0]
            if v in arr2:
                arr2.remove(v)
            cfg2["auto_roles"][target] = arr2
            save_selfroles(cfg2)
            await i.response.send_message("✅ Removed.", ephemeral=True)

        sel.callback = picked  # type: ignore
        v = discord.ui.View(timeout=180)
        v.add_item(sel)
        await interaction.response.send_message("Select one to remove:", view=v, ephemeral=True)

# =========================================================
# ADMIN: ASSIGN/REMOVE ROLES TO USERS (ALL roles w/ guardrails)
# =========================================================

class UserRoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ Assign Role to User", style=discord.ButtonStyle.success)
    async def assign(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a user:", view=PickUserAssignView(), ephemeral=True)

    @discord.ui.button(label="➖ Remove Role from User", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a user:", view=PickUserRemoveView(), ephemeral=True)

class PickUserAssignView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self.picked  # type: ignore
        self.add_item(sel)

    async def picked(self, interaction: discord.Interaction):
        uid = interaction.data["values"][0]
        await interaction.response.send_message("Pick a role to assign:", view=PickRoleAssignView(int(uid)), ephemeral=True)

class PickRoleAssignView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        sel = discord.ui.RoleSelect(placeholder="Pick a role", min_values=1, max_values=1)
        sel.callback = self.picked  # type: ignore
        self.add_item(sel)

    async def picked(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        bot = _get_bot_member(interaction.guild)
        if not bot:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        role = self.children[0].values[0]  # type: ignore
        if not _is_assignable(role, bot):
            return await interaction.response.send_message("❌ That role is blocked or not manageable.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Admin assign by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Assigned {role.mention} to {member.mention}", ephemeral=True)

class PickUserRemoveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        sel = discord.ui.UserSelect(placeholder="Pick a user", min_values=1, max_values=1)
        sel.callback = self.picked  # type: ignore
        self.add_item(sel)

    async def picked(self, interaction: discord.Interaction):
        uid = interaction.data["values"][0]
        await interaction.response.send_message("Pick a role to remove:", view=PickRoleRemoveView(int(uid)), ephemeral=True)

class PickRoleRemoveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.sel = discord.ui.Select(placeholder="Pick a role", min_values=1, max_values=1, options=[])
        self.sel.callback = self.picked  # type: ignore
        self.add_item(self.sel)

    async def _populate(self, guild: discord.Guild):
        bot = _get_bot_member(guild)
        member = guild.get_member(self.user_id)
        if not bot or not member:
            self.sel.options = [discord.SelectOption(label="(None)", value="__none__", default=True)]
            return

        manageable = [r for r in member.roles if _is_assignable(r, bot)]
        manageable.sort(key=lambda r: r.position, reverse=True)
        if not manageable:
            self.sel.options = [discord.SelectOption(label="(None)", value="__none__", default=True)]
            return

        self.sel.options = [discord.SelectOption(label=r.name[:100], value=str(r.id)) for r in manageable[:25]]

    async def picked(self, interaction: discord.Interaction):
        assert interaction.guild is not None
        bot = _get_bot_member(interaction.guild)
        if not bot:
            return await interaction.response.send_message("❌ Bot missing.", ephemeral=True)

        val = self.sel.values[0]
        if val == "__none__":
            return await interaction.response.send_message("ℹ️ Nothing to remove.", ephemeral=True)

        member = interaction.guild.get_member(self.user_id)
        role = interaction.guild.get_role(int(val))
        if not member or not role:
            return await interaction.response.send_message("❌ Missing user/role.", ephemeral=True)

        if not _is_assignable(role, bot):
            return await interaction.response.send_message("❌ That role is blocked.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Admin remove by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)

# =========================================================
# ADMIN DASHBOARD
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select the self-roles channel:", view=SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        assert interaction.guild is not None
        ok, msg = await deploy_or_update_public_menu(interaction.guild)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def categories(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Category manager:", view=CategoryManagerView(), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Role manager:", view=RoleManagerView(), ephemeral=True)

    @discord.ui.button(label="👥 Auto Roles", style=discord.ButtonStyle.secondary)
    async def autoroles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Auto roles:", view=AutoRolesView(), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = load_selfroles()
        log = cfg.get("logging", {}) or {}
        state = "ON" if log.get("enabled") else "OFF"
        ch = log.get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{ch}>' if ch else 'Not set'}"
        await interaction.response.send_message("Logging settings:" + extra, view=LoggingView(), ephemeral=True)

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_assign(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("User role management:", view=UserRoleManagerView(), ephemeral=True)

# =========================================================
# /rolesettings COMMAND (ADMIN ONLY via Pilot permissions)
# =========================================================

@app_commands.command(name="rolesettings", description="Admin panel for self-roles & role tools")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

    await interaction.response.send_message(embed=_status_embed(), view=RoleSettingsDashboard(), ephemeral=True)

# =========================================================
# SETUP (botslash will call setup(tree, client))
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    # Add /rolesettings
    tree.add_command(rolesettings)

    # Register persistent public views (one per guild when deploy occurs)
    # We cannot know guild at import-time; persistent views are rebuilt at deploy/update.
    # Still, we register a "dummy" persistent container once to satisfy discord.py.
    try:
        # This does not include items; items get added when we create views in deploy_or_update_public_menu
        client.add_view(discord.ui.View(timeout=None))
    except Exception:
        pass

# =========================================================
# IMPORTANT NOTE:
# If you use PickRoleRemoveView, populate options after sending it:
# (discord.py doesn't auto-populate custom options)
# We'll do it from botslash or from within the flow when used.
# =========================================================

async def prepare_remove_view(view: PickRoleRemoveView, guild: discord.Guild):
    await view._populate(guild)
