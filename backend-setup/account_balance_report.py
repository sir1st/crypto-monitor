#!/usr/bin/env python
"""
account_balance_report.py - Account Balance Analysis and Position Sizing Report

This script:
1. Gets current account balance
2. Calculates trading PnL from closed positions over 7 days
3. Shows account growth percentage over 7 days
4. Calculates position sizing recommendations
5. Sends report to Telegram (optional)
6. Supports single or multiple accounts
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from pybit.unified_trading import HTTP
from dotenv import load_dotenv
from time_sync import time_sync, get_server_time_ms
import time
import argparse
from collections import defaultdict
import requests

# Load environment variables
load_dotenv()

# Define all possible Beluga accounts - script will only use what's available
BELUGA_ACCOUNTS = {
    "main": {
        "key": os.getenv("BYBIT_API_KEY"),
        "secret": os.getenv("BYBIT_API_SECRET")
    },
    "hedge": {
        "key": os.getenv("BYBIT_API_KEY_HEDGE"),
        "secret": os.getenv("BYBIT_API_SECRET_HEDGE")
    }
}

# Filter out accounts with missing credentials
available_accounts = {
    name: creds for name, creds in BELUGA_ACCOUNTS.items() 
    if creds["key"] and creds["secret"]
}

if not available_accounts:
    sys.exit("❌ Error: No valid API credentials found. Please check your .env file.")

print(f"📊 Found {len(available_accounts)} account(s): {', '.join(available_accounts.keys())}")

# Create sessions with proper recv_window
sessions = {
    name: HTTP(
        testnet=False, 
        api_key=creds["key"], 
        api_secret=creds["secret"],
        recv_window=20000  # 20 seconds to handle timestamp sync issues
    )
    for name, creds in available_accounts.items()
}

def get_current_balance(session, account_type="UNIFIED"):
    """Get current wallet balance"""
    try:
        response = session.get_wallet_balance(accountType=account_type)
        if response["retCode"] == 0:
            account_data = response["result"]["list"][0]
            total_equity = float(account_data["totalEquity"])
            total_wallet_balance = float(account_data["totalWalletBalance"])
            total_unrealized_pnl = float(account_data["totalPerpUPL"])
            
            return {
                "total_equity": total_equity,
                "wallet_balance": total_wallet_balance,
                "unrealized_pnl": total_unrealized_pnl,
                "coins": account_data["coin"]
            }
        else:
            print(f"Error getting wallet balance: {response['retMsg']}")
            return None
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return None

def fetch_closed_pnls(session, category, start_ms, end_ms):
    """Fetch closed PnL in ≤7-day chunks, paging via nextPageCursor"""
    all_recs = []
    max_delta = timedelta(days=7)
    ws = datetime.fromtimestamp(start_ms/1000, tz=timezone.utc)
    we = datetime.fromtimestamp(end_ms/1000, tz=timezone.utc)

    while ws < we:
        chunk_end = min(ws + max_delta, we)
        s_ms, e_ms = int(ws.timestamp()*1000), int(chunk_end.timestamp()*1000)
        cursor = None
        while True:
            try:
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
            except Exception as e:
                print(f"Error fetching closed PnL: {e}")
                break
        ws = chunk_end

    return all_recs

def compute_trading_metrics(records):
    """Compute trading metrics from closed PnL records"""
    sum_all_pnl = 0.0
    total_trades = len(records)
    win_trades = 0
    loss_trades = 0
    sum_win_pnl = 0.0
    sum_loss_pnl = 0.0

    per_sym = defaultdict(lambda: {
        "win_pnl":0.0, "win_count":0,
        "loss_pnl":0.0, "loss_count":0
    })

    for r in records:
        pnl = float(r["closedPnl"])
        sym = r["symbol"]

        sum_all_pnl += pnl

        if pnl > 0:
            sum_win_pnl += pnl
            per_sym[sym]["win_pnl"] += pnl
            per_sym[sym]["win_count"] += 1
            win_trades += 1
        else:
            sum_loss_pnl += pnl
            per_sym[sym]["loss_pnl"] += pnl
            per_sym[sym]["loss_count"] += 1
            loss_trades += 1

    win_rate = (win_trades / total_trades * 100) if total_trades else 0.0
    
    # Calculate PnL ratio - profit-to-loss ratio
    if sum_loss_pnl != 0:
        pnl_ratio = abs(sum_win_pnl / sum_loss_pnl)
    else:
        pnl_ratio = float('inf')

    # per-symbol summary
    symbol_stats = {}
    for s, d in per_sym.items():
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
            "Total PnL$": tot_pnl,
            "Win PnL$": d["win_pnl"],
            "Loss PnL$": d["loss_pnl"],
            "Win Count": d["win_count"],
            "Loss Count": d["loss_count"],
            "Win Rate%": sym_win_rate,
            "PnL Ratio": sym_pnl_ratio
        }

    return {
        "Total PnL$": sum_all_pnl,
        "Win PnL$": sum_win_pnl,
        "Loss PnL$": sum_loss_pnl,
        "Win Count": win_trades,
        "Loss Count": loss_trades,
        "Win Rate%": win_rate,
        "PnL Ratio": pnl_ratio,
        "By Symbol": symbol_stats
    }

def get_trading_performance(session, days_back=7):
    """Get trading performance metrics from closed PnL"""
    try:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days_back)
        
        s_ms = int(start_time.timestamp() * 1000)
        e_ms = int(end_time.timestamp() * 1000)
        
        # Get closed PnL for both categories
        linear_records = fetch_closed_pnls(session, "linear", s_ms, e_ms)
        inverse_records = fetch_closed_pnls(session, "inverse", s_ms, e_ms)
        
        all_records = linear_records + inverse_records
        
        if not all_records:
            return {
                "Total PnL$": 0.0,
                "Win PnL$": 0.0,
                "Loss PnL$": 0.0,
                "Win Count": 0,
                "Loss Count": 0,
                "Win Rate%": 0.0,
                "PnL Ratio": 0.0,
                "By Symbol": {}
            }
        
        return compute_trading_metrics(all_records)
    except Exception as e:
        print(f"Error fetching trading performance: {e}")
        return None

def get_monday_of_current_week():
    """Get the Monday of the current week (start of trading week)"""
    today = datetime.now(timezone.utc)
    # Monday is 0, Sunday is 6
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    # Reset to start of day (00:00:00 UTC)
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday

def get_weekly_trading_performance(session):
    """Get trading performance metrics from Monday of current week to now"""
    try:
        end_time = datetime.now(timezone.utc)
        start_time = get_monday_of_current_week()
        
        # Calculate days for display (include current day)
        days_in_week = (end_time - start_time).days + 1
        
        s_ms = int(start_time.timestamp() * 1000)
        e_ms = int(end_time.timestamp() * 1000)
        
        # Get closed PnL for both categories
        linear_records = fetch_closed_pnls(session, "linear", s_ms, e_ms)
        inverse_records = fetch_closed_pnls(session, "inverse", s_ms, e_ms)
        
        all_records = linear_records + inverse_records
        
        if not all_records:
            return {
                "Total PnL$": 0.0,
                "Win PnL$": 0.0,
                "Loss PnL$": 0.0,
                "Win Count": 0,
                "Loss Count": 0,
                "Win Rate%": 0.0,
                "PnL Ratio": 0.0,
                "By Symbol": {},
                "week_start": start_time,
                "days_trading": days_in_week
            }
        
        weekly_metrics = compute_trading_metrics(all_records)
        weekly_metrics["week_start"] = start_time
        weekly_metrics["days_trading"] = days_in_week
        
        return weekly_metrics
    except Exception as e:
        print(f"Error fetching weekly trading performance: {e}")
        return None

def calculate_position_sizes(balance, percentages=[1, 2, 3, 4, 5]):
    """Calculate position sizes for given percentages"""
    return {f"{pct}%": balance * (pct / 100) for pct in percentages}

def format_currency(amount, decimals=2):
    """Format currency with commas and specified decimals"""
    return f"${amount:,.{decimals}f}"

def generate_telegram_message(account_data, total_data=None):
    """Generate formatted Telegram message"""
    message_parts = []
    
    # Header
    report_title = os.getenv("REPORT_TITLE", "ACCOUNT BALANCE & TRADING REPORT")
    message_parts.append(f"💰 <b>{report_title}</b>")
    message_parts.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    message_parts.append("")
    
    # Individual accounts
    for account_name, data in account_data.items():
        message_parts.append(f"📊 <b>{account_name.upper()} ACCOUNT</b>")
        message_parts.append(f"💼 Current Balance: {format_currency(data['current_equity'])}")
        message_parts.append(f"📅 Balance 7 Days Ago: {format_currency(data['balance_7_days_ago'])}")
        message_parts.append(f"📈 Unrealized P&L: {format_currency(data['unrealized_pnl'])}")
        message_parts.append("")
        
        # Weekly Performance (NEW)
        weekly_perf = data['weekly_performance']
        weekly_start = weekly_perf['week_start'].strftime('%Y-%m-%d')
        days_trading = weekly_perf['days_trading']
        weekly_profit_icon = "📈" if weekly_perf['Total PnL$'] >= 0 else "📉"
        
        message_parts.append(f"📅 <b>This Week Performance (Mon {weekly_start}):</b>")
        message_parts.append(f"   {weekly_profit_icon} Weekly PnL: {format_currency(weekly_perf['Total PnL$'])}")
        message_parts.append(f"   📊 Balance Monday: {format_currency(data['balance_monday'])}")
        message_parts.append(f"   📈 Weekly Growth: {format_currency(data['weekly_net_growth'])}")
        message_parts.append(f"   📈 Raw Growth Rate: {data['weekly_raw_growth_percentage']:+.2f}%")
        message_parts.append(f"   📊 Net Growth Rate: {data['weekly_growth_percentage']:+.2f}%")
        message_parts.append(f"   🗓️ Trading Days: {days_trading}")
        if weekly_perf['Win Count'] + weekly_perf['Loss Count'] > 0:
            message_parts.append(f"   🎯 Trades: {weekly_perf['Win Count']}W/{weekly_perf['Loss Count']}L")
            message_parts.append(f"   📊 Win Rate: {weekly_perf['Win Rate%']:.1f}%")
        else:
            message_parts.append(f"   📊 No trades this week")
        message_parts.append("")
        
        # 7-Day Trading Performance (existing)
        perf = data['trading_performance']
        profit_icon = "📈" if perf['Total PnL$'] >= 0 else "📉"
        message_parts.append(f"{profit_icon} <b>7-Day Trading Performance:</b>")
        message_parts.append(f"   Trading PnL: {format_currency(perf['Total PnL$'])}")
        message_parts.append(f"   Velon (10%): {format_currency(data['associates_share'])}")
        message_parts.append(f"   Net Growth: {format_currency(data['net_growth'])}")
        message_parts.append(f"   Growth Rate: {data['growth_percentage']:+.2f}%")
        message_parts.append(f"   Trades: {perf['Win Count']}W/{perf['Loss Count']}L")
        message_parts.append(f"   Win Rate: {perf['Win Rate%']:.1f}%")
        pnl_ratio_str = f"{perf['PnL Ratio']:.2f}" if perf['PnL Ratio'] != float('inf') else "∞"
        message_parts.append(f"   PnL Ratio: {pnl_ratio_str}")
        message_parts.append("")
        
        # Position sizing
        message_parts.append("🎯 <b>Position Sizing:</b>")
        for pct, amount in data['position_sizes'].items():
            message_parts.append(f"   • {pct}: {format_currency(amount)}")
        message_parts.append("")
        
        # Top symbols (show weekly if available, otherwise 7-day)
        symbols_to_show = weekly_perf['By Symbol'] if weekly_perf['By Symbol'] else perf['By Symbol']
        period_label = "This Week" if weekly_perf['By Symbol'] else "7-Day"
        
        if symbols_to_show:
            message_parts.append(f"🔝 <b>Top Symbols ({period_label}):</b>")
            sorted_symbols = sorted(symbols_to_show.items(), key=lambda x: x[1]['Total PnL$'], reverse=True)
            for sym, stats in sorted_symbols[:3]:  # Top 3
                message_parts.append(f"   • {sym}: {format_currency(stats['Total PnL$'])}")
        
        message_parts.append("─────────────────────")
        message_parts.append("")
    
    # Combined totals if multiple accounts (update this section too)
    if total_data and len(account_data) > 1:
        message_parts.append("🏆 <b>COMBINED TOTAL</b>")
        message_parts.append(f"💼 Total Current Balance: {format_currency(total_data['total_current_equity'])}")
        
        # Combined weekly performance
        if 'combined_weekly_pnl' in total_data:
            weekly_profit_icon = "📈" if total_data['combined_weekly_pnl'] >= 0 else "📉"
            message_parts.append(f"{weekly_profit_icon} Combined Weekly PnL: {format_currency(total_data['combined_weekly_pnl'])}")
            message_parts.append(f"📊 Combined Weekly Growth: {total_data['combined_weekly_growth_pct']:+.2f}%")
        
        message_parts.append(f"📅 Total Balance 7 Days Ago: {format_currency(total_data['total_balance_7_days_ago'])}")
        
        profit_icon = "📈" if total_data['combined_net_growth'] >= 0 else "📉"
        message_parts.append(f"{profit_icon} Combined Trading PnL: {format_currency(total_data['combined_trading_pnl'])}")
        message_parts.append(f"💰 Combined Velon: {format_currency(total_data['combined_associates_share'])}")
        message_parts.append(f"📊 Combined Net Growth: {format_currency(total_data['combined_net_growth'])}")
        message_parts.append(f"📈 Combined Growth Rate: {total_data['combined_growth_pct']:+.2f}%")
        message_parts.append("")
        
        message_parts.append("🎯 <b>Combined Position Sizing:</b>")
        for pct, amount in total_data['combined_position_sizes'].items():
            message_parts.append(f"   • {pct}: {format_currency(amount)}")
        message_parts.append("")
    
    # Footer
    message_parts.append("📊 <i>Performance based on closed positions only</i>")
    
    return "\n".join(message_parts)

def send_to_reports_bot(message):
    """Send message to specific reports Telegram bot"""
    try:
        # Credentials come from the environment; never hardcode them.
        bot_token = os.getenv("REPORTS_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("REPORTS_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        if not bot_token or not chat_id:
            print("Telegram reporting disabled: set REPORTS_BOT_TOKEN and REPORTS_CHAT_ID")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return True
            else:
                print(f"❌ Telegram API error: {result.get('description', 'Unknown error')}")
                return False
        else:
            print(f"❌ HTTP error {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error sending to reports bot: {e}")
        return False
    except Exception as e:
        print(f"❌ Error sending to reports bot: {e}")
        return False

def generate_balance_report(send_to_telegram=False, telegram_only=False, send_to_reports=False, reports_only=False):
    """Generate comprehensive balance and position sizing report"""
    
    if not telegram_only and not reports_only:
        print("=" * 80)
        print("ACCOUNT BALANCE & TRADING PERFORMANCE REPORT")
        print("=" * 80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()
    
    # Synchronize time first
    if not telegram_only and not reports_only:
        print("Synchronizing time with Bybit servers...")
    time_sync._sync_time()
    time.sleep(1)
    
    account_data = {}
    total_current_equity = 0
    total_balance_7_days_ago = 0
    total_trading_pnl = 0
    total_associates_share = 0
    total_net_growth = 0
    
    # Weekly totals
    total_weekly_pnl = 0
    total_balance_monday = 0
    total_weekly_net_growth = 0
    
    for account_name, session in sessions.items():
        if not telegram_only and not reports_only:
            print(f"\n{'=' * 20} {account_name.upper()} ACCOUNT {'=' * 20}")
        
        # Get current balance
        current_balance = get_current_balance(session)
        if not current_balance:
            if not telegram_only and not reports_only:
                print(f"❌ Failed to get current balance for {account_name}")
            continue
            
        # Get trading performance (7-day)
        if not telegram_only and not reports_only:
            print("Fetching 7-day trading performance...")
        trading_perf = get_trading_performance(session)
        if not trading_perf:
            if not telegram_only and not reports_only:
                print(f"❌ Failed to get 7-day trading performance for {account_name}")
            continue
        
        # Get weekly trading performance (Monday to now)
        if not telegram_only and not reports_only:
            print("Fetching weekly trading performance...")
        weekly_perf = get_weekly_trading_performance(session)
        if not weekly_perf:
            if not telegram_only and not reports_only:
                print(f"❌ Failed to get weekly trading performance for {account_name}")
            continue
        
        # Current values
        # We're showing total_equity as "Current Balance"
        current_equity = current_balance["total_equity"]  # $301,053.76

        # But using wallet_balance for calculations  
        current_wallet = current_balance["wallet_balance"]  # Possibly different?
        unrealized_pnl = current_balance["unrealized_pnl"]
        
        # Calculate balance 7 days ago
        balance_7_days_ago = current_wallet - trading_perf['Total PnL$']
        
        # Calculate balance on Monday
        balance_monday = current_equity - weekly_perf['Total PnL$']
        
        # Calculate Velon (10% of trading PnL)
        associates_share = trading_perf['Total PnL$'] * 0.10
        weekly_associates_share = weekly_perf['Total PnL$'] * 0.10
        
        # Calculate net growth (after Velon)
        net_growth = trading_perf['Total PnL$'] - associates_share
        weekly_net_growth = weekly_perf['Total PnL$'] - weekly_associates_share
        
        # Calculate growth percentages
        growth_percentage = (net_growth / balance_7_days_ago * 100) if balance_7_days_ago != 0 else 0
        
        # Calculate weekly growth percentages (both raw and net)
        weekly_raw_growth_percentage = (weekly_perf['Total PnL$'] / balance_monday * 100) if balance_monday != 0 else 0
        weekly_growth_percentage = (weekly_net_growth / balance_monday * 100) if balance_monday != 0 else 0
        
        # Position sizing
        position_sizes = calculate_position_sizes(current_equity)
        
        # Store data for Telegram
        account_data[account_name] = {
            'current_equity': current_equity,
            'wallet_balance': current_wallet,
            'unrealized_pnl': unrealized_pnl,
            'balance_7_days_ago': balance_7_days_ago,
            'balance_monday': balance_monday,
            'trading_performance': trading_perf,
            'weekly_performance': weekly_perf,
            'associates_share': associates_share,
            'weekly_associates_share': weekly_associates_share,
            'net_growth': net_growth,
            'weekly_net_growth': weekly_net_growth,
            'growth_percentage': growth_percentage,
            'weekly_raw_growth_percentage': weekly_raw_growth_percentage,
            'weekly_growth_percentage': weekly_growth_percentage,
            'position_sizes': position_sizes
        }
        
        if not telegram_only and not reports_only:
            # Display results (console output)
            print(f"\n📊 BALANCE SUMMARY:")
            print(f"   Current Balance:          {format_currency(current_equity)}")
            print(f"   Balance 7 Days Ago:       {format_currency(balance_7_days_ago)}")
            print(f"   Balance Monday:           {format_currency(balance_monday)}")
            print(f"   Unrealized P&L:           {format_currency(unrealized_pnl)}")
            
            # Weekly Performance (NEW)
            monday_date = weekly_perf['week_start'].strftime('%Y-%m-%d')
            days_trading = weekly_perf['days_trading']
            weekly_profit_icon = "📈" if weekly_perf['Total PnL$'] >= 0 else "📉"
            
            print(f"\n📅 WEEKLY PERFORMANCE (Monday {monday_date} to Now - {days_trading} days):")
            print(f"   {weekly_profit_icon} Weekly Trading PnL:       {format_currency(weekly_perf['Total PnL$'])}")
            print(f"   💼 Weekly Velon (10%):        {format_currency(weekly_associates_share)}")
            print(f"   📊 Weekly Net Growth:         {format_currency(weekly_net_growth)}")
            print(f"   📈 Weekly Raw Growth Rate:    {weekly_raw_growth_percentage:+.2f}%")
            print(f"   📊 Weekly Net Growth Rate:    {weekly_growth_percentage:+.2f}%")
            if weekly_perf['Win Count'] + weekly_perf['Loss Count'] > 0:
                print(f"   🎯 Weekly Win Rate:           {weekly_perf['Win Rate%']:.1f}%")
                print(f"   📈 Weekly Winning Trades:     {weekly_perf['Win Count']} ({format_currency(weekly_perf['Win PnL$'])})")
                print(f"   📉 Weekly Losing Trades:      {weekly_perf['Loss Count']} ({format_currency(weekly_perf['Loss PnL$'])})")
                weekly_pnl_ratio_str = f"{weekly_perf['PnL Ratio']:.2f}" if weekly_perf['PnL Ratio'] != float('inf') else "∞"
                print(f"   ⚖️  Weekly PnL Ratio:         {weekly_pnl_ratio_str}")
            else:
                print(f"   📊 No trades completed this week")

            print(f"\n💰 7-DAY TRADING PERFORMANCE:")
            profit_icon = "📈" if trading_perf['Total PnL$'] >= 0 else "📉"
            print(f"   {profit_icon} Trading PnL:             {format_currency(trading_perf['Total PnL$'])}")
            print(f"   💼 Velon (10%):   {format_currency(associates_share)}")
            print(f"   📊 Net Growth:               {format_currency(net_growth)}")
            print(f"   📈 Growth Rate:              {growth_percentage:+.2f}%")
            print(f"   🎯 Win Rate:                 {trading_perf['Win Rate%']:.1f}%")
            print(f"   📈 Winning Trades:           {trading_perf['Win Count']} ({format_currency(trading_perf['Win PnL$'])})")
            print(f"   📉 Losing Trades:            {trading_perf['Loss Count']} ({format_currency(trading_perf['Loss PnL$'])})")
            pnl_ratio_str = f"{trading_perf['PnL Ratio']:.2f}" if trading_perf['PnL Ratio'] != float('inf') else "∞"
            print(f"   ⚖️  PnL Ratio:                {pnl_ratio_str}")
            
            print(f"\n🎯 POSITION SIZING RECOMMENDATIONS:")
            print(f"   Based on Current Balance ({format_currency(current_equity)}):")
            for pct, amount in position_sizes.items():
                print(f"   • {pct:>3} per trade:          {format_currency(amount)}")
            
            # Weekly Symbol breakdown
            if weekly_perf['By Symbol']:
                print(f"\n📈 WEEKLY SYMBOL BREAKDOWN:")
                sorted_symbols = sorted(weekly_perf['By Symbol'].items(), key=lambda x: x[1]['Total PnL$'], reverse=True)
                for sym, stats in sorted_symbols:
                    pnl_ratio_str = f"{stats['PnL Ratio']:.2f}" if stats['PnL Ratio'] != float('inf') else "∞"
                    print(f"   • {sym:>8}: {format_currency(stats['Total PnL$']):>12} "
                          f"[{stats['Win Count']}W/{stats['Loss Count']}L, {stats['Win Rate%']:.1f}%, R:{pnl_ratio_str}]")
            
            # 7-day Symbol breakdown
            if trading_perf['By Symbol']:
                print(f"\n📈 7-DAY SYMBOL BREAKDOWN:")
                sorted_symbols = sorted(trading_perf['By Symbol'].items(), key=lambda x: x[1]['Total PnL$'], reverse=True)
                for sym, stats in sorted_symbols:
                    pnl_ratio_str = f"{stats['PnL Ratio']:.2f}" if stats['PnL Ratio'] != float('inf') else "∞"
                    print(f"   • {sym:>8}: {format_currency(stats['Total PnL$']):>12} "
                          f"[{stats['Win Count']}W/{stats['Loss Count']}L, {stats['Win Rate%']:.1f}%, R:{pnl_ratio_str}]")
            
            # Coin breakdown
            print(f"\n💱 COIN BREAKDOWN:")
            for coin_data in current_balance["coins"]:
                coin = coin_data["coin"]
                wallet_bal = float(coin_data["walletBalance"])
                usd_value = float(coin_data["usdValue"])
                
                if usd_value > 1:  # Only show coins with meaningful value
                    print(f"   • {coin:>6}: {wallet_bal:>12.8f} ({format_currency(usd_value)})")
        
        # Add to totals
        total_current_equity += current_equity
        total_balance_7_days_ago += balance_7_days_ago
        total_balance_monday += balance_monday
        total_trading_pnl += trading_perf['Total PnL$']
        total_weekly_pnl += weekly_perf['Total PnL$']
        total_associates_share += associates_share
        total_net_growth += net_growth
        total_weekly_net_growth += weekly_net_growth
    
    # Combined summary
    total_data = None
    if len(sessions) > 1:
        combined_position_sizes = calculate_position_sizes(total_current_equity)
        combined_growth_pct = (total_net_growth / total_balance_7_days_ago * 100) if total_balance_7_days_ago != 0 else 0
        combined_weekly_growth_pct = (total_weekly_net_growth / total_balance_monday * 100) if total_balance_monday != 0 else 0
        
        total_data = {
            'total_current_equity': total_current_equity,
            'total_balance_7_days_ago': total_balance_7_days_ago,
            'total_balance_monday': total_balance_monday,
            'combined_trading_pnl': total_trading_pnl,
            'combined_weekly_pnl': total_weekly_pnl,
            'combined_associates_share': total_associates_share,
            'combined_net_growth': total_net_growth,
            'combined_weekly_net_growth': total_weekly_net_growth,
            'combined_growth_pct': combined_growth_pct,
            'combined_weekly_growth_pct': combined_weekly_growth_pct,
            'combined_position_sizes': combined_position_sizes
        }
        
        if not telegram_only and not reports_only:
            print(f"\n{'=' * 25} COMBINED TOTAL {'=' * 25}")
            print(f"\n📊 COMBINED BALANCE:")
            print(f"   Total Current Balance:    {format_currency(total_current_equity)}")
            print(f"   Total Balance 7 Days Ago: {format_currency(total_balance_7_days_ago)}")
            print(f"   Total Balance Monday:     {format_currency(total_balance_monday)}")
            
            print(f"\n💰 COMBINED WEEKLY PERFORMANCE:")
            weekly_profit_icon = "📈" if total_weekly_net_growth >= 0 else "📉"
            print(f"   📈 Total Weekly PnL:         {format_currency(total_weekly_pnl)}")
            print(f"   {weekly_profit_icon} Total Weekly Growth:     {format_currency(total_weekly_net_growth)}")
            print(f"   📊 Combined Weekly Rate:     {combined_weekly_growth_pct:+.2f}%")

            print(f"\n💰 COMBINED 7-DAY PERFORMANCE:")
            profit_icon = "📈" if total_net_growth >= 0 else "📉"
            print(f"   📈 Total Trading PnL:        {format_currency(total_trading_pnl)}")
            print(f"   💼 Total Velon:   {format_currency(total_associates_share)}")
            print(f"   {profit_icon} Total Net Growth:        {format_currency(total_net_growth)}")
            print(f"   📊 Combined Growth Rate:     {combined_growth_pct:+.2f}%")
            
            print(f"\n🎯 COMBINED POSITION SIZING:")
            print(f"   Based on Total Balance ({format_currency(total_current_equity)}):")
            for pct, amount in combined_position_sizes.items():
                print(f"   • {pct:>3} per trade:          {format_currency(amount)}")
    
    if not telegram_only and not reports_only:
        print(f"\n{'=' * 80}")
        print("📝 NOTES:")
        print("• Position sizes are based on total equity (including unrealized P&L)")
        print("• Trading performance based on closed positions only")
        print("• Weekly tracking resets every Monday at 00:00 UTC")
        print("• Velon calculated as 10% of trading PnL")
        print("• Growth rate calculated on net growth after Velon")
        print("=" * 80)
    
    # Send to Telegram if requested
    telegram_success = True
    reports_success = True
    
    # Send to regular Telegram if requested
    if send_to_telegram:
        try:
            from tele import send_telegram_message
            telegram_message = generate_telegram_message(account_data, total_data)
            
            if send_telegram_message(telegram_message):
                if not telegram_only and not reports_only:
                    print("\n✅ Report sent to regular Telegram successfully!")
            else:
                if not telegram_only and not reports_only:
                    print("\n❌ Failed to send report to regular Telegram")
                telegram_success = False
        except ImportError:
            if not telegram_only and not reports_only:
                print("\n❌ Regular Telegram integration not available (tele.py not found)")
            telegram_success = False
        except Exception as e:
            if not telegram_only and not reports_only:
                print(f"\n❌ Error sending to regular Telegram: {e}")
            telegram_success = False
    
    # Send to reports bot if requested
    if send_to_reports:
        try:
            telegram_message = generate_telegram_message(account_data, total_data)
            
            if send_to_reports_bot(telegram_message):
                if not telegram_only and not reports_only:
                    print("\n✅ Report sent to reports bot successfully!")
            else:
                if not telegram_only and not reports_only:
                    print("\n❌ Failed to send report to reports bot")
                reports_success = False
        except Exception as e:
            if not telegram_only and not reports_only:
                print(f"\n❌ Error sending to reports bot: {e}")
            reports_success = False
    
    return telegram_success and reports_success

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate account balance and position sizing report")
    parser.add_argument("--telegram", "-t", action="store_true", help="Send report to regular Telegram")
    parser.add_argument("--telegram-only", "-to", action="store_true", help="Send to regular Telegram only (no console output)")
    parser.add_argument("--reports", "-r", action="store_true", help="Send report to reports bot")
    parser.add_argument("--reports-only", "-ro", action="store_true", help="Send to reports bot only (no console output)")
    
    args = parser.parse_args()
    
    try:
        send_to_telegram = args.telegram or args.telegram_only
        send_to_reports = args.reports or args.reports_only
        telegram_only = args.telegram_only
        reports_only = args.reports_only
        
        generate_balance_report(
            send_to_telegram=send_to_telegram, 
            telegram_only=telegram_only,
            send_to_reports=send_to_reports,
            reports_only=reports_only
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Report generation cancelled by user")
    except Exception as e:
        print(f"\n❌ Error generating report: {e}")
        import traceback
        traceback.print_exc()
