import { createHmac } from "node:crypto";
import type {
  CoinBalance,
  ExchangeCredentials,
  StandardClosedTrade,
  StandardPosition,
  StandardWallet,
} from "./types";

/**
 * Bitget Elite Trading (带单) reads.
 *
 * Elite portfolios live in a separate wallet from the plain Unified Account, and
 * Bitget exposes their copy-trading side through `/api/v3/copy/futures/*` with a
 * dedicated Elite Trading API key. The classic copy-trading endpoints are
 * disabled for Unified Account mode, and ccxt has no bindings for any of it, so
 * requests are signed here by hand.
 *
 * Every function returns `null` on failure: the caller fans out across accounts
 * and a key without copy-trading permission must not fail the aggregate.
 */

const BASE_URL = "https://api.bitget.com";
const ASSETS_PATH = "/api/v3/account/assets";
const SUMMARY_PATH = "/api/v3/copy/futures/position-summary";
const HISTORY_POSITIONS_PATH = "/api/v3/position/history-position";
/** Bybit-style page caps: the API pages at 100 rows, so bound the walk. */
const PAGE_LIMIT = 100;
const MAX_HISTORY_PAGES = 8;

interface ElitePosition {
  symbol?: string;
  holdSide?: string;
  holdSize?: string;
  avgPrice?: string;
  markPrice?: string;
  leverage?: string;
  liqPrice?: string;
  unrealizedPnl?: string;
  realizedPnl?: string;
  positionValue?: string;
}

interface EliteClosedPosition {
  symbol?: string;
  openPriceAvg?: string;
  openTotalPos?: string;
  closeTotalPos?: string;
  cumRealisedPnl?: string;
  createdTime?: string;
  updatedTime?: string;
}

interface EliteAccountAssets {
  usdtEquity?: string;
  usdtUnrealisedPnl?: string;
  imr?: string;
  mmr?: string;
  assets?: Array<{ coin?: string; equity?: string; balance?: string; usdValue?: string }>;
}

async function signedGet<T>(
  path: string,
  credentials: ExchangeCredentials,
): Promise<T | null> {
  try {
    const timestamp = Date.now().toString();
    const signature = createHmac("sha256", credentials.apiSecret)
      .update(timestamp + "GET" + path)
      .digest("base64");

    const response = await fetch(`${BASE_URL}${path}`, {
      headers: {
        "ACCESS-KEY": credentials.apiKey,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": credentials.passphrase ?? "",
        "Content-Type": "application/json",
        locale: "en-US",
      },
    });

    const body = (await response.json()) as { code?: string; msg?: string; data?: T };
    if (body.code !== "00000") {
      console.error(`Bitget elite ${path} rejected: ${body.msg ?? body.code}`);
      return null;
    }
    return body.data ?? null;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Bitget elite ${path} failed: ${message}`);
    return null;
  }
}

/** Open lead-trading positions, already carrying a clean `SOLUSDT`-style symbol. */
export async function getElitePositions(
  credentials: ExchangeCredentials,
  accountName: string,
  accountId?: number,
): Promise<StandardPosition[] | null> {
  const raw = await signedGet<ElitePosition[]>(SUMMARY_PATH, credentials);
  if (raw === null) return null;

  return raw.map((p) => ({
    exchange: "bitget",
    accountName,
    accountId,
    symbol: p.symbol ?? "UNKNOWN",
    side: p.holdSide === "short" ? "Sell" : "Buy",
    size: p.holdSize ?? "0",
    leverage: p.leverage ?? "1",
    avgPrice: p.avgPrice ?? "0",
    markPrice: p.markPrice ?? "0",
    unrealisedPnl: p.unrealizedPnl ?? "0",
    positionValue: p.positionValue ?? "0",
    liqPrice: p.liqPrice ?? "0",
    takeProfit: "",
    stopLoss: "",
    positionStatus: "Normal",
    cumRealisedPnl: p.realizedPnl ?? "0",
    updatedTime: String(Date.now()),
  }));
}

/**
 * Unified-account wallet, including the margin metrics (`imr`/`mmr`) that ccxt
 * discards when it parses the UTA balance response.
 */
export async function getBitgetWallet(
  credentials: ExchangeCredentials,
  accountName: string,
  accountId?: number,
): Promise<StandardWallet | null> {
  const data = await signedGet<EliteAccountAssets>(ASSETS_PATH, credentials);
  if (data === null) return null;

  const usdt = data.assets?.find((asset) => asset.coin === "USDT");
  const coin: CoinBalance[] = (data.assets ?? [])
    .map((asset) => ({
      coin: asset.coin ?? "UNKNOWN",
      walletBalance: Number(asset.balance ?? asset.equity ?? "0"),
      usdValue: Number(asset.usdValue ?? "0"),
    }))
    .filter((entry) => entry.usdValue > 0.01 || entry.walletBalance > 0.001);

  return {
    exchange: "bitget",
    accountName,
    accountId,
    accountType: "UNIFIED",
    totalEquity: Number(usdt?.equity ?? data.usdtEquity ?? "0"),
    totalWalletBalance: Number(usdt?.balance ?? "0"),
    totalPerpUPL: Number(data.usdtUnrealisedPnl ?? "0"),
    totalInitialMargin: Number(data.imr ?? "0"),
    totalMaintenanceMargin: Number(data.mmr ?? "0"),
    coin,
  };
}

/**
 * Closed positions from the Unified Account, cursor-paginated. Bitget exposes no
 * per-trade leverage here, so `leverage` is left at "1" and ROI falls back to the
 * position notional rather than committed margin.
 */
export async function getEliteClosedTrades(
  credentials: ExchangeCredentials,
  options: { startTime?: number; endTime?: number; limit?: number } = {},
): Promise<StandardClosedTrade[] | null> {
  const { startTime, endTime, limit = 200 } = options;
  const trades: StandardClosedTrade[] = [];
  let cursor: string | undefined;
  let pages = 0;

  do {
    const query = new URLSearchParams({
      category: "USDT-FUTURES",
      limit: String(Math.min(limit - trades.length, PAGE_LIMIT)),
    });
    // Bitget rejects a startTime without an endTime.
    if (startTime) {
      query.set("startTime", String(startTime));
      query.set("endTime", String(endTime ?? Date.now()));
    }
    if (cursor) query.set("cursor", cursor);

    const data = await signedGet<{ list?: EliteClosedPosition[]; cursor?: string }>(
      `${HISTORY_POSITIONS_PATH}?${query.toString()}`,
      credentials,
    );
    if (data === null) return pages === 0 ? null : trades;

    for (const position of data.list ?? []) {
      const notional = Number(position.openTotalPos ?? "0") * Number(position.openPriceAvg ?? "0");
      trades.push({
        symbol: position.symbol ?? "UNKNOWN",
        closedPnl: String(position.cumRealisedPnl ?? "0"),
        cumEntryValue: String(notional),
        leverage: "1",
        closedSize: String(position.closeTotalPos ?? "0"),
        avgEntryPrice: String(position.openPriceAvg ?? "0"),
        createdTime: String(position.updatedTime ?? position.createdTime ?? Date.now()),
      });
    }

    cursor = data.cursor || undefined;
    pages += 1;
  } while (cursor && trades.length < limit && pages < MAX_HISTORY_PAGES);

  return trades.slice(0, limit);
}
