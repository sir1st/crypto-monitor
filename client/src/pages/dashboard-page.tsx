import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { motion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import { 
  Trophy, 
  TrendingUp, 
  TrendingDown, 
  DollarSign, 
  Target, 
  BarChart3, 
  Calendar,
  Activity,
  RefreshCw,
  Award,
  Zap,
  PieChart,
  Clock,
  Expand,
  Minimize2
} from "lucide-react";
import { Account } from "@shared/schema";
import { apiRequest } from "@/lib/queryClient";
import AccountBalanceCard from "@/components/account-balance-card";

// Types for our dashboard data
interface TrophyStats {
  topWinPercentage: number;
  topWinLeverage: string;
  topValueWin: number;
  totalWeeklyTrades: number;
  weekStart: string;
  weekEnd: string;
}

interface TradingReport {
  accountName: string;
  timeframe: string;
  totalROI: number;
  totalPnL: number;
  winROI: number;
  winPnL: number;
  lossROI: number;
  lossPnL: number;
  winCount: number;
  lossCount: number;
  pnlRatio: number;
}


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

export default function DashboardPage() {
  const [selectedTimeframe, setSelectedTimeframe] = useState("7");
  const [allExpanded, setAllExpanded] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const toggleAllCards = () => {
    setAllExpanded(!allExpanded);
  };

  const timeframeOptions = [
    { value: "1", label: "1D" },
    { value: "3", label: "3D" },
    { value: "7", label: "7D" },
    { value: "30", label: "30D" }
  ];

  // Fetch accounts (only for admin users)
  const { data: accounts = [], isLoading: accountsLoading } = useQuery<Account[]>({
    queryKey: ['/api/accounts'],
    queryFn: async () => {
      const response = await apiRequest('GET', '/api/accounts');
      return response.json();
    },
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Real-time Trophy data from Bybit API (updates every 5 seconds)
  const { data: trophyStats = { 
    topWinPercentage: 0, 
    topWinLeverage: "N/A", 
    topValueWin: 0, 
    totalWeeklyTrades: 0,
    weekStart: "",
    weekEnd: ""
  } } = useQuery<TrophyStats>({
    queryKey: ['/api/trophy-stats'],
    queryFn: async () => {
      const response = await apiRequest('GET', '/api/trophy-stats');
      return response.json();
    },
    refetchInterval: 5000,
    staleTime: 0, // Override global setting - always consider data stale
  });



  // Real trading reports from Bybit API - no weekly reports, only trading reports
  const { data: tradingReports = [] } = useQuery<TradingReport[]>({
    queryKey: ['/api/trading-reports', selectedTimeframe],
    queryFn: async () => {
      const response = await apiRequest('GET', `/api/trading-reports?timeframe=${selectedTimeframe}`);
      const data = await response.json();
      console.log(`✅ Frontend received ${data.length} trading reports from accounts:`, data.map((r: any) => `${r.accountName} (${r.winCount} wins)`).join(', '));
      console.log('📊 Full trading reports data:', data);
      return data;
    },
    refetchInterval: 5000, // Refresh every 5 seconds for live data
  });

  // Account Balance Data - Real-time balance analysis like Python script
  const { data: accountsBalance = [], isLoading: balanceLoading, error: balanceError } = useQuery<AccountBalanceData[]>({
    queryKey: ['/api/account-balance'],
    queryFn: async () => {
      const response = await apiRequest('GET', '/api/account-balance');
      const data = await response.json();
      console.log(`✅ Frontend received balance data for ${data.length} accounts:`, data.map((a: any) => `${a.accountName} ($${a.currentEquity.toFixed(2)})`).join(', '));
      console.log('📊 Full balance data:', data);
      return data;
    },
    retry: (failureCount, error) => {
      // Don't retry auth errors, but retry network/server errors
      if (error.message.includes('401') || error.message.includes('403')) {
        return false;
      }
      return failureCount < 2;
    },
    refetchInterval: 10000, // Refresh every 10 seconds for balance data
  });

  // Aggregate all trading reports into a single combined report
  const aggregatedReport = tradingReports.reduce((acc, report) => {
    console.log(`📈 Processing report for ${report.accountName}: ${report.winCount} wins, $${report.totalPnL} PnL`);
    return {
      accountName: "All Accounts Combined",
      timeframe: report.timeframe,
      totalROI: acc.totalROI + (report.totalROI || 0),
      totalPnL: acc.totalPnL + (report.totalPnL || 0),
      winROI: acc.winROI + (report.winROI || 0),
      winPnL: acc.winPnL + (report.winPnL || 0),
      lossROI: acc.lossROI + (report.lossROI || 0),
      lossPnL: acc.lossPnL + (report.lossPnL || 0),
      winCount: acc.winCount + (report.winCount || 0),
      lossCount: acc.lossCount + (report.lossCount || 0),
      pnlRatio: 0 // Will calculate after
    };
  }, {
    accountName: "All Accounts Combined",
    timeframe: tradingReports[0]?.timeframe || `${selectedTimeframe} day${selectedTimeframe !== '1' ? 's' : ''}`,
    totalROI: 0,
    totalPnL: 0,
    winROI: 0,
    winPnL: 0,
    lossROI: 0,
    lossPnL: 0,
    winCount: 0,
    lossCount: 0,
    pnlRatio: 0
  });

  // Add verification logging for the aggregated results
  console.log(`🎯 Aggregated ${tradingReports.length} accounts: ${aggregatedReport.winCount} total wins, $${aggregatedReport.totalPnL.toFixed(2)} total PnL`);

  // Calculate final aggregated metrics
  aggregatedReport.pnlRatio = Math.abs(aggregatedReport.lossPnL) > 0 ? Math.abs(aggregatedReport.winPnL / aggregatedReport.lossPnL) : Infinity;

  const handleRefresh = () => {
    setRefreshKey(prev => prev + 1);
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(amount);
  };

  const formatPercentage = (value: number) => {
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Dashboard</h1>
          <p className="text-muted-foreground">Performance analytics and trading insights</p>
        </div>
        <Button onClick={handleRefresh} variant="outline" size="sm">
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Trophy Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <Card className="bg-gradient-to-r from-yellow-500/10 via-orange-500/10 to-red-500/10 border-yellow-500/20">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 bg-gradient-to-br from-yellow-400 to-orange-500 rounded-lg flex items-center justify-center">
                <Trophy className="w-6 h-6 text-yellow-900" />
              </div>
              <div>
                <CardTitle className="text-xl text-yellow-400">🏆 Trophy</CardTitle>
                <CardDescription>Real-time weekly performance (Monday UTC midnight start)</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
                              <div className="text-center">
                  <div className="flex items-center justify-center mb-2">
                    <Target className="w-5 h-5 text-emerald-400 mr-1" />
                    <p className="text-sm text-muted-foreground">Top Trade %</p>
                  </div>
                  <p className="text-3xl font-bold text-emerald-400">{trophyStats.topWinPercentage.toFixed(1)}%</p>
                  <p className="text-xs text-muted-foreground">{trophyStats.topWinLeverage}x leverage</p>
                </div>
              
              <div className="text-center">
                <div className="flex items-center justify-center mb-2">
                  <DollarSign className="w-5 h-5 text-yellow-400 mr-1" />
                  <p className="text-sm text-muted-foreground">Top Value Win</p>
                </div>
                <p className="text-3xl font-bold text-yellow-400">{formatCurrency(trophyStats.topValueWin)}</p>
                <p className="text-xs text-muted-foreground">Single trade</p>
              </div>
              
              <div className="text-center">
                <div className="flex items-center justify-center mb-2">
                  <Activity className="w-5 h-5 text-blue-400 mr-1" />
                  <p className="text-sm text-muted-foreground">Weekly Trades</p>
                </div>
                <p className="text-3xl font-bold text-blue-400">{trophyStats.totalWeeklyTrades}</p>
                <p className="text-xs text-muted-foreground">This week</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Reports Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.2 }}
      >
        <Card className="bg-black/5">
          <CardHeader>
            <CardTitle className="text-xl flex items-center gap-2">
              <PieChart className="w-5 h-5 text-blue-400" />
              Trading Reports
            </CardTitle>
            <CardDescription>Performance analytics across all trading accounts</CardDescription>
          </CardHeader>
          <CardContent>
            {accounts.length === 0 ? (
              <div className="text-center py-8">
                <Clock className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-muted-foreground">No accounts configured yet</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Aggregated Trading Report from All Accounts */}
                <TradingReportCard 
                  selectedTimeframe={selectedTimeframe}
                  timeframeOptions={timeframeOptions}
                  onTimeframeChange={setSelectedTimeframe}
                  tradingReport={aggregatedReport}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Account Balance Cards */}
      {(() => {
        console.log('🔍 Balance cards render check:', { 
          accountsBalanceLength: accountsBalance.length, 
          balanceLoading, 
          balanceError: balanceError?.message,
          shouldShowCards: accountsBalance.length > 0 
        });
        return accountsBalance.length > 0;
      })() && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="space-y-6"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h2 className="text-2xl font-bold text-white">Account Balance Reports</h2>
              <Badge variant="secondary" className="text-xs">
                {accountsBalance.length} account{accountsBalance.length !== 1 ? 's' : ''}
              </Badge>
            </div>
            
            {/* Expand/Collapse All Button */}
            <Button
              onClick={toggleAllCards}
              variant="outline"
              size="sm"
              className="flex items-center gap-2 bg-slate-800/50 border-slate-600 hover:bg-slate-700/50 text-slate-300 hover:text-white"
            >
              {allExpanded ? (
                <>
                  <Minimize2 className="w-4 h-4" />
                  Collapse All
                </>
              ) : (
                <>
                  <Expand className="w-4 h-4" />
                  Expand All
                </>
              )}
            </Button>
          </div>
          
          <div className="space-y-3">
            {accountsBalance.map((accountData) => (
              <AccountBalanceCard 
                key={`${accountData.accountName}-${allExpanded ? 'expanded' : 'collapsed'}`}
                data={accountData}
                initialCollapsed={!allExpanded}
              />
            ))}
          </div>
        </motion.div>
      )}

      {/* Loading state for balance data */}
      {balanceLoading && accountsBalance.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
        >
          <Card className="bg-black/5">
            <CardContent className="p-8">
              <div className="text-center">
                <div className="animate-spin w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full mx-auto mb-4"></div>
                <p className="text-muted-foreground">Loading account balance data...</p>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Error state for balance data */}
      {balanceError && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
        >
          <Card className="bg-red-500/10 border-red-500/30">
            <CardContent className="p-8">
              <div className="text-center">
                <p className="text-red-400 mb-2">Error loading balance data:</p>
                <p className="text-sm text-muted-foreground">{balanceError.message}</p>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Debug info */}
      {!balanceLoading && !balanceError && accountsBalance.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.4 }}
        >
          <Card className="bg-yellow-500/10 border-yellow-500/30">
            <CardContent className="p-8">
              <div className="text-center">
                <p className="text-yellow-400 mb-2">No balance data received</p>
                <p className="text-sm text-muted-foreground">Check console logs for API response details</p>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}
    </div>
  );
}

// Trading Report Component
function TradingReportCard({ 
  account, 
  selectedTimeframe, 
  timeframeOptions, 
  onTimeframeChange, 
  tradingReport 
}: { 
  account?: Account;
  selectedTimeframe: string;
  timeframeOptions: Array<{ value: string; label: string }>;
  onTimeframeChange: (value: string) => void;
  tradingReport?: TradingReport;
}) {
  if (!tradingReport) {
    return (
      <Card className="bg-gradient-to-br from-slate-900/50 to-slate-800/30 border-slate-700/50">
        <CardContent className="p-6">
          <div className="text-center">
            <p className="text-muted-foreground">Loading trading data...</p>
          </div>
        </CardContent>
      </Card>
    );
  }
  
  const report = tradingReport;
  const totalTrades = (report.winCount || 0) + (report.lossCount || 0);
  
  return (
    <div className="space-y-4">
      {/* Timeframe Selection */}
      <Card className="bg-gradient-to-br from-slate-900/50 to-slate-800/30 border-slate-700/50">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg flex items-center gap-2">
            <Clock className="w-5 h-5 text-blue-400" />
            Trading Report - {report.timeframe}
          </CardTitle>
          <div className="flex flex-wrap gap-2 mt-3">
            {timeframeOptions.map((option) => (
              <Button
                key={option.value}
                variant={selectedTimeframe === option.value ? "default" : "outline"}
                size="sm"
                onClick={() => onTimeframeChange(option.value)}
                className="text-xs px-3 py-1 h-8 min-w-[50px]"
              >
                {option.label}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="text-center p-4 bg-slate-800/30 rounded-lg">
              <p className="text-sm text-muted-foreground mb-2">Total P&L</p>
              <p className={`text-2xl font-bold ${
                (report.totalPnL || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
              }`}>
                {(report.totalPnL || 0) >= 0 ? '+' : ''}{(report.totalPnL || 0).toLocaleString('en-US', {
                  style: 'currency',
                  currency: 'USD'
                })}
              </p>
              <p className="text-xs text-muted-foreground">
                {report.totalROI >= 0 ? '+' : ''}{report.totalROI?.toFixed(2) || '0.00'}% ROI
              </p>
            </div>
            
            <div className="text-center p-4 bg-slate-800/30 rounded-lg">
              <p className="text-sm text-muted-foreground mb-2">Trades</p>
              <p className="text-2xl font-bold text-white">{totalTrades}</p>
              <p className="text-xs text-muted-foreground">
                <span className="text-emerald-400">{report.winCount || 0}W</span> / <span className="text-red-400">{report.lossCount || 0}L</span>
              </p>
            </div>
            
            <div className="text-center p-4 bg-slate-800/30 rounded-lg">
              <p className="text-sm text-muted-foreground mb-2">PnL Ratio</p>
              <p className="text-2xl font-bold text-blue-400">{report.pnlRatio === Infinity ? '∞' : (report.pnlRatio?.toFixed(2) || '0.00')}</p>
              <p className="text-xs text-muted-foreground">
                Profit/Loss
              </p>
            </div>
            
            <div className="text-center p-4 bg-slate-800/30 rounded-lg">
              <p className="text-sm text-muted-foreground mb-2">Win P&L</p>
              <p className="text-xl font-bold text-emerald-400">
                {(report.winPnL || 0).toLocaleString('en-US', {
                  style: 'currency',
                  currency: 'USD'
                })}
              </p>
              <p className="text-xs text-muted-foreground">{report.winROI?.toFixed(2) || '0.00'}% ROI</p>
            </div>
            
            <div className="text-center p-4 bg-slate-800/30 rounded-lg">
              <p className="text-sm text-muted-foreground mb-2">Loss P&L</p>
              <p className="text-xl font-bold text-red-400">
                {(report.lossPnL || 0).toLocaleString('en-US', {
                  style: 'currency',
                  currency: 'USD'
                })}
              </p>
              <p className="text-xs text-muted-foreground">{report.lossROI?.toFixed(2) || '0.00'}% ROI</p>
            </div>
          </div>
        </CardContent>
      </Card>


    </div>
  );
}



