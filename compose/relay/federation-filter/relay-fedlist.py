#!/usr/bin/env python3
"""Keeps a relay's coordinator allowlist (allowed-order-pubkeys.txt) in step with federation.json.

The relay's write policy stores order events (kind 38383) only from the coordinators in that list,
and ratings (31986) only of them; the sync scripts read the same list. This fetches the official
federation.json, takes every coordinator's nostrHexPubkey and rewrites the pubkey lines of the list,
keeping its comments and its "sync-kinds" line. It writes only when the set changed, and on any
failure (fetch, JSON, validation) it leaves the last good list alone: never an empty one.

A line "manual" in the list stops the updates (the list is then yours to edit).

  relay-fedlist.py --url URL --list FILE [--own HEX] [--require-own] [--in-place]
                   [--seed FILE] [--stamp FILE --every SECONDS] [--proxy HOST:PORT]
                   [--tg-token-file FILE --tg-token-var VAR --tg-chat ID --label NAME]
                   [--fail-marker FILE]

--own HEX       this coordinator's pubkey (also $OWN_PUBKEY, or --own-file). With --require-own the
                update fails unless federation.json lists it; without, it is kept in the list anyway
                (a coordinator not yet in federation.json must still be able to publish its orders).
--in-place      rewrite the file in place (same inode): needed for a single-file docker bind mount.
                Otherwise a temporary file is renamed over it.
--stamp/--every check at most once every SECONDS (for a caller that runs more often); after a
                failure, retry in ten minutes.
--url           https URL, or a local path (for tests).
Exit status: 0 when the list is current (changed or not, or skipped), 1 on failure.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_COORDINATORS = 100


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + msg, flush=True)


def fetch(url, proxy):
    if not re.match(r"^https?://", url):
        with open(url, "rb") as f:
            return f.read()
    cmd = ["curl", "-fsSL", "--max-time", "60", "--retry", "2", "-H", "Cache-Control: no-cache"]
    if proxy:
        cmd += ["--socks5-hostname", proxy]
    return subprocess.run(cmd + [url], check=True, capture_output=True).stdout


def federation_keys(raw):
    """[(alias, hex)] in federation.json order; raises ValueError when it does not look right."""
    data = json.loads(raw)
    if not isinstance(data, dict) or not data:
        raise ValueError("federation.json is not a non-empty object")
    keys, bad = [], []
    for alias, c in data.items():
        pk = c.get("nostrHexPubkey") if isinstance(c, dict) else None
        pk = pk.strip().lower() if isinstance(pk, str) else ""
        if HEX64.match(pk):
            if pk not in (k for _, k in keys):
                keys.append((re.sub(r"[^A-Za-z0-9_.-]", "", str(alias))[:40] or "?", pk))
        else:
            bad.append(str(alias))
    if bad:
        log("warning: skipped coordinators without a valid nostrHexPubkey: " + ", ".join(bad))
    if not 1 <= len(keys) <= MAX_COORDINATORS:
        raise ValueError("unexpected number of coordinators: %d" % len(keys))
    return keys


def split_list(text):
    """(lines before the first pubkey, pubkeys, other lines after it)."""
    pre, keys, post = [], [], []
    for line in text.splitlines():
        bare = re.sub(r"\s+", "", line.split("#", 1)[0]).lower()
        if HEX64.match(bare):
            keys.append(bare)
        elif keys:
            post.append(line)
        else:
            pre.append(line)
    return pre, keys, post


def write(path, text, in_place):
    if in_place:
        with open(path, "r+") as f:
            f.seek(0)
            f.write(text)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
        # A reader that caught the file half written in this same second would not see a new
        # mtime (seconds): move it on once more.
        time.sleep(1.1)
        os.utime(path)
    else:
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(prefix=".fedlist.", dir=d)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)


def telegram(a, text):
    if not (a.tg_token_file and a.tg_token_var and a.tg_chat):
        return
    try:
        token = ""
        for line in open(a.tg_token_file):
            if line.startswith(a.tg_token_var + "="):
                token = line.split("=", 1)[1].strip().strip("'\"")
        if not token:
            return
        data = urllib.parse.urlencode({"chat_id": a.tg_chat, "text": text,
                                       "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % token, data,
                               timeout=20).read()
    except Exception as e:  # never fail the update for a notice
        log("telegram notice failed: %s" % type(e).__name__)


def stamp_due(a):
    if not (a.stamp and a.every):
        return True
    try:
        return time.time() - os.stat(a.stamp).st_mtime >= a.every
    except OSError:
        return True


def set_stamp(a, ok):
    if not (a.stamp and a.every):
        return
    try:
        open(a.stamp, "a").close()
        t = time.time() if ok else time.time() - a.every + 600
        os.utime(a.stamp, (t, t))
    except OSError:
        pass


def update(a):
    own = (a.own or os.environ.get("OWN_PUBKEY", "")).strip().lower()
    if not own and a.own_file:
        try:
            own = open(a.own_file).read().split("#", 1)[0].strip().lower()
        except OSError:
            own = ""
    if own and not HEX64.match(own):
        raise ValueError("own pubkey is not 64 hex characters")
    if a.require_own and not own:
        raise ValueError("--require-own without an own pubkey")

    if not os.path.exists(a.list):
        if not a.seed:
            raise ValueError("%s does not exist" % a.list)
        with open(a.seed) as f:
            write(a.list, f.read(), False)
        log("created %s from %s" % (a.list, a.seed))
    with open(a.list) as f:
        current = f.read()
    pre, old_keys, post = split_list(current)
    if any(re.sub(r"\s+", "", l.split("#", 1)[0]) == "manual" for l in pre + post):
        log("list marked manual, not updated")
        return False

    fed = federation_keys(fetch(a.url, a.proxy))
    fed_hex = [k for _, k in fed]
    if own and own not in fed_hex:
        if a.require_own:
            raise ValueError("this coordinator (%s...) is not in federation.json" % own[:12])
        fed.append(("this coordinator, not in federation.json yet", own))
        fed_hex.append(own)
    old, new = set(old_keys), set(fed_hex)
    removed = old - new
    if len(old) >= 2 and len(removed) * 2 > len(old):
        raise ValueError("federation.json would remove %d of the %d coordinators: not applied"
                         % (len(removed), len(old)))

    aliases = dict((k, n) for n, k in fed)
    lines = list(pre)
    stamp_line = "# Source: %s (nostrHexPubkey), updated by relay-fedlist on %s." % (
        a.url if re.match(r"^https?://", a.url) else "federation.json",
        time.strftime("%Y-%m-%d"))
    for i, l in enumerate(lines):
        if l.startswith("# Source:"):
            lines[i] = stamp_line
            break
    else:
        lines.append(stamp_line)
    lines += ["%s  # %s" % (k, aliases[k]) for k in fed_hex]
    lines += post
    text = "\n".join(lines) + "\n"

    if old == new and not (len(old_keys) != len(set(old_keys))):
        log("unchanged (%d coordinators)" % len(new))
        return False
    write(a.list, text, a.in_place)
    added = [aliases[k] + " " + k[:12] for k in fed_hex if k not in old]
    gone = [k[:12] for k in old_keys if k in removed]
    summary = "%d coordinators; added: %s; removed: %s" % (
        len(new), ", ".join(added) or "none", ", ".join(gone) or "none")
    log("UPDATED %s: %s" % (a.list, summary))
    telegram(a, "%s: lista de coordinadores del relay actualizada desde federation.json\n%s"
             % (a.label or a.list, summary))
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", required=True)
    p.add_argument("--list", required=True)
    p.add_argument("--own")
    p.add_argument("--own-file")
    p.add_argument("--require-own", action="store_true")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("--seed")
    p.add_argument("--stamp")
    p.add_argument("--every", type=int, default=0)
    p.add_argument("--proxy")
    p.add_argument("--tg-token-file")
    p.add_argument("--tg-token-var")
    p.add_argument("--tg-chat")
    p.add_argument("--label")
    p.add_argument("--fail-marker")
    a = p.parse_args()
    if not stamp_due(a):
        return 0
    try:
        update(a)
        set_stamp(a, True)
        if a.fail_marker and os.path.exists(a.fail_marker):
            os.unlink(a.fail_marker)
        return 0
    except Exception as e:
        set_stamp(a, False)
        msg = "%s: %s" % (type(e).__name__, e)
        log("FAILED, keeping the last good list: " + msg)
        # Tell once per run of failures (--fail-marker), not every hour.
        if a.fail_marker and not os.path.exists(a.fail_marker):
            open(a.fail_marker, "w").write(msg + "\n")
            telegram(a, "%s: no se pudo actualizar la lista de coordinadores (%s); sigue la anterior"
                     % (a.label or a.list, msg))
        return 1


if __name__ == "__main__":
    sys.exit(main())
