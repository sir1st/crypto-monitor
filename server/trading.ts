import { storage } from "./storage";
import {
  getExchangePositions,
  getExchangeWalletBalance,
  getExchangeClosedPnL,
  getExchangePnlSnapshot,
  preloadExchangeClient,
} from "./exchanges/manager";
import type { ExchangeCredentials, StandardPosition } from "./exchanges/types";
import type { Account } from "@shared/schema";

/**
 * Multi-account analytics over multi-exchange data (Bybit, Binance, OKX, Bitget, Gate).
 *
 * Two conventions run through everything here:
 *
 *  - **ROI is margin-based, not notional.** A trade's committed capital is
 *    `cumEntryValue / leverage`, so a 10x position reports the return on the
 *    margin actually put up rather than on the position size.
 *  - **Weeks run Monday 00:00:00 UTC to Sunday 23:59:59.999 UTC**, independent
 *    of the server's local timezone.
 *
 * Ratios are `null` rather than `Infinity` when there are no losses to divide
 * by — `JSON.stringify(Infinity)` is `null` anyway, so this makes the wire
 * format honest instead of accidental.
 */

const MAX_TRADES_PER_QUERY = 1000;
/** Guards against absurd ROI from malformed or dust-sized fills. */
const ROI_CAP_PERCENT = 1000;

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function ratio(winPnl: number, lossPnl: number): number | null {
  return lossPnl !== 0 ? round2(Math.abs(winPnl / lossPnl)) : null;
}

function credentialsFor(account: Account): ExchangeCredentials {
  return {
    apiKey: account.apiKey,
    apiSecret: account.apiSecret,
    passphrase: account.passphrase,
  };
}

export function weekBoundaries(reference = new Date()) {
  const dayOfWeek = reference.getUTCDay(); // 0 = Sunday
  const daysFromMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;

  const start = new Date(
    Date.UTC(reference.getUTCFullYear(), reference.getUTCMonth(), reference.getUTCDate()),
  );
  start.setUTCDate(start.getUTCDate() - daysFromMonday);

  const end = new Date(start);
  end.setUTCDate(start.getUTCDate() + 6);
  end.setUTCHours(23, 59, 59, 999);

  return { start, end };
}

interface ClosedTrade {
  symbol?: string;
  closedPnl?: string;
  cumEntryValue?: string;
  leverage?: string;
  closedSize?: string;
  avgEntryPrice?: string;
  createdTime?: string;
}

/** Capital actually committed to a trade, used as the ROI denominator. */
function marginOf(trade: ClosedTrade): number {
  const leverage = Math.max(Number(trade.leverage ?? "1") || 1, 1);
  const notional = Number(trade.cumEntryValue ?? "0");

  if (notional > 0) return notional / leverage;

  // Older fills sometimes omit cumEntryValue; reconstruct from size and price.
  const size = Number(trade.closedSize ?? "0");
  const entry = Number(trade.avgEntryPrice ?? "0");
  return size > 0 && entry > 0 ? (size * entry) / leverage : 0;
}

// ---------------------------------------------------------------------------
// Positions and balances
// ---------------------------------------------------------------------------

/**
 * Positions across every configured account from all supported exchanges.
 * Falls back to environment credentials if no accounts configured.
 */
export async function aggregatePositions(_category: "linear" | "inverse" = "linear"): Promise<StandardPosition[]> {
  const accounts = await storage.getTradableAccounts();
  const positions: StandardPosition[] = [];

  for (const account of accounts) {
    const list = await getExchangePositions(
      account.exchange,
      credentialsFor(account),
      account.name,
      account.id,
    );
    positions.push(...list);
  }

  // Fallback to Bybit environment credentials if no DB accounts
  if (accounts.length === 0 && process.env.BYBIT_API_KEY && process.env.BYBIT_API_SECRET) {
    const list = await getExchangePositions(
      "bybit",
      {
        apiKey: process.env.BYBIT_API_KEY,
        apiSecret: process.env.BYBIT_API_SECRET,
      },
      "Environment",
    );
    positions.push(...list);
  }

  return positions;
}

export async function aggregateWalletBalances() {
  const accounts = await storage.getTradableAccounts();
  const balances: Array<Record<string, unknown>> = [];

  for (const account of accounts) {
    const wallet = await getExchangeWalletBalance(
      account.exchange,
      credentialsFor(account),
      account.name,
      account.id,
    );
    if (wallet) {
      balances.push({
        ...wallet,
        // Compatibility properties for UI components expecting Bybit style fields
        totalAvailableBalance: String(wallet.totalWalletBalance),
        accountType: wallet.accountType ?? "UNIFIED",
      });
    }
  }

  // Fallback to Bybit environment credentials if no DB accounts
  if (accounts.length === 0 && process.env.BYBIT_API_KEY && process.env.BYBIT_API_SECRET) {
    const wallet = await getExchangeWalletBalance(
      "bybit",
      {
        apiKey: process.env.BYBIT_API_KEY,
        apiSecret: process.env.BYBIT_API_SECRET,
      },
      "Environment",
    );
    if (wallet) {
      balances.push({
        ...wallet,
        totalAvailableBalance: String(wallet.totalWalletBalance),
        accountType: "UNIFIED",
      });
    }
  }

  return balances;
}

// ---------------------------------------------------------------------------
// Trading reports
// ---------------------------------------------------------------------------

export interface TradingReport {
  accountName: string;
  exchange?: string;
  timeframe: string;
  totalROI: number;
  totalPnL: number;
  winROI: number;
  winPnL: number;
  lossROI: number;
  lossPnL: number;
  winCount: number;
  lossCount: number;
  winRate: number;
  /** Gross profit over gross loss. `null` when there were no losses. */
  pnlRatio: number | null;
}

export async function buildTradingReports(timeframeDays = 7): Promise<TradingReport[]> {
  const accounts = await storage.getTradableAccounts();
  if (accounts.length === 0) return [];

  const cutoff = new Date(Date.now() - timeframeDays * 24 * 60 * 60 * 1000);
  const label = `${timeframeDays} day${timeframeDays === 1 ? "" : "s"}`;
  const reports: TradingReport[] = [];

  for (const account of accounts) {
    const trades = await getExchangeClosedPnL(account.exchange, credentialsFor(account), {
      limit: MAX_TRADES_PER_QUERY,
      startTime: cutoff.getTime(),
    });

    let totalPnL = 0;
    let totalMargin = 0;
    let winPnL = 0;
    let winMargin = 0;
    let lossPnL = 0;
    let lossMargin = 0;
    let winCount = 0;
    let lossCount = 0;

    for (const trade of trades as ClosedTrade[]) {
      if (Number(trade.createdTime ?? 0) < cutoff.getTime()) continue;

      const pnl = Number(trade.closedPnl ?? "0");
      const margin = marginOf(trade);

      totalPnL += pnl;
      totalMargin += margin;

      if (pnl > 0) {
        winPnL += pnl;
        winMargin += margin;
        winCount += 1;
      } else {
        lossPnL += pnl;
        lossMargin += margin;
        lossCount += 1;
      }
    }

    const tradeCount = winCount + lossCount;
    reports.push({
      accountName: account.name,
      exchange: account.exchange,
      timeframe: label,
      totalROI: totalMargin > 0 ? round2((totalPnL / totalMargin) * 100) : 0,
      totalPnL: round2(totalPnL),
      winROI: winMargin > 0 ? round2((winPnL / winMargin) * 100) : 0,
      winPnL: round2(winPnL),
      lossROI: lossMargin > 0 ? round2((lossPnL / lossMargin) * 100) : 0,
      lossPnL: round2(lossPnL),
      winCount,
      lossCount,
      winRate: tradeCount > 0 ? round2((winCount / tradeCount) * 100) : 0,
      pnlRatio: ratio(winPnL, lossPnL),
    });
  }

  return reports;
}

// ---------------------------------------------------------------------------
// Trade history
// ---------------------------------------------------------------------------

export interface TradeHistoryEntry {
  accountName: string;
  exchange: string;
  symbol: string;
  closedPnl: number;
  margin: number;
  /** Margin-based return on the trade, in percent. */
  roi: number;
  leverage: number;
  closedSize: number;
  avgEntryPrice: number;
  closedAt: string;
}

export interface TradeHistoryOptions {
  timeframeDays?: number;
  exchange?: string;
  account?: string;
  symbol?: string;
  limit?: number;
}

/** Exchanges whose API exposes no per-fill history to this app. */
export const HISTORY_UNAVAILABLE_EXCHANGES = ["bitget"] as const;

/**
 * Individual closed trades across every configured account, newest first.
 * `buildTradingReports` aggregates the same source into per-account totals;
 * this returns the raw rows behind those totals.
 */
export async function buildTradeHistory(
  options: TradeHistoryOptions = {},
): Promise<TradeHistoryEntry[]> {
  const { timeframeDays = 30, exchange, account, symbol, limit = 200 } = options;
  const now = Date.now();
  const cutoff = now - timeframeDays * 24 * 60 * 60 * 1000;
  const accounts = (await storage.getTradableAccounts(exchange)).filter(
    (candidate) => !account || candidate.name === account,
  );

  // Accounts are independent (distinct API keys), so fetch them concurrently.
  const perAccount = await Promise.all(
    accounts.map(async (account) => {
      const trades = await getExchangeClosedPnL(account.exchange, credentialsFor(account), {
        limit: MAX_TRADES_PER_QUERY,
        startTime: cutoff,
        endTime: now,
      });

      const rows: TradeHistoryEntry[] = [];
      for (const trade of trades as ClosedTrade[]) {
        const closedAt = Number(trade.createdTime ?? 0);
        if (closedAt < cutoff) continue;

        const tradeSymbol = trade.symbol ?? "UNKNOWN";
        if (symbol && !tradeSymbol.toUpperCase().includes(symbol.toUpperCase())) continue;

        const pnl = Number(trade.closedPnl ?? "0");
        const margin = marginOf(trade);

        rows.push({
          accountName: account.name,
          exchange: account.exchange,
          symbol: tradeSymbol,
          closedPnl: round2(pnl),
          margin: round2(margin),
          roi: margin > 0 ? round2((pnl / margin) * 100) : 0,
          leverage: Math.max(Number(trade.leverage ?? "1") || 1, 1),
          closedSize: Number(trade.closedSize ?? "0"),
          avgEntryPrice: Number(trade.avgEntryPrice ?? "0"),
          closedAt: new Date(closedAt).toISOString(),
        });
      }
      return rows;
    }),
  );

  return perAccount
    .flat()
    .sort((a, b) => Date.parse(b.closedAt) - Date.parse(a.closedAt))
    .slice(0, limit);
}

// ---------------------------------------------------------------------------
// Weekly highlights
// ---------------------------------------------------------------------------

export interface TrophyStats {
  topWinPercentage: number;
  topWinLeverage: string;
  topValueWin: number;
  totalWeeklyTrades: number;
  weekStart: string;
  weekEnd: string;
}

/** Best trade of the current week, by ROI and by absolute profit. */
export async function buildTrophyStats(): Promise<TrophyStats> {
  const { start, end } = weekBoundaries();
  const accounts = await storage.getTradableAccounts();

  let topWinPercentage = 0;
  let topWinLeverage = "n/a";
  let topValueWin = 0;
  let totalWeeklyTrades = 0;

  for (const account of accounts) {
    const trades = await getExchangeClosedPnL(account.exchange, credentialsFor(account), {
      limit: MAX_TRADES_PER_QUERY,
      startTime: start.getTime(),
    });

    for (const trade of trades as ClosedTrade[]) {
      const openedAt = Number(trade.createdTime ?? 0);
      if (openedAt < start.getTime() || openedAt > end.getTime()) continue;

      totalWeeklyTrades += 1;

      const pnl = Number(trade.closedPnl ?? "0");
      if (pnl > topValueWin) topValueWin = pnl;
      if (pnl <= 0) continue;

      const margin = marginOf(trade);
      if (margin <= 0) continue;

      const roi = (pnl / margin) * 100;
      if (roi > topWinPercentage && roi <= ROI_CAP_PERCENT) {
        topWinPercentage = roi;
        topWinLeverage = trade.leverage ?? "n/a";
      }
    }
  }

  return {
    topWinPercentage: round2(topWinPercentage),
    topWinLeverage,
    topValueWin: round2(topValueWin),
    totalWeeklyTrades,
    weekStart: start.toISOString(),
    weekEnd: end.toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Per-account balance report
// ---------------------------------------------------------------------------

export interface SymbolBreakdown {
  symbol: string;
  totalPnl: number;
  winPnl: number;
  lossPnl: number;
  winCount: number;
  lossCount: number;
  totalTrades: number;
  winRate: number;
  pnlRatio: number | null;
}

interface PeriodTotals {
  pnl: number;
  winCount: number;
  lossCount: number;
  winPnl: number;
  lossPnl: number;
  winRate: number;
  pnlRatio: number | null;
  symbols: SymbolBreakdown[];
}

function summarisePeriod(trades: ClosedTrade[]): PeriodTotals {
  const bySymbol = new Map<
    string,
    { winPnl: number; lossPnl: number; wins: number; losses: number }
  >();

  let pnl = 0;
  let winPnl = 0;
  let lossPnl = 0;
  let winCount = 0;
  let lossCount = 0;

  for (const trade of trades) {
    const value = Number(trade.closedPnl ?? "0");
    const symbol = trade.symbol ?? "UNKNOWN";

    pnl += value;

    const bucket = bySymbol.get(symbol) ?? { winPnl: 0, lossPnl: 0, wins: 0, losses: 0 };
    if (value > 0) {
      winPnl += value;
      winCount += 1;
      bucket.winPnl += value;
      bucket.wins += 1;
    } else {
      lossPnl += value;
      lossCount += 1;
      bucket.lossPnl += value;
      bucket.losses += 1;
    }
    bySymbol.set(symbol, bucket);
  }

  const total = winCount + lossCount;

  return {
    pnl: round2(pnl),
    winCount,
    lossCount,
    winPnl: round2(winPnl),
    lossPnl: round2(lossPnl),
    winRate: total > 0 ? round2((winCount / total) * 100) : 0,
    pnlRatio: ratio(winPnl, lossPnl),
    symbols: [...bySymbol.entries()]
      .map(([symbol, b]) => {
        const trades = b.wins + b.losses;
        return {
          symbol,
          totalPnl: round2(b.winPnl + b.lossPnl),
          winPnl: round2(b.winPnl),
          lossPnl: round2(b.lossPnl),
          winCount: b.wins,
          lossCount: b.losses,
          totalTrades: trades,
          winRate: trades > 0 ? round2((b.wins / trades) * 100) : 0,
          pnlRatio: ratio(b.winPnl, b.lossPnl),
        };
      })
      .sort((a, b) => b.totalPnl - a.totalPnl),
  };
}

export interface AccountBalanceReport {
  accountName: string;
  exchange?: string;
  currentEquity: number;
  walletBalance: number;
  unrealizedPnl: number;
  balance7DaysAgo: number;
  balanceWeekStart: number;

  tradingPnl7d: number;
  growthPercentage7d: number;
  winCount7d: number;
  lossCount7d: number;
  winRate7d: number;
  pnlRatio7d: number | null;
  winPnl7d: number;
  lossPnl7d: number;

  weeklyPnl: number;
  weeklyGrowthPercentage: number;
  weeklyWinCount: number;
  weeklyLossCount: number;
  weeklyWinRate: number;
  weeklyPnlRatio: number | null;
  weeklyWinPnl: number;
  weeklyLossPnl: number;
  weekStart: string;
  daysTrading: number;

  positionSizes: Record<string, number>;
  symbols7d: SymbolBreakdown[];
  weeklySymbols: SymbolBreakdown[];
  coinBreakdown: Array<{ coin: string; walletBalance: number; usdValue: number }>;
}

/**
 * Equity, derived historical balances, and performance for the last 7 days and
 * the current week across all configured exchanges.
 */
export async function buildAccountBalanceReports(): Promise<AccountBalanceReport[]> {
  const accounts = await storage.getTradableAccounts();
  const { start: weekStart } = weekBoundaries();
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);

  // Warm ccxt market caches one at a time: Bitget 429s on concurrent public
  // calls, which would otherwise drop accounts from the fan-out below.
  for (const account of accounts) {
    await preloadExchangeClient(account.exchange, credentialsFor(account));
  }

  // Accounts carry independent credentials, so a slow or failing one must not
  // serialise the rest.
  const reports = await Promise.all(
    accounts.map((account) => buildAccountBalanceReport(account, weekStart, sevenDaysAgo)),
  );

  return reports.filter((report): report is AccountBalanceReport => report !== null);
}

async function buildAccountBalanceReport(
  account: Account,
  weekStart: Date,
  sevenDaysAgo: Date,
): Promise<AccountBalanceReport | null> {
  const credentials = credentialsFor(account);

  const wallet = await getExchangeWalletBalance(
    account.exchange,
    credentials,
    account.name,
    account.id,
  );
  if (!wallet) return null;

  const pnlSnapshot = await getExchangePnlSnapshot(account.exchange, credentials);

  const currentEquity = wallet.totalEquity;
  const walletBalance = wallet.totalWalletBalance;
  const unrealizedPnl = pnlSnapshot?.unrealizedPnl ?? wallet.totalPerpUPL;

  const [sevenDayTrades, weeklyTrades] = await Promise.all([
    getExchangeClosedPnL(account.exchange, credentials, {
      limit: MAX_TRADES_PER_QUERY,
      startTime: sevenDaysAgo.getTime(),
    }),
    getExchangeClosedPnL(account.exchange, credentials, {
      limit: MAX_TRADES_PER_QUERY,
      startTime: weekStart.getTime(),
    }),
  ]);

  const last7Days = summarisePeriod(sevenDayTrades as ClosedTrade[]);
  const thisWeek = summarisePeriod(weeklyTrades as ClosedTrade[]);
  if (pnlSnapshot) {
    // Bitget elite portfolios report a single running realised P&L total.
    last7Days.pnl = round2(pnlSnapshot.realizedPnl);
    thisWeek.pnl = round2(pnlSnapshot.realizedPnl);
  }

  const balance7DaysAgo = walletBalance - last7Days.pnl;
  const balanceWeekStart = currentEquity - thisWeek.pnl;

  return {
    accountName: account.name,
    exchange: account.exchange,
    currentEquity: round2(currentEquity),
    walletBalance: round2(walletBalance),
    unrealizedPnl: round2(unrealizedPnl),
    balance7DaysAgo: round2(balance7DaysAgo),
    balanceWeekStart: round2(balanceWeekStart),

    tradingPnl7d: last7Days.pnl,
    growthPercentage7d:
      balance7DaysAgo !== 0 ? round2((last7Days.pnl / balance7DaysAgo) * 100) : 0,
    winCount7d: last7Days.winCount,
    lossCount7d: last7Days.lossCount,
    winRate7d: last7Days.winRate,
    pnlRatio7d: last7Days.pnlRatio,
    winPnl7d: last7Days.winPnl,
    lossPnl7d: last7Days.lossPnl,

    weeklyPnl: thisWeek.pnl,
    weeklyGrowthPercentage:
      balanceWeekStart !== 0 ? round2((thisWeek.pnl / balanceWeekStart) * 100) : 0,
    weeklyWinCount: thisWeek.winCount,
    weeklyLossCount: thisWeek.lossCount,
    weeklyWinRate: thisWeek.winRate,
    weeklyPnlRatio: thisWeek.pnlRatio,
    weeklyWinPnl: thisWeek.winPnl,
    weeklyLossPnl: thisWeek.lossPnl,
    weekStart: weekStart.toISOString(),
    daysTrading: Math.floor((Date.now() - weekStart.getTime()) / (24 * 60 * 60 * 1000)) + 1,

    positionSizes: {
      "1%": round2(currentEquity * 0.01),
      "2%": round2(currentEquity * 0.02),
      "3%": round2(currentEquity * 0.03),
      "4%": round2(currentEquity * 0.04),
      "5%": round2(currentEquity * 0.05),
    },
    symbols7d: last7Days.symbols,
    weeklySymbols: thisWeek.symbols,
    coinBreakdown: wallet.coin
      .filter((c) => c.usdValue > 1 || c.walletBalance > 0.001)
      .map((c) => ({
        coin: c.coin,
        walletBalance: round2(c.walletBalance),
        usdValue: round2(c.usdValue),
      }))
      .sort((a, b) => b.usdValue - a.usdValue),
  };
}
