import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { motion } from "framer-motion";
import { Target, TrendingUp, Plus, Calendar, Activity } from 'lucide-react';

interface Account {
  id: number;
  balance: number;
  status: 'full' | 'growing';
}

interface WeeklyResult {
  week: number;
  totalWealth: number;
  weeklyGains: number;
  accountCount: number;
  fullAccounts: number;
  growingAccounts: number;
  accounts: Account[];
}

/**
 * Compound growth projection across multiple accounts: full accounts throw off a
 * weekly return, those gains fill the next account, and each account that
 * reaches the target is treated as full from then on.
 */
export default function CalculatorPage() {
  const [initialAmount] = useState(1000000); // Target size per account
  const [startingAccounts, setStartingAccounts] = useState(1);
  const [weeklyReturn, setWeeklyReturn] = useState(10);
  const [weeks, setWeeks] = useState(52);
  const [compoundResults, setCompoundResults] = useState<WeeklyResult[]>([]);

  const calculateCompounding = () => {
    // Initialize starting accounts
    let accounts: Account[] = [];
    for (let i = 1; i <= startingAccounts; i++) {
      accounts.push({ 
        id: i, 
        balance: initialAmount, 
        status: 'full' // Starting accounts are considered full
      });
    }
    
    let weeklyResults: WeeklyResult[] = [];
    let nextAccountId = startingAccounts + 1;
    
    for (let week = 1; week <= weeks; week++) {
      let totalWeeklyGains = 0;
      let newAccounts: Account[] = [];
      
      // Calculate gains from all full accounts
      const fullAccounts = accounts.filter(acc => acc.status === 'full');
      const growingAccounts = accounts.filter(acc => acc.status === 'growing');
      
      // Each full account generates weekly return
      let totalFullAccountGains = 0;
      fullAccounts.forEach(account => {
        const weeklyGain = account.balance * (weeklyReturn / 100);
        totalFullAccountGains += weeklyGain;
        totalWeeklyGains += weeklyGain;
      });
      
      // Copy all full accounts (they stay at $1M)
      newAccounts = fullAccounts.map(acc => ({ ...acc }));
      
      // Handle growing accounts
      let totalGainsToDistribute = totalFullAccountGains;
      
      if (growingAccounts.length > 0) {
        // Add gains to the growing account(s)
        growingAccounts.forEach(account => {
          const newBalance = account.balance + totalGainsToDistribute;
          totalGainsToDistribute = 0; // All gains go to first growing account
          
          if (newBalance >= 1000000) {
            // Account reached $1M, excess goes to new account
            const excess = newBalance - 1000000;
            
            newAccounts.push({
              ...account,
              balance: 1000000,
              status: 'full'
            });
            
            if (excess > 0) {
              newAccounts.push({
                id: nextAccountId++,
                balance: excess,
                status: 'growing'
              });
            }
          } else {
            // Account continues growing
            newAccounts.push({
              ...account,
              balance: newBalance,
              status: 'growing'
            });
          }
        });
      } else if (totalFullAccountGains > 0) {
        // No growing accounts, create new one with all gains
        newAccounts.push({
          id: nextAccountId++,
          balance: totalFullAccountGains,
          status: 'growing'
        });
      }
      
      accounts = newAccounts;
      
      // Calculate total wealth
      const totalWealth = accounts.reduce((sum, acc) => sum + acc.balance, 0);
      const fullAccountCount = accounts.filter(acc => acc.status === 'full').length;
      const growingAccountsCount = accounts.filter(acc => acc.status === 'growing').length;
      
      weeklyResults.push({
        week,
        totalWealth,
        weeklyGains: totalWeeklyGains,
        accountCount: accounts.length,
        fullAccounts: fullAccountCount,
        growingAccounts: growingAccountsCount,
        accounts: [...accounts]
      });
    }
    
    setCompoundResults(weeklyResults);
  };
  useEffect(() => {
    calculateCompounding();
  }, [startingAccounts, weeklyReturn, weeks]);

  const formatCurrency = (amount: number) => {
    if (amount >= 1000000000) {
      return `$${(amount / 1000000000).toFixed(2)}B`;
    } else if (amount >= 1000000) {
      return `$${(amount / 1000000).toFixed(2)}M`;
    } else if (amount >= 1000) {
      return `$${(amount / 1000).toFixed(0)}K`;
    }
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  const formatLargeCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  // Helper functions for compound calculator
  const getKeyMilestones = () => {
    const oneYear = compoundResults[51]; // Week 52
    const fiveYears = compoundResults[259]; // Week 260 (5 years)
    const current = compoundResults[compoundResults.length - 1];
    
    return { oneYear, fiveYears, current };
  };

  const { oneYear, fiveYears, current } = getKeyMilestones();
  const weeklyGainPerAccount = initialAmount * (weeklyReturn / 100);
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white p-4 sm:p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="max-w-4xl mx-auto"
      >
        <div className="text-center mb-8">
          <motion.div
            className="flex items-center justify-center gap-3 mb-4"
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <div className="p-3 bg-gradient-to-r from-purple-500 to-pink-600 rounded-full">
              <Target className="text-white" size={28} />
            </div>
            <h1 className="text-4xl lg:text-5xl font-bold bg-gradient-to-r from-white via-cyan-200 to-blue-400 bg-clip-text text-transparent">
              Compound Growth
            </h1>
          </motion.div>
          <p className="text-slate-300 text-lg">Project multi-account compounding over time</p>
        </div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Card className="bg-gradient-to-br from-slate-900/90 to-slate-800/60 border-slate-700/50">
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-gradient-to-r from-purple-500 to-pink-600 rounded-lg">
                      <Target className="text-white" size={24} />
                    </div>
                    <div>
                      <CardTitle className="text-xl text-white">Multi-Account Wealth Calculator</CardTitle>
                      <CardDescription>Generate {weeklyReturn}% weekly returns on full $1M accounts</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                
                <CardContent className="space-y-6">
                  {/* Controls */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">
                        <Plus className="w-4 h-4 inline mr-1" />
                        Starting Accounts
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={startingAccounts}
                        onChange={(e) => setStartingAccounts(Number(e.target.value))}
                        className="w-full p-3 bg-slate-800/70 border border-slate-600/70 rounded-lg focus:ring-2 focus:ring-purple-400 focus:border-transparent text-white text-lg transition-all duration-300"
                      />
                    </div>
                    
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">
                        Weekly Return % (per full account)
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="100"
                        step="0.5"
                        value={weeklyReturn}
                        onChange={(e) => setWeeklyReturn(Number(e.target.value))}
                        className="w-full p-3 bg-slate-800/70 border border-slate-600/70 rounded-lg focus:ring-2 focus:ring-purple-400 focus:border-transparent text-white text-lg transition-all duration-300"
                      />
                    </div>
                    
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">
                        Time Period (Weeks)
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="520"
                        value={weeks}
                        onChange={(e) => setWeeks(Number(e.target.value))}
                        className="w-full p-3 bg-slate-800/70 border border-slate-600/70 rounded-lg focus:ring-2 focus:ring-purple-400 focus:border-transparent text-white text-lg transition-all duration-300"
                      />
                    </div>
                  </div>

                  {/* Current Strategy Display */}
                  <Card className="bg-slate-800/50 border-slate-600/50">
                    <CardContent className="p-4">
                      <h3 className="text-lg font-semibold text-white mb-3">Strategy Overview</h3>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <div className="text-center p-3 bg-slate-700/50 rounded-lg border border-emerald-500/30">
                          <div className="text-lg font-bold text-emerald-400">{startingAccounts}</div>
                          <div className="text-xs text-slate-400">Starting Accounts</div>
                        </div>
                        <div className="text-center p-3 bg-slate-700/50 rounded-lg border border-blue-500/30">
                          <div className="text-lg font-bold text-blue-400">{formatCurrency(initialAmount)}</div>
                          <div className="text-xs text-slate-400">Per Account</div>
                        </div>
                        <div className="text-center p-3 bg-slate-700/50 rounded-lg border border-purple-500/30">
                          <div className="text-lg font-bold text-purple-400">{formatCurrency(weeklyGainPerAccount)}</div>
                          <div className="text-xs text-slate-400">Weekly Gain/Account</div>
                        </div>
                        <div className="text-center p-3 bg-slate-700/50 rounded-lg border border-orange-500/30">
                          <div className="text-lg font-bold text-orange-400">{formatCurrency(startingAccounts * initialAmount)}</div>
                          <div className="text-xs text-slate-400">Starting Capital</div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Key Projections */}
                  {current && (
                    <motion.div 
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="space-y-6"
                    >
                      <div>
                        <h3 className="text-xl font-bold text-white mb-4">Wealth Projections</h3>
                        
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                          {oneYear && (
                            <div className="bg-gradient-to-r from-blue-500/20 to-cyan-600/20 border border-blue-500/30 text-white p-4 rounded-xl">
                              <div className="flex items-center gap-2 mb-2">
                                <Calendar className="w-5 h-5" />
                                <span className="text-sm font-medium">1 Year (52 weeks)</span>
                              </div>
                              <div className="text-xl font-bold mb-1">{formatCurrency(oneYear.totalWealth)}</div>
                              <div className="text-sm text-slate-300">{oneYear.fullAccounts} full + {oneYear.growingAccounts} growing</div>
                              <div className="text-xs text-slate-400">{formatLargeCurrency(oneYear.totalWealth)}</div>
                            </div>
                          )}
                          
                          {fiveYears && (
                            <div className="bg-gradient-to-r from-purple-500/20 to-pink-600/20 border border-purple-500/30 text-white p-4 rounded-xl">
                              <div className="flex items-center gap-2 mb-2">
                                <TrendingUp className="w-5 h-5" />
                                <span className="text-sm font-medium">5 Years (260 weeks)</span>
                              </div>
                              <div className="text-xl font-bold mb-1">{formatCurrency(fiveYears.totalWealth)}</div>
                              <div className="text-sm text-slate-300">{fiveYears.fullAccounts} full + {fiveYears.growingAccounts} growing</div>
                              <div className="text-xs text-slate-400">{formatLargeCurrency(fiveYears.totalWealth)}</div>
                            </div>
                          )}
                          
                          <div className="bg-gradient-to-r from-emerald-500/20 to-green-600/20 border border-emerald-500/30 text-white p-4 rounded-xl">
                            <div className="flex items-center gap-2 mb-2">
                              <Target className="w-5 h-5" />
                              <span className="text-sm font-medium">Current Period ({weeks} weeks)</span>
                            </div>
                            <div className="text-xl font-bold mb-1">{formatCurrency(current.totalWealth)}</div>
                            <div className="text-sm text-slate-300">{current.fullAccounts} full + {current.growingAccounts} growing</div>
                            <div className="text-xs text-slate-400">{formatLargeCurrency(current.totalWealth)}</div>
                          </div>
                        </div>

                        {/* Growth Stats */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                          <div className="bg-slate-800/50 border border-slate-600/50 p-4 rounded-lg text-center">
                            <div className="text-lg font-bold text-white">{formatCurrency(current.weeklyGains)}</div>
                            <div className="text-xs text-slate-400">Current Weekly Gains</div>
                          </div>
                          <div className="bg-slate-800/50 border border-slate-600/50 p-4 rounded-lg text-center">
                            <div className="text-lg font-bold text-blue-400">
                              {((current.totalWealth / (startingAccounts * initialAmount) - 1) * 100).toFixed(0)}%
                            </div>
                            <div className="text-xs text-slate-400">Total Return</div>
                          </div>
                          <div className="bg-slate-800/50 border border-slate-600/50 p-4 rounded-lg text-center">
                            <div className="text-lg font-bold text-emerald-400">
                              {(current.totalWealth / (startingAccounts * initialAmount)).toFixed(1)}x
                            </div>
                            <div className="text-xs text-slate-400">Wealth Multiplier</div>
                          </div>
                          <div className="bg-slate-800/50 border border-slate-600/50 p-4 rounded-lg text-center">
                            <div className="text-lg font-bold text-purple-400">
                              {current.fullAccounts}
                            </div>
                            <div className="text-xs text-slate-400">Full $1M Accounts</div>
                          </div>
                        </div>

                        {/* Weekly Earnings Power */}
                        <Card className="bg-gradient-to-r from-yellow-500/10 to-orange-500/10 border border-yellow-500/30">
                          <CardContent className="p-4">
                            <h4 className="text-lg font-semibold text-white mb-2">Current Earning Power</h4>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                              <div className="text-center">
                                <div className="text-xl font-bold text-yellow-400">{formatCurrency(current.fullAccounts * weeklyGainPerAccount)}</div>
                                <div className="text-sm text-slate-400">Per Week from Full Accounts</div>
                              </div>
                              <div className="text-center">
                                <div className="text-xl font-bold text-orange-400">{formatCurrency(current.fullAccounts * weeklyGainPerAccount * 4)}</div>
                                <div className="text-sm text-slate-400">Per Month</div>
                              </div>
                              <div className="text-center">
                                <div className="text-xl font-bold text-red-400">{formatCurrency(current.fullAccounts * weeklyGainPerAccount * 52)}</div>
                                <div className="text-sm text-slate-400">Per Year</div>
                              </div>
                              <div className="text-center">
                                <div className="text-xl font-bold text-purple-400">{current.fullAccounts > 0 ? Math.floor(1000000 / (current.fullAccounts * weeklyGainPerAccount)) : 'N/A'}</div>
                                <div className="text-sm text-slate-400">Weeks to New $1M</div>
                              </div>
                            </div>
                          </CardContent>
                        </Card>

                        {/* Account Breakdown */}
                        <Card className="bg-slate-800/50 border border-slate-600/50">
                          <CardContent className="p-4">
                            <h4 className="text-lg font-semibold text-white mb-3">Current Account Breakdown</h4>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 max-h-64 overflow-y-auto">
                              {current.accounts.map((account) => (
                                <div key={account.id} className={`p-3 rounded border ${account.status === 'full' ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-yellow-500/10 border-yellow-500/30'}`}>
                                  <div className="flex items-center gap-2 mb-1">
                                    <div className="text-sm text-slate-300">Account #{account.id}</div>
                                    {account.status === 'full' ? (
                                      <Badge variant="secondary" className="text-xs bg-emerald-500/20 text-emerald-400 border-emerald-500/30">FULL</Badge>
                                    ) : (
                                      <Badge variant="secondary" className="text-xs bg-yellow-500/20 text-yellow-400 border-yellow-500/30 flex items-center gap-1">
                                        <Activity className="w-3 h-3" />
                                        GROWING
                                      </Badge>
                                    )}
                                  </div>
                                  <div className="text-lg font-bold text-emerald-400">{formatCurrency(account.balance)}</div>
                                  <div className="text-xs text-slate-400">{formatLargeCurrency(account.balance)}</div>
                                  {account.status === 'growing' && (
                                    <div className="text-xs text-slate-400 mt-1">
                                      {((account.balance / 1000000) * 100).toFixed(1)}% to $1M
                                    </div>
                                  )}
                                  {account.status === 'full' && (
                                    <div className="text-xs text-emerald-400 mt-1">
                                      Generates {formatCurrency(weeklyGainPerAccount)}/week
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </CardContent>
                        </Card>
                      </div>
                    </motion.div>
                  )}
                </CardContent>
              </Card>
            </motion.div>
      </motion.div>
    </div>
  );
}
