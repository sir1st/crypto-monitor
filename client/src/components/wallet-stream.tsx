import { useWalletStream } from "@/hooks/use-wallet-stream";
import { Loader2, WifiOff, Activity, RefreshCw, TrendingUp, TrendingDown, Wallet, DollarSign, ChevronDown, ChevronUp, Eye, EyeOff, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState, useRef } from 'react';

// Component to track P&L changes and trigger animations
function AnimatedPnLValue({ value, className, prefix = "" }: { value: number, className?: string, prefix?: string }) {
  const [prevValue, setPrevValue] = useState(value);
  const [isFlashing, setIsFlashing] = useState(false);
  const [flashType, setFlashType] = useState<'positive' | 'negative' | null>(null);

  useEffect(() => {
    if (prevValue !== value && prevValue !== 0) {
      const changeType = value > prevValue ? 'positive' : 'negative';
      setFlashType(changeType);
      setIsFlashing(true);
      
      const timer = setTimeout(() => {
        setIsFlashing(false);
        setFlashType(null);
      }, 600);
      
      return () => clearTimeout(timer);
    }
    setPrevValue(value);
  }, [value, prevValue]);

  return (
    <motion.p 
      className={`font-semibold ${className} ${
        isFlashing 
          ? flashType === 'positive' 
            ? 'animate-pulse text-emerald-400' 
            : 'animate-pulse text-red-400'
          : ''
      }`}
      animate={isFlashing ? { scale: [1, 1.05, 1] } : {}}
      transition={{ duration: 0.3 }}
    >
      {prefix}{value.toLocaleString()}
    </motion.p>
  );
}

// Type definitions for the wallet data structure
interface CoinData {
  coin: string;
  equity: string;
  usdValue: string;
  walletBalance: string;
  unrealisedPnl: string;
}

interface AccountData {
  accountIMRate: string;
  accountMMRate: string;
  totalEquity: string;
  totalWalletBalance: string;
  totalMarginBalance: string;
  totalAvailableBalance: string;
  totalPerpUPL: string;
  totalInitialMargin: string;
  totalMaintenanceMargin: string;
  coin: CoinData[];
  accountLTV: string;
  accountType: string;
  accountName?: string; // This is the custom account name from our database
  accountId?: number;
}

interface WalletStreamData {
  data: AccountData[];
  creationTime: number;
}

export function WalletStream() {
  const { isConnected, isSubscribed, data, error } = useWalletStream();
  const [showAccountDetails, setShowAccountDetails] = useState(false);
  const [expandedCards, setExpandedCards] = useState<Set<number>>(new Set());
  const [showAllAssets, setShowAllAssets] = useState<Set<number>>(new Set());
  
  const toggleCard = (index: number) => {
    const newExpanded = new Set(expandedCards);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedCards(newExpanded);
  };

  const toggleShowAllAssets = (index: number) => {
    const newShowAll = new Set(showAllAssets);
    if (newShowAll.has(index)) {
      newShowAll.delete(index);
    } else {
      newShowAll.add(index);
    }
    setShowAllAssets(newShowAll);
  };
  
  if (error) {
    return (
      <Card className="w-full enhanced-card border-red-500/20">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <WifiOff className="h-5 w-5 text-red-500 animate-pulse" />
              Live Stream Status
            </CardTitle>
            <Badge variant="destructive" className="h-6 shadow-lg animate-pulse">
              Disconnected
            </Badge>
          </div>
          <CardDescription>Real-time wallet data stream</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="bg-gradient-to-r from-red-900/10 to-red-800/5 text-red-400 rounded-lg p-4 text-sm border border-red-500/20">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-red-500 rounded-full animate-ping"></div>
              {error}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }
  
  if (!isConnected || !isSubscribed) {
    return (
      <Card className="w-full enhanced-card border-amber-500/20">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <RefreshCw className="h-5 w-5 animate-spin text-amber-500" />
              Live Stream Status
            </CardTitle>
            <Badge variant="outline" className="h-6 bg-gradient-to-r from-amber-500/10 to-amber-400/5 text-amber-400 border-amber-500/30 shadow-lg">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse"></div>
                {isConnected ? 'Connecting' : 'Initializing'}
              </div>
            </Badge>
          </div>
          <CardDescription>Real-time wallet data stream</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center py-6">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }
  
  if (!data) {
    return (
      <Card className="w-full bg-black/5">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-500" />
              Live Stream Status
            </CardTitle>
            <Badge variant="outline" className="h-6 bg-emerald-500/10 text-emerald-500 border-emerald-500/20">Connected</Badge>
          </div>
          <CardDescription>Real-time wallet data stream</CardDescription>
        </CardHeader>
        <CardContent className="py-6 text-center text-muted-foreground">
          <p>Waiting for wallet data...</p>
        </CardContent>
      </Card>
    );
  }

  // Type guard to ensure data has the correct structure
  const walletData = data as WalletStreamData;
  
  if (!walletData.data || !Array.isArray(walletData.data)) {
    return (
      <Card className="w-full bg-black/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-500" />
            Live Stream Status
          </CardTitle>
        </CardHeader>
        <CardContent className="py-6 text-center text-muted-foreground">
          <p>Invalid wallet data format</p>
        </CardContent>
      </Card>
    );
  }
  
  // Calculate aggregated totals from all accounts
  const aggregatedTotals = walletData.data.reduce((totals, account) => {
    return {
      totalEquity: totals.totalEquity + parseFloat(account.totalEquity || '0'),
      totalWalletBalance: totals.totalWalletBalance + parseFloat(account.totalWalletBalance || '0'),
      totalAvailableBalance: totals.totalAvailableBalance + parseFloat(account.totalAvailableBalance || '0'),
      totalPerpUPL: totals.totalPerpUPL + parseFloat(account.totalPerpUPL || '0'),
      accounts: [...totals.accounts, account.accountName || account.accountType || 'Unknown']
    };
  }, {
    totalEquity: 0,
    totalWalletBalance: 0,
    totalAvailableBalance: 0,
    totalPerpUPL: 0,
    accounts: [] as string[]
  });

  // Aggregate all coins across accounts
  const aggregatedCoins = new Map();
  walletData.data.forEach(account => {
    account.coin?.forEach(coin => {
      const existing = aggregatedCoins.get(coin.coin) || {
        coin: coin.coin,
        equity: 0,
        usdValue: 0,
        walletBalance: 0,
        unrealisedPnl: 0,
        accounts: []
      };
      
      existing.equity += parseFloat(coin.equity || '0');
      existing.usdValue += parseFloat(coin.usdValue || '0');
      existing.walletBalance += parseFloat(coin.walletBalance || '0');
      existing.unrealisedPnl += parseFloat(coin.unrealisedPnl || '0');
      existing.accounts.push(account.accountName || account.accountType || 'Unknown');
      
      aggregatedCoins.set(coin.coin, existing);
    });
  });
  
  const combinedWalletData = {
    ...aggregatedTotals,
    coin: Array.from(aggregatedCoins.values())
  };
  
  return (
    <div className="space-y-4">
      {/* Aggregated Summary Card with Collapsible Details */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.3 }}
      >
        <Card className="w-full relative overflow-hidden bg-gradient-to-br from-slate-900/80 to-slate-800/60 border-slate-700/60 shadow-xl shadow-black/20">
          {/* Animated gradient background */}
          <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 via-emerald-500/5 to-blue-500/5 animate-pulse" />
          
          <CardHeader className="pb-3 relative z-10">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xl font-bold flex items-center gap-3 text-white">
                <div className="w-10 h-10 bg-gradient-to-br from-emerald-500/30 to-blue-500/30 rounded-xl flex items-center justify-center">
                  <Activity className="h-5 w-5 text-emerald-400" />
                </div>
                Live Wallet Updates (Combined)
              </CardTitle>
              <motion.div
                animate={{ scale: [1, 1.05, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
              >
                <Badge className="h-7 px-3 bg-emerald-500/20 text-emerald-300 border-emerald-500/30 font-medium">
                  Live
                </Badge>
              </motion.div>
            </div>
            <CardDescription className="text-slate-300 text-sm">
              Real-time updates at {new Date(walletData.creationTime).toLocaleTimeString()} • {walletData.data.length} accounts
            </CardDescription>
          </CardHeader>
          
          <CardContent className="pb-4 relative z-10">
            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-emerald-400" />
                  <p className="text-sm text-slate-400 font-medium">Total Equity</p>
                </div>
                <AnimatedPnLValue 
                  value={aggregatedTotals.totalEquity} 
                  className="text-2xl text-white"
                  prefix="$"
                />
              </div>
              
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Wallet className="w-4 h-4 text-blue-400" />
                  <p className="text-sm text-slate-400 font-medium">Wallet Balance</p>
                </div>
                <p className="text-2xl font-bold text-white">
                  ${aggregatedTotals.totalWalletBalance.toLocaleString()}
                </p>
              </div>
              
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  {aggregatedTotals.totalPerpUPL > 0 ? (
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  ) : aggregatedTotals.totalPerpUPL < 0 ? (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  ) : (
                    <Activity className="w-4 h-4 text-slate-400" />
                  )}
                  <p className="text-sm text-slate-400 font-medium">Unrealized P&L</p>
                </div>
                <AnimatedPnLValue 
                  value={aggregatedTotals.totalPerpUPL}
                  className={`text-2xl ${
                    aggregatedTotals.totalPerpUPL > 0 
                      ? 'text-emerald-400' 
                      : aggregatedTotals.totalPerpUPL < 0 
                        ? 'text-red-400' 
                        : 'text-slate-300'
                  }`}
                  prefix="$"
                />
              </div>
              
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-blue-400" />
                  <p className="text-sm text-slate-400 font-medium">Available Balance</p>
                </div>
                <p className="text-2xl font-bold text-white">
                  ${aggregatedTotals.totalAvailableBalance.toLocaleString()}
                </p>
              </div>
            </div>
          </CardContent>
          
          <CardFooter className="pt-3 pb-4 relative z-10 border-t border-slate-700/50">
            <div className="w-full">
              <div className="flex items-center justify-between mb-3">
                <div className="text-center flex-1">
                  <p className="text-sm text-slate-400">
                    Combined data from: <span className="text-blue-400 font-medium">{aggregatedTotals.accounts.join(', ')}</span>
                  </p>
                </div>
                <Button
                  onClick={() => setShowAccountDetails(!showAccountDetails)}
                  variant="outline"
                  size="sm"
                  className="ml-4 border-slate-600/50 text-slate-300 hover:bg-slate-700/30 hover:text-white"
                >
                  <Plus className={`w-4 h-4 mr-2 transition-transform duration-200 ${showAccountDetails ? 'rotate-45' : ''}`} />
                  {showAccountDetails ? 'Hide Details' : 'Show Details'}
                </Button>
              </div>
              
              {/* Collapsible Account Details */}
              <AnimatePresence>
                {showAccountDetails && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3, ease: "easeInOut" }}
                    className="overflow-hidden"
                  >
                    <Separator className="mb-4 bg-slate-700/50" />
                    
                    {/* Individual Account Cards - Space Efficient Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {walletData.data.map((account, index) => {
                        const pnlValue = parseFloat(account.totalPerpUPL || '0');
                        const equityValue = parseFloat(account.totalEquity || '0');
                        const accountName = account.accountName || account.accountType || `Account ${index + 1}`;
                        const isExpanded = expandedCards.has(index);
                        const shouldShowAllAssets = showAllAssets.has(index);
                        const displayAssets = account.coin || [];
                        const visibleAssets = shouldShowAllAssets ? displayAssets : displayAssets.slice(0, 2);
                        
                        return (
                          <motion.div
                            key={index}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: index * 0.05 }}
                            layout
                          >
                            <Card className="relative overflow-hidden bg-gradient-to-br from-slate-800/40 to-slate-700/20 border-slate-600/40 hover:border-slate-500/60 transition-all duration-300 group hover:shadow-md hover:shadow-primary/5 cursor-pointer">
                              {/* Clickable Header */}
                              <CardHeader 
                                className="pb-2 relative z-10 cursor-pointer select-none"
                                onClick={() => toggleCard(index)}
                              >
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    <div className="w-6 h-6 bg-gradient-to-br from-blue-500/20 to-emerald-500/20 rounded-md flex items-center justify-center">
                                      <Wallet className="w-3 h-3 text-blue-400" />
                                    </div>
                                    <CardTitle className="text-sm font-semibold text-white">{accountName}</CardTitle>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <Badge 
                                      variant="outline" 
                                      className="text-xs h-4 bg-slate-700/50 border-slate-500/50 text-slate-300 px-1.5"
                                    >
                                      Live
                                    </Badge>
                                    <motion.div
                                      animate={{ rotate: isExpanded ? 180 : 0 }}
                                      transition={{ duration: 0.2 }}
                                      className="text-slate-400 hover:text-white transition-colors"
                                    >
                                      <ChevronDown className="w-3 h-3" />
                                    </motion.div>
                                  </div>
                                </div>
                                
                                {/* Quick Summary (Always Visible) */}
                                <div className="grid grid-cols-2 gap-2 mt-2">
                                  <div className="space-y-0.5">
                                    <div className="flex items-center gap-1">
                                      <DollarSign className="w-2.5 h-2.5 text-emerald-400" />
                                      <p className="text-xs text-slate-400">Equity</p>
                                    </div>
                                    <p className="text-sm font-semibold text-white">
                                      ${equityValue.toLocaleString()}
                                    </p>
                                  </div>
                                  
                                  <div className="space-y-0.5">
                                    <div className="flex items-center gap-1">
                                      {pnlValue > 0 ? (
                                        <TrendingUp className="w-2.5 h-2.5 text-emerald-400" />
                                      ) : pnlValue < 0 ? (
                                        <TrendingDown className="w-2.5 h-2.5 text-red-400" />
                                      ) : (
                                        <Activity className="w-2.5 h-2.5 text-slate-400" />
                                      )}
                                      <p className="text-xs text-slate-400">P&L</p>
                                    </div>
                                    <p className={`text-sm font-semibold ${
                                      pnlValue > 0 
                                        ? 'text-emerald-400' 
                                        : pnlValue < 0 
                                          ? 'text-red-400' 
                                          : 'text-slate-300'
                                    }`}>
                                      {pnlValue > 0 ? '+' : ''}${pnlValue.toLocaleString()}
                                    </p>
                                  </div>
                                </div>
                              </CardHeader>
                              
                              {/* Collapsible Content */}
                              <AnimatePresence>
                                {isExpanded && (
                                  <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: "auto", opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    transition={{ duration: 0.3, ease: "easeInOut" }}
                                    className="overflow-hidden"
                                  >
                                    <CardContent className="pb-3 relative z-10 pt-0 px-4">
                                      <Separator className="mb-3 bg-slate-600/50" />
                                      
                                      <div className="space-y-3">
                                        {/* Detailed metrics */}
                                        <div className="grid grid-cols-2 gap-2 text-xs">
                                          <div className="space-y-0.5">
                                            <p className="text-slate-400">Balance</p>
                                            <p className="font-semibold text-white">
                                              ${parseFloat(account.totalWalletBalance || '0').toLocaleString()}
                                            </p>
                                          </div>
                                          
                                          <div className="space-y-0.5">
                                            <p className="text-slate-400">Available</p>
                                            <p className="font-semibold text-white">
                                              ${parseFloat(account.totalAvailableBalance || '0').toLocaleString()}
                                            </p>
                                          </div>
                                          
                                          <div className="space-y-0.5">
                                            <p className="text-slate-400">Margin</p>
                                            <p className="font-semibold text-white">
                                              ${parseFloat(account.totalMarginBalance || '0').toLocaleString()}
                                            </p>
                                          </div>
                                          
                                          <div className="space-y-0.5">
                                            <p className="text-slate-400">LTV</p>
                                            <p className="font-semibold text-white">
                                              {parseFloat(account.accountLTV || '0').toFixed(2)}%
                                            </p>
                                          </div>
                                        </div>
                                        
                                        {/* Assets section */}
                                        {displayAssets.length > 0 && (
                                          <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                              <div className="flex items-center gap-1">
                                                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full" />
                                                <p className="text-xs font-medium text-slate-300">Assets ({displayAssets.length})</p>
                                              </div>
                                              {displayAssets.length > 2 && (
                                                <button
                                                  onClick={(e) => {
                                                    e.stopPropagation();
                                                    toggleShowAllAssets(index);
                                                  }}
                                                  className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                                                >
                                                  {shouldShowAllAssets ? (
                                                    <>
                                                      <EyeOff className="w-2.5 h-2.5" />
                                                      Less
                                                    </>
                                                  ) : (
                                                    <>
                                                      <Eye className="w-2.5 h-2.5" />
                                                      All
                                                    </>
                                                  )}
                                                </button>
                                              )}
                                            </div>
                                            
                                            <div className="space-y-1">
                                              <AnimatePresence>
                                                {visibleAssets.map((coin, coinIndex) => (
                                                  <motion.div 
                                                    key={coin.coin}
                                                    initial={{ opacity: 0, x: -5 }}
                                                    animate={{ opacity: 1, x: 0 }}
                                                    exit={{ opacity: 0, x: -5 }}
                                                    transition={{ delay: coinIndex * 0.02 }}
                                                    className="flex items-center justify-between text-xs bg-slate-700/20 border border-slate-600/20 p-1.5 rounded hover:bg-slate-600/20 transition-colors"
                                                  >
                                                    <div className="flex items-center gap-1.5">
                                                      <div className="w-4 h-4 bg-gradient-to-br from-orange-400/20 to-orange-600/20 rounded-full flex items-center justify-center">
                                                        <span className="text-xs font-bold text-orange-400">
                                                          {coin.coin.substring(0, 1)}
                                                        </span>
                                                      </div>
                                                      <span className="font-medium text-slate-200">{coin.coin}</span>
                                                    </div>
                                                    <div className="text-right">
                                                      <div className="text-slate-400">${parseFloat(coin.usdValue || '0').toLocaleString()}</div>
                                                      {parseFloat(coin.unrealisedPnl || '0') !== 0 && (
                                                        <div className={`text-xs ${parseFloat(coin.unrealisedPnl || '0') > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                          {parseFloat(coin.unrealisedPnl || '0') > 0 ? '+' : ''}${parseFloat(coin.unrealisedPnl || '0').toFixed(2)}
                                                        </div>
                                                      )}
                                                    </div>
                                                  </motion.div>
                                                ))}
                                              </AnimatePresence>
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    </CardContent>
                                  </motion.div>
                                )}
                              </AnimatePresence>
                            </Card>
                          </motion.div>
                        );
                      })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </CardFooter>
        </Card>
      </motion.div>
    </div>
  );
}