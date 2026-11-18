# Run a Roblosats coordinator

Roblosats is RoboSats for Bitcoin on the BLAKE2b chain
([Kilombino/roblosats](https://github.com/Kilombino/roblosats)). A coordinator escrows the
trades: its Lightning node holds the bonds and the escrow while an order runs, it pays the
buyer, and it resolves disputes. It earns a small fee on every trade.

This guide sets one up the way Kilobot, the first coordinator, runs.

On a home node there is a packaged coordinator with the same server, relay, onion and setup page:

- **Umbrel**: the Roblosats Coordinator app of the Kilombino store
  ([Kilombino/umbrel-store](https://github.com/Kilombino/umbrel-store)), with Lightning Fork and a
  BLAKE2b node from the PaulsCode.Com store.
- **StartOS 0.4 (Start9)**: the Roblosats Coordinator package of the Kilombino registry
  (`https://registry.kilombino.com`,
  [Kilombino/roblosats-coordinator-startos](https://github.com/Kilombino/roblosats-coordinator-startos)).
  Install Bitcoin Knots (BLAKE2b) Companion and Lightning Fork from Paul's registry
  (`https://start9.paulscode.com`) first, create the Lightning Fork wallet, then install it.

The packaged coordinators run Roblosats 0.9.5 (Lightning-only by default; on-chain escrow is an
optional section of their Settings).

Both still need what is listed below (channels, a synced node, time for disputes); read the rest of
this guide for how a coordinator works. Their Settings start from Kilobot's values (fee 0.19 %, maker
share 10.5 %, orders 101,000 to 100,000,000 sats, on-chain payouts 101,000 to 6,000,000 sats) and show
them as *Recommended*; lower the largest order to what your channels carry. Their **Backup** page
exports one file encrypted with a passphrase (OpenPGP, AES-256: onion keys, Nostr key, secrets,
settings and a database dump) and imports it onto a new install, on Umbrel or StartOS, bringing the
coordinator back with the same onion and Nostr key. Never run the old and the restored one at once.

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
image adds the BTCB2 price feed, the chain's own fee rates, a devfund that goes to the Roblosats
maintainer, configurable limits and
the Roblosats web client.

```sh
cd roblosats
docker build -f Dockerfile.roblosats -t roblosats:0.9.5 .
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
  - Devfund: `DEVFUND` is the fraction of each successful order's proceeds sent by keysend to the
    Roblosats maintainer's node (`DEVFUND_PUBKEY`, or if empty the image's `devfund_pubkey.json`), which pays
    for keeping Roblosats and its security fixes going. It is optional. With 20% or more your
    coordinator gets the DevFund badge, and the web lists coordinators that donate first (a draw
    weighted by the donation) in the order book and as the default host for new orders.
  - Price: `MARKET_PRICE_APIS=https://mempool.kilombino.com/nonkyc-ticker` and
    `NEOXA_TICKER_URL=https://mempool.kilombino.com/neoxa-ticker`, the BTCB2 price from two
    venues (NonKYC and Neoxa). Other fiat currencies are converted with yadio. Those URLs are
    proxies on the Roblosats maintainer's server, because both venues block Tor exits: you
    trust that server with your price. If your coordinator has clearnet access, point
    straight at the venues instead: `https://api.nonkyc.io/api/v2/ticker/BTCB2_USDT` and
    `https://neoxa.exchange/api/exchange/ticker/BTCB2_USDC`. Don't use Neoxa alone in
    `MARKET_PRICE_APIS` (the old setting): that is one venue. If one venue is down (or the
    two disagree by more than 10 %), the price stays frozen for an hour
    (`BTCB2_SINGLE_VENUE_GRACE`), then follows the remaining venue at most 5 % per refresh.
  - `BTCB2_FALLBACK_USD` is used only if no venue answers and there is no stored price yet.
  - PostgreSQL is required (the compose file already runs it): order actions are serialized
    with PostgreSQL advisory locks.
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

Disputes are handled on the dispute panel: `/coordinator/api/order/disputes/` lists the open
and past ones, and `/coordinator/api/order/<id>/dispute/` shows who buys and who sells, both
statements, the chat each party attached, and lets you write to the buyer, the seller or both
(app notification, Nostr DM, Telegram) and resolve with *buyer wins*, *seller wins*, *return
everything* or *trade completed*. Every resolution asks for confirmation first and says who
receives how many sats; it runs the same admin actions as before (*maker wins* / *taker wins*
etc. are still in the order list's action menu). The panel follows your browser language
(English, Spanish, German, French, Italian, Portuguese, Russian, Simplified Chinese, Japanese);
there is a selector at the top of the page. Opening a disputed order from the order list takes
you to its dispute page; add `?raw=1` to the URL (or use the link at the bottom of the dispute
page) for the full Django form. The list has three views: `?view=open` (default),
`?view=waiting` (both statements in, waiting for your decision) and `?view=history`.

## 7. Before asking to join

- [ ] `/api/info/` and `/api/limits/` answer over your onion (test from Tor Browser).
- [ ] You opened an order on https://roblosats.kilombino.com pointing at your coordinator, and
      the bond invoice was created.
- [ ] At least one real trade went through end to end.
- [ ] The watcher messaged you; you can stop a container briefly to test it.
- [ ] Your LND has a backup: seed on paper plus `channel.backup` copied off the machine.
- [ ] The coordinator itself has a backup off the machine: the onion's keys (`HiddenServiceDir`),
      `robosats.env` (`SECRET_KEY`, `NOSTR_NSEC`) and a database dump (on Umbrel/StartOS: the
      page's **Backup → Export**). Losing the onion or the Nostr key means a new identity.
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
- a message signed by your node, with your onion host (no `http://`):
  `lncli signmessage "Roblosats federation: <yourvanity>.onion"`.

On Umbrel and StartOS, the Roblosats Coordinator app does all of this from its page (**Join the
federation**): your node signs, and the issue opens filled in with the entry above.

Once it's reviewed, you are added to `federation.json` (with `tools/add_coordinator.py`) and
ship in the next web and app release. Until then robots can still use your coordinator by
adding its onion under Coordinators, but the Roblosats apps and webs don't list it. Your
coordinator's Nostr key is its identity in the federation: back it up; with a new key you
would have to be added again.

## On-chain escrow (optional, off by default)

Since 0.9.0 a coordinator can also offer **non-custodial on-chain orders**. The trade sits in a
2-of-3 Taproot output on the BLAKE2b chain (seller, buyer, coordinator), the bonds are on-chain
too, and each trader's app signs with keys derived from its robot token:

- a normal trade is released by the seller and the buyer together; a dispute by the winner and
  you; a collaborative cancel returns everything;
- before the deposit is signed, both apps pre-sign a **fair rescue** that pays each side its own
  share after `ESCROW_RESCUE_CSV` blocks, so the funds never depend on you staying online; an
  on-chain bond has its own refund path after 540 blocks;
- your fee is charged only when a trade completes, in one output of at least
  `ESCROW_MIN_COORDINATOR_FEE_SATS` for the whole order; cancels give it back;
- a robot that breaks the rules loses its bond through a penalty transaction to your address;
  the innocent side gets its reward share as usual;
- an on-chain order can also be taken with Lightning (hybrid): a Lightning buyer pays its fee from
  its payout; a Lightning seller turns the order into a Lightning order (its escrow by hold
  invoice) and pays the buyer's swap to on-chain.

**Lightning-only coordinators need no change.** `ONCHAIN_ESCROW` is `False` by default; then
`/api/info` does not announce `onchain_escrow` and the apps hide every on-chain option for your
coordinator. Everything else in 0.9.0 (fixed-price and "丰 sat" orders, past orders, final summary,
fixes) works without it.

To turn it on, add to `robosats.env` (the sample has the block, commented) and restart:

| Setting | What it is |
| --- | --- |
| `ONCHAIN_ESCROW` | `True` to offer on-chain orders. |
| `ESCROW_SECRET` | 32 random bytes in hex (`openssl rand -hex 32`). Your escrow and bond keys are derived from it **and from `COORDINATOR_ALIAS`**. Back it up with your onion and Nostr keys. Never change the secret or the alias while an on-chain order is open: you could no longer co-sign it (the traders would have to wait for their rescue). Without a secret on-chain stays off. |
| `ESCROW_COORDINATOR_ADDRESS` | An address of **your own** wallet on the BLAKE2b chain. Coordinator fees and bond penalties are paid to it. Required. |
| `ESCROW_WATCH_WALLET` | Name of a watch-only descriptor wallet (default `roblosats-escrow`) that the server creates and fills by itself on the node of `BITCOIND_RPCURL` / `BITCOIND_RPCUSER` / `BITCOIND_RPCPASSWORD`, to follow bond and deposit addresses and the mempool. That node must be a **BLAKE2b** node with wallet support enabled, and the RPC user must be allowed the wallet calls (`createwallet`, `loadwallet`, `importdescriptors`, `listunspent`) plus `getrawtransaction`, `gettxout`, `getmempoolentry`, `estimatesmartfee` and `sendrawtransaction`. `txindex=1` is recommended. It holds no private keys. |
| `ESCROW_MIN_SATS` / `ESCROW_MAX_SATS` | Size of on-chain orders in sats (default `MIN_ORDER_SIZE` / `MAX_ORDER_SIZE`). Kilobot started with 20,000–101,000. |
| `ESCROW_RESCUE_CSV` | Blocks after the deposit confirms before the pre-signed rescue is valid. Default and Kilobot: `2016`. |
| `ESCROW_FUNDING_SECONDS` / `ESCROW_BOND_SECONDS` | Time to fund the deposit / pay an on-chain bond (default 3 hours each). |
| `ESCROW_ALLOWED_ROBOTS` | `''` (default) = every robot. A comma list of nicknames, hash ids or Nostr keys keeps on-chain orders private to those robots (out of the public book and Nostr), for testing with your own robots first. |
| `ESCROW_MIN_COORDINATOR_FEE_SATS` | Smallest coordinator fee for a completed on-chain trade, default `1000`, split between both sides in the proportion of your fees. |
| `ESCROW_DEV_FEE_PERCENT` / `ESCROW_DEV_ADDRESS` | Optional: this percent of your on-chain fees goes to that address in the release. Off unless both are set; never leaves your own output below the minimum. |
| `ESCROW_PENALTY_FEE_RATE` / `ESCROW_PENALTY_MIN_FEE_RATE` / `ESCROW_PENALTY_MAX_FEE_PCT` | Mining fee of a bond penalty: sat/vB (default 10), its floor (1) and a cap as a percent of the bond (10). |
| `ESCROW_RESCUE_MIN_FEE_RATE` / `ESCROW_RESCUE_MAX_FEE_RATE` | Mining fee range of the pre-signed rescue (2–20 sat/vB), fixed when the deposit is planned. |
| `ESCROW_MIN_DEPOSIT_FEE_RATE` | Lowest fee rate of the deposit, sat/vB (default `1`, since 0.9.3). The deposit is planned at the current rate; when a trader's funding (the amount it was shown) is a little short of that, the deposit pays the highest rate the funding covers, down to this floor, instead of asking the trader to pay again. |
| `ESCROW_LIGHTNING_TAKER` / `ESCROW_BUYER_FEE_FROM_BOND` | Allow taking on-chain orders with Lightning, and take the buyer's fee and mining share from its on-chain bond (both `True` by default). |

Then check `/api/info/` shows `"onchain_escrow": true`, make a small on-chain order between two of
your own robots (with `ESCROW_ALLOWED_ROBOTS` set to them) and only then open it to everyone. The
admin panel (`/coordinator`) shows every on-chain order: the Escrow column and filters in the order
list, a summary of trades in progress, sats held, penalties and fees, the orders that need
attention (deposit window ending, payment in the mempool with a low fee, missing signatures,
rescue timelock reached), and on each order page the escrow and bonds with explorer links. Disputes
of on-chain orders are resolved from the same dispute panel. `audit_payouts` checks on-chain
penalties too.

## Updating

Roblosats follows RoboSats releases (see `ROBLOSATS.md` in the source repo). To update:

1. Pull the new `roblosats` branch.
2. Rebuild the image with a new tag.
3. Set `ROBLOSATS_TAG`.
4. Run `./coordinator.sh <alias> up -d`, **with no order in progress**.

### Upgrading to 0.9.5 (and 0.9.4)

Server and app, **no migration**; from 0.9.0 or later it is only a new image. 0.9.5 includes 0.9.4.

1. Dump the database as below and rebuild from tag `v0.9.5`:
   `docker build -f Dockerfile.roblosats -t roblosats:0.9.5 .`
2. Set `ROBLOSATS_TAG=0.9.5` in `compose.env` and run `./coordinator.sh <alias> up -d`.
3. Check `/api/info/` (`version` 0.9.5).

What changes in 0.9.5: the cooperative on-chain release (trade or collaborative cancel) is signed by
the seller alone through its leaf with the coordinator; the coordinator adds its signature and
broadcasts (`escrow_release_leaf` action, `escrow_release_leaf_ok` in the order data). The buyer signs
nothing and nobody has to come back for a second round. Releases started with the two-round MuSig2
signing (older apps) can be finished the same way when the seller opens the order with 0.9.5. New
mixed orders where the buyer took with Lightning use the seller's own rescue (the buyer has nothing
inside the escrow), so the buyer signs nothing on-chain. Older escrows keep their plans and older
apps keep working.

What changes in 0.9.4: a notice for every step of an order (Telegram, Nostr and webhook with the new
`action_needed` field, in English, Spanish or Catalan) and reminders 30 and 10 minutes before every
deadline a robot has to meet.

Rollback: set `ROBLOSATS_TAG=0.9.3` again (same schema).

### Upgrading to 0.9.3

**Recommended for every coordinator that offers on-chain orders** (0.9.0–0.9.2 can leave an
on-chain order stuck before the deposit: "the seller's funding is short by N sats" on every loop,
when the seller sent exactly the amount it was shown). Server and app, **no migration**; from 0.9.0
it is only a new image.

1. Dump the database as below and rebuild from tag `v0.9.3`:
   `docker build -f Dockerfile.roblosats -t roblosats:0.9.3 .`
2. Set `ROBLOSATS_TAG=0.9.3` in `compose.env` and run `./coordinator.sh <alias> up -d`.
3. Check `/api/info/` (`version` 0.9.3).

What changes: a short deposit funding pays a lower fee rate (`ESCROW_MIN_DEPOSIT_FEE_RATE`, default
1 sat/vB) instead of stalling; taking an on-chain order on-chain after a cancelled Lightning take
works (the server answers `take_lightning: false`, which also fixes 0.9.2 apps; a bond key on a
Lightning take is refused); the order page tells the app what already confirmed at its funding
address (`escrow_funding_confirmed_sats`); and when a robot's signature (rescue, deposit or release)
is still missing after 90 seconds, the robot is reminded once per step by Telegram, Nostr or
webhook. Rollback: set `ROBLOSATS_TAG=0.9.0` again (same schema).

Coming from 0.8.8-rl30, do the 0.9.0 steps below with the 0.9.5 tag.

### Upgrading to 0.9.0

Server and app; **database migrations** (api 0063–0069: on-chain escrow and bonds, Lightning taker,
fixed price, bond coins, "丰 sat" orders, seller-paid swap). They run by themselves at start
(`migrate_locked`); all new columns have defaults.

1. Make sure no order is in progress (status 6–11, 13, 15 or 16), then dump the database:
   `docker exec sql-<alias> sh -c 'pg_dumpall -U "$POSTGRES_USER"' | gzip > pre-0.9.0.sql.gz`.
2. Rebuild from tag `v0.9.0`: `docker build -f Dockerfile.roblosats -t roblosats:0.9.0 .`
3. Set `ROBLOSATS_TAG=0.9.0` in `compose.env` and run `./coordinator.sh <alias> up -d`.
4. Check `/api/info/` (`version` 0.9.0) and `docker exec rs-<alias> python3 manage.py audit_payouts`.

Nothing else is needed to stay Lightning-only: on-chain orders stay off until you configure the
section above. What changes for a Lightning-only coordinator: fixed-price orders (`fixed_price` in
`/api/info`, the price no longer needs your exchange rate), "丰 sat" orders (amount in sats, paid in
any currency), past orders (`/api/pastorders/`) and a final summary of each order for its robots,
reward withdrawals that fail before leaving (for example an invoice of your own node) refunded
instead of an error, and the slashed-bond rule fixed so the innocent side, not the faulty one, gets
the reward. Users of older apps keep working; they are asked to update.

Rollback: the 0.8.8-rl30 image cannot create orders on the 0.9.0 schema (some new columns have no
database default). Before any on-chain order exists, either run
`docker exec rs-<alias> python3 manage.py migrate api 0062` and then set `ROBLOSATS_TAG` back to
`0.8.8-rl30`, or stop the coordinator, restore the dump and set the old tag.

### To 0.8.8-rl30

Server and app, no migration. When the lightning payout to a buyer fails (order in "Failed
lightning network routing"), the buyer can switch to an onchain address from that screen. It is
offered only if you have onchain payouts on (`DISABLE_ONCHAIN = False`) and the amount fits your
`MIN_SWAP_AMOUNT`/`MAX_SWAP_AMOUNT` and onchain liquidity; the swap fee is the usual one. Before
paying onchain the server cancels the lightning payout, asks LND whether any attempt is still in
flight or already paid (and refuses if so), and checks the escrow again; `audit_payouts` reports
any order paid both ways. LND only: on CLN the switch is always refused. Rebuild from tag
`v0.8.8-rl30` (or pull `ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl30`), set
`ROBLOSATS_TAG` and restart. It includes everything in rl29.

### To 0.8.8-rl29

Server only (no app change, no migration). Disputes are no longer resolved automatically
(RoboSats upstream, "Remove automatic dispute resolution"). Until now, when an order's chat
timed out, the server could decide the dispute by itself if one party had written nothing in the
chat. With the chat over Nostr the coordinator does not see every message, so that could punish
someone who did write. Now every dispute, opened by a party or by the timeout, takes the bonds and
the escrow into custody and waits for your decision in the dispute panel. Rebuild from tag
`v0.8.8-rl29` (or pull `ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl29`), set
`ROBLOSATS_TAG` and restart. It includes everything in rl28.

### To 0.8.8-rl28

Coordinator panel only (no app change, no migration). New in the panel:

- **Penalize the seller / the buyer (no trade)**, two more ways to resolve a dispute (also as
  changelist actions `penalize_maker` / `penalize_taker`). For when one side simply does not show
  up: the escrow goes back to whoever sent it and the other side gets its bond back, both as
  rewards to withdraw from the app; the guilty side's bond stays with the coordinator. Unlike
  "buyer/seller wins", nobody receives trade sats they did not pay for.
- **Outcome** section on a resolved dispute: what each party received as a reward, whether they
  have already withdrawn it, and what they lost (bond, escrow).
- **Failed payouts** page (sidebar, with a counter; home card and banner): orders whose Lightning
  payment to the buyer is failing (status 15), and a history of those that went through it. For
  each one, the invoices the buyer submitted, the failed attempts and their reason, and the node
  each invoice goes to (and its route hints), decoded by your LND. The order page shows the same.

Rebuild from tag `v0.8.8-rl28` (or pull `ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl28`),
set `ROBLOSATS_TAG` and restart.

### To 0.8.8-rl27

Coordinator panel only (no app change, no migration). The order page now says who won a resolved
dispute, what the coordinator earned, the routing fee of the payout (and the txid and mining fee of
an on-chain payout), links to every payment, and a "Chat between them" section (how many messages
each side wrote and when; contents stay encrypted). With only one dispute waiting, the home's
banner and card open it directly. Rebuild from tag `v0.8.8-rl27` (or pull
`ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl27`), set `ROBLOSATS_TAG` and restart.

### To 0.8.8-rl26

Coordinator panel only (no app change). One small migration in `roblosats_admin` (runs by itself
at start). New in the panel:
- A readable page for every order (`/coordinator/api/order/<id>/summary/`, "📄 View" column in
  the order list); disputed orders still open the dispute page.
- **Telegram alerts** (side menu, superusers): your bot token, chat id, language and a switch per
  event (order published, taken, escrow locked, finished, cancelled/expired, dispute opened,
  dispute chat, coordinator message), with a test button. Stored in the database: no variables
  and no restart. If you already had `TELEGRAM_COORDINATOR_CHAT_ID`, dispute alerts keep working
  and are not sent twice.
- Home and side menu translated into the panel's 9 languages.
Rebuild from tag `v0.8.8-rl26` (or pull `ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl26`),
set `ROBLOSATS_TAG`, restart all the coordinator containers (Celery must load the new task).

### To 0.8.8-rl25

No migration and no new variables. `/api/chat/` now accepts an `offset` with decimals: apps in
Nostr chat mode sent one from the second message on, and the coordinator dropped its copy of
those messages (so disputes had no chat). Rebuild from tag `v0.8.8-rl25` (or pull
`ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl25`), set `ROBLOSATS_TAG`, restart.

### To 0.8.8-rl24

One migration (`0062`, runs by itself when the server starts): the BTC/Spamcoin rate is kept with
8 decimals instead of 4 (it moved in ~2 % steps), and orders paid in Spamcoin get their Spamcoin
amount fixed when the taker's bond locks, so both sides see the same number. No new variables.
Back up the database, rebuild from tag `v0.8.8-rl24` (or pull
`ghcr.io/kilombino/roblosats-coordinator:0.8.8-rl24`), set `ROBLOSATS_TAG`, restart with no order
in progress.

### To 0.8.8-rl23

No migrations, no new variables, no server change. The web client the image ships now starts new
coordinators at a 25M sats order limit instead of 250k sats (your own `MAX_ORDER_SIZE` still
applies). Optional: rebuild from tag `v0.8.8-rl23`, set `ROBLOSATS_TAG`, restart with no order in
progress.

### To 0.8.8-rl22

Server only, no migrations, no new variables. rl21 added the dispute panel (section 6) and the
*Send a message to maker / taker* action; rl22 opens disputed orders on that panel and adds the
open / waiting / history views, which the sidebar now links to. Same steps as rl21 below, with
tag `v0.8.8-rl22`.

### To 0.8.8-rl21

Server only, no migrations, no new variables. Adds the dispute panel (section 6) and the
*Send a message to maker / taker* action in the order list. Messages reach the robots with the
prefix `<COORDINATOR_ALIAS> coordinator (order N): `, so check that `COORDINATOR_ALIAS` is set.
Telegram and webhook delivery go through Celery, so the `celery` service must be running.
Rebuild from tag `v0.8.8-rl21`, set `ROBLOSATS_TAG`, restart with no order in progress.
Coming from rl18/rl19, nothing else to do; from rl15/rl17, follow the rl18 steps below.

### To 0.8.8-rl20

Fixes the HTTP 500 when a buyer submits the payout invoice on rl18 (rl19) and the trade screen
not redrawing after an action (rl20). No new migrations:
rebuild from tag `v0.8.8-rl20`, set `ROBLOSATS_TAG`, restart. Coming from rl15/rl17, follow
the rl18 steps below.

### To 0.8.8-rl18 (RoboSats v0.8.8)

- Back up the database first (`docker exec sql-<alias> pg_dump -U <user> <db> | gzip > backup.sql.gz`).
  Going back to an older image needs that dump: the upgrade converts the order logs to JSON.
- The first service that starts applies migrations 0058–0061 (under a database lock) and
  migration 0061 converts every order's log, so no history is lost.
- New optional variables: `DEVFUND_PUBKEY`, `DEVFUND_COMMUNITY`, `DEVFUND_COMMUNITY_ADDRESS`
  (see the sample `robosats.env`).
- After starting, check `/api/info` (version 0.8.8), the admin panel and
  `docker exec rs-<alias> python3 manage.py audit_payouts`.

Questions: https://t.me/roblosats
