import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { useWalletStream } from "@/hooks/use-wallet-stream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { motion } from "framer-motion";
import { Activity, ArrowLeft, ShieldAlert, ShieldCheck, Trash2, WifiOff } from "lucide-react";

interface CurvePoint {
  t: number;
  equity: number;
  walletBalance: number;
  initialMargin: number;
  maintenanceMargin: number;
}

interface CurveSeries {
  name: string;
  exchange: string;
  points: CurvePoint[];
}

interface WalletTick {
  accountName?: string;
  accountId?: number;
  exchange?: string;
  totalEquity?: number | string;
  totalWalletBalance?: number | string;
  totalInitialMargin?: number | string;
  totalMaintenanceMargin?: number | string;
}

const STORAGE_KEY = "vale.account-curves.v2";
const MAX_POINTS = 2000;
const WATCH_RATIO = 0.6;
const DANGER_RATIO = 0.8;

type CurveStore = Record<string, CurveSeries>;

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
    const trimmed: CurveStore = {};
    for (const [key, series] of Object.entries(store)) {
      trimmed[key] = { ...series, points: series.points.slice(-Math.floor(MAX_POINTS / 2)) };
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

function formatRatio(value: number) {
  return `${(value * 100).toFixed(1)}%`;
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

function riskOf(ratio: number) {
  if (ratio >= DANGER_RATIO) return { label: "Danger", cls: "bg-red-500/20 text-red-400 border-red-500/40" };
  if (ratio >= WATCH_RATIO) return { label: "Watch", cls: "bg-amber-500/20 text-amber-400 border-amber-500/40" };
  return { label: "Safe", cls: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40" };
}

/** Equity + maintenance margin on the left axis, margin ratio (%) on the right. */
function MarginChart({ points, id }: { points: CurvePoint[]; id: string }) {
  const width = 640;
  const height = 190;
  const pad = 8;

  const usdtValues = points.flatMap((point) => [
    point.equity,
    point.initialMargin,
    point.maintenanceMargin,
  ]);
  const usdtMin = Math.min(...usdtValues);
  const usdtMax = Math.max(...usdtValues);
  const span = usdtMax - usdtMin || Math.max(Math.abs(usdtMax), 1) * 0.001;
  const rising = points[points.length - 1].equity >= points[0].equity;
  const equityColor = rising ? "#34d399" : "#f87171";

  const x = (index: number) => pad + (index / (points.length - 1)) * (width - pad * 2);
  const yUsdt = (value: number) => pad + (1 - (value - usdtMin) / span) * (height - pad * 2);
  const yRatio = (ratio: number) => pad + (1 - Math.min(Math.max(ratio, 0), 1)) * (height - pad * 2);

  const ratioAt = (point: CurvePoint) =>
    point.equity > 0 ? point.maintenanceMargin / point.equity : 0;

  const line = (getY: (point: CurvePoint) => number) =>
    points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${getY(point).toFixed(1)}`).join(" ");

  const equityLine = line((point) => yUsdt(point.equity));
  const mmLine = line((point) => yUsdt(point.maintenanceMargin));
  const imLine = line((point) => yUsdt(point.initialMargin));
  const ratioLine = line((point) => yRatio(ratioAt(point)));

  const bufferArea = `${equityLine} ${points
    .map((point, index) => `L${x(points.length - 1 - index).toFixed(1)},${yUsdt(points[points.length - 1 - index].maintenanceMargin).toFixed(1)}`)
    .join(" ")} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`buffer-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={equityColor} stopOpacity="0.28" />
          <stop offset="100%" stopColor={equityColor} stopOpacity="0.04" />
        </linearGradient>
      </defs>

      {/* liquidation thresholds on the ratio axis */}
      <line x1={pad} x2={width - pad} y1={yRatio(DANGER_RATIO)} y2={yRatio(DANGER_RATIO)} stroke="#f87171" strokeWidth="1" strokeDasharray="4 4" opacity="0.5" />
      <line x1={pad} x2={width - pad} y1={yRatio(WATCH_RATIO)} y2={yRatio(WATCH_RATIO)} stroke="#fbbf24" strokeWidth="1" strokeDasharray="4 4" opacity="0.4" />

      {/* buffer between equity and maintenance margin */}
      <path d={bufferArea} fill={`url(#buffer-${id})`} />

      <path d={imLine} fill="none" stroke="#ffffff" strokeOpacity="0.25" strokeWidth="1" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
      <path d={mmLine} fill="none" stroke="#f87171" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      <path d={ratioLine} fill="none" stroke="#fbbf24" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      <path d={equityLine} fill="none" stroke={equityColor} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function AccountCurvesPage() {
  const { isConnected, data } = useWalletStream();
  const [store, setStore] = useState<CurveStore>(() => loadStore());
  const lastTickRef = useRef<number>(0);

  useEffect(() => {
    if (!data || data.topic !== "wallet" || !data.data?.length) return;
    if (data.creationTime === lastTickRef.current) return;
    lastTickRef.current = data.creationTime;

    setStore((prev) => {
      const next: CurveStore = { ...prev };
      for (const entry of data.data as WalletTick[]) {
        const name = entry.accountName ?? "Account";
        const exchange = entry.exchange ?? "?";
        const key = `${exchange}:${entry.accountId ?? name}`;
        const point: CurvePoint = {
          t: data.creationTime,
          equity: Number(entry.totalEquity ?? 0),
          walletBalance: Number(entry.totalWalletBalance ?? 0),
          initialMargin: Number(entry.totalInitialMargin ?? 0),
          maintenanceMargin: Number(entry.totalMaintenanceMargin ?? 0),
        };
        const series = next[key] ?? { name, exchange, points: [] };
        const last = series.points[series.points.length - 1];
        if (last && last.t === point.t) continue;
        next[key] = { ...series, name, exchange, points: [...series.points, point].slice(-MAX_POINTS) };
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
      .map(([key, series]) => {
        const points = series.points;
        const first = points[0];
        const last = points[points.length - 1];
        const ratio = last.equity > 0 ? last.maintenanceMargin / last.equity : 0;
        const change = last.equity - first.equity;
        const changePct = first.equity !== 0 ? (change / first.equity) * 100 : 0;
        return {
          key,
          series,
          points,
          last,
          ratio,
          buffer: last.equity - last.maintenanceMargin,
          change,
          changePct,
          risk: riskOf(ratio),
        };
      })
      .sort((a, b) => b.ratio - a.ratio);
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
            <span className="text-[#ffc107]">Margin</span>{" "}
            <span className="text-[#00b4d8]">Curves</span>{" "}
            <span className="text-white">&amp; Liquidation Risk</span>
          </h2>
          <p className="mt-1 text-sm text-white/70 sm:text-base">
            Equity and maintenance margin (left, USDT) with margin ratio (right, %). Liquidation
            approaches as the ratio reaches 100%. Sampled every 5 seconds from the wallet stream.
          </p>
          <div className="mt-2 flex flex-wrap gap-4 text-xs text-white/60">
            <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-emerald-400" /> Equity</span>
            <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-red-400" /> Maintenance margin</span>
            <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-white/40" /> Initial margin</span>
            <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-amber-400" /> Margin ratio (right axis)</span>
          </div>
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
                          {card.series.name.toUpperCase()}
                          <Badge
                            variant="outline"
                            className={`px-1.5 py-0 font-mono text-[10px] uppercase ${exchangeBadgeStyle(card.series.exchange)}`}
                          >
                            {card.series.exchange}
                          </Badge>
                          <Badge
                            variant="outline"
                            className={`flex items-center gap-1 px-1.5 py-0 text-[10px] uppercase ${card.risk.cls}`}
                          >
                            {card.risk.label === "Safe" ? (
                              <ShieldCheck className="h-3 w-3" />
                            ) : (
                              <ShieldAlert className="h-3 w-3" />
                            )}
                            {card.risk.label}
                          </Badge>
                        </CardTitle>
                        <div className="text-right">
                          <p className="text-lg font-bold text-emerald-400">
                            {formatCurrency(card.last.equity)}
                          </p>
                          <p
                            className={`text-xs font-semibold ${
                              rising ? "text-emerald-400" : "text-red-400"
                            }`}
                          >
                            {rising ? "+" : ""}
                            {formatCurrency(card.change)} ({rising ? "+" : ""}
                            {card.changePct.toFixed(2)}%)
                          </p>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      {card.points.length < 2 ? (
                        <div className="flex h-44 items-center justify-center text-sm text-white/40">
                          Collecting samples…
                        </div>
                      ) : (
                        <MarginChart
                          points={card.points}
                          id={String(card.key).replace(/[^a-z0-9]/gi, "")}
                        />
                      )}

                      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                        <div className="rounded-lg bg-slate-800/40 p-2 text-center">
                          <p className="text-[11px] text-white/50">Margin ratio</p>
                          <p
                            className={`text-sm font-bold ${
                              card.ratio >= DANGER_RATIO
                                ? "text-red-400"
                                : card.ratio >= WATCH_RATIO
                                  ? "text-amber-400"
                                  : "text-emerald-400"
                            }`}
                          >
                            {formatRatio(card.ratio)}
                          </p>
                        </div>
                        <div className="rounded-lg bg-slate-800/40 p-2 text-center">
                          <p className="text-[11px] text-white/50">Buffer to liq.</p>
                          <p className="text-sm font-bold text-white">{formatCurrency(card.buffer)}</p>
                        </div>
                        <div className="rounded-lg bg-slate-800/40 p-2 text-center">
                          <p className="text-[11px] text-white/50">Maint. margin</p>
                          <p className="text-sm font-bold text-red-400">
                            {formatCurrency(card.last.maintenanceMargin)}
                          </p>
                        </div>
                        <div className="rounded-lg bg-slate-800/40 p-2 text-center">
                          <p className="text-[11px] text-white/50">Init. margin</p>
                          <p className="text-sm font-bold text-white/80">
                            {formatCurrency(card.last.initialMargin)}
                          </p>
                        </div>
                      </div>

                      <div className="mt-2 flex items-center justify-between text-xs text-white/50">
                        <span>
                          {new Date(card.points[0].t).toLocaleString("en-US", {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                          {" → "}
                          {new Date(card.last.t).toLocaleString("en-US", {
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
