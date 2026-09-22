import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ExternalLink, Network } from "lucide-react";

const traderUrl = (address: string, ref: string) =>
  `https://hyperx.trade/hyperliquid/trader?address=${address}&ref=${ref}`;

interface ExchangeAccount {
  exchange: "bybit" | "bitget" | "binance";
  accountId: string;
  /** Sizing note, e.g. "3000U · mirror 0.1x". */
  detail: string;
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
    address: "0xa1b6d8efbcb2fb750a84dbc05649fa4968034f04",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct1", detail: "2000U · 0.2x" },
      { exchange: "bybit", accountId: "bybitswapu_acct3", detail: "1000U · 0.2x" },
      { exchange: "bitget", accountId: "bitget_acct1", detail: "100U · 0.6x" },
      { exchange: "bitget", accountId: "bitget_acct3", detail: "100U · 0.6x" },
      { exchange: "binance", accountId: "binance_acct2", detail: "500U · 0.4x" },
    ],
  },
  {
    address: "0xca83349eaee309b8143ab34ce2b33df0a0295bcd",
    ref: "HYPER",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct2", detail: "1000U · 0.6x" },
      { exchange: "bitget", accountId: "bitget_acct2", detail: "100U · 0.6x" },
    ],
  },
  {
    address: "0x507e507796c7756ed5a195e9f7cf52bc39009e1d",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct4", detail: "3000U · mirror 0.1x" },
      { exchange: "bitget", accountId: "bitget_acct4", detail: "100U · mirror 0.1x" },
      { exchange: "binance", accountId: "binance_acct1", detail: "1000U · mirror 0.1x" },
    ],
  },
  {
    address: "0x769232f7de58dcdb30659b34d9d51ded02537848",
    ref: "66668",
    accounts: [
      { exchange: "bybit", accountId: "bybitswapu_acct5", detail: "3000U · 0.1x" },
      { exchange: "bitget", accountId: "bitget_acct5", detail: "100U · 0.6x" },
    ],
  },
];

function AccountCell({ account }: { account: ExchangeAccount }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-white/90 font-medium">{account.accountId}</span>
        <Badge
          variant="outline"
          className={`text-[10px] uppercase font-mono px-1.5 py-0 ${exchangeBadgeStyle(account.exchange)}`}
        >
          {account.exchange}
        </Badge>
      </div>
      <div className="text-white/50 text-xs">{account.detail}</div>
    </div>
  );
}

export default function AccountAddressMap() {
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
              {ACCOUNT_ADDRESS_MAPPINGS.map((mapping, index) => (
                <tr
                  key={`${mapping.address}-${index}`}
                  className="border-b border-white/5 last:border-0 hover:bg-[#00b4d8]/5 transition-colors align-top"
                >
                  <td className="py-3 pr-4">
                    <a
                      href={traderUrl(mapping.address, mapping.ref)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[#00b4d8] hover:text-[#00b4d8]/80 font-mono text-xs break-all"
                    >
                      {mapping.address}
                      <ExternalLink className="h-3 w-3 flex-shrink-0" />
                    </a>
                  </td>
                  <td className="py-3">
                    <div className="space-y-2">
                      {mapping.accounts.map((account) => (
                        <AccountCell key={account.accountId} account={account} />
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
