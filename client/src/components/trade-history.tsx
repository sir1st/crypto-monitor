import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Account } from "@shared/schema";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertCircle, History, Loader2 } from "lucide-react";

interface TradeHistoryEntry {
  accountName: string;
  exchange: string;
  symbol: string;
  closedPnl: number;
  margin: number;
  roi: number;
  leverage: number;
  closedSize: number;
  avgEntryPrice: number;
  closedAt: string;
}

const TIMEFRAMES = [
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
  { value: 90, label: "90D" },
];

const EXCHANGES = ["all", "bybit", "binance", "okx", "bitget", "gate"];

/** Exchanges whose API exposes no per-fill history to this dashboard. */
const NO_HISTORY_EXCHANGES = ["bitget"];

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
}

function formatSize(value: number) {
  if (!Number.isFinite(value) || value === 0) return "0";
  return value.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function exchangeBadgeStyle(exchange: string) {
  const ex = exchange.toLowerCase();
  return ex === "binance"
    ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
    : ex === "okx"
      ? "bg-white/10 text-white border-white/20"
      : ex === "bitget"
        ? "bg-cyan-500/20 text-cyan-400 border-cyan-500/30"
        : ex === "gate"
          ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
          : "bg-orange-500/20 text-orange-400 border-orange-500/30";
}

export default function TradeHistory() {
  const [timeframe, setTimeframe] = useState(30);
  const [exchange, setExchange] = useState("all");
  const [account, setAccount] = useState("all");
  const [symbolInput, setSymbolInput] = useState("");
  const [symbol, setSymbol] = useState("");

  const { data: accounts = [] } = useQuery<Account[]>({
    queryKey: ["/api/accounts"],
  });

  const url = useMemo(() => {
    const params = new URLSearchParams({ timeframe: String(timeframe), limit: "500" });
    if (exchange !== "all") params.set("exchange", exchange);
    if (account !== "all") params.set("account", account);
    if (symbol) params.set("symbol", symbol);
    return `/api/exchange/history?${params.toString()}`;
  }, [timeframe, exchange, account, symbol]);

  const { data: trades = [], isLoading, error } = useQuery<TradeHistoryEntry[]>({
    queryKey: [url],
  });

  const totals = useMemo(() => {
    const pnl = trades.reduce((sum, trade) => sum + trade.closedPnl, 0);
    const wins = trades.filter((trade) => trade.closedPnl > 0).length;
    const losses = trades.filter((trade) => trade.closedPnl <= 0).length;
    const winRate = trades.length > 0 ? (wins / trades.length) * 100 : 0;
    return { pnl, wins, losses, winRate };
  }, [trades]);

  return (
    <Card className="bg-[#0d2538] border-[#00b4d8]/20">
      <CardHeader>
        <CardTitle className="text-lg font-bold text-white flex items-center">
          <History className="h-5 w-5 text-[#00b4d8] mr-2" />
          Trade History
        </CardTitle>
        <CardDescription className="text-white/70">
          Individual closed trades across every account, newest first. ROI is calculated on
          margin committed, not notional size.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1">
            {TIMEFRAMES.map((option) => (
              <Button
                key={option.value}
                size="sm"
                variant={timeframe === option.value ? "default" : "outline"}
                onClick={() => setTimeframe(option.value)}
                className="text-xs px-3 h-8"
              >
                {option.label}
              </Button>
            ))}
          </div>

          <select
            value={exchange}
            onChange={(event) => setExchange(event.target.value)}
            className="h-8 rounded-md border border-[#00b4d8]/30 bg-[#112240] px-2 text-xs text-white/90"
          >
            {EXCHANGES.map((option) => (
              <option key={option} value={option}>
                {option === "all" ? "All exchanges" : option}
              </option>
            ))}
          </select>

          <select
            value={account}
            onChange={(event) => setAccount(event.target.value)}
            className="h-8 rounded-md border border-[#00b4d8]/30 bg-[#112240] px-2 text-xs text-white/90"
          >
            <option value="all">All accounts</option>
            {accounts.map((option) => (
              <option key={option.name} value={option.name}>
                {option.name}
              </option>
            ))}
          </select>

          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              setSymbol(symbolInput.trim());
            }}
          >
            <Input
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value)}
              placeholder="Filter symbol, e.g. SOL"
              className="h-8 w-44 text-xs"
            />
            <Button type="submit" size="sm" variant="outline" className="h-8 text-xs">
              Search
            </Button>
            {symbol && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 text-xs text-white/60"
                onClick={() => {
                  setSymbolInput("");
                  setSymbol("");
                }}
              >
                Clear
              </Button>
            )}
          </form>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg bg-slate-800/30 p-3 text-center">
            <p className="text-xs text-white/50">Trades</p>
            <p className="text-lg font-bold text-white">{trades.length}</p>
          </div>
          <div className="rounded-lg bg-slate-800/30 p-3 text-center">
            <p className="text-xs text-white/50">Total P&L</p>
            <p
              className={`text-lg font-bold ${totals.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
            >
              {formatCurrency(totals.pnl)}
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/30 p-3 text-center">
            <p className="text-xs text-white/50">Win / Loss</p>
            <p className="text-lg font-bold">
              <span className="text-emerald-400">{totals.wins}W</span>
              <span className="text-white/40"> / </span>
              <span className="text-red-400">{totals.losses}L</span>
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/30 p-3 text-center">
            <p className="text-xs text-white/50">Win Rate</p>
            <p className="text-lg font-bold text-yellow-400">{totals.winRate.toFixed(1)}%</p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-white/60">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading trade history…
          </div>
        ) : error ? (
          <div className="flex items-center justify-center gap-2 py-12 text-red-400">
            <AlertCircle className="h-4 w-4" />
            {(error as Error).message}
          </div>
        ) : trades.length === 0 ? (
          <div className="py-12 text-center text-white/50">
            No closed trades in this window.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#00b4d8]/20 text-left text-white/60">
                  <th className="py-2 pr-4 font-medium">Time</th>
                  <th className="py-2 pr-4 font-medium">Account</th>
                  <th className="py-2 pr-4 font-medium">Symbol</th>
                  <th className="py-2 pr-4 text-right font-medium">Size</th>
                  <th className="py-2 pr-4 text-right font-medium">Avg Price</th>
                  <th className="py-2 pr-4 text-right font-medium">Lev</th>
                  <th className="py-2 pr-4 text-right font-medium">Margin</th>
                  <th className="py-2 pr-4 text-right font-medium">P&L</th>
                  <th className="py-2 text-right font-medium">ROI</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, index) => (
                  <tr
                    key={`${trade.accountName}-${trade.symbol}-${trade.closedAt}-${index}`}
                    className="border-b border-white/5 last:border-0 hover:bg-[#00b4d8]/5"
                  >
                    <td className="py-2 pr-4 whitespace-nowrap text-white/70">
                      {new Date(trade.closedAt).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <span className="text-white/90">{trade.accountName}</span>
                        <Badge
                          variant="outline"
                          className={`text-[10px] uppercase font-mono px-1.5 py-0 ${exchangeBadgeStyle(trade.exchange)}`}
                        >
                          {trade.exchange}
                        </Badge>
                      </div>
                    </td>
                    <td className="py-2 pr-4 font-medium text-white">{trade.symbol}</td>
                    <td className="py-2 pr-4 text-right text-white/70">
                      {formatSize(trade.closedSize)}
                    </td>
                    <td className="py-2 pr-4 text-right text-white/70">
                      {formatSize(trade.avgEntryPrice)}
                    </td>
                    <td className="py-2 pr-4 text-right text-white/70">{trade.leverage}x</td>
                    <td className="py-2 pr-4 text-right text-white/70">
                      {formatCurrency(trade.margin)}
                    </td>
                    <td
                      className={`py-2 pr-4 text-right font-semibold ${trade.closedPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {formatCurrency(trade.closedPnl)}
                    </td>
                    <td
                      className={`py-2 text-right font-semibold ${trade.roi >= 0 ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {trade.roi >= 0 ? "+" : ""}
                      {trade.roi.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-start gap-2 rounded-md border border-[#00b4d8]/20 bg-[#112240] p-3 text-xs text-white/60">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-[#ffc107]" />
          <span>
            {NO_HISTORY_EXCHANGES.join(", ")} elite portfolios do not expose per-fill history, so
            they never appear here. Bybit's API caps a single query at 7 days, so its history is
            limited to about 90 days. Real-time positions are on the Positions tab.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
