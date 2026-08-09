from martingale_manager import add_martingale_position
import os
import json
from datetime import datetime

def handle_martingale_commands(command, args, chat_id):
    """Handle martingale-specific Telegram commands"""
    
    if command == "/add":
        if not args:
            return """
<b>📈 ADD TO POSITION</b>

<b>Usage:</b>
<code>/add SYMBOL [MULTIPLIER]</code>

<b>Examples:</b>
<code>/add BTCUSDT</code> - Add 2x to BTCUSDT position
<code>/add ETHUSDT 1.5</code> - Add 1.5x to ETHUSDT position

<b>Default multiplier:</b> 2.0
            """
        
        symbol = args[0].upper()
        multiplier = float(args[1]) if len(args) > 1 else 2.0
        
        # Validate multiplier
        if multiplier <= 0 or multiplier > 10:
            return "❌ Invalid multiplier. Use values between 0.1 and 10.0"
        
        # Execute martingale addition
        result = add_martingale_position(symbol, multiplier)
        
        if result["success"]:
            if "accounts" in result:
                # Multi-account response
                message = f"""
✅ <b>MULTI-ACCOUNT MARTINGALE ADDED</b>

<b>Symbol:</b> {symbol}
<b>Side:</b> {result['side']}
<b>Multiplier:</b> {multiplier}x
<b>Success Rate:</b> {result['accounts']}/{result['total_accounts']} accounts

<b>Account Details:</b>
"""
                for account_name, account_result in result['results'].items():
                    if account_result.get('success'):
                        added_amount = account_result.get('added_amount_usdt', 0)
                        added_qty = account_result.get('added_qty', '0')
                        message += f"✅ {account_name}: +${added_amount:.2f} ({added_qty})\n"
                    else:
                        error = account_result.get('error', 'Unknown error')
                        message += f"❌ {account_name}: {error}\n"
                
                message += f"\n<i>Positions will be updated with new average entry prices.</i>"
                return message
            else:
                # Single account response (original)
                message = f"""
✅ <b>MARTINGALE POSITION ADDED</b>

<b>Symbol:</b> {symbol}
<b>Side:</b> {result['side']}
<b>Multiplier:</b> {multiplier}x
<b>Added Amount:</b> ${result['added_amount']:.2f}
<b>Added Quantity:</b> {result['added_qty']}
<b>Order ID:</b> {result['order_id']}

<i>Position will be updated with new average entry price.</i>
                """
                return message
        else:
            return f"❌ Failed to add to {symbol} position: {result['message']}"
    
    elif command == "/martingale_status":
        return show_martingale_status()
    
    elif command == "/martingale_log":
        return show_martingale_log()
    
    return None

def show_martingale_status():
    """Show current martingale strategy status"""
    try:
        # Get active positions
        from trade_manager import get_active_positions
        positions = get_active_positions()
        
        if not positions:
            return "📊 No active positions found."
        
        message = "<b>📊 MARTINGALE STATUS</b>\n\n"
        
        for symbol, pos in positions.items():
            side = pos.get("side")
            size = pos.get("size")
            entry_price = pos.get("entry_price")
            mark_price = pos.get("mark_price")
            unrealized_pnl = pos.get("unrealised_pnl", 0)
            roi_pct = pos.get("roi_pct", 0)
            
            emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
            
            message += f"""
{emoji} <b>{symbol}</b> ({side})
Size: {size}
Entry: ${entry_price:.4f}
Current: ${mark_price:.4f}
PnL: ${unrealized_pnl:.2f} ({roi_pct:.2f}%)

"""
        
        return message
        
    except Exception as e:
        return f"❌ Error getting martingale status: {e}"

def show_martingale_log():
    """Show recent martingale operations"""
    try:
        if not os.path.exists("martingale_log.json"):
            return "📋 No martingale operations recorded yet."
        
        with open("martingale_log.json", "r") as f:
            logs = json.load(f)
        
        if not logs:
            return "📋 No martingale operations recorded yet."
        
        message = "<b>📋 RECENT MARTINGALE OPERATIONS</b>\n\n"
        
        # Show last 5 operations
        for log in logs[-5:]:
            timestamp = log.get("timestamp", "")
            symbol = log.get("symbol", "")
            multiplier = log.get("multiplier", 0)
            added_amount = log.get("added_amount_usdt", 0)
            
            try:
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime("%m-%d %H:%M")
            except:
                time_str = timestamp[:10]
            
            message += f"<code>{time_str}</code> {symbol} +{multiplier}x (${added_amount:.0f})\n"
        
        return message
        
    except Exception as e:
        return f"❌ Error getting martingale log: {e}" 