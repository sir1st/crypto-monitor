import type { IncomingMessage, Server } from "http";
import type { Duplex } from "stream";
import { WebSocket, WebSocketServer } from "ws";
import { URL } from "url";
import { aggregateWalletBalances } from "./trading";
import { onAlertTriggered } from "./alerts";
import { log } from "./vite";

const WS_PATH = "/ws";
const WALLET_POLL_MS = 5_000;

type Topic = "wallet" | "alerts";
const TOPICS: Topic[] = ["wallet", "alerts"];

interface Client extends WebSocket {
  subscriptions: Set<Topic>;
}

function send(socket: WebSocket, payload: unknown) {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

export function setupWebSocket(server: Server) {
  // noServer so upgrades on other paths (Vite's HMR socket in dev) are left for
  // whichever listener owns them.
  const wss = new WebSocketServer({ noServer: true });

  server.on("upgrade", (req: IncomingMessage, socket: Duplex, head: Buffer) => {
    let pathname: string;
    try {
      pathname = new URL(req.url ?? "", `http://${req.headers.host ?? "localhost"}`).pathname;
    } catch {
      return;
    }

    // Not ours — leave it for any other upgrade listener.
    if (pathname !== WS_PATH) return;

    wss.handleUpgrade(req, socket, head, (ws) => {
      const client = ws as Client;
      client.subscriptions = new Set();
      wss.emit("connection", client, req);
    });
  });

  wss.on("connection", (ws: WebSocket) => {
    const client = ws as Client;
    log("socket connected", "ws");

    send(client, { op: "ready" });

    client.on("message", async (raw) => {
      let message: { op?: string; args?: unknown };
      try {
        message = JSON.parse(raw.toString());
      } catch {
        return send(client, { op: "error", message: "Expected JSON" });
      }

      switch (message.op) {
        case "subscribe": {
          const requested = (Array.isArray(message.args) ? message.args : []).filter(
            (topic): topic is Topic => TOPICS.includes(topic as Topic),
          );
          for (const topic of requested) client.subscriptions.add(topic);
          send(client, { op: "subscribe", success: true, args: [...client.subscriptions] });

          if (client.subscriptions.has("wallet")) {
            send(client, await walletSnapshot());
          }
          break;
        }

        case "unsubscribe": {
          for (const topic of Array.isArray(message.args) ? message.args : []) {
            client.subscriptions.delete(topic as Topic);
          }
          send(client, { op: "unsubscribe", success: true, args: [...client.subscriptions] });
          break;
        }

        default:
          send(client, { op: "error", message: `Unknown op "${message.op}"` });
      }
    });

    client.on("close", () => log("socket closed", "ws"));
  });

  /** Push triggered alerts to anyone subscribed. */
  const unsubscribeAlerts = onAlertTriggered((alert, price) => {
    for (const ws of wss.clients) {
      const client = ws as Client;
      if (client.subscriptions?.has("alerts")) {
        send(client, { topic: "alert", creationTime: Date.now(), data: { alert, price } });
      }
    }
  });

  /**
   * One Bybit fan-out per tick shared by every subscriber, rather than a fetch
   * per client.
   */
  const timer = setInterval(async () => {
    const subscribers = [...wss.clients].filter(
      (ws) => (ws as Client).subscriptions?.has("wallet") && ws.readyState === WebSocket.OPEN,
    );
    if (subscribers.length === 0) return;

    const snapshot = await walletSnapshot();
    for (const ws of subscribers) send(ws, snapshot);
  }, WALLET_POLL_MS);
  timer.unref();

  wss.on("close", () => {
    clearInterval(timer);
    unsubscribeAlerts();
  });

  log("websocket server listening on /ws", "ws");
  return wss;
}

async function walletSnapshot() {
  try {
    const balances = await aggregateWalletBalances();

    if (balances.length === 0) {
      return {
        topic: "wallet-error",
        creationTime: Date.now(),
        error: true,
        message: "No Bybit account returned a balance. Add credentials under Accounts.",
      };
    }

    return {
      topic: "wallet",
      creationTime: Date.now(),
      data: balances,
      accountCount: balances.length,
    };
  } catch (error) {
    return {
      topic: "wallet-error",
      creationTime: Date.now(),
      error: true,
      message: (error as Error).message,
    };
  }
}
