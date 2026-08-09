import { useQuery } from "@tanstack/react-query";

export interface MarketHoursData {
  name: string;
  timeZone: string;
  abbreviation: string;
  status: "open" | "closed";
  openTime: string;
  closeTime: string;
  currentTime: string;
}

export interface MarketHoursResponse {
  success: boolean;
  source: "bybit" | "local";
  timestamp: number;
  iso: string;
  markets: MarketHoursData[];
}

export interface ServerTimeResponse {
  success: boolean;
  serverTime: { timestamp: number; iso: string };
}

const REFETCH_MS = 60_000;

/** Market open/closed status. The default query function fetches queryKey[0]. */
export function useMarketHours() {
  return useQuery<MarketHoursResponse, Error>({
    queryKey: ["/api/market-hours"],
    refetchInterval: REFETCH_MS,
  });
}

export function useServerTime() {
  return useQuery<ServerTimeResponse, Error>({
    queryKey: ["/api/server-time"],
    refetchInterval: REFETCH_MS,
  });
}
