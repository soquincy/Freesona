# Command Reference

Default prefix is `~`. Change it with `~prefix <symbol>`. All commands work as both prefix and slash commands unless noted.

## AI

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `~write <prompt>` | Structured output using active persona | Anyone |
| `~ask <question>` | Conversational response using active persona | Anyone |
| `~search <query>` | Web search with AI summary | Anyone |
| `~separate <url>` | Vocal/instrumental separation via MVSEP | Anyone |

## Conversation Channel

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/setchannel #channel` | Set the AI conversation channel | Administrator |
| `/clearchannel` | Remove the conversation channel | Administrator |
| `/clearmemory` | Wipe short-term channel memory and summary | Administrator |

The bot responds to all messages in the conversation channel. It keeps the last 5 messages as context and summarizes older history automatically. Every message is tagged with the sender's display name so the bot can tell users apart.

## Persona

| Command | Action | Permissions |
| :--- | :--- | :--- |
| `/setpersona core` | Edit core personality and background | Bot Owner |
| `/setpersona style` | Edit beliefs, language style, system instructions | Bot Owner |
| `/personalock` | Lock persona against changes | Bot Owner |
| `/personaunlock` | Unlock persona | Bot Owner |
| `/personasave <name>` | Save current persona as a preset | Bot Owner |
| `/personaload <name>` | Load a saved persona preset | Bot Owner |
| `/personalist` | List all saved presets | Bot Owner |
| `/personadelete <name>` | Delete a saved preset | Bot Owner |
| `/debugpersona` | Show active persona, last prompt, model, lock state, autonomy | Bot Owner |

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
| `~prefix <symbol>` | Change command prefix | Administrator |
| `~purge <limit>` | Delete messages (1–1000) | Manage Messages |
| `~kick <member> [reason]` | Kick a member | Kick Members |
| `~ban <user> [reason]` | Ban a user | Ban Members |
| `~unban <user> [reason]` | Unban a user | Ban Members |
| `~timeout <member> <duration> [reason]` | Timeout a member (e.g. `10m`, `1h`) | Moderate Members |
| `~removetimeout <member>` | Remove a timeout | Moderate Members |
| `~math <equation>` | Solve an equation via Wolfram\|Alpha | Anyone |
| `~download <url>` | Download video (1080p/720p/480p/compressed) | Anyone |
| `~audio <url>` | Download audio as MP3 | Anyone |
| `~ping` | Show bot and Discord API latency | Anyone |
| `~hello` | Says hello | Anyone |
