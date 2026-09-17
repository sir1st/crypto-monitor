import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/queryClient";
import { Button } from "@/components/ui/button";
import { motion } from "framer-motion";
import DashboardPage from "@/pages/dashboard-page";
import CalculatorPage from "@/pages/calculator-page";
import TradingPositions from "@/components/trading-positions";
import AccountManagement from "@/components/account-management";
import AccountAddressMap from "@/components/account-address-map";
import { WalletStream } from "@/components/wallet-stream";
import BybitApiStatus from "@/components/bybit-api-status";
import MarketHours from "@/components/market-hours";
import TradingViewChart from "@/components/trading-view-chart";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Bell, User, Settings, HelpCircle, Wallet, BarChart2, Activity, Globe, Zap, Link, Users, Maximize2, Minimize2, Expand, X, ChevronDown, ChevronUp, TrendingUp, TrendingDown, Calculator } from "lucide-react";

function ChartSection() {
  const [chartHeight, setChartHeight] = useState(600);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [showPositions, setShowPositions] = useState(true);
  
  // Fetch positions data with more frequent updates
  const { data: positions = [], refetch: refetchPositions } = useQuery<any[]>({
    queryKey: ["/api/bybit/positions"],
    refetchInterval: 2000, // Update every 2 seconds for real-time data
    refetchOnWindowFocus: true,
    staleTime: 1000, // Consider data stale after 1 second
  });

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
    setChartHeight(isExpanded ? 600 : 800);
  };

  const toggleFullScreen = async () => {
    if (!isFullScreen) {
      // Enter full screen
      try {
        await document.documentElement.requestFullscreen();
        setIsFullScreen(true);
        // Refresh positions when entering full screen for fresh data
        refetchPositions();
      } catch (err) {
        console.log('Fullscreen not supported, falling back to page fullscreen');
        setIsFullScreen(true);
        refetchPositions();
      }
    } else {
      // Exit full screen
      try {
        if (document.fullscreenElement) {
          await document.exitFullscreen();
        }
        setIsFullScreen(false);
      } catch (err) {
        setIsFullScreen(false);
      }
    }
  };

  // Fullscreen change events and keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isFullScreen) {
        toggleFullScreen();
      }
    };

    const handleFullscreenChange = () => {
      // Update state when user exits fullscreen using browser controls
      if (!document.fullscreenElement && isFullScreen) {
        setIsFullScreen(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, [isFullScreen]);

  return (
    <>
      {/* Regular Chart */}
      {!isFullScreen && (
        <div className="mb-4 sm:mb-6 border border-[#00b4d8]/30 rounded-lg overflow-hidden bg-gradient-to-br from-[#0d2538] to-[#1a1a2e] shadow-xl">
            <div className="bg-white/5 border-b border-white/10">
            {/* Main Header */}
            <div className="p-2 sm:p-3 flex items-center justify-between">
              <div className="flex items-center">
                <BarChart2 className="h-4 w-4 sm:h-5 sm:w-5 text-[#00b4d8] mr-1 sm:mr-2" />
                <span className="text-white/90 font-medium text-sm sm:text-base">
                  <span className="hidden sm:inline">BTCUSDT Perpetual Futures</span>
                  <span className="sm:hidden">BTCUSDT</span>
                </span>
                {positions.length > 0 && (
                  <div className="ml-2 sm:ml-4 flex items-center space-x-1 sm:space-x-2">
                    <span className="text-white/60 text-xs sm:text-sm">Pos: {positions.length}</span>
                    <Button
                      onClick={() => {
                        setShowPositions(!showPositions);
                        refetchPositions(); // Refresh positions when toggling
                      }}
                      variant="ghost"
                      size="sm"
                      className="text-white/70 hover:text-white hover:bg-white/10 h-5 w-5 sm:h-6 sm:w-6 p-0"
                      title="Toggle positions panel"
                    >
                      {showPositions ? <ChevronUp className="h-2 w-2 sm:h-3 sm:w-3" /> : <ChevronDown className="h-2 w-2 sm:h-3 sm:w-3" />}
                    </Button>
                  </div>
                )}
              </div>
              <div className="flex items-center space-x-1 sm:space-x-2">
                <span className="hidden sm:inline text-white/60 text-sm">Height: {chartHeight}px</span>
                <Button
                  onClick={toggleExpanded}
                  variant="ghost"
                  size="sm"
                  className="text-white/70 hover:text-white hover:bg-white/10 h-6 w-6 sm:h-7 sm:w-7 p-0"
                  title="Resize chart"
                >
                  {isExpanded ? <Minimize2 className="h-3 w-3 sm:h-4 sm:w-4" /> : <Maximize2 className="h-3 w-3 sm:h-4 sm:w-4" />}
                </Button>
                <Button
                  onClick={toggleFullScreen}
                  variant="ghost"
                  size="sm"
                  className="text-white/70 hover:text-white hover:bg-white/10 h-6 w-6 sm:h-7 sm:w-7 p-0"
                  title="Full screen"
                >
                  <Expand className="h-3 w-3 sm:h-4 sm:w-4" />
                </Button>
              </div>
            </div>

            {/* Collapsible Positions Panel */}
            {showPositions && positions.length > 0 && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.3 }}
                className="px-3 pb-3 overflow-hidden"
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {positions.map((position: any, index: number) => {
                    const unrealizedPnl = parseFloat(position.unrealisedPnl || '0');
                    const isWinning = unrealizedPnl > 0;
                    const entryPrice = parseFloat(position.avgPrice || '0');
                    const markPrice = parseFloat(position.markPrice || '0');
                    const leverage = parseFloat(position.leverage || '1');
                    const isLong = position.side === 'Buy';
                    
                    // Calculate real-time PnL percentage
                    let pnlPercentage = 0;
                    if (entryPrice > 0 && markPrice > 0) {
                      const priceChange = isLong ? markPrice - entryPrice : entryPrice - markPrice;
                      pnlPercentage = (priceChange / entryPrice) * leverage * 100;
                    }
                    
                    return (
                      <motion.div
                        key={`${position.symbol}-${index}`}
                        className={`p-2 rounded-md border transition-all duration-300 ${
                          isWinning 
                            ? 'bg-green-500/10 border-green-500/30' 
                            : 'bg-red-500/10 border-red-500/30'
                        }`}
                        animate={{
                          boxShadow: isWinning 
                            ? ['0 0 0 rgba(34, 197, 94, 0)', '0 0 10px rgba(34, 197, 94, 0.3)', '0 0 0 rgba(34, 197, 94, 0)']
                            : ['0 0 0 rgba(239, 68, 68, 0)', '0 0 10px rgba(239, 68, 68, 0.3)', '0 0 0 rgba(239, 68, 68, 0)']
                        }}
                        transition={{ duration: 2, repeat: Infinity }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center space-x-1">
                            {position.symbol === 'BTCUSDT' && (
                              <span className="text-orange-400 text-sm mr-1">₿</span>
                            )}
                            <span className="text-white/90 font-medium text-sm">{position.symbol}</span>
                            <div className={`flex items-center ${position.side === 'Buy' ? 'text-green-400' : 'text-red-400'}`}>
                              {position.side === 'Buy' ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                              <span className="text-xs ml-1">{position.side}</span>
                            </div>
                          </div>
                          <div className="flex items-center space-x-1">
                            {position.accountName && (
                              <span className="text-[#00b4d8] text-xs px-1.5 py-0.5 rounded-full bg-[#00b4d8]/10 border border-[#00b4d8]/20">
                                {position.accountName}
                              </span>
                            )}
                            <span className="text-white/60 text-xs">{position.leverage}x</span>
                          </div>
                        </div>
                        <div className="text-xs text-white/60">
                          Entry: ${parseFloat(position.avgPrice || '0').toLocaleString()}
                        </div>
                        <motion.div 
                          className="text-xs text-white/60"
                          animate={{
                            opacity: [0.6, 1, 0.6],
                          }}
                          transition={{
                            duration: 2,
                            repeat: Infinity,
                            ease: "easeInOut"
                          }}
                        >
                          Mark: ${parseFloat(position.markPrice || '0').toLocaleString()}
                        </motion.div>
                        <div className="text-xs text-white/60">
                          Size: {parseFloat(position.size || '0').toFixed(4)}
                        </div>
                        <div className={`text-xs font-medium ${isWinning ? 'text-green-400' : 'text-red-400'}`}>
                          PnL: {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(2)} ({pnlPercentage >= 0 ? '+' : ''}{pnlPercentage.toFixed(2)}%)
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </div>
          <TradingViewChart 
            key={`chart-${chartHeight}`}
            symbol="BYBIT:BTCUSDT.P"
            height={chartHeight}
            theme="dark"
            interval="15"
            hide_side_toolbar={true}
            allow_symbol_change={true}
          />
        </div>
      )}

      {/* Full Screen Chart */}
      {isFullScreen && (
        <div className="fixed inset-0 z-50 bg-[#0a192f] flex flex-col">
          <div className="bg-[#112240] border-b border-[#00b4d8]/30">
            {/* Full Screen Main Header */}
            <div className="p-4 flex items-center justify-between">
              <div className="flex items-center">
                <BarChart2 className="h-6 w-6 text-[#00b4d8] mr-3" />
                <span className="text-white font-medium text-lg">BTCUSDT Perpetual Futures - Full Screen</span>
                {positions.length > 0 && (
                  <div className="ml-6 flex items-center space-x-4">
                    <span className="text-white/60">Positions: {positions.length}</span>
                    <Button
                      onClick={() => {
                        setShowPositions(!showPositions);
                        refetchPositions(); // Refresh positions when toggling
                      }}
                      variant="ghost"
                      size="sm"
                      className="text-white/70 hover:text-white hover:bg-white/10 h-7 w-7 p-0"
                      title="Toggle positions panel"
                    >
                      {showPositions ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </Button>
                  </div>
                )}
              </div>
              <Button
                onClick={toggleFullScreen}
                variant="ghost"
                size="sm"
                className="text-white/70 hover:text-white hover:bg-white/10 h-8 w-8 p-0"
                title="Exit full screen (ESC)"
              >
                <X className="h-5 w-5" />
              </Button>
            </div>

            {/* Full Screen Positions Panel */}
            {showPositions && positions.length > 0 && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.3 }}
                className="px-4 pb-4 overflow-hidden"
              >
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-3">
                  {positions.map((position: any, index: number) => {
                    const unrealizedPnl = parseFloat(position.unrealisedPnl || '0');
                    const isWinning = unrealizedPnl > 0;
                    const entryPrice = parseFloat(position.avgPrice || '0');
                    const markPrice = parseFloat(position.markPrice || '0');
                    const leverage = parseFloat(position.leverage || '1');
                    const isLong = position.side === 'Buy';
                    
                    // Calculate real-time PnL percentage
                    let pnlPercentage = 0;
                    if (entryPrice > 0 && markPrice > 0) {
                      const priceChange = isLong ? markPrice - entryPrice : entryPrice - markPrice;
                      pnlPercentage = (priceChange / entryPrice) * leverage * 100;
                    }
                    
                    return (
                      <motion.div
                        key={`fullscreen-${position.symbol}-${index}`}
                        className={`p-3 rounded-lg border transition-all duration-300 ${
                          isWinning 
                            ? 'bg-green-500/10 border-green-500/30' 
                            : 'bg-red-500/10 border-red-500/30'
                        }`}
                        animate={{
                          boxShadow: isWinning 
                            ? ['0 0 0 rgba(34, 197, 94, 0)', '0 0 15px rgba(34, 197, 94, 0.4)', '0 0 0 rgba(34, 197, 94, 0)']
                            : ['0 0 0 rgba(239, 68, 68, 0)', '0 0 15px rgba(239, 68, 68, 0.4)', '0 0 0 rgba(239, 68, 68, 0)']
                        }}
                        transition={{ duration: 2, repeat: Infinity }}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center space-x-2">
                            {position.symbol === 'BTCUSDT' && (
                              <span className="text-orange-400 text-lg">₿</span>
                            )}
                            <span className="text-white font-medium">{position.symbol}</span>
                            <div className={`flex items-center ${position.side === 'Buy' ? 'text-green-400' : 'text-red-400'}`}>
                              {position.side === 'Buy' ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                              <span className="text-sm ml-1">{position.side}</span>
                            </div>
                          </div>
                          <div className="flex items-center space-x-2">
                            {position.accountName && (
                              <span className="text-[#00b4d8] text-sm px-2 py-1 rounded-full bg-[#00b4d8]/10 border border-[#00b4d8]/20">
                                {position.accountName}
                              </span>
                            )}
                            <span className="text-white/60 text-sm">{position.leverage}x</span>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <div className="text-sm text-white/70">
                            Entry: ${parseFloat(position.avgPrice || '0').toLocaleString()}
                          </div>
                          <motion.div 
                            className="text-sm text-white/70"
                            animate={{
                              opacity: [0.7, 1, 0.7],
                            }}
                            transition={{
                              duration: 2,
                              repeat: Infinity,
                              ease: "easeInOut"
                            }}
                          >
                            Mark: ${parseFloat(position.markPrice || '0').toLocaleString()}
                          </motion.div>
                          <div className="text-sm text-white/70">
                            Size: {parseFloat(position.size || '0').toFixed(4)}
                          </div>
                          <div className={`text-sm font-medium ${isWinning ? 'text-green-400' : 'text-red-400'}`}>
                            PnL: {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(2)}
                          </div>
                          <div className={`text-xs ${isWinning ? 'text-green-400' : 'text-red-400'}`}>
                            {pnlPercentage >= 0 ? '+' : ''}{pnlPercentage.toFixed(2)}%
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </div>
          <div className="flex-1" style={{ minHeight: '600px', height: showPositions ? 'calc(100vh - 300px)' : 'calc(100vh - 120px)' }}>
            <TradingViewChart 
              key={`fullscreen-chart-${isFullScreen}-${showPositions}`}
              symbol="BYBIT:BTCUSDT.P"
              height={showPositions ? window.innerHeight - 300 : window.innerHeight - 120}
              theme="dark"
              interval="15"
              hide_side_toolbar={false}
              allow_symbol_change={true}
            />
          </div>
        </div>
      )}
    </>
  );
}

export default function HomePage() {
  return (
    <div className="min-h-screen bg-[#0a192f] text-white">
      {/* Header */}
      <header className="p-2 sm:p-4 border-b border-[#00b4d8]/20 flex justify-between items-center sticky top-0 bg-[#0a192f] z-10">
        <div className="flex items-center">
          <h1 className="font-['Orbitron'] text-lg sm:text-xl lg:text-2xl whitespace-nowrap">
            <span className="text-[#ffc107]">Vale</span>{" "}
            <span className="text-[#00b4d8]">Monitor</span>
          </h1>
        </div>

        {/* Desktop Navigation */}
        <div className="hidden md:flex items-center space-x-6 ml-12">
          <button className="flex items-center text-[#00b4d8] border-b-2 border-[#00b4d8] px-2 py-1">
            <Activity size={16} className="mr-1" /> Positions
          </button>
        </div>
        
      </header>
      
      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-4 sm:py-8 px-2 sm:px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="mb-4 sm:mb-6">
            <h2 className="text-xl sm:text-2xl font-bold font-['Orbitron']">
              <span className="text-[#ffc107]">Trading</span>{" "}
              <span className="text-[#00b4d8]">Positions</span>{" "}
              <span className="text-white">Monitor</span>
            </h2>
            <p className="text-white/70 mt-1 text-sm sm:text-base">
              Track your open positions, PnL, and market data in real-time
            </p>
          </div>
          
          <Tabs defaultValue="positions" className="w-full">
            <div className="mb-4 sm:mb-6 overflow-x-auto scrollbar-hide">
              <TabsList className="flex w-full min-w-max sm:grid sm:grid-cols-5 sm:max-w-5xl bg-[#112240] p-1 h-auto gap-1 sm:gap-0">
                <TabsTrigger 
                  value="positions" 
                  className="flex-shrink-0 min-w-[90px] sm:min-w-0 data-[state=active]:bg-[#0a192f] data-[state=active]:text-[#00b4d8] data-[state=active]:shadow-none text-xs sm:text-sm py-3 px-3 sm:px-4 rounded-md sm:rounded-none"
                >
                  <BarChart2 size={16} className="mr-1 sm:mr-2" />
                  <span className="whitespace-nowrap">Positions</span>
                </TabsTrigger>
                <TabsTrigger 
                  value="dashboard" 
                  className="flex-shrink-0 min-w-[90px] sm:min-w-0 data-[state=active]:bg-[#0a192f] data-[state=active]:text-[#00b4d8] data-[state=active]:shadow-none text-xs sm:text-sm py-3 px-3 sm:px-4 rounded-md sm:rounded-none relative"
                >
                  <Activity size={16} className="mr-1 sm:mr-2" />
                  <span className="whitespace-nowrap">Dashboard</span>
                  <span className="absolute -top-1 -right-1 w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                </TabsTrigger>
                <TabsTrigger 
                  value="accounts" 
                  className="flex-shrink-0 min-w-[90px] sm:min-w-0 data-[state=active]:bg-[#0a192f] data-[state=active]:text-[#00b4d8] data-[state=active]:shadow-none text-xs sm:text-sm py-3 px-3 sm:px-4 rounded-md sm:rounded-none"
                >
                  <Users size={16} className="mr-1 sm:mr-2" />
                  <span className="whitespace-nowrap">Accounts</span>
                </TabsTrigger>
                <TabsTrigger 
                  value="streaming" 
                  className="flex-shrink-0 min-w-[90px] sm:min-w-0 data-[state=active]:bg-[#0a192f] data-[state=active]:text-[#00b4d8] data-[state=active]:shadow-none text-xs sm:text-sm py-3 px-3 sm:px-4 rounded-md sm:rounded-none"
                >
                  <Zap size={16} className="mr-1 sm:mr-2" />
                  <span className="whitespace-nowrap">Live Stream</span>
                </TabsTrigger>
                <TabsTrigger 
                  value="calculator" 
                  className="flex-shrink-0 min-w-[90px] sm:min-w-0 data-[state=active]:bg-[#0a192f] data-[state=active]:text-[#00b4d8] data-[state=active]:shadow-none text-xs sm:text-sm py-3 px-3 sm:px-4 rounded-md sm:rounded-none"
                >
                  <Calculator size={16} className="mr-1 sm:mr-2" />
                  <span className="whitespace-nowrap">Calculator</span>
                </TabsTrigger>
              </TabsList>
            </div>
            
            <TabsContent value="positions" className="mt-6 sm:mt-8">
              {/* Chart Section */}
              <ChartSection />
              
              <TradingPositions />
            </TabsContent>
            
            <TabsContent value="dashboard" className="mt-0">
              <DashboardPage />
            </TabsContent>
            
            <TabsContent value="accounts" className="mt-0">
              <AccountManagement />
              <div className="mt-6">
                <AccountAddressMap />
              </div>
            </TabsContent>
            
            <TabsContent value="streaming" className="mt-0">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2">
                  <WalletStream />
                  
                  <div className="mt-6">
                    <BybitApiStatus />
                  </div>
                  
                  <div className="mt-6">
                    <MarketHours />
                  </div>
                </div>
                <div className="lg:col-span-1">
                  <div className="rounded-lg border bg-card text-card-foreground shadow-sm bg-black/5 border-[#00b4d8]/20 p-6">
                    <h3 className="text-lg font-semibold mb-4 flex items-center">
                      <Zap size={18} className="text-[#ffc107] mr-2" />
                      About Real-time Data
                    </h3>
                    <p className="text-sm text-white/70 mb-4">
                      Vale Monitor streams wallet updates over a WebSocket, authenticated by your session.
                    </p>
                    <ul className="space-y-2 text-sm text-white/70">
                      <li className="flex items-start">
                        <span className="text-[#ffc107] mr-2">•</span>
                        <span>Updates every 5 seconds without page refreshes</span>
                      </li>
                      <li className="flex items-start">
                        <span className="text-[#ffc107] mr-2">•</span>
                        <span>See immediate changes to balance, PnL, and positions</span>
                      </li>
                      <li className="flex items-start">
                        <span className="text-[#ffc107] mr-2">•</span>
                        <span>Automatic reconnection if connection is lost</span>
                      </li>
                      <li className="flex items-start">
                        <span className="text-[#ffc107] mr-2">•</span>
                        <span>Subscribe to specific data streams based on your needs</span>
                      </li>
                    </ul>
                    <div className="mt-6 p-3 rounded-md bg-[#112240] border border-[#00b4d8]/20 text-xs font-mono">
                      <p className="text-white/70">Connection: <span className="text-[#00b4d8]">{`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`}</span></p>
                      <p className="text-white/70 mt-1">Topic: <span className="text-[#ffc107]">wallet</span></p>
                      <p className="text-white/70 mt-1">Status: <span className="text-emerald-400">connected</span></p>
                    </div>
                    
                    <div className="mt-6 p-3 rounded-md bg-[#112240] border border-[#00b4d8]/20">
                      <h4 className="text-sm font-medium mb-2 flex items-center">
                        <Link size={14} className="text-[#ffc107] mr-2" />
                        Bybit Integration
                      </h4>
                      <p className="text-xs text-white/70">
                        This platform is now connected to the Bybit exchange API, providing real wallet data instead of simulated values.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </TabsContent>
            
            <TabsContent value="calculator" className="mt-0">
              <CalculatorPage />
            </TabsContent>
          </Tabs>
        </motion.div>
      </main>
    </div>
  );
}
