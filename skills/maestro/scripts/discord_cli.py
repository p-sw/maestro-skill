#!/usr/bin/env python3
"""Discord server admin CLI: roles, categories, channels, channel permissions.

Requires env vars DISCORD_BOT_TOKEN and DISCORD_SERVER_ID. Stdlib only.
All commands print JSON to stdout; errors go to stderr with exit code 1.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/maestro/discord-cli, 1.0)"

CHANNEL_TYPES = {
    "text": 0,
    "voice": 2,
    "category": 4,
    "announcement": 5,
    "stage": 13,
    "forum": 15,
}
TYPE_NAMES = {
    0: "text", 2: "voice", 4: "category", 5: "announcement",
    13: "stage", 15: "forum", 16: "media",
}

PERMISSIONS = {
    "CREATE_INSTANT_INVITE": 0, "KICK_MEMBERS": 1, "BAN_MEMBERS": 2,
    "ADMINISTRATOR": 3, "MANAGE_CHANNELS": 4, "MANAGE_GUILD": 5,
    "ADD_REACTIONS": 6, "VIEW_AUDIT_LOG": 7, "PRIORITY_SPEAKER": 8,
    "STREAM": 9, "VIEW_CHANNEL": 10, "SEND_MESSAGES": 11,
    "SEND_TTS_MESSAGES": 12, "MANAGE_MESSAGES": 13, "EMBED_LINKS": 14,
    "ATTACH_FILES": 15, "READ_MESSAGE_HISTORY": 16, "MENTION_EVERYONE": 17,
    "USE_EXTERNAL_EMOJIS": 18, "VIEW_GUILD_INSIGHTS": 19, "CONNECT": 20,
    "SPEAK": 21, "MUTE_MEMBERS": 22, "DEAFEN_MEMBERS": 23, "MOVE_MEMBERS": 24,
    "USE_VAD": 25, "CHANGE_NICKNAME": 26, "MANAGE_NICKNAMES": 27,
    "MANAGE_ROLES": 28, "MANAGE_WEBHOOKS": 29, "MANAGE_GUILD_EXPRESSIONS": 30,
    "USE_APPLICATION_COMMANDS": 31, "REQUEST_TO_SPEAK": 32,
    "MANAGE_EVENTS": 33, "MANAGE_THREADS": 34, "CREATE_PUBLIC_THREADS": 35,
    "CREATE_PRIVATE_THREADS": 36, "USE_EXTERNAL_STICKERS": 37,
    "SEND_MESSAGES_IN_THREADS": 38, "USE_EMBEDDED_ACTIVITIES": 39,
    "MODERATE_MEMBERS": 40, "SEND_VOICE_MESSAGES": 46, "SEND_POLLS": 49,
}


class CliError(Exception):
    pass


def env(name):
    val = os.environ.get(name)
    if not val:
        raise CliError(f"environment variable {name} is not set")
    return val


def request(method, path, body=None, retries=3):
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bot {env('DISCORD_BOT_TOKEN')}",
        "User-Agent": UA,
        "Content-Type": "application/json",
    }
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            if e.code == 429 and attempt < retries:
                try:
                    wait = float(json.loads(raw).get("retry_after", 1))
                except (ValueError, AttributeError):
                    wait = 1.0
                time.sleep(wait + 0.1)
                continue
            try:
                msg = json.loads(raw).get("message", raw)
            except ValueError:
                msg = raw
            raise CliError(f"Discord API {e.code} on {method} {path}: {msg}")
        except urllib.error.URLError as e:
            raise CliError(f"network error: {e.reason}")


def guild():
    return env("DISCORD_SERVER_ID")


def out(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def perm_names(bits):
    bits = int(bits)
    return [n for n, i in PERMISSIONS.items() if bits & (1 << i)]


def parse_perms(spec):
    """'VIEW_CHANNEL,SEND_MESSAGES' (or a raw integer) -> int bitfield."""
    if not spec:
        return 0
    spec = spec.strip()
    if spec.isdigit():
        return int(spec)
    bits = 0
    for name in spec.split(","):
        name = name.strip().upper()
        if not name:
            continue
        if name not in PERMISSIONS:
            raise CliError(f"unknown permission '{name}'. See `permissions list`.")
        bits |= 1 << PERMISSIONS[name]
    return bits


# ---- lookups -------------------------------------------------------------

def get_roles():
    return request("GET", f"/guilds/{guild()}/roles")


def get_channels():
    return request("GET", f"/guilds/{guild()}/channels")


def resolve(items, ref, kind):
    """Find an item by exact id or case-insensitive name; error if ambiguous."""
    if ref.isdigit():
        for it in items:
            if it["id"] == ref:
                return it
    matches = [it for it in items if it["name"].lower() == ref.lower().lstrip("@#")]
    if not matches:
        raise CliError(f"{kind} '{ref}' not found")
    if len(matches) > 1:
        ids = ", ".join(m["id"] for m in matches)
        raise CliError(f"{kind} name '{ref}' is ambiguous (ids: {ids}); use the id")
    return matches[0]


def resolve_channel(ref, only_type=None):
    chans = get_channels()
    if only_type is not None:
        chans = [c for c in chans if c["type"] == only_type]
    return resolve(chans, ref, "channel" if only_type is None else "category")


def resolve_target(spec):
    """'role:<name|id>' | 'member:<user id>' | '@everyone' -> (id, type int)."""
    if spec in ("@everyone", "everyone"):
        return guild(), 0  # @everyone role id == guild id
    kind, _, ref = spec.partition(":")
    if kind == "role" and ref:
        if ref.lower().lstrip("@") == "everyone":
            return guild(), 0
        return resolve(get_roles(), ref, "role")["id"], 0
    if kind in ("member", "user") and ref.isdigit():
        return ref, 1
    raise CliError("target must be '@everyone', 'role:<name|id>' or 'member:<user_id>'")


# ---- commands ------------------------------------------------------------

def cmd_roles_list(a):
    roles = sorted(get_roles(), key=lambda r: -r["position"])
    out([{
        "id": r["id"], "name": r["name"], "position": r["position"],
        "color": f"#{r['color']:06x}", "managed": r["managed"],
        "mentionable": r["mentionable"], "hoist": r["hoist"],
        "permissions": perm_names(r["permissions"]) if a.permissions else None,
    } if a.permissions else {
        "id": r["id"], "name": r["name"], "position": r["position"],
        "color": f"#{r['color']:06x}", "managed": r["managed"],
    } for r in roles])


def cmd_categories_list(a):
    chans = get_channels()
    cats = sorted((c for c in chans if c["type"] == 4), key=lambda c: c["position"])
    out([{
        "id": c["id"], "name": c["name"], "position": c["position"],
        "channel_count": sum(1 for x in chans if x.get("parent_id") == c["id"]),
    } for c in cats])


def cmd_channels_list(a):
    chans = get_channels()
    cats = {c["id"]: c["name"] for c in chans if c["type"] == 4}
    parent_id = None
    if a.category:
        parent_id = resolve_channel(a.category, only_type=4)["id"]
    rows = []
    for c in sorted(chans, key=lambda c: (c.get("position", 0))):
        if c["type"] == 4:
            continue
        if parent_id and c.get("parent_id") != parent_id:
            continue
        if a.type and TYPE_NAMES.get(c["type"]) != a.type:
            continue
        rows.append({
            "id": c["id"], "name": c["name"],
            "type": TYPE_NAMES.get(c["type"], str(c["type"])),
            "category": cats.get(c.get("parent_id")),
            "category_id": c.get("parent_id"),
            "topic": c.get("topic"),
        })
    out(rows)


def cmd_channels_create(a):
    body = {"name": a.name, "type": CHANNEL_TYPES[a.type]}
    if a.type == "category" and a.category:
        raise CliError("a category cannot have a parent category")
    if a.category:
        body["parent_id"] = resolve_channel(a.category, only_type=4)["id"]
    if a.topic:
        body["topic"] = a.topic
    if a.nsfw:
        body["nsfw"] = True
    if a.private:
        # Hide from @everyone; optionally grant to roles.
        view = 1 << PERMISSIONS["VIEW_CHANNEL"]
        overwrites = [{"id": guild(), "type": 0, "allow": "0", "deny": str(view)}]
        roles = get_roles() if a.allow_role else []
        for ref in a.allow_role or []:
            rid = resolve(roles, ref, "role")["id"]
            overwrites.append({"id": rid, "type": 0, "allow": str(view), "deny": "0"})
        body["permission_overwrites"] = overwrites
    elif a.allow_role:
        raise CliError("--allow-role requires --private")
    if a.dry_run:
        return out({"dry_run": True, "POST": f"/guilds/{guild()}/channels", "body": body})
    c = request("POST", f"/guilds/{guild()}/channels", body)
    out({"id": c["id"], "name": c["name"], "type": TYPE_NAMES.get(c["type"]),
         "parent_id": c.get("parent_id")})


def cmd_perms_show(a):
    ch = resolve_channel(a.channel)
    roles = {r["id"]: r["name"] for r in get_roles()}
    rows = []
    for ow in ch.get("permission_overwrites", []):
        rows.append({
            "target": f"role:{roles.get(ow['id'], ow['id'])}" if ow["type"] == 0
                      else f"member:{ow['id']}",
            "id": ow["id"],
            "allow": perm_names(ow["allow"]),
            "deny": perm_names(ow["deny"]),
        })
    out({"channel": {"id": ch["id"], "name": ch["name"]}, "overwrites": rows})


def cmd_perms_set(a):
    ch = resolve_channel(a.channel)
    tid, ttype = resolve_target(a.target)
    allow, deny = parse_perms(a.allow), parse_perms(a.deny)
    if allow & deny:
        raise CliError("a permission cannot be both allowed and denied")
    if not a.replace:
        # Merge with the existing overwrite so unrelated bits are preserved.
        cur = next((o for o in ch.get("permission_overwrites", []) if o["id"] == tid), None)
        if cur:
            old_allow, old_deny = int(cur["allow"]), int(cur["deny"])
            allow = (old_allow & ~deny) | allow
            deny = (old_deny & ~allow) | deny
    body = {"type": ttype, "allow": str(allow), "deny": str(deny)}
    if a.dry_run:
        return out({"dry_run": True, "PUT": f"/channels/{ch['id']}/permissions/{tid}",
                    "body": body, "allow": perm_names(allow), "deny": perm_names(deny)})
    request("PUT", f"/channels/{ch['id']}/permissions/{tid}", body)
    out({"channel": ch["name"], "target": a.target,
         "allow": perm_names(allow), "deny": perm_names(deny)})


def cmd_perms_clear(a):
    ch = resolve_channel(a.channel)
    tid, _ = resolve_target(a.target)
    if a.dry_run:
        return out({"dry_run": True, "DELETE": f"/channels/{ch['id']}/permissions/{tid}"})
    request("DELETE", f"/channels/{ch['id']}/permissions/{tid}")
    out({"channel": ch["name"], "target": a.target, "cleared": True})


def cmd_perms_list(a):
    out(sorted(PERMISSIONS))


def build_parser():
    p = argparse.ArgumentParser(prog="discord_cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="group", required=True)

    roles = sub.add_parser("roles", help="role queries").add_subparsers(dest="cmd", required=True)
    r = roles.add_parser("list", help="list roles (highest position first)")
    r.add_argument("--permissions", action="store_true", help="include permission names")
    r.set_defaults(fn=cmd_roles_list)

    cats = sub.add_parser("categories", help="category queries").add_subparsers(dest="cmd", required=True)
    cats.add_parser("list", help="list categories").set_defaults(fn=cmd_categories_list)

    ch = sub.add_parser("channels", help="channel queries/creation").add_subparsers(dest="cmd", required=True)
    c = ch.add_parser("list", help="list non-category channels")
    c.add_argument("--category", help="filter by category name or id")
    c.add_argument("--type", choices=sorted(set(TYPE_NAMES.values()) - {"category"}))
    c.set_defaults(fn=cmd_channels_list)

    c = ch.add_parser("create", help="create a channel (or category with --type category)")
    c.add_argument("name")
    c.add_argument("--type", choices=sorted(CHANNEL_TYPES), default="text")
    c.add_argument("--category", help="parent category name or id")
    c.add_argument("--topic")
    c.add_argument("--nsfw", action="store_true")
    c.add_argument("--private", action="store_true", help="hide from @everyone")
    c.add_argument("--allow-role", action="append", metavar="ROLE",
                   help="with --private: role (name/id) that may view; repeatable")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(fn=cmd_channels_create)

    pm = sub.add_parser("perms", help="channel permission overwrites").add_subparsers(dest="cmd", required=True)
    s = pm.add_parser("show", help="show overwrites on a channel")
    s.add_argument("channel", help="channel name or id")
    s.set_defaults(fn=cmd_perms_show)

    s = pm.add_parser("set", help="set allow/deny for a role or member (merges by default)")
    s.add_argument("channel", help="channel name or id")
    s.add_argument("target", help="@everyone | role:<name|id> | member:<user_id>")
    s.add_argument("--allow", default="", help="comma-separated permission names")
    s.add_argument("--deny", default="", help="comma-separated permission names")
    s.add_argument("--replace", action="store_true",
                   help="overwrite the existing entry instead of merging")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_perms_set)

    s = pm.add_parser("clear", help="remove a target's overwrite from a channel")
    s.add_argument("channel")
    s.add_argument("target")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_perms_clear)

    sub.add_parser("permissions", help="reference").add_subparsers(
        dest="cmd", required=True).add_parser("list", help="list permission names"
    ).set_defaults(fn=cmd_perms_list)
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
