import { useEffect, useRef, memo } from 'react';

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

function TradingViewChart({
  symbol = "BYBIT:BTCUSDT",
  width = "100%",
  height = 400,
  theme = "dark",
  autosize = true,
  interval = "15",
  timezone = "Etc/UTC",
  style = "1",
  locale = "en",
  toolbar_bg = "#f1f3f6",
  enable_publishing = false,
  hide_side_toolbar = false,
  allow_symbol_change = true,
  container_id
}: TradingViewChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Small delay to ensure container has proper dimensions
    const timer = setTimeout(() => {
      if (!containerRef.current) return;

      // Clear any existing content
      containerRef.current.innerHTML = '';

      // Create a unique container div
      const widgetContainer = document.createElement('div');
      widgetContainer.className = 'tradingview-widget-container__widget';
      widgetContainer.style.height = '100%';
      
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
      script.type = 'text/javascript';
      script.async = true;
      
      // Calculate actual height for TradingView
      let actualHeight = height;
      if (typeof height === 'string' && height.includes('calc(')) {
        // For calc values, use the container's actual height
        actualHeight = containerRef.current.clientHeight || 600;
      } else if (typeof height === 'string' && height === '100%') {
        actualHeight = containerRef.current.clientHeight || 600;
      }

      script.innerHTML = JSON.stringify({
        width: "100%",
        height: typeof actualHeight === 'number' ? actualHeight : parseInt(actualHeight.toString()),
        symbol,
        interval,
        timezone,
        theme,
        style,
        locale,
        toolbar_bg,
        enable_publishing,
        allow_symbol_change,
        hide_side_toolbar,
        calendar: false,
        support_host: "https://www.tradingview.com"
      });

      containerRef.current.appendChild(widgetContainer);
      containerRef.current.appendChild(script);
    }, 100); // Small delay to ensure proper rendering

    // Cleanup function
    return () => {
      clearTimeout(timer);
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [symbol, width, height, theme, autosize, interval, timezone, style, locale, toolbar_bg, enable_publishing, hide_side_toolbar, allow_symbol_change]);

  return (
    <div 
      ref={containerRef}
      className="tradingview-widget-container rounded-lg overflow-hidden"
      style={{ 
        width: typeof width === 'number' ? `${width}px` : width,
        height: typeof height === 'number' ? `${height}px` : height 
      }}
    >
      <div className="tradingview-widget-container__widget"></div>
    </div>
  );
}

export default memo(TradingViewChart);