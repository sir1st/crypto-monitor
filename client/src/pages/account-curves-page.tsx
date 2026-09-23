import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { useWalletStream } from "@/hooks/use-wallet-stream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { motion } from "framer-motion";
import { Activity, ArrowLeft, Trash2, TrendingDown, TrendingUp, WifiOff } from "lucide-react";

interface CurvePoint {
  t: number;
  equity: number;
  walletBalance: number;
}

interface WalletTick {
  accountName?: string;
  accountId?: number;
  exchange?: string;
  totalEquity?: number | string;
  totalWalletBalance?: number | string;
}

const STORAGE_KEY = "vale.account-curves.v1";
const MAX_POINTS = 2000;

/** Persisted series keyed by `${exchange}:${accountId ?? accountName}`. */
type CurveStore = Record<string, CurvePoint[]>;

function loadStore(): CurveStore {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as CurveStore) : {};
  } catch {
    return {};
  }
}

function saveStore(store: CurveStore) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Quota exceeded — drop the oldest half of each series and retry once.
    const trimmed: CurveStore = {};
    for (const [key, points] of Object.entries(store)) {
      trimmed[key] = points.slice(-Math.floor(MAX_POINTS / 2));
    }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
    } catch {
      // Give up silently; the live curve still works for this session.
    }
  }
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
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

function EquityChart({ points, id }: { points: CurvePoint[]; id: string }) {
  const width = 640;
  const height = 170;
  const pad = 6;

  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(Math.abs(max), 1) * 0.001;
  const rising = values[values.length - 1] >= values[0];
  const color = rising ? "#34d399" : "#f87171";

  const x = (index: number) => pad + (index / (points.length - 1)) * (width - pad * 2);
  const y = (value: number) => pad + (1 - (value - min) / span) * (height - pad * 2);

  const line = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.equity).toFixed(1)}`).join(" ");
  const area = `${line} L${x(points.length - 1).toFixed(1)},${height - pad} L${x(0).toFixed(1)},${height - pad} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`fill-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#fill-${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function AccountCurvesPage() {
  const { isConnected, data } = useWalletStream();
  const [store, setStore] = useState<CurveStore>(() => loadStore());
  const lastTickRef = useRef<number>(0);

  // Append one point per account on each wallet tick.
  useEffect(() => {
    if (!data || data.topic !== "wallet" || !data.data?.length) return;
    if (data.creationTime === lastTickRef.current) return;
    lastTickRef.current = data.creationTime;

    setStore((prev) => {
      const next: CurveStore = { ...prev };
      for (const entry of data.data as WalletTick[]) {
        const key = `${entry.exchange ?? "?"}:${entry.accountId ?? entry.accountName ?? "?"}`;
        const point: CurvePoint = {
          t: data.creationTime,
          equity: Number(entry.totalEquity ?? 0),
          walletBalance: Number(entry.totalWalletBalance ?? 0),
        };
        const series = next[key] ?? [];
        const last = series[series.length - 1];
        if (last && last.t === point.t) continue;
        next[key] = [...series, point].slice(-MAX_POINTS);
      }
      saveStore(next);
      return next;
    });
  }, [data]);

  const clearAll = useCallback(() => {
    setStore({});
    saveStore({});
  }, []);

  const cards = useMemo(() => {
    return Object.entries(store)
      .map(([key, points]) => {
        const [exchange, account] = key.split(":");
        const first = points[0];
        const last = points[points.length - 1];
        const change = last.equity - first.equity;
        const changePct = first.equity !== 0 ? (change / first.equity) * 100 : 0;
        return { key, exchange, account, points, last, change, changePct };
      })
      .sort((a, b) => a.account.localeCompare(b.account));
  }, [store]);

  return (
    <div className="min-h-screen bg-[#0a192f] text-white">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[#00b4d8]/20 bg-[#0a192f] p-2 sm:p-4">
        <h1 className="font-['Orbitron'] text-lg sm:text-xl lg:text-2xl whitespace-nowrap">
          <span className="text-[#ffc107]">Vale</span>{" "}
          <span className="text-[#00b4d8]">Monitor</span>
        </h1>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-xs text-white/60">
            {isConnected ? (
              <>
                <span className="h-2 w-2 rounded-full bg-emerald-400" /> Live
              </>
            ) : (
              <>
                <WifiOff className="h-3.5 w-3.5 text-red-400" /> Disconnected
              </>
            )}
          </span>
          <Button size="sm" variant="outline" onClick={clearAll} className="h-8 text-xs">
            <Trash2 className="mr-1 h-3.5 w-3.5" /> Clear
          </Button>
          <Link href="/">
            <Button size="sm" variant="outline" className="h-8 text-xs">
              <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Positions
            </Button>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-2 py-4 sm:px-4 sm:py-8">
        <div className="mb-4 sm:mb-6">
          <h2 className="font-['Orbitron'] text-xl font-bold sm:text-2xl">
            <span className="text-[#ffc107]">Account</span>{" "}
            <span className="text-[#00b4d8]">Equity</span>{" "}
            <span className="text-white">Curves</span>
          </h2>
          <p className="mt-1 text-sm text-white/70 sm:text-base">
            Live equity sampled from the wallet stream every 5 seconds. Points accumulate while
            the page is open and are kept in this browser.
          </p>
        </div>

        {cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-24 text-white/50">
            <Activity className="h-6 w-6 animate-pulse text-[#00b4d8]" />
            Waiting for the first wallet sample…
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {cards.map((card, index) => {
              const rising = card.change >= 0;
              const Icon = rising ? TrendingUp : TrendingDown;
              const times = card.points.map((point) => point.t);
              return (
                <motion.div
                  key={card.key}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(index * 0.03, 0.3) }}
                >
                  <Card className="bg-gradient-to-br from-slate-900/90 to-slate-800/60 border-slate-700/50">
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <CardTitle className="flex items-center gap-2 text-base text-white">
                          {card.account.toUpperCase()}
                          <Badge
                            variant="outline"
                            className={`px-1.5 py-0 font-mono text-[10px] uppercase ${exchangeBadgeStyle(card.exchange)}`}
                          >
                            {card.exchange}
                          </Badge>
                        </CardTitle>
                        <div className="text-right">
                          <p className="text-lg font-bold text-emerald-400">
                            {formatCurrency(card.last.equity)}
                          </p>
                          <p
                            className={`flex items-center justify-end gap-1 text-xs font-semibold ${
                              rising ? "text-emerald-400" : "text-red-400"
                            }`}
                          >
                            <Icon className="h-3.5 w-3.5" />
                            {rising ? "+" : ""}
                            {formatCurrency(card.change)} ({rising ? "+" : ""}
                            {card.changePct.toFixed(2)}%)
                          </p>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      {card.points.length < 2 ? (
                        <div className="flex h-40 items-center justify-center text-sm text-white/40">
                          Collecting samples…
                        </div>
                      ) : (
                        <EquityChart points={card.points} id={String(card.key).replace(/[^a-z0-9]/gi, "")} />
                      )}
                      <div className="mt-2 flex items-center justify-between text-xs text-white/50">
                        <span>
                          {new Date(times[0]).toLocaleString("en-US", {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                          {" → "}
                          {new Date(times[times.length - 1]).toLocaleString("en-US", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                        <span>
                          {card.points.length} samples · wallet{" "}
                          {formatCurrency(card.last.walletBalance)}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
