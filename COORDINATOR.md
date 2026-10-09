# Run a Roblosats coordinator

Roblosats is RoboSats for Bitcoin on the BLAKE2b chain
([Kilombino/roblosats](https://github.com/Kilombino/roblosats)). A coordinator escrows the
trades: its Lightning node holds the bonds and the escrow while an order runs, it pays the
buyer, and it resolves disputes. It earns a small fee on every trade.

This guide sets one up the way Kilobot, the first coordinator, runs.

## What you need

- **LND on the BLAKE2b chain** with well-connected channels:
  - inbound liquidity to receive bonds and escrows;
  - outbound liquidity to pay buyers.
  
  Your largest order can't be bigger than what your routes can carry. Start small, for example
  6,000,000 sats, and raise it as liquidity grows.
- **A BLAKE2b full node** with RPC. The coordinator uses it to validate addresses for on-chain
  payouts.
- **An always-on Linux server** with Docker (compose v2), about 4 GB of RAM and 40 GB of disk.
- **Time to handle disputes.**

## 1. Get the code

```sh
git clone -b roblosats https://github.com/Kilombino/roblosats-deploy.git
git clone -b roblosats https://github.com/Kilombino/roblosats.git
```

## 2. Build the coordinator image

Build it from the Roblosats source. Do not use the official RoboSats image: the Roblosats
image adds the BTCB2 price feed, the chain's own fee rates, no devfund, configurable limits and
the Roblosats web client.

```sh
cd roblosats
docker build -f Dockerfile.roblosats -t roblosats:0.8.7-rl6 .
```

Use the tag of the release you are building. Then set `ROBLOSATS_TAG` in `compose.env` to the
same tag.

## 3. Identity

- **Onion address.** A vanity prefix is optional:
  `mkp224o -n 1 -d keys <prefix>`, where a 5-letter prefix takes seconds.
  Copy `hs_ed25519_secret_key`, `hs_ed25519_public_key` and `hostname` into
  `compose/env/<alias>/tor/<alias>/`, with mode 700 on the folder and 600 on the files.
- **Nostr key** for the coordinator (`nsec`). Orders are published on nostr as kind 38383,
  signed with it.
- **Telegram bot** from @BotFather. Users get notifications about their orders through it, and
  you get the "dispute opened" alerts.

## 4. Configure

```sh
cd roblosats-deploy/compose
mkdir -p env/<alias>/nginx
cp env-sample/roblosats/robosats.env env-sample/roblosats/compose.env \
   env-sample/roblosats/torrc env-sample/roblosats/relay.* env/<alias>/
cp env-sample/roblosats/nginx/local.conf env/<alias>/nginx/
chmod 600 env/<alias>/*.env
```

`env/` is gitignored, so your secrets never get committed. Fill in every `<…>` value:

- **`robosats.env`** — the coordinator.
  - LND connection: base64 of `tls.cert` and `admin.macaroon` (`base64 -w0 file`), and
    `LND_GRPC_HOST`.
  - Node RPC.
  - `SECRET_KEY` and the Postgres password (random values).
  - Telegram bot, nostr `nsec`, onion and hosts.
  - The values left in place are Kilobot's: fee 0.19%, 3% bond, orders of 101,000–6,000,000
    sats, on-chain payouts for buyers, `DEVFUND=0`. Change them if you want.
  - Keep `MARKET_PRICE_APIS=https://mempool.kilombino.com/neoxa-ticker`: the BTCB2 price from
    Neoxa, reachable over Tor. Other fiat currencies are converted with yadio.
  - `BTCB2_FALLBACK_USD` is used only if that feed stops answering.
- **`compose.env`** — paths and ports.
  - `SUFFIX` (container suffix, e.g. `-<alias>`), data paths, `WEB_LOCAL_PORT`.
  - The same Postgres password as in `robosats.env`.
  - `ROBLOSATS_TAG`.
- **`torrc`** — the hidden service folder name, `/var/lib/tor/<alias>/`.
- **`nginx/local.conf`** — replace `<yourvanity>` and `<lan.ip>`. The admin panel
  (`/coordinator`) answers only on your onion or LAN address, never on clearnet.
- **Relay files.**
  - `relay.external_urls.txt` lists `wss://relay.kilombino.com`, so your orders reach
    everyone.
  - Leave `relay.federation_urls.txt` empty, or list the other Roblosats coordinators'
    `ws://<onion>/relay`.
  - Do not sync with RoboSats relays: those orders are on the other chain.

## 5. Start

```sh
./coordinator.sh <alias> up -d
./coordinator.sh <alias> ps
docker exec -it rs-<alias> python3 manage.py createsuperuser   # the 'admin' user (ESCROW_USERNAME)
curl -s http://<lan ip>:<WEB_LOCAL_PORT>/api/info/
```

`/api/info/` should show `network: mainnet`, your node alias and LND version.
`/api/limits/` should show prices: about 1/100 of the SHA-256 chain's BTC price, plus a `BTC`
row with the BTCB2→BTC rate.

All services restart on their own after a reboot (`restart: always`).

Optional clearnet access: put the LAN port behind a Cloudflare tunnel (or any HTTPS reverse
proxy) at a hostname, and list that host in `HOST_NAME2` and `CSRF_TRUSTED_ORIGINS`.

## 6. Get told about disputes

`tools/dispute_watcher.py` messages you on Telegram when:

- an order goes into dispute;
- both sides have sent their statements;
- a dispute is resolved;
- a container stops;
- the price feed fails.

Create `~/.config/roblosats-watcher.env` with mode 600:

```
WATCH_SUFFIX=-<alias>
WATCH_TG_TOKEN=<bot token>
WATCH_TG_CHAT=<your telegram user id>
WATCH_ONION=<yourvanity>.onion
```

Then install `tools/roblosats-watcher.service` as a user service (instructions inside the file).
Send `/start` to your bot once, or Telegram won't let it message you.

Disputes are resolved in the admin panel (`/coordinator/api/order/<id>/change/`) with the
*maker wins* / *taker wins* actions, after reading both statements.

## 7. Before asking to join

- [ ] `/api/info/` and `/api/limits/` answer over your onion (test from Tor Browser).
- [ ] You opened an order on https://roblosats.kilombino.com pointing at your coordinator, and
      the bond invoice was created.
- [ ] At least one real trade went through end to end.
- [ ] The watcher messaged you; you can stop a container briefly to test it.
- [ ] Your LND has a backup: seed on paper plus `channel.backup` copied off the machine.
- [ ] You never restart the coordinator while an order is in progress (status 6–11). Check
      with:
      `docker exec rs-<alias> python3 manage.py shell -c "from api.models import Order;print(Order.objects.filter(status__in=range(6,12)).count())"`

## 8. Join the federation

Open an issue at https://github.com/Kilombino/roblosats/issues containing:

```json
"<alias>": {
  "longAlias": "<Your Name>", "shortAlias": "<alias>", "identifier": "<alias>",
  "description": "…", "motto": "…", "color": "#rrggbb", "established": "YYYY-MM-DD",
  "nostrHexPubkey": "<hex pubkey of your coordinator nostr key>",
  "contact": { "email": "…", "telegram": "…", "nostr": "npub…", "website": "…" },
  "badges": { "isFounder": false, "donatesToDevFund": 0, "hasGoodOpSec": true, "hasLargeLimits": false },
  "policies": { "Privacy Policy": "…", "Data Policy": "…" },
  "mainnet": { "onion": "http://<yourvanity>.onion", "clearnet": null, "i2p": null },
  "testnet": { "onion": null, "clearnet": null, "i2p": null },
  "mainnetNodesPubkeys": ["<your LN node pubkey>"], "testnetNodesPubkeys": [], "federated": true
}
```

Also include:

- a 200×200 avatar;
- a message signed by your node:
  `lncli signmessage "Roblosats coordinator <alias>: <onion>"`.

Once it's reviewed, you are added to `federation.json` and ship in the next web and app
release.

## Updating

Roblosats follows RoboSats releases (see `ROBLOSATS.md` in the source repo). To update:

1. Pull the new `roblosats` branch.
2. Rebuild the image with a new tag.
3. Set `ROBLOSATS_TAG`.
4. Run `./coordinator.sh <alias> up -d`, **with no order in progress**.

Questions: https://t.me/roblosats
