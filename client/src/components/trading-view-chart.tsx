import { useEffect, useRef, useState, memo } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  TickMarkType,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';

/**
 * K-line chart fed by our own backend (/api/market/candles, which proxies the
 * public Bybit API). It used to embed the TradingView widget, but that loads
 * from s3.tradingview.com / tradingview-widget.com in the viewer's browser and
 * renders as a blank box wherever those domains are unreachable. Everything
 * here is bundled, so the browser only ever talks to this server.
 *
 * The props mirror the old widget so existing call sites keep working; options
 * that only made sense for the widget are accepted and ignored.
 */
interface TradingViewChartProps {
  symbol: string;
  width?: string | number;
  height?: string | number;
  theme?: 'light' | 'dark';
  autosize?: boolean;
  interval?: string;
  timezone?: string;
  style?: string;
  locale?: string;
  toolbar_bg?: string;
  enable_publishing?: boolean;
  hide_side_toolbar?: boolean;
  allow_symbol_change?: boolean;
  container_id?: string;
}

interface Candle {
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

const INTERVALS: { label: string; value: string }[] = [
  { label: '1m', value: '1' },
  { label: '5m', value: '5' },
  { label: '15m', value: '15' },
  { label: '1h', value: '60' },
  { label: '4h', value: '240' },
  { label: '1D', value: 'D' },
];

const UP = '#22c55e';
const DOWN = '#ef4444';
const TOOLBAR_HEIGHT = 40;
const HISTORY_LIMIT = 500;
const POLL_MS = 5_000;

/** "BYBIT:BTCUSDT.P" -> "BTCUSDT" (the widget's symbol format -> Bybit's). */
function toBybitSymbol(symbol: string): string {
  const bare = symbol.includes(':') ? symbol.split(':').pop()! : symbol;
  return bare.replace(/\.P$/i, '').toUpperCase();
}

async function fetchCandles(symbol: string, interval: string, limit: number): Promise<Candle[]> {
  const params = new URLSearchParams({ symbol, interval, limit: String(limit) });
  const res = await fetch(`/api/market/candles?${params}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? body.message ?? `HTTP ${res.status}`);
  return body.candles as Candle[];
}

const toBar = (c: Candle) => ({
  time: (c.openTime / 1000) as UTCTimestamp,
  open: c.open,
  high: c.high,
  low: c.low,
  close: c.close,
});

const toVolume = (c: Candle) => ({
  time: (c.openTime / 1000) as UTCTimestamp,
  value: c.volume,
  color: c.close >= c.open ? `${UP}66` : `${DOWN}66`,
});

function TradingViewChart({
  symbol = 'BYBIT:BTCUSDT.P',
  width = '100%',
  height = 400,
  interval = '15',
  allow_symbol_change = true,
}: TradingViewChartProps) {
  const chartBoxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  const [activeSymbol, setActiveSymbol] = useState(() => toBybitSymbol(symbol));
  const [symbolDraft, setSymbolDraft] = useState(activeSymbol);
  const [activeInterval, setActiveInterval] = useState(interval);
  const [last, setLast] = useState<Candle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const next = toBybitSymbol(symbol);
    setActiveSymbol(next);
    setSymbolDraft(next);
  }, [symbol]);

  useEffect(() => setActiveInterval(interval), [interval]);

  // Create the chart once; it follows its container's size.
  useEffect(() => {
    const box = chartBoxRef.current;
    if (!box) return;
    const chart = createChart(box, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#0b1220' },
        textColor: '#94a3b8',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.08)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.08)' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(148, 163, 184, 0.2)' },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.2)',
        timeVisible: true,
        secondsVisible: false,
        // Axis labels in local time too; the default formatter shows UTC.
        tickMarkFormatter: (t: number, type: TickMarkType) => {
          const d = new Date(t * 1000);
          const pad = (n: number) => String(n).padStart(2, '0');
          if (type === TickMarkType.Year) return String(d.getFullYear());
          if (type === TickMarkType.Month || type === TickMarkType.DayOfMonth) {
            return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
          }
          return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
        },
      },
      localization: {
        // Show times in the viewer's local zone (the data is UTC epoch seconds).
        timeFormatter: (t: number) => new Date(t * 1000).toLocaleString(),
      },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'volume' });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.25 } });

    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volume;
    return () => {
      chart.remove();
      chartRef.current = candleRef.current = volumeRef.current = null;
    };
  }, []);

  // Load history for the current symbol/interval, then keep the latest bars live.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    setError(null);

    const load = async () => {
      try {
        const rows = await fetchCandles(activeSymbol, activeInterval, HISTORY_LIMIT);
        if (cancelled || !candleRef.current) return;
        candleRef.current.setData(rows.map(toBar));
        volumeRef.current?.setData(rows.map(toVolume));
        chartRef.current?.timeScale().scrollToRealTime();
        setLast(rows[rows.length - 1] ?? null);

        timer = setInterval(async () => {
          try {
            const recent = await fetchCandles(activeSymbol, activeInterval, 2);
            if (cancelled || !candleRef.current) return;
            for (const c of recent) {
              candleRef.current.update(toBar(c));
              volumeRef.current?.update(toVolume(c));
            }
            setLast(recent[recent.length - 1] ?? null);
            setError(null);
          } catch (e) {
            if (!cancelled) setError((e as Error).message);
          }
        }, POLL_MS);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    };
    load();

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [activeSymbol, activeInterval]);

  const change = last ? ((last.close - last.open) / last.open) * 100 : 0;
  const cssSize = (v: string | number) => (typeof v === 'number' ? `${v}px` : v);

  return (
    <div
      className="rounded-lg overflow-hidden flex flex-col bg-[#0b1220] border border-white/5"
      style={{ width: cssSize(width), height: cssSize(height) }}
    >
      <div
        className="flex items-center gap-3 px-3 border-b border-white/10 text-xs text-white/70 shrink-0"
        style={{ height: TOOLBAR_HEIGHT }}
      >
        {allow_symbol_change ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const next = toBybitSymbol(symbolDraft.trim());
              if (next.length >= 3) setActiveSymbol(next);
            }}
          >
            <input
              value={symbolDraft}
              onChange={(e) => setSymbolDraft(e.target.value.toUpperCase())}
              onBlur={() => setSymbolDraft(activeSymbol)}
              className="w-28 bg-transparent border border-white/15 rounded px-2 py-1 text-white font-medium focus:outline-none focus:border-[#00b4d8]"
              aria-label="Symbol"
            />
          </form>
        ) : (
          <span className="text-white font-medium">{activeSymbol}</span>
        )}
        <div className="flex items-center gap-1">
          {INTERVALS.map((iv) => (
            <button
              key={iv.value}
              type="button"
              onClick={() => setActiveInterval(iv.value)}
              className={`px-2 py-1 rounded ${
                activeInterval === iv.value ? 'bg-white/15 text-white' : 'hover:bg-white/10'
              }`}
            >
              {iv.label}
            </button>
          ))}
        </div>
        {last && (
          <div className="ml-auto flex items-center gap-3 font-mono">
            <span>O {last.open}</span>
            <span>H {last.high}</span>
            <span>L {last.low}</span>
            <span className={change >= 0 ? 'text-green-400' : 'text-red-400'}>
              C {last.close} ({change >= 0 ? '+' : ''}
              {change.toFixed(2)}%)
            </span>
          </div>
        )}
      </div>
      <div className="relative flex-1 min-h-0">
        <div ref={chartBoxRef} className="absolute inset-0" />
        {error && (
          <div className="absolute top-2 left-2 right-2 text-xs text-red-300 bg-red-900/40 border border-red-500/30 rounded px-2 py-1">
            Failed to load {activeSymbol} candles: {error}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(TradingViewChart);
