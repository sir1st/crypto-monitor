import { useEffect, useRef, useState, memo } from 'react';
import { init, dispose, type Chart, type KLineData, type Period } from 'klinecharts';

/**
 * K-line chart with indicators and drawing tools, fed by our own backend
 * (/api/market/candles, which proxies the public Bybit API).
 *
 * The page used to embed the TradingView widget, but that loads from
 * s3.tradingview.com / tradingview-widget.com in the viewer's browser and is a
 * blank box wherever those domains are unreachable. KLineChart is bundled, so
 * the default view only talks to this server. The TradingView widget is still
 * one click away (and remembered) for viewers who can reach it.
 *
 * The props mirror the old widget so existing call sites keep working; options
 * that only made sense for the widget are passed through to it.
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
  turnover: number;
}

const INTERVALS: { label: string; value: string; period: Period }[] = [
  { label: '1m', value: '1', period: { type: 'minute', span: 1 } },
  { label: '5m', value: '5', period: { type: 'minute', span: 5 } },
  { label: '15m', value: '15', period: { type: 'minute', span: 15 } },
  { label: '1h', value: '60', period: { type: 'hour', span: 1 } },
  { label: '4h', value: '240', period: { type: 'hour', span: 4 } },
  { label: '1D', value: 'D', period: { type: 'day', span: 1 } },
];

/** Overlaid on the candles. */
const MAIN_INDICATORS = ['MA', 'EMA', 'BOLL', 'SAR', 'BBI'];
/** Each gets its own pane under the candles. */
const SUB_INDICATORS = ['VOL', 'MACD', 'KDJ', 'RSI', 'CCI', 'WR', 'OBV', 'DMI', 'TRIX'];

const DRAWING_TOOLS: { name: string; label: string }[] = [
  { name: 'segment', label: '线段' },
  { name: 'rayLine', label: '射线' },
  { name: 'straightLine', label: '直线' },
  { name: 'horizontalStraightLine', label: '水平线' },
  { name: 'horizontalRayLine', label: '水平射线' },
  { name: 'verticalStraightLine', label: '垂直线' },
  { name: 'priceLine', label: '价格线' },
  { name: 'priceChannelLine', label: '价格通道' },
  { name: 'parallelStraightLine', label: '平行线' },
  { name: 'fibonacciLine', label: '斐波那契' },
  { name: 'simpleAnnotation', label: '标注' },
];

const UP = '#22c55e';
const DOWN = '#ef4444';
const HISTORY_LIMIT = 1000;
const POLL_MS = 5_000;
const ENGINE_KEY = 'vale.chartEngine';
const DEFAULT_MAIN = ['MA'];
const DEFAULT_SUB = ['VOL'];

/** "BYBIT:BTCUSDT.P" -> "BTCUSDT" (the widget's symbol format -> Bybit's). */
function toBybitSymbol(symbol: string): string {
  const bare = symbol.includes(':') ? symbol.split(':').pop()! : symbol;
  return bare.replace(/\.P$/i, '').toUpperCase();
}

async function fetchCandles(symbol: string, interval: string, limit: number): Promise<KLineData[]> {
  const params = new URLSearchParams({ symbol, interval, limit: String(limit) });
  const res = await fetch(`/api/market/candles?${params}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? body.message ?? `HTTP ${res.status}`);
  return (body.candles as Candle[]).map((c) => ({
    timestamp: c.openTime,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume,
    turnover: c.turnover,
  }));
}

/** Enough decimals to show the smallest price step in the data. */
function pricePrecision(rows: KLineData[]): number {
  let max = 2;
  for (const r of rows.slice(-50)) {
    const decimals = (String(r.close).split('.')[1] ?? '').length;
    max = Math.max(max, decimals);
  }
  return Math.min(max, 8);
}

const DARK_STYLES = {
  grid: {
    horizontal: { color: 'rgba(148, 163, 184, 0.08)' },
    vertical: { color: 'rgba(148, 163, 184, 0.08)' },
  },
  candle: {
    bar: {
      upColor: UP, downColor: DOWN, noChangeColor: '#94a3b8',
      upBorderColor: UP, downBorderColor: DOWN, noChangeBorderColor: '#94a3b8',
      upWickColor: UP, downWickColor: DOWN, noChangeWickColor: '#94a3b8',
    },
    priceMark: {
      last: { upColor: UP, downColor: DOWN, noChangeColor: '#94a3b8' },
      high: { color: '#cbd5e1' },
      low: { color: '#cbd5e1' },
    },
    tooltip: { title: { color: '#cbd5e1' }, legend: { color: '#cbd5e1' } },
  },
  indicator: {
    tooltip: { legend: { color: '#cbd5e1' } },
    bars: [{ upColor: `${UP}88`, downColor: `${DOWN}88`, noChangeColor: '#94a3b888' }],
  },
  xAxis: {
    axisLine: { color: 'rgba(148, 163, 184, 0.2)' },
    tickLine: { color: 'rgba(148, 163, 184, 0.2)' },
    tickText: { color: '#94a3b8' },
  },
  yAxis: {
    axisLine: { color: 'rgba(148, 163, 184, 0.2)' },
    tickLine: { color: 'rgba(148, 163, 184, 0.2)' },
    tickText: { color: '#94a3b8' },
  },
  separator: { color: 'rgba(148, 163, 184, 0.2)' },
  crosshair: {
    horizontal: { line: { color: '#64748b' }, text: { backgroundColor: '#334155' } },
    vertical: { line: { color: '#64748b' }, text: { backgroundColor: '#334155' } },
  },
};

const btn = (active: boolean) =>
  `px-2 py-1 rounded whitespace-nowrap ${active ? 'bg-white/15 text-white' : 'hover:bg-white/10'}`;

function ValeKLineChart({
  symbol,
  interval,
  allowSymbolChange,
  onUseTradingView,
}: {
  symbol: string;
  interval: string;
  allowSymbolChange: boolean;
  onUseTradingView: () => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);

  const [activeSymbol, setActiveSymbol] = useState(symbol);
  const [symbolDraft, setSymbolDraft] = useState(symbol);
  const [activeInterval, setActiveInterval] = useState(interval);
  const [mainInd, setMainInd] = useState<string[]>(DEFAULT_MAIN);
  const [subInd, setSubInd] = useState<string[]>(DEFAULT_SUB);
  const [menu, setMenu] = useState<'none' | 'indicators' | 'draw'>('none');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setActiveSymbol(symbol);
    setSymbolDraft(symbol);
  }, [symbol]);
  useEffect(() => setActiveInterval(interval), [interval]);

  // Create the chart once and keep it sized to its box.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const chart = init(box, { styles: DARK_STYLES });
    if (!chart) return;
    chartRef.current = chart;
    for (const name of DEFAULT_MAIN) chart.createIndicator({ name, paneId: 'candle_pane' }, true);
    for (const name of DEFAULT_SUB) chart.createIndicator(name);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(box);
    return () => {
      observer.disconnect();
      dispose(box);
      chartRef.current = null;
    };
  }, []);

  // (Re)load history and keep the newest bar live for the current symbol/interval.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const iv = INTERVALS.find((i) => i.value === activeInterval) ?? INTERVALS[2];
    let timer: ReturnType<typeof setInterval> | undefined;
    let cancelled = false;
    setError(null);

    chart.setDataLoader({
      getBars: async ({ type, callback }) => {
        // The backend only serves the most recent window, so there is no
        // older/newer page to fetch when the user scrolls past the edge.
        if (type !== 'init') return callback([], false);
        try {
          const rows = await fetchCandles(activeSymbol, iv.value, HISTORY_LIMIT);
          if (cancelled) return;
          chart.setSymbol({ ticker: activeSymbol, pricePrecision: pricePrecision(rows), volumePrecision: 3 });
          callback(rows, false);
        } catch (e) {
          if (!cancelled) setError((e as Error).message);
          callback([], false);
        }
      },
      subscribeBar: ({ callback }) => {
        clearInterval(timer);
        timer = setInterval(async () => {
          try {
            const recent = await fetchCandles(activeSymbol, iv.value, 2);
            if (cancelled) return;
            for (const bar of recent) callback(bar);
            setError(null);
          } catch (e) {
            if (!cancelled) setError((e as Error).message);
          }
        }, POLL_MS);
      },
      unsubscribeBar: () => clearInterval(timer),
    });
    chart.setSymbol({ ticker: activeSymbol, pricePrecision: 2, volumePrecision: 3 });
    chart.setPeriod(iv.period);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeSymbol, activeInterval]);

  const toggleMain = (name: string) => {
    const chart = chartRef.current;
    if (!chart) return;
    if (mainInd.includes(name)) {
      chart.removeIndicator({ paneId: 'candle_pane', name });
      setMainInd(mainInd.filter((n) => n !== name));
    } else {
      chart.createIndicator({ name, paneId: 'candle_pane' }, true);
      setMainInd([...mainInd, name]);
    }
  };

  const toggleSub = (name: string) => {
    const chart = chartRef.current;
    if (!chart) return;
    if (subInd.includes(name)) {
      chart.removeIndicator({ name });
      setSubInd(subInd.filter((n) => n !== name));
    } else {
      chart.createIndicator(name);
      setSubInd([...subInd, name]);
    }
  };

  const draw = (name: string) => {
    chartRef.current?.createOverlay(name);
    setMenu('none');
  };

  return (
    <div className="flex flex-col h-full">
      <div className="relative flex items-center gap-2 px-3 h-10 border-b border-white/10 text-xs text-white/70 shrink-0">
        {allowSymbolChange ? (
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
        <div className="flex items-center gap-0.5">
          {INTERVALS.map((iv) => (
            <button key={iv.value} type="button" onClick={() => setActiveInterval(iv.value)} className={btn(activeInterval === iv.value)}>
              {iv.label}
            </button>
          ))}
        </div>
        <span className="w-px h-5 bg-white/10" />
        <button type="button" onClick={() => setMenu(menu === 'indicators' ? 'none' : 'indicators')} className={btn(menu === 'indicators')}>
          指标
        </button>
        <button type="button" onClick={() => setMenu(menu === 'draw' ? 'none' : 'draw')} className={btn(menu === 'draw')}>
          画线
        </button>
        <button type="button" onClick={() => chartRef.current?.removeOverlay()} className={btn(false)}>
          清除画线
        </button>
        <button type="button" onClick={onUseTradingView} className={`ml-auto ${btn(false)}`} title="需要能访问 tradingview.com">
          切换到 TradingView
        </button>

        {menu === 'indicators' && (
          <div className="absolute left-3 top-10 z-20 w-80 rounded-md border border-white/10 bg-[#0f172a] p-3 shadow-xl">
            <div className="mb-1 text-white/50">主图（叠加在 K 线上）</div>
            <div className="mb-3 flex flex-wrap gap-1">
              {MAIN_INDICATORS.map((n) => (
                <button key={n} type="button" onClick={() => toggleMain(n)} className={btn(mainInd.includes(n))}>{n}</button>
              ))}
            </div>
            <div className="mb-1 text-white/50">副图（独立窗格）</div>
            <div className="flex flex-wrap gap-1">
              {SUB_INDICATORS.map((n) => (
                <button key={n} type="button" onClick={() => toggleSub(n)} className={btn(subInd.includes(n))}>{n}</button>
              ))}
            </div>
          </div>
        )}
        {menu === 'draw' && (
          <div className="absolute left-3 top-10 z-20 w-80 rounded-md border border-white/10 bg-[#0f172a] p-3 shadow-xl">
            <div className="mb-1 text-white/50">选择工具后在图上点击落点</div>
            <div className="flex flex-wrap gap-1">
              {DRAWING_TOOLS.map((t) => (
                <button key={t.name} type="button" onClick={() => draw(t.name)} className={btn(false)}>{t.label}</button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="relative flex-1 min-h-0" onClick={() => menu !== 'none' && setMenu('none')}>
        <div ref={boxRef} className="absolute inset-0" />
        {error && (
          <div className="absolute top-2 left-2 right-16 text-xs text-red-300 bg-red-900/40 border border-red-500/30 rounded px-2 py-1">
            Failed to load {activeSymbol} candles: {error}
          </div>
        )}
      </div>
    </div>
  );
}

/** The original TradingView embed; only works where tradingview.com is reachable. */
function TradingViewEmbed({ props, height }: { props: TradingViewChartProps; height: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    box.innerHTML = '';
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    widget.style.height = '100%';
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      width: '100%',
      height,
      symbol: props.symbol,
      interval: props.interval ?? '15',
      timezone: props.timezone ?? 'Etc/UTC',
      theme: props.theme ?? 'dark',
      style: props.style ?? '1',
      locale: props.locale ?? 'en',
      toolbar_bg: props.toolbar_bg ?? '#f1f3f6',
      enable_publishing: props.enable_publishing ?? false,
      allow_symbol_change: props.allow_symbol_change ?? true,
      hide_side_toolbar: props.hide_side_toolbar ?? false,
      calendar: false,
      support_host: 'https://www.tradingview.com',
    });
    box.appendChild(widget);
    box.appendChild(script);
    return () => {
      box.innerHTML = '';
    };
  }, [props.symbol, props.interval, props.timezone, props.theme, props.style, props.locale, props.toolbar_bg,
      props.enable_publishing, props.allow_symbol_change, props.hide_side_toolbar, height]);
  return <div ref={ref} className="tradingview-widget-container h-full" />;
}

function TradingViewChart(props: TradingViewChartProps) {
  const { symbol = 'BYBIT:BTCUSDT.P', width = '100%', height = 400, interval = '15', allow_symbol_change = true } = props;
  const [engine, setEngine] = useState<'vale' | 'tradingview'>(() =>
    typeof localStorage !== 'undefined' && localStorage.getItem(ENGINE_KEY) === 'tradingview' ? 'tradingview' : 'vale',
  );
  const choose = (next: 'vale' | 'tradingview') => {
    setEngine(next);
    try {
      localStorage.setItem(ENGINE_KEY, next);
    } catch {
      // Private mode etc.: the choice just won't persist.
    }
  };
  const cssSize = (v: string | number) => (typeof v === 'number' ? `${v}px` : v);
  const numericHeight = typeof height === 'number' ? height : parseInt(String(height), 10) || 600;

  return (
    <div
      className="relative rounded-lg overflow-hidden bg-[#0b1220] border border-white/5"
      style={{ width: cssSize(width), height: cssSize(height) }}
    >
      {engine === 'vale' ? (
        <ValeKLineChart
          symbol={toBybitSymbol(symbol)}
          interval={interval}
          allowSymbolChange={allow_symbol_change}
          onUseTradingView={() => choose('tradingview')}
        />
      ) : (
        <>
          <TradingViewEmbed props={{ ...props, symbol }} height={numericHeight} />
          <button
            type="button"
            onClick={() => choose('vale')}
            className="absolute bottom-2 left-2 z-10 rounded bg-[#0f172a]/90 border border-white/15 px-2 py-1 text-xs text-white/80 hover:bg-[#1e293b]"
            title="TradingView 加载不出来时用这个"
          >
            切回本地图表
          </button>
        </>
      )}
    </div>
  );
}

export default memo(TradingViewChart);
