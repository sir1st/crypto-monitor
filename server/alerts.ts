import { storage } from "./storage";
import { getLastPrices } from "./market";
import { log } from "./vite";
import type { Alert } from "@shared/schema";

const DEFAULT_INTERVAL_MS = 30_000;

type AlertListener = (alert: Alert, price: number) => void;

const listeners = new Set<AlertListener>();

/** Subscribe to trigger events — used to push alerts over the WebSocket. */
export function onAlertTriggered(listener: AlertListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function isTriggered(alert: Alert, price: number): boolean {
  return alert.direction === "above" ? price >= alert.price : price <= alert.price;
}

/**
 * Prices every active alert's symbol in one batch and marks the ones whose
 * threshold has been crossed. Returns the alerts that fired.
 */
export async function evaluateAlerts(): Promise<Alert[]> {
  const active = await storage.getActiveAlerts();
  if (active.length === 0) return [];

  const symbols = [...new Set(active.map((a) => a.symbol))];
  const prices = await getLastPrices(symbols);
  const fired: Alert[] = [];

  for (const alert of active) {
    const price = prices.get(alert.symbol);
    if (price === undefined || !isTriggered(alert, price)) continue;

    const updated = await storage.markAlertTriggered(alert.id, price);
    if (!updated) continue;

    fired.push(updated);
    log(
      `alert #${updated.id} triggered: ${updated.symbol} ${updated.direction} ${updated.price} (last ${price})`,
      "alerts",
    );

    for (const listener of listeners) {
      try {
        listener(updated, price);
      } catch (error) {
        console.error("Alert listener failed:", error);
      }
    }
  }

  return fired;
}

/**
 * Starts the polling loop. Failures are logged and swallowed so a transient
 * network problem never takes the process down.
 */
export function startAlertWatcher(intervalMs = DEFAULT_INTERVAL_MS) {
  const tick = async () => {
    try {
      await evaluateAlerts();
    } catch (error) {
      log(`alert evaluation failed: ${(error as Error).message}`, "alerts");
    }
  };

  void tick();
  const timer = setInterval(tick, intervalMs);
  timer.unref();

  log(`watching alerts every ${Math.round(intervalMs / 1000)}s`, "alerts");
  return () => clearInterval(timer);
}
