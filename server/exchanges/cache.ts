/**
 * Per-account response cache for exchange reads.
 *
 * Every dashboard tab polls on its own timer, so without a shared cache the
 * exchange load scales with the number of open tabs. Entries are keyed per
 * account and request, concurrent identical requests share one in-flight
 * promise, and a failed fetch serves the last good value (stale) instead of an
 * empty result, then waits {@link FAILURE_RETRY_MS} before trying again.
 */

interface Entry {
  value: unknown;
  fetchedAt: number;
}

const FAILURE_RETRY_MS = 10_000;

const entries = new Map<string, Entry>();
const inflight = new Map<string, Promise<unknown>>();
const failedAt = new Map<string, number>();

export async function cachedFetch<T>(
  key: string,
  ttlMs: number,
  fetcher: () => Promise<T>,
  fallback: T,
  label: string,
): Promise<T> {
  const now = Date.now();
  const entry = entries.get(key);
  if (entry && now - entry.fetchedAt < ttlMs) return entry.value as T;

  // Recently failed: don't hammer the exchange, serve stale (or the fallback).
  const lastFailure = failedAt.get(key);
  if (lastFailure !== undefined && now - lastFailure < FAILURE_RETRY_MS) {
    return entry ? (entry.value as T) : fallback;
  }

  const pending = inflight.get(key);
  if (pending) return pending as Promise<T>;

  const promise = (async () => {
    try {
      const value = await fetcher();
      entries.set(key, { value, fetchedAt: Date.now() });
      failedAt.delete(key);
      return value;
    } catch (error) {
      failedAt.set(key, Date.now());
      const message = error instanceof Error ? error.message : String(error);
      const age = entry ? `${Math.round((Date.now() - entry.fetchedAt) / 1000)}s old` : "none";
      console.error(`${label} failed (serving cached: ${age}): ${message}`);
      return entry ? (entry.value as T) : fallback;
    } finally {
      inflight.delete(key);
    }
  })();
  inflight.set(key, promise);
  return promise;
}

export function cacheStats() {
  return { entries: entries.size, inflight: inflight.size, failing: failedAt.size };
}
