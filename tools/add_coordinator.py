#!/usr/bin/env python3
"""
Add (or update) a coordinator in the Roblosats federation, in one go.

    tools/add_coordinator.py coordinator.json --src ../src/roblosats [--bridge-port 9102] [--signature <zbase>]

coordinator.json is the coordinator's entry as federation.json keeps it (see
federation-template.json next to this script). The script:

  1. checks the entry: alias, onion v3, 64-hex nostr key, LN node ids, colour, date;
  2. with --signature, checks the coordinator's LN signature of
     "Roblosats federation: <onion host>" against its node id (lncli verifymessage
     on our own LND), so the entry comes from whoever runs that node;
  3. writes it into BOTH federation.json files of the Roblosats source
     (frontend/static and api), keeping the others in their order;
  4. for an onion-only coordinator and --bridge-port, adds its bridge to the web
     server (web-roblosats/bridges.conf and its socat service in docker-compose.yml),
     so the clearnet web at roblosats.kilombino.com reaches it over Tor.

Nothing is committed, built or restarted: the script prints what to do next.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEPLOY = HERE.parent
ONION = re.compile(r"^http://[a-z2-7]{56}\.onion$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NODE = re.compile(r"^0[23][0-9a-f]{64}$")
REQUIRED = ["longAlias", "shortAlias", "identifier", "description", "motto", "color", "established",
            "nostrHexPubkey", "contact", "badges", "policies", "mainnet", "testnet",
            "mainnetNodesPubkeys", "testnetNodesPubkeys", "federated"]


def fail(msg):
    sys.exit(f"✗ {msg}")


def check(e):
    missing = [k for k in REQUIRED if k not in e]
    if missing:
        fail(f"missing fields: {', '.join(missing)}")
    alias = e["shortAlias"]
    if not re.fullmatch(r"[a-z0-9]{2,20}", alias) or e["identifier"] != alias:
        fail("shortAlias must be 2-20 lowercase letters/digits, and identifier the same")
    if not HEX64.match(e["nostrHexPubkey"] or ""):
        fail("nostrHexPubkey must be the coordinator's nostr public key in hex (64 chars), not an npub")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", e["color"]):
        fail("color must look like #2e7dff")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["established"]):
        fail("established must be YYYY-MM-DD")
    m = e["mainnet"]
    if not m.get("onion") or not ONION.match(m["onion"]):
        fail("mainnet.onion must be http://<56 chars>.onion (no trailing slash)")
    if m.get("clearnet") and not m["clearnet"].startswith("https://"):
        fail("mainnet.clearnet must be https:// or null")
    nodes = e["mainnetNodesPubkeys"]
    if not nodes or not all(NODE.match(n) for n in nodes):
        fail("mainnetNodesPubkeys: at least one LN node id (66 hex chars)")
    if e["federated"] is not True:
        fail("federated must be true")
    return alias


def verify_signature(e, sig):
    host = e["mainnet"]["onion"].removeprefix("http://")
    msg = f"Roblosats federation: {host}"
    out = subprocess.run(["docker", "exec", "lnd-blake2b", "lncli", "verifymessage", "--msg", msg, "--sig", sig],
                         capture_output=True, text=True)
    if out.returncode != 0:
        fail(f"lncli verifymessage failed: {out.stderr.strip()}")
    r = json.loads(out.stdout)
    if not r.get("valid") or r.get("pubkey") not in e["mainnetNodesPubkeys"]:
        fail(f"the signature is from {r.get('pubkey')}, not from the coordinator's node")
    print(f"✓ LN signature of \"{msg}\" by {r['pubkey'][:16]}…")


def write_federation(src, alias, e):
    for rel in ("frontend/static/federation.json", "api/federation.json"):
        p = src / rel
        d = json.loads(p.read_text())
        new = alias not in d
        d[alias] = e
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        print(f"✓ {'added to' if new else 'updated in'} {rel}")


def add_bridge(alias, onion, port):
    host = onion.removeprefix("http://")
    conf = DEPLOY / "web-roblosats" / "bridges.conf"
    text = conf.read_text()
    if f"location /mainnet/{alias}/" in text:
        print(f"· bridge for {alias} already in bridges.conf")
    else:
        conf.write_text(text.rstrip("\n") + f"""

location /mainnet/{alias}/ {{
    proxy_pass http://127.0.0.1:{port}/;
    proxy_http_version 1.1;
    proxy_set_header Host {host};
    proxy_set_header Origin http://{host};
    proxy_set_header Referer "";
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 300s;
    proxy_connect_timeout 60s;
}}
""")
        print(f"✓ bridge /mainnet/{alias}/ → 127.0.0.1:{port} in bridges.conf")
    compose = DEPLOY / "web-roblosats" / "docker-compose.yml"
    text = compose.read_text()
    if f"bridge-{alias}:" in text:
        print(f"· socat service for {alias} already in docker-compose.yml")
    else:
        if f"TCP-LISTEN:{port}," in text:
            fail(f"port {port} is already used by another bridge")
        compose.write_text(text.rstrip("\n") + f"""
  bridge-{alias}:
    image: alpine/socat:1.8.0.1
    container_name: roblosats-bridge-{alias}
    restart: always
    network_mode: service:tor
    command: ["TCP-LISTEN:{port},fork,reuseaddr,bind=127.0.0.1", "SOCKS4A:127.0.0.1:{host}:80,socksport=9050"]
""")
        print(f"✓ socat service bridge-{alias} in docker-compose.yml")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entry", type=Path)
    ap.add_argument("--src", type=Path, default=DEPLOY.parent / "src" / "roblosats")
    ap.add_argument("--signature", help="the coordinator's lncli signmessage of 'Roblosats federation: <onion host>'")
    ap.add_argument("--bridge-port", type=int, help="onion-only: local port of its bridge (9101 is marcanotrades)")
    a = ap.parse_args()
    e = json.loads(a.entry.read_text())
    alias = check(e)
    print(f"✓ entry for {e['longAlias']} ({alias}) looks right")
    if a.signature:
        verify_signature(e, a.signature)
    else:
        print("! no --signature: the entry is not proven to come from the node's operator")
    write_federation(a.src, alias, e)
    if not e["mainnet"].get("clearnet"):
        if a.bridge_port:
            add_bridge(alias, e["mainnet"]["onion"], a.bridge_port)
        else:
            print("! onion only and no --bridge-port: roblosats.kilombino.com (clearnet) won't reach it")
    print(f"""
Next:
  1. git -C {a.src} diff; commit on branch roblosats; new rl tag + release (server and app)
  2. web: copy the new build to web-roblosats/dist; docker compose -f web-roblosats/docker-compose.yml up -d
  3. Kilobot: new image (the API serves federation.json too) when no order is in status 6-11
  4. app (Android, Umbrel, StartOS): new versions with the federation inside""")


if __name__ == "__main__":
    main()
