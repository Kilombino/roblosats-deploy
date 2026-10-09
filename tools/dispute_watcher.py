#!/usr/bin/env python3
"""
Roblosats coordinator watcher: tells the operator on Telegram about the coordinator's disputes,
any of its containers going down and the price feed failing. Run it as a systemd service.

Configuration (environment):
  WATCH_SUFFIX     container suffix used in compose.env (SUFFIX), e.g. "-kilobot"
  WATCH_TG_TOKEN   Telegram bot token (the coordinator's bot works; /start it first)
  WATCH_TG_CHAT    your Telegram user id
  WATCH_ONION      the coordinator's onion (for the admin links)
  WATCH_PRICE_URL  price feed to check (default https://mempool.kilombino.com/neoxa-ticker)
  WATCH_STATE      state file (default ~/.local/state/roblosats-watcher.json)

- Disputes: every 60 s, the orders in dispute (status 11 "in dispute", 16 "waiting for
  resolution"); one message per order and status change, and one when it is resolved.
- Health: every 10 min, the coordinator's containers; one message when one stops, one when back.
- Price: every 10 min, the BTCB2 price feed; if it stops, the coordinator runs on BTCB2_FALLBACK_USD.
"""
import json, os, subprocess, time, urllib.request, urllib.parse
from datetime import datetime, timezone

SUFFIX = os.environ.get("WATCH_SUFFIX", "-kilobot")
STATE = os.path.expanduser(os.environ.get("WATCH_STATE", "~/.local/state/roblosats-watcher.json"))
CHAT = os.environ["WATCH_TG_CHAT"]
ONION = os.environ.get("WATCH_ONION", "")
PRICE_URL = os.environ.get("WATCH_PRICE_URL", "https://mempool.kilombino.com/neoxa-ticker")
CONTAINERS = [c + SUFFIX for c in ["tor", "rs", "daphne", "sql", "redis", "nginx", "invo",
                                    "clord", "cele", "beat", "tg", "relay"]]
STATUS = {11: "⚖️ In dispute", 16: "📝 Waiting for your resolution (statements in)",
          17: "✅ Resolved: maker lost", 18: "✅ Resolved: taker lost"}

QUERY = r'''
import json
from api.models import Order
out=[]
for o in Order.objects.filter(is_disputed=True).order_by("-id")[:200]:
    out.append({"id":o.id,"status":o.status,"amount":o.last_satoshis or o.t0_satoshis,
                "currency":o.currency.get_currency_display() if o.currency else None,"fiat":str(o.amount),
                "maker_stmt":bool(o.maker_statement),"taker_stmt":bool(o.taker_statement)})
print("JSON:"+json.dumps(out))
'''

def token():
    return os.environ["WATCH_TG_TOKEN"]

def tg(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "disable_web_page_preview": "true"}).encode()
    try: urllib.request.urlopen(f"https://api.telegram.org/bot{token()}/sendMessage", data, timeout=20).read()
    except Exception as e: print("telegram:", e, flush=True)

def load():
    try: return json.load(open(STATE))
    except Exception: return {"disputes": {}, "down": []}

def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"; json.dump(s, open(tmp, "w")); os.replace(tmp, STATE)

def disputes():
    r = subprocess.run(["docker", "exec", "rs" + SUFFIX, "python3", "manage.py", "shell", "-c", QUERY],
                       capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("JSON:"): return json.loads(line[5:])
    raise RuntimeError((r.stderr or r.stdout)[-300:])

def check_disputes(s):
    seen = s["disputes"]
    for o in disputes():
        k = str(o["id"]); st = o["status"]
        if seen.get(k) == st: continue
        if st in STATUS:
            stm = ("maker ✅" if o["maker_stmt"] else "maker —") + " · " + ("taker ✅" if o["taker_stmt"] else "taker —")
            admin = f"\nAdmin (over Tor): http://{ONION}/coordinator/api/order/{o['id']}/change/" if ONION else ""
            tg(f"Coordinator · order {o['id']}: {STATUS[st]}\n"
               f"{o['amount']:,} sats ({o['fiat']} {o['currency']})\nStatements: {stm}" + admin)
        seen[k] = st

def check_health(s):
    r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True)
    up = set(r.stdout.split())
    down = [c for c in CONTAINERS if c not in up]
    for c in down:
        if c not in s["down"]: tg(f"⚠️ Container {c} is down.")
    for c in s["down"]:
        if c not in down: tg(f"✅ Container {c} is back up.")
    s["down"] = down

def check_price(s):
    ok = False
    try:
        # Cloudflare turns away urllib's default user agent (403).
        req = urllib.request.Request(PRICE_URL,
                                     headers={"User-Agent": "roblosats-watcher/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=20))
        ok = float(d["ticker"]["lastPrice"]) > 0
    except Exception as e:
        print("price:", e, flush=True)
    if not ok and not s.get("price_down"):
        tg("⚠️ The BTCB2 price feed is down; the coordinator uses BTCB2_FALLBACK_USD from robosats.env. Update it if needed.")
    if ok and s.get("price_down"):
        tg("✅ The BTCB2 price feed is back.")
    s["price_down"] = not ok

def main():
    s = load(); last_health = 0
    while True:
        try: check_disputes(s)
        except Exception as e: print(datetime.now(timezone.utc).isoformat(), "disputes:", e, flush=True)
        if time.time() - last_health > 600:
            try: check_health(s)
            except Exception as e: print("health:", e, flush=True)
            check_price(s)
            last_health = time.time()
        save(s); time.sleep(60)

if __name__ == "__main__":
    main()
