import type { SupportedExchange } from "@shared/schema";

export interface ExchangeCredentials {
  apiKey: string;
  apiSecret: string;
  passphrase?: string | null;
}

export interface StandardPosition {
  exchange: SupportedExchange | string;
  accountName: string;
  accountId?: number;
  symbol: string;
  side: "Buy" | "Sell" | "long" | "short" | string;
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
}

export interface CoinBalance {
  coin: string;
  walletBalance: number;
  usdValue: number;
}

export interface StandardWallet {
  exchange: SupportedExchange | string;
  accountName: string;
  accountId?: number;
  accountType?: string;
  totalEquity: number;
  totalWalletBalance: number;
  totalPerpUPL: number;
  coin: CoinBalance[];
}

export interface StandardClosedTrade {
  symbol: string;
  closedPnl: string;
  cumEntryValue: string;
  leverage: string;
  closedSize?: string;
  avgEntryPrice?: string;
  createdTime: string; // epoch ms string
}

export interface ApiTestResult {
  success: boolean;
  publicAccess: boolean;
  message: string;
  exchange: string;
  serverTime?: number;
}
