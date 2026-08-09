import { complete, type Effort } from "./index";
import { summariseCandles } from "../market";
import type { Candle, Strategy } from "@shared/schema";
import type { AccountBalanceReport, TradingReport } from "../trading";

/**
 * Prompts for the analysis endpoints. Each builds a compact digest of real data
 * rather than dumping raw payloads, which keeps token cost predictable and
 * keeps the model's attention on the numbers that matter.
 */

const ANALYST_SYSTEM = `You are a trading data analyst embedded in a monitoring dashboard.

Work only from the figures given to you. Do not invent prices, dates, or trades,
and say so plainly when the data is too thin to support a conclusion.

Be specific and quantitative: cite the actual numbers you are reasoning from.
Lead with what the data shows, then what is worth watching. Keep it under 250
words unless asked otherwise, and use plain prose over bullet-point sprawl.

You are describing what the data shows, not issuing financial advice or
directing trades. Do not tell the user to buy or sell.`;

/** Trims a candle series to a token-reasonable digest for the prompt. */
function digestCandles(candles: Candle[], keep = 40) {
  const recent = candles.slice(-keep);
  return recent
    .map(
      (c) =>
        `${new Date(c.openTime).toISOString()} O:${c.open} H:${c.high} L:${c.low} C:${c.close} V:${c.volume}`,
    )
    .join("\n");
}

export async function analyseMarket(options: {
  symbol: string;
  interval: string;
  candles: Candle[];
  question?: string;
  model?: string;
  effort?: Effort;
}) {
  const { symbol, interval, candles, question, model, effort } = options;
  const summary = summariseCandles(candles);

  if (!summary) {
    throw new Error(`No candle data available for ${symbol}`);
  }

  const prompt = `Symbol: ${symbol}
Interval: ${interval}
Window: ${summary.from} to ${summary.to} (${summary.count} candles)

Open: ${summary.open}
Close: ${summary.close}
High: ${summary.high}
Low: ${summary.low}
Change: ${summary.changePercent.toFixed(2)}%
Average close: ${summary.averageClose.toFixed(2)}
Total volume: ${summary.totalVolume}

Most recent candles (oldest first):
${digestCandles(candles)}

${question ? `The operator asks: ${question}` : "Describe the price action in this window: trend, notable moves, volume behaviour, and the levels that stand out."}`;

  return complete({ prompt, system: ANALYST_SYSTEM, model, effort });
}

export async function analysePerformance(options: {
  reports: TradingReport[];
  balances?: AccountBalanceReport[];
  question?: string;
  model?: string;
  effort?: Effort;
}) {
  const { reports, balances, question, model, effort } = options;

  if (reports.length === 0) {
    throw new Error("No trading reports available to analyse. Configure an account first.");
  }

  const reportLines = reports
    .map(
      (r) =>
        `- ${r.accountName} over ${r.timeframe}: ROI ${r.totalROI}% on margin, P&L $${r.totalPnL}, ` +
        `${r.winCount}W/${r.lossCount}L (win rate ${r.winRate}%), ` +
        `profit/loss ratio ${r.pnlRatio ?? "n/a (no losses)"}, ` +
        `win ROI ${r.winROI}% / loss ROI ${r.lossROI}%`,
    )
    .join("\n");

  const balanceLines = balances?.length
    ? "\n\nEquity and weekly movement:\n" +
      balances
        .map((b) => {
          const topSymbols =
            b.weeklySymbols
              .slice(0, 3)
              .map((s) => `${s.symbol} $${s.totalPnl}`)
              .join(", ") || "none";

          return (
            `- ${b.accountName}: equity $${b.currentEquity}, unrealised $${b.unrealizedPnl}, ` +
            `7d P&L $${b.tradingPnl7d} (${b.growthPercentage7d}%), ` +
            `week-to-date P&L $${b.weeklyPnl} (${b.weeklyGrowthPercentage}%), ` +
            `top symbols this week ${topSymbols}`
          );
        })
        .join("\n")
    : "";

  const prompt = `Realised performance per account. ROI is calculated on margin
committed (entry notional divided by leverage), not on notional size.

${reportLines}${balanceLines}

${question ? `The operator asks: ${question}` : "Compare the accounts. Where is the return actually coming from, what does the win rate paired with the profit factor tell you, and which account's risk profile looks least sustainable?"}`;

  return complete({ prompt, system: ANALYST_SYSTEM, model, effort });
}

export async function reviewStrategy(options: {
  strategy: Strategy;
  candles?: Candle[];
  question?: string;
  model?: string;
  effort?: Effort;
}) {
  const { strategy, candles, question, model, effort } = options;
  const summary = candles ? summariseCandles(candles) : null;

  const marketContext = summary
    ? `\nRecent ${strategy.symbol} price action (${summary.count} candles, ${summary.from} to ${summary.to}):
change ${summary.changePercent.toFixed(2)}%, high ${summary.high}, low ${summary.low}, close ${summary.close}

${digestCandles(candles!)}`
    : "\nNo market data was supplied alongside this strategy.";

  const prompt = `Strategy under review.

Name: ${strategy.name}
Symbol: ${strategy.symbol}
Timeframe: ${strategy.timeframe}
Status: ${strategy.status}
Description: ${strategy.description ?? "(none given)"}
Rules: ${strategy.rules ? JSON.stringify(strategy.rules, null, 2) : "(none defined)"}
${marketContext}

${question ? `The operator asks: ${question}` : "Assess this strategy as specified: what is underdefined or ambiguous, what would break it in the market conditions shown, and what would need to be measured to know whether it works. Be concrete about the gaps — do not assume rules that were not stated."}`;

  return complete({ prompt, system: ANALYST_SYSTEM, model, effort });
}
