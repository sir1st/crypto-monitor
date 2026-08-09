import os, sys
from datetime import datetime, timezone, timedelta
from pybit.unified_trading import HTTP
from dotenv import load_dotenv
from collections import defaultdict

# ── Load API credentials ─────────────────────────────────────────────────────────
load_dotenv()

# Define all Beluga accounts
BELUGA_ACCOUNTS = {
    "main": {
        "key": os.getenv("BYBIT_API_KEY"),
        "secret": os.getenv("BYBIT_API_SECRET")
    },
    # "BelugaV1": {
    #     "key": os.getenv("BELUGA1_BYBIT_API_KEY"),
    #     "secret": os.getenv("BELUGA1_BYBIT_API_SECRET")
    # },
    # "BelugaV2": {u
    #     "key": os.getenv("BELUGA2_BYBIT_API_KEY"),
    #     "secret": os.getenv("BELUGA2_BYBIT_API_SECRET")
    # }
    # "BelugaV3": {
    #     "key": os.getenv("BELUGA3_BYBIT_API_KEY"),
    #     "secret": os.getenv("BELUGA3_BYBIT_API_SECRET")
    # },
    # "BelugaV4": {
    #     "key": os.getenv("BELUGA4_BYBIT_API_KEY"),
    #     "secret": os.getenv("BELUGA4_BYBIT_API_SECRET")
    # }
}

# Validate all credentials are present
missing_creds = [name for name, creds in BELUGA_ACCOUNTS.items() 
                if not creds["key"] or not creds["secret"]]
if missing_creds:
    sys.exit(f"Error: Missing API credentials for: {', '.join(missing_creds)}")

# Create sessions for each account
sessions = {
    name: HTTP(testnet=False, api_key=creds["key"], api_secret=creds["secret"])
    for name, creds in BELUGA_ACCOUNTS.items()
}

# ── Fetch closed-PnL in ≤7-day chunks, paging via nextPageCursor ────────────────
def fetch_closed_pnls(session, category, start_ms, end_ms):
    all_recs = []
    max_delta = timedelta(days=7)
    ws = datetime.fromtimestamp(start_ms/1000, tz=timezone.utc)
    we = datetime.fromtimestamp(end_ms/1000,   tz=timezone.utc)

    while ws < we:
        chunk_end = min(ws + max_delta, we)
        s_ms, e_ms = int(ws.timestamp()*1000), int(chunk_end.timestamp()*1000)
        cursor = None
        while True:
            resp = session.get_closed_pnl(
                category=category, startTime=s_ms, endTime=e_ms,
                limit=100, cursor=cursor
            )["result"]
            batch = resp.get("list", [])  # closed-PnL array 
            if not batch:
                break
            all_recs.extend(batch)
            cursor = resp.get("nextPageCursor")
            if not cursor:
                break
        ws = chunk_end

    return all_recs

# ── Compute ROI metrics ───────────────────────────────────────────────────────────
def compute_roi_metrics(records):
    sum_all_pnl, sum_all_mrg = 0.0, 0.0
    sum_win_pnl, sum_win_mrg = 0.0, 0.0
    sum_loss_pnl, sum_loss_mrg = 0.0, 0.0
    total_trades = len(records)
    win_trades = 0
    loss_trades = 0

    per_sym = defaultdict(lambda: {
        "win_pnl":0.0, "win_mrg":0.0, "win_count":0,
        "loss_pnl":0.0,"loss_mrg":0.0,"loss_count":0
    })

    for r in records:
        pnl      = float(r["closedPnl"])
        notional = float(r["cumEntryValue"])
        lev      = float(r["leverage"])
        mrg      = notional / lev    # initial margin 
        sym      = r["symbol"]

        # overall sums
        sum_all_pnl += pnl
        sum_all_mrg += mrg

        # win vs loss sums
        if pnl > 0:
            sum_win_pnl += pnl
            sum_win_mrg += mrg
            per_sym[sym]["win_pnl"]   += pnl
            per_sym[sym]["win_mrg"]   += mrg
            per_sym[sym]["win_count"] += 1
            win_trades += 1
        else:
            sum_loss_pnl += pnl
            sum_loss_mrg += mrg
            per_sym[sym]["loss_pnl"]    += pnl
            per_sym[sym]["loss_mrg"]    += mrg
            per_sym[sym]["loss_count"]  += 1
            loss_trades += 1

    # avoid divide-by-zero
    total_roi = (sum_all_pnl / sum_all_mrg * 100) if sum_all_mrg else 0.0
    win_roi   = (sum_win_pnl / sum_win_mrg * 100) if sum_win_mrg else 0.0
    loss_roi  = (sum_loss_pnl / sum_loss_mrg * 100) if sum_loss_mrg else 0.0
    win_rate  = (win_trades / total_trades * 100) if total_trades else 0.0
    
    # Calculate PnL ratio correctly - profit-to-loss ratio
    if sum_loss_pnl != 0:
        pnl_ratio = abs(sum_win_pnl / sum_loss_pnl)
    else:
        pnl_ratio = float('inf')

    # per-symbol ROI summary
    symbol_stats = {}
    for s, d in per_sym.items():
        tot_mrg = d["win_mrg"] + d["loss_mrg"]
        tot_pnl = d["win_pnl"] + d["loss_pnl"]
        tot_trades = d["win_count"] + d["loss_count"]
        
        # Calculate win rate for this symbol
        sym_win_rate = (d["win_count"] / tot_trades * 100) if tot_trades else 0.0
        
        # Calculate profit-to-loss ratio for this symbol
        if d["loss_pnl"] != 0:
            sym_pnl_ratio = abs(d["win_pnl"] / d["loss_pnl"])
        else:
            sym_pnl_ratio = float('inf')
        
        symbol_stats[s] = {
            "Total ROI%": (tot_pnl/tot_mrg*100) if tot_mrg else 0.0,
            "Total PnL$": tot_pnl,
            "Win ROI%":   (d["win_pnl"]/d["win_mrg"]*100) if d["win_mrg"] else 0.0,
            "Win PnL$":   d["win_pnl"],
            "Loss ROI%":  (d["loss_pnl"]/d["loss_mrg"]*100) if d["loss_mrg"] else 0.0,
            "Loss PnL$":  d["loss_pnl"],
            "Win Count":  d["win_count"],
            "Loss Count": d["loss_count"],
            "Win Rate%":  sym_win_rate,
            "PnL Ratio":  sym_pnl_ratio
        }

    return {
        "Total ROI%": total_roi,
        "Total PnL$": sum_all_pnl,
        "Win ROI%":   win_roi,
        "Win PnL$":   sum_win_pnl,
        "Loss ROI%":  loss_roi,
        "Loss PnL$":  sum_loss_pnl,
        "Win Count":  win_trades,
        "Loss Count": loss_trades,
        "Win Rate%":  win_rate,
        "PnL Ratio":  pnl_ratio,
        "By Symbol":  symbol_stats
    }

# ── Report for each timeframe ─────────────────────────────────────────────────────
def report(label, delta):
    end = datetime.now(timezone.utc)
    start = end - delta
    s_ms, e_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)

    # Collect records from all accounts
    all_records = []
    for account_name, session in sessions.items():
        account_recs = fetch_closed_pnls(session, "linear", s_ms, e_ms) + \
                      fetch_closed_pnls(session, "inverse", s_ms, e_ms)
        all_records.extend(account_recs)
        
        # Print individual account stats
        if account_recs:
            print(f"\n{account_name} {label} ({len(account_recs)} trades):")
            m = compute_roi_metrics(account_recs)
            print(f" • Total ROI: {m['Total ROI%']:.2f}% (${m['Total PnL$']:.2f})")
            print(f" • Winning ROI: {m['Win ROI%']:.2f}% (${m['Win PnL$']:.2f}) over {m['Win Count']} wins")
            print(f" • Losing ROI: {m['Loss ROI%']:.2f}% (${m['Loss PnL$']:.2f}) over {m['Loss Count']} losses")
            print(f" • Win Rate: {m['Win Rate%']:.2f}%")
            print(f" • PnL Ratio: {m['PnL Ratio']:.2f}" if m['PnL Ratio'] != float('inf') else " • PnL Ratio: ∞")

    # Print combined stats
    if all_records:
        print(f"\nCOMBINED {label} ({len(all_records)} trades):")
        m = compute_roi_metrics(all_records)
        print(f" • Total ROI: {m['Total ROI%']:.2f}% (${m['Total PnL$']:.2f})")
        print(f" • Winning ROI: {m['Win ROI%']:.2f}% (${m['Win PnL$']:.2f}) over {m['Win Count']} wins")
        print(f" • Losing ROI: {m['Loss ROI%']:.2f}% (${m['Loss PnL$']:.2f}) over {m['Loss Count']} losses")
        print(f" • Win Rate: {m['Win Rate%']:.2f}%")
        print(f" • PnL Ratio: {m['PnL Ratio']:.2f}" if m['PnL Ratio'] != float('inf') else " • PnL Ratio: ∞")
        print(" • Per-symbol breakdown:")
        for sym, stats in sorted(m["By Symbol"].items()):
            pnl_ratio_str = f"{stats['PnL Ratio']:.2f}" if stats['PnL Ratio'] != float('inf') else "∞"
            print(f"    – {sym}: Tot {stats['Total ROI%']:.2f}% (${stats['Total PnL$']:.2f}), "
                  f"Win {stats['Win ROI%']:.2f}% (${stats['Win PnL$']:.2f}), "
                  f"Loss {stats['Loss ROI%']:.2f}% (${stats['Loss PnL$']:.2f}) "
                  f"({stats['Win Count']}W/{stats['Loss Count']}L, {stats['Win Rate%']:.1f}%, PnL {pnl_ratio_str})")
    print()

if __name__ == "__main__":
    report("Past 1 day", timedelta(days=1))
    report("Past 2 days", timedelta(days=2))
    report("Past 3 days", timedelta(days=3))
    report("Past 7 days", timedelta(days=7))
    report("Past 30 days", timedelta(days=30))
