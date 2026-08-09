# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Vale Monitor — a self-hosted, read-only Bybit trading dashboard. It aggregates
positions, balances and realised P&L across multiple accounts, reads candles,
evaluates price alerts, stores strategy definitions, and exposes all of it to
agents over MCP. It never places orders; every exchange call is a read.

See [README.md](README.md) for setup and usage, and [docs/API.md](docs/API.md)
for the endpoint reference. This file covers what isn't obvious from reading a
single file.

**`backend-setup/` is a different system.** It is a Python trading bot that
places real leveraged orders, with its own `.env`, its own JSON config and its own
[README](backend-setup/README.md). The TypeScript dashboard does not import it
and never places orders. Do not blur the two: guidance in this file describes the
dashboard only, and the "read-only against the exchange" property is the
dashboard's, not the repository's. Its private config
(`accounts_config.json`, `trading_config.json`, state JSON, logs) is gitignored in
two places — never un-ignore them.

**The repo is kept free of unreachable modules.** Every `.ts`/`.tsx` under
`client/src`, `server`, `shared` and `scripts` is reachable from an entry point
(`client/src/main.tsx`, `server/index.ts`, `server/mcp/index.ts`, `scripts/*`).
Only 11 shadcn/ui primitives are present — the unused ones were deleted, so add
what you need via the shadcn CLI rather than assuming a component exists. The
same applies to dependencies: there are no unused runtime packages.

An earlier version carried a manual wallet / transaction / P&L-record feature
(three tables, ~110 lines of routes, a dozen components). Its UI was orphaned and
it duplicated what the exchange already reports, so it was removed. Don't
reintroduce those tables to store balances — balances come from Bybit.

## Commands

```bash
npm run dev        # API + Vite middleware on one port (5000)
npm run check      # tsc --noEmit — the only static gate; no linter, no test runner
npm run smoke      # end-to-end HTTP check; needs a server running
npm run build      # vite build -> dist/public, esbuild server -> dist/index.js
npm start          # run the production build
npm run mcp        # run the MCP server directly
npm run db:push    # drizzle-kit push from shared/schema.ts
```

After changing anything, run `npm run check`, then `npm run smoke` against a
running server. `scripts/` is inside the tsconfig `include`, so it is typechecked
too.

**`tsconfig.json` sets `incremental: true` with a build-info file under
`node_modules/typescript/`.** If `tsc` reports errors that contradict the config
(notably `TS2802` downlevel-iteration errors when `target` is clearly ES2022),
the cache is stale — delete `node_modules/typescript/tsbuildinfo` and re-run.

## Architecture

### One process, one port

`server/index.ts` boots, `server/routes.ts` registers every route and returns an
`http.Server`, then Vite is attached **last**: `setupVite()` in development
(middleware mode, single port, no separate dev server) or `serveStatic()` in
production. Because Vite owns the catch-all `*` route, **any new route must be
registered inside `registerRoutes()`** or Vite will swallow it.

Aliases `@/*` → `client/src`, `@shared/*` → `shared`, declared in both
`tsconfig.json` and `vite.config.ts`.

### Startup contract

`bootstrap()` in `server/index.ts` calls `initialiseSchema()` (raw
`CREATE TABLE IF NOT EXISTS` DDL in `server/db.ts`) and then listens. There are no
required environment variables — the app runs with no `.env` at all.

`HOST` defaults to `127.0.0.1`, not `0.0.0.0`, and this is **load-bearing**: the
API is unauthenticated, so the loopback binding is the only access control. The
server logs a warning when bound elsewhere. Do not change the default.

### Database

Local SQLite via `better-sqlite3` + `drizzle-orm/better-sqlite3`, at
`DATABASE_PATH` (default `./data/vale.db`). WAL is enabled so the MCP server and
web server can read concurrently, and `foreign_keys = ON`.

**`better-sqlite3` must be a version with prebuilt binaries for the local Node
release.** There is no C++ toolchain on this machine, so a version that falls back
to `node-gyp` fails to install — 12.x covers Node 24.

Three tables: `accounts`, `alerts`, `strategies`.
Timestamps are `integer({mode: "timestamp"})`, surfaced as JS `Date`s. Every query
lives in `server/storage.ts`; nothing outside it imports `db`.

DDL uses `CREATE TABLE IF NOT EXISTS`, so **removing a table from
`initialiseSchema()` does not drop it from an existing `data/vale.db`** — delete
the file (or migrate) to get a clean schema.

### No authentication

There is none, by explicit request: no users, sessions, passwords, tokens,
passport, or `express-session`. Every route is open and the WebSocket accepts any
connection.

Consequences to keep in mind when editing:

- **Never add an ownership check** — there is no `req.user` and no owner column on
  any table. Alerts and strategies are global.
- **Do not reintroduce a login** without being asked; several files were deleted
  for this (`server/auth.ts`, `server/crypto.ts`, `client/src/hooks/use-auth.tsx`,
  `client/src/lib/protected-route.tsx`, `client/src/pages/auth-page.tsx`,
  `client/src/components/login-form.tsx`, `scripts/token.ts`).
- Any new route is public the moment it is registered. Weigh that before adding
  one that mutates state or reveals credentials.

### WebSocket

`server/websocket.ts` uses `WebSocketServer({ noServer: true })` and handles the
server's `upgrade` event itself. It **must return early for paths other than
`/ws`**, because Vite's HMR socket shares the same server in development.

Topics are `wallet` (one shared Bybit fan-out per 5s tick, not per client) and
`alerts` (pushed from `onAlertTriggered`).

### Analytics conventions

`server/trading.ts` owns all multi-account aggregation. Two conventions:

- **ROI is margin-based**: `cumEntryValue / leverage`, falling back to
  `closedSize * avgEntryPrice / leverage` on older fills that omit
  `cumEntryValue`. Not notional.
- **Weeks are Monday 00:00:00 UTC → Sunday 23:59:59.999 UTC**, computed from
  `getUTCDay()` with Sunday mapped to 6 days from Monday.

Ratios are `null`, never `Infinity` — `JSON.stringify(Infinity)` is `null`
anyway, so this makes the wire format intentional. Trade-level ROI is capped at
1000% in the weekly highlights to suppress dust-fill outliers. Money is rounded
at the response boundary via `round2`.

Per-account failures are caught and logged, never fatal: a route returns partial
data rather than erroring, because one bad API key must not break the aggregate.

`buildAccountBalanceReports` back-derives historical balances from realised P&L
(`walletBalance - pnl`) rather than storing snapshots.

### Exchange access

Two modules, split by whether credentials are needed:

- `server/market.ts` — **public** endpoints (kline, tickers, time). No API key, so
  candles and prices work on a fresh install. Throws `MarketDataError`, and
  detects Bybit's CloudFront geo-block, which returns an HTML page rather than a
  JSON error. Candles are re-sorted oldest-first; Bybit returns newest-first.
- `server/bybit-api.ts` — **authenticated** reads. Returns `null` on failure
  rather than throwing, precisely so the multi-account fan-out can skip a bad
  account.

Credentials live per row in the `accounts` table. `storage.getTradableAccounts()`
is the filter (`exchange === "bybit" && status === "active"` and both keys
present). The `BYBIT_API_KEY` env pair is a single-account fallback used **only
when no account rows exist at all**. Account API responses strip `apiKey`/
`apiSecret` and expose a `hasCredentials` boolean instead.

### AI layer

`server/ai/` is provider-agnostic. `config.ts` holds the `MODELS` registry —
**the only place a model id is hardcoded** — and resolves `AI_PROVIDER`/`AI_MODEL`/
`AI_EFFORT`, throwing `AiConfigError` (surfaced as `503`) with the exact env var
to set. `providers/` implements one `complete()` per provider; `createProvider`
switches on provider name with an exhaustiveness guard.

**The completion interface has no `temperature` on purpose**: current Claude
models reject `temperature`/`top_p`/`top_k` with a 400. Depth is `effort`, mapped
per provider (Anthropic `output_config.effort`; OpenAI `reasoning_effort`, with
`xhigh` folded to `high` since OpenAI has no equivalent).

The Anthropic provider sets `thinking: {type: "adaptive"}` and **checks
`stop_reason === "refusal"` before reading `content`** — a refusal is an HTTP 200
with empty or partial content, so indexing content first would throw.

Anthropic model ids are stable strings with no date suffix — never append one.
The OpenAI entries are best-effort and marked as needing verification.

## Repository conventions

- Adding a route: inside `registerRoutes()`; validate with a Zod `safeParse` and
  return `badRequest(res, parsed.error)`; wrap async bodies in `handler()` so a
  rejection becomes a 500 instead of an unhandled rejection.
- `storage.cancelAlert` filters on `status = 'active'` in the query, so
  cancelling twice reports false rather than silently succeeding.
- `noStore(res)` on anything live.
- The MCP server talks to the app over **HTTP**, not directly to SQLite, so
  validation stays in one place. It therefore needs the app running.
- **The MCP server must never write to stdout** — stdio carries the protocol.
  Log to stderr.
- Alerts and strategies are API- and MCP-first: full REST + MCP coverage, but no
  dedicated UI panel yet.

## Gotchas

- **Never commit `.env` or `data/`.** Both are gitignored and both hold exchange
  credentials.
- Exchange keys are stored **unencrypted** in the SQLite file.
- `client/index.html` defines the theme CSS variables in an inline `<style>`
  block. There is no theme plugin — edit them there, and keep them in sync with
  the token list in `tailwind.config.ts`.
- The client's balance-card and dashboard interfaces mirror the flat shape
  returned by `buildAccountBalanceReports`. Renaming a field there means editing
  `client/src/components/account-balance-card.tsx` and
  `client/src/pages/dashboard-page.tsx` too.
- When running the dev server through a pipe, don't cap it with `head -n` — the
  pipe closing terminates the server and looks exactly like a crash (clean exit,
  no stack trace).
