import discord
from discord import app_commands
from discord.ui import View, Button, Select, RoleSelect

from permissions import (
    has_global_access,
    load_settings,
    save_settings,
)

# =========================
# CONSTANTS
# =========================

SCOPES = {
    "global": "Global Admin",
    "mute": "Mute",
    "warnings": "Warnings",
    "poo_goat": "Poo / Goat",
    "welcome_leave": "Welcome / Leave",
}

# =========================
# MAIN PANEL VIEW
# =========================

class PilotSettingsView(View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.guild = guild
        self.mode = "main"
        self.page = 0
        self.scope = None
        self.render()

    # =========================
    # RENDERER
    # =========================

    def render(self):
        self.clear_items()

        if self.mode == "main":
            self.render_main()

        elif self.mode == "view_roles":
            self.render_view_roles()

        elif self.mode == "allowed_roles":
            self.render_allowed_roles()

        elif self.mode in ("welcome", "leave"):
            self.render_welcome_leave()

    # =========================
    # MAIN MENU
    # =========================

    def render_main(self):
        self.add_item(Button(
            label="Allowed Roles",
            style=discord.ButtonStyle.primary,
            custom_id="main_allowed"
        ))
        self.add_item(Button(
            label="View Roles",
            style=discord.ButtonStyle.secondary,
            custom_id="main_view"
        ))
        self.add_item(Button(
            label="Welcome / Leave Settings",
            style=discord.ButtonStyle.secondary,
            custom_id="main_welcome"
        ))

    # =========================
    # VIEW ROLES (PAGINATED)
    # =========================

    def render_view_roles(self):
        settings = load_settings()

        all_sections = []
        all_sections.append(
            ("🔐 Global Admin",
             settings.get("global_allowed_roles", []))
        )

        for key, label in SCOPES.items():
            if key == "global":
                continue
            roles = settings["apps"].get(key, {}).get("allowed_roles", [])
            all_sections.append((label, roles))

        per_page = 2
        pages = [
            all_sections[i:i + per_page]
            for i in range(0, len(all_sections), per_page)
        ]

        page = pages[self.page]

        embed = discord.Embed(
            title="🔍 Pilot Role Permissions",
            color=discord.Color.blurple()
        )

        for name, role_ids in page:
            mentions = [
                self.guild.get_role(r).mention
                for r in role_ids
                if self.guild.get_role(r)
            ]
            embed.add_field(
                name=name,
                value="\n".join(mentions) if mentions else "*None*",
                inline=False
            )

        embed.set_footer(
            text=f"Page {self.page+1}/{len(pages)} • Server owner & override role always have access"
        )

        self.embed = embed

        if self.page > 0:
            self.add_item(Button(
                label="◀ Prev",
                style=discord.ButtonStyle.secondary,
                custom_id="view_prev"
            ))

        if self.page < len(pages) - 1:
            self.add_item(Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                custom_id="view_next"
            ))

        self.add_item(Button(
            label="⬅ Back",
            style=discord.ButtonStyle.danger,
            custom_id="back_main"
        ))

    # =========================
    # ALLOWED ROLES
    # =========================

    def render_allowed_roles(self):
        options = [
            discord.SelectOption(label=v, value=k)
            for k, v in SCOPES.items()
        ]

        self.add_item(Select(
            placeholder="Select application",
            options=options,
            custom_id="scope_select"
        ))

        self.add_item(Button(
            label="⬅ Back",
            style=discord.ButtonStyle.danger,
            custom_id="back_main"
        ))

    # =========================
    # WELCOME / LEAVE TABS
    # =========================

    def render_welcome_leave(self):
        # Tabs (own row)
        self.add_item(Button(
            label="Welcome",
            style=discord.ButtonStyle.primary if self.mode == "welcome" else discord.ButtonStyle.danger,
            row=0,
            custom_id="tab_welcome"
        ))
        self.add_item(Button(
            label="Leave / Logs",
            style=discord.ButtonStyle.success if self.mode == "leave" else discord.ButtonStyle.danger,
            row=0,
            custom_id="tab_leave"
        ))

        # Content buttons (grey)
        if self.mode == "welcome":
            labels = [
                "Edit Title", "Edit Text",
                "Set Welcome Channel", "Add/Edit Channel Slot",
                "Add Image", "Toggle Bot Add Logs",
                "Set Bot Add Channel",
                "Preview", "Toggle Welcome On/Off"
            ]
        else:
            labels = [
                "Set Member Log Channel",
                "Toggle Leave Logs",
                "Toggle Kick Logs",
                "Toggle Ban Logs"
            ]

        row = 1
        col = 0
        for label in labels:
            self.add_item(Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                row=row,
                custom_id=f"wl_{label.lower().replace(' ', '_')}"
            ))
            col += 1
            if col == 2:
                col = 0
                row += 1

        self.add_item(Button(
            label="⬅ Back",
            style=discord.ButtonStyle.danger,
            row=row+1,
            custom_id="back_main"
        ))

    # =========================
    # INTERACTION HANDLER
    # =========================

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not has_global_access(interaction.user):
            await interaction.response.send_message("❌ No permission.")
            return False
        return True

    async def on_timeout(self):
        self.clear_items()

    async def interaction_handler(self, interaction: discord.Interaction):
        cid = interaction.data.get("custom_id")

        if cid == "main_allowed":
            self.mode = "allowed_roles"

        elif cid == "main_view":
            self.mode = "view_roles"
            self.page = 0

        elif cid == "main_welcome":
            self.mode = "welcome"

        elif cid == "view_prev":
            self.page -= 1

        elif cid == "view_next":
            self.page += 1

        elif cid == "tab_welcome":
            self.mode = "welcome"

        elif cid == "tab_leave":
            self.mode = "leave"

        elif cid == "back_main":
            self.mode = "main"

        self.render()

        if hasattr(self, "embed"):
            await interaction.response.edit_message(embed=self.embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

# =========================
# SLASH COMMAND
# =========================

def setup_admin_settings(tree: app_commands.CommandTree):

    @tree.command(name="pilotsettings", description="Open Pilot control panel")
    async def pilotsettings(interaction: discord.Interaction):
        if not has_global_access(interaction.user):
            return await interaction.response.send_message(
                "❌ You don’t have permission."
            )

        view = PilotSettingsView(interaction.guild)

        await interaction.response.send_message(
            content="⚙️ **Pilot Settings**",
            view=view
        )