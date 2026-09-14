import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Wallet, 
  TrendingUp, 
  TrendingDown, 
  DollarSign, 
  Target, 
  BarChart3, 
  Calendar,
  Activity,
  Award,
  Coins,
  PieChart,
  Clock,
  Percent,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff
} from "lucide-react";

interface SymbolData {
  symbol: string;
  totalPnl: number;
  winPnl: number;
  lossPnl: number;
  winCount: number;
  lossCount: number;
  totalTrades: number;
  winRate: number;
  pnlRatio: number | null;
}

interface CoinData {
  coin: string;
  walletBalance: number | null;
  usdValue: number | null;
}

interface AccountBalanceData {
  accountName: string;
  exchange?: string;
  currentEquity: number;
  walletBalance: number;
  unrealizedPnl: number;
  balance7DaysAgo: number;
  balanceWeekStart: number;
  
  // 7-day performance
  tradingPnl7d: number;
  growthPercentage7d: number;
  winCount7d: number;
  lossCount7d: number;
  winRate7d: number;
  pnlRatio7d: number | null;
  winPnl7d: number;
  lossPnl7d: number;
  
  // Weekly performance
  weeklyPnl: number;
  weeklyGrowthPercentage: number;
  weeklyWinCount: number;
  weeklyLossCount: number;
  weeklyWinRate: number;
  weeklyPnlRatio: number | null;
  weeklyWinPnl: number;
  weeklyLossPnl: number;
  weekStart: string;
  daysTrading: number;
  
  // Position sizing
  positionSizes: Record<string, number>;
  
  // Symbol breakdowns
  symbols7d: SymbolData[];
  weeklySymbols: SymbolData[];
  
  // Coin breakdown
  coinBreakdown: CoinData[];
}

interface AccountBalanceCardProps {
  data: AccountBalanceData;
  initialCollapsed?: boolean;
}

export default function AccountBalanceCard({ data, initialCollapsed = true }: AccountBalanceCardProps) {
  const [isCollapsed, setIsCollapsed] = useState(initialCollapsed);
  const formatCurrency = (amount: number | null | undefined) => {
    if (amount === null || amount === undefined || isNaN(amount)) return '$0.00';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(amount);
  };

  const formatPercentage = (value: number | null | undefined) => {
    if (value === null || value === undefined || isNaN(value)) return '0.00%';
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  const formatNumber = (value: number | null | undefined, decimals: number = 2) => {
    if (value === null || value === undefined || isNaN(value)) return '0';
    return value.toFixed(decimals);
  };

  const formatRatio = (value: number | null | undefined) => {
    if (value === null || value === undefined || isNaN(value)) return '0.00';
    if (value === Infinity) return '∞';
    return value.toFixed(2);
  };

  const getWeekStartDate = () => {
    return new Date(data.weekStart).toLocaleDateString('en-US', { 
      weekday: 'short',
      month: 'short', 
      day: 'numeric' 
    });
  };

  const weeklyProfitIcon = data.weeklyPnl >= 0 ? TrendingUp : TrendingDown;
  const sevenDayProfitIcon = data.tradingPnl7d >= 0 ? TrendingUp : TrendingDown;

  const toggleCollapsed = () => {
    setIsCollapsed(!isCollapsed);
  };

  const renderExchangeBadge = (exchange?: string) => {
    if (!exchange) return null;
    const ex = exchange.toLowerCase();
    const style =
      ex === 'binance' ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
      ex === 'okx' ? 'bg-white/10 text-white border-white/20' :
      ex === 'bitget' ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30' :
      ex === 'gate' ? 'bg-blue-500/20 text-blue-400 border-blue-500/30' :
      'bg-orange-500/20 text-orange-400 border-orange-500/30';
    return <Badge variant="outline" className={`text-[10px] uppercase font-mono px-1.5 py-0 ${style}`}>{exchange}</Badge>;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      layout
    >
      <Card className={`bg-gradient-to-br from-slate-900/90 to-slate-800/60 border-slate-700/50 transition-all duration-300 hover:border-slate-600/70 ${
        isCollapsed ? 'cursor-pointer hover:bg-slate-800/20' : ''
      }`}>
        {/* Collapsed View */}
        {isCollapsed && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={toggleCollapsed}
            className="p-4"
          >
            <div className="flex items-center justify-between">
              {/* Account Info */}
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-cyan-600 rounded-lg flex items-center justify-center">
                  <Wallet className="w-5 h-5 text-white" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold text-white">{data.accountName.toUpperCase()}</h3>
                    {renderExchangeBadge(data.exchange)}
                  </div>
                  <p className="text-sm text-muted-foreground">Trading Account</p>
                </div>
              </div>

              {/* Key Metrics */}
              <div className="flex items-center gap-6">
                {/* Current Balance */}
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">Current Balance</p>
                  <p className="text-xl font-bold text-emerald-400">{formatCurrency(data.currentEquity)}</p>
                </div>

                {/* Weekly Performance */}
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">Weekly P&L</p>
                  <p className={`text-lg font-semibold ${data.weeklyPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatPercentage(data.weeklyGrowthPercentage)}
                  </p>
                </div>

                {/* Status */}
                <div className="flex items-center gap-2">
                  <motion.div 
                    className="w-2 h-2 bg-emerald-400 rounded-full"
                    animate={{ 
                      scale: [1, 1.2, 1],
                      opacity: [1, 0.7, 1] 
                    }}
                    transition={{ 
                      duration: 2, 
                      repeat: Infinity, 
                      ease: "easeInOut" 
                    }}
                  />
                  <span className="text-sm text-emerald-400 font-medium">Live</span>
                </div>

                {/* Expand Button */}
                <motion.div 
                  className="flex items-center justify-center w-8 h-8 rounded-full bg-slate-700/50 hover:bg-slate-600/50 transition-colors"
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.95 }}
                >
                  <ChevronRight className="w-4 h-4 text-slate-400" />
                </motion.div>
              </div>
            </div>
          </motion.div>
        )}

        {/* Expanded View */}
        <AnimatePresence>
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.3 }}
            >
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-cyan-600 rounded-lg flex items-center justify-center">
                      <Wallet className="w-6 h-6 text-white" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-xl text-white">{data.accountName.toUpperCase()} ACCOUNT</CardTitle>
                        {renderExchangeBadge(data.exchange)}
                      </div>
                      <CardDescription>Real-time balance & performance analysis</CardDescription>
                    </div>
                  </div>
                  
                  {/* Collapse Button */}
                  <motion.button 
                    onClick={toggleCollapsed}
                    className="flex items-center justify-center w-10 h-10 rounded-full bg-slate-700/50 hover:bg-slate-600/50 transition-colors"
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    <ChevronDown className="w-5 h-5 text-slate-400" />
                  </motion.button>
                </div>
              </CardHeader>
              
              <CardContent className="space-y-6">
                {/* Balance Summary */}
                <motion.div 
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                >
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="text-center p-4 bg-slate-800/40 rounded-lg border border-slate-700/30 hover:border-slate-600/50 transition-colors">
                      <div className="flex items-center justify-center mb-2">
                        <DollarSign className="w-5 h-5 text-emerald-400 mr-1" />
                        <p className="text-sm text-muted-foreground">Current Balance</p>
                      </div>
                      <p className="text-2xl font-bold text-emerald-400">{formatCurrency(data.currentEquity)}</p>
                      <p className="text-xs text-muted-foreground">Total Equity</p>
                    </div>
                    
                    <div className="text-center p-4 bg-slate-800/40 rounded-lg border border-slate-700/30 hover:border-slate-600/50 transition-colors">
                      <div className="flex items-center justify-center mb-2">
                        <Calendar className="w-5 h-5 text-blue-400 mr-1" />
                        <p className="text-sm text-muted-foreground">Balance 7 Days Ago</p>
                      </div>
                      <p className="text-2xl font-bold text-blue-400">{formatCurrency(data.balance7DaysAgo)}</p>
                      <p className="text-xs text-muted-foreground">Before trading</p>
                    </div>
                    
                    <div className="text-center p-4 bg-slate-800/40 rounded-lg border border-slate-700/30 hover:border-slate-600/50 transition-colors">
                      <div className="flex items-center justify-center mb-2">
                        <Activity className="w-5 h-5 text-purple-400 mr-1" />
                        <p className="text-sm text-muted-foreground">Unrealized P&L</p>
                      </div>
                      <p className={`text-2xl font-bold ${data.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatCurrency(data.unrealizedPnl)}
                      </p>
                      <p className="text-xs text-muted-foreground">Open positions</p>
                    </div>
                  </div>
                </motion.div>

                <Separator className="bg-slate-700/50" />

                {/* Weekly Performance */}
                <motion.div 
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                >
                  <div className="flex items-center gap-2 mb-4">
                    <Clock className="w-5 h-5 text-yellow-400" />
                    <h3 className="text-lg font-semibold text-white">
                      Weekly Performance (Mon {getWeekStartDate()})
                    </h3>
                    <Badge variant="secondary" className="text-xs">
                      {data.daysTrading} day{data.daysTrading !== 1 ? 's' : ''}
                    </Badge>
                  </div>
                  
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        {React.createElement(weeklyProfitIcon, { 
                          className: `w-4 h-4 mr-1 ${data.weeklyPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}` 
                        })}
                        <p className="text-xs text-muted-foreground">Weekly PnL</p>
                      </div>
                      <p className={`text-lg font-bold ${data.weeklyPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatCurrency(data.weeklyPnl)}
                      </p>
                    </div>
                    
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        <Percent className="w-4 h-4 text-blue-400 mr-1" />
                        <p className="text-xs text-muted-foreground">Net Growth</p>
                      </div>
                      <p className={`text-lg font-bold ${data.weeklyGrowthPercentage >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatPercentage(data.weeklyGrowthPercentage)}
                      </p>
                    </div>
                    
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        <BarChart3 className="w-4 h-4 text-purple-400 mr-1" />
                        <p className="text-xs text-muted-foreground">Trades</p>
                      </div>
                      <p className="text-lg font-bold text-white">
                        {data.weeklyWinCount + data.weeklyLossCount}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        <span className="text-emerald-400">{data.weeklyWinCount}W</span> / 
                        <span className="text-red-400">{data.weeklyLossCount}L</span>
                      </p>
                    </div>
                    
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        <Target className="w-4 h-4 text-yellow-400 mr-1" />
                        <p className="text-xs text-muted-foreground">Win Rate</p>
                      </div>
                      <p className="text-lg font-bold text-yellow-400">{formatNumber(data.weeklyWinRate, 1)}%</p>
                    </div>
                  </div>
                </motion.div>

                <Separator className="bg-slate-700/50" />

                {/* 7-Day Trading Performance */}
                <motion.div 
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3 }}
                >
                  <div className="flex items-center gap-2 mb-4">
                    <BarChart3 className="w-5 h-5 text-cyan-400" />
                    <h3 className="text-lg font-semibold text-white">7-Day Trading Performance</h3>
                  </div>
                  
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        {React.createElement(sevenDayProfitIcon, { 
                          className: `w-4 h-4 mr-1 ${data.tradingPnl7d >= 0 ? 'text-emerald-400' : 'text-red-400'}` 
                        })}
                        <p className="text-xs text-muted-foreground">Trading PnL</p>
                      </div>
                      <p className={`text-lg font-bold ${data.tradingPnl7d >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatCurrency(data.tradingPnl7d)}
                      </p>
                    </div>
                    
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        <Percent className="w-4 h-4 text-green-400 mr-1" />
                        <p className="text-xs text-muted-foreground">Growth Rate</p>
                      </div>
                      <p className={`text-lg font-bold ${data.growthPercentage7d >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatPercentage(data.growthPercentage7d)}
                      </p>
                    </div>
                    
                    <div className="text-center p-3 bg-slate-800/30 rounded-lg hover:bg-slate-700/30 transition-colors">
                      <div className="flex items-center justify-center mb-1">
                        <Award className="w-4 h-4 text-yellow-400 mr-1" />
                        <p className="text-xs text-muted-foreground">PnL Ratio</p>
                      </div>
                      <p className="text-lg font-bold text-yellow-400">
                        {formatRatio(data.pnlRatio7d)}
                      </p>
                    </div>
                  </div>
                </motion.div>

                <Separator className="bg-slate-700/50" />

                {/* Position Sizing */}
                <motion.div 
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.4 }}
                >
                  <div className="flex items-center gap-2 mb-4">
                    <Target className="w-5 h-5 text-green-400" />
                    <h3 className="text-lg font-semibold text-white">Position Sizing</h3>
                    <Badge variant="outline" className="text-xs">
                      Based on {formatCurrency(data.currentEquity)}
                    </Badge>
                  </div>
                  
                  <div className="grid grid-cols-5 gap-3">
                    {Object.entries(data.positionSizes).map(([percentage, amount]) => (
                      <div key={percentage} className="text-center p-3 bg-slate-800/30 rounded-lg border border-slate-700/30 hover:border-green-500/30 hover:bg-slate-700/30 transition-all">
                        <p className="text-sm font-medium text-green-400 mb-1">{percentage}</p>
                        <p className="text-sm font-bold text-white">{formatCurrency(amount)}</p>
                      </div>
                    ))}
                  </div>
                </motion.div>

                {/* Top Symbols */}
                {(data.weeklySymbols.length > 0 || data.symbols7d.length > 0) && (
                  <>
                    <Separator className="bg-slate-700/50" />
                    <motion.div 
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.5 }}
                    >
                      <div className="flex items-center gap-2 mb-4">
                        <PieChart className="w-5 h-5 text-purple-400" />
                        <h3 className="text-lg font-semibold text-white">Top Symbols</h3>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Weekly symbols */}
                        {data.weeklySymbols.length > 0 && (
                          <div>
                            <h4 className="text-sm font-medium text-muted-foreground mb-2">This Week</h4>
                            <div className="space-y-2">
                              {data.weeklySymbols.slice(0, 3).map((symbol) => (
                                <div key={symbol.symbol} className="flex justify-between items-center p-2 bg-slate-800/20 rounded hover:bg-slate-700/20 transition-colors">
                                  <span className="text-sm font-medium text-white">{symbol.symbol}</span>
                                  <div className="text-right">
                                    <span className={`text-sm font-bold ${symbol.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {formatCurrency(symbol.totalPnl)}
                                    </span>
                                    <p className="text-xs text-muted-foreground">
                                      {symbol.winCount}W/{symbol.lossCount}L
                                    </p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        
                        {/* 7-day symbols */}
                        {data.symbols7d.length > 0 && (
                          <div>
                            <h4 className="text-sm font-medium text-muted-foreground mb-2">7-Day</h4>
                            <div className="space-y-2">
                              {data.symbols7d.slice(0, 3).map((symbol) => (
                                <div key={symbol.symbol} className="flex justify-between items-center p-2 bg-slate-800/20 rounded hover:bg-slate-700/20 transition-colors">
                                  <span className="text-sm font-medium text-white">{symbol.symbol}</span>
                                  <div className="text-right">
                                    <span className={`text-sm font-bold ${symbol.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {formatCurrency(symbol.totalPnl)}
                                    </span>
                                    <p className="text-xs text-muted-foreground">
                                      {symbol.winCount}W/{symbol.lossCount}L
                                    </p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </motion.div>
                  </>
                )}

                {/* Coin Breakdown */}
                {data.coinBreakdown.length > 0 && (
                  <>
                    <Separator className="bg-slate-700/50" />
                    <motion.div 
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.6 }}
                    >
                      <div className="flex items-center gap-2 mb-4">
                        <Coins className="w-5 h-5 text-amber-400" />
                        <h3 className="text-lg font-semibold text-white">Coin Breakdown</h3>
                        <Badge variant="outline" className="text-xs">
                          {data.coinBreakdown.length} coin{data.coinBreakdown.length !== 1 ? 's' : ''}
                        </Badge>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {data.coinBreakdown.slice(0, 6).map((coin) => (
                          <div key={coin.coin} className="flex justify-between items-center p-3 bg-slate-800/20 rounded-lg hover:bg-slate-700/20 transition-colors">
                            <div>
                              <span className="text-sm font-bold text-white">{coin.coin}</span>
                              <p className="text-xs text-muted-foreground">
                                {formatNumber(coin.walletBalance, 8)}
                              </p>
                            </div>
                            <span className="text-sm font-medium text-amber-400">
                              {formatCurrency(coin.usdValue)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  </>
                )}
              </CardContent>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.div>
  );
}