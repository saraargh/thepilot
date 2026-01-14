# bot_warnings.py
import os
import json
import base64
import requests
import discord
import random
from discord import app_commands
from datetime import datetime
from typing import List, Optional, Literal, Tuple

from permissions import has_app_access

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "saraargh/the-pilot")
GITHUB_FILE_PATH = "warnings.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

# ------------------- Roles (logic roles, not permissions) -------------------
PASSENGERS_ROLE_ID = 1404100554807971971
WILLIAM_ROLE_ID = 1413545658006110401
SAZZLES_ROLE_ID = 1404104881098195015
KD_ROLE_ID = 1420817462290681936  # KD can warn Sazzles (RESTRICTED ONLY)

# ------------------- Default JSON structure -------------------
DEFAULT_DATA = {
    "warnings": {},
    "blocked_warners": [],   # user IDs blocked from warning
    "ffa_enabled": False,    # False=restricted, True=free_for_all
    "last_reset": None,
    "extra_var": None
}

# ------------------- Helpers -------------------
def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def _gh_url():
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

def _chunk(items: List[str], size: int) -> List[List[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]

def _page_label(i: int, per_page: int, total: int) -> str:
    start = i * per_page + 1
    end = min((i + 1) * per_page, total)
    return f"Page {i+1} ({start}–{end})"

async def reply(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = False,
):
    # Build kwargs without ever including view=None/embed=None/content=None
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    kwargs["ephemeral"] = ephemeral

    # Use followup if already acknowledged
    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)
    return await interaction.response.send_message(**kwargs)


# ------------------- GitHub Load / Save -------------------
def load_data() -> Tuple[dict, Optional[str]]:
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            data = json.loads(raw) if raw.strip() else DEFAULT_DATA.copy()

            data.setdefault("warnings", {})
            data.setdefault("blocked_warners", [])
            data.setdefault("ffa_enabled", False)
            data.setdefault("last_reset", None)
            data.setdefault("extra_var", None)

            return data, content.get("sha")

        if r.status_code == 404:
            sha = save_data(DEFAULT_DATA.copy(), sha=None)
            return DEFAULT_DATA.copy(), sha

        sha = save_data(DEFAULT_DATA.copy(), sha=None)
        return DEFAULT_DATA.copy(), sha

    except Exception:
        sha = save_data(DEFAULT_DATA.copy(), sha=None)
        return DEFAULT_DATA.copy(), sha

def save_data(data: dict, sha: Optional[str] = None) -> Optional[str]:
    payload = {
        "message": "Update warnings.json",
        "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode()
    }
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload), timeout=10)

        if r.status_code in (200, 201):
            return r.json().get("content", {}).get("sha")

        # stale sha -> 409 (retry once with fresh sha)
        if r.status_code == 409:
            _, fresh_sha = load_data()
            payload["sha"] = fresh_sha
            r2 = requests.put(_gh_url(), headers=HEADERS, data=json.dumps(payload), timeout=10)
            if r2.status_code in (200, 201):
                return r2.json().get("content", {}).get("sha")

    except Exception:
        pass

    return sha

# ------------------- Warning Operations -------------------
def add_warning(user_id: int, reason: str | None = None) -> int:
    data, sha = load_data()
    uid = str(user_id)

    if uid not in data["warnings"]:
        data["warnings"][uid] = []

    data["warnings"][uid].append(reason or "No reason provided")
    save_data(data, sha)
    return len(data["warnings"][uid])

def get_warnings(user_id: int) -> List[str]:
    data, _ = load_data()
    return data["warnings"].get(str(user_id), [])

def get_all_warnings() -> dict:
    data, _ = load_data()
    return data["warnings"]

# ------------------- Dropdown Pagination -------------------
class PageSelect(discord.ui.Select):
    def __init__(self, parent_view: "PagedEmbedView"):
        self.parent_view = parent_view
        options = []
        for i in range(len(parent_view.embeds)):
            options.append(
                discord.SelectOption(
                    label=_page_label(i, parent_view.per_page, parent_view.total_items),
                    value=str(i)
                )
            )
        super().__init__(
            placeholder="Select a page…",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.index = int(self.values[0])
        await interaction.response.edit_message(
            embed=self.parent_view.embeds[self.parent_view.index],
            view=self.parent_view
        )

class PagedEmbedView(discord.ui.View):
    def __init__(self, embeds: List[discord.Embed], per_page: int, total_items: int):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.index = 0
        self.per_page = per_page
        self.total_items = total_items
        self.add_item(PageSelect(self))

# ------------------- Embed Builders -------------------
def build_warnings_list_embeds(target: discord.Member, warns: List[str], per_page: int = 10) -> List[discord.Embed]:
    lines = [f"**{i+1}.** {w}" for i, w in enumerate(warns)]
    pages = _chunk(lines, per_page) if lines else [[]]
    embeds: List[discord.Embed] = []
    for i, chunk_lines in enumerate(pages):
        e = discord.Embed(title=f"⚠️ Warnings for {target.display_name}")
        e.description = "\n".join(chunk_lines) if chunk_lines else "No warnings."
        e.set_footer(text=f"Page {i+1}/{len(pages)}")
        embeds.append(e)
    return embeds

def build_server_warnings_embeds(interaction: discord.Interaction, per_page: int = 10) -> Tuple[List[discord.Embed], int]:
    all_warns = get_all_warnings()

    rows: List[Tuple[str, int]] = []
    for uid, warns in all_warns.items():
        member = interaction.guild.get_member(int(uid))
        if member:
            rows.append((member.display_name, len(warns)))

    rows.sort(key=lambda x: x[1], reverse=True)  # most -> least
    total_items = len(rows)

    lines = [f"**{i+1}.** {name} — **{count}**" for i, (name, count) in enumerate(rows)]
    pages = _chunk(lines, per_page) if lines else [[]]

    embeds: List[discord.Embed] = []
    for i, chunk_lines in enumerate(pages):
        e = discord.Embed(title="📋 Server Warnings")
        e.description = "\n".join(chunk_lines) if chunk_lines else "No warnings found for this server."
        e.set_footer(text=f"Page {i+1}/{len(pages)}")
        embeds.append(e)

    return embeds, total_items

# ------------------- Command Setup -------------------
def setup_warnings_commands(tree: app_commands.CommandTree):

    # ---------------- /warningsmode ----------------
    @tree.command(name="warningsmode", description="Set how warnings work on this server.")
    @app_commands.describe(mode="restricted = fun rules, free_for_all = anyone can warn anyone")
    async def warningsmode(interaction: discord.Interaction, mode: Literal["restricted", "free_for_all"]):
        if not has_app_access(interaction.user, "warnings"):
            await reply(interaction, "❌ You do not have permission to change warning mode.", ephemeral=False)
            return

        data, sha = load_data()

        if mode == "free_for_all":
            data["ffa_enabled"] = True
            save_data(data, sha)
            await reply(interaction, "🔓 **Warnings free for all enabled** - Anyone can warn anyone.", ephemeral=False)
        else:
            data["ffa_enabled"] = False
            save_data(data, sha)
            await reply(interaction, "🔒 **Warning restrictions enabled**", ephemeral=False)

    # ---------------- /block_warner ----------------
    @tree.command(name="block_warner", description="Stop a user from being allowed to warn.")
    async def block_warner(interaction: discord.Interaction, member: discord.Member):
        if not has_app_access(interaction.user, "warnings"):
            await reply(interaction, "❌ You do not have permission to block warners.", ephemeral=False)
            return

        data, sha = load_data()
        data.setdefault("blocked_warners", [])

        if member.id not in data["blocked_warners"]:
            data["blocked_warners"].append(member.id)
            save_data(data, sha)

        await reply(interaction, f"🚫 {member.mention} is no longer allowed to warn people.", ephemeral=False)

    # ---------------- /unblock_warner ----------------
    @tree.command(name="unblock_warner", description="Allow a user to warn again.")
    async def unblock_warner(interaction: discord.Interaction, member: discord.Member):
        if not has_app_access(interaction.user, "warnings"):
            await reply(interaction, "❌ You do not have permission to unblock warners.", ephemeral=False)
            return

        data, sha = load_data()
        data.setdefault("blocked_warners", [])

        if member.id in data["blocked_warners"]:
            data["blocked_warners"].remove(member.id)
            save_data(data, sha)

        await reply(interaction, f"✅ {member.mention} can warn again.", ephemeral=False)

    # ---------------- /warn ----------------
    @tree.command(name="warn", description="Warn a user (joke warnings).")
    @app_commands.describe(member="Member to warn", reason="Reason (optional)")
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = None):

        author = interaction.user
        author_roles = {r.id for r in author.roles}
        target_roles = {r.id for r in member.roles}

        data, _ = load_data()
        ffa_enabled = bool(data.get("ffa_enabled", False))

        # 🚫 BLOCKED WARNER (applies in all modes)
        if author.id in data.get("blocked_warners", []):
            await reply(interaction, f"❌ {author.mention} is no longer allowed to warn people.", ephemeral=False)
            return

        # 🤡 SELF-WARN RULE (applies in all modes)
        if member.id == author.id:
            candidates = [
                m for m in interaction.guild.members
                if not m.bot
                and m.id != author.id
                and SAZZLES_ROLE_ID not in [r.id for r in m.roles]
            ]

            if not candidates:
                await reply(interaction, "🤡 You tried to warn yourself but there was no one else to punish.", ephemeral=False)
                return

            chosen = random.choice(candidates)

            reason_text = f"{author.mention} couldn’t warn themselves, so the pilot gave it to {chosen.mention}"
            add_warning(chosen.id, reason_text)

            await reply(
                interaction,
                f"🤡 {author.mention} You cannot warn yourself, instead a warning has been given to {chosen.mention}!",
                ephemeral=False
            )
            return

        # ---------------- SAZZLES protection (RESTRICTED ONLY) ----------------
        if not ffa_enabled and (SAZZLES_ROLE_ID in target_roles):
            if KD_ROLE_ID not in author_roles:
                await reply(
                    interaction,
                    "❌ Only Mr KD can warn this user because she is too pretty and nice to be warned and made this so you can all warn William!",
                    ephemeral=False
                )
                return
            # KD allowed → continue

        # ---------------- FREE FOR ALL MODE ----------------
        if ffa_enabled:
            count = add_warning(member.id, reason)
            msg = f"⚠️ {member.mention} was warned"
            if reason:
                msg += f" for {reason}"
            msg += f", this is their {ordinal(count)} warning."
            await reply(interaction, msg, ephemeral=False)
            return

        # ---------------- RESTRICTED MODE (existing fun rules) ----------------

        # PASSENGER → WILLIAM allowed
        if PASSENGERS_ROLE_ID in author_roles and WILLIAM_ROLE_ID in target_roles:
            count = add_warning(member.id, reason)
            msg = f"⚠️ {member.mention} was warned"
            if reason:
                msg += f" for {reason}"
            msg += f", this is their {ordinal(count)} warning."
            await reply(interaction, msg, ephemeral=False)
            return

        # Permission check for restricted mode
        if not has_app_access(author, "warnings"):

            # Passenger punishment (NOT William)
            if PASSENGERS_ROLE_ID in author_roles:
                reason_text = f"Trying to warn {member.mention}"
                count = add_warning(author.id, reason_text)

                await reply(
                    interaction,
                    f"❌ {author.mention} has been warned for trying to warn {member.mention}, "
                    f"as you cannot warn your fellow passengers — only William. "
                    f"This is their {ordinal(count)} warning.",
                    ephemeral=False
                )
                return

            await reply(interaction, f"❌ You do not have permission to warn {member.mention}.", ephemeral=False)
            return

        # Normal restricted-mode warn (allowed roles)
        count = add_warning(member.id, reason)
        msg = f"⚠️ {member.mention} was warned"
        if reason:
            msg += f" for {reason}"
        msg += f", this is their {ordinal(count)} warning."
        await reply(interaction, msg, ephemeral=False)

    # ---------------- /warnings_list (member optional = self) ----------------
    @tree.command(name="warnings_list", description="List warnings (yourself or another user).")
    @app_commands.describe(member="Member to see warnings for (optional)")
    async def warnings_list(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        warns = get_warnings(target.id)

        embeds = build_warnings_list_embeds(target, warns, per_page=10)
        view = PagedEmbedView(embeds, per_page=10, total_items=len(warns))
        await reply(interaction, embed=embeds[0], view=view, ephemeral=False)

    # ---------------- /server_warnings (embed + dropdown pages) ----------------
    @tree.command(name="server_warnings", description="Show all warnings on this server (counts only).")
    async def server_warnings(interaction: discord.Interaction):
        embeds, total_items = build_server_warnings_embeds(interaction, per_page=10)
        view = PagedEmbedView(embeds, per_page=10, total_items=total_items)
        await reply(interaction, embed=embeds[0], view=view, ephemeral=False)

    # ---------------- /clear_warnings ----------------
    @tree.command(name="clear_warnings", description="Clear all warnings for a user.")
    @app_commands.describe(member="Member to clear warnings for")
    async def clear_warnings(interaction: discord.Interaction, member: discord.Member):

        if not has_app_access(interaction.user, "warnings"):
            await reply(interaction, "❌ You do not have permission to clear warnings.", ephemeral=False)
            return

        if member.id == interaction.user.id:
            reason_text = "Trying to remove their warnings"
            count = add_warning(interaction.user.id, reason_text)

            await reply(
                interaction,
                f"❌ You can not clear your own warnings. {interaction.user.mention} has now been warned. "
                f"This is their {ordinal(count)} warning.",
                ephemeral=False
            )
            return

        data, sha = load_data()
        uid = str(member.id)

        if uid in data["warnings"]:
            data["warnings"].pop(uid)
            data["last_reset"] = datetime.utcnow().isoformat()
            save_data(data, sha)
            await reply(interaction, f"✅ All warnings for {member.mention} have been cleared.", ephemeral=False)
        else:
            await reply(interaction, f"{member.mention} has no warnings to clear.", ephemeral=False)

    # ---------------- /clear_server_warnings ----------------
    @tree.command(name="clear_server_warnings", description="Clear all warnings for the server.")
    async def clear_server_warnings(interaction: discord.Interaction):

        if not has_app_access(interaction.user, "warnings"):
            await reply(interaction, "❌ You do not have permission to clear server warnings.", ephemeral=False)
            return

        data, sha = load_data()
        guild_member_ids = {str(m.id) for m in interaction.guild.members}
        removed = 0

        for uid in list(data["warnings"].keys()):
            if uid in guild_member_ids:
                data["warnings"].pop(uid)
                removed += 1

        data["last_reset"] = datetime.utcnow().isoformat()
        save_data(data, sha)

        await reply(interaction, f"✅ Cleared {removed} warnings from the server.", ephemeral=False)