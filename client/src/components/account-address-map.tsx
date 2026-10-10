import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ExternalLink, Network } from "lucide-react";

const traderUrl = (address: string, ref: string) =>
  `https://hyperx.trade/hyperliquid/trader?address=${address}&ref=${ref}`;

interface ExchangeAccount {
  exchange: "bybit" | "bitget" | "binance" | "gate";
  accountId: string;
  /** Sizing note, e.g. "3000U · mirror 0.1x". */
  detail: string;
  /** live = copy trading is running; pending = staged (enabled=false), not trading yet. */
  status: "live" | "pending";
}

interface AccountAddressMapping {
  address: string;
  ref: string;
  accounts: ExchangeAccount[];
}

function exchangeBadgeStyle(exchange: string) {
  const ex = exchange.toLowerCase();
  return ex === "binance"
    ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
    : ex === "gate"
      ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
      : ex === "bitget"
      ? "bg-cyan-500/20 text-cyan-400 border-cyan-500/30"
      : "bg-orange-500/20 text-orange-400 border-orange-500/30";
}

/**
 * HyperX address -> exchange account mapping, sourced from the trading
 * backend's hyperx.ak.sk. Kept in sync with the account names in the `accounts`
 * table. An address can be mirrored by several accounts across exchanges.
 */
const ACCOUNT_ADDRESS_MAPPINGS: AccountAddressMapping[] = [
  {
    address: "0xed1c710ad28e9aca013178a4e8d43a580b4b0dbf",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct1", detail: "2620U · ratio 1x", status: "live" },
      { exchange: "bitget", accountId: "bitget_acct1", detail: "300U · ratio 1x · force-min", status: "live" },
    ],
  },
  {
    address: "0x61e9e0b9ea92e21709115425569feba8d3f0f5ab",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct3", detail: "1060U · ratio 1x", status: "live" },
      { exchange: "bitget", accountId: "bitget_acct3", detail: "300U · ratio 1x · force-min", status: "live" },
    ],
  },
  {
    address: "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct5", detail: "3080U · ratio 2x", status: "live" },
      { exchange: "bitget", accountId: "bitget_acct5", detail: "300U · ratio 2x · force-min", status: "live" },
    ],
  },
  {
    address: "0x15baf1cefcced43e971da85b7b4de5a0391f7b29",
    ref: "66668",
    accounts: [
      { exchange: "binance", accountId: "binance_acct2", detail: "680U · ratio 2x · force-min", status: "live" },
      { exchange: "bitget", accountId: "bitget_acct4", detail: "300U · ratio 2x · force-min", status: "live" },
    ],
  },
  {
    address: "0xa4ac1d48fe393ac94e7f9480af8abd9360abf48a",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct2", detail: "1110U · ratio 3x · force-min", status: "live" },
      { exchange: "bybit", accountId: "bybitswapu_acct4", detail: "3030U · ratio 3x · force-min", status: "live" },
      { exchange: "binance", accountId: "binance_acct1", detail: "640U · ratio 3x · force-min", status: "live" },
      { exchange: "bitget", accountId: "bitget_acct2", detail: "300U · ratio 3x · force-min", status: "live" },
      { exchange: "gate", accountId: "gateioswapu_hx1", detail: "10000U · ratio 5x · maker open/add, taker exit", status: "live" },
      { exchange: "gate", accountId: "gateioswapu_gq1", detail: "10000U · ratio 5x", status: "live" },
    ],
  },
  {
    address: "0xa4178e3b8d7799cd472ceeb63b302b4a1344da19",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct6", detail: "78U · ratio 1x", status: "pending" },
      { exchange: "gate", accountId: "gateioswapu_gateb", detail: "200U · ratio 2x · force-min", status: "live" },
    ],
  },
];

function StatusBadge({ status }: { status: ExchangeAccount["status"] }) {
  return status === "live" ? (
    <Badge
      variant="outline"
      className="text-[10px] font-mono px-1.5 py-0 gap-1 bg-emerald-500/15 text-emerald-400 border-emerald-500/40"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
      LIVE
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className="text-[10px] font-mono px-1.5 py-0 border-dashed bg-transparent text-white/45 border-white/25"
    >
      PENDING
    </Badge>
  );
}

function AccountCell({ account }: { account: ExchangeAccount }) {
  const pending = account.status === "pending";
  return (
    <div
      className={
        pending
          ? "opacity-50 border-l-2 border-dashed border-white/20 pl-2"
          : "border-l-2 border-emerald-500/60 pl-2"
      }
    >
      <div className="flex items-center gap-2">
        <span className={pending ? "text-white/70 font-medium" : "text-white/90 font-medium"}>
          {account.accountId}
        </span>
        <Badge
          variant="outline"
          className={`text-[10px] uppercase font-mono px-1.5 py-0 ${exchangeBadgeStyle(account.exchange)}`}
        >
          {account.exchange}
        </Badge>
        <StatusBadge status={account.status} />
      </div>
      <div className="text-white/50 text-xs">{account.detail}</div>
    </div>
  );
}

/** Live accounts first, then pending; stable otherwise. */
function sortedAccounts(accounts: ExchangeAccount[]): ExchangeAccount[] {
  return [...accounts].sort(
    (a, b) => Number(a.status === "pending") - Number(b.status === "pending"),
  );
}

const compareAccountIds = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

/** Rank by exchange (Bybit, then Gate), then by that exchange's first account id. */
const ADDRESS_ORDER_EXCHANGES: ExchangeAccount["exchange"][] = ["bybit", "gate"];

function addressSortKey(mapping: AccountAddressMapping): [number, string] {
  for (const [rank, exchange] of ADDRESS_ORDER_EXCHANGES.entries()) {
    const ids = mapping.accounts
      .filter((account) => account.exchange === exchange)
      .map((account) => account.accountId)
      .sort(compareAccountIds);
    if (ids.length > 0) return [rank, ids[0]];
  }
  return [ADDRESS_ORDER_EXCHANGES.length, ""];
}

/** Addresses in Bybit account order (acct1, acct2, …), then Gate-only ones in Gate account order. */
function sortedMappings(mappings: AccountAddressMapping[]): AccountAddressMapping[] {
  return [...mappings].sort((a, b) => {
    const [rankA, idA] = addressSortKey(a);
    const [rankB, idB] = addressSortKey(b);
    return rankA - rankB || compareAccountIds(idA, idB);
  });
}

export default function AccountAddressMap() {
  const all = ACCOUNT_ADDRESS_MAPPINGS.flatMap((mapping) => mapping.accounts);
  const liveCount = all.filter((account) => account.status === "live").length;
  const pendingCount = all.length - liveCount;
  const mappings = sortedMappings(ACCOUNT_ADDRESS_MAPPINGS);

  return (
    <Card className="bg-[#0d2538] border-[#00b4d8]/20">
      <CardHeader>
        <CardTitle className="text-lg font-bold text-white flex items-center">
          <Network className="h-5 w-5 text-[#00b4d8] mr-2" />
          Accounts → HyperX Mapping
        </CardTitle>
        <CardDescription className="text-white/70">
          Each HyperX trader address and the exchange accounts it mirrors. Click an address to open
          it.
        </CardDescription>
        <div className="flex items-center gap-2 pt-1">
          <StatusBadge status="live" />
          <span className="text-white/80 text-xs font-mono">{liveCount} 跟单中</span>
          <span className="text-white/20">|</span>
          <StatusBadge status="pending" />
          <span className="text-white/50 text-xs font-mono">{pendingCount} 未上线</span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/60 border-b border-[#00b4d8]/20">
                <th className="py-2 pr-4 font-medium">HyperX Address</th>
                <th className="py-2 font-medium">Accounts</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((mapping, index) => {
                const anyLive = mapping.accounts.some((account) => account.status === "live");
                return (
                  <tr
                    key={`${mapping.address}-${index}`}
                    className="border-b border-white/5 last:border-0 hover:bg-[#00b4d8]/5 transition-colors align-top"
                  >
                    <td className={anyLive ? "py-3 pr-4" : "py-3 pr-4 opacity-50"}>
                      <a
                        href={traderUrl(mapping.address, mapping.ref)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[#00b4d8] hover:text-[#00b4d8]/80 font-mono text-xs break-all"
                      >
                        {mapping.address}
                        <ExternalLink className="h-3 w-3 flex-shrink-0" />
                      </a>
                      {!anyLive && <div className="text-white/40 text-[10px] mt-1">无账户在跟</div>}
                    </td>
                    <td className="py-3">
                      <div className="space-y-2">
                        {sortedAccounts(mapping.accounts).map((account) => (
                          <AccountCell key={account.accountId} account={account} />
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
