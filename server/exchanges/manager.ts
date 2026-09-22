import ccxt, { type Exchange, type Trade } from "ccxt";
import type { SupportedExchange } from "@shared/schema";
import type {
  ExchangeCredentials,
  StandardPosition,
  StandardWallet,
  StandardClosedTrade,
  ApiTestResult,
  CoinBalance,
} from "./types";
import * as bybitNative from "../bybit-api";
import { getElitePnl, getElitePositions } from "./bitget-elite";

interface ClientCacheEntry {
  client: Exchange;
  createdAt: number;
}

const clientCache = new Map<string, ClientCacheEntry>();

/** Bybit rejects a closed-P&L range wider than 7 days. */
const BYBIT_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
const BYBIT_PAGE_LIMIT = 100;
/** Bybit also pages at 100 rows, so cap cursor pages to bound the request count. */
const BYBIT_MAX_PAGES_PER_WINDOW = 3;
/** Bound the native history walk to 13 weekly windows (~91 days) per account. */
const BYBIT_MAX_LOOKBACK_MS = 13 * BYBIT_WINDOW_MS;

function getCacheKey(exchange: string, credentials?: ExchangeCredentials): string {
  return `${exchange}:${credentials?.apiKey ?? "public"}:${credentials?.passphrase ?? ""}`;
}

/**
 * Creates or retrieves a cached CCXT client instance configured for perpetual futures.
 */
export function getCcxtClient(exchange: SupportedExchange | string, credentials?: ExchangeCredentials): Exchange {
  const cacheKey = getCacheKey(exchange, credentials);
  const cached = clientCache.get(cacheKey);
  if (cached && Date.now() - cached.createdAt < 3600_000) {
    return cached.client;
  }

  const ex = exchange.toLowerCase();
  let client: Exchange;

  const config: Record<string, unknown> = {
    apiKey: credentials?.apiKey,
    secret: credentials?.apiSecret,
    password: credentials?.passphrase ?? undefined,
    enableRateLimit: true,
    timeout: 15_000,
  };

  switch (ex) {
    case "binance":
      client = new ccxt.binance({
        ...config,
        options: { defaultType: "future" },
      });
      break;
    case "okx":
      client = new ccxt.okx({
        ...config,
        options: { defaultType: "swap" },
      });
      break;
    case "bitget":
      client = new ccxt.bitget({
        ...config,
        options: { defaultType: "swap" },
      });
      break;
    case "gate":
      client = new ccxt.gate({
        ...config,
        options: { defaultType: "swap" },
      });
      break;
    case "bybit":
    default:
      client = new ccxt.bybit({
        ...config,
        options: { defaultType: "swap" },
      });
      break;
  }

  clientCache.set(cacheKey, { client, createdAt: Date.now() });
  return client;
}

/**
 * Warms a cached ccxt client's market cache with a single public call. Bitget
 * rate-limits those calls by IP, so callers warm clients one at a time before
 * fanning out; without this, concurrent balance reads trip 429s.
 */
export async function preloadExchangeClient(
  exchange: SupportedExchange | string,
  credentials: ExchangeCredentials,
): Promise<void> {
  if (exchange.toLowerCase() === "bybit") return;

  try {
    await getCcxtClient(exchange, credentials).loadMarkets();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Preloading ${exchange} markets failed: ${message}`);
  }
}

function cleanSymbol(symbol: string): string {
  // ccxt renders derivatives as "BASE/QUOTE:SETTLE", so drop the settle suffix
  // before stripping separators — otherwise "HYPE/USDT:USDT" -> "HYPEUSDTUSDT".
  // Also handles "BTC/USDT:USDT" -> "BTCUSDT" and "BTC-USDT-SWAP" -> "BTCUSDT".
  const [base] = symbol.split(":");
  return base.replace(/[/\-_]/g, "").replace(/SWAP$/i, "").toUpperCase();
}

/**
 * Test connectivity and credentials for an exchange account
 */
export async function testExchangeConnection(
  exchange: SupportedExchange | string,
  credentials?: ExchangeCredentials,
): Promise<ApiTestResult> {
  const ex = exchange.toLowerCase();

  // If Bybit, we can use the proven probe logic
  if (ex === "bybit") {
    const res = await bybitNative.testApiConnection(credentials ? {
      apiKey: credentials.apiKey,
      apiSecret: credentials.apiSecret,
    } : undefined);
    return {
      success: res.success,
      publicAccess: res.publicAccess,
      message: res.message,
      exchange: "bybit",
    };
  }

  try {
    const client = getCcxtClient(ex, credentials);
    // Public time probe
    let serverTime: number | undefined;
    try {
      serverTime = await client.fetchTime();
    } catch {
      // Not fatal if exchange doesn't support fetchTime
    }

    // Authenticated probe
    if (credentials?.apiKey && credentials?.apiSecret) {
      await client.fetchBalance();
      return {
        success: true,
        publicAccess: true,
        message: `Successfully connected to ${exchange} with credentials.`,
        exchange: ex,
        serverTime,
      };
    }

    return {
      success: true,
      publicAccess: true,
      message: `Public connection to ${exchange} is working.`,
      exchange: ex,
      serverTime,
    };
  } catch (error) {
    const err = error as Error;
    return {
      success: false,
      publicAccess: true,
      message: `Connection to ${exchange} failed: ${err.message ?? "unknown error"}`,
      exchange: ex,
    };
  }
}

/**
 * Fetch positions across supported exchanges
 */
export async function getExchangePositions(
  exchange: SupportedExchange | string,
  credentials: ExchangeCredentials,
  accountName = "Account",
  accountId?: number,
): Promise<StandardPosition[]> {
  const ex = exchange.toLowerCase();

  // Keep Bybit's robust native format for Bybit accounts
  if (ex === "bybit") {
    const rawPositions = await bybitNative.getPositions("linear", {
      apiKey: credentials.apiKey,
      apiSecret: credentials.apiSecret,
    });

    if (!rawPositions) return [];

    return rawPositions.map((p) => ({
      exchange: "bybit",
      accountName,
      accountId,
      symbol: p.symbol,
      side: p.side,
      size: String(p.size ?? "0"),
      leverage: String(p.leverage ?? "1"),
      avgPrice: String(p.avgPrice ?? "0"),
      markPrice: String(p.markPrice ?? "0"),
      unrealisedPnl: String(p.unrealisedPnl ?? "0"),
      positionValue: String(p.positionValue ?? "0"),
      liqPrice: String(p.liqPrice ?? "0"),
      takeProfit: String(p.takeProfit ?? ""),
      stopLoss: String(p.stopLoss ?? ""),
      positionStatus: p.positionStatus ?? "Normal",
      cumRealisedPnl: String(p.cumRealisedPnl ?? "0"),
      updatedTime: String(p.updatedTime ?? Date.now()),
    }));
  }

  // Bitget elite portfolios expose positions only through the copy-trading API.
  if (ex === "bitget") {
    const elite = await getElitePositions(credentials, accountName, accountId);
    if (elite) return elite;
  }

  // Use CCXT for Binance, OKX, Bitget, Gate
  try {
    const client = getCcxtClient(ex, credentials);
    const positions = await client.fetchPositions();
    const result: StandardPosition[] = [];

    for (const p of positions ?? []) {
      const contracts = Math.abs(Number(p.contracts ?? 0));
      if (contracts <= 0 && Number(p.notional ?? 0) <= 0) continue;

      const rawSide = (p.side ?? "long").toLowerCase();
      const side = rawSide === "buy" || rawSide === "long" ? "Buy" : "Sell";
      const symbol = p.symbol ? cleanSymbol(p.symbol) : "UNKNOWN";
      const notional = Number(p.notional ?? contracts * Number(p.entryPrice ?? 0));
      const initialMargin = Number(p.initialMargin ?? 0);

      // Binance's v3 positionRisk omits `leverage`; recover it from the margin
      // requirement (leverage = notional / initial margin).
      const leverage =
        Number(p.leverage ?? 0) || (initialMargin > 0 ? notional / initialMargin : 1);

      result.push({
        exchange: ex,
        accountName,
        accountId,
        symbol,
        side,
        size: String(contracts),
        leverage: String(Math.round(leverage * 100) / 100),
        avgPrice: String(p.entryPrice ?? "0"),
        markPrice: String(p.markPrice ?? "0"),
        unrealisedPnl: String(p.unrealizedPnl ?? "0"),
        positionValue: String(notional),
        liqPrice: String(p.liquidationPrice ?? "0"),
        takeProfit: "",
        stopLoss: "",
        positionStatus: "Normal",
        cumRealisedPnl: "0",
        updatedTime: String(p.timestamp ?? Date.now()),
      });
    }

    return result;
  } catch (error) {
    console.error(`Fetching positions from ${exchange} for ${accountName} failed:`, error);
    return [];
  }
}

/**
 * Fetch wallet balance across supported exchanges
 */
export async function getExchangeWalletBalance(
  exchange: SupportedExchange | string,
  credentials: ExchangeCredentials,
  accountName = "Account",
  accountId?: number,
): Promise<StandardWallet | null> {
  const ex = exchange.toLowerCase();

  // If Bybit, use native client
  if (ex === "bybit") {
    const raw = await bybitNative.getWalletBalance({
      apiKey: credentials.apiKey,
      apiSecret: credentials.apiSecret,
    });
    const summary = raw?.list?.[0];
    if (!summary) return null;

    const coins: CoinBalance[] = (summary.coin ?? [])
      .map((c) => ({
        coin: c.coin,
        walletBalance: Number(c.walletBalance ?? "0"),
        usdValue: Number(c.usdValue ?? "0"),
      }))
      .filter((c) => c.usdValue > 0.01 || c.walletBalance > 0);

    return {
      exchange: "bybit",
      accountName,
      accountId,
      accountType: summary.accountType,
      totalEquity: Number(summary.totalEquity ?? "0"),
      totalWalletBalance: Number(summary.totalWalletBalance ?? "0"),
      totalPerpUPL: Number(summary.totalPerpUPL ?? "0"),
      coin: coins,
    };
  }

  // CCXT for Binance, OKX, Bitget, Gate
  try {
    const client = getCcxtClient(ex, credentials);

    // Bitget accounts running in Unified Account (UTA) mode reject the classic
    // balance API, so a plain fetchBalance() returns an empty structure. Ask for
    // the UTA endpoint and fall back to the classic call for non-UTA accounts.
    let balance: Awaited<ReturnType<Exchange["fetchBalance"]>>;
    if (ex === "bitget") {
      try {
        balance = await client.fetchBalance({ uta: true });
      } catch {
        balance = await client.fetchBalance();
      }
    } else {
      balance = await client.fetchBalance();
    }

    const coins: CoinBalance[] = [];
    let totalEquity = 0;
    let totalWalletBalance = 0;
    let totalPerpUPL = 0;

    const totalMap = ((balance.total ?? {}) as unknown) as Record<string, number | undefined>;
    const usdtTotal = totalMap["USDT"] ?? totalMap["usdt"] ?? 0;

    // Check exchange specific summary info first
    if (ex === "binance") {
      const info = balance.info as Record<string, unknown>;
      totalEquity = Number(info?.totalMarginBalance ?? usdtTotal);
      totalWalletBalance = Number(info?.totalWalletBalance ?? usdtTotal);
      totalPerpUPL = Number(info?.totalUnrealizedProfit ?? 0);
    } else if (ex === "okx") {
      const infoList = (balance.info as { data?: Array<Record<string, unknown>> })?.data;
      const primary = infoList?.[0];
      if (primary) {
        totalEquity = Number(primary.totalEq ?? 0);
        totalWalletBalance = Number(primary.isoEq ?? totalEquity);
        totalPerpUPL = Number(primary.upl ?? 0);
      }
    } else {
      // General fallback
      totalWalletBalance = Number(usdtTotal);
      totalEquity = totalWalletBalance;
    }

    // Extract non-zero coin balances
    for (const [coin, amount] of Object.entries(totalMap)) {
      const numAmount = Number(amount ?? 0);
      if (numAmount > 0.0001) {
        const isUsdt = coin.toUpperCase() === "USDT" || coin.toUpperCase() === "USD";
        const estimatedUsd = isUsdt ? numAmount : numAmount; // conservative baseline
        coins.push({
          coin,
          walletBalance: Math.round(numAmount * 10000) / 10000,
          usdValue: Math.round(estimatedUsd * 100) / 100,
        });
      }
    }

    if (totalEquity === 0 && coins.length > 0) {
      totalEquity = coins.reduce((sum, c) => sum + c.usdValue, 0);
      totalWalletBalance = totalEquity;
    }

    return {
      exchange: ex,
      accountName,
      accountId,
      accountType: "UNIFIED",
      totalEquity,
      totalWalletBalance,
      totalPerpUPL,
      coin: coins.sort((a, b) => b.usdValue - a.usdValue),
    };
  } catch (error) {
    console.error(`Fetching wallet balance from ${exchange} for ${accountName} failed:`, error);
    return null;
  }
}

/**
 * Fetch closed PnL / trade executions for performance reports
 */
export async function getExchangeClosedPnL(
  exchange: SupportedExchange | string,
  credentials: ExchangeCredentials,
  options: { startTime?: number; endTime?: number; limit?: number } = {},
): Promise<StandardClosedTrade[]> {
  const ex = exchange.toLowerCase();
  const { startTime, endTime, limit = 200 } = options;

  // Bybit rejects a closed-P&L range wider than 7 days (and ignores a lone
  // startTime), so walk the window in week-long slices, newest first, until the
  // look-back or row limit is reached.
  if (ex === "bybit") {
    const bybitCredentials = {
      apiKey: credentials.apiKey,
      apiSecret: credentials.apiSecret,
    };
    const to = endTime ?? Date.now();
    const from = Math.max(startTime ?? to - BYBIT_WINDOW_MS, to - BYBIT_MAX_LOOKBACK_MS);
    const trades: StandardClosedTrade[] = [];

    for (
      let windowEnd = to;
      windowEnd > from && trades.length < limit;
      windowEnd -= BYBIT_WINDOW_MS
    ) {
      const windowStart = Math.max(from, windowEnd - BYBIT_WINDOW_MS);
      let cursor: string | undefined;
      let pages = 0;

      do {
        const raw = await bybitNative.getClosedPnL({
          credentials: bybitCredentials,
          limit: Math.min(limit - trades.length, BYBIT_PAGE_LIMIT),
          startTime: windowStart,
          endTime: windowEnd,
          cursor,
        });
        if (!raw?.list?.length) break;

        for (const t of raw.list) {
          trades.push({
            symbol: t.symbol ?? "UNKNOWN",
            closedPnl: String(t.closedPnl ?? "0"),
            cumEntryValue: String(t.cumEntryValue ?? "0"),
            leverage: String(t.leverage ?? "1"),
            closedSize: String(t.closedSize ?? "0"),
            avgEntryPrice: String(t.avgEntryPrice ?? "0"),
            createdTime: String(t.createdTime ?? Date.now()),
          });
        }

        cursor = raw.nextPageCursor || undefined;
        pages += 1;
      } while (cursor && trades.length < limit && pages < BYBIT_MAX_PAGES_PER_WINDOW);
    }

    return trades.slice(0, limit);
  }

  // Binance reports realised P&L through the futures income ledger, which —
  // unlike fetchMyTrades — does not need a symbol per call.
  if (ex === "binance") {
    try {
      const client = getCcxtClient(ex, credentials);
      const entries = await client.fetchLedger(undefined, startTime, limit, {
        incomeType: "REALIZED_PNL",
      });
      return entries.map((entry) => {
        // parseLedgerEntry folds the sign into `direction` and keeps `amount`
        // positive, so re-apply it here.
        const magnitude = Number(entry.amount ?? 0);
        const signed = entry.direction === "out" ? -magnitude : magnitude;
        const info = entry.info as { symbol?: string };
        return {
          symbol: info?.symbol ? cleanSymbol(info.symbol) : "UNKNOWN",
          closedPnl: String(signed),
          cumEntryValue: "0",
          leverage: "1",
          closedSize: "0",
          avgEntryPrice: "0",
          createdTime: String(entry.timestamp ?? Date.now()),
        };
      });
    } catch (error) {
      console.error(`Fetching closed PnL from ${exchange} failed:`, error);
      return [];
    }
  }

  // Bitget's classic fills endpoint is disabled for Unified Accounts, and the
  // elite copy-trading API has no per-fill history. Realised P&L is exposed as a
  // running total through getExchangePnlSnapshot instead.
  if (ex === "bitget") return [];

  // For Binance, OKX, Gate: use CCXT fetchMyTrades
  try {
    const client = getCcxtClient(ex, credentials);
    let trades: Trade[] = [];

    if (client.has["fetchMyTrades"]) {
      trades = await client.fetchMyTrades(undefined, startTime, limit);
    }

    const results: StandardClosedTrade[] = [];
    for (const t of trades) {
      const info = t.info as Record<string, unknown>;
      // Look for realized PnL fields in various exchange trade objects
      const pnl = Number(
        info?.realizedPnl ?? info?.fillPnl ?? info?.pnl ?? t.fee?.cost ?? 0,
      );
      if (pnl === 0 && !info?.realizedPnl) continue;

      const symbol = t.symbol ? cleanSymbol(t.symbol) : "UNKNOWN";
      const notional = Number(t.cost ?? (Number(t.amount ?? 0) * Number(t.price ?? 0)));

      results.push({
        symbol,
        closedPnl: String(pnl),
        cumEntryValue: String(notional),
        leverage: "1",
        closedSize: String(t.amount ?? 0),
        avgEntryPrice: String(t.price ?? 0),
        createdTime: String(t.timestamp ?? Date.now()),
      });
    }

    return results;
  } catch (error) {
    console.error(`Fetching closed PnL from ${exchange} failed:`, error);
    return [];
  }
}

export interface ExchangePnlSnapshot {
  realizedPnl: number;
  unrealizedPnl: number;
}

/**
 * P&L that cannot be reconstructed from closed fills, for exchanges whose API
 * only reports running totals. Currently only Bitget elite portfolios; returns
 * `null` for everything else so callers keep the trade-derived figures.
 */
export async function getExchangePnlSnapshot(
  exchange: SupportedExchange | string,
  credentials: ExchangeCredentials,
): Promise<ExchangePnlSnapshot | null> {
  if (exchange.toLowerCase() !== "bitget") return null;
  return getElitePnl(credentials);
}
