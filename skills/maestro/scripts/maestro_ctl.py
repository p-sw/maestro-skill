#!/usr/bin/env python3
"""MAESTRO control helper: Hermes-side plumbing for project agents.

Wraps the `hermes` CLI for the pieces that are fiddly to do by hand:
gateway.profile_routes (a YAML list), comma-separated Discord env lists,
per-profile Hindsight config.json, template rendering and status checks.

Stdlib only. All commands print JSON to stdout; errors go to stderr with
exit code 1. Gateway-wide settings (routes, Discord env lists) always live
in the default profile, which is where the Discord bot runs.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CSV_KEYS = (
    "DISCORD_ALLOWED_USERS",
    "DISCORD_ALLOWED_ROLES",
    "DISCORD_ALLOWED_CHANNELS",
    "DISCORD_FREE_RESPONSE_CHANNELS",
    "DISCORD_IGNORED_CHANNELS",
    "DISCORD_NO_THREAD_CHANNELS",
)
SECRET_HINTS = ("key", "token", "secret", "password")
PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class CliError(Exception):
    pass


def out(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# ---- hermes CLI ------------------------------------------------------------

def hermes(profile, *args, check=True):
    cmd = ["hermes", "-p", profile, *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise CliError("`hermes` is not on PATH")
    if check and res.returncode != 0:
        msg = (res.stderr or res.stdout).strip()
        raise CliError(f"`hermes -p {profile} {' '.join(args[:3])}` failed: {msg}")
    return res


def last_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


def config_get(profile, key, as_json=True):
    """Value of a config/.env key, or None when it is not set."""
    flags = ["--json", "--raw"] if as_json else ["--raw"]
    res = hermes(profile, "config", "get", key, *flags, check=False)
    if res.returncode != 0:
        if "not set" in (res.stderr + res.stdout).lower():
            return None
        raise CliError(f"hermes config get {key} failed: {(res.stderr or res.stdout).strip()}")
    if not as_json:
        return last_line(res.stdout)
    for text in (res.stdout, last_line(res.stdout)):
        try:
            return json.loads(text)
        except ValueError:
            continue
    raise CliError(f"could not parse `hermes config get {key} --json` output")


def config_set(profile, key, value):
    hermes(profile, "config", "set", key, value)


def profile_home(profile):
    path = last_line(hermes(profile, "config", "path").stdout)
    if not path.endswith("config.yaml"):
        raise CliError(f"unexpected `hermes config path` output: {path!r}")
    return Path(path).parent


# ---- routes ------------------------------------------------------------------

def get_routes():
    routes = config_get("default", "gateway.profile_routes")
    return routes or []


def save_routes(routes, dry_run):
    payload = json.dumps(routes, ensure_ascii=False)
    if dry_run:
        return out({"dry_run": True, "gateway.profile_routes": routes})
    config_set("default", "gateway.profile_routes", payload)
    out({"gateway.profile_routes": routes, "restart_required": True})


def find_route(routes, name):
    for i, r in enumerate(routes):
        if r.get("name") == name:
            return i
    raise CliError(f"route '{name}' not found")


def cmd_routes_list(a):
    routes = get_routes()
    if a.profile:
        routes = [r for r in routes if r.get("profile") == a.profile]
    out(routes)


def cmd_routes_add(a):
    for v, flag in ((a.chat_id, "--chat-id"), (a.guild_id, "--guild-id")):
        if v and not v.isdigit():
            raise CliError(f"{flag} must be a numeric id, got '{v}'")
    if not a.chat_id and not a.guild_id:
        raise CliError("pass --chat-id (and usually --guild-id)")
    routes = get_routes()
    route = {"name": a.name, "platform": a.platform}
    if a.guild_id:
        route["guild_id"] = a.guild_id
    if a.chat_id:
        route["chat_id"] = a.chat_id
    route["profile"] = a.profile
    clash = [r for r in routes if r.get("name") != a.name and r.get("platform") == a.platform
             and a.chat_id and str(r.get("chat_id")) == a.chat_id]
    if clash and not a.force:
        names = ", ".join(f"{r.get('name')}->{r.get('profile')}" for r in clash)
        raise CliError(f"chat {a.chat_id} is already routed ({names}); pass --force to add anyway")
    try:
        routes[find_route(routes, a.name)] = route
    except CliError:
        routes.append(route)
    if config_get("default", "gateway.multiplex_profiles") is False:
        print("warning: gateway.multiplex_profiles is false; routes are ignored", file=sys.stderr)
    save_routes(routes, a.dry_run)


def cmd_routes_remove(a):
    routes = get_routes()
    routes.pop(find_route(routes, a.name))
    save_routes(routes, a.dry_run)


def set_route_enabled(a, enabled):
    routes = get_routes()
    r = routes[find_route(routes, a.name)]
    if enabled:
        r.pop("enabled", None)
    else:
        r["enabled"] = False
    save_routes(routes, a.dry_run)


def cmd_routes_enable(a):
    set_route_enabled(a, True)


def cmd_routes_disable(a):
    set_route_enabled(a, False)


# ---- comma-separated env lists ----------------------------------------------

def csv_values(profile, key):
    raw = config_get(profile, key, as_json=False)
    return [v.strip() for v in (raw or "").split(",") if v.strip()]


def cmd_envlist(a):
    if a.key not in CSV_KEYS:
        raise CliError(f"KEY must be one of: {', '.join(CSV_KEYS)}")
    values = csv_values(a.profile, a.key)
    if a.action == "list":
        return out({"profile": a.profile, a.key: values})
    if not a.value:
        raise CliError(f"`{a.action}` needs VALUE")
    for v in a.value:
        if not v.isdigit():
            raise CliError(f"values must be numeric Discord ids, got '{v}'")
    before = list(values)
    if a.action == "add":
        values += [v for v in a.value if v not in values]
    else:
        values = [v for v in values if v not in a.value]
    result = {"profile": a.profile, a.key: values, "changed": values != before}
    if a.dry_run or values == before:
        return out(dict(result, dry_run=a.dry_run))
    if values:
        config_set(a.profile, a.key, ",".join(values))
    else:
        hermes(a.profile, "config", "unset", a.key)
    out(dict(result, restart_required=True))


# ---- hindsight config.json -----------------------------------------------------

def mask(cfg):
    return {k: ("***" if any(h in k.lower() for h in SECRET_HINTS) and v else v)
            for k, v in cfg.items()}


def parse_value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def cmd_hindsight_config(a):
    home = profile_home(a.profile)
    path = home / "hindsight" / "config.json"
    notes = []
    if path.exists():
        cfg = json.loads(path.read_text())
    elif a.bank_id or a.set:
        seed = profile_home("default") / "hindsight" / "config.json"
        cfg = json.loads(seed.read_text()) if seed.exists() else {"mode": "cloud"}
        for k in ("additional_banks", "recall_additional_banks", "mirror_to_own_bank"):
            if cfg.pop(k, None) is not None:
                notes.append(f"dropped '{k}' inherited from the default profile")
        notes.append(f"seeded from {seed}" if seed.exists() else "created a new cloud config")
    else:
        raise CliError(f"{path} does not exist; pass --bank-id to create it")
    new = dict(cfg)
    if a.bank_id:
        new["bank_id"] = a.bank_id
        if new.pop("bank_id_template", None) is not None:
            notes.append("removed 'bank_id_template' so the fixed bank_id is used")
    for item in a.set or []:
        k, sep, v = item.partition("=")
        if not sep or not k:
            raise CliError(f"--set expects key=value, got '{item}'")
        new[k] = parse_value(v)
    for k in ("additional_banks", "recall_additional_banks"):
        if new.get(k):
            notes.append(f"'{k}' is set ({new[k]}); make sure it does not leak another project's bank")
    result = {"path": str(path), "config": mask(new), "changed": new != cfg, "notes": notes}
    if a.dry_run or new == cfg:
        return out(dict(result, dry_run=a.dry_run))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n")
    out(result)


# ---- templates -------------------------------------------------------------------

def cmd_render(a):
    template = Path(a.template).expanduser()
    text = template.read_text()
    values = {}
    for item in a.var or []:
        k, sep, v = item.partition("=")
        if not sep or not k:
            raise CliError(f"--var expects key=value, got '{item}'")
        values[k] = v
    missing = sorted({m for m in PLACEHOLDER.findall(text) if m not in values})
    if missing:
        raise CliError(f"missing --var for: {', '.join(missing)}")
    rendered = PLACEHOLDER.sub(lambda m: values[m.group(1)], text)
    dest = Path(a.dest).expanduser()
    if a.dry_run:
        sys.stdout.write(rendered)
        return
    backup = None
    if dest.exists() and dest.read_text().strip():
        if not a.force:
            raise CliError(f"{dest} already has content; pass --force (a backup is kept)")
        backup = dest.with_name(f"{dest.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(dest.read_text())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rendered)
    out({"written": str(dest), "chars": len(rendered),
         "backup": str(backup) if backup else None})


# ---- status ------------------------------------------------------------------------

def git(path, *args):
    res = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else None


def workspace_status(ws):
    if not (ws / ".git").exists():
        return {"path": str(ws), "exists": ws.exists(), "git": False}
    remotes = {}
    for line in (git(ws, "remote", "-v") or "").splitlines():
        name, url, *_ = line.split()
        remotes[name] = url
    return {"path": str(ws), "exists": True, "git": True,
            "branch": git(ws, "rev-parse", "--abbrev-ref", "HEAD"),
            "remotes": remotes, "dirty": bool(git(ws, "status", "--porcelain"))}


def profile_status(name, routes):
    home = profile_home(name)
    hs = home / "hindsight" / "config.json"
    hs_cfg = json.loads(hs.read_text()) if hs.exists() else None
    mem = home / "memories"
    cwd = config_get(name, "terminal.cwd")
    return {
        "profile": name,
        "home": str(home),
        "soul_md_chars": len((home / "SOUL.md").read_text()) if (home / "SOUL.md").exists() else None,
        "memories_chars": {f.name: len(f.read_text()) for f in sorted(mem.glob("*.md"))} if mem.exists() else {},
        "memory_provider": config_get(name, "memory.provider"),
        "hindsight_bank_id": (hs_cfg or {}).get("bank_id"),
        "terminal_cwd": cwd,
        "workspace": workspace_status(Path(cwd) if cwd and cwd != "." else home / "workspace"),
        "routes": [r for r in routes if r.get("profile") == name],
    }


def cmd_status(a):
    routes = get_routes()
    if a.profile:
        return out(profile_status(a.profile, routes))
    profiles_dir = profile_home("default") / "profiles"
    names = sorted(p.name for p in profiles_dir.glob(f"{a.prefix}*") if p.is_dir())
    out([profile_status(n, routes) for n in names])


# ---- parser --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="maestro_ctl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="group", required=True)

    rt = sub.add_parser("routes", help="gateway.profile_routes (default profile)").add_subparsers(
        dest="cmd", required=True)
    r = rt.add_parser("list", help="list routes")
    r.add_argument("--profile", help="only routes targeting this profile")
    r.set_defaults(fn=cmd_routes_list)
    r = rt.add_parser("add", help="add or replace a route by name")
    r.add_argument("name", help="route name, e.g. proj-<slug>")
    r.add_argument("--profile", required=True, help="target profile")
    r.add_argument("--chat-id", help="Discord channel id")
    r.add_argument("--guild-id", default=os.environ.get("DISCORD_SERVER_ID"),
                   help="Discord server id (default: $DISCORD_SERVER_ID)")
    r.add_argument("--platform", default="discord")
    r.add_argument("--force", action="store_true", help="allow a second route for the same chat")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_routes_add)
    for name, fn, what in (("remove", cmd_routes_remove, "delete a route"),
                           ("enable", cmd_routes_enable, "re-enable a disabled route"),
                           ("disable", cmd_routes_disable, "keep a route but stop matching it")):
        r = rt.add_parser(name, help=what)
        r.add_argument("name")
        r.add_argument("--dry-run", action="store_true")
        r.set_defaults(fn=fn)

    r = sub.add_parser("env-list", help="edit a comma-separated Discord id list in .env")
    r.add_argument("action", choices=("list", "add", "remove"))
    r.add_argument("key", metavar="KEY", help=" | ".join(CSV_KEYS))
    r.add_argument("value", nargs="*", help="ids to add/remove")
    r.add_argument("--profile", default="default")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_envlist)

    r = sub.add_parser("hindsight-config", help="show or edit <profile>/hindsight/config.json")
    r.add_argument("profile")
    r.add_argument("--bank-id", help="bank this profile reads and writes")
    r.add_argument("--set", action="append", metavar="KEY=VALUE",
                   help="extra key (VALUE parsed as JSON when possible); repeatable")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_hindsight_config)

    r = sub.add_parser("render", help="fill {{placeholders}} in a template and write it")
    r.add_argument("template")
    r.add_argument("dest")
    r.add_argument("--var", action="append", metavar="KEY=VALUE", help="repeatable")
    r.add_argument("--force", action="store_true", help="overwrite non-empty DEST (keeps a backup)")
    r.add_argument("--dry-run", action="store_true", help="print instead of writing")
    r.set_defaults(fn=cmd_render)

    r = sub.add_parser("status", help="summarise project profiles")
    r.add_argument("profile", nargs="?", help="one profile (default: all matching --prefix)")
    r.add_argument("--prefix", default="proj-")
    r.set_defaults(fn=cmd_status)
    return p


def main():
    args = build_parser().parse_args()
    try:
        args.fn(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
