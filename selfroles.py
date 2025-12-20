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
# GITHUB CONFIG (selfroles.json lives in repo)
# =========================================================

GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = os.getenv("SELFROLES_FILE_PATH", "selfroles.json")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

# Cache to reduce GitHub calls
_CONFIG_CACHE: Dict[str, Any] = {"data": None, "sha": None, "ts": 0.0}
_CACHE_TTL_SECONDS = 2.0


# =========================================================
# CONFIG SHAPE
# =========================================================

def ensure_shape(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = cfg or {}

    # tolerate bad types
    if isinstance(cfg.get("selfroles_message_id"), list):
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

    # normalize categories defensively
    for k, cat in list(cfg["categories"].items()):
        if not isinstance(cat, dict):
            cfg["categories"][k] = {
                "title": str(k),
                "description": "",
                "emoji": None,
                "multi_select": True,
                "roles": {},
            }
            continue

        cat.setdefault("title", str(k))
        cat.setdefault("description", "")
        cat.setdefault("emoji", None)
        cat.setdefault("multi_select", True)
        cat.setdefault("roles", {})
        if not isinstance(cat["roles"], dict):
            cat["roles"] = {}

        # normalize role meta
        for rid, meta in list(cat["roles"].items()):
            if not isinstance(meta, dict):
                cat["roles"][rid] = {"label": str(rid), "emoji": None}
                continue
            meta.setdefault("label", str(rid))
            meta.setdefault("emoji", None)
            cat["roles"][rid] = meta

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

    payload: Dict[str, Any] = {
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
    sha = _CONFIG_CACHE.get("sha")

    try:
        new_sha = await asyncio.to_thread(_gh_put_file_sync, cfg, sha)
    except RuntimeError as e:
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


async def _defer_ephemeral(interaction: discord.Interaction) -> None:
    # Prevent "interaction failed" during GitHub IO / slow moments
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
    except Exception:
        pass


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
# PUBLIC SELF-ROLES (NO BUTTONS, SELECTS ONLY)
# - Category select always visible so you can "go back"
# =========================================================

def public_embed() -> discord.Embed:
    return discord.Embed(
        title="✨ Choose Your Roles",
        description="Select a category, then pick your roles.\nYou can change these any time ✈️",
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
            custom_id="selfroles:category",
        )

    async def callback(self, interaction: discord.Interaction):
        await _defer_ephemeral(interaction)

        key = self.values[0]
        cfg = await load_config()
        cat = cfg.get("categories", {}).get(key)

        if not cat:
            return await interaction.followup.send("❌ Category no longer exists.", ephemeral=True)

        view = PublicSelfRolesView(active_category=key)
        await interaction.message.edit(embed=role_embed(cat), view=view)


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
            custom_id=f"selfroles:roles:{category_key}",
        )

    async def callback(self, interaction: discord.Interaction):
        await _defer_ephemeral(interaction)

        if not interaction.guild:
            return

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return

        cfg = await load_config()
        cat = cfg.get("categories", {}).get(self.category_key)
        if not cat:
            return await interaction.followup.send("❌ Category missing.", ephemeral=True)

        me = guild_me(interaction.guild)
        if not me:
            return await interaction.followup.send("❌ Bot member missing.", ephemeral=True)

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

        await interaction.followup.send("\n".join(lines), ephemeral=True)


class PublicSelfRolesView(discord.ui.View):
    def __init__(self, active_category: Optional[str] = None):
        super().__init__(timeout=None)
        self.active_category = active_category

        # We DO NOT block in __init__. Instead, we create items in an async task.
        # But discord requires items exist immediately for the outgoing message,
        # so deploy/update builds the "real" view. This class is used for callbacks too.
        #
        # For safety, we show a disabled placeholder if constructed without preloaded categories.
        self.add_item(
            discord.ui.Select(
                placeholder="Loading categories…",
                options=[discord.SelectOption(label="Loading…", value="__loading__")],
                disabled=True,
                custom_id="selfroles:loading",
            )
        )


async def build_public_view(active_category: Optional[str]) -> discord.ui.View:
    cfg = await load_config()
    categories = cfg.get("categories", {}) or {}

    view = discord.ui.View(timeout=None)

    # loader / empty
    if not categories:
        view.add_item(
            discord.ui.Select(
                placeholder="No categories available",
                options=[discord.SelectOption(label="No categories", value="__none__")],
                disabled=True,
                custom_id="selfroles:none",
            )
        )
        return view

    # category select always present
    view.add_item(CategorySelect(categories, selected=active_category))

    # roles select if active category chosen
    if active_category and active_category in categories:
        cat = categories[active_category]
        if cat.get("roles"):
            view.add_item(RoleSelect(active_category, cat))

    return view


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
    view = await build_public_view(active_category=None)

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
# ADMIN: SET CHANNEL PICKERS
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
        await _defer_ephemeral(interaction)
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
        await _defer_ephemeral(interaction)
        channel: discord.abc.GuildChannel = self.sel.values[0]

        cfg = await load_config()
        cfg["logging"]["channel_id"] = channel.id
        await save_config(cfg)

        await interaction.followup.send(f"🧾 Log channel set to {channel.mention}", ephemeral=True)


# =========================================================
# ADMIN: CATEGORY MODAL
# =========================================================

class CategoryModal(discord.ui.Modal, title="Category Settings"):
    def __init__(
        self,
        mode: str,
        existing_key: Optional[str] = None,
        existing: Optional[Dict[str, Any]] = None,
    ):
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
            label="Title (shown to users) e.g. Colour Roles",
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
        # ✅ critical to prevent "interaction failed"
        await _defer_ephemeral(interaction)

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
            cats[key] = {
                "title": self.title_in.value.strip(),
                "description": "",
                "emoji": emoji_raw or None,
                "multi_select": multi,
                "roles": {},
            }
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
    cats = cfg.get("categories") or {}
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
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=category_options(cfg),
        )


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
        await _defer_ephemeral(interaction)

        v = self.sel.values[0]
        if v == "__none__":
            self.selected = None
            return await interaction.followup.send("ℹ️ No categories yet.", ephemeral=True)

        self.selected = v
        await interaction.followup.send(f"✅ Selected `{v}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Category", style=discord.ButtonStyle.success)
    async def add_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        # modal is immediate, no github IO here
        await interaction.response.send_modal(CategoryModal("add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)

        if not self.selected:
            return await interaction.followup.send("❌ Select a category first.", ephemeral=True)

        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.selected)
        if not cat:
            return await interaction.followup.send("❌ Category missing.", ephemeral=True)

        await interaction.followup.send("✏️ Opening editor…", ephemeral=True)
        # we must use followup for the "defer" path; but send_modal requires response
        # so we open the modal via a fresh interaction: easiest is not to defer here
        # HOWEVER: discord.py won't allow modal after defer.
        #
        # So we do the right thing: DO NOT defer when opening modal.
        #
        # -> We'll re-implement correctly by NOT deferring above.
        #
        # This method is replaced below in a safe way.
        return

    @discord.ui.button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger)
    async def delete_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)

        if not self.selected:
            return await interaction.followup.send("❌ Select a category first.", ephemeral=True)

        cfg = await load_config()
        cats = cfg.get("categories") or {}
        if self.selected in cats:
            del cats[self.selected]
            cfg["categories"] = cats
            await save_config(cfg)
            self.selected = None
            return await interaction.followup.send("✅ Category deleted.", ephemeral=True)

        await interaction.followup.send("❌ Category missing.", ephemeral=True)


# --- FIX: Edit Selected must open modal BEFORE defer ---
# We patch the button by subclassing with correct behavior.

class CategoryManagerViewFixed(CategoryManagerView):
    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat_fixed(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.selected)
        if not cat:
            return await interaction.response.send_message("❌ Category missing.", ephemeral=True)

        await interaction.response.send_modal(CategoryModal("edit", existing_key=self.selected, existing=cat))


# =========================================================
# ADMIN: ROLE META MODAL (label / emoji)
# =========================================================

class RoleMetaModal(discord.ui.Modal, title="Role Display Settings"):
    def __init__(self, category_key: str, role_id: str, meta: Dict[str, Any]):
        super().__init__()
        self.category_key = category_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label (shown to users)",
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
        # ✅ critical to prevent "interaction failed"
        await _defer_ephemeral(interaction)

        cfg = await load_config()
        cat = (cfg.get("categories") or {}).get(self.category_key)
        if not cat:
            return await interaction.followup.send("❌ Category missing.", ephemeral=True)

        roles = cat.get("roles") or {}
        if self.role_id not in roles:
            return await interaction.followup.send("❌ Role missing.", ephemeral=True)

        emoji_raw = self.emoji_in.value.strip()
        if emoji_raw and not parse_emoji(emoji_raw):
            return await interaction.followup.send("❌ Invalid emoji format.", ephemeral=True)

        roles[self.role_id]["label"] = self.label_in.value.strip()
        roles[self.role_id]["emoji"] = emoji_raw or None
        cat["roles"] = roles

        await save_config(cfg)
        await interaction.followup.send("✅ Role display updated.", ephemeral=True)


# =========================================================
# ADMIN: ROLES IN CATEGORIES
# =========================================================

class RolesCategoryManagerView(discord.ui.View):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(timeout=300)
        self.category_key: Optional[str] = None

        self.sel = CategoryPicker("Select category to manage roles…", cfg)
        self.sel.callback = self.pick_category  # type: ignore
        self.add_item(self.sel)

    async def pick_category(self, interaction: discord.Interaction):
        await _defer_ephemeral(interaction)

        v = self.sel.values[0]
        if v == "__none__":
            self.category_key = None
            return await interaction.followup.send("ℹ️ No categories yet.", ephemeral=True)

        self.category_key = v
        await interaction.followup.send(f"✅ Selected `{v}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Roles (up to 25)", style=discord.ButtonStyle.success)
    async def add_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.category_key:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        assert interaction.guild is not None
        me = guild_me(interaction.guild)
        if not me:
            return await interaction.response.send_message("❌ Bot member missing.", ephemeral=True)

        view = discord.ui.View(timeout=180)
        rs = discord.ui.RoleSelect(placeholder="Pick roles to add", min_values=1, max_values=25)

        async def picked(i: discord.Interaction):
            await _defer_ephemeral(i)

            cfg2 = await load_config()
            cat = (cfg2.get("categories") or {}).get(self.category_key)
            if not cat:
                return await i.followup.send("❌ Category missing.", ephemeral=True)

            roles_cfg = cat.get("roles") or {}
            added: List[discord.Role] = []

            for role in rs.values:
                if not role_manageable(role, me):
                    continue
                rid = str(role.id)
                if rid in roles_cfg:
                    continue
                roles_cfg[rid] = {"label": role.name, "emoji": None}
                added.append(role)

            cat["roles"] = roles_cfg
            await save_config(cfg2)

            if added:
                await i.followup.send("✅ Added: " + ", ".join(r.mention for r in added), ephemeral=True)
            else:
                await i.followup.send("ℹ️ No roles added.", ephemeral=True)

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

        sel = discord.ui.Select(placeholder="Pick a role to remove", min_values=1, max_values=1, options=options)

        async def picked(i: discord.Interaction):
            await _defer_ephemeral(i)

            cfg2 = await load_config()
            cat2 = (cfg2.get("categories") or {}).get(self.category_key)
            if not cat2:
                return await i.followup.send("❌ Category missing.", ephemeral=True)

            rid = sel.values[0]
            if rid in cat2.get("roles", {}):
                del cat2["roles"][rid]
                await save_config(cfg2)
                return await i.followup.send("✅ Role removed.", ephemeral=True)

            await i.followup.send("❌ Role missing.", ephemeral=True)

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

        sel = discord.ui.Select(placeholder="Pick a role to edit", min_values=1, max_values=1, options=options)

        async def picked(i: discord.Interaction):
            # ✅ DO NOT defer here because we need to open a modal (must use response)
            rid = sel.values[0]
            cfg2 = await load_config()
            meta = (cfg2.get("categories") or {}).get(self.category_key, {}).get("roles", {}).get(rid)
            if not meta:
                return await i.response.send_message("❌ Role missing.", ephemeral=True)

            await i.response.send_modal(RoleMetaModal(self.category_key, rid, meta))

        sel.callback = picked  # type: ignore
        view = discord.ui.View(timeout=180)
        view.add_item(sel)
        await interaction.response.send_message("Pick role to edit:", view=view, ephemeral=True)


# =========================================================
# ADMIN: LOGGING VIEW
# =========================================================

class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)

        cfg = await load_config()
        cfg["logging"]["enabled"] = not bool(cfg.get("logging", {}).get("enabled"))
        await save_config(cfg)

        await interaction.followup.send(
            f"🧾 Logging is now **{'ON' if cfg['logging']['enabled'] else 'OFF'}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="📍 Set Log Channel", style=discord.ButtonStyle.secondary)
    async def set_chan(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select a log channel:", view=SetLogChannelView(), ephemeral=True)

    @discord.ui.button(label="🧹 Clear Log Channel", style=discord.ButtonStyle.danger)
    async def clear_chan(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)

        cfg = await load_config()
        cfg["logging"]["channel_id"] = None
        await save_config(cfg)

        await interaction.followup.send("✅ Log channel cleared.", ephemeral=True)


# =========================================================
# ADMIN DASHBOARD + COMMAND
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select the self-roles channel:", view=SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Public Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)
        msg = await deploy_or_update_menu(interaction.guild)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def cats(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)
        cfg = await load_config()
        await interaction.followup.send("Category manager:", view=CategoryManagerViewFixed(cfg), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)
        cfg = await load_config()
        await interaction.followup.send("Role manager:", view=RolesCategoryManagerView(cfg), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        await _defer_ephemeral(interaction)
        cfg = await load_config()
        state = "ON" if cfg.get("logging", {}).get("enabled") else "OFF"
        chan = cfg.get("logging", {}).get("channel_id")
        extra = f"\nCurrent: **{state}** | Channel: {f'<#{chan}>' if chan else 'Not set'}"
        await interaction.followup.send("Logging settings:" + extra, view=LoggingView(), ephemeral=True)


@app_commands.command(name="rolesettings", description="Admin panel for self-roles")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

    cfg = await load_config()
    lg = cfg.get("logging") or {}

    desc = [
        f"📍 **Self-roles channel:** {f'<#{cfg.get('selfroles_channel_id')}>' if cfg.get('selfroles_channel_id') else 'Not set'}",
        f"📌 **Menu posted:** {'Yes' if cfg.get('selfroles_message_id') else 'No'}",
        f"🧾 **Logging:** {'ON' if lg.get('enabled') else 'OFF'}",
    ]
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

    # Persistent public view registration:
    # We register a basic placeholder view; actual menu uses build_public_view on deploy/update.
    try:
        client.add_view(PublicSelfRolesView(active_category=None))
    except Exception:
        pass