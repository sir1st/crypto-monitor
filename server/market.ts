import axios from "axios";
import type { Candle } from "@shared/schema";

/**
 * Public Bybit market data. These endpoints need no API key, so candles and
 * prices work on a fresh install before any account is configured.
 */
const client = axios.create({
  baseURL: process.env.BYBIT_BASE_URL ?? "https://api.bybit.com",
  timeout: 10_000,
});

export const KLINE_INTERVALS = [
  "1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M",
] as const;

export type KlineInterval = (typeof KLINE_INTERVALS)[number];

export function isValidInterval(value: string): value is KlineInterval {
  return (KLINE_INTERVALS as readonly string[]).includes(value);
}

/** Bybit rejects unknown categories, so keep this to the ones we support. */
export type MarketCategory = "linear" | "inverse" | "spot";

class MarketDataError extends Error {
  constructor(message: string, readonly retCode?: number) {
    super(message);
    this.name = "MarketDataError";
  }
}

function describeAxiosFailure(error: unknown, action: string): never {
  const err = error as { response?: { data?: unknown }; message?: string };
  const body = err.response?.data;

  // Bybit fronts its API with CloudFront, which returns an HTML block page for
  // geo-restricted regions rather than a JSON error.
  if (typeof body === "string" && body.includes("CloudFront")) {
    throw new MarketDataError(
      `${action} failed: Bybit is not reachable from this region (CloudFront geo-block).`,
    );
  }

  throw new MarketDataError(`${action} failed: ${err.message ?? "unknown error"}`);
}

/**
 * Fetches OHLCV candles, oldest first. Bybit returns newest-first, which is the
 * opposite of what charting and indicator code expects.
 */
export async function getCandles(options: {
  symbol: string;
  interval?: string;
  limit?: number;
  category?: MarketCategory;
  start?: number;
  end?: number;
}): Promise<Candle[]> {
  const { symbol, interval = "60", limit = 200, category = "linear", start, end } = options;

  if (!isValidInterval(interval)) {
    throw new MarketDataError(
      `Invalid interval "${interval}". Expected one of: ${KLINE_INTERVALS.join(", ")}`,
    );
  }

  try {
    const { data } = await client.get("/v5/market/kline", {
      params: {
        category,
        symbol: symbol.toUpperCase(),
        interval,
        limit: Math.min(Math.max(limit, 1), 1000),
        ...(start ? { start } : {}),
        ...(end ? { end } : {}),
      },
    });

    if (data.retCode !== 0) {
      throw new MarketDataError(`Bybit rejected the kline request: ${data.retMsg}`, data.retCode);
    }

    const rows: string[][] = data.result?.list ?? [];
    return rows
      .map((row) => ({
        openTime: Number(row[0]),
        open: Number(row[1]),
        high: Number(row[2]),
        low: Number(row[3]),
        close: Number(row[4]),
        volume: Number(row[5]),
        turnover: Number(row[6]),
      }))
      .sort((a, b) => a.openTime - b.openTime);
  } catch (error) {
    if (error instanceof MarketDataError) throw error;
    describeAxiosFailure(error, `Fetching candles for ${symbol}`);
  }
}

/** Last traded price for a single symbol. */
export async function getLastPrice(
  symbol: string,
  category: MarketCategory = "linear",
): Promise<number> {
  const prices = await getLastPrices([symbol], category);
  const price = prices.get(symbol.toUpperCase());
  if (price === undefined) {
    throw new MarketDataError(`No price returned for ${symbol}`);
  }
  return price;
}

/**
 * Last traded prices for many symbols in one request. Bybit's tickers endpoint
 * returns the whole category when no symbol is given, so a single call covers
 * every alert regardless of how many distinct symbols are being watched.
 */
export async function getLastPrices(
  symbols: string[],
  category: MarketCategory = "linear",
): Promise<Map<string, number>> {
  const wanted = new Set(symbols.map((s) => s.toUpperCase()));
  const prices = new Map<string, number>();
  if (wanted.size === 0) return prices;

  try {
    const { data } = await client.get("/v5/market/tickers", {
      // One symbol is cheaper to fetch directly; several are cheaper in bulk.
      params: wanted.size === 1
        ? { category, symbol: [...wanted][0] }
        : { category },
    });

    if (data.retCode !== 0) {
      throw new MarketDataError(`Bybit rejected the ticker request: ${data.retMsg}`, data.retCode);
    }

    for (const ticker of data.result?.list ?? []) {
      if (wanted.has(ticker.symbol)) {
        prices.set(ticker.symbol, Number(ticker.lastPrice));
      }
    }

    return prices;
  } catch (error) {
    if (error instanceof MarketDataError) throw error;
    describeAxiosFailure(error, "Fetching ticker prices");
  }
}

/** Bybit server time, also used as a cheap connectivity probe. */
export async function getServerTime() {
  try {
    const { data } = await client.get("/v5/market/time");
    if (data.retCode !== 0) {
      throw new MarketDataError(`Bybit rejected the time request: ${data.retMsg}`, data.retCode);
    }
    return {
      timeSecond: Number(data.result.timeSecond),
      iso: new Date(Number(data.result.timeSecond) * 1000).toISOString(),
    };
  } catch (error) {
    if (error instanceof MarketDataError) throw error;
    describeAxiosFailure(error, "Fetching server time");
  }
}

/** Simple derived stats so callers don't each reimplement them over candles. */
export function summariseCandles(candles: Candle[]) {
  if (candles.length === 0) return null;

  const closes = candles.map((c) => c.close);
  const first = candles[0];
  const last = candles[candles.length - 1];

  return {
    count: candles.length,
    from: new Date(first.openTime).toISOString(),
    to: new Date(last.openTime).toISOString(),
    open: first.open,
    close: last.close,
    high: Math.max(...candles.map((c) => c.high)),
    low: Math.min(...candles.map((c) => c.low)),
    changePercent: first.open === 0 ? 0 : ((last.close - first.open) / first.open) * 100,
    averageClose: closes.reduce((sum, c) => sum + c, 0) / closes.length,
    totalVolume: candles.reduce((sum, c) => sum + c.volume, 0),
  };
}

export { MarketDataError };
