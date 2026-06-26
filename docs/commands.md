# Command Reference

Default prefix is `~`. Change it with `~prefix <symbol>`. Most commands work as both prefix and slash commands. `/setpersona` and `/autonomy` are slash-only because they use Discord UI interactions.

## AI Commands

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `~write <prompt>` (`/write`, alias `~w`) | Structured output using active persona | Anyone |
| `~ask <question>` (`/ask`, alias `~a`) | Conversational response using active persona | Anyone |
| `~search <query>` (`/search`, alias `~s`) | Web search with AI summary | Anyone |
| `~separate <url>` (`/separate`, aliases `~sep`, `~stems`) | Vocal/instrumental separation via MVSEP | Anyone |

## RSS / News

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/rss latest <feed>` | Show latest items from an RSS/Atom feed | Anyone |
| `/rss list` | List configured RSS feeds | Anyone |
| `/rss add <name> <url>` | Add or update an RSS feed | Administrator |
| `/rss remove <name>` | Remove an RSS feed | Administrator |
| `/rss setchannel <#channel>` | Set RSS auto-post channel | Administrator |
| `/rss clearchannel` | Disable RSS auto-posting | Administrator |

## Conversation Channel

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/setchannel #channel` | Set the AI conversation channel | Administrator |
| `/clearchannel` | Remove the conversation channel | Administrator |
| `/clearmemory` | Clear short-term channel memory | Administrator |
| `/chatmode <all/mentions/smart>` | Set when the bot replies in the conversation channel | Administrator |

The bot responds to messages in the configured conversation channel. It keeps the last 5 messages as context and summarizes older history automatically. Every message is tagged with the sender's display name so the bot can tell users apart.

## Persona & Memory

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/setpersona` | Open the button-based persona editor | Bot Owner |
| `/personalock` (`~personalock`, alias `~plock`) | Lock persona against changes | Bot Owner |
| `/personaunlock` (`~personaunlock`, alias `~pulock`) | Unlock persona | Bot Owner |
| `/personasave <name>` (`~personasave`, alias `~psave`) | Save current persona as a preset | Bot Owner |
| `/personaload <name>` (`~personaload`, alias `~pload`) | Load a saved persona preset | Bot Owner |
| `/personalist` (`~personalist`, alias `~plist`) | List saved persona presets | Bot Owner |
| `/personadelete <name>` (`~personadelete`, alias `~pdel`) | Delete a saved persona preset | Bot Owner |
| `/debugpersona` (`~debugpersona`, alias `~pdeb`) | Show active persona, last prompt, model, lock state, autonomy | Bot Owner |
| `/memorylist <user>` (`~memorylist`, alias `~meml`) | List long-term memory facts for a user | Administrator |
| `/memoryclear <user>` (`~memoryclear`, alias `~memcl`) | Clear long-term memory facts for a user | Administrator |
| `/memorydelete <index> [user]` (`~memorydelete`, alias `~memdel`) | Delete a specific memory fact | Administrator |
| `/migrate` (`~migrate`) | Migrate memory data to SQLite | Administrator |

## Runtime Controls

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/module list` | List enabled/disabled modules | Administrator |
| `/module enable <name>` | Enable and load a module | Administrator |
| `/module disable <name>` | Disable and unload a module | Administrator |
| `/module reload <name>` | Reload an enabled module | Administrator |
| `/model show` | Show the active Gemini model | Bot Owner |
| `/model set <name>` | Set the active Gemini model | Bot Owner |
| `/model reset` | Reset to the environment/default model | Bot Owner |
| `/botwhitelist` (`~botwhitelist`, alias `~bw`) | List whitelisted bot IDs | Administrator |
| `/botwhitelist add <bot_id>` | Add a bot ID to the whitelist | Administrator |
| `/botwhitelist remove <bot_id>` | Remove a bot ID from the whitelist | Administrator |
| `/sync` | Sync global slash commands | Bot Owner |
| `/settimezone <timezone>` | Set the bot's timezone | Administrator |
| `/timezone` | Show the bot's currently configured timezone | Anyone |
| `/setanniversarychannel <channel>` | Set the anniversary announcement channel | Administrator |

Module and model names include slash-command suggestions.

## Autonomy

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/autonomy on` | Enable autonomous mode | Administrator |
| `/autonomy off` | Disable autonomous mode | Administrator |
| `/autonomy frequency <low/default/high>` | Set confidence threshold | Administrator |

Autonomous mode uses a confidence-scored intent evaluator (not random chance). Thresholds: `low` = 0.70, `default` = 0.50, `high` = 0.35. A 120-second per-channel cooldown prevents the bot from dominating a conversation.

## Moderation & Utility

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `~help [command]` | Show help for commands | Anyone |
| `~prefix <symbol>` | Change command prefix | Administrator |
| `~purge <limit>` | Delete messages (1–1000) | Manage Messages |
| `~kick <member> [reason]` | Kick a member | Kick Members |
| `~ban <user> [reason]` | Ban a user | Ban Members |
| `~unban <user> [reason]` | Unban a user | Ban Members |
| `~timeout <member> <duration> [reason]` (`~to`) | Timeout a member (e.g. `10m`, `1h`) | Moderate Members |
| `~removetimeout <member>` (`~rt`, `~rto`) | Remove a timeout | Moderate Members |
| `~warn <member\|id> [reason]` | Warn a member | Administrator |
| `~warns <member\|id>` | Show warnings for a member | Administrator |
| `~delwarn <warn_id>` | Delete a warning by ID | Administrator |
| `~clearwarns <member\|id>` | Clear warnings for a member | Administrator |
| `~warnthresholds` (`~wt`) | View/edit auto-punishment thresholds | Administrator |
| `/math <equation>` | Solve an equation via Wolfram\|Alpha | Anyone |
| `~download <url>` (`~dl`) | Download a video | Anyone |
| `~audio <url>` (`~mp3`) | Download audio as MP3 | Anyone |
| `~ping` | Show bot and Discord API latency | Anyone |

## Fun

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `~hello` | Say hello back | Anyone |
| `~randommember` | Randomly selects a server member | Anyone |
| `~coinflip` | Flips a coin | Anyone |
| `~roll [sides]` | Rolls a die (default: 6 sides) | Anyone |
| `~pick <choice1, choice2, ...>` | Randomly picks from comma-separated choices | Anyone |
