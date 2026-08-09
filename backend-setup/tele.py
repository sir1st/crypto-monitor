"""
Telegram Bot for Trading Signals

This module provides a standalone Telegram bot that can:
1. Send trading signals from the main script
2. Process user commands
3. Show current trading positions
4. Display system status
"""

import os
import json
import time
import logging
import threading
import traceback
import requests
from datetime import datetime
from dotenv import load_dotenv
import html
import re
from datetime import timezone
import trade_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TelegramBot")

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_DEBUG = True

# Configuration files
POSITIONS_FILE = "all_positions.json"
SIGNALS_FILE = "all_trade_signals.json"
CONFIG_FILE = "trading_config.json"

# Import martingale command handler
try:
    from telegram_martingale_commands import handle_martingale_commands
    MARTINGALE_AVAILABLE = True
except ImportError:
    logger.warning("Martingale commands not available - telegram_martingale_commands.py not found")
    MARTINGALE_AVAILABLE = False

# Command definitions
COMMANDS = {
    "/help": "Show available commands",
    "/status": "Show bot status and all open positions",
    "/signals": "Show current trading signals",
    "/positions": "Show all open positions",
    "/position": "Show details for a specific position (e.g., /position BTCUSDT)",
    "/close": "Close a specific position (e.g., /close BTCUSDT)",
    "/enter": "Open new positions (e.g., /enter BTCUSDT Buy)",
    "/ping": "Check if the bot is running",
    "/reports": "Show trading reports and alerts",
    "/auto_on": "AI takes trades automatically",
    "/auto_off": "Manual confirmation required for trades",
    "/auto_status": "Show current auto mode",
    "/session_reset": "Reset session state for all symbols",
    "/accounts": "Show all account status and connections",
    "/positions_all": "Show positions across all accounts separately", 
    "/account_count": "Show number of active trading accounts",
    "/add_account": "Instructions for adding a new account",
    "/close_all": "Close all positions across all accounts",
    "/account_positions": "Show positions grouped by account",
    "/sync_accounts": "Sync and refresh all account data"
}

# Add martingale commands if available
if MARTINGALE_AVAILABLE:
    COMMANDS.update({
        "/add": "Add to position with martingale strategy (e.g., /add BTCUSDT 2.0)",
        "/martingale_status": "Show current martingale strategy status",
        "/martingale_log": "Show recent martingale operations"
    })

# Add this global variable at the top of the file to track standalone mode
STANDALONE_MODE = True

# Add session tracking for standalone mode
session_trades = {}

# Session management constants for standalone mode
SESSION_STATE_FILE = "session_state.json"
SESSION_WAIT_MINUTES = 30  # 30-minute wait period after session starts

# Add these constants at the top of the file
TELEGRAM_STATE_FILE = "telegram_state.json"

# Add these session constants after the existing SESSION_WAIT_MINUTES = 30 line:

# Market Sessions Times (UTC) - matching s1.py exactly
TOKYO_START = 0
TOKYO_END = 7
LONDON_START = 7
LONDON_END = 13
NY_START = 13
NY_START_MINUTES = 30
NY_END = 21

TOKYO_SESSION = {"start": f"{TOKYO_START:02d}:00", "end": f"{TOKYO_END:02d}:00"}
LONDON_SESSION = {"start": f"{LONDON_START:02d}:00", "end": f"{LONDON_END:02d}:00"}
NY_SESSION = {"start": f"{NY_START:02d}:30", "end": f"{NY_END:02d}:00"}

def verify_telegram_chat_id(chat_id):
    """
    Verify and normalize the Telegram chat ID format.
    
    Args:
        chat_id: The chat ID to verify
        
    Returns:
        Normalized chat ID
    """
    try:
        # Ensure the chat ID is a string
        chat_id = str(chat_id).strip()
        
        # For public channels: If it starts with '@', leave it as is
        if chat_id.startswith('@'):
            return chat_id
            
        # For private channels or groups: Should be negative and either start with -100 or not
        try:
            # Try to convert to integer to check format
            chat_id_int = int(chat_id)
            
            # Private channel/supergroup IDs should start with -100
            if chat_id_int < 0:
                # If it's negative but doesn't start with -100, it's likely a group
                if not str(chat_id_int).startswith('-100') and chat_id_int > -1000000000:
                    # Likely a simple group, not a supergroup
                    return str(chat_id_int)
                else:
                    # Already in correct format
                    return str(chat_id_int)
            else:
                # Positive IDs need to be converted to channel format
                return f"-100{chat_id_int}"
        except ValueError:
            # Not a number, return as is
            return chat_id
    except Exception as e:
        logger.error(f"Error verifying chat ID: {e}")
        return chat_id

def send_telegram_message(message, parse_mode="HTML", chat_id=None):
    """
    Send a message to Telegram.
    
    Args:
        message: Message text to send
        parse_mode: Message format (HTML, Markdown, or None)
        chat_id: Override the default chat ID
        
    Returns:
        True if successful, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return False
        
    # Use provided chat ID or global setting
    target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_ID
    
    # Verify and normalize the chat ID
    target_chat_id = verify_telegram_chat_id(target_chat_id)
        
    try:
        # Print debug information
        if TELEGRAM_DEBUG:
            logger.info(f"Sending Telegram message to {target_chat_id}")
            logger.debug(f"Message length: {len(message)} characters")
            logger.debug(f"Message preview: {message[:100]}...")
            
        # Make the API call
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        # Use a longer timeout for the request
        response = requests.post(
            url, 
            data=json.dumps(payload), 
            headers=headers,
            timeout=10  # 10 second timeout
        )
        
        # Process response
        if response.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Failed to send Telegram message. Status code: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        traceback.print_exc()
        return False

def get_positions():
    """
    Load current trading positions from the positions file.
    
    Returns:
        Dictionary with position data
    """
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, "r") as f:
                return json.load(f)
        else:
            logger.warning(f"Positions file not found: {POSITIONS_FILE}")
            return {"positions": {}, "last_update": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error loading positions: {e}")
        return {"positions": {}, "last_update": datetime.now().isoformat()}

def get_signals():
    """
    Load current trading signals.
    
    Returns:
        Dictionary with signal data
    """
    try:
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, "r") as f:
                return json.load(f)
        else:
            logger.warning(f"Signals file not found: {SIGNALS_FILE}")
            return {}
    except Exception as e:
        logger.error(f"Error loading signals: {e}")
        return {}

def format_position(symbol, position_data):
    """
    Format a position for display in Telegram.
    
    Args:
        symbol: Trading symbol
        position_data: Position data dictionary
        
    Returns:
        Formatted message
    """
    try:
        side = position_data.get("side", "Unknown")
        size = position_data.get("size", 0)
        value = position_data.get("value", 0)
        leverage = position_data.get("leverage", 1)
        entry_price = position_data.get("entry_price", 0)
        mark_price = position_data.get("mark_price", 0)
        unrealised_pnl = position_data.get("unrealised_pnl", 0)
        
        # Calculate ROI percentage correctly with leverage multiplier
        # For unrealized PnL percentage, include leverage in calculation
        # For sell positions, profit happens when price goes down
        price_change_pct = 0
        if side == "Sell" and entry_price > 0:
            price_change_pct = ((entry_price - mark_price) / entry_price) * 100
        elif side == "Buy" and entry_price > 0:
            price_change_pct = ((mark_price - entry_price) / entry_price) * 100
            
        # Apply leverage to get actual ROI
        unrealised_pnl_pct = price_change_pct * leverage
        
        liq_price = position_data.get("liq_price", 0)
        stop_loss = position_data.get("stop_loss", 0)
        take_profit = position_data.get("take_profit", 0)
        
        # Determine emoji based on actual PnL
        if unrealised_pnl > 0:
            emoji = "🔴" if side == "Sell" else "🟢"
        elif unrealised_pnl < 0:
            emoji = "🟢" if side == "Sell" else "🔴"
        else:
            emoji = "⚪"
            
        # Format the message
        message = f"<b>{emoji} {symbol}</b> ({side})\n"
        message += f"Size: {size} (${value:.2f})\n"
        message += f"Leverage: {leverage}x\n"
        message += f"Entry: ${entry_price:.4f}\n"
        message += f"Current: ${mark_price:.4f}\n"
        
        # PnL formatting
        if unrealised_pnl > 0:
            message += f"PnL: <b>+${unrealised_pnl:.2f}</b> (+{unrealised_pnl_pct:.2f}%)\n"
        elif unrealised_pnl < 0:
            message += f"PnL: <b>${unrealised_pnl:.2f}</b> ({unrealised_pnl_pct:.2f}%)\n"
        else:
            message += f"PnL: ${unrealised_pnl:.2f} (0.00%)\n"
            
        # Risk management levels
        message += f"Liquidation: ${liq_price:.4f}\n"
        if stop_loss > 0:
            message += f"Stop Loss: ${stop_loss:.4f}\n"
        if take_profit > 0:
            message += f"Take Profit: ${take_profit:.4f}\n"
            
        return message
    except Exception as e:
        logger.error(f"Error formatting position: {e}")
        return f"Error formatting position for {symbol}"

def format_all_positions():
    """Format all positions for display in Telegram - supports multi-account with individual sizes"""
    try:
        # Check if multi-account is enabled
        if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
            all_positions = trade_manager.get_active_positions_all_accounts()
            
            if not all_positions:
                # Show account summary even when no positions
                summary = trade_manager.multi_trader.get_account_summary()
                message = f"<b>📊 No Open Positions</b>\n\n"
                message += f"Trading: <b>{summary['trading_symbol']}</b>\n"
                message += f"Accounts: {summary['total_accounts']}\n"
                message += f"Combined Size: <b>${summary['total_position_usdt']} USDT</b>\n\n"
                
                for account_info in summary['accounts']:
                    if account_info['enabled']:
                        message += f"• {account_info['name']}: ${account_info['position_usdt']} USDT\n"
                
                return message
            
            message = f"<b>📊 ALL ACCOUNT POSITIONS</b>\n\n"
            
            total_accounts_pnl = 0
            total_accounts_value = 0
            
            for symbol, account_positions in all_positions.items():
                message += f"<b>{symbol}</b>\n"
                
                symbol_total_pnl = 0
                symbol_total_value = 0
                
                for pos in account_positions:
                    account = pos.get('account', 'unknown')
                    side = pos.get('side', 'Unknown')
                    size = pos.get('size', 0)
                    entry_price = pos.get('entry_price', 0)
                    mark_price = pos.get('mark_price', 0)
                    unrealised_pnl = float(pos.get('unrealised_pnl', 0))
                    leverage = pos.get('leverage', 1)
                    configured_usdt = pos.get('configured_position_usdt', 'unknown')
                    
                    # Calculate position value
                    position_value = float(size) * float(entry_price) if entry_price else 0
                    
                    # Calculate ROI percentage
                    roi_pct = 0
                    if entry_price and mark_price:
                        if side == "Buy":
                            roi_pct = ((float(mark_price) / float(entry_price)) - 1) * 100 * float(leverage)
                        else:  # Sell
                            roi_pct = ((float(entry_price) / float(mark_price)) - 1) * 100 * float(leverage)
                    
                    # Determine emoji
                    emoji = "🟢" if unrealised_pnl > 0 else "🔴" if unrealised_pnl < 0 else "⚪"
                    
                    message += f"  {emoji} <b>{account}</b> (${configured_usdt} USDT): {side} {size}\n"
                    message += f"    Entry: ${entry_price} | Current: ${mark_price}\n"
                    message += f"    PnL: ${unrealised_pnl:.2f} ({roi_pct:+.2f}%)\n"
                    
                    symbol_total_pnl += unrealised_pnl
                    symbol_total_value += position_value
                
                message += f"  <b>Symbol Total: ${symbol_total_pnl:.2f}</b>\n\n"
                
                total_accounts_pnl += symbol_total_pnl
                total_accounts_value += symbol_total_value
            
            # Add totals
            summary = trade_manager.multi_trader.get_account_summary()
            message += f"<b>🎯 GRAND TOTAL</b>\n"
            message += f"Total PnL: <b>${total_accounts_pnl:+.2f}</b>\n"
            message += f"Total Value: ${total_accounts_value:.2f}\n"
            message += f"Combined Size: ${summary['total_position_usdt']} USDT\n"
            message += f"Accounts: {summary['total_accounts']}\n"
            
        else:
            # Single account mode - use existing logic
            positions_data = get_positions()
            if not isinstance(positions_data, dict):
                positions_data = {}
                
            positions = positions_data.get("positions", {})
            last_update = positions_data.get("last_update", datetime.now().isoformat())
            
            if not positions:
                return "<b>📊 No Open Positions</b>\n\nNo positions are currently open."
                
            # Calculate total PnL
            total_pnl = sum(pos.get("unrealised_pnl", 0) for pos in positions.values())
            total_value = sum(pos.get("value", 0) for pos in positions.values())
            
            message = "<b>📊 CURRENT POSITIONS (Single Account)</b>\n\n"
            if total_pnl >= 0:
                message += f"Total PnL: <b>+${total_pnl:.2f}</b>\n"
            else:
                message += f"Total PnL: <b>${total_pnl:.2f}</b>\n"
                
            message += f"Total Position Value: ${total_value:.2f}\n"
            message += f"Positions: {len(positions)}\n\n"
            
            # Add each position
            for symbol, position in positions.items():
                message += format_position(symbol, position) + "\n"
        
        # Add timestamp
        message += f"\n<i>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        return message
        
    except Exception as e:
        logger.error(f"Error formatting positions: {e}")
        return f"Error getting positions: {str(e)}"

def format_signals():
    """
    Format all trading signals for display in Telegram.

    Returns:
        Formatted message
    """
    signals = get_signals()
    if not isinstance(signals, dict):
        signals = {}
    message = "<b>📈 CURRENT TRADING SIGNALS</b>\n\n"
    buy_signals = []
    sell_signals = []
    close_signals = []
    neutral_signals = []
    for symbol, signal_data in signals.items():
        if not isinstance(signal_data, dict):
            continue  # skip _last_update or any non-dict entry
        signal = signal_data.get("signal", "NEUTRAL")
        if signal == "BUY":
            buy_signals.append((symbol, signal_data))
        elif signal == "SELL":
            sell_signals.append((symbol, signal_data))
        elif signal == "CLOSE":
            close_signals.append((symbol, signal_data))
        else:
            neutral_signals.append((symbol, signal_data))
    # Format buy signals
    if buy_signals:
        message += "<b>🟢 BUY Signals:</b>\n"
        for symbol, signal_data in buy_signals:
            price = signal_data.get("price", 0)
            confidence = signal_data.get("ai_confidence", 0)
            trend = signal_data.get("trend", "Neutral")
            message += f"• {symbol} @ ${price:.4f} ({confidence:.0f}% confidence) - {trend}\n"
        message += "\n"
    # Format sell signals
    if sell_signals:
        message += "<b>🔴 SELL Signals:</b>\n"
        for symbol, signal_data in sell_signals:
            price = signal_data.get("price", 0)
            confidence = signal_data.get("ai_confidence", 0)
            trend = signal_data.get("trend", "Neutral")
            message += f"• {symbol} @ ${price:.4f} ({confidence:.0f}% confidence) - {trend}\n"
        message += "\n"
    # Format close signals
    if close_signals:
        message += "<b>⚠️ CLOSE Signals:</b>\n"
        for symbol, signal_data in close_signals:
            price = signal_data.get("price", 0)
            confidence = signal_data.get("ai_confidence", 0)
            trend = signal_data.get("trend", "Neutral")
            message += f"• {symbol} @ ${price:.4f} ({confidence:.0f}% confidence) - {trend}\n"
        message += "\n"
    # Format neutral signals (limit to 5 to avoid too long messages)
    if neutral_signals:
        message += f"<b>⚪ Neutral Signals:</b> {len(neutral_signals)} symbols\n"
        for symbol, signal_data in neutral_signals[:5]:
            price = signal_data.get("price", 0)
            message += f"• {symbol} @ ${price:.4f}\n"
        if len(neutral_signals) > 5:
            message += f"<i>... and {len(neutral_signals) - 5} more</i>\n"
    message += f"\n<i>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    return message

def format_bot_status():
    """
    Format bot status information for display in Telegram.
    
    Returns:
        Formatted message
    """
    try:
        logger.info("Starting format_bot_status function")
        
        # Test each step individually
        logger.info("Loading positions data...")
        positions_data = get_positions()
        logger.info(f"Positions data type: {type(positions_data)}")
        
        if not isinstance(positions_data, dict):
            positions_data = {}
        positions = positions_data.get("positions", {})
        logger.info(f"Positions count: {len(positions)}")
        
        logger.info("Loading signals data...")
        signals = get_signals()
        logger.info(f"Signals data type: {type(signals)}")
        
        if not isinstance(signals, dict):
            signals = {}
        logger.info(f"Signals keys: {list(signals.keys())}")
        
        logger.info("Building message...")
        message = "<b>🤖 TRADING BOT STATUS</b>\n\n"
        
        # System status
        message += "<b>System Status:</b>\n"
        message += "• Bot: Online ✅\n"
        message += f"• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        message += "<b>Available Commands:</b>\n"
        message += "• /help - Show all commands\n"
        message += "• /positions - Show positions\n"
        message += "• /signals - Show signals\n"
        message += "• /ping - Test connection\n"
        
        logger.info("Message built successfully")
        return message
        
    except Exception as e:
        logger.error(f"Error formatting bot status: {e}")
        logger.error(f"Exception type: {type(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"Error getting bot status: {str(e)}"

def handle_command(command, args=None, chat_id=None):
    """
    Handle a Telegram command.
    
    Args:
        command: Command string
        args: Optional arguments
        chat_id: Chat ID for martingale commands
        
    Returns:
        Response message
    """
    try:
        command = command.lower()
        
        # Check for martingale commands first
        if MARTINGALE_AVAILABLE:
            martingale_response = handle_martingale_commands(command, args, chat_id)
            if martingale_response:
                return martingale_response
        
        if command == "/help":
            message = "<b>📋 Available Commands</b>\n\n"
            
            # Use the main COMMANDS dictionary instead of duplicating
            # Basic commands (filter out specialized ones)
            basic_cmds = ["/help", "/status", "/signals", "/positions", "/position", "/close", "/enter", "/ping", "/reports"]
            auto_cmds = ["/auto_on", "/auto_off", "/auto_status"]
            account_cmds = ["/accounts", "/account_count", "/account_positions", "/close_all", "/sync_accounts", "/add_account"]
            session_cmds = ["/session_reset"]
            
            message += "<b>📊 Basic Commands:</b>\n"
            for cmd in basic_cmds:
                if cmd in COMMANDS:
                    message += f"• <code>{cmd}</code> - {COMMANDS[cmd]}\n"
            
            message += "\n<b>🤖 Auto Mode Commands:</b>\n"
            for cmd in auto_cmds:
                if cmd in COMMANDS:
                    message += f"• <code>{cmd}</code> - {COMMANDS[cmd]}\n"
            
            message += "\n<b>🏦 Multi-Account Commands:</b>\n"
            for cmd in account_cmds:
                if cmd in COMMANDS:
                    message += f"• <code>{cmd}</code> - {COMMANDS[cmd]}\n"
            
            message += "\n<b>⚙️ Session Commands:</b>\n"
            for cmd in session_cmds:
                if cmd in COMMANDS:
                    message += f"• <code>{cmd}</code> - {COMMANDS[cmd]}\n"
            
            # Martingale commands (if available)
            if MARTINGALE_AVAILABLE:
                message += "\n<b>📈 Martingale Commands:</b>\n"
                martingale_cmds = ["/add", "/martingale_status", "/martingale_log"]
                for cmd in martingale_cmds:
                    if cmd in COMMANDS:
                        message += f"• <code>{cmd}</code> - {COMMANDS[cmd]}\n"
            
            return message
            
        elif command == "/status":
            try:
                message = "<b>🤖 TRADING BOT STATUS</b>\n\n"
                message += "<b>System Status:</b>\n"
                message += "• Bot: Online ✅\n"
                message += f"• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                
                # Add martingale status if available
                if MARTINGALE_AVAILABLE:
                    message += "• Martingale: Available ✅\n"
                else:
                    message += "• Martingale: Not Available ❌\n"
                
                message += "\n<b>Available Commands:</b>\n"
                message += "• /help - Show all commands\n"
                message += "• /positions - Show positions\n"
                message += "• /signals - Show signals\n"
                message += "• /ping - Test connection\n"
                
                if MARTINGALE_AVAILABLE:
                    message += "• /add SYMBOL [MULTIPLIER] - Add to position\n"
                    message += "• /martingale_status - Show martingale status\n"
                
                return message
            except Exception as e:
                return f"Status error: {str(e)}"
            
        elif command == "/positions":
            return format_all_positions()
            
        elif command == "/signals":
            return format_signals()
            
        elif command == "/position":
            if not args:
                return "Please specify a symbol (e.g., /position BTCUSDT)"
            symbol = args[0].upper()
            
            try:
                import trade_manager
                
                # Check if multi-account is enabled
                if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
                    # Multi-account mode - show positions from all accounts
                    all_positions = trade_manager.get_active_positions_all_accounts()
                    
                    if symbol not in all_positions:
                        return f"❌ No open positions found for <b>{symbol}</b> across any account."
                    
                    account_positions = all_positions[symbol]
                    
                    message = f"<b>📊 {symbol} POSITIONS (Multi-Account)</b>\n\n"
                    
                    total_pnl = 0
                    total_value = 0
                    
                    for pos in account_positions:
                        account = pos['account']
                        side = pos['side']
                        size = pos['size']
                        entry_price = float(pos.get('entry_price', 0))
                        mark_price = float(pos.get('mark_price', 0))
                        unrealised_pnl = float(pos.get('unrealised_pnl', 0))
                        leverage = pos.get('leverage', 1)
                        configured_usdt = pos.get('configured_position_usdt', 'unknown')
                        
                        # Calculate ROI
                        roi_pct = 0
                        if entry_price > 0 and mark_price > 0:
                            if side == "Buy":
                                roi_pct = ((mark_price / entry_price) - 1) * 100 * float(leverage)
                            else:  # Sell
                                roi_pct = ((entry_price / mark_price) - 1) * 100 * float(leverage)
                        
                        position_value = float(size) * entry_price if entry_price else 0
                        
                        # Determine emoji
                        emoji = "🟢" if unrealised_pnl > 0 else "🔴" if unrealised_pnl < 0 else "⚪"
                        
                        message += f"{emoji} <b>{account}</b> (${configured_usdt} USDT)\n"
                        message += f"   Side: {side} | Size: {size}\n"
                        message += f"   Entry: ${entry_price:.4f} | Current: ${mark_price:.4f}\n"
                        message += f"   PnL: ${unrealised_pnl:.2f} ({roi_pct:+.2f}%)\n"
                        message += f"   Leverage: {leverage}x\n\n"
                        
                        total_pnl += unrealised_pnl
                        total_value += position_value
                    
                    message += f"<b>🎯 COMBINED TOTALS</b>\n"
                    message += f"Total PnL: <b>${total_pnl:+.2f}</b>\n"
                    message += f"Total Value: ${total_value:.2f}\n"
                    message += f"Accounts: {len(account_positions)}\n"
                    
                    return message
                
                else:
                    # Single account mode - use original logic
                    positions_data = get_positions()
                    if not isinstance(positions_data, dict):
                        positions_data = {}
                    positions = positions_data.get("positions", {})
                    if symbol in positions:
                        return format_position(symbol, positions[symbol])
                    else:
                        return f"No open position found for {symbol}"
            
            except Exception as e:
                logger.error(f"Error getting position for {symbol}: {e}")
                return f"❌ Error getting position for <b>{symbol}</b>: {str(e)}"
            
        elif command == "/close":
            if not args:
                return "Please specify a symbol to close (e.g., /close BTCUSDT)"
            
            symbol = args[0].upper()
            
            try:
                import trade_manager
                
                # Check if multi-account is enabled
                if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
                    # Multi-account mode - close positions on all accounts
                    logger.info(f"🏦 Multi-account mode: Closing positions for {symbol}")
                    
                    # Get positions from all accounts
                    all_positions = trade_manager.get_active_positions_all_accounts()
                    
                    if symbol not in all_positions:
                        return f"❌ No open positions found for <b>{symbol}</b> across any account."
                    
                    # Show confirmation message with all account details
                    account_positions = all_positions[symbol]
                    confirmation_message = f"🔄 <b>CLOSING MULTI-ACCOUNT POSITIONS</b>\n\n"
                    confirmation_message += f"Symbol: <b>{symbol}</b>\n"
                    confirmation_message += f"Accounts with positions: {len(account_positions)}\n\n"
                    
                    total_pnl = 0
                    for pos in account_positions:
                        account = pos['account']
                        side = pos['side']
                        size = pos['size']
                        pnl = float(pos.get('unrealised_pnl', 0))
                        total_pnl += pnl
                        confirmation_message += f"• {account}: {side} {size} (PnL: ${pnl:.2f})\n"
                    
                    confirmation_message += f"\n<b>Total PnL: ${total_pnl:.2f}</b>\n"
                    confirmation_message += f"⏳ Closing positions across all accounts..."
                    
                    send_telegram_message(confirmation_message)
                    
                    # Get the position side (should be same across all accounts)
                    position_side = account_positions[0]['side']
                    
                    # Execute close across all accounts
                    result = trade_manager.close_position_parallel(symbol, position_side)
                    
                    if result and result.get("multi_account"):
                        results = result.get("results", {})
                        success_count = result.get("success_count", 0)
                        total_count = result.get("total_count", 0)
                        
                        success_message = f"✅ <b>MULTI-ACCOUNT POSITIONS CLOSED</b>\n\n"
                        success_message += f"Symbol: <b>{symbol}</b>\n"
                        success_message += f"Success Rate: {success_count}/{total_count} accounts\n"
                        success_message += f"Final Total PnL: ${total_pnl:.2f}\n\n"
                        
                        # Show details for each account
                        for account_name, account_result in results.items():
                            if account_result.get("success"):
                                success_message += f"✅ {account_name}: Position closed\n"
                            else:
                                error = account_result.get("error", "Unknown error")
                                success_message += f"❌ {account_name}: {error}\n"
                        
                        success_message += f"\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        return success_message
                    else:
                        return f"❌ Failed to close positions for <b>{symbol}</b> across accounts"
                
                else:
                    # Single account mode - use original logic
                    from trade_manager import close_position, get_active_positions
                    
                    # Get current active positions
                    active_positions = get_active_positions()
                    
                    if symbol not in active_positions:
                        return f"❌ No open position found for <b>{symbol}</b>."
                    
                    # Get position details
                    position = active_positions[symbol]
                    position_side = position.get("side")
                    position_size = position.get("size", 0)
                    entry_price = position.get("entry_price", 0)
                    unrealized_pnl = position.get("unrealised_pnl", 0)
                    
                    if not position_side:
                        return f"❌ Invalid position data for <b>{symbol}</b>."
                    
                    # Show confirmation message first
                    confirmation_message = (
                        f"🔄 <b>CLOSING POSITION</b>\n\n"
                        f"Symbol: <b>{symbol}</b>\n"
                        f"Side: {position_side}\n"
                        f"Size: {position_size}\n"
                        f"Entry Price: ${entry_price:.4f}\n"
                        f"Unrealized PnL: ${unrealized_pnl:.2f}\n\n"
                        f"⏳ Closing position..."
                    )
                    send_telegram_message(confirmation_message)
                    
                    # Attempt to close the position
                    result = close_position(symbol, position_side)
                    
                    if result:
                        success_message = (
                            f"✅ <b>POSITION CLOSED SUCCESSFULLY</b>\n\n"
                            f"Symbol: <b>{symbol}</b>\n"
                            f"Side: {position_side}\n"
                            f"Size: {position_size}\n"
                            f"Final PnL: ${unrealized_pnl:.2f}\n"
                            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        return success_message
                    else:
                        error_message = (
                            f"❌ <b>FAILED TO CLOSE POSITION</b>\n\n"
                            f"Symbol: <b>{symbol}</b>\n"
                            f"Side: {position_side}\n"
                            f"Reason: API error or insufficient balance\n\n"
                            f"💡 Try again in a few moments or check your account status."
                        )
                        return error_message
            
            except ImportError:
                return "❌ Trade manager module not available. Position closing functionality disabled."
            except Exception as e:
                logger.error(f"Error closing position for {symbol}: {e}")
                return f"❌ Error closing position for <b>{symbol}</b>: {str(e)}"
            
        elif command == "/enter":
            if not args:
                return """
<b>🎯 ENTER NEW POSITIONS</b>

<b>Usage:</b>
<code>/enter SYMBOL SIDE</code>

<b>Examples:</b>
<code>/enter BTCUSDT Buy</code> - Open Buy position
<code>/enter BTCUSDT Sell</code> - Open Sell position

<b>Description:</b>
Opens a new trading position for the specified symbol and side using the trade manager.

<b>Note:</b> Position size and leverage will be determined by your trading configuration.
                """
            
            # Validate arguments
            if len(args) < 2:
                return "❌ /enter requires symbol and side (e.g., /enter BTCUSDT Buy)"
            
            symbol = args[0].upper()
            side = args[1].capitalize()
            
            # Validate side
            if side not in ["Buy", "Sell"]:
                return "❌ Invalid side. Use 'Buy' or 'Sell'"
            
            return execute_enter_position(symbol, side)
            
        elif command == "/ping":
            return "Pong! Bot is running."
            
        elif command == "/reports":
            message = "<b>📊 Reports</b>\n\n"
            positions_data = get_positions()
            if not isinstance(positions_data, dict):
                positions_data = {}
            positions = positions_data.get("positions", {})
            signals = get_signals()
            if not isinstance(signals, dict):
                signals = {}
            
            # Add position summary if positions exist
            if positions:
                total_pnl = sum(pos.get("unrealised_pnl", 0) for pos in positions.values())
                message += f"<b>Open Positions:</b> {len(positions)}\n"
                if total_pnl >= 0:
                    message += f"Overall PnL: +${total_pnl:.2f}\n\n"
                else:
                    message += f"Overall PnL: ${total_pnl:.2f}\n\n"
                
                # List positions briefly
                for symbol, pos in positions.items():
                    side = pos.get("side", "Unknown")
                    pnl = pos.get("unrealised_pnl", 0)
                    # Fix emoji logic for Sell positions
                    if side == "Sell":
                        emoji = "🔴" if pnl > 0 else "🟢" if pnl < 0 else "⚪"
                    else: # Buy position
                        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
                    message += f"{emoji} {symbol} ({side}): ${pnl:.2f}\n"
            else:
                message += "No open positions.\n\n"
            
            # Add signal summary
            if signals:
                buy_count = sum(1 for s in signals.values() if isinstance(s, dict) and s.get("signal") == "BUY")
                sell_count = sum(1 for s in signals.values() if isinstance(s, dict) and s.get("signal") == "SELL")
                message += f"\n<b>Active Signals:</b>\n"
                message += f"• BUY signals: {buy_count}\n"
                message += f"• SELL signals: {sell_count}\n\n"
            
            # Add available commands
            message += "<b>Available commands:</b>\n"
            message += "• /positions - Detailed position information\n"
            message += "• /signals - View all trading signals\n"
            message += "• /status - Complete bot status\n"
            
            if MARTINGALE_AVAILABLE:
                message += "• /add SYMBOL [MULTIPLIER] - Add to position\n"
                message += "• /martingale_status - Show martingale status\n"
            
            return message
            
        elif command == "/auto_on":
            set_auto_mode(True)
            send_telegram_message("🤖 AUTO MODE is now <b>ON</b>. AI will take trades automatically.")
            return "AUTO MODE is now ON."
        elif command == "/auto_off":
            set_auto_mode(False)
            send_telegram_message("🛑 AUTO MODE is now <b>OFF</b>. Manual confirmation required for trades.")
            return "AUTO MODE is now OFF."
        elif command == "/auto_status":
            mode = get_auto_mode()
            msg = "🤖 AUTO MODE is <b>ON</b>." if mode else "🛑 AUTO MODE is <b>OFF</b>."
            send_telegram_message(msg)
            return msg
            
        elif command == "/session_reset":
            if STANDALONE_MODE:
                # Force session reset using same logic as s1.py startup
                initialize_session_state_file_standalone()
                session_changed, current_session, session_state = check_session_change_standalone()
                
                now_utc = datetime.now(timezone.utc)
                session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
                session_name = session_names.get(current_session, "No session") if current_session else "No session"
                
                message = f"<b>🔄 SESSION RESET COMPLETE</b>\n\n"
                message += f"⏰ <b>Current UTC:</b> {now_utc.strftime('%H:%M:%S')}\n"
                message += f"📊 <b>Current Session:</b> {session_name}\n"
                message += f"🔄 <b>Trade Counters:</b> Reset for all symbols\n"
                message += f"✅ <b>Session State:</b> Synchronized"
                
                return message
            else:
                return "❌ Session reset only available in standalone mode"
            
        elif command == "/accounts":
            return handle_accounts_command()
            
        elif command == "/account_count":
            return handle_account_count_command()
            
        elif command == "/positions_all":
            # This is the same as /positions but with explicit multi-account formatting
            return format_all_positions()
            
        elif command == "/add_account":
            return handle_add_account_command()
            
        elif command == "/close_all":
            try:
                import trade_manager
                
                if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
                    all_positions = trade_manager.get_active_positions_all_accounts()
                    
                    if not all_positions:
                        return "❌ No open positions found across any account."
                    
                    confirmation_message = f"�� <b>CLOSING ALL POSITIONS</b>\n\n"
                    confirmation_message += f"Symbols: {', '.join(all_positions.keys())}\n"
                    
                    total_accounts = sum(len(positions) for positions in all_positions.values())
                    confirmation_message += f"Total positions: {total_accounts}\n\n"
                    confirmation_message += f"⏳ Closing all positions..."
                    
                    send_telegram_message(confirmation_message)
                    
                    results = {}
                    for symbol, account_positions in all_positions.items():
                        position_side = account_positions[0]['side']  # Should be same across accounts
                        result = trade_manager.close_position_parallel(symbol, position_side)
                        results[symbol] = result
                    
                    # Build summary message
                    success_message = f"✅ <b>ALL POSITIONS CLOSED</b>\n\n"
                    total_success = 0
                    total_attempts = 0
                    
                    for symbol, result in results.items():
                        if result and result.get("multi_account"):
                            success_count = result.get("success_count", 0)
                            total_count = result.get("total_count", 0)
                            total_success += success_count
                            total_attempts += total_count
                            success_message += f"{symbol}: {success_count}/{total_count}\n"
                    
                    success_message += f"\n<b>Overall: {total_success}/{total_attempts} accounts</b>\n"
                    success_message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    return success_message
                else:
                    return "❌ Multi-account mode not enabled."
                    
            except Exception as e:
                logger.error(f"Error closing all positions: {e}")
                return f"❌ Error closing all positions: {str(e)}"

        elif command == "/account_positions":
            try:
                import trade_manager
                
                if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
                    all_positions = trade_manager.get_active_positions_all_accounts()
                    
                    if not all_positions:
                        summary = trade_manager.multi_trader.get_account_summary()
                        message = f"<b>📊 No Open Positions</b>\n\n"
                        for account_info in summary['accounts']:
                            message += f"• {account_info['name']}: ${account_info['position_usdt']} USDT ready\n"
                        return message
                    
                    # Group by account instead of by symbol
                    account_positions = {}
                    for symbol, positions in all_positions.items():
                        for pos in positions:
                            account = pos['account']
                            if account not in account_positions:
                                account_positions[account] = []
                            account_positions[account].append({**pos, 'symbol': symbol})
                    
                    message = f"<b>🏦 POSITIONS BY ACCOUNT</b>\n\n"
                    
                    grand_total_pnl = 0
                    
                    for account_name, positions in account_positions.items():
                        account_total_pnl = sum(float(pos.get('unrealised_pnl', 0)) for pos in positions)
                        grand_total_pnl += account_total_pnl
                        
                        emoji = "🟢" if account_total_pnl > 0 else "🔴" if account_total_pnl < 0 else "⚪"
                        
                        message += f"{emoji} <b>{account_name}</b> (${account_total_pnl:+.2f})\n"
                        
                        for pos in positions:
                            symbol = pos['symbol']
                            side = pos['side']
                            size = pos['size']
                            pnl = float(pos.get('unrealised_pnl', 0))
                            message += f"   {symbol}: {side} {size} (${pnl:+.2f})\n"
                        
                        message += "\n"
                    
                    message += f"<b>🎯 GRAND TOTAL: ${grand_total_pnl:+.2f}</b>\n"
                    message += f"<i>Updated: {datetime.now().strftime('%H:%M:%S')}</i>"
                    
                    return message
                else:
                    return "❌ Multi-account mode not enabled."
                    
            except Exception as e:
                logger.error(f"Error getting account positions: {e}")
                return f"❌ Error getting account positions: {str(e)}"

        elif command == "/sync_accounts":
            try:
                import trade_manager
                
                if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.multi_trader:
                    # Test all connections
                    connection_results = trade_manager.test_all_account_connections()
                    
                    message = f"🔄 <b>ACCOUNT SYNC COMPLETE</b>\n\n"
                    
                    connected_count = 0
                    for account_name, status_info in connection_results.items():
                        status = status_info.get("status", "unknown")
                        if status == "connected":
                            emoji = "✅"
                            connected_count += 1
                            status_text = "Connected & Synced"
                        else:
                            emoji = "❌"
                            error = status_info.get("error", "Unknown error")
                            status_text = f"Error: {error[:30]}..."
                        
                        message += f"{emoji} {account_name}: {status_text}\n"
                    
                    message += f"\n<b>Result: {connected_count}/{len(connection_results)} accounts synced</b>\n"
                    message += f"<i>Synced at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
                    
                    return message
                else:
                    return "❌ Multi-account mode not enabled."
                    
            except Exception as e:
                logger.error(f"Error syncing accounts: {e}")
                return f"❌ Error syncing accounts: {str(e)}"
            
        else:
            return f"Unknown command: {command}\nType /help to see available commands."
            
    except Exception as e:
        logger.error(f"Error handling command {command}: {e}")
        return "Error processing command"

def save_telegram_state(last_update_id):
    """Save the last processed update ID to avoid reprocessing messages."""
    try:
        state = {"last_update_id": last_update_id}
        with open(TELEGRAM_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"Error saving telegram state: {e}")

def load_telegram_state():
    """Load the last processed update ID."""
    try:
        if os.path.exists(TELEGRAM_STATE_FILE):
            with open(TELEGRAM_STATE_FILE, "r") as f:
                state = json.load(f)
                return state.get("last_update_id", 0)
    except Exception as e:
        logger.error(f"Error loading telegram state: {e}")
    return 0

def clear_telegram_queue():
    """Clear all pending Telegram messages without processing them."""
    try:
        # Get the latest update ID and mark all as processed
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            updates = response.json().get("result", [])
            if updates:
                latest_id = max(update.get("update_id", 0) for update in updates)
                # Mark all as processed by setting offset to latest_id + 1
                clear_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
                clear_params = {"offset": latest_id + 1, "limit": 1}
                requests.get(clear_url, params=clear_params, timeout=10)
                save_telegram_state(latest_id)
                logger.info(f"Cleared {len(updates)} pending messages, latest ID: {latest_id}")
                return latest_id
    except Exception as e:
        logger.error(f"Error clearing telegram queue: {e}")
    return 0

def process_telegram_updates(last_update_id=None):
    """
    Process incoming Telegram updates (messages, commands).
    
    Args:
        last_update_id: ID of the last processed update (if None, loads from state)
        
    Returns:
        New last_update_id
    """
    if last_update_id is None:
        last_update_id = load_telegram_state()
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return last_update_id
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {
            "offset": last_update_id + 1,
            "timeout": 30
        }
        
        print(f"🔍 POLLING: Checking for messages...")
        logger.info(f"Checking for new Telegram messages (last_update_id={last_update_id})")
        
        # Add connection retry logic with exponential backoff
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, timeout=35)
                break  # Success, exit retry loop
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, 
                    requests.exceptions.RequestException) as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise e  # Re-raise the exception
                
                wait_time = (2 ** attempt) * 5  # Exponential backoff: 5, 10, 20 seconds
                print(f"🔄 CONNECTION RETRY: Attempt {attempt + 1}/{max_retries} failed. Retrying in {wait_time}s...")
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        if response.status_code == 200:
            updates = response.json().get("result", [])
            logger.info(f"Received {len(updates)} new updates from Telegram")
            
            if updates:
                logger.debug(f"Updates data: {json.dumps(updates)}")
            
            for update in updates:
                update_id = update.get("update_id", 0)
                logger.info(f"Processing update ID: {update_id}")
                
                # Update last_update_id to acknowledge this update
                if update_id > last_update_id:
                    last_update_id = update_id
                    
                # Check for messages or channel posts
                message = update.get("message") or update.get("channel_post")
                if not message:
                    logger.debug(f"No message or channel_post in update: {update}")
                    continue
                    
                # Get chat information and from user info
                chat = message.get("chat", {})
                chat_id = chat.get("id", "")
                chat_type = chat.get("type", "")
                user_info = message.get("from", {})
                user_id = user_info.get("id", "")
                username = user_info.get("username", "unknown")
                
                logger.info(f"Received message from chat ID: {chat_id}, type: {chat_type}, user: {username}")
                
                # Check if it's a command or normal text
                text = message.get("text", "").strip()
                if not text:
                    logger.debug("Message contains no text, skipping")
                    continue
                    
                logger.info(f"Message text: {text}")
                
                # Store message for context in standalone mode
                store_recent_message(text)

                # Check for ENTER or SKIP with symbol
                if text.startswith("ENTER ") or text.startswith("SKIP "):
                    logger.info(f"Processing confirmation command: {text}")
                    parts = text.split()
                    if len(parts) == 2:
                        action, symbol = parts
                        symbol = symbol.upper()
                        logger.info(f"Action: {action}, Symbol: {symbol}")
                        
                        # Load pending signals
                        pending = {}
                        if os.path.exists("pending_signals.json"):
                            with open("pending_signals.json", "r") as f:
                                pending = json.load(f)
                            logger.info(f"Loaded {len(pending)} pending signals: {list(pending.keys())}")
                        else:
                            logger.warning("No pending_signals.json file found")
                        
                        # Check if symbol is in pending signals (normal operation)
                        if symbol in pending:
                            logger.info(f"Found pending signal for {symbol}")
                            signal_data = pending[symbol]
                            if action == "ENTER":
                                # Approve: write to all_trade_signals.json
                                signals = get_signals()
                                signals[symbol] = signal_data
                                with open("all_trade_signals.json", "w") as f:
                                    json.dump(signals, f, indent=2)
                                
                                # INCREMENT SESSION COUNTER FOR MANUAL CONFIRMATION (NEW ADDITION)
                                signal_type = signal_data.get("signal")
                                if signal_type in ["BUY", "SELL"]:
                                    try:
                                        # Import the session management functions
                                        from s1 import increment_session_counter_on_execution
                                        success = increment_session_counter_on_execution(symbol, signal_type)
                                        if success:
                                            print(f"🎯 SESSION TRADE CONFIRMED: {signal_type} for {symbol}")
                                        else:
                                            print(f"⚠️ Failed to increment session counter for {symbol}")
                                    except ImportError:
                                        print(f"⚠️ Could not import session management functions")
                                    except Exception as e:
                                        print(f"⚠️ Error incrementing session counter: {e}")
                                
                                if signal_data.get("signal") == "CLOSE":
                                    send_telegram_message(f"✅ Position for <b>{symbol}</b> has been <b>CLOSED</b>.")
                                else:
                                    send_telegram_message(f"✅ Trade for <b>{symbol}</b> has been <b>ENTERED</b>.")
                                
                                # Check if this is a CLOSE signal and execute position closing directly
                                if signal_data.get("signal") == "CLOSE":
                                    try:
                                        # Import trade_manager module
                                        from trade_manager import close_position, get_active_positions
                                        
                                        # Get positions to find the side
                                        positions = get_active_positions()
                                        if symbol in positions:
                                            position = positions[symbol]
                                            position_side = position.get("side")
                                            
                                            # Close the position
                                            result = close_position(symbol, position_side)
                                            
                                            if result:
                                                send_telegram_message(f"✅ Position for <b>{symbol}</b> has been closed successfully.")
                                                print(f"Position for {symbol} has been closed successfully.")
                                            else:
                                                send_telegram_message(f"❌ Failed to close position for <b>{symbol}</b>. The trading watchdog will try again.")
                                                print(f"Failed to close position for {symbol}. The trading watchdog will try again.")
                                        else:
                                            send_telegram_message(f"⚠️ No open position found for <b>{symbol}</b>.")
                                            print(f"No open position found for {symbol}.")
                                    except ImportError:
                                        send_telegram_message(f"❌ Could not import trade_manager module. Position closing will be handled by the trading watchdog.")
                                        print(f"Could not import trade_manager module. Position closing will be handled by the trading watchdog.")
                                    except Exception as e:
                                        send_telegram_message(f"❌ Error closing position for <b>{symbol}</b>: {str(e)}")
                                        print(f"Error closing position for {symbol}: {e}")
                            else:
                                send_telegram_message(f"❌ Trade for <b>{symbol}</b> has been <b>SKIPPED</b> and will not be executed.")
                                print(f"❌ Trade for {symbol} has been SKIPPED and will not be executed.")
                            # Remove from pending
                            del pending[symbol]
                            with open("pending_signals.json", "w") as f:
                                json.dump(pending, f, indent=2)
                            continue
                        
                        # STANDALONE MODE: Handle direct ENTER command when no pending signals
                        elif STANDALONE_MODE and action == "ENTER":
                            logger.info(f"Processing direct ENTER command in standalone mode for {symbol}")
                            
                            # Get recent message context for analysis
                            analysis_context = get_recent_analysis_context()
                            
                            logger.info(f"Analysis context for {symbol}: {analysis_context[:200] if analysis_context else 'None'}...")
                            
                            # Process the direct trade command with validation
                            success = process_direct_trade_command(symbol, analysis_context)
                            if success:
                                logger.info(f"Direct trade command executed successfully for {symbol}")
                            else:
                                logger.info(f"Direct trade command rejected for {symbol}")
                            continue
                        
                        # STANDALONE MODE: Handle SKIP command
                        elif STANDALONE_MODE and action == "SKIP":
                            logger.info(f"Processing SKIP command in standalone mode for {symbol}")
                            send_telegram_message(f"✅ Trade for <b>{symbol}</b> has been <b>SKIPPED</b>.")
                            continue
                        
                        else:
                            # Symbol not found in pending and not in standalone mode
                            available = list(pending.keys()) if pending else []
                            logger.warning(f"Symbol {symbol} not in pending. Available: {available}")
                            if STANDALONE_MODE:
                                send_telegram_message(f"No pending trade signal for {symbol}.\nIn standalone mode, only respond to ENTER/SKIP after receiving a proper trade confirmation request.")
                            else:
                                send_telegram_message(f"No pending trade signal for {symbol}.\nAvailable: {available}")
                            print(f"No pending trade signal for {symbol}.")
                            continue
                
                if text.startswith('/'):
                    # It's a command
                    logger.info(f"Command detected: {text}")
                    
                    # Extract command and arguments
                    parts = text.split()
                    command = parts[0].lower()
                    args = parts[1:] if len(parts) > 1 else None
                    
                    # Handle the command (now passing chat_id for martingale commands)
                    logger.info(f"Handling command: {command} with args: {args}")
                    response_text = handle_command(command, args, chat_id)
                    
                    # Send the response
                    logger.info(f"Sending command response to chat ID: {chat_id}")
                    result = send_telegram_message(response_text, chat_id=chat_id)
                    logger.info(f"Send result: {result}")
                else:
                    # It's a regular message, not a command
                    logger.debug(f"Regular message (not a command): {text}")
                    # Optionally handle non-command messages here
                
        else:
            logger.error(f"Failed to get updates. Status code: {response.status_code}")
            logger.error(f"Response: {response.text}")
            
    except Exception as e:
        logger.error(f"Error processing Telegram updates: {e}")
        traceback.print_exc()
        
    # At the end of the function, save the state
    save_telegram_state(last_update_id)
    return last_update_id

def run_telegram_bot_with_shutdown(shutdown_flag=None):
    """
    Run the Telegram bot with shutdown flag support and session monitoring.
    """
    logger.info("Starting Telegram bot...")
    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured. Bot will not run.")
        return
    
    # Validate configuration first with retry logic (make it more forgiving)
    max_validation_retries = 2
    validation_success = False
    for attempt in range(max_validation_retries):
        try:
            # Test API connectivity
            test_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
            test_response = requests.get(test_url, timeout=10)
            if test_response.status_code != 200:
                logger.error(f"Telegram bot token invalid. Status: {test_response.status_code}")
                return
            else:
                bot_info = test_response.json()
                logger.info(f"Telegram bot validated: {bot_info.get('result', {}).get('username', 'Unknown')}")
                validation_success = True
                break  # Success, exit retry loop
        except Exception as e:
            if attempt == max_validation_retries - 1:  # Last attempt
                logger.warning(f"Failed to validate Telegram bot after {max_validation_retries} attempts: {e}")
                logger.info("🔄 VALIDATION SKIPPED: Bot will start anyway - network may recover during runtime")
                print("⚠️ TELEGRAM VALIDATION FAILED: Starting bot anyway - network may recover")
                break  # Continue anyway, network might recover
            
            wait_time = 5
            logger.warning(f"Validation attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)

    # Set up the bot commands (make this optional if network is down)
    if validation_success:
        try:
            logger.info("Setting up bot commands with Telegram...")
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
            command_data = []
            
            # Format commands for the API
            for cmd, description in COMMANDS.items():
                command_data.append({
                    "command": cmd.replace("/", ""),
                    "description": description
                })
                
            payload = {
                "commands": command_data
            }
            
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Bot commands registered successfully")
            else:
                logger.error(f"Failed to register bot commands: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.warning(f"Error setting up bot commands: {e} - Commands will be set up when network recovers")
    
    # Process updates in a loop with session monitoring
    last_update_id = 0
    consecutive_errors = 0
    max_consecutive_errors = 20
    network_error_count = 0
    total_network_errors = 0
    
    # Session monitoring variables
    last_session_check = time.time()
    
    # Adaptive sleep timing
    current_sleep = 1
    max_sleep = 30
    
    try:
        print("🤖 TELEGRAM BOT: Starting resilient polling mode with session monitoring...")
        logger.info("Starting resilient Telegram polling mode with session monitoring")
        
        # Initialize session monitoring on startup
        if STANDALONE_MODE:
            logger.info("📊 Session monitoring enabled for standalone mode")
            monitor_session_changes()  # Initial check
        
        while not (shutdown_flag and shutdown_flag.is_set()):
            try:
                # ====== SESSION MANAGEMENT: CHECK FOR SESSION CHANGES ====== (EXACT COPY FROM s1.py)
                # Check for session changes frequently to ensure timely detection (same as s1.py WebSocket handler)
                if STANDALONE_MODE:
                    session_changed, current_session, session_state = check_session_change_standalone()
                
                # Process telegram updates
                last_update_id = process_telegram_updates(last_update_id)
                consecutive_errors = 0
                network_error_count = 0
                current_sleep = 1
                time.sleep(current_sleep)
                
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                network_error_count += 1
                consecutive_errors += 1
                total_network_errors += 1
                
                # Adaptive backoff - increase sleep time during network issues
                current_sleep = min(current_sleep * 1.5, max_sleep)
                
                logger.error(f"Network error in main loop (consecutive: {consecutive_errors}, total: {total_network_errors}): {e}")
                print(f"🌐 NETWORK ISSUE: Connection problem. Waiting {current_sleep:.1f}s before retry... (Total errors: {total_network_errors})")
                
                # Only stop if we have WAY too many consecutive errors (something is fundamentally broken)
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Excessive consecutive errors suggest a fundamental problem. Stopping bot...")
                    print("❌ CRITICAL ERROR: Too many consecutive failures. Telegram bot stopped.")
                    break
                
                time.sleep(current_sleep)
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Unexpected error in update loop ({consecutive_errors}/{max_consecutive_errors}): {e}")
                print(f"⚠️ UNEXPECTED ERROR: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive unexpected errors. Stopping bot...")
                    print("❌ CRITICAL ERROR: Too many unexpected errors. Telegram bot stopped.")
                    break
                
                time.sleep(min(consecutive_errors * 2, 10))
                
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
        print("🛑 TELEGRAM BOT: Stopped by user (Ctrl+C)")
    finally:
        logger.info("Telegram bot shutdown complete")
        print("📴 TELEGRAM BOT: Shutdown complete")

def run_telegram_bot():
    """
    Run the Telegram bot in a loop with enhanced error handling.
    Original function maintained for backward compatibility.
    """
    return run_telegram_bot_with_shutdown()

# Standalone functions that can be imported by the main script

def send_trading_signal(symbol, signal_data):
    """
    Send a trading signal to the Telegram channel.
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        signal_data: Dictionary with signal data
    """
    try:
        # Ensure we have the required data
        if not isinstance(signal_data, dict):
            print(f"Invalid signal data for {symbol}")
            return False
            
        # Extract signal information
        signal = signal_data.get("signal", "NEUTRAL")
        trend = signal_data.get("trend", "Neutral")
        price = signal_data.get("price", 0)
        timestamp = signal_data.get("timestamp", datetime.now().isoformat())
        crossover_direction = signal_data.get("crossover_direction")
        ai_confidence = signal_data.get("ai_confidence", 0)
        
        # Ensure we have the correct verified trend data
        # Get the AI analysis from the signal data
        ai_analysis = signal_data.get("ai_analysis", {})
        
        # Extract verified timeframe data if available
        verified_timeframes = {}
        if "timeframe_trends" in signal_data:
            verified_timeframes = signal_data.get("timeframe_trends", {})
            # This will ensure we're using the same trend data the AI used
        
        # Format the signal emoji
        signal_emoji = "🟡"  # Default neutral
        if signal == "BUY":
            signal_emoji = "🟢"
        elif signal == "SELL":
            signal_emoji = "🔴"
        elif signal == "CLOSE":
            signal_emoji = "⚪"
            
        # Format the crossover direction emoji
        crossover_emoji = "↔️"  # Default no crossover
        if crossover_direction == "bullish":
            crossover_emoji = "↗️"
        elif crossover_direction == "bearish":
            crossover_emoji = "↘️"
            
        # Format the timeframes section
        timeframes_str = ""
        if "timeframes" in signal_data:
            timeframes = signal_data.get("timeframes", {})
            for tf, tf_trend in timeframes.items():
                # Use verified timeframe data if available
                if tf in verified_timeframes:
                    tf_trend = verified_timeframes[tf]
                
                # Format emoji based on trend
                if "Strong Bullish" in tf_trend:
                    tf_emoji = "🟢🟢"
                elif "Bullish" in tf_trend:
                    tf_emoji = "🟢"
                elif "Strong Bearish" in tf_trend:
                    tf_emoji = "🔴🔴"
                elif "Bearish" in tf_trend:
                    tf_emoji = "🔴"
                else:
                    tf_emoji = "⚪"
                    
                timeframes_str += f"{tf_emoji} {tf}: {tf_trend}\n"
        
        # Format timestamp
        try:
            dt = datetime.fromisoformat(timestamp)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except:
            formatted_time = str(timestamp)
            
        # Get AI analysis snippet
        ai_snippet = ""
        if ai_analysis and isinstance(ai_analysis, dict):
            ai_text = ai_analysis.get("analysis", "")
            if ai_text:
                # Find the recommendation section at the end
                recommendation_lines = []
                lines = ai_text.split('\n')
                for i, line in enumerate(reversed(lines)):
                    if line.startswith("Recommendation:"):
                        recommendation_lines.append(line)
                        break
                    if "Recommendation:" in line:
                        recommendation_lines.append(line[line.index("Recommendation:"):])
                        break
                    if i < 10 and line.strip():  # Get up to 10 non-empty lines from the end
                        recommendation_lines.append(line)
                
                # Format the recommendation section
                if recommendation_lines:
                    ai_snippet = '\n'.join(reversed(recommendation_lines))
                else:
                    # If no recommendation found, use last few lines
                    ai_snippet = '\n'.join(lines[-3:]) if len(lines) > 3 else ai_text[-200:]
        
        # Build message
        message = f"🚨 TRADING SIGNAL: {symbol}\n\n"
        message += f"Signal: {signal_emoji} {signal} (Confidence: {ai_confidence}%)\n"
        message += f"Price: ${price}\n"
        message += f"Trend: {trend}\n"
        message += f"Crossover: {crossover_emoji} {crossover_direction.upper() if crossover_direction else 'NONE'}\n\n"
        
        # Add timeframes section
        if timeframes_str:
            message += f"Timeframes:\n{timeframes_str}\n"
            
        # Add AI analysis if available
        if ai_snippet:
            message += f"AI Analysis:\n{ai_snippet}\n\n"
            
        message += f"Generated: {formatted_time}"
        
        # Send to Telegram bot
        return send_telegram_message(message)
        
    except Exception as e:
        print(f"Error sending trading signal: {e}")
        traceback.print_exc()
        return False

def send_crossover_alert(symbol, timeframe, direction, price, diff):
    """
    Send a crossover alert to Telegram.
    
    Args:
        symbol: Trading symbol
        timeframe: Timeframe where crossover occurred
        direction: Direction of crossover (bullish or bearish)
        price: Current price
        diff: EMA difference
        
    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        crossover_emoji = "↗️" if direction == "bullish" else "↘️"
        message = f"<b>⚠️ EMA CROSSOVER DETECTED: {symbol}</b>\n\n"
        message += f"<b>Direction: {crossover_emoji} {direction.upper()}</b>\n"
        message += f"Timeframe: {timeframe}\n"
        message += f"Price: <code>${price:.6g}</code>\n"
        message += f"EMA Difference: {diff:.6g}\n\n"
        message += "<i>Waiting for AI analysis to confirm signal...</i>"
        
        return send_telegram_message(message)
    except Exception as e:
        logger.error(f"Error sending crossover alert: {e}")
        return False

def send_bot_status():
    """
    Send bot status information to Telegram.
    
    Returns:
        True if message was sent successfully, False otherwise
    """
    message = format_bot_status()
    return send_telegram_message(message)

def escape_html(text):
    """Escape HTML characters for safe Telegram message formatting."""
    if not text:
        return ""
    return html.escape(str(text))

def send_trade_confirmation_request(symbol, signal_data):
    """
    Send a trade signal to Telegram for manual confirmation.
    """
    signal = signal_data.get("signal", "NEUTRAL")
    price = signal_data.get("price", 0)
    trend = signal_data.get("trend", "Neutral")
    confidence = signal_data.get("ai_confidence", 0)
    ai_analysis = signal_data.get("ai_analysis", {}).get("analysis", "")
    
    # HTML escape the AI analysis to prevent parsing errors
    ai_analysis_escaped = escape_html(ai_analysis)
    
    # Custom message for CLOSE signals
    if signal == "CLOSE":
        message = (
            f"<b>🟡 CLOSE POSITION CONFIRMATION REQUIRED</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Action: <b>CLOSE POSITION</b>\n"
            f"Price: <code>${price:.6g}</code>\n"
            f"Trend: {trend}\n"
            f"Confidence: {confidence}%\n"
            f"\nAI Analysis:\n{ai_analysis_escaped}\n"
            "\n<b>Reply with:</b>\n"
            f"<code>ENTER {symbol}</code> to approve and close the position\n"
            f"<code>SKIP {symbol}</code> to keep the position open"
        )
    else:
        message = (
            f"<b>🟡 TRADE CONFIRMATION REQUIRED</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Signal: <b>{signal}</b>\n"
            f"Price: <code>${price:.6g}</code>\n"
            f"Trend: {trend}\n"
            f"Confidence: {confidence}%\n"
            f"\nAI Analysis:\n{ai_analysis_escaped}\n"
            "\n<b>Reply with:</b>\n"
            f"<code>ENTER {symbol}</code> to approve and execute the trade\n"
            f"<code>SKIP {symbol}</code> to ignore this signal"
        )
    send_telegram_message(message)

def get_auto_mode():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        return config.get("auto_mode", False)
    except Exception:
        return False

def set_auto_mode(value: bool):
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        config["auto_mode"] = value
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        # If turning AUTO ON, process all pending signals
        if value:
            process_pending_signals_auto()
    except Exception as e:
        print(f"Error setting auto_mode: {e}")

def process_pending_signals_auto():
    try:
        if os.path.exists("pending_signals.json"):
            with open("pending_signals.json", "r") as f:
                pending = json.load(f)
            if pending:
                # Load current signals
                if os.path.exists("all_trade_signals.json"):
                    with open("all_trade_signals.json", "r") as f:
                        signals = json.load(f)
                else:
                    signals = {}
                for symbol, signal_data in pending.items():
                    signals[symbol] = signal_data
                    send_telegram_message(f"✅ [AUTO MODE] Trade for <b>{symbol}</b> has been <b>ENTERED</b> automatically.")
                # Save updated signals
                with open("all_trade_signals.json", "w") as f:
                    json.dump(signals, f, indent=2)
                # Clear pending signals
                with open("pending_signals.json", "w") as f:
                    json.dump({}, f)
    except Exception as e:
        print(f"Error processing pending signals in AUTO mode: {e}")

def safe_read_json(file_path):
    """Safely read a JSON file with error handling."""
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding='utf-8') as f:
                return json.load(f), True
        return {}, False
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return {}, False

def safe_write_json(file_path, data):
    """Safely write a JSON file with error handling."""
    try:
        with open(file_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error writing {file_path}: {e}")
        return False

def get_current_session_standalone():
    """Determine the current trading session based on UTC time with clean handoffs"""
    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour
    current_minute = now_utc.minute
    
    # NY Session: 13:30-20:59 UTC
    if (current_hour > NY_START or (current_hour == NY_START and current_minute >= NY_START_MINUTES)) and current_hour < NY_END:
        return "NY"
    
    # London Session: 07:00-13:29 UTC (ends when NY starts)  
    if LONDON_START <= current_hour < NY_START or (current_hour == NY_START and current_minute < NY_START_MINUTES):
        return "LONDON"
    
    # Tokyo Session: 00:00-06:59 UTC (ends when London starts)
    if current_hour < LONDON_START:
        return "TOKYO"
    
    # No active session: 21:00-23:59 UTC
    return None

def get_session_state_standalone():
    """Load current session state from file"""
    default_state = {
        "current_session": None,
        "session_start_time": None,
        "trades_taken_this_session": {},
        "last_session_change": None
    }
    
    data, success = safe_read_json(SESSION_STATE_FILE)
    if success:
        # Merge with defaults to handle missing keys
        for key, value in default_state.items():
            if key not in data:
                data[key] = value
        
        # Convert old format (integer) to new format (dict) if needed
        if isinstance(data.get("trades_taken_this_session"), int):
            data["trades_taken_this_session"] = {}
            
        return data
    
    return default_state

def save_session_state_standalone(state):
    """Save session state to file"""
    return safe_write_json(SESSION_STATE_FILE, state)

def check_session_change_standalone():
    """
    Check if we've entered a new trading session and handle session transitions
    
    Returns:
        tuple: (session_changed, current_session, session_state)
    """
    current_session = get_current_session_standalone()
    session_state = get_session_state_standalone()
    
    session_changed = False
    
    # Check if session has changed
    if current_session != session_state.get("current_session"):
        session_changed = True
        now_utc = datetime.now(timezone.utc)
        
        # Only set session_start_time if we're ENTERING a session, not exiting
        if current_session:  # Entering a session
            # Calculate the actual session start time based on current session
            actual_session_start = None
            if current_session == "TOKYO":
                # Tokyo starts at 00:00 UTC
                today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                actual_session_start = today_utc
            elif current_session == "LONDON":
                # London starts at 07:00 UTC
                today_utc = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)
                actual_session_start = today_utc
            elif current_session == "NY":
                # NY starts at 13:30 UTC
                today_utc = now_utc.replace(hour=13, minute=30, second=0, microsecond=0)
                actual_session_start = today_utc
            
            # Check if this is a REAL session transition or just bot startup
            minutes_since_actual_start = (now_utc - actual_session_start).total_seconds() / 60
            
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            
            if minutes_since_actual_start <= SESSION_WAIT_MINUTES:
                # Session started recently - ENTERING NEW SESSION
                session_state.update({
                    "current_session": current_session,
                    "session_start_time": actual_session_start.isoformat(),  # Set wait period
                    "trades_taken_this_session": {},
                    "last_session_change": now_utc.isoformat()
                })
                
                if session_changed:  # Only print once
                    remaining_wait = SESSION_WAIT_MINUTES - minutes_since_actual_start
                    logger.info(f"🟢 ENTERED NEW SESSION: {session_name}")
                    logger.info(f"⏳ Wait period active: {remaining_wait:.1f} minutes remaining before trading allowed")
                    send_telegram_message(f"🟢 <b>ENTERED NEW SESSION:</b> {session_name}\n⏳ Wait period: {remaining_wait:.1f} minutes remaining")
            else:
                # Session started more than 30 minutes ago - JOINING EXISTING SESSION
                session_state.update({
                    "current_session": current_session,
                    "session_start_time": None,  # No wait period
                    "trades_taken_this_session": {},
                    "last_session_change": now_utc.isoformat()
                })
                
                if session_changed:  # Only print once
                    logger.info(f"📍 JOINED EXISTING SESSION: {session_name} (started {minutes_since_actual_start:.1f} minutes ago)")
                    logger.info(f"No wait period - session already active for {minutes_since_actual_start:.1f} minutes")
                    send_telegram_message(f"📍 <b>JOINED EXISTING SESSION:</b> {session_name}\nNo wait period - session already active")
        else:
            # Exiting a session - no specific action needed
            session_state.update({
                "current_session": current_session,
                "session_start_time": None,
                "trades_taken_this_session": {},
                "last_session_change": now_utc.isoformat()
            })
            logger.info(f"📍 EXITED SESSION - No active trading session")
            send_telegram_message(f"📍 <b>EXITED SESSION</b>\nNo active trading session")
        
        # Save the updated state
        save_session_state_standalone(session_state)
    
    return session_changed, current_session, session_state

def can_trade_in_session_standalone(symbol=None):
    """
    Check if trading is allowed in the current session for a specific symbol
    
    Args:
        symbol: Trading symbol to check (optional)
    
    Returns:
        tuple: (can_trade, reason, session_state)
    """
    current_session = get_current_session_standalone()
    session_state = get_session_state_standalone()
    
    # No active session - allow trading (no session restrictions)
    if not current_session:
        return True, "No active trading session - trading allowed", session_state
    
    # CHECK SYMBOL TRADING LIMITS FIRST (before session timing checks)
    if symbol:
        trades_per_symbol = session_state.get("trades_taken_this_session", {})
        symbol_trades = trades_per_symbol.get(symbol, 0)
        if symbol_trades >= 1:
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            return False, f"{symbol} already traded in {session_name} ({symbol_trades}/1 used)", session_state
    
    # Check if we have a session start time (only set when actually entering a session)
    session_start_time_str = session_state.get("session_start_time")
    if not session_start_time_str:
        # Session is active but no start time recorded - this means we started 
        # the bot while already in a session, so no wait period applies
        return True, f"Already in {current_session} session - no wait period", session_state
    
    # Check if we're still in the 30-minute wait period
    try:
        # Ensure both datetimes are timezone-aware
        if session_start_time_str.endswith('Z'):
            session_start_time_str = session_start_time_str[:-1] + '+00:00'
        elif not session_start_time_str.endswith(('+00:00', 'Z')) and 'T' in session_start_time_str:
            session_start_time_str += '+00:00'
            
        session_start = datetime.fromisoformat(session_start_time_str)
        if session_start.tzinfo is None:
            session_start = session_start.replace(tzinfo=timezone.utc)
            
        now_utc = datetime.now(timezone.utc)
        minutes_since_start = (now_utc - session_start).total_seconds() / 60
        
        if minutes_since_start < SESSION_WAIT_MINUTES:
            remaining_minutes = SESSION_WAIT_MINUTES - minutes_since_start
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            return False, f"{session_name} wait period active. {remaining_minutes:.1f} minutes remaining", session_state
    except Exception as e:
        logger.error(f"Error calculating session wait time: {e}")
        # If we can't calculate wait time, allow trading
        return True, f"Session wait calculation error - allowing trading", session_state
    
    # All checks passed
    session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
    session_name = session_names.get(current_session, current_session)
    symbol_text = f"for {symbol} " if symbol else ""
    return True, f"Trading allowed {symbol_text}in {session_name}", session_state

def increment_session_trade_counter_standalone(symbol):
    """
    Increment the trade counter for a specific symbol in the current session
    
    Args:
        symbol: Trading symbol that made the trade
    
    Returns:
        bool: Success status
    """
    session_state = get_session_state_standalone()
    trades_per_symbol = session_state.get("trades_taken_this_session", {})
    trades_per_symbol[symbol] = trades_per_symbol.get(symbol, 0) + 1
    session_state["trades_taken_this_session"] = trades_per_symbol
    
    success = save_session_state_standalone(session_state)
    if success:
        current_session = session_state.get("current_session")
        if current_session:
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            symbol_trades = trades_per_symbol[symbol]
            logger.info(f"📊 {symbol}: {symbol_trades}/1 trades used in {session_name}")
    
    return success

def check_session_limits(symbol):
    """
    Check if we can trade this symbol in the current session.
    Returns True if trade is allowed, False otherwise.
    """
    try:
        # Try to import from s1 first
        from s1 import can_trade_in_session
        can_trade, reason, _ = can_trade_in_session(symbol)
        return can_trade
    except ImportError:
        # Use standalone session management
        if STANDALONE_MODE:
            # Check for session changes first
            check_session_change_standalone()
            
            can_trade, reason, _ = can_trade_in_session_standalone(symbol)
            if not can_trade:
                logger.warning(f"Session restriction for {symbol}: {reason}")
            return can_trade
        return True  # If not standalone and can't import s1, allow trading
    except Exception as e:
        logger.error(f"Error checking session limits: {e}")
        return False

def increment_session_counter(symbol):
    """Increment the session counter for this symbol."""
    try:
        # Try to use s1 session management first
        from s1 import increment_session_counter_on_execution
        return increment_session_counter_on_execution(symbol, "BUY")  # Use BUY as default
    except ImportError:
        # Use standalone session management
        if STANDALONE_MODE:
            return increment_session_trade_counter_standalone(symbol)
        return False
    except Exception as e:
        logger.error(f"Error incrementing session counter: {e}")
        return False

def is_valid_confirmation_context(symbol):
    """
    Check if there's a recent trade confirmation request for this symbol.
    Only allow ENTER commands if there was a recent confirmation request.
    """
    if not STANDALONE_MODE:
        return True  # Normal mode always allows
        
    # Check recent messages for a confirmation request for this symbol
    recent_context = get_recent_analysis_context()
    if not recent_context:
        return False
        
    # Look for the confirmation pattern in recent messages
    pattern = f"Symbol: {symbol}"
    confirmation_pattern = "Reply with:"
    enter_pattern = f"ENTER {symbol}"
    
    has_symbol = pattern in recent_context
    has_confirmation = confirmation_pattern in recent_context
    has_enter_instruction = enter_pattern in recent_context
    
    return has_symbol and has_confirmation and has_enter_instruction

def process_direct_trade_command(symbol, analysis_text=None):
    """
    Process a direct ENTER command and determine BUY/SELL signal from analysis.
    Only works when running in standalone mode with proper validation.
    
    Args:
        symbol: Trading symbol (e.g., SOLUSDT)
        analysis_text: Optional analysis text to parse for recommendation
        
    Returns:
        True if trade was executed, False otherwise
    """
    try:
        # Only work in standalone mode
        if not STANDALONE_MODE:
            logger.info(f"Direct trade command ignored - not in standalone mode")
            return False
            
        logger.info(f"Processing direct trade command for {symbol}")
        
        # Check if this is a valid confirmation context
        if not is_valid_confirmation_context(symbol):
            send_telegram_message(f"❌ No recent trade confirmation request found for {symbol}. Please wait for a proper trade signal before using ENTER command.")
            logger.warning(f"No valid confirmation context for {symbol}")
            return False
        
        # Check session limits
        if not check_session_limits(symbol):
            send_telegram_message(f"❌ Session limit reached for {symbol}. Only 1 trade per symbol per session is allowed.")
            logger.warning(f"Session limit reached for {symbol}")
            return False
        
        # Load current signals
        signals = get_signals()
        
        # Extract recommendation from analysis text
        signal_type = extract_recommendation_from_message(analysis_text)
        
        # Default to SKIP if no clear recommendation found
        if not signal_type:
            send_telegram_message(f"⚠️ No clear BUY/SELL recommendation found for {symbol}. Trade SKIPPED.")
            logger.info(f"No clear recommendation found for {symbol}, trade skipped")
            return False
        
        # Create signal data if symbol doesn't exist, or update existing
        current_time = datetime.now().isoformat()
        
        if symbol not in signals:
            # Create new signal entry
            signals[symbol] = {
                "timestamp": current_time,
                "symbol": symbol,
                "signal": signal_type,
                "confidence": 0,
                "processed_time": current_time,
                "processed": True,
                "stack_position": False,
                "price": 0,  # Will be updated by trading system
                "trend": "Unknown",
                "source": "standalone_telegram"
            }
        else:
            # Update existing signal
            signals[symbol]["signal"] = signal_type
            signals[symbol]["timestamp"] = current_time
            signals[symbol]["processed_time"] = current_time
            signals[symbol]["processed"] = True
            signals[symbol]["source"] = "standalone_telegram"
        
        # Update last update timestamp
        signals["_last_update"] = current_time
        
        # Save updated signals
        with open("all_trade_signals.json", "w") as f:
            json.dump(signals, f, indent=2)
        
        # Increment session counter
        success = increment_session_counter(symbol)
        if success:
            print(f"🎯 SESSION TRADE CONFIRMED: {signal_type} for {symbol}")
        else:
            print(f"⚠️ Failed to increment session counter for {symbol}")
        
        # Send confirmation message
        send_telegram_message(f"✅ Trade for <b>{symbol}</b> has been <b>ENTERED</b> as <b>{signal_type}</b>.")
        print(f"✅ Direct trade executed: {signal_type} for {symbol}")
        
        logger.info(f"Successfully processed direct trade: {signal_type} for {symbol}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing direct trade command for {symbol}: {e}")
        send_telegram_message(f"❌ Error executing trade for <b>{symbol}</b>: {str(e)}")
        return False

def extract_recommendation_from_message(message_text):
    """
    Extract trading recommendation from a message that contains analysis.
    
    Args:
        message_text: The full message text containing analysis
        
    Returns:
        "BUY", "SELL", or None if no clear recommendation found
    """
    try:
        if not message_text:
            return None
            
        text_lower = message_text.lower()
        
        # Look for explicit recommendation patterns
        recommendation_patterns = [
            r"recommendation:\s*(buy|sell)",
            r"recommendation\s*(buy|sell)", 
            r"recommend\s*(buying|selling)",
            r"suggest\s*(buy|sell)",
            r"action:\s*(buy|sell)"
        ]
        
        for pattern in recommendation_patterns:
            match = re.search(pattern, text_lower)
            if match:
                action = match.group(1)
                if action in ["buy", "buying"]:
                    return "BUY"
                elif action in ["sell", "selling"]:
                    return "SELL"
        
        # Look for signal patterns in the message format
        signal_patterns = [
            r"signal:\s*(buy|sell)",
            r"signal\s*(buy|sell)"
        ]
        
        for pattern in signal_patterns:
            match = re.search(pattern, text_lower)
            if match:
                action = match.group(1)
                if action == "buy":
                    return "BUY"
                elif action == "sell":
                    return "SELL"
        
        # Look for conclusion patterns
        if "conclusion" in text_lower:
            conclusion_section = text_lower[text_lower.find("conclusion"):]
            if "sell" in conclusion_section or "short" in conclusion_section:
                return "SELL"
            elif "buy" in conclusion_section or "long" in conclusion_section:
                return "BUY"
        
        return None
        
    except Exception as e:
        logger.error(f"Error extracting recommendation from message: {e}")
        return None

# Store recent messages for analysis context (only in standalone mode)
recent_messages = []

def store_recent_message(message_text, max_messages=10):
    """Store recent messages to provide context for trade decisions."""
    if STANDALONE_MODE:
        global recent_messages
        recent_messages.append({
            "text": message_text,
            "timestamp": datetime.now().isoformat()
        })
        # Keep only the most recent messages
        if len(recent_messages) > max_messages:
            recent_messages = recent_messages[-max_messages:]

def get_recent_analysis_context():
    """Get recent message context for analysis."""
    if not STANDALONE_MODE:
        return None
    
    # Combine recent messages to look for analysis context
    context = ""
    for msg in recent_messages[-3:]:  # Last 3 messages
        context += msg["text"] + "\n"
    return context if context.strip() else None

# Add this new function after the session functions:
def monitor_session_changes():
    """Monitor session changes in standalone mode with proper logging."""
    if STANDALONE_MODE:
        try:
            session_changed, current_session, session_state = check_session_change_standalone()
            if session_changed:
                logger.info(f"🔄 Session changed to: {current_session}")
                
                # Send notification about session change
                if current_session:
                    session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
                    session_name = session_names.get(current_session, current_session)
                    
                    # Check if there's a wait period
                    session_start_time_str = session_state.get("session_start_time")
                    if session_start_time_str:
                        try:
                            if session_start_time_str.endswith('Z'):
                                session_start_time_str = session_start_time_str[:-1] + '+00:00'
                            elif not session_start_time_str.endswith(('+00:00', 'Z')) and 'T' in session_start_time_str:
                                session_start_time_str += '+00:00'
                                
                            session_start = datetime.fromisoformat(session_start_time_str)
                            if session_start.tzinfo is None:
                                session_start = session_start.replace(tzinfo=timezone.utc)
                                
                            now_utc = datetime.now(timezone.utc)
                            minutes_since_start = (now_utc - session_start).total_seconds() / 60
                            
                            if minutes_since_start < SESSION_WAIT_MINUTES:
                                remaining = SESSION_WAIT_MINUTES - minutes_since_start
                                logger.info(f"⏳ New session wait period: {remaining:.1f} minutes remaining")
                        except Exception as e:
                            logger.error(f"Error calculating wait period: {e}")
                else:
                    logger.info(f"📍 Exited trading session - no session restrictions")
                    
        except Exception as e:
            logger.error(f"Error monitoring session changes: {e}")

# Update the existing run_telegram_bot_with_shutdown function to add session monitoring:
# Find the while loop in run_telegram_bot_with_shutdown and modify it to include:

# In the main while loop, add this after the shutdown flag check:
if STANDALONE_MODE:
    # Check for session changes every minute (adjust the timing as needed)
    current_time = time.time()
    if not hasattr(monitor_session_changes, 'last_check'):
        monitor_session_changes.last_check = current_time
    
    if current_time - monitor_session_changes.last_check > 60:  # Check every 60 seconds
        monitor_session_changes()
        monitor_session_changes.last_check = current_time

# Move this function from the end of the file to around line 1980 (before __main__)
def initialize_session_state_file_standalone():
    """Initialize the session state file if it doesn't exist or reset it on startup"""
    # Check current session status
    current_session = get_current_session_standalone()
    
    default_session_state = {
        "current_session": current_session,
        "session_start_time": None,  # Don't set start time on initialization
        "trades_taken_this_session": {},  # Reset trade counter
        "last_session_change": datetime.now(timezone.utc).isoformat()
    }
    
    if safe_write_json(SESSION_STATE_FILE, default_session_state):
        logger.info(f"✅ Created/Reset session state file: {SESSION_STATE_FILE}")
        if current_session:
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            logger.info(f"📊 Currently in {session_name} - no wait period on startup")
        else:
            logger.info(f"📊 No active session - trading allowed")
    else:
        logger.error(f"❌ Failed to initialize session state file")

def execute_enter_position(symbol, side):
    """
    Execute position opening for the specified symbol and side.
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        side: Position side ("Buy" or "Sell")
        
    Returns:
        Formatted message with execution result
    """
    try:
        # Import trade_manager functions
        import trade_manager
        
        # Check if multi-account is enabled
        if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
            # Multi-account mode - use parallel execution with individual position sizes
            logger.info(f"🏦 Multi-account mode: Opening {side} position for {symbol}")
            
            # Check if position already exists (check all accounts)
            all_positions = trade_manager.get_active_positions_all_accounts()
            if symbol in all_positions:
                account_list = [pos['account'] for pos in all_positions[symbol]]
                return f"❌ Position already exists for <b>{symbol}</b> on accounts: {', '.join(account_list)}. Close first or use martingale."
            
            # Check session limits
            if not check_session_limits(symbol):
                return f"❌ Session limit reached for {symbol}. Only 1 trade per symbol per session is allowed."
            
            # Get account summary for confirmation message
            summary = trade_manager.multi_trader.get_account_summary()
            total_usdt = summary['total_position_usdt']
            account_count = summary['total_accounts']
            
            # Show confirmation message
            confirmation_message = (
                f"🎯 <b>OPENING MULTI-ACCOUNT POSITION</b>\n\n"
                f"Symbol: <b>{symbol}</b>\n"
                f"Side: {side}\n"
                f"Accounts: {account_count}\n"
                f"Combined Size: ${total_usdt} USDT @ 40x leverage\n"
                f"⏳ Placing orders across all accounts..."
            )
            send_telegram_message(confirmation_message)
            
            # Execute across all accounts in parallel
            result = trade_manager.open_position_parallel(symbol, side, None)
            
            if result and result.get("multi_account"):
                results = result.get("results", {})
                success_count = result.get("success_count", 0)
                total_count = result.get("total_count", 0)
                
                if success_count > 0:
                    # Increment session counter on successful orders
                    increment_session_counter(symbol)
                    
                    # Build success message
                    success_message = f"✅ <b>MULTI-ACCOUNT POSITION OPENED</b>\n\n"
                    success_message += f"Symbol: <b>{symbol}</b>\n"
                    success_message += f"Side: {side}\n"
                    success_message += f"Success Rate: {success_count}/{total_count} accounts\n\n"
                    
                    # Show details for each account
                    for account_name, account_result in results.items():
                        if account_result.get("success"):
                            qty = account_result.get("qty", "unknown")
                            position_usdt = account_result.get("position_usdt", "unknown")
                            success_message += f"✅ {account_name}: {qty} ({position_usdt} USDT)\n"
                        else:
                            error = account_result.get("error", "Unknown error")
                            success_message += f"❌ {account_name}: {error}\n"
                    
                    success_message += f"\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    return success_message
                else:
                    error_message = f"❌ <b>ALL ACCOUNTS FAILED</b>\n\n"
                    error_message += f"Symbol: <b>{symbol}</b>\n"
                    error_message += f"Side: {side}\n\n"
                    
                    for account_name, account_result in results.items():
                        error = account_result.get("error", "Unknown error")
                        error_message += f"❌ {account_name}: {error}\n"
                    
                    return error_message
            else:
                return f"❌ Failed to execute multi-account position for <b>{symbol}</b>"
        
        else:
            # Single account mode - use original logic but with proper position size
            logger.info(f"📱 Single account mode: Opening {side} position for {symbol}")
            
            from trade_manager import get_active_positions, calculate_position_size, open_position
            
            # Check if position already exists
            active_positions = get_active_positions()
            if symbol in active_positions:
                existing_side = active_positions[symbol].get("side")
                existing_size = active_positions[symbol].get("size", 0)
                return f"❌ Position already exists for <b>{symbol}</b> ({existing_side} {existing_size}). Close it first."
            
            # Check session limits before placing order
            if not check_session_limits(symbol):
                return f"❌ Session limit reached for {symbol}. Only 1 trade per symbol per session is allowed."
            
            # For single account, use a reasonable default position size if trading_config.json has 0
            # This is a fallback to prevent the 0 USDT issue
            position_data = calculate_position_size(symbol, side, amount_usdt=15)  # Use 15 USDT as fallback
            if not position_data:
                return f"❌ Failed to calculate position size for {symbol}. Check your trading configuration."
            
            qty = position_data["formatted_qty"]
            leverage = position_data["leverage"]
            value_usdt = position_data["value_usdt"]
            
            # Show confirmation message
            confirmation_message = (
                f"🎯 <b>OPENING POSITION</b>\n\n"
                f"Symbol: <b>{symbol}</b>\n"
                f"Side: {side}\n"
                f"Size: {qty} ({value_usdt} USDT with {leverage}x leverage)\n"
                f"⏳ Placing order..."
            )
            send_telegram_message(confirmation_message)
            
            # Place the order using trade manager
            result = open_position(symbol, side, qty)
            
            if result and result.get("success", False):
                # Increment session counter on successful order
                increment_session_counter(symbol)
                
                # Get order details
                order_id = result.get("order_id", "N/A")
                
                success_message = (
                    f"✅ <b>POSITION OPENED SUCCESSFULLY</b>\n\n"
                    f"Symbol: <b>{symbol}</b>\n"
                    f"Side: {side}\n"
                    f"Quantity: {qty}\n"
                    f"Leverage: {leverage}x\n"
                    f"Value: ${value_usdt}\n"
                    f"Order ID: {order_id}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                return success_message
            else:
                error_details = result.get("message", "Unknown error") if result else "No response from trade manager"
                error_message = (
                    f"❌ <b>FAILED TO OPEN POSITION</b>\n\n"
                    f"Symbol: <b>{symbol}</b>\n"
                    f"Side: {side}\n"
                    f"Reason: {error_details}\n\n"
                    f"💡 Check your account balance and trading configuration."
                )
                return error_message
            
    except ImportError:
        return "❌ Trade manager module not available. Position opening functionality disabled."
    except Exception as e:
        logger.error(f"Error opening position for {symbol} {side}: {e}")
        return f"❌ Error opening position for <b>{symbol}</b>: {str(e)}"

def handle_accounts_command():
    """Show status of all accounts with individual position sizes"""
    try:
        if not hasattr(trade_manager, 'is_multi_account_enabled') or not trade_manager.multi_trader:
            return "📱 <b>Single Account Mode</b>\n\nMulti-account trading is not enabled or configured."
            
        # Get account summary
        summary = trade_manager.multi_trader.get_account_summary()
        
        # Test all connections
        connection_results = trade_manager.test_all_account_connections()
        
        message = f"🏦 <b>MULTI-ACCOUNT STATUS</b>\n\n"
        message += f"Trading Symbol: <b>{summary['trading_symbol']}</b>\n"
        message += f"Total Accounts: {summary['total_accounts']}\n"
        message += f"Combined Position Size: <b>${summary['total_position_usdt']} USDT</b>\n\n"
        
        for account_info in summary['accounts']:
            account_name = account_info['name']
            position_usdt = account_info['position_usdt']
            leverage = account_info['leverage']
            
            status_info = connection_results.get(account_name, {"status": "unknown"})
            status = status_info.get("status", "unknown")
            
            if status == "connected":
                emoji = "✅"
                status_text = "Connected"
            elif status == "error":
                emoji = "❌"
                status_text = f"Error: {status_info.get('error', 'Unknown error')[:50]}..."
            else:
                emoji = "⚠️"
                status_text = "Unknown"
                
            message += f"{emoji} <b>{account_name}</b>\n"
            message += f"   Position: ${position_usdt} USDT @ {leverage}x\n"
            message += f"   Status: {status_text}\n\n"
        
        message += f"<i>Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        return message
        
    except Exception as e:
        logger.error(f"Error getting account status: {e}")
        return f"Error checking account status: {str(e)}"

def handle_account_count_command():
    """Show number of active accounts"""
    try:
        if hasattr(trade_manager, 'get_account_count'):
            count = trade_manager.get_account_count()
            if count > 1:
                accounts = ", ".join(trade_manager.multi_trader.accounts) if trade_manager.multi_trader else "unknown"
                return f"🏦 <b>Multi-Account Mode</b>\n\n{count} accounts active:\n{accounts}"
            else:
                account_name = trade_manager.multi_trader.accounts[0] if trade_manager.multi_trader and trade_manager.multi_trader.accounts else "main"
                return f"📱 <b>Single Account Mode</b>\n\nActive account: {account_name}"
        else:
            return "📱 <b>Single Account Mode</b>\n\nMulti-account features not available."
    except Exception as e:
        logger.error(f"Error getting account count: {e}")
        return f"Error: {str(e)}"

def handle_add_account_command():
    """Show instructions for adding a new account"""
    return """
<b>📝 HOW TO ADD A NEW ACCOUNT</b>

<b>1. Add API keys to .env file:</b>
<code>BYBIT_API_KEY_4=your_new_api_key
BYBIT_API_SECRET_4=your_new_api_secret</code>

<b>2. Add account to accounts_config.json:</b>
<code>{
  "name": "account4",
  "api_key_env": "BYBIT_API_KEY_4", 
  "api_secret_env": "BYBIT_API_SECRET_4",
  "enabled": true,
  "position_usdt": 20,
  "leverage": 40
}</code>

<b>3. Restart the trading system</b>

<b>Settings:</b>
• <code>position_usdt</code>: Position size in USDT for this account
• <code>leverage</code>: Always use 40 for BTC trading
• <code>enabled</code>: Set to false to disable account

<b>⚠️ Important:</b>
All accounts trade BTCUSDT only with the same signals but different position sizes.
"""

# Main entry point when run directly
if __name__ == "__main__":

    
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set. Please set it in your .env file.")
        print("\nTELEGRAM_BOT_TOKEN not configured!")
        print("Please set your Telegram bot token in the .env file:")
        print("TELEGRAM_BOT_TOKEN=your_token_here\n")
        exit(1)
    
    # ====== SESSION MANAGEMENT INITIALIZATION ====== (EXACT COPY FROM s1.py)
    # Initialize session state file if it doesn't exist
    initialize_session_state_file_standalone()
    
    # Check current session status on startup
    session_changed, current_session, session_state = check_session_change_standalone()
    
    session_info = ""
    if current_session:
        session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
        session_name = session_names.get(current_session, current_session)
        trades_count = len(session_state.get("trades_taken_this_session", {}))
        session_info = f"\n📊 Current Session: {session_name} (Symbols traded: {trades_count})"
        
        # Check if in wait period
        session_start_time_str = session_state.get("session_start_time")
        if session_start_time_str:
            try:
                from datetime import timezone
                if session_start_time_str.endswith('Z'):
                    session_start_time_str = session_start_time_str[:-1] + '+00:00'
                elif not session_start_time_str.endswith(('+00:00', 'Z')) and 'T' in session_start_time_str:
                    session_start_time_str += '+00:00'
                    
                session_start = datetime.fromisoformat(session_start_time_str)
                if session_start.tzinfo is None:
                    session_start = session_start.replace(tzinfo=timezone.utc)
                    
                now_utc = datetime.now(timezone.utc)
                minutes_since_start = (now_utc - session_start).total_seconds() / 60
                
                if minutes_since_start < SESSION_WAIT_MINUTES:
                    remaining = SESSION_WAIT_MINUTES - minutes_since_start
                    session_info += f"\n⏳ Wait period: {remaining:.1f} minutes remaining"
                else:
                    session_info += f"\n✅ Trading allowed (session active {minutes_since_start:.1f} min)"
            except Exception:
                session_info += f"\n✅ Trading allowed"
    else:
        session_info = f"\n📊 Outside trading hours - no session restrictions"
    
    # Console startup message
    print("🚀 Starting Telegram bot in STANDALONE mode...")
    print("📋 Standalone features enabled:")
    print("   • Direct ENTER {SYMBOL} commands (only after confirmation requests)")
    print("   • Analysis-based BUY/SELL detection")
    print("   • Session limit enforcement (1 trade per symbol per session)")
    print("   • Default to SKIP if no clear recommendation")
    print(session_info)
    logger.info("Starting Telegram bot in STANDALONE mode...")
    
    # Send startup message to Telegram
    startup_message = (
        "<b>🚀 TELEGRAM BOT STARTED IN STANDALONE MODE</b>\n\n"
        "<b>📋 Features Enabled:</b>\n"
        "• Direct <code>ENTER {SYMBOL}</code> commands\n"
        "• Analysis-based BUY/SELL detection\n"
        "• Session limit enforcement (1 trade per symbol per session)\n"
        "• Default to SKIP if no clear recommendation\n\n"
        "<b>ℹ️ How it works:</b>\n"
        "1. Wait for a trade confirmation request\n"
        "2. Reply with <code>ENTER {SYMBOL}</code> to execute\n"
        "3. Reply with <code>SKIP {SYMBOL}</code> to ignore\n\n"
        "<b>⚠️ Important:</b>\n"
        "• Only 1 trade per symbol per session allowed\n"
        "• ENTER commands only work after proper confirmation requests\n"
        "• Bot will analyze recent messages for BUY/SELL signals\n"
    )
    
    # Add session info to telegram message
    if current_session:
        session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
        session_name = session_names.get(current_session, current_session)
        trades_count = len(session_state.get("trades_taken_this_session", {}))
        startup_message += f"\n<b>📊 Current Session:</b> {session_name}\n"
        startup_message += f"<b>Symbols traded:</b> {trades_count}\n"
        
        # Add wait period info if applicable
        session_start_time_str = session_state.get("session_start_time")
        if session_start_time_str:
            try:
                from datetime import timezone
                if session_start_time_str.endswith('Z'):
                    session_start_time_str = session_start_time_str[:-1] + '+00:00'
                elif not session_start_time_str.endswith(('+00:00', 'Z')) and 'T' in session_start_time_str:
                    session_start_time_str += '+00:00'
                    
                session_start = datetime.fromisoformat(session_start_time_str)
                if session_start.tzinfo is None:
                    session_start = session_start.replace(tzinfo=timezone.utc)
                    
                now_utc = datetime.now(timezone.utc)
                minutes_since_start = (now_utc - session_start).total_seconds() / 60
                
                if minutes_since_start < SESSION_WAIT_MINUTES:
                    remaining = SESSION_WAIT_MINUTES - minutes_since_start
                    startup_message += f"⏳ <b>Wait period:</b> {remaining:.1f} minutes remaining\n"
                else:
                    startup_message += f"✅ <b>Trading:</b> Allowed (session active {minutes_since_start:.1f} min)\n"
            except Exception:
                startup_message += f"✅ <b>Trading:</b> Allowed\n"
    else:
        startup_message += f"\n📊 <b>Outside trading hours</b> - no session restrictions\n"
    
    startup_message += f"\n<i>Bot started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
    
    # Try to send startup message to Telegram
    try:
        if send_telegram_message(startup_message):
            print("✅ Startup message sent to Telegram successfully")
            logger.info("Startup message sent to Telegram successfully")
        else:
            print("⚠️ Failed to send startup message to Telegram")
            logger.warning("Failed to send startup message to Telegram")
    except Exception as e:
        print(f"⚠️ Error sending startup message to Telegram: {e}")
        logger.error(f"Error sending startup message to Telegram: {e}")
    
    # Run the bot
    try:
        run_telegram_bot()
    except KeyboardInterrupt:
        print("\nBot stopped.")
        # Send shutdown message to Telegram
        try:
            shutdown_message = (
                "<b>🛑 TELEGRAM BOT STOPPED</b>\n\n"
                f"<i>Bot stopped at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
            )
            send_telegram_message(shutdown_message)
            print("✅ Shutdown message sent to Telegram")
        except Exception as e:
            print(f"⚠️ Error sending shutdown message: {e}") 