import { useEffect, useRef, useState } from "react";

interface WalletEntry {
  accountIMRate: string;
  accountMMRate: string;
  totalEquity: string;
  totalWalletBalance: string;
  totalMarginBalance: string;
  totalAvailableBalance: string;
  totalPerpUPL: string;
  totalInitialMargin: string;
  totalMaintenanceMargin: string;
  accountLTV: string;
  accountType: string;
  accountName?: string;
  accountId?: number;
  coin: Array<{
    coin: string;
    equity: string;
    usdValue: string;
    walletBalance: string;
    availableToWithdraw: string;
    unrealisedPnl: string;
    [key: string]: unknown;
  }>;
}

interface WalletStreamData {
  topic: string;
  creationTime: number;
  data: WalletEntry[];
  accountCount?: number;
}

export interface WalletStreamState {
  isConnected: boolean;
  isSubscribed: boolean;
  data: WalletStreamData | null;
  error: string | null;
}

const RECONNECT_DELAY_MS = 3_000;

/**
 * Subscribes to the wallet topic on /ws. The socket is unauthenticated, so it
 * connects as soon as the component mounts and reconnects on drop.
 */
export function useWalletStream(): WalletStreamState {
  const [state, setState] = useState<WalletStreamState>({
    isConnected: false,
    isSubscribed: false,
    data: null,
    error: null,
  });

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guards the reconnect loop against firing after unmount.
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;

    const connect = () => {
      if (!activeRef.current) return;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/ws`;

      let socket: WebSocket;
      try {
        socket = new WebSocket(url);
      } catch (error) {
        setState((prev) => ({ ...prev, error: (error as Error).message }));
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        setState((prev) => ({ ...prev, isConnected: true, error: null }));
        socket.send(JSON.stringify({ op: "subscribe", args: ["wallet"] }));
      };

      socket.onmessage = (event) => {
        let message: Record<string, unknown>;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }

        if (message.op === "subscribe") {
          setState((prev) => ({ ...prev, isSubscribed: true }));
          return;
        }

        if (message.topic === "wallet") {
          setState((prev) => ({
            ...prev,
            data: message as unknown as WalletStreamData,
            error: null,
          }));
          return;
        }

        if (message.topic === "wallet-error") {
          setState((prev) => ({ ...prev, error: String(message.message ?? "Wallet error") }));
        }
      };

      socket.onerror = () => {
        setState((prev) => ({ ...prev, error: "WebSocket connection error" }));
      };

      socket.onclose = () => {
        setState((prev) => ({ ...prev, isConnected: false, isSubscribed: false }));
        if (activeRef.current) {
          reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
    };

    connect();

    return () => {
      activeRef.current = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  return state;
}
