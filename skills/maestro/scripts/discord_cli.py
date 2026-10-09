#!/usr/bin/env python3
"""Discord server admin CLI: roles, members, categories, channels, channel permissions.

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
UA = "DiscordBot (https://github.com/p-sw/maestro-skill, 1.1)"

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


def parse_color(spec):
    """'#5865f2' | '5865f2' | '0' -> int."""
    try:
        return int(spec.lstrip("#"), 16)
    except ValueError:
        raise CliError(f"invalid color '{spec}'; use hex like #5865f2")


def normalize_name(name, ctype):
    """Discord lowercases text-like channel names and turns spaces into hyphens."""
    if ctype in ("text", "announcement", "forum"):
        return "-".join(name.lower().split())
    return name.lower()


# ---- lookups -------------------------------------------------------------

def get_roles():
    return request("GET", f"/guilds/{guild()}/roles")


def get_channels():
    return request("GET", f"/guilds/{guild()}/channels")


_BOT_ID = []


def bot_id():
    if not _BOT_ID:
        _BOT_ID.append(request("GET", "/users/@me")["id"])
    return _BOT_ID[0]


def get_members():
    """All guild members (needs the Server Members privileged intent)."""
    members, after = [], "0"
    while True:
        page = request("GET", f"/guilds/{guild()}/members?limit=1000&after={after}")
        members.extend(page)
        if len(page) < 1000:
            return members
        after = page[-1]["user"]["id"]


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
    """'role:<name|id>' | 'member:<user id>' | '@everyone' | 'bot' -> (id, type int)."""
    if spec in ("@everyone", "everyone"):
        return guild(), 0  # @everyone role id == guild id
    if spec == "bot":
        return bot_id(), 1
    kind, _, ref = spec.partition(":")
    if kind == "role" and ref:
        if ref.lower().lstrip("@") == "everyone":
            return guild(), 0
        return resolve(get_roles(), ref, "role")["id"], 0
    if kind in ("member", "user") and ref.isdigit():
        return ref, 1
    raise CliError("target must be '@everyone', 'bot', 'role:<name|id>' or 'member:<user_id>'")


def member_row(m, roles=None):
    u = m["user"]
    row = {"id": u["id"], "username": u["username"],
           "display_name": m.get("nick") or u.get("global_name") or u["username"]}
    if roles is not None:
        row["roles"] = [roles.get(r, r) for r in m.get("roles", [])]
    return row


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


def cmd_roles_create(a):
    same = [r for r in get_roles() if r["name"].lower() == a.name.lower()]
    if len(same) == 1 and a.exist_ok:
        return out({"id": same[0]["id"], "name": same[0]["name"], "created": False})
    if same:
        ids = ", ".join(r["id"] for r in same)
        hint = "" if a.exist_ok else "; pass --exist-ok to reuse it"
        raise CliError(f"role '{a.name}' already exists (ids: {ids}){hint}")
    body = {"name": a.name, "permissions": str(parse_perms(a.permissions)),
            "hoist": a.hoist, "mentionable": a.mentionable}
    if a.color:
        body["color"] = parse_color(a.color)
    if a.dry_run:
        return out({"dry_run": True, "POST": f"/guilds/{guild()}/roles", "body": body})
    r = request("POST", f"/guilds/{guild()}/roles", body)
    out({"id": r["id"], "name": r["name"], "created": True})


def cmd_roles_edit(a):
    role = resolve(get_roles(), a.role, "role")
    body = {}
    if a.name:
        body["name"] = a.name
    if a.color:
        body["color"] = parse_color(a.color)
    if a.hoist is not None:
        body["hoist"] = a.hoist
    if a.mentionable is not None:
        body["mentionable"] = a.mentionable
    if a.permissions is not None:
        body["permissions"] = str(parse_perms(a.permissions))
    if not body:
        raise CliError("nothing to change; pass --name, --color, --[no-]hoist, "
                       "--[no-]mentionable or --permissions")
    path = f"/guilds/{guild()}/roles/{role['id']}"
    if a.dry_run:
        return out({"dry_run": True, "PATCH": path, "body": body})
    r = request("PATCH", path, body)
    out({"id": r["id"], "name": r["name"], "color": f"#{r['color']:06x}",
         "hoist": r["hoist"], "mentionable": r["mentionable"],
         "permissions": perm_names(r["permissions"])})


def member_role_change(a, method):
    if not a.user.isdigit():
        raise CliError("USER must be a numeric Discord user id")
    role = resolve(get_roles(), a.role, "role")
    path = f"/guilds/{guild()}/members/{a.user}/roles/{role['id']}"
    if a.dry_run:
        return out({"dry_run": True, method: path})
    request(method, path)
    out({"role": role["name"], "user": a.user, "assigned": method == "PUT"})


def cmd_roles_assign(a):
    member_role_change(a, "PUT")


def cmd_roles_unassign(a):
    member_role_change(a, "DELETE")


def cmd_roles_members(a):
    role = resolve(get_roles(), a.role, "role")
    out([member_row(m) for m in get_members() if role["id"] in m.get("roles", [])])


def cmd_members_show(a):
    if not a.user.isdigit():
        raise CliError("USER must be a numeric Discord user id")
    m = request("GET", f"/guilds/{guild()}/members/{a.user}")
    out(member_row(m, {r["id"]: r["name"] for r in get_roles()}))


def cmd_bot_whoami(a):
    u = request("GET", "/users/@me")
    out({"id": u["id"], "username": u["username"]})


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
    chans = get_channels()
    parent_id = None
    if a.category:
        parent_id = resolve([c for c in chans if c["type"] == 4], a.category, "category")["id"]
        body["parent_id"] = parent_id
    wanted = normalize_name(a.name, a.type)
    same = [c for c in chans if c["type"] == body["type"]
            and c.get("parent_id") == parent_id and c["name"].lower() == wanted]
    if len(same) == 1 and a.exist_ok:
        c = same[0]
        return out({"id": c["id"], "name": c["name"], "type": TYPE_NAMES.get(c["type"]),
                    "parent_id": c.get("parent_id"), "created": False})
    if same:
        ids = ", ".join(c["id"] for c in same)
        hint = "" if a.exist_ok else "; pass --exist-ok to reuse it"
        raise CliError(f"channel '{a.name}' already exists here (ids: {ids}){hint}")
    if a.topic:
        body["topic"] = a.topic
    if a.nsfw:
        body["nsfw"] = True
    if a.private:
        # Hide from @everyone; optionally grant to roles, members and this bot.
        view = 1 << PERMISSIONS["VIEW_CHANNEL"]
        overwrites = [{"id": guild(), "type": 0, "allow": "0", "deny": str(view)}]
        roles = get_roles() if a.allow_role else []
        for ref in a.allow_role or []:
            rid = resolve(roles, ref, "role")["id"]
            overwrites.append({"id": rid, "type": 0, "allow": str(view), "deny": "0"})
        members = list(a.allow_member or [])
        if a.allow_bot:
            members.append(bot_id())
        for uid in members:
            if not uid.isdigit():
                raise CliError(f"--allow-member needs a numeric user id, got '{uid}'")
            overwrites.append({"id": uid, "type": 1, "allow": str(view), "deny": "0"})
        body["permission_overwrites"] = overwrites
    elif a.allow_role or a.allow_member or a.allow_bot:
        raise CliError("--allow-role/--allow-member/--allow-bot require --private")
    if a.dry_run:
        return out({"dry_run": True, "POST": f"/guilds/{guild()}/channels", "body": body})
    c = request("POST", f"/guilds/{guild()}/channels", body)
    out({"id": c["id"], "name": c["name"], "type": TYPE_NAMES.get(c["type"]),
         "parent_id": c.get("parent_id"), "created": True})


def cmd_channels_edit(a):
    chans = get_channels()
    ch = resolve(chans, a.channel, "channel")
    body = {}
    if a.name:
        body["name"] = a.name
    if a.topic is not None:
        body["topic"] = a.topic
    if a.category and a.no_category:
        raise CliError("use either --category or --no-category")
    if a.category:
        if ch["type"] == 4:
            raise CliError("a category cannot have a parent category")
        body["parent_id"] = resolve([c for c in chans if c["type"] == 4],
                                    a.category, "category")["id"]
    if a.no_category:
        body["parent_id"] = None
    if not body:
        raise CliError("nothing to change; pass --name, --topic, --category or --no-category")
    path = f"/channels/{ch['id']}"
    if a.dry_run:
        return out({"dry_run": True, "PATCH": path, "body": body})
    c = request("PATCH", path, body)
    out({"id": c["id"], "name": c["name"], "type": TYPE_NAMES.get(c["type"]),
         "parent_id": c.get("parent_id"), "topic": c.get("topic")})


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

    roles = sub.add_parser("roles", help="role queries/management").add_subparsers(dest="cmd", required=True)
    r = roles.add_parser("list", help="list roles (highest position first)")
    r.add_argument("--permissions", action="store_true", help="include permission names")
    r.set_defaults(fn=cmd_roles_list)

    r = roles.add_parser("create", help="create a role (no server-wide permissions by default)")
    r.add_argument("name")
    r.add_argument("--color", help="hex color such as #5865f2")
    r.add_argument("--hoist", action="store_true", help="show separately in the member list")
    r.add_argument("--mentionable", action="store_true")
    r.add_argument("--permissions", default="", help="server-wide permission names (default none)")
    r.add_argument("--exist-ok", action="store_true", help="reuse a role with the same name")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_roles_create)

    r = roles.add_parser("edit", help="rename or restyle a role")
    r.add_argument("role", help="role name or id")
    r.add_argument("--name")
    r.add_argument("--color", help="hex color such as #5865f2")
    r.add_argument("--hoist", dest="hoist", action="store_const", const=True)
    r.add_argument("--no-hoist", dest="hoist", action="store_const", const=False)
    r.add_argument("--mentionable", dest="mentionable", action="store_const", const=True)
    r.add_argument("--no-mentionable", dest="mentionable", action="store_const", const=False)
    r.add_argument("--permissions", help="replace server-wide permissions ('' or 0 clears)")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_roles_edit)

    for name, fn, what in (("assign", cmd_roles_assign, "give a role to a member"),
                           ("unassign", cmd_roles_unassign, "take a role from a member")):
        r = roles.add_parser(name, help=what)
        r.add_argument("role", help="role name or id")
        r.add_argument("user", help="Discord user id")
        r.add_argument("--dry-run", action="store_true")
        r.set_defaults(fn=fn)

    r = roles.add_parser("members", help="list members holding a role (Server Members intent)")
    r.add_argument("role", help="role name or id")
    r.set_defaults(fn=cmd_roles_members)

    mem = sub.add_parser("members", help="member queries").add_subparsers(dest="cmd", required=True)
    m = mem.add_parser("show", help="show a member and their roles")
    m.add_argument("user", help="Discord user id")
    m.set_defaults(fn=cmd_members_show)

    bot = sub.add_parser("bot", help="the bot itself").add_subparsers(dest="cmd", required=True)
    bot.add_parser("whoami", help="print the bot's user id and name").set_defaults(fn=cmd_bot_whoami)

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
    c.add_argument("--allow-member", action="append", metavar="USER_ID",
                   help="with --private: member that may view; repeatable")
    c.add_argument("--allow-bot", action="store_true",
                   help="with --private: keep this bot able to view the channel")
    c.add_argument("--exist-ok", action="store_true",
                   help="reuse a same-named channel of this type in the same category")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(fn=cmd_channels_create)

    c = ch.add_parser("edit", help="rename, retopic or move a channel")
    c.add_argument("channel", help="channel name or id")
    c.add_argument("--name")
    c.add_argument("--topic", help="new topic ('' clears it)")
    c.add_argument("--category", help="move under this category (name or id)")
    c.add_argument("--no-category", action="store_true", help="move out of any category")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(fn=cmd_channels_edit)

    pm = sub.add_parser("perms", help="channel permission overwrites").add_subparsers(dest="cmd", required=True)
    s = pm.add_parser("show", help="show overwrites on a channel")
    s.add_argument("channel", help="channel name or id")
    s.set_defaults(fn=cmd_perms_show)

    s = pm.add_parser("set", help="set allow/deny for a role or member (merges by default)")
    s.add_argument("channel", help="channel name or id")
    s.add_argument("target", help="@everyone | bot | role:<name|id> | member:<user_id>")
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
