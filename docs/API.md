# HTTP API reference

Base URL defaults to `http://127.0.0.1:5000`.

## Authentication

There is none. Every route below is open and needs no headers or cookies:

```bash
curl "http://127.0.0.1:5000/api/market/candles?symbol=BTCUSDT&interval=60&limit=5"
```

The server binds to `127.0.0.1` by default, which is the only thing limiting who
can call these endpoints. Anything that can reach the port can read exchange
balances and add or delete accounts — see the security notes in the README before
changing `HOST`.

## Conventions

- All responses are JSON. Errors are `{"error": "..."}`.
- Validation failures return `400` with
  `{"error":"Validation failed","issues":[{"path":"...","message":"..."}]}`.
- `503` from an `/api/ai/*` route means no provider key is configured.
- Live figures are sent with `Cache-Control: no-store`.
- Ratio fields (`pnlRatio`) are `null` when there were no losses to divide by.
- Money and percentages are rounded to 2 decimal places.
- Alerts and strategies are not scoped by owner; there are no users.
- Routes that aggregate across accounts return `[]` rather than erroring when no
  accounts are configured, and skip individual accounts whose credentials fail.

---

## Public

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/health` | `{status, ai}` — `ai` is false when no provider key is set |
| `GET` | `/api/server-time` | Bybit server time |
| `GET` | `/api/market-hours` | Exchange open/closed status. `source` is `bybit` or `local` if the exchange clock was unreachable |

## Market data

No exchange credentials required; these use Bybit's public endpoints.

**`GET /api/market/candles`**

| Param | Default | Notes |
| --- | --- | --- |
| `symbol` | required | e.g. `BTCUSDT` |
| `interval` | `60` | `1 3 5 15 30 60 120 240 360 720 D W M` |
| `limit` | `200` | 1–1000 |
| `category` | `linear` | `linear` \| `inverse` \| `spot` |

Returns `{symbol, interval, limit, category, candles: [...]}` with candles
**oldest first** (Bybit returns newest first; this flips them):

```json
{ "openTime": 1786248000000, "open": 64758.4, "high": 64807.1,
  "low": 64753.9, "close": 64756.6, "volume": 534.682, "turnover": 34636637.45 }
```

**`GET /api/market/price?symbol=BTCUSDT`** → `{symbol, price}`

## Aggregated exchange views

These need at least one account with credentials.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/bybit/positions` | Open positions across all accounts, each tagged `accountName`. `?category=linear\|inverse` |
| `GET` | `/api/bybit/wallet` | Balances across all accounts. `404` if none returned one |
| `GET` | `/api/bybit/test` | Connectivity probe using the environment credentials |
| `GET` | `/api/trading-reports?timeframe=7` | Realised performance per account, 1–365 days |
| `GET` | `/api/account-balance` | Equity, derived historical balances, 7-day and week-to-date performance, per-symbol breakdown, 1–5% position sizing |
| `GET` | `/api/trophy-stats` | Best trade of the current week by ROI and by absolute profit |

**ROI is margin-based**, not notional: a trade's committed capital is
`cumEntryValue / leverage`. Weeks run Monday 00:00:00 UTC to Sunday
23:59:59.999 UTC.

`/api/trading-reports` returns one object per account:

```json
{ "accountName": "Main", "timeframe": "7 days", "totalROI": 12.4,
  "totalPnL": 843.21, "winROI": 18.2, "winPnL": 1203.4, "lossROI": -9.1,
  "lossPnL": -360.19, "winCount": 14, "lossCount": 6, "winRate": 70,
  "pnlRatio": 3.34 }
```

## Accounts

Credentials are never returned; each account reports `hasCredentials` instead.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/accounts` | List |
| `POST` | `/api/accounts` | `{name, exchange:"bybit", apiKey, apiSecret, status?}` |
| `PUT` | `/api/accounts/:id` | partial update |
| `DELETE` | `/api/accounts/:id` | `204` |
| `GET` | `/api/accounts/:id/positions` | Positions for one account |
| `GET` | `/api/accounts/:id/wallet` | Balance for one account |
| `GET` | `/api/accounts/:id/test` | Verify that account's credentials |

## Alerts

A background poll (`ALERT_POLL_MS`, default 30s)
prices every active alert's symbol and flips it to `triggered` once crossed,
recording `triggeredAt` and `triggeredPrice`.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/alerts` | `?status=active\|triggered\|cancelled` |
| `POST` | `/api/alerts` | `{symbol, direction:"above"\|"below", price, note?}` → `201` |
| `POST` | `/api/alerts/:id/cancel` | Keeps the record, sets status `cancelled` |
| `DELETE` | `/api/alerts/:id` | `204` |

`POST` rejects a symbol the exchange doesn't price, so an alert can't sit dead:

```bash
curl -H 'Content-Type: application/json' \
  -d '{"symbol":"ETHUSDT","direction":"below","price":3000,"note":"support"}' \
  http://127.0.0.1:5000/api/alerts
```

## Strategies

Stored definitions. `rules` is free-form JSON, persisted as given and **never
executed** — this app does not trade.

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/strategies` | List |
| `GET` | `/api/strategies/:id` | One |
| `POST` | `/api/strategies` | `{name, symbol, timeframe?, description?, rules?, status?}` → `201` |
| `PATCH` | `/api/strategies/:id` | Any subset |
| `DELETE` | `/api/strategies/:id` | `204` |

`timeframe` takes the same values as a candle `interval`. `status` is
`draft` \| `active` \| `paused`.

## AI

`503` with the exact environment variable to set when unconfigured. All three
accept optional `question`, `model` and `effort`
(`low`\|`medium`\|`high`\|`xhigh`\|`max`).

| Method | Path | Body |
| --- | --- | --- |
| `GET` | `/api/ai/config` | — returns `{configured, models: [...]}` |
| `POST` | `/api/ai/market` | `{symbol, interval?, limit?}` |
| `POST` | `/api/ai/performance` | `{timeframe?}` |
| `POST` | `/api/ai/strategies/:id/review` | `{}` |

Every response reports which model answered plus cost:

```json
{ "text": "...", "refused": false, "stopReason": "end_turn",
  "model": "claude-opus-5", "provider": "anthropic",
  "usage": { "inputTokens": 2143, "outputTokens": 388 },
  "configuredModel": "claude-opus-5", "effort": "medium",
  "estimatedCostUsd": 0.0204 }
```

`refused: true` with empty `text` means the provider's safety layer declined.

---

## WebSocket

Connect to `ws://127.0.0.1:5000/ws`. No authentication; any connection is
accepted. Upgrades on other paths are left alone, so Vite's HMR socket is
unaffected in development.

On connect the server sends `{"op":"ready"}`. Then:

```json
{"op":"subscribe","args":["wallet","alerts"]}
```

| Topic | Payload |
| --- | --- |
| `wallet` | `{topic:"wallet", creationTime, data:[...], accountCount}` every 5s, or `{topic:"wallet-error", message}` |
| `alerts` | `{topic:"alert", creationTime, data:{alert, price}}` when an alert fires |

`{"op":"unsubscribe","args":[...]}` stops a topic.
