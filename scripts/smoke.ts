#!/usr/bin/env node
import dotenv from "dotenv";

dotenv.config();

/**
 * End-to-end check against a running server. The API is unauthenticated, so
 * every route is exercised directly.
 *
 *   npm run dev      # in one terminal
 *   npm run smoke    # in another
 */

const baseUrl = (process.env.SMOKE_URL ?? "http://127.0.0.1:5000").replace(/\/$/, "");

let passed = 0;
let failed = 0;

function report(name: string, ok: boolean, detail = "") {
  if (ok) {
    passed += 1;
    console.log(`  PASS  ${name}${detail ? ` — ${detail}` : ""}`);
  } else {
    failed += 1;
    console.log(`  FAIL  ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

async function call(method: string, path: string, body?: unknown) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  const text = await response.text();
  let payload: unknown = text;
  try {
    payload = text ? JSON.parse(text) : undefined;
  } catch {
    // Leave payload as raw text.
  }
  return { status: response.status, payload };
}

async function check(
  name: string,
  method: string,
  path: string,
  options: { body?: unknown; expect?: number | number[] } = {},
) {
  const expected = options.expect ?? 200;
  const allowed = Array.isArray(expected) ? expected : [expected];

  try {
    const { status, payload } = await call(method, path, options.body);
    const ok = allowed.includes(status);
    report(
      name,
      ok,
      ok
        ? `${status}`
        : `expected ${allowed.join("/")}, got ${status}: ${JSON.stringify(payload).slice(0, 160)}`,
    );
    return payload;
  } catch (error) {
    report(name, false, (error as Error).message);
    return undefined;
  }
}

async function main() {
  console.log(`\nSmoke test against ${baseUrl}\n`);

  console.log("Status");
  await check("GET /api/health", "GET", "/api/health");
  await check("GET /api/market-hours", "GET", "/api/market-hours");
  await check("GET /api/server-time", "GET", "/api/server-time");

  console.log("\nMarket data");
  const candles = (await check(
    "GET /api/market/candles",
    "GET",
    "/api/market/candles?symbol=BTCUSDT&interval=60&limit=5",
  )) as { candles?: unknown[] } | undefined;
  report(
    "candles come back non-empty",
    Array.isArray(candles?.candles) && candles!.candles!.length > 0,
    `${candles?.candles?.length ?? 0} candles`,
  );
  await check("GET /api/market/price", "GET", "/api/market/price?symbol=BTCUSDT");
  await check(
    "GET /api/market/candles rejects a bad interval",
    "GET",
    "/api/market/candles?symbol=BTCUSDT&interval=7m",
    { expect: 400 },
  );
  await check("GET /api/market/candles rejects a missing symbol", "GET", "/api/market/candles", {
    expect: 400,
  });

  console.log("\nAggregated views (empty without configured accounts)");
  await check("GET /api/bybit/positions", "GET", "/api/bybit/positions");
  await check("GET /api/trading-reports", "GET", "/api/trading-reports?timeframe=7");
  await check("GET /api/account-balance", "GET", "/api/account-balance");
  await check("GET /api/trophy-stats", "GET", "/api/trophy-stats");
  await check("GET /api/accounts", "GET", "/api/accounts");
  await check("GET /api/trading-reports rejects a bad timeframe", "GET", "/api/trading-reports?timeframe=0", {
    expect: 400,
  });

  console.log("\nAccounts");
  await check("POST /api/accounts rejects a missing apiSecret", "POST", "/api/accounts", {
    body: { name: "incomplete", exchange: "bybit", apiKey: "abc" },
    expect: 400,
  });
  await check("GET /api/accounts/:id for an unknown id is 404", "GET", "/api/accounts/999999/test", {
    expect: 404,
  });

  console.log("\nAlert lifecycle");
  const alert = (await check("POST /api/alerts", "POST", "/api/alerts", {
    body: { symbol: "BTCUSDT", direction: "above", price: 999_999, note: "smoke test" },
    expect: 201,
  })) as { id?: number } | undefined;
  await check("POST /api/alerts rejects an unknown symbol", "POST", "/api/alerts", {
    body: { symbol: "NOTAREALPAIR", direction: "above", price: 1 },
    expect: 400,
  });
  await check("POST /api/alerts rejects a negative price", "POST", "/api/alerts", {
    body: { symbol: "BTCUSDT", direction: "above", price: -5 },
    expect: 400,
  });
  await check("POST /api/alerts rejects a bad direction", "POST", "/api/alerts", {
    body: { symbol: "BTCUSDT", direction: "sideways", price: 100 },
    expect: 400,
  });
  await check("GET /api/alerts", "GET", "/api/alerts?status=active");
  if (alert?.id) {
    await check("POST /api/alerts/:id/cancel", "POST", `/api/alerts/${alert.id}/cancel`);
    await check(
      "POST /api/alerts/:id/cancel twice is 404",
      "POST",
      `/api/alerts/${alert.id}/cancel`,
      { expect: 404 },
    );
    await check("DELETE /api/alerts/:id", "DELETE", `/api/alerts/${alert.id}`, { expect: 204 });
    await check("DELETE /api/alerts/:id twice is 404", "DELETE", `/api/alerts/${alert.id}`, {
      expect: 404,
    });
  }

  console.log("\nStrategy lifecycle");
  const strategy = (await check("POST /api/strategies", "POST", "/api/strategies", {
    body: {
      name: "Smoke test strategy",
      symbol: "ETHUSDT",
      timeframe: "240",
      description: "Created by the smoke test",
      rules: { entry: "close > ma200", exit: "close < ma50", riskPercent: 1 },
    },
    expect: 201,
  })) as { id?: number } | undefined;
  await check("POST /api/strategies rejects a bad timeframe", "POST", "/api/strategies", {
    body: { name: "bad", symbol: "ETHUSDT", timeframe: "13" },
    expect: 400,
  });
  await check("GET /api/strategies", "GET", "/api/strategies");
  if (strategy?.id) {
    await check("GET /api/strategies/:id", "GET", `/api/strategies/${strategy.id}`);
    await check("PATCH /api/strategies/:id", "PATCH", `/api/strategies/${strategy.id}`, {
      body: { status: "active" },
    });
    await check("DELETE /api/strategies/:id", "DELETE", `/api/strategies/${strategy.id}`, {
      expect: 204,
    });
    await check("GET /api/strategies/:id after delete is 404", "GET", `/api/strategies/${strategy.id}`, {
      expect: 404,
    });
  }

  console.log("\nAI layer");
  const aiConfig = (await check("GET /api/ai/config", "GET", "/api/ai/config")) as
    | { configured?: boolean }
    | undefined;
  if (aiConfig?.configured) {
    await check("POST /api/ai/market", "POST", "/api/ai/market", {
      body: { symbol: "BTCUSDT", interval: "60", limit: 30 },
    });
  } else {
    // 503 is the correct answer when no provider key is configured.
    await check("POST /api/ai/market without a key is 503", "POST", "/api/ai/market", {
      body: { symbol: "BTCUSDT" },
      expect: 503,
    });
  }

  console.log(`\n${passed} passed, ${failed} failed\n`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((error) => {
  console.error("\nSmoke test could not run:", error.message);
  console.error(`Is the server up at ${baseUrl}? Start it with \`npm run dev\`.\n`);
  process.exit(1);
});
