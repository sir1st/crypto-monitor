# Vale Monitor

A self-hosted dashboard for watching Bybit trading accounts. It aggregates
positions, balances and realised P&L across several accounts, reads candles,
watches price alerts, stores strategy definitions, and exposes all of it to AI
agents over MCP.

The dashboard is **read-only against the exchange** — it never places, modifies
or cancels orders. Use read-only API keys.

> This repository also contains [`backend-setup/`](backend-setup/README.md), a
> separate Python trading bot that **does** place real leveraged orders. It is an
> independent system with its own setup and its own credentials — nothing in the
> dashboard imports it. Read its own README before running any of it.

- **Local SQLite** — no database to provision. First boot creates the file.
- **Multi-account** — aggregates any number of Bybit accounts.
- **Candles and prices** — work with no exchange keys at all.
- **Alerts** — price thresholds, evaluated on a background poll.
- **Strategies** — stored definitions with free-form JSON rules.
- **AI analysis** — optional, provider-agnostic (Claude or OpenAI).
- **MCP server** — lets Claude Code read candles and manage alerts/strategies.

---

## Quick start

Requires Node.js 20+ (tested on 24).

```bash
git clone <your-fork-url> vale-monitor
cd vale-monitor
npm install
npm run dev
```

Open <http://127.0.0.1:5000>. There is no configuration step and no login — the
SQLite database is created at `./data/vale.db` on first boot.

Copy `.env.example` to `.env` when you want to connect an exchange account or
enable the AI layer. Nothing in it is required.

Verify a running instance end to end:

```bash
npm run smoke
```

> **There is no authentication.** Anything that can reach the port can read your
> exchange balances and add or delete accounts. `HOST` defaults to `127.0.0.1`
> so the server is reachable only from your own machine — see
> [Security notes](#security-notes) before changing that.

---

## Using the dashboard

The app is a single page with five tabs:

| Tab | What it does |
| --- | --- |
| **Positions** (default) | Open positions across every configured account, with live P&L, and a TradingView chart |
| **Dashboard** | Weekly highlights, trading reports by timeframe, and a per-account balance card (equity, 7-day and week-to-date performance, per-symbol breakdown, 1–5% position sizing) |
| **Accounts** | Add, test and remove exchange accounts |
| **Streaming** | Live wallet balances pushed over the WebSocket |
| **Calculator** | Compound growth projection across multiple accounts |

**Positions, Dashboard and Streaming stay empty until you connect an account** —
they read credentialed exchange endpoints. Candles, prices and market hours work
immediately.

Alerts and strategies are **API- and MCP-first**: they have full REST and MCP
coverage but no dedicated tab yet. Drive them from Claude Code (below), or
directly over HTTP — see [docs/API.md](docs/API.md).

---

## Configuration

Every setting lives in `.env`; see [`.env.example`](.env.example) for the
annotated list. **Nothing is required** — the app runs with no `.env` at all.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` / `HOST` | `5000` / `127.0.0.1` | Only change `HOST` behind an authenticating proxy |
| `DATABASE_PATH` | `./data/vale.db` | Where the SQLite file lives |
| `ALERT_POLL_MS` | `30000` | How often active alerts are re-checked |
| `BYBIT_API_KEY` / `BYBIT_API_SECRET` | — | Single-account fallback; prefer the Accounts tab |

### Connecting exchange accounts

Candles, prices and market hours need no credentials. Positions, balances and
realised P&L do.

Add accounts in the **Accounts** tab so you can track several at once. Credentials are stored in the local database and are never returned by the
API — account responses only report whether credentials are present. The
`BYBIT_API_KEY` environment pair is a single-account fallback, used only when no
accounts are configured.

---

## Using it from Claude Code

The MCP server exposes 22 tools — candles, prices, positions, balances, trading
reports, and full CRUD for alerts and strategies. No credential is needed.

**1. Point Claude Code at it:**

```bash
cp .mcp.json.example .mcp.json
```

```json
{
  "mcpServers": {
    "vale-monitor": {
      "command": "npx",
      "args": ["tsx", "server/mcp/index.ts"],
      "env": { "VALE_API_URL": "http://127.0.0.1:5000" }
    }
  }
}
```

**2. Start the app** (`npm run dev`) — the MCP server talks to it over HTTP, so
it must be running. Then ask Claude Code things like:

> Read the last 200 hourly BTCUSDT candles and tell me where support is sitting.
>
> Set an alert for ETHUSDT below 3000, and list what's already active.
>
> Save a strategy for SOLUSDT on the 4h with these rules, then review it.

Available tools: `server_status`, `get_candles`, `get_price`, `get_market_hours`,
`get_positions`, `get_account_balances`, `get_trading_report`,
`get_weekly_highlights`, `list_accounts`, `list_alerts`, `create_alert`,
`cancel_alert`, `delete_alert`, `list_strategies`, `get_strategy`,
`create_strategy`, `update_strategy`, `delete_strategy`, `ai_config`,
`analyze_market`, `analyze_performance`, `review_strategy`.

The HTTP API is equally open — no headers required:

```bash
curl "http://127.0.0.1:5000/api/market/candles?symbol=BTCUSDT&interval=60&limit=5"
```

---

## The AI layer

Optional. Without a provider key, the AI endpoints return `503` and everything
else works normally.

Three analyses are available — market commentary over a candle window,
performance comparison across accounts, and strategy review — via
`POST /api/ai/market`, `/api/ai/performance` and
`/api/ai/strategies/:id/review`, and via the matching MCP tools.

### Switching models

Two environment variables:

```env
AI_PROVIDER=anthropic        # anthropic | openai
AI_MODEL=claude-opus-5       # any id in the registry
AI_EFFORT=medium             # low | medium | high | xhigh | max
ANTHROPIC_API_KEY=sk-ant-...
```

Registered by default:

| Model | Provider | Context | $/Mtok in | $/Mtok out |
| --- | --- | --- | --- | --- |
| `claude-opus-5` (default) | Anthropic | 1M | 5 | 25 |
| `claude-sonnet-5` | Anthropic | 1M | 3 | 15 |
| `claude-haiku-4-5` | Anthropic | 200K | 1 | 5 |
| `claude-opus-4-8` | Anthropic | 1M | 5 | 25 |
| `gpt-5.1`, `gpt-5`, `gpt-5-mini` | OpenAI | 400K | 1.25 / 0.25 | 10 / 2 |

`GET /api/ai/config` returns the registry with an `available` flag per model
based on which keys are set. Each response reports the model that answered, the
token counts and an estimated cost.

The OpenAI ids and pricing are best-effort and move quickly — check
<https://platform.openai.com/docs/models> before relying on them.

### Adding a model or provider

Nothing outside `server/ai/` hardcodes a model id.

**A new model on an existing provider** — add an entry to `MODELS` in
[`server/ai/config.ts`](server/ai/config.ts):

```ts
"claude-sonnet-4-6": {
  id: "claude-sonnet-4-6",
  provider: "anthropic",
  label: "Claude Sonnet 4.6",
  contextWindow: 1_000_000,
  maxOutputTokens: 128_000,
  pricing: { inputPerMTok: 3, outputPerMTok: 15 },
  supportsEffort: true,
},
```

Then set `AI_MODEL=claude-sonnet-4-6`.

**A new provider** — add its name to `ProviderName`, implement the `Provider`
interface (a single `complete()` method) under `server/ai/providers/`, and wire
it into the `switch` in `createProvider`. The switch is exhaustively typed, so
TypeScript will point at anything you miss.

Note the request interface deliberately has no `temperature`: current Claude
models reject `temperature`/`top_p`/`top_k` with a 400. Reasoning depth is
expressed as `effort` and each provider maps it onto its own knob.

**Prompts** live in [`server/ai/analyze.ts`](server/ai/analyze.ts) — one
system prompt plus one builder per analysis.

---

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | API + Vite dev server on one port |
| `npm run build` | Client to `dist/public`, server bundle to `dist/index.js` |
| `npm start` | Run the production build |
| `npm run check` | TypeScript, no emit — the project's only static gate |
| `npm run smoke` | End-to-end HTTP check against a running server |
| `npm run mcp` | Run the MCP server directly (normally launched by the client) |
| `npm run db:push` | Push `shared/schema.ts` with drizzle-kit |

There is no test runner or linter configured; `npm run check` and `npm run smoke`
are the checks.

---

## Architecture

One Express process serves both the API and the client. In development Vite runs
as middleware inside it, so there is a single port and no separate dev server; in
production the built assets are served statically. Vite owns the catch-all route
and is registered last, so **new routes must be added inside `registerRoutes()`**.

```
server/
  index.ts        Bootstrap: schema init, middleware, listen
  routes.ts       All HTTP routes
  storage.ts      Every database query
  db.ts           SQLite connection and schema bootstrap
  trading.ts      Multi-account aggregation and analytics
  bybit-api.ts    Authenticated exchange reads
  market.ts       Public market data (candles, prices)
  market-hours.ts Exchange open/closed calculation
  alerts.ts       Background alert evaluation
  websocket.ts    Session-authenticated /ws stream
  vite.ts         Dev middleware / static serving, logger
  ai/             Model registry, providers, analysis prompts
  mcp/            MCP server for agents
shared/schema.ts  Drizzle tables, Zod schemas, shared types
client/src/       React + Vite front end
scripts/          smoke test CLI
docs/API.md       HTTP and WebSocket reference

backend-setup/    Separate Python trading bot — places real orders, own README
```

Three tables: `accounts`, `alerts`, `strategies`. There are no users.

Two conventions run through the analytics:

- **ROI is margin-based, not notional.** A trade's committed capital is
  `cumEntryValue / leverage`, so a 10x position reports return on the margin
  actually put up.
- **Weeks run Monday 00:00:00 UTC to Sunday 23:59:59.999 UTC**, independent of
  the server's timezone.

Ratios are `null` rather than `Infinity` when there are no losses to divide by.

### No authentication

Every route is open, and the WebSocket at `/ws` accepts any connection. There are
no users, sessions, passwords or tokens in the codebase.

This is deliberate for a single-user tool bound to loopback. It also means the
only thing standing between the internet and your exchange credentials is the
`HOST` binding — see below.

Full endpoint and WebSocket reference: **[docs/API.md](docs/API.md)**.

---

## Security notes

- **There is no authentication.** Any process or person who can reach the port
  can read your balances and positions, and add or delete exchange accounts.
- `HOST` defaults to `127.0.0.1`, which is the control that makes the above
  acceptable — the server is reachable only from your own machine. The app logs a
  warning if you bind it anywhere else. Before exposing it, put a reverse proxy
  with TLS **and** access control in front; do not simply set `HOST=0.0.0.0`.
- Use **read-only** exchange API keys. Nothing here needs trade permissions, and
  a leaked read-only key cannot move funds.
- Exchange credentials are stored **unencrypted** in the local SQLite file.
  Protect the file; it is as sensitive as the keys themselves.
- `.env`, `data/` and `.mcp.json` are gitignored. Keep it that way.

## License

MIT — see [LICENSE](LICENSE).
