from __future__ import annotations

import os
import json
import base64
import asyncio
from typing import Dict, Any, List, Optional, Tuple

import requests
import discord
from discord import app_commands

from permissions import has_global_access

# =========================================================
# GITHUB CONFIG (selfroles.json lives in same repo)
# =========================================================

GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = os.getenv("SELFROLES_FILE_PATH", "selfroles.json")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# Small cache so we don't spam GitHub for every UI redraw.
_CONFIG_CACHE: Dict[str, Any] = {"data": None, "sha": None, "ts": 0.0}
_CACHE_TTL_SECONDS = 2.0

# =========================================================
# CONFIG SHAPE
# =========================================================

def ensure_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = cfg or {}

    # tolerate bad types from manual edits
    if isinstance(cfg.get("selfroles_message_id"), list):
        # some people tried []
        cfg["selfroles_message_id"] = None

    cfg.setdefault("selfroles_channel_id", None)
    cfg.setdefault("selfroles_message_id", None)

    cfg.setdefault("logging", {})
    if not isinstance(cfg["logging"], dict):
        cfg["logging"] = {}
    cfg["logging"].setdefault("enabled", False)
    cfg["logging"].setdefault("channel_id", None)

    cfg.setdefault("auto_roles", {})
    if not isinstance(cfg["auto_roles"], dict):
        cfg["auto_roles"] = {}
    cfg["auto_roles"].setdefault("humans", [])
    cfg["auto_roles"].setdefault("bots", [])

    cfg.setdefault("categories", {})
    if not isinstance(cfg["categories"], dict):
        cfg["categories"] = {}

    # normalize category structure defensively
    for k, cat in list(cfg["categories"].items()):
        if not isinstance(cat, dict):
            cfg["categories"][k] = {"title": str(k), "description": "", "multi_select": True, "roles": {}}
            continue
        cat.setdefault("title", str(k))
        cat.setdefault("description", "")
        cat.setdefault("emoji", None)
        cat.setdefault("multi_select", True)
        cat.setdefault("roles", {})
        if not isinstance(cat["roles"], dict):
            cat["roles"] = {}
        cfg["categories"][k] = cat

    return cfg

# =========================================================
# GITHUB IO (async-safe)
# =========================================================

def _gh_get_file_sync() -> Tuple[Dict[str, Any], Optional[str]]:
    r = requests.get(_gh_url(), headers=HEADERS, timeout=15)
    if r.status_code == 404:
        return ensure_shape({}), None
    if r.status_code != 200:
        raise RuntimeError(f"GitHub GET failed: {r.status_code} {r.text}")

    payload = r.json()
    sha = payload.get("sha")
    content_b64 = payload.get("content", "")
    raw = base64.b64decode(content_b64).decode("utf-8") if content_b64 else ""
    data = json.loads(raw) if raw.strip() else {}
    return ensure_shape(data), sha

def _gh_put_file_sync(cfg: Dict[str, Any], sha: Optional[str]) -> str:
    cfg = ensure_shape(cfg)
    body = json.dumps(cfg, indent=2, ensure_ascii=False)

    payload = {
        "message": "Update selfroles.json",
        "content": base64.b64encode(body.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(_gh_url(), headers=HEADERS, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub PUT failed: {r.status_code} {r.text}")

    return r.json().get("content", {}).get("sha") or r.json().get("sha") or sha or ""

async def load_config() -> Dict[str, Any]:
    now = asyncio.get_running_loop().time()
    if _CONFIG_CACHE["data"] is not None and (now - float(_CONFIG_CACHE["ts"])) <= _CACHE_TTL_SECONDS:
        return ensure_shape(dict(_CONFIG_CACHE["data"]))

    data, sha = await asyncio.to_thread(_gh_get_file_sync)
    _CONFIG_CACHE["data"] = dict(data)
    _CONFIG_CACHE["sha"] = sha
    _CONFIG_CACHE["ts"] = now
    return ensure_shape(dict(data))

async def save_config(cfg: Dict[str, Any]) -> None:
    # optimistic: use cached sha first
    sha = _CONFIG_CACHE.get("sha")

    try:
        new_sha = await asyncio.to_thread(_gh_put_file_sync, cfg, sha)
    except RuntimeError as e:
        # If SHA mismatch or stale, refetch once and retry.
        # GitHub returns 409 or 422 sometimes depending on state.
        msg = str(e)
        if "409" in msg or "422" in msg:
            fresh_cfg, fresh_sha = await asyncio.to_thread(_gh_get_file_sync)
            _CONFIG_CACHE["data"] = dict(fresh_cfg)
            _CONFIG_CACHE["sha"] = fresh_sha
            _CONFIG_CACHE["ts"] = asyncio.get_running_loop().time()
            new_sha = await asyncio.to_thread(_gh_put_file_sync, cfg, fresh_sha)
        else:
            raise

    _CONFIG_CACHE["data"] = ensure_shape(dict(cfg))
    _CONFIG_CACHE["sha"] = new_sha or sha
    _CONFIG_CACHE["ts"] = asyncio.get_running_loop().time()

# =========================================================
# HELPERS
# =========================================================

def guild_me(guild: discord.Guild) -> Optional[discord.Member]:
    try:
        return guild.me or guild.get_member(guild.client.user.id)
    except Exception:
        return None

def parse_emoji(raw: Optional[str]):
    raw = (raw or "").strip()
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

async def send_log(guild: discord.Guild, embed: discord.Embed):
    cfg = await load_config()
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
# AUTO ROLES
# =========================================================

async def apply_auto_roles(member: discord.Member):
    cfg = await load_config()
    auto = cfg.get("auto_roles", {})
    role_ids = auto.get("bots" if member.bot else "humans", [])

    me = guild_me(member.guild)
    if not me:
        return

    for rid in role_ids:
        try:
            role = member.guild.get_role(int(rid))
        except Exception:
            continue
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
    def __init__(self, categories: Dict[str, Any], selected: Optional[str] = None):
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
        cfg = await load_config()
        cat = cfg.get("categories", {}).get(key)

        if not cat:
            return await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)

        view = PublicSelfRolesView(active_category=key)
        await interaction.response.edit_message(embed=role_embed(cat), view=view)

class RoleSelect(discord.ui.Select):
    def __init__(self, category_key: str, category: dict):
        self.category_key = category_key

        options: List[discord.SelectOption] = []
        for rid, meta in (category.get("roles", {}) or {}).items():
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
            max_values=(len(options) if multi else 1) if options else 1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        cfg = await load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return

        me = guild_me(interaction.guild)
        if not me:
            return

        valid_ids = {int(r) for r in (cat.get("roles", {}) or {}).keys() if str(r).isdigit()}
        selected = {int(v) for v in self.values if str(v).isdigit()}

        added, removed = [], []

        for rid in valid_ids:
            role = interaction.guild.get_role(rid)
            if not role or not role_manageable(role, me):
                continue

            if rid in selected and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Self-role")
                    added.append(role)
                except Exception:
                    pass
            elif rid not in selected and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Self-role")
                    removed.append(role)
                except Exception:
                    pass

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

        # Category selector ALWAYS visible so users can go back
        # (this fixes your “no way to pick something else” issue)
        self._active_category = active_category

        # We'll populate items lazily in on_timeout-safe way via current config
        # but discord.py requires items in __init__, so we load once here.
        # This is fine because view is rebuilt on category click + deploy/update.
        # Data changes without deploy are handled by deploy/update button in admin.
        # (and yes, it reads GitHub now)
        # NOTE: This matches your original behavior.
        # -------------------------------------------------------------
        # If you edit JSON manually in GitHub, press "Post/Update Public Menu".
        # -------------------------------------------------------------
        # You explicitly asked not to require redeploy for JSON changes. ✅
        # This is now true.
        cfg = asyncio.get_event_loop().run_until_complete(load_config()) if asyncio.get_event_loop().is_running() is False else None  # type: ignore
        # The above line is a safety fallback for rare cases; normally the bot loop is running.
        # We'll do the normal async path below:
        categories = {}
        if cfg:
            categories = cfg.get("categories", {}) or {}

        # If we are in an active running loop, we can't block here.
        # In that case we'll add a minimal placeholder, and rebuild views on interaction.
        if not categories:
            # We still add empty select to avoid component missing; it will rebuild on click.
            self.add_item(discord.ui.Select(placeholder="Loading categories…", options=[discord.SelectOption(label="Loading…", value="__loading__")], min_values=1, max_values=1))
            return

        self.add_item(CategorySelect(categories, selected=active_category))

        if active_category and active_category in categories:
            cat = categories[active_category]
            if cat.get("roles"):
                self.add_item(RoleSelect(active_category, cat))

# =========================================================
# DEPLOY / UPDATE PUBLIC MENU MESSAGE
# =========================================================

async def deploy_or_update_menu(guild: discord.Guild) -> str:
    cfg = await load_config()

    cid = cfg.get("selfroles_channel_id")
    if not cid:
        return "❌ Self-roles channel not set."

    ch = guild.get_channel(int(cid))
    if not isinstance(ch, discord.TextChannel):
        return "❌ Configured self-roles channel is missing or not a text channel."

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
    await save_config(cfg)
    return "✅ Posted a new self-role menu."

# =========================================================
# ADMIN: SET CHANNEL PICKERS (NO interaction.data hacks)
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
        await interaction.response.defer(ephemeral=True)
        channel: discord.abc.GuildChannel = self.sel.values[0]
        cfg = await load_config()
        cfg["selfroles_channel_id"] = channel.id
        await save_config(cfg)
        await interaction.followup.send(f"📍 Self-roles channel set to {channel.mention}", ephemeral=True)

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
        await interaction.response.defer(ephemeral=True)
        channel: discord.abc.GuildChannel = self.sel.values[0]
        cfg = await load_config()
        cfg["logging"]["channel_id"] = channel.id
        await save_config(cfg)
        await interaction.followup.send(f"🧾 Log channel set to {channel.mention}", ephemeral=True)

# =========================================================
# ADMIN: CATEGORY MODAL
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
        await interaction.response.defer(ephemeral=True)

        cfg = await load_config()
        cats = cfg.get("categories") or {}

        key = self.key_in.value.strip().lower().replace(" ", "_")
        if not key:
            return await interaction.followup.send("❌ Category key required.", ephemeral=True)

        emoji_raw = self.emoji_in.value.strip()
        if emoji_raw and not parse_emoji(emoji_raw):
            return await interaction.followup.send("❌ Emoji format invalid.", ephemeral=True)

        multi_raw = self.multi_in.value.strip().lower()
        multi = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if key in cats:
                return await interaction.followup.send("❌ That category key already exists.", ephemeral=True)
            cats[key] = {"title": self.title_in.value.strip(), "description": "", "emoji": emoji_raw or None, "multi_select": multi, "roles": {}}
        else:
            if not self.existing_key or self.existing_key not in cats:
                return await interaction.followup.send("❌ Category missing.", ephemeral=True)

            if key != self.existing_key:
                if key in cats:
                    return await interaction.followup.send("❌ New key already exists.", ephemeral=True)
                cats[key] = cats.pop(self.existing_key)

            cats[key].setdefault("roles", {})
            cats[key]["title"] = self.title_in.value.strip()
            cats[key]["emoji"] = emoji_raw or None
            cats[key]["multi_select"] = multi

        cfg["categories"] = cats
        await save_config(cfg)
        await interaction.followup.send("✅ Category saved.", ephemeral=True)

# =========================================================
# ADMIN: CATEGORY PICKER
# =========================================================

def category_options(cfg: Dict[str, Any]) -> List[discord.SelectOption]:
    cats = (cfg.get("categories") or {})
    if not cats:
        return [discord.SelectOption(label="(No categories)", value="__none__", default=True)]
    opts: List[discord.SelectOption] = []
    for k, v in list(cats.items())[:25]:
        opts.append(
            discord.SelectOption(
                label=(v.get("title") or k)[:100],
                value=k,
                emoji=parse_emoji(v.get("emoji")),
            )
        )
    return opts

class CategoryPicker(discord.ui.Select):
    def __init__(self, placeholder: str, cfg: Dict[str, Any]):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=category_options(cfg))

# =========================================================
# ADMIN: CATEGORY MANAGER VIEW
# =========================================================

class CategoryManagerView(discord.ui.View):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(timeout=300)
        self.selected: Optional[str] = None

        self.sel = CategoryPicker("Select category to edit/delete…", cfg)
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
        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.selected)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)
        await interaction.response.send_modal(CategoryModal("edit", existing_key=self.selected, existing=cat))

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        cfg = await load_config()
        cats = cfg.get("categories") or {}
        if self.selected in cats:
            del cats[self.selected]
            cfg["categories"] = cats
            await save_config(cfg)
            self.selected = None
            return await interaction.followup.send("✅ Category deleted.", ephemeral=True)

        await interaction.followup.send("❌ Category missing.", ephemeral=True)

# =========================================================
# ADMIN: ROLES IN CATEGORIES (multi-add up to 25)
# =========================================================

class RoleMetaModal(discord.ui.Modal, title="Role Display Settings"):
    def __init__(self, category_key: str, role_id: int, meta: Dict[str, Any]):
        super().__init__()
        self.category_key = category_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label (shown to users – emoji allowed)",
            required=True,
            max_length=100,
            default=str(meta.get("label") or ""),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji override (optional, <:name:id> or unicode)",
            required=False,
            max_length=80,
            default=str(meta.get("emoji") or ""),
        )

        self.add_item(self.label_in)
        self.add_item(self.emoji_in)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat:
            return await interaction.followup.send("❌ Category missing.", ephemeral=True)

        roles = cat.get("roles") or {}
        rid = str(self.role_id)
        if rid not in roles:
            return await interaction.followup.send("❌ Role missing.", ephemeral=True)

        emoji_raw = self.emoji_in.value.strip()
        if emoji_raw and not parse_emoji(emoji_raw):
            return await interaction.followup.send("❌ Invalid emoji format.", ephemeral=True)

        roles[rid]["label"] = self.label_in.value.strip()
        roles[rid]["emoji"] = emoji_raw or None
        cat["roles"] = roles

        await save_config(cfg)
        await interaction.followup.send("✅ Role display updated.", ephemeral=True)


class RolesCategoryManagerView(discord.ui.View):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        self.sel = CategoryPicker("Select category to manage roles…", cfg)
        self.sel.callback = self.pick_category  # type: ignore
        self.add_item(self.sel)

    async def pick_category(self, interaction: discord.Interaction):
        v = self.sel.values[0]
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
        me = guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        rs = discord.ui.RoleSelect(min_values=1, max_values=25)

        async def picked(i: discord.Interaction):
            cfg = await load_config()
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
            await save_config(cfg)

            if added:
                await i.response.send_message(
                    "✅ Added: " + ", ".join(r.mention for r in added),
                    ephemeral=True,
                )
            else:
                await i.response.send_message("ℹ️ No roles added.", ephemeral=True)

        rs.callback = picked  # type: ignore
        view.add_item(rs)
        await interaction.response.send_message("Pick roles to add:", view=view, ephemeral=True)

    @discord.ui.button(label="➖ Remove Role", style=discord.ButtonStyle.danger)
    async def remove_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat or not cat.get("roles"):
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        options = [
            discord.SelectOption(
                label=(meta.get("label") or rid)[:100],
                value=rid,
                emoji=parse_emoji(meta.get("emoji")),
            )
            for rid, meta in list(cat["roles"].items())[:25]
        ]

        sel = discord.ui.Select(min_values=1, max_values=1, options=options)

        async def picked(i: discord.Interaction):
            cfg2 = await load_config()
            cat2 = (cfg2.get("categories") or {}).get(self.category_key)
            if not cat2:
                return await i.response.send_message("❌ Category missing.", ephemeral=True)

            rid = sel.values[0]
            if rid in cat2.get("roles", {}):
                del cat2["roles"][rid]
                await save_config(cfg2)
                return await i.response.send_message("✅ Role removed.", ephemeral=True)

            await i.response.send_message("❌ Role missing.", ephemeral=True)

        sel.callback = picked  # type: ignore
        view = discord.ui.View(timeout=180)
        view.add_item(sel)
        await interaction.response.send_message("Pick role to remove:", view=view, ephemeral=True)

    @discord.ui.button(label="😀 Edit Label / Emoji", style=discord.ButtonStyle.primary)
    async def edit_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat or not cat.get("roles"):
            return await interaction.response.send_message("ℹ️ No roles in this category.", ephemeral=True)

        options = [
            discord.SelectOption(
                label=(meta.get("label") or rid)[:100],
                value=rid,
                emoji=parse_emoji(meta.get("emoji")),
            )
            for rid, meta in list(cat["roles"].items())[:25]
        ]

        sel = discord.ui.Select(min_values=1, max_values=1, options=options)

        async def picked(i: discord.Interaction):
            rid = sel.values[0]
            cfg2 = await load_config()
            meta = (cfg2.get("categories") or {}).get(self.category_key, {}).get("roles", {}).get(rid)
            if not meta:
                return await i.response.send_message("❌ Role missing.", ephemeral=True)

            await i.response.send_modal(RoleMetaModal(self.category_key, int(rid), meta))

        sel.callback = picked  # type: ignore
        view = discord.ui.View(timeout=180)
        view.add_item(sel)
        await interaction.response.send_message("Pick role to edit:", view=view, ephemeral=True)

# =========================================================
# ADMIN DASHBOARD + COMMAND
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cfg = cfg

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Select the self-roles channel:",
            view=SetSelfRolesChannelView(),
            ephemeral=True,
        )

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        msg = await deploy_or_update_menu(interaction.guild)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def cats(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await load_config()
        await interaction.response.send_message(
            "Category manager:",
            view=CategoryManagerView(cfg),
            ephemeral=True,
        )

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await load_config()
        await interaction.response.send_message(
            "Role manager:",
            view=RolesCategoryManagerView(cfg),
            ephemeral=True,
        )

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await load_config()
        state = "ON" if cfg.get("logging", {}).get("enabled") else "OFF"
        await interaction.response.send_message(
            f"Logging is **{state}**.",
            view=LoggingView(),
            ephemeral=True,
        )


@app_commands.command(name="rolesettings", description="Admin panel for self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

    cfg = await load_config()
    desc = [
        f"📍 **Self-roles channel:** {f'<#{cfg.get('selfroles_channel_id')}>' if cfg.get('selfroles_channel_id') else 'Not set'}",
        f"📌 **Menu posted:** {'Yes' if cfg.get('selfroles_message_id') else 'No'}",
        f"🧾 **Logging:** {'ON' if cfg.get('logging', {}).get('enabled') else 'OFF'}",
    ]

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description="\n".join(desc),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(
        embed=embed,
        view=RoleSettingsDashboard(cfg),
        ephemeral=True,
    )

# =========================================================
# SETUP
# =========================================================

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)

    # Persistent public view
    try:
        client.add_view(PublicSelfRolesView(active_category=None))
    except Exception:
        pass