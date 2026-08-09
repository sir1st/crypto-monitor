import { RestClientV5, type CategoryV5 } from "bybit-api";
import { getServerTime } from "./market";

/**
 * Authenticated Bybit reads. Every function returns `null` on failure rather
 * than throwing: callers fan out across several accounts and a single bad key
 * must not fail the whole aggregate.
 */

export interface Credentials {
  apiKey: string;
  apiSecret: string;
}

function createClient(credentials?: Credentials) {
  return new RestClientV5({
    key: credentials?.apiKey ?? process.env.BYBIT_API_KEY,
    secret: credentials?.apiSecret ?? process.env.BYBIT_API_SECRET,
    testnet: process.env.BYBIT_TESTNET === "true",
  });
}

function logFailure(action: string, error: unknown) {
  const err = error as { message?: string; body?: unknown };
  const geoBlocked =
    typeof err.body === "string" &&
    err.body.includes("CloudFront") &&
    err.body.includes("block access from your country");

  console.error(
    geoBlocked
      ? `${action}: Bybit blocks authenticated access from this region.`
      : `${action}: ${err.message ?? "unknown error"}`,
  );
}

export async function getWalletBalance(credentials?: Credentials) {
  try {
    const response = await createClient(credentials).getWalletBalance({ accountType: "UNIFIED" });
    if (response.retCode !== 0) {
      console.error(`Wallet balance rejected: ${response.retMsg}`);
      return null;
    }
    return response.result;
  } catch (error) {
    logFailure("Fetching wallet balance", error);
    return null;
  }
}

export async function getPositions(
  category: CategoryV5 = "linear",
  credentials?: Credentials,
) {
  try {
    const response = await createClient(credentials).getPositionInfo({
      category,
      settleCoin: "USDT",
    });
    if (response.retCode !== 0) {
      console.error(`Positions rejected: ${response.retMsg}`);
      return null;
    }
    return response.result.list;
  } catch (error) {
    logFailure("Fetching positions", error);
    return null;
  }
}

export async function getClosedPnL(options: {
  category?: CategoryV5;
  limit?: number;
  credentials?: Credentials;
  startTime?: number;
  endTime?: number;
}) {
  const { category = "linear", limit = 100, credentials, startTime, endTime } = options;

  try {
    const response = await createClient(credentials).getClosedPnL({
      category,
      limit,
      ...(startTime ? { startTime } : {}),
      ...(endTime ? { endTime } : {}),
    });
    if (response.retCode !== 0) {
      console.error(`Closed P&L rejected: ${response.retMsg}`);
      return null;
    }
    return response.result;
  } catch (error) {
    logFailure("Fetching closed P&L", error);
    return null;
  }
}

export async function getExecutionList(options: {
  category?: CategoryV5;
  limit?: number;
  credentials?: Credentials;
}) {
  const { category = "linear", limit = 50, credentials } = options;

  try {
    const response = await createClient(credentials).getExecutionList({ category, limit });
    if (response.retCode !== 0) {
      console.error(`Execution list rejected: ${response.retMsg}`);
      return null;
    }
    return response.result.list;
  } catch (error) {
    logFailure("Fetching execution list", error);
    return null;
  }
}

/**
 * Probes connectivity, distinguishing "the network is fine but these keys are
 * not usable here" from "Bybit is unreachable at all".
 */
export async function testApiConnection(credentials?: Credentials) {
  try {
    await getServerTime();
  } catch (error) {
    return {
      success: false,
      publicAccess: false,
      message: (error as Error).message,
    };
  }

  try {
    const response = await createClient(credentials).getServerTime();
    return {
      success: response.retCode === 0,
      publicAccess: true,
      message:
        response.retCode === 0
          ? "Connected to Bybit with these credentials."
          : response.retMsg,
    };
  } catch (error) {
    const err = error as { body?: unknown; message?: string };
    const geoBlocked = typeof err.body === "string" && err.body.includes("CloudFront");

    return {
      success: false,
      publicAccess: true,
      message: geoBlocked
        ? "Public market data works, but Bybit blocks authenticated requests from this region."
        : `Authenticated request failed: ${err.message ?? "unknown error"}`,
    };
  }
}
