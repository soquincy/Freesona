# utils/persona.py: Persona data layer, modals, and /setpersona command group.

import os
import json
import logging
from typing import Optional

import discord
from discord import ui, app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("FreesonaBot")

AI_PERSONA_PATH      = os.getenv("AI_PERSONA_FILE",    "/etc/secrets/persona.txt")
AI_PERSONA_JSON_PATH = os.getenv("AI_PERSONA_JSON_FILE", "/etc/secrets/persona.json")
PERSONAS_PATH        = os.getenv("AI_PERSONAS_FILE",   "/etc/secrets/personas.json")

PERSONA_FIELDS = [
    "core_personality",
    "background",
    "beliefs",
    "language",
    "system_instructions",
]

PERSONA_LABELS = {
    "core_personality":    "Core Personality & Traits",
    "background":          "Background & History",
    "beliefs":             "Beliefs, Likes & Dislikes",
    "language":            "Language & Communication Style",
    "system_instructions": "System Instructions",
}

ASSEMBLY_ORDER = [
    "system_instructions",
    "core_personality",
    "background",
    "beliefs",
    "language",
]

# ---------------------------------------------------------------------------
# Runtime state (module-level globals, mutated by modals and commands)
# ---------------------------------------------------------------------------

PERSONA_DATA:    dict = {}
CURRENT_PERSONA: str  = ""
PERSONA_LOCKED:  bool = False
LEGACY_DETECTED: bool = False

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def default_persona_json() -> dict:
    return {f: "" for f in PERSONA_FIELDS}


def load_persona_json() -> dict:
    if os.path.exists(AI_PERSONA_JSON_PATH):
        try:
            with open(AI_PERSONA_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for field_name in PERSONA_FIELDS:
                    if field_name not in data:
                        data[field_name] = ""
                return data
        except Exception as e:
            logger.error(f"Persona JSON load error: {e}")
    return default_persona_json()


def save_persona_json(data: dict):
    os.makedirs(
        os.path.dirname(AI_PERSONA_JSON_PATH) if os.path.dirname(AI_PERSONA_JSON_PATH) else ".",
        exist_ok=True
    )
    with open(AI_PERSONA_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def assemble_persona(data: dict) -> str:
    xml_tags = {
        "system_instructions": "system_instructions",
        "core_personality":    "role",
        "background":          "background",
        "beliefs":             "beliefs",
        "language":            "language",
    }
    parts = []
    for f in ASSEMBLY_ORDER:
        tag   = xml_tags[f]
        value = data.get(f, "").strip()
        if value:
            parts.append(f"<{tag}>\n{value}\n</{tag}>")
    return "\n\n".join(parts)


def load_legacy_persona() -> Optional[str]:
    if os.path.exists(AI_PERSONA_PATH):
        try:
            with open(AI_PERSONA_PATH, "r", encoding="utf-8") as f:
                data = f.read().strip()
                if data:
                    return data
        except Exception as e:
            logger.error(f"Legacy persona load error: {e}")
    return None


def load_profiles() -> dict:
    if os.path.exists(PERSONAS_PATH):
        try:
            with open(PERSONAS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_profiles(profiles: dict):
    os.makedirs(
        os.path.dirname(PERSONAS_PATH) if os.path.dirname(PERSONAS_PATH) else ".",
        exist_ok=True
    )
    with open(PERSONAS_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)


def init_persona():
    global PERSONA_DATA, CURRENT_PERSONA, LEGACY_DETECTED
    if os.path.exists(AI_PERSONA_JSON_PATH):
        PERSONA_DATA = load_persona_json()
        CURRENT_PERSONA = assemble_persona(PERSONA_DATA)
        LEGACY_DETECTED = False
    else:
        legacy = load_legacy_persona()
        if legacy:
            PERSONA_DATA = default_persona_json()
            CURRENT_PERSONA = legacy
            LEGACY_DETECTED = True
        else:
            PERSONA_DATA = default_persona_json()
            CURRENT_PERSONA = os.getenv("AI_PERSONA", "You are a helpful assistant.")
            LEGACY_DETECTED = False


# Run on import
init_persona()

# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

class PersonaCoreModal(ui.Modal, title="Persona: Core & Background"):
    core_personality = ui.TextInput(
        label="Core Personality & Traits",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
        placeholder="Describe the bot's personality, identity, and core traits.",
    )
    background = ui.TextInput(
        label="Background & History",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
        placeholder="Origin, backstory, relevant history.",
    )

    def __init__(self, data: dict):
        super().__init__()
        self.core_personality.default = data.get("core_personality", "")
        self.background.default = data.get("background", "")

    async def on_submit(self, interaction: discord.Interaction):
        global PERSONA_DATA, CURRENT_PERSONA
        if PERSONA_LOCKED:
            await interaction.response.send_message("Persona is locked. Use `/personaunlock` first.", ephemeral=True)
            return
        PERSONA_DATA["core_personality"] = self.core_personality.value.strip()
        PERSONA_DATA["background"] = self.background.value.strip()
        CURRENT_PERSONA = assemble_persona(PERSONA_DATA)
        try:
            save_persona_json(PERSONA_DATA)
            await interaction.response.send_message(
                "✅ Core & Background saved. Use `/setpersona style` for the remaining fields.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Save failed: {e}", ephemeral=True)


class PersonaStyleModal(ui.Modal, title="Persona: Style & Instructions"):
    beliefs = ui.TextInput(
        label="Beliefs, Likes & Dislikes",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
        placeholder="Values, opinions, preferences, things they love or hate.",
    )
    language = ui.TextInput(
        label="Language & Communication Style",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
        placeholder="Primary language, tone, slang, formality level.",
    )
    system_instructions = ui.TextInput(
        label="System Instructions",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
        placeholder="Advanced rules, constraints, or override behavior.",
    )

    def __init__(self, data: dict):
        super().__init__()
        self.beliefs.default = data.get("beliefs", "")
        self.language.default = data.get("language", "")
        self.system_instructions.default = data.get("system_instructions", "")

    async def on_submit(self, interaction: discord.Interaction):
        global PERSONA_DATA, CURRENT_PERSONA
        if PERSONA_LOCKED:
            await interaction.response.send_message("Persona is locked. Use `/personaunlock` first.", ephemeral=True)
            return
        PERSONA_DATA["beliefs"] = self.beliefs.value.strip()
        PERSONA_DATA["language"] = self.language.value.strip()
        PERSONA_DATA["system_instructions"] = self.system_instructions.value.strip()
        CURRENT_PERSONA = assemble_persona(PERSONA_DATA)
        try:
            save_persona_json(PERSONA_DATA)
            await interaction.response.send_message("✅ Style & Instructions saved.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Save failed: {e}", ephemeral=True)


# ---------------------------------------------------------------------------
# /setpersona command group
# ---------------------------------------------------------------------------

class SetPersonaGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="setpersona", description="Edit the bot's persona (Owner only).")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        bot = interaction.client
        if isinstance(bot, commands.Bot):
            if not await bot.is_owner(interaction.user):
                await interaction.response.send_message("Owner only.", ephemeral=True)
                return False
            return True
        await interaction.response.send_message("Owner check failed.", ephemeral=True)
        return False

    @app_commands.command(name="core", description="Edit core personality and background.")
    async def set_core(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PersonaCoreModal(PERSONA_DATA))

    @app_commands.command(name="style", description="Edit beliefs, language style, and system instructions.")
    async def set_style(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PersonaStyleModal(PERSONA_DATA))

# ---------------------------------------------------------------------------
# Panel UI (replaces SetPersonaGroup slash command group)
# ---------------------------------------------------------------------------

class PersonaFullModal(ui.Modal, title="Persona Editor"):
    core_personality = ui.TextInput(
        label="Core Personality & Traits",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
    )
    background = ui.TextInput(
        label="Background & History",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
    )
    beliefs = ui.TextInput(
        label="Beliefs, Likes & Dislikes",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
    )
    language = ui.TextInput(
        label="Language & Communication Style",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
    )
    system_instructions = ui.TextInput(
        label="System Instructions",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1024,
    )

    def __init__(self, data: dict):
        super().__init__()
        for field_name in PERSONA_FIELDS:
            getattr(self, field_name).default = data.get(field_name, "")

    async def on_submit(self, interaction: discord.Interaction):
        global PERSONA_DATA, CURRENT_PERSONA
        if PERSONA_LOCKED:
            await interaction.response.send_message("Persona is locked. Use `/personaunlock` first.", ephemeral=True)
            return
        for field_name in PERSONA_FIELDS:
            PERSONA_DATA[field_name] = getattr(self, field_name).value.strip()
        CURRENT_PERSONA = assemble_persona(PERSONA_DATA)
        try:
            save_persona_json(PERSONA_DATA)
            await interaction.response.send_message("Persona saved.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Save failed: {e}", ephemeral=True)


class PersonaPanelView(ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=300)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return False
        return True

    @ui.button(label="Edit Persona", style=discord.ButtonStyle.primary)
    async def edit_persona(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PersonaFullModal(PERSONA_DATA))

    @ui.button(label="Preview", style=discord.ButtonStyle.secondary)
    async def preview_persona(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(title="Persona Preview", color=discord.Color.yellow())
        for field_name in ASSEMBLY_ORDER:
            value = PERSONA_DATA.get(field_name, "").strip() or "(empty)"
            embed.add_field(
                name=PERSONA_LABELS[field_name],
                value=value[:1024],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Status", style=discord.ButtonStyle.secondary)
    async def persona_status(self, interaction: discord.Interaction, button: ui.Button):
        locked = "locked" if PERSONA_LOCKED else "unlocked"
        legacy = "legacy persona.txt active" if LEGACY_DETECTED else "structured persona active"
        await interaction.response.send_message(f"Persona is {locked}; {legacy}.", ephemeral=True)


async def open_persona_panel(interaction: discord.Interaction):
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        await interaction.response.send_message("Owner check failed.", ephemeral=True)
        return
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return
    embed = discord.Embed(
        title="Persona Editor",
        description="Use the buttons below to edit, preview, or check the active persona.",
        color=discord.Color.yellow(),
    )
    embed.add_field(name="Fields", value="\n".join(PERSONA_LABELS[f] for f in PERSONA_FIELDS), inline=False)
    await interaction.response.send_message(embed=embed, view=PersonaPanelView(bot), ephemeral=True)