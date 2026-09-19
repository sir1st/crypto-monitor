import { createHmac } from "node:crypto";
import type { ExchangeCredentials, StandardPosition } from "./types";

/**
 * Bitget Elite Trading (带单) reads.
 *
 * Elite portfolios live in a separate wallet from the plain Unified Account, and
 * Bitget exposes them only through the copy-trading API (`/api/v3/copy/futures/*`)
 * with a dedicated Elite Trading API key. The classic copy-trading endpoints are
 * disabled for Unified Account mode, and ccxt has no bindings for these at all,
 * so requests are signed here by hand.
 *
 * Every function returns `null` on failure: the caller fans out across accounts
 * and a key without copy-trading permission must not fail the aggregate.
 */

const BASE_URL = "https://api.bitget.com";
const SUMMARY_PATH = "/api/v3/copy/futures/position-summary";
const PROFIT_PATH = "/api/v3/copy/futures/profit-summary";

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

interface EliteProfitSummary {
  totalProfit?: string;
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
 * Cumulative realised P&L plus open-position unrealised P&L for the elite
 * portfolio. Bitget's copy-trading API has no time-windowed or per-fill view,
 * so the realised figure is the account's running total, not a weekly one.
 */
export async function getElitePnl(
  credentials: ExchangeCredentials,
): Promise<{ realizedPnl: number; unrealizedPnl: number } | null> {
  const [profit, positions] = await Promise.all([
    signedGet<EliteProfitSummary>(PROFIT_PATH, credentials),
    signedGet<ElitePosition[]>(SUMMARY_PATH, credentials),
  ]);
  if (profit === null) return null;

  const unrealizedPnl = (positions ?? []).reduce(
    (total, p) => total + Number(p.unrealizedPnl ?? "0"),
    0,
  );

  return { realizedPnl: Number(profit.totalProfit ?? "0"), unrealizedPnl };
}
