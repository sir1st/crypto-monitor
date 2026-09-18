import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ExternalLink, Network } from "lucide-react";

const traderUrl = (address: string, ref: string) =>
  `https://hyperx.trade/hyperliquid/trader?address=${address}&ref=${ref}`;

interface ExchangeAccount {
  accountId: string;
  principal: string;
  entry: string;
}

interface AccountAddressMapping {
  address: string;
  ref: string;
  bybit: ExchangeAccount;
  bitget: ExchangeAccount;
}

/**
 * HyperX address -> Bybit + Bitget account mapping, sourced from the trading
 * backend's hyperx.ak.sk. Kept in sync with the account names in the `accounts`
 * table. Each address is mirrored by one Bybit and one Bitget account.
 */
const ACCOUNT_ADDRESS_MAPPINGS: AccountAddressMapping[] = [
  {
    address: "0xa1b6d8efbcb2fb750a84dbc05649fa4968034f04",
    ref: "66668",
    bybit: { accountId: "bybitswapu_acct1", principal: "2000U", entry: "0.2x" },
    bitget: { accountId: "bitget_acct1", principal: "100U", entry: "0.5x" },
  },
  {
    address: "0xca83349eaee309b8143ab34ce2b33df0a0295bcd",
    ref: "HYPER",
    bybit: { accountId: "bybitswapu_acct2", principal: "1000U", entry: "0.4x" },
    bitget: { accountId: "bitget_acct2", principal: "100U", entry: "0.5x" },
  },
  {
    address: "0xfdb03a2574e9e7d1c77d9ed752d99cdf25c3db25",
    ref: "66668",
    bybit: { accountId: "bybitswapu_acct3", principal: "1000U", entry: "0.33x" },
    bitget: { accountId: "bitget_acct3", principal: "100U", entry: "0.5x" },
  },
  {
    address: "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1",
    ref: "66668",
    bybit: { accountId: "bybitswapu_acct4", principal: "3000U", entry: "0.1x" },
    bitget: { accountId: "bitget_acct4", principal: "100U", entry: "0.5x" },
  },
  {
    address: "0x769232f7de58dcdb30659b34d9d51ded02537848",
    ref: "66668",
    bybit: { accountId: "bybitswapu_acct5", principal: "3000U", entry: "0.1x" },
    bitget: { accountId: "bitget_acct5", principal: "100U", entry: "0.5x" },
  },
];

function AccountCell({ account }: { account: ExchangeAccount }) {
  return (
    <div>
      <div className="text-white/90 font-medium">{account.accountId}</div>
      <div className="text-white/50 text-xs">
        {account.principal} · 开仓 {account.entry}
      </div>
    </div>
  );
}

export default function AccountAddressMap() {
  return (
    <Card className="bg-[#0d2538] border-[#00b4d8]/20">
      <CardHeader>
        <CardTitle className="text-lg font-bold text-white flex items-center">
          <Network className="h-5 w-5 text-[#00b4d8] mr-2" />
          Bybit / Bitget → HyperX Mapping
        </CardTitle>
        <CardDescription className="text-white/70">
          Each HyperX trader address and the Bybit + Bitget accounts it mirrors. Click an address to open it.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-white/60 border-b border-[#00b4d8]/20">
                <th className="py-2 pr-4 font-medium">HyperX Address</th>
                <th className="py-2 pr-4 font-medium">Bybit Account</th>
                <th className="py-2 font-medium">Bitget Account</th>
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
                  <td className="py-3 pr-4">
                    <AccountCell account={mapping.bybit} />
                  </td>
                  <td className="py-3">
                    <AccountCell account={mapping.bitget} />
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