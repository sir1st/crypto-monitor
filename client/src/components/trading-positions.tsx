import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import { Account } from "@shared/schema";
import { apiRequest } from "@/lib/queryClient";

import { 
  Activity, 
  TrendingUp, 
  TrendingDown, 
  Loader2, 
  AlertCircle, 
  DollarSign,
  BarChart3,
  Clock,
  Target,
  Expand,
  X
} from "lucide-react";

interface Position {
  symbol: string;
  side: string;
  size: string;
  leverage: string;
  avgPrice: string;
  markPrice: string;
  unrealisedPnl: string;
  positionValue: string;
  liqPrice: string;
  takeProfit: string;
  stopLoss: string;
  positionStatus: string;
  cumRealisedPnl: string;
  updatedTime: string;
  accountName?: string;
  exchange?: string;
}

export default function TradingPositions() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [isFullScreen, setIsFullScreen] = useState(false);

  // Fetch all accounts
  const { data: accounts = [], isLoading: accountsLoading } = useQuery<Account[]>({
    queryKey: ['/api/accounts'],
    queryFn: async () => {
      const response = await apiRequest('GET', '/api/accounts');
      return response.json();
    },
  });

  // Query positions across all configured exchange accounts
  const { data: positions = [], isLoading: positionsLoading, error, refetch } = useQuery<Position[]>({
    queryKey: ['/api/exchange/positions', refreshKey],
    refetchInterval: 5000, // Refresh every 5 seconds
    staleTime: 1000,
  });

  const isLoading = accountsLoading || positionsLoading;

  const handleRefresh = () => {
    setRefreshKey(prev => prev + 1);
    refetch();
  };

  const toggleFullScreen = async () => {
    if (!isFullScreen) {
      try {
        await document.documentElement.requestFullscreen();
        setIsFullScreen(true);
      } catch (err) {
        console.log('Fullscreen not supported, falling back to page fullscreen');
        setIsFullScreen(true);
      }
    } else {
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

  // Handle fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      if (!document.fullscreenElement && isFullScreen) {
        setIsFullScreen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isFullScreen) {
        toggleFullScreen();
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('keydown', handleKeyDown);
    
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isFullScreen]);

  const formatCurrency = (value: string | number) => {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    if (isNaN(num)) return '$0.00';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(num);
  };

  const formatPrice = (value: string | number) => {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    if (isNaN(num)) return '0.00';
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(num);
  };

  const getPnlColor = (pnl: string) => {
    const value = parseFloat(pnl);
    if (value > 0) return 'text-green-400';
    if (value < 0) return 'text-red-400';
    return 'text-white/70';
  };

  const getPnlIcon = (pnl: string) => {
    const value = parseFloat(pnl);
    if (value > 0) return <TrendingUp className="h-4 w-4" />;
    if (value < 0) return <TrendingDown className="h-4 w-4" />;
    return <BarChart3 className="h-4 w-4" />;
  };

  if (isLoading) {
    return (
      <Card className="bg-[#0d2538] border-[#00b4d8]/20">
        <CardHeader>
          <CardTitle className="text-lg font-bold text-white flex items-center">
            <Activity className="h-5 w-5 text-[#00b4d8] mr-2" />
            Trading Positions
          </CardTitle>
          <CardDescription className="text-white/70">
            Live data from your Bybit account
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-12">
            <div className="text-center space-y-3">
              <Loader2 className="h-8 w-8 animate-spin text-[#00b4d8] mx-auto" />
              <p className="text-white/70">Loading position data...</p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="bg-[#0d2538] border-[#00b4d8]/20">
        <CardHeader>
          <CardTitle className="text-lg font-bold text-white flex items-center">
            <Activity className="h-5 w-5 text-[#00b4d8] mr-2" />
            Trading Positions
          </CardTitle>
          <CardDescription className="text-white/70">
            Live data from your Bybit account
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-12">
            <div className="text-center space-y-3">
              <AlertCircle className="h-8 w-8 text-red-400 mx-auto" />
              <p className="text-red-400">Failed to load position data</p>
              <Button 
                onClick={handleRefresh}
                variant="outline"
                size="sm"
                className="border-[#00b4d8]/50 text-[#00b4d8] hover:bg-[#00b4d8]/10"
              >
                Retry
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const positionsContent = (
    <Card className={`bg-gradient-to-br from-[#0d2538] to-[#1a1a2e] border-[#00b4d8]/30 shadow-2xl shadow-[#00b4d8]/10 ${isFullScreen ? 'h-full' : ''}`}>
      <CardHeader className="p-4 sm:p-6">
        <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start space-y-3 sm:space-y-0">
          <div>
            <CardTitle className="text-lg sm:text-xl font-bold text-white flex items-center">
              <Activity className="h-5 w-5 sm:h-6 sm:w-6 text-[#00b4d8] mr-2" />
              <span className="hidden sm:inline">Trading Positions</span>
              <span className="sm:hidden">Positions</span>
            </CardTitle>
            <CardDescription className="text-white/70 text-sm sm:text-base">
              <span className="hidden sm:inline">Live data</span>
              <span className="sm:hidden">Live Bybit data</span>
            </CardDescription>
          </div>
          <div className="flex items-center space-x-2">
            <Button 
              onClick={handleRefresh}
              variant="outline"
              size="sm"
              className="border-[#00b4d8]/50 text-[#00b4d8] hover:bg-[#00b4d8]/20 hover:border-[#00b4d8] transition-all duration-300 hover:shadow-lg hover:shadow-[#00b4d8]/20 text-xs sm:text-sm"
            >
              <Activity className="h-3 w-3 sm:h-4 sm:w-4 mr-1" />
              <span className="hidden sm:inline">Refresh</span>
              <span className="sm:hidden">↻</span>
            </Button>
            <Button 
              onClick={toggleFullScreen}
              variant="outline"
              size="sm"
              className="border-[#00b4d8]/50 text-[#00b4d8] hover:bg-[#00b4d8]/20 hover:border-[#00b4d8] transition-all duration-300 hover:shadow-lg hover:shadow-[#00b4d8]/20"
              title={isFullScreen ? "Exit full screen" : "Full screen"}
            >
              {isFullScreen ? <X className="h-3 w-3 sm:h-4 sm:w-4" /> : <Expand className="h-3 w-3 sm:h-4 sm:w-4" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-3 sm:p-4 md:p-6">
        {!positions || positions.length === 0 ? (
          <div className="text-center py-16 space-y-6">
            <motion.div 
              className="bg-gradient-to-br from-[#00b4d8]/10 to-[#ffc107]/5 p-8 rounded-xl border border-[#00b4d8]/20 backdrop-blur-sm"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            >
              <motion.div
                animate={{ 
                  scale: [1, 1.1, 1],
                  rotate: [0, 5, -5, 0]
                }}
                transition={{ 
                  duration: 3,
                  repeat: Infinity,
                  ease: "easeInOut"
                }}
              >
                <BarChart3 className="h-16 w-16 text-[#00b4d8] mx-auto mb-4" />
              </motion.div>
              <h3 className="text-white font-bold text-xl mb-3">No Active Positions</h3>
              <p className="text-white/70 text-base">
                {accounts.length === 0 
                  ? "Add a Bybit account to view positions"
                  : "Position data will appear here when available from your connected accounts"
                }
              </p>
            </motion.div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {positions.map((position, index) => {
              const isLong = position.side === "Buy";
              const pnl = parseFloat(position.unrealisedPnl);
              const isProfitable = pnl >= 0;
              
              return (
                <motion.div
                  key={`${position.symbol}-${index}`}
                  initial={{ opacity: 0, y: 20, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ delay: index * 0.1, type: "spring", stiffness: 100 }}
                  className={`relative overflow-hidden rounded-xl backdrop-blur-md border transition-all duration-500 hover:scale-[1.02] hover:shadow-2xl group cursor-pointer ${
                    isLong 
                      ? "bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border-emerald-500/30 shadow-emerald-500/10 hover:border-emerald-500/50 hover:shadow-emerald-500/20" 
                      : "bg-gradient-to-br from-red-500/10 to-red-600/5 border-red-500/30 shadow-red-500/10 hover:border-red-500/50 hover:shadow-red-500/20"
                  }`}
                >
                  {/* Background glow effect */}
                  <div className={`absolute inset-0 opacity-20 ${
                    isLong ? "bg-emerald-500/5" : "bg-red-500/5"
                  }`} />
                  
                  {/* Content */}
                  <div className="relative p-2 sm:p-3 md:p-4 space-y-1.5 sm:space-y-2 md:space-y-3">
                    {/* Header */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        {/* Crypto Logo */}
                        {position.symbol.includes('BTC') ? (
                          <div className="w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-[#f7931a] flex items-center justify-center shadow-lg">
                            <span className="text-white font-bold text-xs">₿</span>
                          </div>
                        ) : (
                          <div className="w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-[#00b4d8]/20 border border-[#00b4d8]/30 flex items-center justify-center">
                            <span className="text-[#00b4d8] font-bold text-xs">{position.symbol.charAt(0)}</span>
                          </div>
                        )}
                        <motion.div 
                          className={`w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full ${
                            isLong ? "bg-emerald-400 shadow-emerald-400/50" : "bg-red-400 shadow-red-400/50"
                          }`}
                          animate={{
                            boxShadow: isLong
                              ? ["0 0 4px rgba(52, 211, 153, 0.5)", "0 0 8px rgba(52, 211, 153, 0.8)", "0 0 4px rgba(52, 211, 153, 0.5)"]
                              : ["0 0 4px rgba(248, 113, 113, 0.5)", "0 0 8px rgba(248, 113, 113, 0.8)", "0 0 4px rgba(248, 113, 113, 0.5)"]
                          }}
                          transition={{
                            duration: 2,
                            repeat: Infinity,
                            ease: "easeInOut"
                          }}
                        />
                        <h3 className="text-sm sm:text-base md:text-lg font-bold text-white group-hover:text-white/90 transition-colors">{position.symbol}</h3>
                      </div>
                      <Badge 
                        variant="outline"
                        className={`text-xs font-semibold border-0 px-1.5 py-0.5 sm:px-2 ${
                          isLong 
                            ? "bg-emerald-500/20 text-emerald-300" 
                            : "bg-red-500/20 text-red-300"
                        }`}
                      >
                        {position.side}
                      </Badge>
                    </div>

                    {/* Account & Exchange Badge */}
                    <div className="flex items-center justify-between gap-1">
                      {position.exchange ? (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase border ${
                          position.exchange.toLowerCase() === 'binance' ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
                          position.exchange.toLowerCase() === 'okx' ? 'bg-white/10 text-white border-white/20' :
                          position.exchange.toLowerCase() === 'bitget' ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30' :
                          position.exchange.toLowerCase() === 'gate' ? 'bg-blue-500/20 text-blue-400 border-blue-500/30' :
                          'bg-orange-500/20 text-orange-400 border-orange-500/30'
                        }`}>
                          {position.exchange}
                        </span>
                      ) : <span />}
                      <div className="text-xs text-[#00b4d8] bg-[#00b4d8]/20 px-2 py-0.5 rounded-full border border-[#00b4d8]/30 truncate max-w-[120px]">
                        {position.accountName || 'Main Account'}
                      </div>
                    </div>

                    {/* Key Metrics */}
                    <div className="grid grid-cols-2 gap-1 sm:gap-2 md:gap-3 text-xs">
                      <div>
                        <span className="text-white/60 block text-xs">Size</span>
                        <span className="text-white font-medium text-xs sm:text-sm">{position.size}</span>
                      </div>
                      <div>
                        <span className="text-white/60 block text-xs">Leverage</span>
                        <span className="text-white font-medium text-xs sm:text-sm">{position.leverage}x</span>
                      </div>
                    </div>

                    {/* Prices */}
                    <div className="space-y-0.5 sm:space-y-1 md:space-y-2 text-xs">
                      <div className="flex justify-between">
                        <span className="text-white/60 text-xs">Entry</span>
                        <span className="text-white font-mono text-xs">${formatPrice(position.avgPrice)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-white/60 text-xs">Mark</span>
                        <span className="text-white font-mono text-xs">${formatPrice(position.markPrice)}</span>
                      </div>
                    </div>

                    {/* PnL Display - Animated */}
                    <motion.div 
                      className={`p-1.5 sm:p-2 md:p-3 rounded-lg border ${
                        isProfitable 
                          ? "bg-emerald-500/10 border-emerald-500/30" 
                          : "bg-red-500/10 border-red-500/30"
                      }`}
                      animate={{
                        boxShadow: isProfitable 
                          ? ["0 0 0 rgba(16, 185, 129, 0)", "0 0 20px rgba(16, 185, 129, 0.3)", "0 0 0 rgba(16, 185, 129, 0)"]
                          : ["0 0 0 rgba(239, 68, 68, 0)", "0 0 20px rgba(239, 68, 68, 0.3)", "0 0 0 rgba(239, 68, 68, 0)"]
                      }}
                      transition={{
                        duration: 2,
                        repeat: Infinity,
                        ease: "easeInOut"
                      }}
                    >
                      <div className="space-y-0.5 sm:space-y-1 md:space-y-2">
                        <div className="flex justify-between items-center">
                          <span className="text-white/70 text-xs">
                            <span className="hidden sm:inline">Unrealized PnL</span>
                            <span className="sm:hidden">PnL</span>
                          </span>
                          <motion.span 
                            className={`font-bold text-xs sm:text-sm md:text-base font-mono ${
                              isProfitable ? "text-emerald-300" : "text-red-300"
                            }`}
                            animate={{
                              scale: [1, 1.05, 1],
                            }}
                            transition={{
                              duration: 1.5,
                              repeat: Infinity,
                              ease: "easeInOut"
                            }}
                          >
                            {isProfitable ? "+" : ""}{formatCurrency(position.unrealisedPnl)}
                          </motion.span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-white/60 text-xs">PnL %</span>
                          <motion.span 
                            className={`font-semibold text-xs font-mono ${
                              isProfitable ? "text-emerald-300" : "text-red-300"
                            }`}
                            animate={{
                              scale: [1, 1.03, 1],
                            }}
                            transition={{
                              duration: 1.8,
                              repeat: Infinity,
                              ease: "easeInOut"
                            }}
                          >
                            {(() => {
                              const entryPrice = parseFloat(position.avgPrice);
                              const markPrice = parseFloat(position.markPrice);
                              const leverage = parseFloat(position.leverage);
                              
                              if (entryPrice > 0 && markPrice > 0) {
                                const priceChange = isLong ? markPrice - entryPrice : entryPrice - markPrice;
                                const pnlPercent = (priceChange / entryPrice) * leverage * 100;
                                return `${pnlPercent >= 0 ? "+" : ""}${pnlPercent.toFixed(2)}%`;
                              }
                              return "0.00%";
                            })()}
                          </motion.span>
                        </div>
                      </div>
                    </motion.div>




                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );

  if (isFullScreen) {
    return (
      <div className="fixed inset-0 z-50 bg-[#0a192f] p-4">
        {positionsContent}
      </div>
    );
  }

  return positionsContent;
}