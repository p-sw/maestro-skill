# maestro-skill

The MAESTRO root-agent skill for [Hermes Agent](https://hermes-agent.nousresearch.com). MAESTRO (Master Agent for Every Sprint, Task, Route, and Output) manages a Hermes installation from Discord:

- creates a dedicated Hermes profile per project (the project agent) and writes its `SOUL.md` and memory files
- creates and configures a Hindsight memory bank per project
- creates the project's private Discord channel and role, and routes the channel to the profile
- forks an existing GitHub repository and clones the fork into the profile, or starts a new local repository
- changes project and profile settings, members and permissions, and audits or archives projects

Project agents plan, answer questions and code. They delegate coding to the local Codex or Claude Code CLI, follow each repository's commit conventions, and reach the original repository only through pull requests from the fork.

It merges the [discord-server-admin](https://github.com/p-sw/maestro-discord-cli) skill; its CLI is bundled here and extended with role, member and channel edit commands.

## Layout

```
skills/maestro/
├── SKILL.md                     # MAESTRO identity, rules and workflows
├── scripts/
│   ├── discord_cli.py           # Discord REST admin CLI (stdlib only)
│   └── maestro_ctl.py           # profile_routes, .env id lists, Hindsight config, templates, status
├── templates/
│   ├── project-SOUL.md          # standing rules for every project agent
│   └── project-MEMORY.md        # seeded repository facts
└── references/
    ├── discord-cli.md
    └── hermes-hindsight.md
```

## Requirements

- Hermes with one multiplexed gateway in the default profile (MAESTRO), Discord connected, and the Hindsight memory provider
- A `Projects` category in the Discord server; the bot needs Manage Channels and Manage Roles (Server Members Intent for `roles members`)
- Environment: `MAESTRO_DISCORD_BOT_TOKEN` (same value as `DISCORD_BOT_TOKEN`, which Hermes does not forward), `DISCORD_SERVER_ID`, `HINDSIGHT_API_URL`, `HINDSIGHT_API_KEY`
- CLIs: `hermes`, `hindsight`, `gh` (authenticated), `git`, `codex`, `claude`, Python 3.8+

## Install as a Hermes skill

Install it in the default (MAESTRO) profile only. Project profiles must not get it.

```bash
hermes skills install p-sw/maestro-skill/skills/maestro
# or register the repo as a tap
hermes skills tap add p-sw/maestro-skill
```

Syntax may differ between Hermes versions; check `hermes skills --help`.

## Use the CLIs directly

```bash
python3 skills/maestro/scripts/discord_cli.py --help
python3 skills/maestro/scripts/maestro_ctl.py --help
python3 skills/maestro/scripts/maestro_ctl.py status
```

See [SKILL.md](skills/maestro/SKILL.md) for the workflows.
