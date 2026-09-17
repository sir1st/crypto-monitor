import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ExternalLink, Network } from "lucide-react";

const HYPERX_REF = "66668";

const traderUrl = (address: string) =>
  `https://hyperx.trade/hyperliquid/trader?address=${address}&ref=${HYPERX_REF}`;

interface AccountAddressMapping {
  accountId: string;
  username: string;
  address: string;
  baseMarginAmount: string;
}

/**
 * Bybit account -> HyperX address mapping, sourced from the trading backend's
 * config/local.json `accounts` list. Kept in sync with the account names in the
 * `accounts` table.
 */
const ACCOUNT_ADDRESS_MAPPINGS: AccountAddressMapping[] = [
  {
    accountId: "bybitswapu_acct1",
    username: "acct1",
    address: "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1",
    baseMarginAmount: "500",
  },
  {
    accountId: "bybitswapu_acct2",
    username: "acct2",
    address: "0xca83349eaee309b8143ab34ce2b33df0a0295bcd",
    baseMarginAmount: "400",
  },
  {
    accountId: "bybitswapu_acct3",
    username: "acct3",
    address: "0xfdb03a2574e9e7d1c77d9ed752d99cdf25c3db25",
    baseMarginAmount: "330",
  },
  {
    accountId: "bybitswapu_acct4",
    username: "acct4",
    address: "0xb7e0b9fbc9479330d70bcc82a7d4325a20e8d1aa",
    baseMarginAmount: "300",
  },
  {
    accountId: "bybitswapu_acct5",
    username: "acct5",
    address: "0xf2b23d759dc23cea06ae9fb2d6cd7059c74cad8e",
    baseMarginAmount: "300",
  },
];

export default function AccountAddressMap() {
  return (
    <Card className="bg-[#0d2538] border-[#00b4d8]/20">
      <CardHeader>
        <CardTitle className="text-lg font-bold text-white flex items-center">
          <Network className="h-5 w-5 text-[#00b4d8] mr-2" />
          Bybit → HyperX Mapping
        </CardTitle>
        <CardDescription className="text-white/70">
          Each Bybit account and the HyperX trader address it mirrors. Click an address to open it.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/60 border-b border-[#00b4d8]/20">
                <th className="py-2 pr-4 font-medium">Bybit Account</th>
                <th className="py-2 pr-4 font-medium">Base Margin</th>
                <th className="py-2 font-medium">HyperX Address</th>
              </tr>
            </thead>
            <tbody>
              {ACCOUNT_ADDRESS_MAPPINGS.map((mapping) => (
                <tr
                  key={mapping.accountId}
                  className="border-b border-white/5 last:border-0 hover:bg-[#00b4d8]/5 transition-colors"
                >
                  <td className="py-3 pr-4">
                    <div className="text-white/90 font-medium">{mapping.accountId}</div>
                    <div className="text-white/50 text-xs">{mapping.username}</div>
                  </td>
                  <td className="py-3 pr-4 text-white/70">{mapping.baseMarginAmount}</td>
                  <td className="py-3">
                    <a
                      href={traderUrl(mapping.address)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[#00b4d8] hover:text-[#00b4d8]/80 font-mono text-xs break-all"
                    >
                      {mapping.address}
                      <ExternalLink className="h-3 w-3 flex-shrink-0" />
                    </a>
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
