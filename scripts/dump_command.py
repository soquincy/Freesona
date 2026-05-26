import asyncio
import logging
import sys
import yaml
from collections import OrderedDict
from pathlib import Path
from typing import Any, List, Union, Iterable

import discord
from discord.ext import commands

# Suppress noisy logs to keep output clean
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("PreviewBot")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.config import load_config
from utils.modules import CORE_EXTENSIONS, OPTIONAL_MODULES, load_enabled_modules

class PreviewBot(commands.Bot):
    async def setup_hook(self):
        pass

def get_params(command: Any) -> List[dict]:
    """Extracts parameter details from both Prefix and Slash commands."""
    params = []
    
    # Handle Prefix/Hybrid Commands
    if isinstance(command, commands.Command):
        for name, param in command.clean_params.items():
            params.append({
                "name": name,
                "required": param.default is param.empty,
                "type": str(param.annotation.__name__) if hasattr(param.annotation, "__name__") else "Any"
            })
    
    # Handle Slash Commands (App Commands)
    elif isinstance(command, discord.app_commands.Command):
        for param in command.parameters:
            params.append({
                "name": param.name,
                "required": param.required,
                "type": str(param.type.name) if hasattr(param.type, "name") else "Any"
            })
            
    return params

def process_commands(cmds: Iterable[Any], is_tree: bool = False) -> List[dict]:
    """Recursively processes commands and subcommands."""
    cmd_list = list(cmds)
    extracted = []
    
    for cmd in sorted(cmd_list, key=lambda x: x.name):
        if not is_tree and getattr(cmd, "hidden", False):
            continue

        entry = {
            "name": cmd.name,
            "qualified_name": cmd.qualified_name,
            "description": getattr(cmd, "help", getattr(cmd, "description", "")) or "No description provided.",
        }
        
        if not is_tree:
            entry["aliases"] = list(getattr(cmd, "aliases", []))
            entry["is_hybrid"] = isinstance(cmd, commands.HybridCommand)
        
        entry["parameters"] = get_params(cmd)

        # Check for subcommands
        children = []
        if is_tree and hasattr(cmd, "commands"): # Slash Groups
            children = cmd.commands
        elif not is_tree and isinstance(cmd, commands.Group): # Prefix Groups
            children = list(cmd.commands)

        if children:
            entry["children"] = process_commands(children, is_tree)
        
        extracted.append(entry)
    
    return extracted

async def main() -> None:
    config = load_config()
    prefix = str(config.get("prefix", "~"))
    
    intents = discord.Intents.none()
    bot = PreviewBot(command_prefix=prefix, intents=intents)
    
    enabled_modules = load_enabled_modules(config)
    extensions = CORE_EXTENSIONS + [
        ext for name, ext in OPTIONAL_MODULES.items() if enabled_modules.get(name, True)
    ]

    bot.remove_command("help")

    loaded_successfully = []
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            loaded_successfully.append(ext)
        except Exception as e:
            print(f"Failed to load {ext}: {e}", file=sys.stderr)

    report = {
        "bot_info": {
            "prefix": prefix,
            "extension_count": len(loaded_successfully),
            "modules": {name: enabled_modules.get(name, True) for name in sorted(OPTIONAL_MODULES)}
        },
        "prefix_commands": process_commands(bot.commands, is_tree=False),
        "slash_commands": process_commands(bot.tree.get_commands(), is_tree=True)
    }

    # Use sort_keys=False to preserve the order we built
    print(yaml.dump(report, sort_keys=False, allow_unicode=True, indent=2))

    await bot.close()

if __name__ == "__main__":
    asyncio.run(main())