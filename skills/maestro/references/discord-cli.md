# Discord admin CLI reference

`scripts/discord_cli.py` is a stdlib-only Python CLI (Python 3.8+, no installs) around the Discord REST API (v10) for the server in `DISCORD_SERVER_ID`, authenticated as the bot in `DISCORD_BOT_TOKEN`. All output is JSON on stdout; errors go to stderr with exit code 1.

Examples below use `$DCLI`, defined in SKILL.md as `python3 <skill directory>/scripts/discord_cli.py`.

## Commands

| Goal | Command |
|---|---|
| Bot's own user id | `bot whoami` |
| List roles | `roles list [--permissions]` |
| Create role | `roles create NAME [--color #hex] [--hoist] [--mentionable] [--permissions P] [--exist-ok] [--dry-run]` |
| Edit role | `roles edit ROLE [--name N] [--color #hex] [--[no-]hoist] [--[no-]mentionable] [--permissions P] [--dry-run]` |
| Give / take role | `roles assign ROLE USER_ID [--dry-run]` / `roles unassign ROLE USER_ID [--dry-run]` |
| Members with a role | `roles members ROLE` |
| One member's roles | `members show USER_ID` |
| List categories | `categories list` |
| List channels | `channels list [--category NAME] [--type text\|voice\|announcement\|stage\|forum]` |
| Create channel | `channels create NAME [--type T] [--category C] [--topic TXT] [--nsfw] [--private [--allow-role R]... [--allow-member ID]... [--allow-bot]] [--exist-ok] [--dry-run]` |
| Create category | `channels create NAME --type category [--exist-ok]` |
| Rename / retopic / move | `channels edit CHANNEL [--name N] [--topic TXT] [--category C \| --no-category] [--dry-run]` |
| Show overwrites | `perms show CHANNEL` |
| Set overwrite | `perms set CHANNEL TARGET [--allow A,B] [--deny C,D] [--replace] [--dry-run]` |
| Remove overwrite | `perms clear CHANNEL TARGET [--dry-run]` |
| Permission names | `permissions list` |

- `CHANNEL`, `--category`, `ROLE` accept a name (case-insensitive) or a snowflake id. Ambiguous names error out and list the ids; retry with an id.
- `TARGET` is `@everyone`, `bot`, `role:<name|id>`, or `member:<user_id>`.
- Permissions are Discord names such as `VIEW_CHANNEL,SEND_MESSAGES` (or a raw integer bitfield).
- `perms set` merges into any existing overwrite for that target (unrelated bits are kept); `--replace` overwrites it entirely.
- `channels create` and `roles create` refuse to make a same-named duplicate; `--exist-ok` returns the existing one with `"created": false`, which makes provisioning safe to re-run.
- `--private` denies `VIEW_CHANNEL` to `@everyone`, then allows it for each `--allow-role`, `--allow-member` and (with `--allow-bot`) the bot itself. Always pass `--allow-bot` unless the bot has Administrator, or it loses access to the channel it just created.
- There is no delete command for channels or roles, by design. To retire something, move it to an archive category and make it read-only; actual deletion is done by the owner in Discord.

## Examples

```bash
$DCLI roles list
$DCLI channels list --category Projects
$DCLI roles create proj-demo --mentionable --exist-ok
$DCLI channels create demo --category Projects --topic "Demo project agent" \
  --private --allow-role proj-demo --allow-bot --exist-ok --dry-run
$DCLI roles assign proj-demo 284102345871466496
$DCLI perms set announcements @everyone --deny SEND_MESSAGES --allow VIEW_CHANNEL
$DCLI perms show demo
$DCLI channels edit demo --category Archive
```

## Workflow guidance
1. Read first: `roles list` / `categories list` / `channels list` to confirm real names before changing anything.
2. For writes, run with `--dry-run` first and show the user the request body, then run for real once they confirm (MAESTRO's project provisioning plan counts as that confirmation for the steps it listed).
3. After a permission change, verify with `perms show`.

## Pitfalls
- The bot needs **Manage Channels** (and **Manage Roles** to edit overwrites, create roles and assign them), and can only grant permissions it holds itself. A 403 `Missing Permissions` means the bot's role lacks these or sits below the target role in the role list.
- Roles the bot creates are placed just above `@everyone`, below the bot's own role, so it can assign them. It cannot assign roles above its own.
- `roles members` lists all guild members and needs the **Server Members Intent** enabled for the application; without it Discord returns 403.
- `@everyone`'s role id equals the server id; the CLI handles this for `@everyone`.
- Explicit deny beats allow only within the same overwrite; role overwrites are combined and member overwrites win over roles. A channel inside a category does not inherit overwrites automatically unless it was synced, so check `perms show`.
- Rate limits (429) are retried automatically.
- The token is read from `MAESTRO_DISCORD_BOT_TOKEN`, falling back to `DISCORD_BOT_TOKEN` (which Hermes strips from skill commands). If env vars are missing the CLI errors with the variable's name; never print or echo the token.
