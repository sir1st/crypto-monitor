/**
 * Binance IP-weight guard.
 *
 * The dashboard shares its outbound IP with the copy-trading bot, and Binance
 * meters request weight per IP (2400 per minute on USDⓈ-M futures). The bot's
 * reads and orders must win, so the dashboard backs off early:
 *
 *  - after every Binance response, read `x-mbx-used-weight-1m`; once it passes
 *    {@link WEIGHT_SOFT_LIMIT}, stop calling Binance until the minute window
 *    rolls over (callers serve cached data meanwhile);
 *  - on 429 / 418, stop until the exchange's `Retry-After` (or a conservative
 *    default when the header is missing).
 */

export const WEIGHT_SOFT_LIMIT = 1000;
const DEFAULT_429_BACKOFF_MS = 60_000;
const DEFAULT_418_BACKOFF_MS = 120_000;

let blockedUntil = 0;
let blockReason = "";
let lastUsedWeight: number | null = null;
let lastLoggedBlock = 0;

export class BinanceBudgetError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BinanceBudgetError";
  }
}

function header(headers: unknown, name: string): string | undefined {
  if (!headers || typeof headers !== "object") return undefined;
  for (const [key, value] of Object.entries(headers as Record<string, unknown>)) {
    if (key.toLowerCase() === name) return value == null ? undefined : String(value);
  }
  return undefined;
}

function block(until: number, reason: string, now: number): void {
  if (until <= blockedUntil) return;
  blockedUntil = until;
  blockReason = reason;
  if (now - lastLoggedBlock > 5_000) {
    lastLoggedBlock = now;
    console.warn(
      `[binance-guard] pausing Binance calls for ${Math.ceil((until - now) / 1000)}s: ${reason}`,
    );
  }
}

/** Throws {@link BinanceBudgetError} while Binance calls are paused. */
export function assertBinanceBudget(now = Date.now()): void {
  if (now < blockedUntil) {
    throw new BinanceBudgetError(
      `Binance paused for ${Math.ceil((blockedUntil - now) / 1000)}s (${blockReason})`,
    );
  }
}

/** Record the IP weight reported on a successful Binance response. */
export function recordBinanceResponse(headers: unknown, now = Date.now()): void {
  const used = Number(header(headers, "x-mbx-used-weight-1m"));
  if (!Number.isFinite(used)) return;
  lastUsedWeight = used;
  if (used > WEIGHT_SOFT_LIMIT) {
    // The weight counter is a per-minute window: resume at the next minute.
    const nextMinute = Math.floor(now / 60_000) * 60_000 + 60_000 + 1_000;
    block(nextMinute, `IP weight ${used}/min > ${WEIGHT_SOFT_LIMIT}`, now);
  }
}

/** Back off after a 429 / 418 from Binance, honouring Retry-After. */
export function recordBinanceFailure(error: unknown, headers: unknown, now = Date.now()): void {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  const banned = /\b418\b|-1003.*banned|IP banned/i.test(text);
  const throttled = banned || /\b429\b|-1003|Too many requests|DDoSProtection|RateLimitExceeded/i.test(text);
  if (!throttled) return;

  const retryAfter = Number(header(headers, "retry-after"));
  const fallback = banned ? DEFAULT_418_BACKOFF_MS : DEFAULT_429_BACKOFF_MS;
  const waitMs = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : fallback;
  block(now + waitMs, banned ? "418 IP banned" : "429 rate limited", now);
}

export function binanceGuardStatus(now = Date.now()) {
  return {
    paused: now < blockedUntil,
    resumeInMs: Math.max(0, blockedUntil - now),
    reason: now < blockedUntil ? blockReason : null,
    lastUsedWeight,
    softLimit: WEIGHT_SOFT_LIMIT,
  };
}
