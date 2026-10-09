# Hermes and Hindsight cheat sheet

Facts MAESTRO relies on. Hermes and Hindsight move fast; when a command errors, check `--help` and adapt rather than forcing it.

## Hermes profiles

- A profile is a separate Hermes home: `~/.hermes/profiles/<name>/` with its own `config.yaml`, `.env`, `SOUL.md`, `memories/`, `skills/`, `plugins/`, sessions and `state.db`. The default profile is `~/.hermes` itself (MAESTRO). Target any profile with `hermes -p <name> <command>`.
- `hermes profile create <name> --clone-from <src> [--description "..."]` copies config, `.env` (minus messaging channel settings), `SOUL.md`, skills, `memories/MEMORY.md` + `USER.md`, the memory provider's config (`hindsight/config.json`) and `plugins/`. Sessions, `state.db` and cron jobs start empty. Bot tokens, allowlists and `gateway.profile_routes` are never cloned.
- Names: lowercase letters, digits, `-` and `_`.
- `hermes profile list | show <name> | describe <name> --text "..." | rename <old> <new> | delete <name> --yes`. Deleting removes the whole profile directory, including `workspace/`.
- `hermes -p <name> config get <key> [--json] [--raw]`, `config set <key> <value>`, `config unset <key>`, `config path`. Dotted keys go to `config.yaml`; `UPPER_SNAKE` keys go to that profile's `.env`. Lists/maps are passed as JSON/YAML literals.
- Profiles are not sandboxes. Set the starting directory explicitly: `hermes -p <name> config set terminal.cwd /abs/path`.
- `SOUL.md` is loaded from the profile home only and injected verbatim as the agent identity; changes apply to new sessions.
- `memories/MEMORY.md` (2,200 chars) and `memories/USER.md` (1,375 chars) are entries separated by a line containing only `§`. They are injected as a frozen snapshot at session start.
- Skills: `hermes -p <name> skills list | install <id> | uninstall <name>`; disable without uninstalling via `hermes -p <name> config set skills.disabled '["maestro"]'`.
- Project agents use the bundled `codex`, `claude-code` and `github` skills.

## One gateway, many profiles

- One gateway process (`gateway.multiplex_profiles: true`, the default) serves the default profile and every profile under `profiles/`. Never run `hermes -p <proj> gateway install/start`, and never give a project profile its own copy of the Discord bot token: the duplicate adapter gets parked.
- A profile created while the gateway runs is served immediately. Gateway config such as `gateway.profile_routes` and the Discord `.env` lists is read at start-up, so a change needs a gateway restart.
- Restart from Discord with the `/restart` command, or from a shell with `hermes gateway restart` (drains active turns first). Running it from inside a MAESTRO turn makes the gateway wait for that same turn, so either ask the owner to send `/restart`, or detach it as your last action: `nohup sh -c 'sleep 20; hermes gateway restart' >/dev/null 2>&1 &`.
- `gateway.profile_routes` (declared on the default profile) sends traffic from the shared bot to a profile:

  ```yaml
  gateway:
    profile_routes:
      - name: proj-demo
        platform: discord
        guild_id: "<server id>"
        chat_id: "<channel id>"   # threads under this channel match too
        profile: proj-demo
        # enabled: false          # keep the route but stop matching it
  ```

  Match score: `user_id` 16, `thread_id` 8, `chat_id` 4, `guild_id` 2; the most specific wins. Unmatched traffic stays with the default profile (MAESTRO). A route whose target profile is missing is rejected, not sent to MAESTRO. Manage it with `maestro_ctl.py routes ...`.
- Authorization for routed messages is decided by the receiving bot's profile (the default one): `DISCORD_ALLOWED_USERS` / `DISCORD_ALLOWED_ROLES` in the default profile's `.env`. The routed profile needs no allowlist of its own.
- Useful Discord `.env` lists (comma-separated ids, default profile): `DISCORD_ALLOWED_USERS`, `DISCORD_ALLOWED_ROLES`, `DISCORD_FREE_RESPONSE_CHANNELS` (answer without @mention), `DISCORD_IGNORED_CHANNELS`, `DISCORD_NO_THREAD_CHANNELS`. Manage them with `maestro_ctl.py env-list ...`.

## Hindsight memory provider (Hermes plugin)

- Install and activate per profile: `hermes -p <name> plugins install hindsight`, `hermes -p <name> config set memory.provider hindsight`. Check with `hermes -p <name> memory status`.
- Config file: `<profile home>/hindsight/config.json`. Keys used here: `mode` (`cloud`), `api_url`, `bank_id`, `bank_id_template` (overrides `bank_id` when set, so remove it for a fixed bank), `additional_banks` / `recall_additional_banks`, `retain_context`, `auto_retain`, `auto_recall`, `recall_budget`, `memory_mode`.
- `HINDSIGHT_API_KEY` (and optional `HINDSIGHT_API_URL`, `HINDSIGHT_BANK_ID`) are read from the profile's `.env`. A cloned profile inherits them from its source.
- Agent tools: `hindsight_retain`, `hindsight_recall`, `hindsight_reflect`.

## Hindsight CLI (`hindsight`)

Uses `HINDSIGHT_API_URL` and `HINDSIGHT_API_KEY` from the environment. Add `-o json` for machine-readable output.

| Goal | Command |
|---|---|
| List banks | `hindsight -o json bank list` |
| Create bank | `hindsight bank create <bank_id> --name "<display name>" --mission "<reflect mission>"` |
| Update name/mission | `hindsight bank update <bank_id> [--name N] [--mission M]` |
| Tune extraction | `hindsight bank set-config <bank_id> --retain-mission "..." --observations-mission "..." [--reflect-mission "..."] [--retain-extraction-mode concise\|verbose]` |
| Show config | `hindsight bank config <bank_id> [--overrides-only]` |
| Stats | `hindsight bank stats <bank_id>` |
| Store a memory | `hindsight memory retain <bank_id> "<text>" --context "<label>" [--doc-id <id>]` |
| Add a standing directive | `hindsight directive create <bank_id> "<name>" "<content>" [--priority N]` |
| Delete bank (irreversible) | `hindsight bank delete <bank_id> -y` |
