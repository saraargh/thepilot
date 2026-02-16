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

    cfg.setdefault("requests_channel_id", None)

    cfg.setdefault("role_request_instructions", "")

    cfg.setdefault("role_requests", {})
    if not isinstance(cfg["role_requests"], dict):
        cfg["role_requests"] = {}
    
    cfg.setdefault("categories", {})
    if not isinstance(cfg["categories"], dict):
        cfg["categories"] = {}

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

async def load_config(force: bool = False) -> Dict[str, Any]:
    now = asyncio.get_running_loop().time()
    if not force:
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

def guild_me(guild: discord.Guild) -> Optional[discord.Member]:
    try:
        return guild.me or guild.get_member(guild.client.user.id)
    except Exception:
        return None

import re

_VARIATION_SELECTORS = {"\uFE0F", "\uFE0E"}  # VS16 / VS15

def _strip_variation_selectors(s: str) -> str:
    return "".join(ch for ch in s if ch not in _VARIATION_SELECTORS).strip()

def parse_emoji(raw: Optional[str]):
    """
    Safe emoji parser for SelectOption:
    - Custom emoji "<:name:id>" or "<a:name:id>" -> PartialEmoji (name normalised)
    - Unicode emoji -> str (variation selectors stripped)
    - Anything else -> None
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    # Custom emoji
    if raw.startswith("<") and raw.endswith(">"):
        try:
            pe = discord.PartialEmoji.from_str(raw)
            if pe.id is None:
                return None

            name = (pe.name or "").lower()
            name = re.sub(r"[^a-z0-9_]", "", name)

            if not (1 <= len(name) <= 32):
                return None

            return discord.PartialEmoji(name=name, id=pe.id, animated=pe.animated)
        except Exception:
            return None

    # Unicode emoji
    uni = _strip_variation_selectors(raw)

    # reject obvious garbage / accidental strings
    if any(ch.isspace() for ch in uni):
        return None
    if "<" in uni or ">" in uni:
        return None
    if len(uni) > 32:
        return None

    return uni
        
# =========================================================
# ROLE / LOGGING HELPERS
# =========================================================

def role_manageable(role: discord.Role, me: discord.Member) -> bool:
    if role.is_default():
        return False
    if role.managed:
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

def _fmt_chan(cid: Optional[int]) -> str:
    return f"<#{cid}>" if cid else "Not set"

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
# PUBLIC SELF ROLES (NO BUTTONS)
# =========================================================

def public_embed() -> discord.Embed:
    return discord.Embed(
        title="✨ Choose Your Roles",
        description="Select a category, then pick your roles.\nYou can change these any time ✈️",
        color=discord.Color.blurple(),
    )

def role_embed(cat: dict) -> discord.Embed:
    desc = (cat.get("description") or "").strip()
    text = f"{desc}\n\nSelect your roles below." if desc else "Select your roles below."
    return discord.Embed(
        title=cat.get("title", "Roles"),
        description=text,
        color=discord.Color.blurple(),
    )

class CategorySelect(discord.ui.Select):
    def __init__(self, categories: Dict[str, Any], selected: Optional[str] = None):
        options: List[discord.SelectOption] = []

        for key, cat in list(categories.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=(cat.get("title") or key)[:100],
                    value=key,
                    emoji=parse_emoji(cat.get("emoji")),
                    default=(key == selected),
                )
            )

        if not options:
            options = [discord.SelectOption(label="No categories", value="__none__")]

        super().__init__(
            placeholder="Select a category…",
            min_values=1,
            max_values=1,
            options=options,
            disabled=(options[0].value == "__none__"),
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        key = self.values[0]
        if key == "__none__":
            return await interaction.response.send_message("ℹ️ No categories available.", ephemeral=True)

        cfg = await load_config()
        categories = cfg.get("categories", {}) or {}
        cat = categories.get(key)
        if not cat:
            return await interaction.response.send_message("❌ Category no longer exists.", ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        member_role_ids = {r.id for r in member.roles} if member else set()
        
        view = PublicSelfRolesView(
            categories,
            active_category=key,
            member_role_ids=member_role_ids,
        )
        await interaction.response.edit_message(embed=role_embed(cat), view=view)

class RoleSelect(discord.ui.Select):
    def __init__(
        self,
        category_key: str,
        category: dict,
        member_role_ids: Optional[set[int]] = None,
    ):
        self.category_key = category_key
        member_role_ids = member_role_ids or set()

        options: List[discord.SelectOption] = []
        for rid, meta in list((category.get("roles") or {}).items())[:25]:
            rid_int = int(rid)
            options.append(
                discord.SelectOption(
                    label=(meta.get("label") or rid)[:100],
                    value=str(rid),
                    emoji=parse_emoji(meta.get("emoji")),
                    default=(rid_int in member_role_ids),  # ⭐ THIS is the key line
                )
            )

        multi = bool(category.get("multi_select", True))
        max_vals = len(options) if multi else 1
        max_vals = max(max_vals, 1)

        super().__init__(
            placeholder="Select your roles…",
            min_values=0,
            max_values=max_vals,
            options=options if options else [
                discord.SelectOption(label="No roles", value="__none__")
            ],
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            return

        # ✅ defer so we can both reply + edit the message cleanly
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return await interaction.followup.send("❌ Member missing.", ephemeral=True)

        cfg = await load_config()
        cats = cfg.get("categories", {}) or {}
        cat = cats.get(self.category_key)
        if not cat:
            return await interaction.followup.send("❌ Category missing.", ephemeral=True)

        me = guild_me(interaction.guild)
        if not me:
            return await interaction.followup.send("❌ Bot member missing.", ephemeral=True)

        valid_ids = {int(r) for r in (cat.get("roles") or {}) if str(r).isdigit()}
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

            if rid not in selected and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Self-role")
                    removed.append(role)
                except Exception:
                    pass

        # ✅ send ephemeral feedback
        lines = ["✨ **Your roles have been updated**"]
        if added:
            lines.append("✅ Added: " + ", ".join(r.mention for r in added))
        if removed:
            lines.append("❌ Removed: " + ", ".join(r.mention for r in removed))
        if not added and not removed:
            lines.append("ℹ️ No changes made.")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

        # ✅ Reset the original menu message back to the main view (no role chips shown)
        try:
            cfg2 = await load_config()
            categories2 = cfg2.get("categories", {}) or {}
            await interaction.message.edit(
                embed=public_embed(),
                view=PublicSelfRolesView(categories2),
            )
        except Exception:
            pass
                
class BackToMainButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="⬅️ Back",
            style=discord.ButtonStyle.secondary,
            custom_id="sr_back_main",
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = await load_config()
        categories = cfg.get("categories", {}) or {}
        await interaction.response.edit_message(
            embed=public_embed(),
            view=PublicSelfRolesView(categories),
        )                    
    
##requests##

class RequestRoleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Request Custom Role",
            style=discord.ButtonStyle.success,
            custom_id="sr_request_role",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RoleRequestModal())

class PublicSelfRolesView(discord.ui.View):
    def __init__(
        self,
        categories: Dict[str, Any],
        active_category: Optional[str] = None,
        member_role_ids: Optional[set[int]] = None,
    ):
        super().__init__(timeout=None)

        # 1️⃣ Category dropdown always first
        self.add_item(CategorySelect(categories, selected=active_category))

        # 2️⃣ Role selector (only when inside a category)
        if active_category and active_category in categories:
            cat = categories[active_category]
            if cat.get("roles"):
                self.add_item(
                    RoleSelect(
                        active_category,
                        cat,
                        member_role_ids=member_role_ids,
                    )
                )

                # ⬅ Back button ONLY when viewing a category
                self.add_item(BackToMainButton())

        # 3️⃣ Green request button ALWAYS LAST
        self.add_item(RequestRoleButton())
# =========================================================
# DEPLOY / UPDATE PUBLIC MENU
# =========================================================

async def deploy_or_update_menu(guild: discord.Guild) -> str:
    cfg = await load_config(force=True)
    categories = cfg.get("categories", {}) or {}

    cid = cfg.get("selfroles_channel_id")
    if not cid:
        return "❌ Self-roles channel not set."

    ch = guild.get_channel(int(cid))
    if not isinstance(ch, discord.TextChannel):
        return "❌ Invalid self-roles channel."

    embed = public_embed()
    view = PublicSelfRolesView(categories)

    mid = cfg.get("selfroles_message_id")
    if mid:
        try:
            msg = await ch.fetch_message(int(mid))
            await msg.edit(embed=embed, view=view)
            return "✅ Updated self-role menu."
        except Exception:
            pass

    sent = await ch.send(embed=embed, view=view)
    cfg["selfroles_message_id"] = sent.id
    await save_config(cfg)
    return "✅ Posted self-role menu."

# =========================================================
# ADMIN: CHANNEL PICKERS
# =========================================================

class SetSelfRolesChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.sel = discord.ui.ChannelSelect(
            placeholder="Select self-roles channel",
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
            placeholder="Select log channel",
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

##requests##
class SetRequestsChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.sel = discord.ui.ChannelSelect(
            placeholder="Select requests channel",
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
        cfg["requests_channel_id"] = channel.id
        await save_config(cfg)

        await interaction.followup.send(f"📝 Requests channel set to {channel.mention}", ephemeral=True)

class RoleRequestModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Request Custom Role")

        self.role_type = discord.ui.TextInput(
            label="Role Type",
            required=True,
            max_length=20,
            placeholder="Game Ping/Cosmetic",
        )
        self.role_name = discord.ui.TextInput(
            label="Role Name",
            required=True,
            max_length=80,
            placeholder="e.g. Deathnote",
        )
        self.colour = discord.ui.TextInput(
            label="Colour (Cosmetic)",
            required=False,
            max_length=30,
            placeholder="e.g. #FF69B4 or 'pink'",
        )
        self.icon = discord.ui.TextInput(
            label="Icon (Cosmetic)",
            required=False,
            max_length=80,
            placeholder="e.g. 🩷 or advise custom",
        )

        self.add_item(self.role_type)
        self.add_item(self.role_name)
        self.add_item(self.colour)
        self.add_item(self.icon)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            return await interaction.followup.send("❌ This only works in a server.", ephemeral=True)

        rt = self.role_type.value.strip().lower()
        rn = self.role_name.value.strip()
        colour = self.colour.value.strip()
        icon = self.icon.value.strip()

        # normalise role type
        if rt in ("gameping", "ping", "game"):
            rt = "game ping"

        if rt not in ("game ping", "cosmetic"):
            return await interaction.followup.send("❌ Role Type must be **Game Ping** or **Cosmetic**.", ephemeral=True)

        if not rn:
            return await interaction.followup.send("❌ Role Name is required.", ephemeral=True)

        is_cosmetic = (rt == "cosmetic")

# ✅ add this right here
        if not is_cosmetic:
            colour = ""
            icon = ""
    
        if is_cosmetic and not colour:
            return await interaction.followup.send("❌ Colour is required for **Cosmetic** roles.", ephemeral=True)

        cfg = await load_config()
        req_cid = cfg.get("requests_channel_id")
        if not req_cid:
            return await interaction.followup.send("❌ Requests channel not set yet (use /rolesettings).", ephemeral=True)

        ch = interaction.guild.get_channel(int(req_cid))
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("❌ Requests channel is missing / not a text channel.", ephemeral=True)

        emb = discord.Embed(title="📝 Custom Role Request", color=discord.Color.blurple())
        emb.add_field(name="Requester", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        emb.add_field(name="Type", value=("Cosmetic" if is_cosmetic else "Game Ping"), inline=True)
        emb.add_field(name="Name", value=rn, inline=True)

        if is_cosmetic:
            emb.add_field(name="Colour", value=(colour or "—"), inline=True)
            emb.add_field(name="Icon", value=(icon or "—"), inline=True)

        msg = await ch.send(embed=emb, view=RequestCompleteView())

        # Persist request by message id so the complete button works after restart
        cfg = await load_config()
        reqs = cfg.get("role_requests", {}) or {}
        reqs[str(msg.id)] = {
            "user_id": interaction.user.id,
            "role_type": rt,
            "role_name": rn,
            "colour": colour,
            "icon": icon,
        }
        cfg["role_requests"] = reqs
        await save_config(cfg)

        # DM user
        try:
            await interaction.user.send(f"✅ Got it — your request for **{rn}** has been received.")
        except Exception:
            pass

        await interaction.followup.send("✅ Submitted! Check your DMs ✨", ephemeral=True)
# =========================================================
# ADMIN: CATEGORY MODAL
# (labels must be 1..45 chars -> fixed)
# =========================================================

class CategoryModal(discord.ui.Modal):
    def __init__(self, mode: str, existing_key: Optional[str] = None, existing: Optional[Dict[str, Any]] = None):
        super().__init__(title="Category Settings")
        self.mode = mode
        self.existing_key = existing_key
        existing = existing or {}

        self.key_in = discord.ui.TextInput(
            label="Category key",
            required=True,
            max_length=50,
            default=existing_key or "",
        )
        self.title_in = discord.ui.TextInput(
            label="Title",
            required=True,
            max_length=150,
            default=str(existing.get("title") or ""),
        )
        self.desc_in = discord.ui.TextInput(
            label="Description (optional)",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=500,
            default=str(existing.get("description") or ""),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji (optional)",
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
        self.add_item(self.desc_in)
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
            return await interaction.followup.send("❌ Invalid emoji format.", ephemeral=True)

        multi_raw = self.multi_in.value.strip().lower()
        multi = multi_raw in ("yes", "y", "true", "1", "on")

        if self.mode == "add":
            if key in cats:
                return await interaction.followup.send("❌ That key already exists.", ephemeral=True)
            cats[key] = {
                "title": self.title_in.value.strip(),
                "description": self.desc_in.value.strip(),
                "emoji": emoji_raw or None,
                "multi_select": multi,
                "roles": {},
            }
        else:
            if not self.existing_key or self.existing_key not in cats:
                return await interaction.followup.send("❌ Category missing.", ephemeral=True)

            if key != self.existing_key:
                if key in cats:
                    return await interaction.followup.send("❌ New key exists already.", ephemeral=True)
                cats[key] = cats.pop(self.existing_key)

            cats[key].setdefault("roles", {})
            cats[key]["title"] = self.title_in.value.strip()
            cats[key]["description"] = self.desc_in.value.strip()
            cats[key]["emoji"] = emoji_raw or None
            cats[key]["multi_select"] = multi

        cfg["categories"] = cats
        await save_config(cfg)

        await interaction.followup.send("✅ Category saved.", ephemeral=True)

# =========================================================
# ADMIN: CATEGORY MANAGER
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

class CategoryManagerView(discord.ui.View):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cfg_snapshot = ensure_shape(dict(cfg))
        self.selected: Optional[str] = None

        self.sel = CategoryPicker("Select category…", self.cfg_snapshot)
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
        # modal must be first response
        await interaction.response.send_modal(CategoryModal("add"))

    @discord.ui.button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary)
    async def edit_cat(self, interaction: discord.Interaction, _: discord.ui.Button):
        # modal must be first response
        if not self.selected:
            return await interaction.response.send_message("❌ Select a category first.", ephemeral=True)

        cat = (self.cfg_snapshot.get("categories") or {}).get(self.selected)
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
# ADMIN: ROLE META MODAL (labels <=45 chars fixed)
# =========================================================

class RoleMetaModal(discord.ui.Modal):
    def __init__(self, category_key: str, role_id: int, meta: Dict[str, Any]):
        super().__init__(title="Role Display")
        self.category_key = category_key
        self.role_id = role_id

        self.label_in = discord.ui.TextInput(
            label="Label",
            required=True,
            max_length=100,
            default=str(meta.get("label") or ""),
        )
        self.emoji_in = discord.ui.TextInput(
            label="Emoji (optional)",
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
        await interaction.followup.send("✅ Role updated.", ephemeral=True)

# =========================================================
# ADMIN: ROLES IN CATEGORIES
# =========================================================

class RolesCategoryManagerView(discord.ui.View):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(timeout=300)
        self.cfg_snapshot = ensure_shape(dict(cfg))
        self.category_key: Optional[str] = None

        self.sel = CategoryPicker("Select category…", self.cfg_snapshot)
        self.sel.callback = self.pick_category  # type: ignore
        self.add_item(self.sel)

    async def pick_category(self, interaction: discord.Interaction):
        v = self.sel.values[0]
        if v == "__none__":
            self.category_key = None
            return await interaction.response.send_message("ℹ️ No categories yet.", ephemeral=True)

        self.category_key = v
        await interaction.response.send_message(f"✅ Selected `{v}`", ephemeral=True)

    @discord.ui.button(label="➕ Add Roles", style=discord.ButtonStyle.success)
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
            await i.response.defer(ephemeral=True)

            cfg = await load_config()
            cat = (cfg.get("categories") or {}).get(self.category_key)
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
            await save_config(cfg)

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

        sel = discord.ui.Select(placeholder="Pick role to remove", min_values=1, max_values=1, options=options)

        async def picked(i: discord.Interaction):
            await i.response.defer(ephemeral=True)

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

    @discord.ui.button(label="😀 Edit Label/Emoji", style=discord.ButtonStyle.primary)
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

        sel = discord.ui.Select(placeholder="Pick role to edit", min_values=1, max_values=1, options=options)

        async def picked(i: discord.Interaction):
            # opening a modal -> DO NOT defer
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
# ADMIN: LOGGING VIEW
# =========================================================

class LoggingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔁 Toggle Logging", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

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
        await interaction.response.defer(ephemeral=True)

        cfg = await load_config()
        cfg["logging"]["channel_id"] = None
        await save_config(cfg)

        await interaction.followup.send("✅ Log channel cleared.", ephemeral=True)

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

        view = discord.ui.View(timeout=180)
        rs = discord.ui.RoleSelect(placeholder="Pick an auto-role", min_values=1, max_values=1)

        async def on_pick(i: discord.Interaction):
            await i.response.defer(ephemeral=True)
            role = rs.values[0]

            if not role_manageable(role, me):
                return await i.followup.send("❌ Role not manageable.", ephemeral=True)

            cfg = await load_config()
            arr = (cfg.get("auto_roles") or {}).get(target, [])
            rid = str(role.id)
            if rid not in arr:
                arr.append(rid)
            cfg["auto_roles"][target] = arr
            await save_config(cfg)

            await i.followup.send(f"✅ Added {role.mention} to auto-roles ({target}).", ephemeral=True)

        rs.callback = on_pick  # type: ignore
        view.add_item(rs)
        await interaction.response.send_message("Pick a role:", view=view, ephemeral=True)

    async def _remove(self, interaction: discord.Interaction, target: str):
        cfg = await load_config()
        arr = (cfg.get("auto_roles") or {}).get(target, [])
        if not arr:
            return await interaction.response.send_message("ℹ️ None set.", ephemeral=True)

        options: List[discord.SelectOption] = []
        for rid in arr[:25]:
            role = interaction.guild.get_role(int(rid)) if interaction.guild else None
            options.append(discord.SelectOption(label=(role.name if role else str(rid))[:100], value=str(rid)))

        sel = discord.ui.Select(placeholder="Pick one to remove", min_values=1, max_values=1, options=options)

        async def on_remove(i: discord.Interaction):
            await i.response.defer(ephemeral=True)
            rid = sel.values[0]

            cfg2 = await load_config()
            arr2 = (cfg2.get("auto_roles") or {}).get(target, [])
            if rid in arr2:
                arr2.remove(rid)
            cfg2["auto_roles"][target] = arr2
            await save_config(cfg2)

            await i.followup.send("✅ Removed.", ephemeral=True)

        sel.callback = on_remove  # type: ignore
        view = discord.ui.View(timeout=180)
        view.add_item(sel)
        await interaction.response.send_message("Pick one:", view=view, ephemeral=True)

# =========================================================
# ADMIN: USER ROLE MANAGEMENT
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
            await interaction.response.send_message("Pick a role:", view=PickRoleAssignView(uid), ephemeral=True)
        else:
            view = PickRoleRemoveView(uid)
            await view.populate(interaction.guild)
            await interaction.response.send_message("Pick a role:", view=view, ephemeral=True)

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
            return await interaction.response.send_message("❌ Role not manageable.", ephemeral=True)

        if role in member.roles:
            return await interaction.response.send_message("ℹ️ Already has that role.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Admin assign by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed (permissions).", ephemeral=True)

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

    async def populate(self, guild: Optional[discord.Guild]):
        if not guild:
            self.sel.options = [discord.SelectOption(label="(Not available)", value="__none__", default=True)]
            return

        member = guild.get_member(self.user_id)
        me = guild_me(guild)
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
            return await interaction.response.send_message("❌ Role not manageable.", ephemeral=True)

        if role not in member.roles:
            return await interaction.response.send_message("ℹ️ They don’t have that role.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Admin remove by {interaction.user}")
        except Exception:
            return await interaction.response.send_message("❌ Failed (permissions).", ephemeral=True)

        await interaction.response.send_message(f"✅ Removed {role.mention} from {member.mention}", ephemeral=True)

        emb = discord.Embed(title="🛂 Role Removed", color=discord.Color.red())
        emb.add_field(name="Admin", value=interaction.user.mention, inline=False)
        emb.add_field(name="User", value=member.mention, inline=False)
        emb.add_field(name="Role", value=role.mention, inline=False)
        await send_log(interaction.guild, emb)

##requests##
class RequestCompleteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ℹ️ Instructions",
        style=discord.ButtonStyle.secondary,
        custom_id="sr_req_help",
    )
    async def help(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild:
            return

        # Optional: gate to admins only (same as completion)
        if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        cfg = await load_config()
        text = (cfg.get("role_request_instructions") or "").strip()

        if not text:
            text = "Add your instructions in config: `role_request_instructions`"

        emb = discord.Embed(title="🧾 Role Request Instructions", description=text, color=discord.Color.blurple())
        await interaction.response.send_message(embed=emb, ephemeral=True)
    
    @discord.ui.button(
        label="✅ Mark Completed",
        style=discord.ButtonStyle.success,
        custom_id="sr_req_done",  # fixed id = persistent across restarts
    )
    async def done(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild or not interaction.message:
            return

        # gate completion to admins (same permission style as rolesettings)
        if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        cfg = await load_config()
        reqs = cfg.get("role_requests", {}) or {}
        msg_id = str(interaction.message.id)
        req = reqs.get(msg_id)

        if not req:
            return await interaction.followup.send("❌ I can’t find this request in storage.", ephemeral=True)

        user_id = int(req.get("user_id"))
        role_name = str(req.get("role_name") or "your role request")

        # DM requester
        user = interaction.client.get_user(user_id)
        if not user:
            try:
                user = await interaction.client.fetch_user(user_id)
            except Exception:
                user = None

        if user:
            try:
                await user.send(f"✅ Your request for **{role_name}** has been marked complete. Visit #self-roles to assign the role.")
            except Exception:
                pass

        # Update the request message embed to show completed
        try:
            emb = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="📝 Custom Role Request")
            emb.color = discord.Color.green()
            # remove old Status field if it exists
            new_fields = [f for f in emb.fields if f.name.lower() != "status"]
            emb.clear_fields()
            for f in new_fields:
                emb.add_field(name=f.name, value=f.value, inline=f.inline)
            
            emb.add_field(name="Status", value=f"✅ Completed by {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=emb, view=self)
        except Exception:
            pass
        
        reqs.pop(msg_id, None)
        cfg["role_requests"] = reqs
        await save_config(cfg)
        
        await interaction.followup.send("✅ Marked complete + DM sent.", ephemeral=True)
        
# =========================================================
# ADMIN DASHBOARD + COMMAND
# =========================================================

class RoleSettingsDashboard(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📍 Self-Roles Channel", style=discord.ButtonStyle.primary)
    async def set_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Select the self-roles channel:", view=SetSelfRolesChannelView(), ephemeral=True)

    @discord.ui.button(label="📌 Post / Update Menu", style=discord.ButtonStyle.success)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        msg = await deploy_or_update_menu(interaction.guild)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="📂 Categories", style=discord.ButtonStyle.secondary)
    async def cats(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await load_config()
        await interaction.response.send_message("Category manager:", view=CategoryManagerView(cfg), ephemeral=True)

    @discord.ui.button(label="🎭 Roles in Categories", style=discord.ButtonStyle.secondary)
    async def roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await load_config()
        await interaction.response.send_message("Role manager:", view=RolesCategoryManagerView(cfg), ephemeral=True)

    @discord.ui.button(label="👥 Auto Roles", style=discord.ButtonStyle.secondary)
    async def autoroles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("Auto-roles:", view=AutoRolesView(), ephemeral=True)

    @discord.ui.button(label="🧾 Logging", style=discord.ButtonStyle.secondary)
    async def logging(self, interaction: discord.Interaction, _: discord.ui.Button):
        cfg = await load_config()
        state = "ON" if cfg.get("logging", {}).get("enabled") else "OFF"
        chan = cfg.get("logging", {}).get("channel_id")
        await interaction.response.send_message(
            f"Logging is **{state}** | Channel: {_fmt_chan(chan)}",
            view=LoggingView(),
            ephemeral=True,
        )

    @discord.ui.button(label="🛂 Admin Assign Roles", style=discord.ButtonStyle.primary)
    async def admin_roles(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("User role management:", view=AdminUserRoleView(), ephemeral=True)

    @discord.ui.button(label="📝 Requests Channel", style=discord.ButtonStyle.secondary)
    async def requests_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Select the requests channel:",
            view=SetRequestsChannelView(),
            ephemeral=True,
        )

@app_commands.command(name="rolesettings", description="Admin panel for self-roles + role tools")
async def rolesettings(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_global_access(interaction.user):
        return await interaction.response.send_message("❌ You do not have permission.", ephemeral=True)

    cfg = await load_config()

    ch = cfg.get("selfroles_channel_id")
    mid = cfg.get("selfroles_message_id")

    lg = cfg.get("logging") or {}
    log_state = "ON" if lg.get("enabled") else "OFF"
    log_chan = lg.get("channel_id")
    req_chan = cfg.get("requests_channel_id")
    

    desc = [
        f"📍 **Self-roles channel:** {_fmt_chan(ch)}",
        f"📌 **Menu posted:** {'Yes' if mid else 'No'}",
        f"🧾 **Logging:** {log_state}",
    ]
    if log_chan:
        desc.append(f"🧾 **Log channel:** {_fmt_chan(log_chan)}")

    if req_chan:
        desc.append(f"📝 **Requests channel:** {_fmt_chan(req_chan)}")

    embed = discord.Embed(
        title="⚙️ Role Settings",
        description="\n".join(desc),
        color=discord.Color.blurple(),
    )

    await interaction.response.send_message(embed=embed, view=RoleSettingsDashboard(), ephemeral=True)

# =========================================================
# SETUP
# =========================================================

_MENU_REFRESH_STARTED = False

async def _refresh_menus_when_ready(client: discord.Client):
    await client.wait_until_ready()
    await asyncio.sleep(1)

    for guild in client.guilds:
        try:
            await deploy_or_update_menu(guild)
        except Exception:
            pass

def setup(tree: app_commands.CommandTree, client: discord.Client):
    tree.add_command(rolesettings)

    # ✅ persistent request buttons
    try:
        client.add_view(RequestCompleteView())
    except Exception:
        pass

    # 🔁 auto-refresh the public self-roles menu after restart
    global _MENU_REFRESH_STARTED
    if not _MENU_REFRESH_STARTED:
        _MENU_REFRESH_STARTED = True
        client.loop.create_task(_refresh_menus_when_ready(client))

    return