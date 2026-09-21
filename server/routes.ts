import type { Express, Request, Response } from "express";
import { createServer, type Server } from "http";
import { z } from "zod";
import { storage } from "./storage";
import { setupWebSocket } from "./websocket";
import { startAlertWatcher } from "./alerts";
import { getCandles, getLastPrice, getServerTime, isValidInterval, KLINE_INTERVALS } from "./market";
import {
  testExchangeConnection,
  getExchangePositions,
  getExchangeWalletBalance,
} from "./exchanges/manager";
import {
  aggregatePositions,
  aggregateWalletBalances,
  buildAccountBalanceReports,
  buildTradingReports,
  buildTradeHistory,
  buildTrophyStats,
} from "./trading";
import { analyseMarket, analysePerformance, reviewStrategy } from "./ai/analyze";
import { AiConfigError, isAiConfigured, listModels } from "./ai";
import {
  insertAccountSchema,
  insertAlertSchema,
  insertStrategySchema,
  updateStrategySchema,
  SUPPORTED_EXCHANGES,
} from "@shared/schema";
import { getMarketHours } from "./market-hours";

/**
 * The API is unauthenticated. Bind to loopback (the default) — anything that can
 * reach this port can read exchange balances and add or delete accounts.
 */

/** Live figures must never be served from a cache. */
function noStore(res: Response) {
  res.set("Cache-Control", "no-store");
}

/** Wraps an async handler so a rejected promise becomes a 500, not a crash. */
function handler(fn: (req: Request, res: Response) => Promise<unknown>) {
  return (req: Request, res: Response) => {
    fn(req, res).catch((error: Error) => {
      if (error instanceof AiConfigError) {
        res.status(503).json({ error: error.message });
        return;
      }
      console.error(`${req.method} ${req.path} failed:`, error);
      if (!res.headersSent) {
        res.status(500).json({ error: error.message ?? "Internal server error" });
      }
    });
  };
}

function badRequest(res: Response, error: z.ZodError) {
  return res.status(400).json({
    error: "Validation failed",
    issues: error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
  });
}

const idParam = z.coerce.number().int().positive();

export async function registerRoutes(app: Express): Promise<Server> {
  // -- Status ---------------------------------------------------------------

  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", ai: isAiConfigured() });
  });

  app.get(
    "/api/server-time",
    handler(async (_req, res) => {
      const time = await getServerTime();
      res.json({ success: true, serverTime: { timestamp: time.timeSecond, iso: time.iso } });
    }),
  );

  app.get(
    "/api/market-hours",
    handler(async (_req, res) => {
      // Prefer exchange time, but never fail the request over it.
      let timestamp = Math.floor(Date.now() / 1000);
      let source = "local";
      try {
        timestamp = (await getServerTime()).timeSecond;
        source = "bybit";
      } catch {
        // Local clock is a fine fallback for market-hours display.
      }

      res.json({
        success: true,
        source,
        timestamp,
        iso: new Date(timestamp * 1000).toISOString(),
        markets: getMarketHours(timestamp),
      });
    }),
  );

  // -- Market data ----------------------------------------------------------

  const candleQuery = z.object({
    symbol: z.string().min(3),
    interval: z.string().default("60"),
    limit: z.coerce.number().int().min(1).max(1000).default(200),
    category: z.enum(["linear", "inverse", "spot"]).default("linear"),
  });

  app.get(
    "/api/market/candles",
    handler(async (req, res) => {
      const parsed = candleQuery.safeParse(req.query);
      if (!parsed.success) return badRequest(res, parsed.error);
      if (!isValidInterval(parsed.data.interval)) {
        return res.status(400).json({
          error: `Invalid interval. Expected one of: ${KLINE_INTERVALS.join(", ")}`,
        });
      }

      const candles = await getCandles(parsed.data);
      noStore(res);
      res.json({ ...parsed.data, candles });
    }),
  );

  app.get(
    "/api/market/price",
    handler(async (req, res) => {
      const parsed = z.object({ symbol: z.string().min(3) }).safeParse(req.query);
      if (!parsed.success) return badRequest(res, parsed.error);

      const price = await getLastPrice(parsed.data.symbol);
      noStore(res);
      res.json({ symbol: parsed.data.symbol.toUpperCase(), price });
    }),
  );

  // -- Aggregated Exchange views --------------------------------------------

  const handlePositions = async (req: Request, res: Response) => {
    const category = req.query.category === "inverse" ? "inverse" : "linear";
    noStore(res);
    res.json(await aggregatePositions(category));
  };

  app.get("/api/exchange/positions", handler(handlePositions));
  app.get("/api/bybit/positions", handler(handlePositions));

  const handleWallet = async (_req: Request, res: Response) => {
    const balances = await aggregateWalletBalances();
    if (balances.length === 0) {
      return res.status(404).json({
        success: false,
        message: "No exchange account returned a balance. Check credentials in Accounts.",
      });
    }
    noStore(res);
    res.json({ success: true, data: balances });
  };

  app.get("/api/exchange/wallet", handler(handleWallet));
  app.get("/api/bybit/wallet", handler(handleWallet));

  const handleTest = async (req: Request, res: Response) => {
    const exchange = (req.query.exchange as string) ?? "bybit";
    res.json(await testExchangeConnection(exchange));
  };

  app.get("/api/exchange/test", handler(handleTest));
  app.get("/api/bybit/test", handler(handleTest));

  app.get(
    "/api/trophy-stats",
    handler(async (_req, res) => {
      noStore(res);
      res.json(await buildTrophyStats());
    }),
  );

  app.get(
    "/api/trading-reports",
    handler(async (req, res) => {
      const parsed = z
        .object({ timeframe: z.coerce.number().int().min(1).max(365).default(7) })
        .safeParse(req.query);
      if (!parsed.success) return badRequest(res, parsed.error);

      noStore(res);
      res.json(await buildTradingReports(parsed.data.timeframe));
    }),
  );

  app.get(
    "/api/exchange/history",
    handler(async (req, res) => {
      const parsed = z
        .object({
          // Bybit and Binance both cap a single history query, so the window is
          // bounded here too.
          timeframe: z.coerce.number().int().min(1).max(90).default(30),
          exchange: z.enum(SUPPORTED_EXCHANGES).optional(),
          symbol: z.string().max(32).optional(),
          limit: z.coerce.number().int().min(1).max(1000).default(200),
        })
        .safeParse(req.query);
      if (!parsed.success) return badRequest(res, parsed.error);

      noStore(res);
      res.json(
        await buildTradeHistory({
          timeframeDays: parsed.data.timeframe,
          exchange: parsed.data.exchange,
          symbol: parsed.data.symbol,
          limit: parsed.data.limit,
        }),
      );
    }),
  );

  app.get(
    "/api/account-balance",
    handler(async (_req, res) => {
      noStore(res);
      res.json(await buildAccountBalanceReports());
    }),
  );

  // -- Accounts -------------------------------------------------------------

  app.get(
    "/api/accounts",
    handler(async (_req, res) => {
      // Credentials never leave the server.
      const accounts = await storage.getAllAccounts();
      res.json(
        accounts.map(({ apiKey, apiSecret, passphrase, ...rest }) => ({
          ...rest,
          hasCredentials: Boolean(apiKey && apiSecret),
          hasPassphrase: Boolean(passphrase),
        })),
      );
    }),
  );

  app.post(
    "/api/accounts",
    handler(async (req, res) => {
      const parsed = insertAccountSchema.safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);

      const account = await storage.createAccount(parsed.data);
      const { apiKey, apiSecret, passphrase, ...safe } = account;
      res.status(201).json({
        ...safe,
        hasCredentials: Boolean(apiKey && apiSecret),
        hasPassphrase: Boolean(passphrase),
      });
    }),
  );

  app.put(
    "/api/accounts/:id",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid account id" });

      const parsed = insertAccountSchema.partial().safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);

      const updated = await storage.updateAccount(id.data, parsed.data);
      if (!updated) return res.status(404).json({ error: "Account not found" });

      const { apiKey, apiSecret, passphrase, ...safe } = updated;
      res.json({
        ...safe,
        hasCredentials: Boolean(apiKey && apiSecret),
        hasPassphrase: Boolean(passphrase),
      });
    }),
  );

  app.delete(
    "/api/accounts/:id",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid account id" });

      const deleted = await storage.deleteAccount(id.data);
      if (!deleted) return res.status(404).json({ error: "Account not found" });
      res.sendStatus(204);
    }),
  );

  /** Loads an account and rejects it if it can't serve exchange reads. */
  async function tradableAccount(req: Request, res: Response) {
    const id = idParam.safeParse(req.params.id);
    if (!id.success) {
      res.status(400).json({ error: "Invalid account id" });
      return null;
    }

    const account = await storage.getAccount(id.data);
    if (!account) {
      res.status(404).json({ error: "Account not found" });
      return null;
    }
    if (!(SUPPORTED_EXCHANGES as readonly string[]).includes(account.exchange)) {
      res.status(400).json({ error: `Unsupported exchange: ${account.exchange}` });
      return null;
    }
    if (!account.apiKey || !account.apiSecret) {
      res.status(400).json({ error: "Account has no API credentials configured" });
      return null;
    }
    return account;
  }

  app.get(
    "/api/accounts/:id/positions",
    handler(async (req, res) => {
      const account = await tradableAccount(req, res);
      if (!account) return;

      const positions = await getExchangePositions(
        account.exchange,
        { apiKey: account.apiKey, apiSecret: account.apiSecret, passphrase: account.passphrase },
        account.name,
        account.id,
      );
      noStore(res);
      res.json(positions);
    }),
  );

  app.get(
    "/api/accounts/:id/wallet",
    handler(async (req, res) => {
      const account = await tradableAccount(req, res);
      if (!account) return;

      const wallet = await getExchangeWalletBalance(
        account.exchange,
        { apiKey: account.apiKey, apiSecret: account.apiSecret, passphrase: account.passphrase },
        account.name,
        account.id,
      );
      if (!wallet) {
        return res.status(502).json({ error: `${account.exchange} did not return a balance for this account` });
      }
      noStore(res);
      res.json(wallet);
    }),
  );

  app.get(
    "/api/accounts/:id/test",
    handler(async (req, res) => {
      const account = await tradableAccount(req, res);
      if (!account) return;

      res.json(
        await testExchangeConnection(account.exchange, {
          apiKey: account.apiKey,
          apiSecret: account.apiSecret,
          passphrase: account.passphrase,
        }),
      );
    }),
  );

  // -- Alerts ---------------------------------------------------------------

  app.get(
    "/api/alerts",
    handler(async (req, res) => {
      const parsed = z
        .object({ status: z.enum(["active", "triggered", "cancelled"]).optional() })
        .safeParse(req.query);
      if (!parsed.success) return badRequest(res, parsed.error);

      res.json(await storage.getAlerts(parsed.data.status));
    }),
  );

  app.post(
    "/api/alerts",
    handler(async (req, res) => {
      const parsed = insertAlertSchema.safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);

      // Reject symbols the exchange doesn't price, so alerts can't sit dead.
      try {
        await getLastPrice(parsed.data.symbol);
      } catch {
        return res
          .status(400)
          .json({ error: `Bybit does not price "${parsed.data.symbol}" on the linear market` });
      }

      res.status(201).json(await storage.createAlert(parsed.data));
    }),
  );

  app.post(
    "/api/alerts/:id/cancel",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid alert id" });

      const cancelled = await storage.cancelAlert(id.data);
      if (!cancelled) {
        return res.status(404).json({ error: "No active alert with that id" });
      }
      res.json(await storage.getAlert(id.data));
    }),
  );

  app.delete(
    "/api/alerts/:id",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid alert id" });

      const deleted = await storage.deleteAlert(id.data);
      if (!deleted) return res.status(404).json({ error: "Alert not found" });
      res.sendStatus(204);
    }),
  );

  // -- Strategies -----------------------------------------------------------

  app.get(
    "/api/strategies",
    handler(async (_req, res) => {
      res.json(await storage.getStrategies());
    }),
  );

  app.get(
    "/api/strategies/:id",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid strategy id" });

      const strategy = await storage.getStrategy(id.data);
      if (!strategy) return res.status(404).json({ error: "Strategy not found" });
      res.json(strategy);
    }),
  );

  app.post(
    "/api/strategies",
    handler(async (req, res) => {
      const parsed = insertStrategySchema.safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);
      if (!isValidInterval(parsed.data.timeframe)) {
        return res.status(400).json({
          error: `Invalid timeframe. Expected one of: ${KLINE_INTERVALS.join(", ")}`,
        });
      }

      res.status(201).json(await storage.createStrategy(parsed.data));
    }),
  );

  app.patch(
    "/api/strategies/:id",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid strategy id" });

      const parsed = updateStrategySchema.safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);
      if (parsed.data.timeframe && !isValidInterval(parsed.data.timeframe)) {
        return res.status(400).json({
          error: `Invalid timeframe. Expected one of: ${KLINE_INTERVALS.join(", ")}`,
        });
      }

      const updated = await storage.updateStrategy(id.data, parsed.data);
      if (!updated) return res.status(404).json({ error: "Strategy not found" });
      res.json(updated);
    }),
  );

  app.delete(
    "/api/strategies/:id",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid strategy id" });

      const deleted = await storage.deleteStrategy(id.data);
      if (!deleted) return res.status(404).json({ error: "Strategy not found" });
      res.sendStatus(204);
    }),
  );

  // -- AI -------------------------------------------------------------------

  app.get("/api/ai/config", (_req, res) => {
    res.json({ configured: isAiConfigured(), models: listModels() });
  });

  const aiOptions = z.object({
    question: z.string().max(1000).optional(),
    model: z.string().optional(),
    effort: z.enum(["low", "medium", "high", "xhigh", "max"]).optional(),
  });

  app.post(
    "/api/ai/market",
    handler(async (req, res) => {
      const parsed = aiOptions
        .extend({
          symbol: z.string().min(3),
          interval: z.string().default("60"),
          limit: z.coerce.number().int().min(10).max(500).default(120),
        })
        .safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);

      const { symbol, interval, limit, ...rest } = parsed.data;
      const candles = await getCandles({ symbol, interval, limit });
      res.json(await analyseMarket({ symbol, interval, candles, ...rest }));
    }),
  );

  app.post(
    "/api/ai/performance",
    handler(async (req, res) => {
      const parsed = aiOptions
        .extend({ timeframe: z.coerce.number().int().min(1).max(365).default(7) })
        .safeParse(req.body);
      if (!parsed.success) return badRequest(res, parsed.error);

      const { timeframe, ...rest } = parsed.data;
      const [reports, balances] = await Promise.all([
        buildTradingReports(timeframe),
        buildAccountBalanceReports(),
      ]);
      res.json(await analysePerformance({ reports, balances, ...rest }));
    }),
  );

  app.post(
    "/api/ai/strategies/:id/review",
    handler(async (req, res) => {
      const id = idParam.safeParse(req.params.id);
      if (!id.success) return res.status(400).json({ error: "Invalid strategy id" });

      const parsed = aiOptions.safeParse(req.body ?? {});
      if (!parsed.success) return badRequest(res, parsed.error);

      const strategy = await storage.getStrategy(id.data);
      if (!strategy) return res.status(404).json({ error: "Strategy not found" });

      // Market context is a nice-to-have; a review without it is still useful.
      let candles;
      try {
        candles = await getCandles({
          symbol: strategy.symbol,
          interval: strategy.timeframe,
          limit: 120,
        });
      } catch {
        candles = undefined;
      }

      res.json(await reviewStrategy({ strategy, candles, ...parsed.data }));
    }),
  );

  // -- Server ---------------------------------------------------------------

  const httpServer = createServer(app);
  setupWebSocket(httpServer);
  startAlertWatcher(Number(process.env.ALERT_POLL_MS ?? 30_000));

  return httpServer;
}
