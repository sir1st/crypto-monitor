#!/usr/bin/env node
import dotenv from "dotenv";

dotenv.config();

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { createApiClient, ApiError } from "./client";

/**
 * MCP server exposing Vale Monitor to agents such as Claude Code.
 *
 * Transport is stdio, so **nothing may be written to stdout** except protocol
 * frames — all logging goes to stderr.
 */

const KLINE_INTERVALS = [
  "1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M",
] as const;

const api = createApiClient();

/** MCP tool results are content blocks; JSON is returned as pretty text. */
function json(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

function failure(error: unknown) {
  const message =
    error instanceof ApiError ? error.message : `Unexpected error: ${(error as Error).message}`;
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

/** Wraps a handler so a failed call becomes a tool error, not a crash. */
function tool<T>(fn: (args: T) => Promise<unknown>) {
  return async (args: T) => {
    try {
      return json(await fn(args));
    } catch (error) {
      return failure(error);
    }
  };
}

const server = new McpServer({ name: "vale-monitor", version: "1.0.0" });

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

server.registerTool(
  "server_status",
  {
    title: "Server status",
    description:
      "Confirms the Vale server is reachable and reports whether its AI layer has a provider key. Call this first if other tools are failing.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(async () => api.get("/api/health")),
);

// ---------------------------------------------------------------------------
// Market data
// ---------------------------------------------------------------------------

server.registerTool(
  "get_candles",
  {
    title: "Get candles",
    description:
      "Reads OHLCV candles for a symbol from Bybit, oldest first. Works without exchange API keys. Use this for price action, trend and volatility questions.",
    inputSchema: {
      symbol: z.string().describe('Trading pair, e.g. "BTCUSDT"'),
      interval: z
        .enum(KLINE_INTERVALS)
        .default("60")
        .describe('Candle interval in minutes, or "D"/"W"/"M"'),
      limit: z.number().int().min(1).max(1000).default(200).describe("Number of candles"),
      category: z.enum(["linear", "inverse", "spot"]).default("linear"),
    },
    annotations: { readOnlyHint: true },
  },
  tool((args) => api.get("/api/market/candles", args)),
);

server.registerTool(
  "get_price",
  {
    title: "Get last price",
    description: "Last traded price for a symbol on the Bybit linear market.",
    inputSchema: { symbol: z.string().describe('Trading pair, e.g. "ETHUSDT"') },
    annotations: { readOnlyHint: true },
  },
  tool(({ symbol }) => api.get("/api/market/price", { symbol })),
);

server.registerTool(
  "get_market_hours",
  {
    title: "Get market hours",
    description: "Open/closed status of the major equity exchanges plus crypto.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(() => api.get("/api/market-hours")),
);

// ---------------------------------------------------------------------------
// Account state
// ---------------------------------------------------------------------------

server.registerTool(
  "get_positions",
  {
    title: "Get open positions",
    description:
      "Open positions across every configured Bybit account, each tagged with its account name. Requires at least one account with API credentials.",
    inputSchema: { category: z.enum(["linear", "inverse"]).default("linear") },
    annotations: { readOnlyHint: true },
  },
  tool((args) => api.get("/api/bybit/positions", args)),
);

server.registerTool(
  "get_account_balances",
  {
    title: "Get account balances",
    description:
      "Per-account equity, derived historical balances, 7-day and week-to-date performance, per-symbol breakdown and 1-5% position sizing.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(() => api.get("/api/account-balance")),
);

server.registerTool(
  "get_trading_report",
  {
    title: "Get trading report",
    description:
      "Realised performance per account over a window. ROI is calculated on margin committed (entry notional / leverage), not on notional size.",
    inputSchema: {
      timeframe: z.number().int().min(1).max(365).default(7).describe("Look-back window in days"),
    },
    annotations: { readOnlyHint: true },
  },
  tool(({ timeframe }) => api.get("/api/trading-reports", { timeframe })),
);

server.registerTool(
  "get_trade_history",
  {
    title: "Get trade history",
    description:
      "Individual closed trades across accounts, newest first, with margin-based ROI. Bitget elite portfolios do not expose per-fill history, so they are absent.",
    inputSchema: {
      timeframe: z
        .number()
        .int()
        .min(1)
        .max(90)
        .default(30)
        .describe("Look-back window in days (max 90 — exchange history APIs are capped)"),
      exchange: z
        .string()
        .optional()
        .describe("Filter to one exchange: bybit, binance, okx, bitget or gate"),
      account: z.string().max(120).optional().describe("Filter to one account name"),
      symbol: z.string().max(32).optional().describe("Filter by symbol substring, e.g. SOL"),
      limit: z.number().int().min(1).max(1000).default(200).describe("Maximum rows to return"),
    },
    annotations: { readOnlyHint: true },
  },
  tool((args) => api.get("/api/exchange/history", args)),
);

server.registerTool(
  "get_weekly_highlights",
  {
    title: "Get weekly highlights",
    description:
      "Best trade of the current week (Monday 00:00 UTC onward) by ROI and by absolute profit.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(() => api.get("/api/trophy-stats")),
);

server.registerTool(
  "list_accounts",
  {
    title: "List accounts",
    description:
      "Configured exchange accounts. API credentials are never returned — only whether each account has them.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(() => api.get("/api/accounts")),
);

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

server.registerTool(
  "list_alerts",
  {
    title: "List alerts",
    description: "Price alerts, optionally filtered by status.",
    inputSchema: {
      status: z.enum(["active", "triggered", "cancelled"]).optional(),
    },
    annotations: { readOnlyHint: true },
  },
  tool((args) => api.get("/api/alerts", args)),
);

server.registerTool(
  "create_alert",
  {
    title: "Create alert",
    description:
      "Creates a price alert. The server checks the symbol is priced by the exchange before accepting it, and marks the alert triggered once the threshold is crossed.",
    inputSchema: {
      symbol: z.string().describe('Trading pair, e.g. "BTCUSDT"'),
      direction: z.enum(["above", "below"]).describe("Fire when price goes above or below"),
      price: z.number().positive().describe("Threshold price"),
      note: z.string().max(500).optional().describe("Why this level matters"),
    },
  },
  tool((args) => api.post("/api/alerts", args)),
);

server.registerTool(
  "cancel_alert",
  {
    title: "Cancel alert",
    description: "Cancels an active alert, keeping it on record.",
    inputSchema: { id: z.number().int().positive() },
  },
  tool(({ id }) => api.post(`/api/alerts/${id}/cancel`)),
);

server.registerTool(
  "delete_alert",
  {
    title: "Delete alert",
    description: "Permanently deletes an alert.",
    inputSchema: { id: z.number().int().positive() },
    annotations: { destructiveHint: true },
  },
  tool(async ({ id }) => {
    await api.del(`/api/alerts/${id}`);
    return { deleted: id };
  }),
);

// ---------------------------------------------------------------------------
// Strategies
// ---------------------------------------------------------------------------

server.registerTool(
  "list_strategies",
  {
    title: "List strategies",
    description: "Saved strategies with their rules and status.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(() => api.get("/api/strategies")),
);

server.registerTool(
  "get_strategy",
  {
    title: "Get strategy",
    description: "A single strategy by id.",
    inputSchema: { id: z.number().int().positive() },
    annotations: { readOnlyHint: true },
  },
  tool(({ id }) => api.get(`/api/strategies/${id}`)),
);

server.registerTool(
  "create_strategy",
  {
    title: "Create strategy",
    description:
      "Saves a strategy. `rules` is free-form JSON — put entry/exit conditions and risk parameters in whatever shape suits, it is stored as given and not executed.",
    inputSchema: {
      name: z.string().min(1).max(120),
      symbol: z.string().describe('Trading pair, e.g. "SOLUSDT"'),
      timeframe: z.enum(KLINE_INTERVALS).default("60"),
      description: z.string().max(2000).optional(),
      rules: z.record(z.unknown()).optional().describe("Free-form JSON rules object"),
      status: z.enum(["draft", "active", "paused"]).default("draft"),
    },
  },
  tool((args) => api.post("/api/strategies", args)),
);

server.registerTool(
  "update_strategy",
  {
    title: "Update strategy",
    description: "Updates any subset of a strategy's fields.",
    inputSchema: {
      id: z.number().int().positive(),
      name: z.string().min(1).max(120).optional(),
      symbol: z.string().optional(),
      timeframe: z.enum(KLINE_INTERVALS).optional(),
      description: z.string().max(2000).optional(),
      rules: z.record(z.unknown()).optional(),
      status: z.enum(["draft", "active", "paused"]).optional(),
    },
  },
  tool(({ id, ...updates }) => api.patch(`/api/strategies/${id}`, updates)),
);

server.registerTool(
  "delete_strategy",
  {
    title: "Delete strategy",
    description: "Permanently deletes a strategy.",
    inputSchema: { id: z.number().int().positive() },
    annotations: { destructiveHint: true },
  },
  tool(async ({ id }) => {
    await api.del(`/api/strategies/${id}`);
    return { deleted: id };
  }),
);

// ---------------------------------------------------------------------------
// AI analysis
// ---------------------------------------------------------------------------

const aiArgs = {
  question: z.string().max(1000).optional().describe("Ask something specific instead of the default analysis"),
  model: z.string().optional().describe("Override the configured model id"),
  effort: z.enum(["low", "medium", "high", "xhigh", "max"]).optional(),
};

server.registerTool(
  "ai_config",
  {
    title: "AI configuration",
    description:
      "Whether the server's AI layer has a provider key, and which models are registered.",
    inputSchema: {},
    annotations: { readOnlyHint: true },
  },
  tool(() => api.get("/api/ai/config")),
);

server.registerTool(
  "analyze_market",
  {
    title: "Analyze market",
    description:
      "Runs the server's AI layer over a candle window. Costs tokens on the server's configured provider — prefer get_candles when you want to reason over the data yourself.",
    inputSchema: {
      symbol: z.string(),
      interval: z.enum(KLINE_INTERVALS).default("60"),
      limit: z.number().int().min(10).max(500).default(120),
      ...aiArgs,
    },
  },
  tool((args) => api.post("/api/ai/market", args)),
);

server.registerTool(
  "analyze_performance",
  {
    title: "Analyze performance",
    description:
      "Runs the server's AI layer over realised performance across accounts. Costs tokens on the server's configured provider.",
    inputSchema: {
      timeframe: z.number().int().min(1).max(365).default(7),
      ...aiArgs,
    },
  },
  tool((args) => api.post("/api/ai/performance", args)),
);

server.registerTool(
  "review_strategy",
  {
    title: "Review strategy",
    description:
      "Runs the server's AI layer over a saved strategy plus recent price action for its symbol. Costs tokens on the server's configured provider.",
    inputSchema: { id: z.number().int().positive(), ...aiArgs },
  },
  tool(({ id, ...rest }) => api.post(`/api/ai/strategies/${id}/review`, rest)),
);

// ---------------------------------------------------------------------------

async function main() {
  await server.connect(new StdioServerTransport());
  // stderr only — stdout carries the protocol.
  console.error(
    `vale-monitor MCP server ready (api: ${process.env.VALE_API_URL ?? "http://127.0.0.1:5000"})`,
  );
}

main().catch((error) => {
  console.error("MCP server failed to start:", error);
  process.exit(1);
});
