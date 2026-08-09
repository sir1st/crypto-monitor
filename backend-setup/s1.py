"""
Multi-Timeframe EMA Cross Strategy

Advanced version with support for multiple timeframes.
Uses Bybit WebSocket API to receive real-time market data and detect EMA crossovers.
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pybit.unified_trading import HTTP, WebSocket
import traceback
import sys
import logging
import operator
from openai import OpenAI  # Import standard OpenAI client
import threading
import random
import math
from tele import send_telegram_message, send_trading_signal, send_crossover_alert, send_bot_status, send_trade_confirmation_request, run_telegram_bot, run_telegram_bot_with_shutdown, STANDALONE_MODE  # Import Telegram functions
import shutil
import tempfile
import signal
from smi_indicator import update_smi_for_symbol, get_smi_analysis_for_symbol, start_smi_monitor

# Fix Windows console Unicode issues
import sys
if sys.platform.startswith('win'):
    import os
    os.system('chcp 65001 > nul')  # Set console to UTF-8

# Market Sessions Times (UTC) - fix NY session times
TOKYO_START = 0
TOKYO_END = 7  # ← Change from 9 to 7 
LONDON_START = 7  # ← Change from 8 to 7
LONDON_END = 13  # ← Change from 17 to 13 (when NY starts)
NY_START = 13
NY_START_MINUTES = 30  # NY starts at 13:30, not 13:00
NY_END = 21  # Changed from 22 to 21
SESSION_WAIT_MINUTES = 30  # Wait 30 minutes after session start before allowing trades

# Add after line 37 (after SESSION_WAIT_MINUTES = 30)
TOKYO_SESSION = {"start": f"{TOKYO_START:02d}:00", "end": f"{TOKYO_END:02d}:00"}
LONDON_SESSION = {"start": f"{LONDON_START:02d}:00", "end": f"{LONDON_END:02d}:00"}
NY_SESSION = {"start": f"{NY_START:02d}:30", "end": f"{NY_END:02d}:00"}  # Fixed to 13:30-21:00

# ====== CONFIGURATION ======
# Timeframes to monitor (interval codes used by Bybit API)
TIMEFRAMES = {
    "1m": {"interval": "1", "description": "1 minute", "enabled": False},
    "5m": {"interval": "5", "description": "5 minutes", "enabled": True},
    "15m": {"interval": "15", "description": "15 minutes", "enabled": True},
    "30m": {"interval": "30", "description": "30 minutes", "enabled": True},
    "1h": {"interval": "60", "description": "1 hour", "enabled": True},
    "4h": {"interval": "240", "description": "4 hours", "enabled": False},
    "1d": {"interval": "D", "description": "1 day", "enabled": False},
}

# Which timeframes should trigger alerts on crossover?
ALERT_TIMEFRAMES = ["5","15"]

# Main timeframe that will be used for detailed analysis
MAIN_TIMEFRAME = "5m"

# Default values for EMA periods (can be adjusted per timeframe if needed)
EMA_SHORT_PERIOD = 12
EMA_LONG_PERIOD = 21
EMA_TREND_PERIOD = 50

# Other settings
CONFIG_FILE = "trading_config.json"
CATEGORY = "linear"  # USDT perpetual
SIGNALS_FILE = "all_trade_signals.json"
DEBUG = False  # Set to True for verbose output
DECISION_HISTORY_FILE = "trading_decision_history.json"
MAX_DECISION_HISTORY = 500  # Store up to 500 past decisions

# ====== INDICATOR CONSTANTS ======cv 89o;=-[]
RSI_PERIOD = 14  # Standard RSI period
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9

# ====== LOGGING SETUP ======
# Configure logging to suppress WebSocket output
logging.basicConfig(level=logging.ERROR)
# Specifically silence the websocket-client
logging.getLogger('websocket').setLevel(logging.ERROR)

# Custom stdout to suppress WebSocket debug output
class CustomStdout:
    def __init__(self, orig_stdout):
        self.orig_stdout = orig_stdout
        self.suppress_patterns = [
            "++Sent raw:", 
            "++Sent decoded:", 
            "++Rcv raw:", 
            "++Rcv decoded:",
            "--- request header ---",
            "--- response header ---"
        ]
    
    def write(self, message):
        if not any(pattern in message for pattern in self.suppress_patterns):
            self.orig_stdout.write(message)
    
    def flush(self):
        self.orig_stdout.flush()

# Replace sys.stdout with our custom version
sys.stdout = CustomStdout(sys.stdout)

# Load environment variables from .env file
load_dotenv()
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# Initialize REST client
rest_client = HTTP(
    testnet=False,  # Set to True for testnet
    api_key=API_KEY,
    api_secret=API_SECRET
)

# Global variables
symbol_data = {}  # Dictionary to store data for each symbol
active_pairs = []  # List of active trading pairs
# subscriptions = {"klines": {}}  # Dictionary to track active subscriptions - Not needed with pybit
ws = None  # Global WebSocket connection
# last_pong_time = 0  # Timestamp of last pong message - Not needed with pybit
# last_ping_sent = 0  # Timestamp of last ping message - Not needed with pybit
# connection_active = False  # Flag to track if connection is active - Not needed with pybit

# At the top
PENDING_SIGNALS_FILE = "pending_signals.json"
POSITIONS_FILE = "all_positions.json"
SESSION_STATE_FILE = "session_state.json"

# Add these global variables at the top after imports
_session_blocked_symbols = set()
_last_session_message_time = 0

# Add session lock at the top
_session_lock = threading.Lock()

def safe_read_json(file_path):
    """
    Safely read a JSON file with proper error handling
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        tuple: (data, success)
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data = json.load(f)
            return data, True
        else:
            return {}, False
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return {}, False

def safe_write_json(file_path, data):
    """
    Safely write data to a JSON file with proper error handling
    
    Args:
        file_path: Path to the JSON file
        data: Data to write
        
    Returns:
        bool: Success or failure
    """
    try:
        # Use a temporary file to avoid corruption
        with tempfile.NamedTemporaryFile('w', delete=False) as tf:
            json.dump(data, tf, indent=2)
            tempname = tf.name
        # Move the temp file to the target path
        shutil.move(tempname, file_path)
        return True
    except Exception as e:
        print(f"Error writing {file_path}: {e}")
        return False

def initialize_session_state_file():
    """
    Initialize the session state file if it doesn't exist
    """
    if not os.path.exists(SESSION_STATE_FILE):
        # Check current session status
        current_session = get_current_session()
        
        default_session_state = {
            "current_session": current_session,
            "session_start_time": None,  # Don't set start time on initialization
            "trades_taken_this_session": {},  # Reset trade counter
            "last_session_change": datetime.now(timezone.utc).isoformat()
        }
        
        if safe_write_json(SESSION_STATE_FILE, default_session_state):
            print(f"✅ Created session state file: {SESSION_STATE_FILE}")
            if current_session:
                print(f"📊 Currently in {current_session} session (started before bot) - no wait period")
            else:
                print(f"📊 No active session - trading allowed")
        else:
            print(f"❌ Failed to create session state file: {SESSION_STATE_FILE}")

def get_current_session():
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

def get_session_state():
    """
    Load current session state from file
    
    Returns:
        dict: Session state data
    """
    default_state = {
        "current_session": None,
        "session_start_time": None,
        "trades_taken_this_session": {},  # Reset trade counter
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

def save_session_state(state):
    """Save session state to file with file locking"""
    with _session_lock:  # Use the existing session lock
        return safe_write_json(SESSION_STATE_FILE, state)

def check_session_change():
    """
    Check if we've entered a new trading session and handle session transitions
    
    Returns:
        tuple: (session_changed, current_session, session_state)
    """
    current_session = get_current_session()
    session_state = get_session_state()
    
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
                # London starts at 07:00 UTC (not 08:00)
                today_utc = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)  # ← Fix this
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
                    print(f"🟢 ENTERED NEW SESSION: {session_name}")
                    print(f"⏳ Wait period active: {remaining_wait:.1f} minutes remaining before trading allowed")
            else:
                # Session started more than 30 minutes ago - JOINING EXISTING SESSION
                session_state.update({
                    "current_session": current_session,
                    "session_start_time": None,  # No wait period
                    "trades_taken_this_session": {},
                    "last_session_change": now_utc.isoformat()
                })
                
                if session_changed:  # Only print once
                    print(f"📍 JOINED EXISTING SESSION: {session_name} (started {minutes_since_actual_start:.1f} minutes ago)")
                    print(f"No wait period - session already active for {minutes_since_actual_start:.1f} minutes")
        
        # Save the updated state
        save_session_state(session_state)
    
    return session_changed, current_session, session_state

def reset_decision_history_for_new_session(session_name):
    """
    Reset the trading decision history file for a new session
    
    Args:
        session_name: Name of the new session (TOKYO, LONDON, NY)
    """
    try:
        session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
        session_display_name = session_names.get(session_name, session_name)
        
        # Create a fresh decision history with session marker
        fresh_history = {
            "session_info": {
                "session_name": session_name,
                "session_display_name": session_display_name,
                "session_start": datetime.now(timezone.utc).isoformat(),
                "reset_reason": f"New {session_display_name} session started"
            },
            "decisions": []
        }
        
        if safe_write_json(DECISION_HISTORY_FILE, fresh_history):
            print(f"✅ Decision history reset for new {session_display_name}")
        else:
            print(f"❌ Failed to reset decision history for new session")
            
    except Exception as e:
        print(f"Error resetting decision history: {e}")

def can_trade_in_session(symbol=None):
    """
    Check if trading is allowed in the current session for a specific symbol
    
    Args:
        symbol: Trading symbol to check (optional)
    
    Returns:
        tuple: (can_trade, reason, session_state)
    """
    current_session = get_current_session()
    session_state = get_session_state()
    
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
        print(f"Error calculating session wait time: {e}")
        # If we can't calculate wait time, allow trading
        return True, f"Session wait calculation error - allowing trading", session_state
    
    # All checks passed
    session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
    session_name = session_names.get(current_session, current_session)
    symbol_text = f"for {symbol} " if symbol else ""
    return True, f"Trading allowed {symbol_text}in {session_name}", session_state

def increment_session_trade_counter(symbol):
    """
    Increment the trade counter for a specific symbol in the current session
    
    Args:
        symbol: Trading symbol that made the trade
    
    Returns:
        bool: Success status
    """
    session_state = get_session_state()
    trades_per_symbol = session_state.get("trades_taken_this_session", {})
    trades_per_symbol[symbol] = trades_per_symbol.get(symbol, 0) + 1
    session_state["trades_taken_this_session"] = trades_per_symbol
    
    success = save_session_state(session_state)
    if success:
        current_session = session_state.get("current_session")
        if current_session:
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            symbol_trades = trades_per_symbol[symbol]
            print(f"📊 {symbol}: {symbol_trades}/1 trades used in {session_name}")
    
    return success

def get_session_rules_for_ai():
    """
    Get session rules text to include in AI prompts
    
    Returns:
        str: Session rules text for AI
    """
    current_session = get_current_session()
    session_state = get_session_state()
    
    if not current_session:
        return "TRADING SESSIONS: Currently outside trading sessions (Tokyo: 00:00-09:00 UTC, London: 08:00-17:00 UTC, NY: 13:30-21:00 UTC). No trading allowed."
    
    session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
    session_name = session_names.get(current_session, current_session)
    
    # Get per-symbol trade counts
    trades_per_symbol = session_state.get("trades_taken_this_session", {})
    total_symbols_traded = len(trades_per_symbol)
    
    # Check session wait period with proper timezone handling
    session_wait_info = ""
    session_start_time_str = session_state.get("session_start_time")
    if session_start_time_str:
        try:
            # Ensure both datetimes are timezone-aware (same logic as can_trade_in_session)
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
                session_wait_info = f" WARNING: Still in 30-minute wait period ({remaining_minutes:.1f} minutes remaining)."
        except Exception as e:
            print(f"Error calculating session wait time in AI rules: {e}")
            # If calculation fails, don't add wait info
            session_wait_info = ""
    
    rules_text = f"""
CRITICAL TRADING SESSION RULES:
- Current Session: {session_name}
- Symbols Traded: {total_symbols_traded} symbols have traded this session{session_wait_info}
- RULE 1: Only ONE trade allowed per SYMBOL per session (Tokyo/London/NY)
- RULE 2: No trading for first 30 minutes of each session
- RULE 3: If this symbol already traded this session, recommend HOLD only
- RULE 4: Each session starts fresh with reset counters per symbol

IMPORTANT: These session rules OVERRIDE all other technical analysis. If this symbol already traded or wait period is active, ALWAYS recommend HOLD regardless of technical signals.
"""
    
    return rules_text.strip()

def load_config():
    """Load trading configuration from JSON file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                debug_print(f"Loaded configuration from {CONFIG_FILE}")
                return config
        else:
            print(f"Configuration file {CONFIG_FILE} not found")
            # Default fallback with support for timeframes
            return {
                "trading_pairs": ["BTCUSDT"],
                "timeframes": {
                    "1m": {"enabled": TIMEFRAMES["1m"]["enabled"]},
                    "5m": {"enabled": TIMEFRAMES["5m"]["enabled"]},
                    "15m": {"enabled": TIMEFRAMES["15m"]["enabled"]},
                    "30m": {"enabled": TIMEFRAMES["30m"]["enabled"]},
                    "1h": {"enabled": TIMEFRAMES["1h"]["enabled"]},
                    "4h": {"enabled": TIMEFRAMES["4h"]["enabled"]},
                    "1d": {"enabled": TIMEFRAMES["1d"]["enabled"]},
                },
                "alert_timeframes": ALERT_TIMEFRAMES,
                "main_timeframe": MAIN_TIMEFRAME
            }
    except Exception as e:
        print(f"Error loading configuration: {e}")
        traceback.print_exc()
        return {
            "trading_pairs": ["BTCUSDT"],
            "timeframes": {k: {"enabled": v["enabled"]} for k, v in TIMEFRAMES.items()},
            "alert_timeframes": ALERT_TIMEFRAMES,
            "main_timeframe": MAIN_TIMEFRAME
        }

def debug_print(message):
    """Print debug messages if DEBUG is enabled"""
    if DEBUG:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[DEBUG {timestamp}] {message}")

def calculate_ema(prices, period):
    """
    Calculate the Exponential Moving Average (EMA) for a series.
    Uses the correct EMA formula with proper smoothing factor and handles NaN values.
    """
    if len(prices) < period:
        # Not enough data to calculate EMA
        return pd.Series(np.nan, index=prices.index)
    
    # Create a copy of prices to avoid modifying the original
    prices_values = prices.values.copy()
    
    # Check for NaN or invalid values in the input data
    if np.isnan(prices_values).any():
        # Replace NaN values with nearby valid values
        mask = np.isnan(prices_values)
        prices_values[mask] = np.interp(
            np.flatnonzero(mask), 
            np.flatnonzero(~mask), 
            prices_values[~mask]
        )
    
    # Calculate the multiplier: 2/(period+1)
    multiplier = 2 / (period + 1)
    
    # Initialize with SMA for first value
    ema_values = np.zeros_like(prices_values)
    ema_values[:period] = np.nan  # First values are NaN until we have enough data
    
    # Calculate first EMA value (SMA of first 'period' values)
    if len(prices) >= period:
        ema_values[period-1] = np.mean(prices_values[:period])
    
    # Calculate EMA for the rest of the series
    for i in range(period, len(prices)):
        ema_values[i] = (prices_values[i] - ema_values[i-1]) * multiplier + ema_values[i-1]
    
    # Create a Series with the same index as the input
    ema_series = pd.Series(ema_values, index=prices.index)
    
    # Forward fill any remaining NaN values to ensure we have valid data
    ema_series = ema_series.ffill()
    
    return ema_series

# ======== NEW INDICATOR UTILITY FUNCTIONS (placed before first use) ========

def calculate_rsi(prices: pd.Series, period: int = RSI_PERIOD):
    """Compute Wilder's RSI (default period 14)."""
    if len(prices) < period + 1:
        return pd.Series(np.nan, index=prices.index)

    delta = prices.diff().fillna(0)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    roll_up = pd.Series(gain).rolling(period).mean()
    roll_down = pd.Series(loss).rolling(period).mean()

    rs = roll_up / roll_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return pd.Series(rsi, index=prices.index).bfill()


def calculate_macd(prices: pd.Series, fast: int = MACD_FAST_PERIOD, slow: int = MACD_SLOW_PERIOD, signal: int = MACD_SIGNAL_PERIOD):
    """Return (MACD line, signal line, histogram) series aligned with prices."""
    if len(prices) < slow + signal:
        nan = pd.Series(np.nan, index=prices.index)
        return nan, nan, nan

    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def get_historical_klines(symbol, interval, limit=200):
    """
    Fetch historical kline data via Bybit's REST API.
    
    Args:
        symbol: Trading symbol
        interval: Timeframe interval (e.g., "5" for 5 minutes)
        limit: Number of candles to fetch
        
    Returns:
        DataFrame with kline data
    """
    try:
        debug_print(f"Fetching historical klines for {symbol}, interval={interval}, limit={limit}")
        
        # Call Bybit API using pybit client
        response = rest_client.get_kline(
            category=CATEGORY,
            symbol=symbol,
            interval=interval,
            limit=limit
        )
        
        if response["retCode"] != 0:
            print(f"Error fetching klines: {response['retMsg']}")
            return pd.DataFrame()
            
        # Extract kline data
        klines = response["result"]["list"]
        debug_print(f"Received {len(klines)} klines from API")
        
        if len(klines) == 0:
            print("No historical klines returned from API")
            return pd.DataFrame()
            
        # Convert to DataFrame
        # Format: [timestamp, open, high, low, close, volume, turnover]
        df = pd.DataFrame(klines, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
        
        # Convert types
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            df[col] = df[col].astype(float)
            
        # Check for any zero or negative values in price columns
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            invalid_mask = df[col] <= 0
            if invalid_mask.any():
                invalid_count = invalid_mask.sum()
                if invalid_count > 0:
                    print(f"Warning: Found {invalid_count} invalid {col} values in {symbol} data")
                    # Replace invalid values with nearby valid values
                    valid_indices = (~invalid_mask).nonzero()[0]
                    invalid_indices = invalid_mask.nonzero()[0]
                    if len(valid_indices) > 0:
                        df.loc[invalid_mask, col] = np.interp(
                            invalid_indices, 
                            valid_indices, 
                            df.loc[~invalid_mask, col]
                        )
            
        # Fix timestamp conversion warning by explicitly converting to int first
        df["timestamp"] = pd.to_numeric(df["timestamp"])
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
        
        # Sort by time (oldest first)
        df = df.sort_values("time").reset_index(drop=True)
        
        debug_print(f"Processed historical data. DataFrame shape: {df.shape}")
        debug_print(f"Time range: {df['time'].min()} to {df['time'].max()}")
        
        return df
        
    except Exception as e:
        print(f"Error fetching historical data: {e}")
        traceback.print_exc()
        return pd.DataFrame()

def check_ema_cross_signals(symbol, current_ema_short, current_ema_long, prev_ema_short, prev_ema_long, current_price, ema_trend=None):
    """
    Check for EMA crossover signals.
    
    Args:
        symbol: Trading symbol
        current_ema_short: Current value of short-term EMA
        current_ema_long: Current value of long-term EMA
        prev_ema_short: Previous value of short-term EMA
        prev_ema_long: Previous value of long-term EMA
        current_price: Current price
        ema_trend: Optional trend EMA (e.g., EMA200)
        
    Returns:
        Dictionary with signal information
    """
    # Skip if any value is None
    if (current_ema_short is None or current_ema_long is None or 
        prev_ema_short is None or prev_ema_long is None):
        return {
            "signal": "NEUTRAL",
            "crossover_detected": False,
            "crossover_direction": None,
            "diff": current_ema_short - current_ema_long if current_ema_short is not None and current_ema_long is not None else 0
        }
        
    # Calculate the difference between EMAs
    prev_diff = prev_ema_short - prev_ema_long
    curr_diff = current_ema_short - current_ema_long
    
    # Use a small threshold for floating point comparisons
    # This helps avoid false crossover detections due to floating point issues
    epsilon = 1e-8
    
    # Detect fresh crossovers with improved floating-point handling
    bullish_crossover = (prev_diff <= epsilon and curr_diff > epsilon) or (prev_diff < 0 and curr_diff > 0)
    bearish_crossover = (prev_diff >= -epsilon and curr_diff < -epsilon) or (prev_diff > 0 and curr_diff < 0)
    
    # Also detect crossovers that just happened (when current candle shows the crossover)
    if not bullish_crossover and not bearish_crossover:
        if abs(prev_diff) < epsilon and curr_diff > epsilon:
            bullish_crossover = True
        elif abs(prev_diff) < epsilon and curr_diff < -epsilon:
            bearish_crossover = True
    
    # Verify the crossover with additional checks to prevent false signals
    # For bullish crossover: short EMA must be above long EMA by a meaningful amount
    if bullish_crossover and curr_diff < epsilon * 10:
        bullish_crossover = False
        
    # For bearish crossover: short EMA must be below long EMA by a meaningful amount
    if bearish_crossover and curr_diff > -epsilon * 10:
        bearish_crossover = False
    
    # Determine trend
    trend = "Neutral"
    if ema_trend is not None:
        if current_price > ema_trend:
            if current_ema_short > current_ema_long:
                trend = "Strong Bullish"
            else:
                trend = "Bullish"
        elif current_price < ema_trend:
            if current_ema_short < current_ema_long:
                trend = "Strong Bearish"
            else:
                trend = "Bearish"
    
    # Modified signal logic to consider both crossover and trend
    signal = "NEUTRAL"
    crossover_detected = False
    crossover_direction = None
    proposed_signal = "NEUTRAL"  # New field for proposed signal
    
    if bullish_crossover:
        crossover_detected = True
        crossover_direction = "bullish"
        # Only propose BUY if trend is also bullish or neutral
        if trend in ["Bullish", "Strong Bullish", "Neutral"]:
            proposed_signal = "BUY"
    elif bearish_crossover:
        crossover_detected = True
        crossover_direction = "bearish"
        # Only propose SELL if trend is also bearish or neutral
        if trend in ["Bearish", "Strong Bearish", "Neutral"]:
            proposed_signal = "SELL"
    
    # Debug diagnostics for crossover detection
    if DEBUG and (bullish_crossover or bearish_crossover):
        debug_print(f"Crossover detected: {'Bullish' if bullish_crossover else 'Bearish'}")
        debug_print(f"Previous Diff: {prev_diff:.10f}, Current Diff: {curr_diff:.10f}")
        debug_print(f"Previous EMAs: Short={prev_ema_short:.6f}, Long={prev_ema_long:.6f}")
        debug_print(f"Current EMAs: Short={current_ema_short:.6f}, Long={current_ema_long:.6f}")
        debug_print(f"Proposed Signal: {proposed_signal}")
    
    return {
        "signal": "NEUTRAL",  # Always return NEUTRAL, let AI decide
        "proposed_signal": proposed_signal,  # Include the proposed signal
        "crossover_detected": crossover_detected,
        "crossover_direction": crossover_direction,
        "trend": trend,
        "diff": curr_diff,
        "prev_diff": prev_diff,
        "current_ema_position": "above" if curr_diff > 0 else "below"
    }

def load_trade_signals():
    """
    Load existing trade signals from the JSON file.
    If file doesn't exist or is empty, return empty dict.
    Retry up to 3 times if a parse error occurs.
    """
    import time
    retries = 3
    for attempt in range(retries):
        try:
            if os.path.exists(SIGNALS_FILE) and os.path.getsize(SIGNALS_FILE) > 0:
                with open(SIGNALS_FILE, 'r') as f:
                    data = json.load(f)
                    return data
            else:
                return {}
        except json.JSONDecodeError as e:
            if attempt < retries - 1:
                time.sleep(0.1)  # Wait 100ms and retry
                continue
            print(f"Error parsing signals file {SIGNALS_FILE}. File may be corrupted. Creating new file.")
            return {}
        except Exception as e:
            print(f"Error loading trade signals: {e}")
            return {}

def save_trade_signals(signals_data):
    """
    Save trade signals to the JSON file with safety check.
    Only allows BUY/SELL signals if:
    1. AUTO mode is ON, or
    2. It's being saved by tele.py (from confirmation)
    """
    try:
        # SAFETY CHECK: If AUTO mode is OFF, force all signals to NEUTRAL
        # unless called from tele.py (for confirmation)
        auto_mode = get_auto_mode()
        caller_file = traceback.extract_stack()[-2].filename
        is_telegram_call = "tele.py" in caller_file
        
        if not auto_mode and not is_telegram_call:
            # Safety check - convert any BUY/SELL to NEUTRAL if not from tele.py
            for symbol, data in signals_data.items():
                if isinstance(data, dict) and data.get("signal") in ["BUY", "SELL"]:
                    print(f"SAFETY: Converting {data['signal']} to NEUTRAL for {symbol} (AUTO OFF)")
                    data["signal"] = "NEUTRAL"
        
        # Continue with normal save
        file_dir = os.path.dirname(SIGNALS_FILE)
        if file_dir and not os.path.exists(file_dir):
            os.makedirs(file_dir)
        # Use a unique temp file
        with tempfile.NamedTemporaryFile('w', dir=file_dir or '.', delete=False) as tf:
            json.dump(signals_data, tf, indent=2)
            tempname = tf.name
        shutil.move(tempname, SIGNALS_FILE)
    except Exception as e:
        print(f"Error saving trade signals: {e}")
        traceback.print_exc()

def update_signal_data(symbol, price, signal_info, timestamp, timeframe):
    try:
        # Load existing signals
        signals_data = load_trade_signals()
        
        # Get existing signal for this symbol or create a new one
        if symbol in signals_data:
            signal_data = signals_data[symbol]
        else:
            signal_data = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "signal": "NEUTRAL",  # Always start as NEUTRAL
                "strength": "NEUTRAL",
                "noise_level": "Low",
                "trend": "Neutral",
                "price": price,
                "timeframes": {tf: "Neutral" for tf in TIMEFRAMES.keys() if TIMEFRAMES[tf]["enabled"]},
                "ema12": 0,
                "ema21": 0,
                "diff": 0,
                "processed_time": datetime.now().isoformat(),
                "crossovers": {}
            }
        
        # Current time for timestamps
        current_time = datetime.now().isoformat()
        
        # IMPORTANT: Never update main file's signal to BUY/SELL directly!
        # Only update metadata, trends, prices, etc.
        
        # Always keep signal as NEUTRAL unless already something else
        # This preserves any BUY/SELL that was properly set through confirmation
        existing_signal = signal_data.get("signal", "NEUTRAL")
        
        # Update all fields EXCEPT signal (keep existing)
        signal_data["timestamp"] = current_time
        signal_data["price"] = price
        signal_data["ema12"] = signal_info.get("ema12", 0)
        signal_data["ema21"] = signal_info.get("ema21", 0) 
        signal_data["diff"] = signal_info.get("diff", 0)
        signal_data["processed_time"] = current_time
        # ... other metadata updates ...
        
        # If crossover detected, only update crossover data, NOT signal
        if signal_info["crossover_detected"]:
            # Store crossover info but DON'T change signal
            print(f"Crossover detected for {symbol} ({timeframe}): {signal_info['crossover_direction']}")
            # ... update crossover data ...
            
        # Always update the signals data dictionary and save
        signals_data[symbol] = signal_data
        save_trade_signals(signals_data)

        # Only run AI analysis if needed - keep as a separate step
        if timeframe == MAIN_TIMEFRAME:
            print(f"Running AI analysis for {symbol} ({timeframe}) candle close...")
            
            # ====== CHECK OPEN POSITIONS FIRST ======
            open_position_exists = False
            try:
                with open("all_positions.json", "r") as f:
                    open_positions_data = json.load(f)
                positions_dict = open_positions_data.get("positions", {})
                for pos_symbol in positions_dict:
                    if pos_symbol.upper() == symbol.upper():
                        open_position_exists = True
                        break
            except Exception as e:
                open_position_exists = False
            
            # Load config to check if we should skip signals for open positions
            config = load_config()
            skip_signals = config.get("skip_signals_for_open_positions", True)
            
            if open_position_exists and skip_signals:
                print(f"Open position detected for {symbol}. Signal set to NEUTRAL and AI analysis skipped.")
                # Set signal to NEUTRAL and return
                signals_data = load_trade_signals()
                if symbol in signals_data:
                    signals_data[symbol]["signal"] = "NEUTRAL"
                    signals_data[symbol]["ai_analysis"] = {
                        "analysis": f"Open position detected for {symbol}. Signal set to NEUTRAL.",
                        "model": "system",
                        "timestamp": datetime.now().isoformat(),
                        "crossover_direction": signal_data.get("crossover_direction", None)
                    }
                    signals_data[symbol]["ai_confidence"] = 100
                    save_trade_signals(signals_data)
                    # Send trading signal to Telegram
                    send_trading_signal(symbol, signals_data[symbol])
                return
            
            # ====== CHECK SESSION RULES SECOND ======
            with _session_lock:
                can_trade, trade_reason, session_state = can_trade_in_session(symbol)
                
                if not can_trade:
                    print(f"🚫 SESSION RESTRICTION: {trade_reason} - Skipping AI analysis for {symbol}")
                    # Set signal to NEUTRAL and return
                    signals_data = load_trade_signals()
                    if symbol in signals_data:
                        signals_data[symbol]["signal"] = "NEUTRAL"
                        signals_data[symbol]["ai_analysis"] = {
                            "analysis": f"SESSION RESTRICTION: {trade_reason}",
                            "model": "session_manager",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "crossover_direction": signal_data.get("crossover_direction", None),
                            "session_reason": trade_reason
                        }
                        signals_data[symbol]["ai_confidence"] = 100
                        save_trade_signals(signals_data)
                    return
                else:
                    print(f"✅ ALL CHECKS PASSED - Proceeding with AI analysis for {symbol}")
            
            # Only start AI thread if all checks pass
            ai_thread = threading.Thread(
                target=analyze_signal_with_ai_and_update,
                args=(symbol, signal_data),
                daemon=False
            )
            ai_thread.start()
        
    except Exception as e:
        print(f"Error updating signal data: {e}")
        traceback.print_exc()

def analyze_signal_with_ai_and_update(symbol, signal_data):
    """Analyze signal with AI and update trade signals"""
    print(f"🔍 DEBUG: Starting AI analysis for {symbol}")
    
    try:
        # Check for open position before running AI analysis (supporting 'positions' dict structure)
        open_position_exists = False
        try:
            with open("all_positions.json", "r") as f:
                open_positions_data = json.load(f)
            positions_dict = open_positions_data.get("positions", {})
            for pos_symbol in positions_dict:
                if pos_symbol.upper() == symbol.upper():
                    open_position_exists = True
                    break
        except Exception as e:
            open_position_exists = False
        
        # Load config to check if we should skip signals for open positions
        config = load_config()
        skip_signals = config.get("skip_signals_for_open_positions", True)
        
        if open_position_exists and skip_signals:
            # Set signal to NEUTRAL and update signals file
            signals_data = load_trade_signals()
            if symbol in signals_data:
                signals_data[symbol]["signal"] = "NEUTRAL"
                signals_data[symbol]["ai_analysis"] = {
                    "analysis": f"Open position detected for {symbol}. Signal set to NEUTRAL.",
                    "model": "system",
                    "timestamp": datetime.now().isoformat(),
                    "crossover_direction": signal_data.get("crossover_direction", None)
                }
                signals_data[symbol]["ai_confidence"] = 100
                save_trade_signals(signals_data)
                print(f"Open position detected for {symbol}. Signal set to NEUTRAL and AI analysis skipped.")
                # Send trading signal to Telegram (with latest AI fields)
                send_trading_signal(symbol, signals_data[symbol])
            return
        elif open_position_exists and not skip_signals:
            print(f"Open position detected for {symbol}, but skip_signals_for_open_positions is disabled. Continuing with AI analysis.")
        
        
        print(f"🔍 DEBUG: About to start AI analysis for {symbol}")
        
        crossover_direction = signal_data.get("crossover_direction", "unknown")
        proposed_signal = signal_data.get("proposed_signal", "NEUTRAL")
        print("\n" + "="*50)
        print(f"AI ANALYSIS FOR {symbol}")
        print("="*50)
        print(f"Crossover Direction: {str(crossover_direction).upper() if crossover_direction else 'NONE'}")
        print(f"Current Price: ${signal_data.get('price', 0):.4f}")
        print("-"*50)
        # Run AI analysis
        ai_result = analyze_signal_with_ai(symbol, signal_data)
        analysis_text = ai_result["analysis"]
        
        # Extract confidence score with multiple patterns
        confidence_score = 0
        try:
            # First check standard "Confidence Score: X%" or "Confidence: X%" format
            confidence_patterns = [
                r"Confidence Score:?\s*(\d+\.?\d*)%?",
                r"confidence:?\s*(\d+\.?\d*)%?",
                r"Confidence:?\s*(\d+\.?\d*)%?"
            ]
            
            for pattern in confidence_patterns:
                import re
                match = re.search(pattern, analysis_text, re.IGNORECASE)
                if match:
                    confidence_score = float(match.group(1))
                    break
                    
            # If no match yet, check for "X%" format in confidence section
            if confidence_score == 0:
                # Look for numbered sections or headings with confidence
                sections = [
                    "Confidence Score", 
                    "Confidence", 
                    "7. Confidence", 
                    "6. Confidence", 
                    "5. Confidence"
                ]
                
                for section in sections:
                    if section in analysis_text:
                        # Find the section and look for a percentage
                        section_text = analysis_text.split(section)[1].split("\n\n")[0]
                        percent_match = re.search(r"(\d+\.?\d*)%", section_text)
                        if percent_match:
                            confidence_score = float(percent_match.group(1))
                            break
        except Exception as e:
            print(f"Error parsing confidence score: {e}")
            confidence_score = 0

        # Parse AI recommendation from analysis text
        ai_decision = "NEUTRAL"  # Default
        analysis_lower = analysis_text.lower()
        
        # First, prioritize explicit recommendations from the text
        explicit_recommendation = None
        recommendation_line = None
        
        # Look specifically for a "Recommendation: X" line which should have highest priority
        for line in analysis_text.split('\n'):
            line_lower = line.lower()
            if "recommendation:" in line_lower:
                recommendation_line = line_lower
                if "buy" in line_lower:
                    explicit_recommendation = "BUY"
                    break
                elif "sell" in line_lower:
                    explicit_recommendation = "SELL"
                    break
                elif "close" in line_lower:
                    explicit_recommendation = "CLOSE"
                    break
                elif "neutral" in line_lower:
                    explicit_recommendation = "NEUTRAL"
                    break
        
        # If we found an explicit recommendation, use it
        if explicit_recommendation:
            ai_decision = explicit_recommendation
            print(f"Using explicit recommendation: {ai_decision} from line: {recommendation_line}")
        else:
            # If no explicit recommendation is found, use the hierarchical decision process
            # Look for clear trade recommendations
            if "enter long" in analysis_lower or "buy signal" in analysis_lower or "buy entry" in analysis_lower or "buy recommendation" in analysis_lower:
                ai_decision = "BUY"
            elif "enter short" in analysis_lower or "sell signal" in analysis_lower or "sell entry" in analysis_lower or "sell recommendation" in analysis_lower:
                ai_decision = "SELL"
            elif "close position" in analysis_lower or "close the position" in analysis_lower or "close trade" in analysis_lower or "exit position" in analysis_lower or "close signal" in analysis_lower:
                ai_decision = "CLOSE"
            elif "no trade" in analysis_lower or "stay out" in analysis_lower or "no entry" in analysis_lower:
                ai_decision = "NEUTRAL"
            else:
                # Look for recommendation/conclusion section
                sections = ["conclusion", "recommendation", "trade decision", "signal status", "summary"]
                found_section = False
                
                for section in sections:
                    if not found_section and section in analysis_lower:
                        found_section = True
                        # Find the section line
                        lines = analysis_text.split('\n')
                        for i, line in enumerate(lines):
                            if section.lower() in line.lower():
                                # Check this line and next 5 lines for clear buy/sell signals
                                for j in range(i, min(i+6, len(lines))):
                                    check_line = lines[j].lower()
                                    # More explicit checks
                                    if any(term in check_line for term in ["buy signal", "long entry", "bullish entry", "enter long", "take buy"]):
                                        ai_decision = "BUY"
                                        break
                                    elif any(term in check_line for term in ["sell signal", "short entry", "bearish entry", "enter short", "take sell"]):
                                        ai_decision = "SELL"
                                        break
                                    # Add CLOSE detection for recommendation sections
                                    elif any(term in check_line for term in ["close position", "close the position", "exit position", "close trade", "close the trade"]):
                                        ai_decision = "CLOSE"
                                        break
                                    # Simpler word checks as fallback
                                    elif " buy" in check_line or "buy " in check_line:
                                        ai_decision = "BUY"
                                        break
                                    elif " sell" in check_line or "sell " in check_line:
                                        ai_decision = "SELL"
                                        break
                                    elif " close" in check_line or "close " in check_line:
                                        ai_decision = "CLOSE"
                                        break
                                    elif "no trade" in check_line or "neutral" in check_line or "no entry" in check_line:
                                        ai_decision = "NEUTRAL"
                                        break
                                if ai_decision != "NEUTRAL":
                                    break
                
        # Extra verification: if the analysis concludes with an explicit recommendation, honor it
        # Look at the last few lines of the analysis to check for a final recommendation
        last_lines = analysis_text.split('\n')[-5:]  # Check last 5 lines
        for line in last_lines:
            line_lower = line.lower()
            if "recommendation:" in line_lower:
                if "buy" in line_lower:
                    # Override only if the final recommendation is crystal clear
                    ai_decision = "BUY"
                    print(f"Final recommendation found in last lines: {line}")
                    break
                elif "sell" in line_lower:
                    ai_decision = "SELL"
                    print(f"Final recommendation found in last lines: {line}")
                    break
                elif "close" in line_lower:
                    ai_decision = "CLOSE"
                    print(f"Final recommendation found in last lines: {line}")
                    break
                elif "neutral" in line_lower:
                    ai_decision = "NEUTRAL"
                    print(f"Final recommendation found in last lines: {line}")
                    break

        # NEW: Validate AI decision against actual verified trend data
        # Get actual verified trend data for this symbol
        verified_trends = {}
        for tf_key, tf_info in TIMEFRAMES.items():
            if tf_info["enabled"] and symbol in symbol_data and tf_key in symbol_data[symbol]:
                df = symbol_data[symbol][tf_key]["df"]
                if not df.empty:
                    # Extract current trend information
                    current_price = df["close"].iloc[-1]
                    current_ema_short = df["EMA_short"].iloc[-1]
                    current_ema_long = df["EMA_long"].iloc[-1]
                    current_ema_trend = df["EMA_trend"].iloc[-1]
                    
                    # Calculate actual trend based on EMAs
                    actual_trend = "Neutral"
                    if current_price > current_ema_trend:
                        if current_ema_short > current_ema_long:
                            actual_trend = "Strong Bullish"
                        else:
                            actual_trend = "Bullish"
                    elif current_price < current_ema_trend:
                        if current_ema_short < current_ema_long:
                            actual_trend = "Strong Bearish"
                        else:
                            actual_trend = "Bearish"
                    
                    verified_trends[tf_key] = actual_trend
        
        # Check for inconsistencies between AI decision and verified trend data
        has_trend_inconsistency = False
        main_timeframe_trend = verified_trends.get(MAIN_TIMEFRAME)
        highest_timeframe = None
        highest_timeframe_trend = None
        
        # Find the highest enabled timeframe and its trend
        for tf_key in sorted(verified_trends.keys(), key=lambda x: int(x.rstrip('mhd')) if x.rstrip('mhd').isdigit() else 0, reverse=True):
            highest_timeframe = tf_key
            highest_timeframe_trend = verified_trends[tf_key]
            break
        
        # Log verification information
        print(f"TREND VERIFICATION:")
        print(f"Main Timeframe ({MAIN_TIMEFRAME}): {main_timeframe_trend}")
        if highest_timeframe:
            print(f"Highest Timeframe ({highest_timeframe}): {highest_timeframe_trend}")
        print(f"AI Decision: {ai_decision}")
        
        # Check for trend inconsistencies based on AI decision
        if highest_timeframe_trend:
            if ai_decision == "BUY" and "Bearish" in highest_timeframe_trend:
                print(f"⚠️ WARNING: AI recommends BUY but highest timeframe trend is {highest_timeframe_trend}")
                has_trend_inconsistency = True
            elif ai_decision == "SELL" and "Bullish" in highest_timeframe_trend:
                print(f"⚠️ WARNING: AI recommends SELL but highest timeframe trend is {highest_timeframe_trend}")
                has_trend_inconsistency = True
            
            # If we detect inconsistency, adjust the decision based on configuration
            if has_trend_inconsistency:
                if config.get("enforce_highest_timeframe_trend", False):
                    old_decision = ai_decision
                    # Force consistent decision with highest timeframe trend
                    if "Bullish" in highest_timeframe_trend and ai_decision == "SELL":
                        ai_decision = "NEUTRAL"
                    elif "Bearish" in highest_timeframe_trend and ai_decision == "BUY":
                        ai_decision = "NEUTRAL"
                    print(f"⚠️ ADJUSTED AI decision from {old_decision} to {ai_decision} to match highest timeframe trend")
                else:
                    print(f"⚠️ Trend inconsistency detected but keeping AI decision as enforce_highest_timeframe_trend=False")

        # Log the AI analysis result
        print("\nAI ANALYSIS RESULTS:")
        print("-"*20)
        print(f"AI Decision: {ai_decision}")
        print(f"Confidence Score: {confidence_score}%")
        print("\nAnalysis:")
        print("-"*10)
        print(f"{ai_result['analysis']}")
        print("\n" + "="*50)

        # Update the signals file with the AI analysis and decision
        signals_data = load_trade_signals()
        if symbol in signals_data:
            # Only update the signal field, not any other fields to avoid corruption
            original_signal = signals_data[symbol].get("signal", "NEUTRAL")
            signals_data[symbol]["signal"] = ai_decision
            
            # Store AI analysis in a separate field without modifying other data
            if "ai_analysis" not in signals_data[symbol]:
                signals_data[symbol]["ai_analysis"] = {}
            
            signals_data[symbol]["ai_analysis"]["analysis"] = ai_result["analysis"]
            signals_data[symbol]["ai_analysis"]["model"] = ai_result["model"]
            signals_data[symbol]["ai_analysis"]["timestamp"] = ai_result["timestamp"]
            signals_data[symbol]["ai_analysis"]["crossover_direction"] = ai_result["crossover_direction"]
            
            # Store confidence as a separate field
            signals_data[symbol]["ai_confidence"] = confidence_score
            
            # Store verified trend data to ensure consistency
            signals_data[symbol]["timeframe_trends"] = verified_trends
            
            # Collect market data for enhanced decision history
            market_data = {}
            
            # Add timeframe trends
            if "timeframes" in signal_data:
                market_data["timeframes"] = signal_data.get("timeframes", {})
            
            # Add verified timeframe trends
            market_data["verified_timeframes"] = verified_trends
            
            # Collect technical indicators
            indicators = {}
            
            # Get data from the main timeframe
            if symbol in symbol_data and MAIN_TIMEFRAME in symbol_data[symbol]:
                df = symbol_data[symbol][MAIN_TIMEFRAME]["df"]
                if not df.empty:
                    # Get the latest values for key indicators
                    latest = df.iloc[-1]
                    indicators["ema_short"] = float(latest.get("EMA_short", 0))
                    indicators["ema_long"] = float(latest.get("EMA_long", 0))
                    indicators["ema_trend"] = float(latest.get("EMA_trend", 0))
                    
                    # Add MACD if available
                    if "MACD_line" in latest:
                        indicators["macd_line"] = float(latest.get("MACD_line", 0))
                        indicators["macd_signal"] = float(latest.get("MACD_signal", 0))
                        indicators["macd_hist"] = float(latest.get("MACD_hist", 0))
                    
                    # Add RSI if available
                    if "RSI" in df.columns:
                        indicators["rsi"] = float(latest.get("RSI", 0))
                    
                    # Get recent candles (last 5)
                    recent_candles = []
                    for i in range(min(5, len(df))):
                        idx = -1 - i  # Start from the latest and go backwards
                        candle = df.iloc[idx]
                        recent_candles.append({
                            "time": candle["time"].isoformat() if isinstance(candle["time"], datetime) else str(candle["time"]),
                            "open": float(candle["open"]),
                            "high": float(candle["high"]),
                            "low": float(candle["low"]),
                            "close": float(candle["close"]),
                            "volume": float(candle["volume"])
                        })
                    market_data["recent_candles"] = recent_candles
            
            # Add indicators to market data
            market_data["indicators"] = indicators
            
            # Add key support and resistance levels
            key_levels = identify_key_levels(symbol, MAIN_TIMEFRAME)
            if key_levels:
                # Format key levels for storage (convert tuples to lists)
                formatted_levels = {
                    "support": [{"price": float(level[0]), "description": level[1]} 
                               for level in key_levels["support"][:3]],  # Store top 3 support levels
                    "resistance": [{"price": float(level[0]), "description": level[1]} 
                                  for level in key_levels["resistance"][:3]]  # Store top 3 resistance levels
                }
                market_data["key_levels"] = formatted_levels
            
            # Save the decision to history with enhanced information
            save_trading_decision(
                symbol=symbol,
                decision=ai_decision,
                confidence=confidence_score,
                price=signal_data.get("price", 0),
                timestamp=datetime.now().isoformat(),
                ai_analysis=ai_result,
                market_data=market_data
            )
            
            save_trade_signals(signals_data)
            
            # Clear output messaging based on the decision
            if ai_decision == "BUY":
                print(f"AI SET BUY SIGNAL for {symbol} with {confidence_score}% confidence")
            elif ai_decision == "SELL":
                print(f"AI SET SELL SIGNAL for {symbol} with {confidence_score}% confidence")
            elif ai_decision == "CLOSE":
                print(f"AI SET CLOSE SIGNAL for {symbol} with {confidence_score}% confidence")
            else:
                print(f"AI SET NEUTRAL for {symbol} with {confidence_score}% confidence")
                
            print(f"Updated signal file with AI analysis for {symbol}")
            print("="*50 + "\n")
        
        # Remove this duplicate notification - we'll send notifications based on signal type below
        # signals_data = load_trade_signals()
        # if symbol in signals_data:
        #     send_trading_signal(symbol, signals_data[symbol])
        
        if ai_decision in ["BUY", "SELL", "CLOSE"]:
            # For BUY/SELL/CLOSE, check AUTO mode FIRST
            if get_auto_mode():
                # AUTO ON: Update main file and send signal
                signals_data = load_trade_signals()
                if symbol in signals_data:
                    signals_data[symbol]["signal"] = ai_decision
                    signals_data[symbol]["ai_analysis"] = ai_result
                    signals_data[symbol]["ai_confidence"] = confidence_score
                    # Store verified trend data 
                    signals_data[symbol]["timeframe_trends"] = verified_trends
                    save_trade_signals(signals_data)
                    
                    # INCREMENT SESSION COUNTER FOR AUTO MODE TRADES
                    if ai_decision in ["BUY", "SELL"]:
                        increment_session_counter_on_execution(symbol, ai_decision)
                    
                    print(f"AUTO MODE ON: {ai_decision} signal for {symbol} written directly to signals.")
                    send_trading_signal(symbol, signals_data[symbol])
            else:
                # AUTO OFF: Save to pending and send for confirmation
                # IMPORTANT: Do NOT update main file here!
                if "ai_analysis" not in signal_data:
                    signal_data["ai_analysis"] = {}
                
                signal_data["signal"] = ai_decision
                signal_data["ai_analysis"]["analysis"] = ai_result["analysis"]
                signal_data["ai_analysis"]["model"] = ai_result["model"]
                signal_data["ai_analysis"]["timestamp"] = ai_result["timestamp"]
                signal_data["ai_analysis"]["crossover_direction"] = ai_result["crossover_direction"]
                signal_data["ai_confidence"] = confidence_score
                # Add verified trend data
                signal_data["timeframe_trends"] = verified_trends
                
                # Save to pending signals ONLY
                save_pending_signal(symbol, signal_data)
                send_trade_confirmation_request(symbol, signal_data)
                print(f"AUTO MODE OFF: Sent {ai_decision} signal for {symbol} to Telegram for confirmation.")
        else:
            # For NEUTRAL, update main file directly
            signals_data = load_trade_signals()
            if symbol in signals_data:
                signals_data[symbol]["signal"] = ai_decision
                if "ai_analysis" not in signals_data[symbol]:
                    signals_data[symbol]["ai_analysis"] = {}
                
                signals_data[symbol]["ai_analysis"]["analysis"] = ai_result["analysis"]
                signals_data[symbol]["ai_analysis"]["model"] = ai_result["model"]
                signals_data[symbol]["ai_analysis"]["timestamp"] = ai_result["timestamp"]
                signals_data[symbol]["ai_analysis"]["crossover_direction"] = ai_result["crossover_direction"]
                signals_data[symbol]["ai_confidence"] = confidence_score
                # Store verified trend data
                signals_data[symbol]["timeframe_trends"] = verified_trends
                
                save_trade_signals(signals_data)
                print(f"AI SET NEUTRAL for {symbol} with {confidence_score}% confidence")
                send_trading_signal(symbol, signals_data[symbol])
        
    except Exception as e:
        print(f"❌ ERROR in analyze_signal_with_ai_and_update for {symbol}: {e}")
        import traceback
        traceback.print_exc()

def identify_key_levels(symbol, timeframe_key, df=None):
    """
    Identify key support and resistance levels for a symbol based on historical data,
    recent price action, and past crossovers.
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        timeframe_key: The timeframe to use (e.g., "30m")
        df: Optional dataframe with price data
        
    Returns:
        Dictionary with support and resistance levels
    """
    try:
        levels = {
            "support": [],
            "resistance": []
        }
        
        # If no DataFrame provided, use the one from symbol_data
        if df is None and symbol in symbol_data and timeframe_key in symbol_data[symbol]:
            df = symbol_data[symbol][timeframe_key]["df"]
        
        if df is None or df.empty:
            return levels
            
        # Current price
        current_price = df["close"].iloc[-1]
        
        # Get high and low of last 50 candles
        recent_df = df.iloc[-50:] if len(df) > 50 else df
        
        # 1. Find swing highs and lows (peaks and valleys)
        highs = []
        lows = []
        
        # A simple method to find local peaks and valleys
        for i in range(2, len(recent_df) - 2):
            # Check for a peak (potential resistance)
            if (recent_df["high"].iloc[i] > recent_df["high"].iloc[i-1] and
                recent_df["high"].iloc[i] > recent_df["high"].iloc[i-2] and
                recent_df["high"].iloc[i] > recent_df["high"].iloc[i+1] and
                recent_df["high"].iloc[i] > recent_df["high"].iloc[i+2]):
                highs.append(recent_df["high"].iloc[i])
                
            # Check for a valley (potential support)
            if (recent_df["low"].iloc[i] < recent_df["low"].iloc[i-1] and
                recent_df["low"].iloc[i] < recent_df["low"].iloc[i-2] and
                recent_df["low"].iloc[i] < recent_df["low"].iloc[i+1] and
                recent_df["low"].iloc[i] < recent_df["low"].iloc[i+2]):
                lows.append(recent_df["low"].iloc[i])
        
        # 2. Add recent crossover levels from all_trade_signals.json
        signals_data = load_trade_signals()
        if symbol in signals_data and "crossovers" in signals_data[symbol]:
            for tf, crossover in signals_data[symbol]["crossovers"].items():
                if isinstance(crossover, dict) and "price" in crossover:
                    crossover_price = crossover.get("price", 0)
                    if crossover_price > 0:
                        # If within 5% of current price, add to appropriate level list
                        if 0.95 * current_price <= crossover_price <= 1.05 * current_price:
                            if crossover_price < current_price:
                                levels["support"].append((crossover_price, f"Recent {tf} crossover"))
                            else:
                                levels["resistance"].append((crossover_price, f"Recent {tf} crossover"))
        
        # 3. Add horizontal levels from peaks and valleys
        # Group nearby levels together (within 0.5% of each other)
        grouped_highs = []
        for high in sorted(highs):
            added = False
            for i, (level, count, _) in enumerate(grouped_highs):
                if 0.995 * level <= high <= 1.005 * level:
                    # Update the group average
                    new_level = (level * count + high) / (count + 1)
                    grouped_highs[i] = (new_level, count + 1, "Swing high")
                    added = True
                    break
            if not added:
                grouped_highs.append((high, 1, "Swing high"))
                
        grouped_lows = []
        for low in sorted(lows):
            added = False
            for i, (level, count, _) in enumerate(grouped_lows):
                if 0.995 * level <= low <= 1.005 * level:
                    # Update the group average
                    new_level = (level * count + low) / (count + 1)
                    grouped_lows[i] = (new_level, count + 1, "Swing low")
                    added = True
                    break
            if not added:
                grouped_lows.append((low, 1, "Swing low"))
        
        # 4. Add psychological levels (round numbers)
        # Determine the appropriate decimal places based on the price magnitude
        if current_price < 0.1:  # Very low-value coins
            decimal_places = 4
        elif current_price < 1:  # Low-value coins
            decimal_places = 3
        elif current_price < 10:  # Medium-low
            decimal_places = 2
        elif current_price < 100:  # Medium
            decimal_places = 1
        elif current_price < 1000:  # Medium-high
            decimal_places = 0
        else:  # High-value (like BTC)
            decimal_places = -1  # Round to tens/hundreds
            
        # Generate psychological levels above and below current price
        price_magnitude = 10 ** decimal_places
        
        # Add psychological levels above current price
        psych_level = math.ceil(current_price / price_magnitude) * price_magnitude
        for i in range(3):  # Add 3 levels above
            if psych_level > current_price:  # Only if above current price
                levels["resistance"].append((psych_level, "Psychological level"))
            psych_level += price_magnitude
            
        # Add psychological levels below current price
        psych_level = math.floor(current_price / price_magnitude) * price_magnitude
        for i in range(3):  # Add 3 levels below
            if psych_level < current_price:  # Only if below current price
                levels["support"].append((psych_level, "Psychological level"))
            psych_level -= price_magnitude
            
        # 5. Add strong support/resistance from grouped peaks and valleys
        # Add swing highs as resistance (if above current price)
        for level, count, desc in grouped_highs:
            if level > current_price:
                strength = "Strong" if count >= 2 else "Moderate"
                levels["resistance"].append((level, f"{strength} {desc} (tested {count}x)"))
            
        # Add swing lows as support (if below current price)
        for level, count, desc in grouped_lows:
            if level < current_price:
                strength = "Strong" if count >= 2 else "Moderate"
                levels["support"].append((level, f"{strength} {desc} (tested {count}x)"))
                
        # 6. Add recent EMA levels
        current_ema_short = df["EMA_short"].iloc[-1]
        current_ema_long = df["EMA_long"].iloc[-1]
        current_ema_trend = df["EMA_trend"].iloc[-1]
        
        if current_ema_short < current_price:
            levels["support"].append((current_ema_short, "Short EMA"))
        else:
            levels["resistance"].append((current_ema_short, "Short EMA"))
            
        if current_ema_long < current_price:
            levels["support"].append((current_ema_long, "Long EMA"))
        else:
            levels["resistance"].append((current_ema_long, "Long EMA"))
            
        if current_ema_trend < current_price:
            levels["support"].append((current_ema_trend, "Trend EMA"))
        else:
            levels["resistance"].append((current_ema_trend, "Trend EMA"))
            
        # Sort levels by price (ascending for support, descending for resistance)
        levels["support"] = sorted(levels["support"], key=lambda x: x[0], reverse=False)
        levels["resistance"] = sorted(levels["resistance"], key=lambda x: x[0], reverse=False)
        
        return levels
        
    except Exception as e:
        print(f"Error identifying key levels: {e}")
        traceback.print_exc()
        return {"support": [], "resistance": []}

def get_all_trades_signals_data(symbol=None):
    """
    Load all the data from all_trade_signals.json for analysis
    
    Args:
        symbol: Optional symbol to filter for
        
    Returns:
        Dictionary with signals data
    """
    try:
        signals_data = load_trade_signals()
        
        if symbol:
            # Return just the data for the specified symbol
            return signals_data.get(symbol, {})
        
        return signals_data
    except Exception as e:
        print(f"Error getting all trade signals data: {e}")
        return {}

def analyze_signal_with_ai(symbol, signal_data):
    """
    Use an LLM to analyze trading signals and provide insights.

    The model is configurable: set AI_MODEL (or MODEL) in .env. Routes through
    OpenRouter when OPENROUTER_API_KEY is set, otherwise OpenAI directly.
    
    Args:
        symbol: Trading symbol
        signal_data: Dictionary with signal data
        
    Returns:
        Dictionary with analysis results
    """
    # Client and model both come from the environment - see .env.example.
    ai_model = os.getenv("AI_MODEL") or os.getenv("MODEL") or "gpt-5-mini"
    if os.getenv("OPENROUTER_API_KEY"):
        client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )
    else:
        client = OpenAI()  # reads OPENAI_API_KEY
    
    # Extract key data for analysis
    price = signal_data.get('price', 0)
    timeframes = signal_data.get('timeframes', {})
    crossovers = signal_data.get('crossovers', {})
    
    # Identify crossover direction
    crossover_direction = signal_data.get('crossover_direction', 'unknown')
    
    # Get current time and determine active market sessions
    current_time_utc = datetime.now(timezone.utc)
    current_time_str = current_time_utc.strftime("%H:%M")
    
    # Check which market sessions are active
    def is_time_in_session(time_str, session):
        if session["start"] <= session["end"]:
            return session["start"] <= time_str <= session["end"]
        else:  # Session crosses midnight
            return time_str >= session["start"] or time_str <= session["end"]
            
    tokyo_active = is_time_in_session(current_time_str, TOKYO_SESSION)
    london_active = is_time_in_session(current_time_str, LONDON_SESSION)
    ny_active = is_time_in_session(current_time_str, NY_SESSION)
    
    active_sessions = []
    if tokyo_active:
        active_sessions.append("Tokyo")
    if london_active:
        active_sessions.append("London")
    if ny_active:
        active_sessions.append("New York")
        
    active_sessions_str = ", ".join(active_sessions) if active_sessions else "No major session"
    
    # Get recent candle data for the main timeframe
    recent_candles = []
    actual_trends = {}  # Store actual trend data from dataframes
    
    # Collect actual trend data from dataframes for each timeframe
    for tf_key, tf_info in TIMEFRAMES.items():
        if tf_info["enabled"] and symbol in symbol_data and tf_key in symbol_data[symbol]:
            df = symbol_data[symbol][tf_key]["df"]
            if not df.empty:
                # Determine actual trend from the latest data
                current_price = df["close"].iloc[-1]
                current_ema_short = df["EMA_short"].iloc[-1]
                current_ema_long = df["EMA_long"].iloc[-1]
                current_ema_trend = df["EMA_trend"].iloc[-1]
                
                # Calculate actual trend
                actual_trend = "Neutral"
                if current_price > current_ema_trend:
                    if current_ema_short > current_ema_long:
                        actual_trend = "Strong Bullish"
                    else:
                        actual_trend = "Bullish"
                elif current_price < current_ema_trend:
                    if current_ema_short < current_ema_long:
                        actual_trend = "Strong Bearish"
                    else:
                        actual_trend = "Bearish"
                
                actual_trends[tf_key] = {
                    "trend": actual_trend,
                    "price": current_price,
                    "ema_short": current_ema_short,
                    "ema_long": current_ema_long,
                    "ema_trend": current_ema_trend,
                    "diff": current_ema_short - current_ema_long
                }
    
    # Get specific data for the main timeframe
    if symbol in symbol_data and MAIN_TIMEFRAME in symbol_data[symbol]:
        df = symbol_data[symbol][MAIN_TIMEFRAME]["df"]
        if not df.empty:
            # Select last 50 candles
            recent_df = df.tail(50)
            # Convert to dict for each row
            recent_candles = recent_df[["time", "open", "high", "low", "close", "volume", "EMA_short", "EMA_long", "EMA_trend", "MACD_line", "MACD_signal", "MACD_hist"]].to_dict(orient="records")
    
    # Format candle data as markdown table
    candle_table = ""
    if recent_candles:
        candle_table = "\n## Recent Candle Data (last 50 candles)\n"
        candle_table += "| Time | Open | High | Low | Close | Vol | EMA12 | EMA21 | EMA50 | MACD | MACD_Sig | MACD_Hist |\n"
        candle_table += "|------|------|------|-----|-------|-----|-------|-------|-------|------|----------|-----------|\n"
        for row in recent_candles:
            candle_table += f"| {row['time'].strftime('%H:%M:%S')} | {row['open']:.4f} | {row['high']:.4f} | {row['low']:.4f} | {row['close']:.4f} | {row['volume']:.2f} | {row['EMA_short']:.4f} | {row['EMA_long']:.4f} | {row['EMA_trend']:.4f} | {row['MACD_line']:.4f} | {row['MACD_signal']:.4f} | {row['MACD_hist']:.4f} |\n"
    else:
        candle_table = "\nNo recent candle data available.\n"
    
    # Format crossover data
    crossover_info = ""
    for tf, cross_data in crossovers.items():
        if isinstance(cross_data, dict):
            crossover_info += f"\nTimeframe {tf}: {cross_data.get('direction', 'none')} at ${cross_data.get('price', 0)}, {cross_data.get('candles_ago', '?')} candles ago"
    
    # Build trading timeframe configuration from global TIMEFRAMES
    timeframe_config = ", ".join([f"{tf}: {'Enabled' if details['enabled'] else 'Disabled'}" for tf, details in TIMEFRAMES.items()])

    # Load open positions from all_positions.json and calculate accurate ROI
    position_data = None
    roi_pct = 0
    try:
        with open("all_positions.json", "r") as f:
            open_positions = json.load(f)
        positions = open_positions.get("positions", {})
        
        # Check if we have a position for this symbol and calculate its ROI
        if symbol in positions:
            position = positions[symbol]
            # Use the calculate_position_roi function to get accurate ROI
            roi_pct = calculate_position_roi(position)
            
            # Update the position with accurate ROI
            position["roi_pct"] = roi_pct
            position["pnl_percentage"] = roi_pct
            
            position_data = position
        
        open_positions_str = json.dumps(open_positions, indent=2)
    except Exception as e:
        open_positions_str = f"Error loading positions: {e}"

    # Load symbol configuration from trading_config.json
    try:
        with open("trading_config.json", "r") as f:
            config_data = json.load(f)
        symbol_config = config_data.get("symbol_config", {})
        symbol_config_str = json.dumps(symbol_config, indent=2)
    except Exception as e:
        symbol_config_str = "No symbol configuration available."
    
    # Get all signals data for context
    all_signals = get_all_trades_signals_data()
    
    # Extract relevant signals data for this symbol and other symbols
    other_symbols_data = ""
    for other_symbol, other_data in all_signals.items():
        if other_symbol != symbol and "signal" in other_data:
            other_symbols_data += f"{other_symbol}: Signal={other_data.get('signal', 'NEUTRAL')}, Trend={other_data.get('trend', 'Neutral')}\n"
    
    # Identify key support and resistance levels
    main_tf_key = MAIN_TIMEFRAME
    key_levels = identify_key_levels(symbol, main_tf_key)
    
    # Format the levels for the prompt
    support_levels_str = ""
    resistance_levels_str = ""
    
    # Sort support levels from highest to lowest
    sorted_support = sorted(key_levels["support"], key=lambda x: x[0], reverse=True)
    for level, desc in sorted_support[:5]:  # Take top 5
        support_levels_str += f"• ${level:.6g} - {desc}\n"
        
    # Sort resistance levels from lowest to highest
    sorted_resistance = sorted(key_levels["resistance"], key=lambda x: x[0])
    for level, desc in sorted_resistance[:5]:  # Take top 5
        resistance_levels_str += f"• ${level:.6g} - {desc}\n"
    
    # Add proximity warning if price is too close to resistance
    warning_str = ""
    for level, desc in sorted_resistance:
        if price * 1.01 >= level >= price:  # Within 1% of resistance above current price
            warning_str = f"⚠️ WARNING: Price (${price}) is within 1% of resistance at ${level:.6g} ({desc}). This is a risky entry point for a long position."
            break

    # Add proximity warning if price is too close to support
    for level, desc in sorted_support:
        if price <= level <= price * 1.01:  # Within 1% of support below current price
            warning_str = f"⚠️ WARNING: Price (${price}) is within 1% of support at ${level:.6g} ({desc}). This is a risky entry point for a short position."
            break
    
    # Load trading decision history for this symbol
    decision_history = load_trading_decision_history(symbol)
    decision_history_str = ""
    if decision_history and isinstance(decision_history, list):
        decision_history_str = "\n## Trading Decision History (Most Recent First)\n"
        decision_history_str += "| Time | Decision | Confidence | Price |\n"
        decision_history_str += "|------|----------|------------|-------|\n"
        
        # Add most recent 10 decisions to the history table - handle both list and dict return types
        history_items = decision_history[:10] if isinstance(decision_history, list) else []
        for i, decision in enumerate(history_items):
            timestamp = decision.get("timestamp", "")
            if isinstance(timestamp, str) and timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    timestamp = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    # If parsing fails, just use the string
                    pass
            
            decision_str = decision.get("decision", "UNKNOWN")
            confidence = decision.get("confidence", 0)
            price = decision.get("price", 0)
            
            decision_history_str += f"| {timestamp} | {decision_str} | {confidence}% | ${price:.4f} |\n"
    else:
        decision_history_str = "\nNo trading decision history available for this symbol.\n"
        
    # Prepare verified timeframe trend data
    verified_timeframes_data = ""
    for tf, trend_data in actual_trends.items():
        verified_timeframes_data += f"• {tf}: {trend_data['trend']} (EMA short={trend_data['ema_short']:.6f}, EMA long={trend_data['ema_long']:.6f}, diff={trend_data['diff']:.6f})\n"
    
    # Determine the highest timeframe and its trend
    highest_timeframe = None
    highest_timeframe_trend = None
    
    for tf_key in sorted(actual_trends.keys(), key=lambda x: int(x.rstrip('mhd')) if x.rstrip('mhd').isdigit() else 0, reverse=True):
        highest_timeframe = tf_key
        highest_timeframe_trend = actual_trends[tf_key]["trend"]
        break
            
    # Add position ROI information with accurate calculations
    position_info_str = ""
    if position_data:
        side = position_data.get("side", "Unknown")
        entry_price = position_data.get("entry_price", position_data.get("entryPrice", 0))
        mark_price = position_data.get("mark_price", position_data.get("markPrice", current_price))
        leverage = position_data.get("leverage", 1)
        size = position_data.get("size", 0)
        value = position_data.get("value", 0)
        
        # Highlight the accurate ROI calculation that includes leverage
        position_info_str = f"""
## Current Position Information
- Symbol: {symbol}
- Side: {side}
- Entry Price: ${entry_price}
- Current Price: ${mark_price}
- Size: {size}
- Leverage: {leverage}x
- ROI (with leverage): {roi_pct:.2f}%
"""
    
    # ADD SMI ANALYSIS SECTION - Get current SMI data AND from decision history
    smi_analysis = get_smi_analysis_for_symbol(symbol, [tf for tf in TIMEFRAMES.keys() if TIMEFRAMES[tf]["enabled"]])
    
    # Also get SMI data from recent decision history
    smi_history_str = ""
    if decision_history and isinstance(decision_history, list):
        recent_smi_decisions = [d for d in decision_history[:5] if d.get("smi_analysis")]
        if recent_smi_decisions:
            smi_history_str = "\n### Recent SMI History:\n"
            for i, decision in enumerate(recent_smi_decisions):
                smi_data = decision.get("smi_analysis", {})
                overall = smi_data.get("overall_assessment", {})
                smi_history_str += f"**{decision.get('timestamp', '')}**: Entry Rec: {overall.get('entry_recommendation', 'N/A')}, Exhaustion: {overall.get('exhaustion_risk_level', 'N/A')}, Direction: {overall.get('overall_direction', 'N/A')}\n"
    
    # Format SMI data for the prompt
    smi_section = ""
    if smi_analysis and smi_analysis.get('status') == 'AVAILABLE':
        smi_section = f"""
## Stochastic Momentum Index (SMI) Analysis
**CRITICAL: SMI helps detect trend exhaustion and prevents bad re-entries after stop-outs**

### Overall SMI Assessment:
- Direction: {smi_analysis['overall_assessment'].get('overall_direction', 'UNKNOWN')}
- Trend Consistency: {smi_analysis['overall_assessment'].get('trend_consistency', 0)}%
- Entry Recommendation: {smi_analysis['overall_assessment'].get('entry_recommendation', 'NEUTRAL')}
- Exhaustion Risk: {smi_analysis['overall_assessment'].get('exhaustion_risk_level', 'UNKNOWN')}
- Momentum Shift Risk: {smi_analysis['overall_assessment'].get('momentum_shift_risk', 'UNKNOWN')}

### SMI by Timeframe:
"""
        for tf, smi_data in smi_analysis.get('timeframes', {}).items():
            smi_section += f"""
**{tf}:**
- SMI %K: {smi_data['smi_k']} | SMI %D: {smi_data['smi_d']}
- Signal: {smi_data['signal']} | Momentum: {smi_data['momentum']}
- Trend Strength: {smi_data['trend_strength']} | Direction: {smi_data['trend_direction']}
- Exhaustion Risk: {smi_data['exhaustion_risk']} | Momentum Shift: {smi_data['momentum_shift']}
- Divergence: {smi_data['divergence']} | Confidence: {smi_data['confidence']}%
"""
        
        # Add warnings if any
        warnings = smi_analysis['overall_assessment'].get('warnings', [])
        if warnings:
            smi_section += f"\n⚠️ **SMI WARNINGS:** {', '.join(warnings)}\n"
        
        # Add historical SMI context
        smi_section += smi_history_str
    else:
        smi_section = "\n## SMI Analysis: Not available\n"
    
    # Build a comprehensive prompt with trading rules - ORIGINAL PROMPT + SMI SECTION
    prompt = f"""
# Trading Signal Analysis for {symbol}

{smi_section}

## Current Market Data
- Symbol: {symbol}
- Current Price: ${price}
- Current Time (UTC): {current_time_str}
- Active Market Sessions: {active_sessions_str}
- EMA Values: short={signal_data.get('ema12', 0)}, long={signal_data.get('ema21', 0)}
- EMA Difference: {signal_data.get('diff', 0)}
- Crossover Direction (if any): {crossover_direction}

{warning_str}

## VERIFIED Timeframe Trends (From Raw Data)
{verified_timeframes_data}

## IMPORTANT TREND INFORMATION
THE VERIFIED HIGHEST TIMEFRAME ({highest_timeframe}) TREND IS: {highest_timeframe_trend}
THE VERIFIED MAIN TIMEFRAME ({MAIN_TIMEFRAME}) TREND IS: {actual_trends.get(MAIN_TIMEFRAME, {}).get("trend", "Unknown")}

You MUST acknowledge these verified trends in your analysis and ensure your recommendation is consistent with them.

{position_info_str}

## Key Support & Resistance Levels
### Resistance Levels (Price barriers above)
{resistance_levels_str}

### Support Levels (Price floors below)
{support_levels_str}

## Multi-Timeframe Trends
{', '.join([f"{tf}: {trend}" for tf, trend in timeframes.items()])}

## Trading Timeframe Configuration
{timeframe_config}

## Recent Crossovers
{crossover_info}

## Open Positions
{open_positions_str}

## Symbol Configuration
{symbol_config_str}

## Other Symbols Trends
{other_symbols_data}

{decision_history_str}

{candle_table}

You are a sophisticated trader,
Core Principles  
   • Check for ema cross overs, call the trend if align with the day trend proceed if not do not enter unless is a clear sign or reversal or solid pullback 
   Follow your intuition, if we enter can we get atleast 30/50% with the existing leverage?
   You are the best trader in the world, you are a hybrid of scalping and interday trading, you are a master of both.
   If there is a long wick at the bottom or top awaiting a pullback or a reversal you are allow to go against the trend and enter the trade.

IMPORTANT: Use the VERIFIED Timeframe Trends section above for your analysis. This contains accurate trend data calculated directly from the price and EMAs. Do not contradict this verified data in your analysis.
Is the trend ending or starting?
What the canles tell us?
How do you interpret them?

## CRITICAL SMI INTEGRATION RULES informational only:
1. **NEVER enter a trade when SMI shows VERY_HIGH exhaustion risk**
2. **AVOID re-entering after stop-out if SMI shows momentum shift or divergence**
3. **Use SMI warnings to prevent bad entries at trend ends**
4. **If SMI shows CAUTION or WAIT recommendation, be very conservative**
5. **SMI divergence is a strong signal that trend may be ending**
6. **Consider SMI history from previous decisions to avoid repeated mistakes**

## Position Management Instructions
- Position Status: {open_positions_str}
- If NO open position exists for this symbol and market conditions are favorable, recommend entering the market with BUY or SELL.
- If an open position EXISTS for this symbol:
  1. If the trend is continuing in the SAME direction as the position → recommend NEUTRAL (let it run)
  2. If the trend is clearly shifting in the OPPOSITE direction of the position → recommend CLOSE, DO NOT CLOSE IF THE MARKET ALLOWS IT TO RUN or is JUST a swing, allow -25% ROI before closing PLEASE even if is temporary trend shift!
  IMPORTANT: You are allow to close only positive positions to lock in profits as negative positions will be handled by the stoploss that is already preset, if the stoploss fail to trigger you can close the position > or = to -25% ROI.
  3. For major shifts from bullish to bearish (or vice versa), recommend CLOSE to lock in profits
  4. Be careful not to close too early on minor pullbacks or fake signals, aloow -25% ROI before closing PLEASE.
  5. Calculate unrealized PnL with leverage in mind: {symbol_config_str}
  6. Evaluate if ROI meets our target (10% minimum, if the market allow let it run)
  7. You can counter the trend if we are at the end of the run.
  8. Counter the trend if you have a feeling is a reversal or a pullback we need to make sure we are not in a trap, what institutions and whales do is make the market go up and down in a way that is not logical, we need to be aware of this and not get trapped.
  The trend lines are indicators of the trend not the buy and sell signal!
## Market Sessions Times (UTC)
- TOKYO_SESSION: {TOKYO_SESSION["start"]} - {TOKYO_SESSION["end"]} - Currently {"ACTIVE" if tokyo_active else "INACTIVE"}
- LONDON_SESSION: {LONDON_SESSION["start"]} - {LONDON_SESSION["end"]} - Currently {"ACTIVE" if london_active else "INACTIVE"}
- NY_SESSION: {NY_SESSION["start"]} - {NY_SESSION["end"]} - Currently {"ACTIVE" if ny_active else "INACTIVE"}
- CURRENT_TIME (UTC): {current_time_str}

Consider the current market session when making your trading decision. Asian session tends to range more, while London/NY sessions often have more volatility and trend movements.

Try to identify pivot points, retests, and high probability entry zones!

Review your past decisions (shown in the Trading Decision History section) and maintain consistency unless there's a clear reason to change your view. Don't flip-flop between signals without solid evidence.

{get_session_rules_for_ai()}

## Analysis Request

1. Provide specific: BUY, SELL, CLOSE or NEUTRAL based on data and logic.
2. Provide a confidence score (0-100%).
3. Consider your previous decisions for this symbol and maintain consistency unless there's a clear reason to change your view.
4. Your analysis MUST acknowledge the highest timeframe trend: {highest_timeframe_trend} for {highest_timeframe}
5. You must explain explicitly how your recommendation aligns with or differs from the highest timeframe trend
6. **MANDATORY: Address the SMI analysis in your reasoning and how it affects your decision**
**MANDATORY: Check session trading rules and enforce them strictly**
## IMPORTANT: EXPLICITLY STATE YOUR RECOMMENDATION
At the end of your analysis, CLEARLY state one of:
- "Recommendation: BUY" (if a long entry is justified)
- "Recommendation: SELL" (if a short entry is justified)
- "Recommendation: CLOSE" (if a position should be closed)
- "Recommendation: NEUTRAL" (if no trade should be taken now)
"""

    # Invoke chat completion API for analysis
    response = client.chat.completions.create(
        model=ai_model,
        messages=[{"role": "user", "content": prompt}]
    )
    
    # Extract analysis from the chat response
    analysis = response.choices[0].message.content
    
    return {
        "analysis": analysis,
        "model": ai_model,
        "timestamp": datetime.now().isoformat(),
        "crossover_direction": crossover_direction
    }

def validate_signal_file():
    """
    Validate the signal file to ensure all entries are correctly formatted
    """
    try:
        signals_data = load_trade_signals()
        
        # Remove _last_update from validation if it exists
        if "_last_update" in signals_data:
            last_update = signals_data.pop("_last_update")
        
        # Validate each symbol's data
        for symbol, signal_data in signals_data.items():
            # Skip metadata keys that start with underscore
            if symbol.startswith('_'):
                continue
                
            # Check for required fields
            required_fields = ["signal", "symbol", "price", "trend"]
            missing_fields = [field for field in required_fields if field not in signal_data]
            
            if missing_fields:
                print(f"WARNING: Signal data for {symbol} is missing required fields: {missing_fields}")
                # Initialize missing fields with default values
                for field in missing_fields:
                    if field == "signal":
                        signal_data[field] = "NEUTRAL"
                    elif field == "symbol":
                        signal_data[field] = symbol
                    elif field == "price":
                        signal_data[field] = 0
                    elif field == "trend":
                        signal_data[field] = "Neutral"
            
            # Validate crossover consistency
            if signal_data.get("crossover_detected", False):
                direction = signal_data.get("crossover_direction")
                signal = signal_data.get("signal")
                
                # Only update signal if we have a valid crossover direction
                if direction in ["bullish", "bearish"]:
                    if direction == "bullish" and signal != "BUY":
                        print(f"WARNING: Inconsistent signal data for {symbol}: Bullish crossover but signal is {signal}")
                        # Only update to BUY if we're not in a NEUTRAL state
                        if signal != "NEUTRAL":
                            signal_data["signal"] = "BUY"
                            print(f"Updated {symbol} signal to BUY based on bullish crossover")
                    elif direction == "bearish" and signal != "SELL":
                        print(f"WARNING: Inconsistent signal data for {symbol}: Bearish crossover but signal is {signal}")
                        # Only update to SELL if we're not in a NEUTRAL state
                        if signal != "NEUTRAL":
                            signal_data["signal"] = "SELL"
                            print(f"Updated {symbol} signal to SELL based on bearish crossover")
                else:
                    # If we have crossover_detected but no valid direction, reset crossover state
                    print(f"WARNING: Invalid crossover direction for {symbol}: {direction}")
                    signal_data["crossover_detected"] = False
                    signal_data["crossover_direction"] = None
                    signal_data["signal"] = "NEUTRAL"
                    print(f"Reset {symbol} crossover state due to invalid direction")
            
            # Ensure crossovers dictionary exists
            if "crossovers" not in signal_data:
                signal_data["crossovers"] = {}
            
            # Validate timeframe-specific crossovers
            for tf, crossover in signal_data["crossovers"].items():
                if isinstance(crossover, dict):
                    # Ensure crossover has required fields
                    if "direction" not in crossover:
                        print(f"WARNING: Missing direction in {symbol} {tf} crossover data")
                        crossover["direction"] = None
                    if "signal" not in crossover:
                        print(f"WARNING: Missing signal in {symbol} {tf} crossover data")
                        crossover["signal"] = "NEUTRAL"
                    
                    # Validate crossover signal consistency
                    if crossover["direction"] == "bullish" and crossover["signal"] != "BUY":
                        print(f"WARNING: Inconsistent {tf} crossover signal for {symbol}: Bullish but signal is {crossover['signal']}")
                        crossover["signal"] = "BUY"
                    elif crossover["direction"] == "bearish" and crossover["signal"] != "SELL":
                        print(f"WARNING: Inconsistent {tf} crossover signal for {symbol}: Bearish but signal is {crossover['signal']}")
                        crossover["signal"] = "SELL"
        
        # Add back _last_update
        signals_data["_last_update"] = datetime.now().isoformat()
        
        # Save validated data
        save_trade_signals(signals_data)
        return True
    except Exception as e:
        print(f"Error validating signal file: {e}")
        traceback.print_exc()
        return False

def find_last_crossover(df):
    """
    Find the last EMA crossover from historical data.
    
    Args:
        df: DataFrame with calculated EMAs
        
    Returns:
        Dictionary with crossover information
    """
    if df.empty or len(df) < 2 or "EMA_short" not in df.columns or "EMA_long" not in df.columns:
        return {
            "found": False,
            "index": None,
            "time": None,
            "price": None,
            "direction": None
        }
    
    # Create crossover detection columns
    df["prev_diff"] = df["EMA_short"].shift(1) - df["EMA_long"].shift(1)
    df["curr_diff"] = df["EMA_short"] - df["EMA_long"]
    
    # Detect crossovers with clear zero-crossing to avoid precision issues
    epsilon = 1e-10  # Small threshold for floating point comparisons
    df["bullish_cross"] = (df["prev_diff"] <= epsilon) & (df["curr_diff"] > epsilon)
    df["bearish_cross"] = (df["prev_diff"] >= -epsilon) & (df["curr_diff"] < -epsilon)
    
    # Find the last crossover
    bullish_indices = df[df["bullish_cross"]].index.tolist()
    bearish_indices = df[df["bearish_cross"]].index.tolist()
    
    last_cross_info = {
        "found": False,
        "index": None,
        "time": None,
        "price": None,
        "direction": None
    }
    
    # Determine the last crossover index and direction
    last_idx = None
    last_dir = None
    if bullish_indices and bearish_indices:
        # choose the most recent of the two
        if bullish_indices[-1] > bearish_indices[-1]:
            last_idx, last_dir = bullish_indices[-1], "bullish"
        else:
            last_idx, last_dir = bearish_indices[-1], "bearish"
    elif bullish_indices:
        last_idx, last_dir = bullish_indices[-1], "bullish"
    elif bearish_indices:
        last_idx, last_dir = bearish_indices[-1], "bearish"
    # If we found a crossover, safely index into df
    if last_idx is not None and 0 <= last_idx < len(df):
        last_cross_info["found"] = True
        last_cross_info["index"] = last_idx
        last_cross_info["direction"] = last_dir
        last_cross_info["time"] = df.iloc[last_idx]["time"]
        last_cross_info["price"] = df.iloc[last_idx]["close"]
    
    return last_cross_info

def handle_kline_websocket(message):
    """
    Process kline data from WebSocket.
    Update EMAs, SMI and check for crossover signals across multiple timeframes.
    """
    global symbol_data
    
    try:
        # ====== SESSION MANAGEMENT: CHECK FOR SESSION CHANGES ======
        # Check for session changes on every websocket message to ensure timely detection
        session_changed, current_session, session_state = check_session_change()
        
        if DEBUG:
            debug_print(f"Received WebSocket message: {json.dumps(message)[:200]}...")
        
        # Check if message contains kline data
        if "data" in message and message.get("topic", "").startswith("kline"):
            data = message["data"]
            
            if not data or len(data) == 0:
                debug_print("No data in kline message")
                return
                
            # Extract symbol and interval from the topic
            topic = message.get("topic", "")
            parts = topic.split(".")
            if len(parts) >= 3:
                interval = parts[1]  # Interval code (e.g., "5", "15", "60")
                symbol = parts[2]    # Trading symbol (e.g., "BTCUSDT")
            else:
                debug_print(f"Cannot extract symbol from topic: {topic}")
                return
                
            # Determine timeframe key from interval
            timeframe_key = None
            for tf, info in TIMEFRAMES.items():
                if info["interval"] == interval:
                    timeframe_key = tf
                    break
                    
            if not timeframe_key:
                debug_print(f"Unknown interval: {interval}")
                return
                
            # Skip if this timeframe is not enabled
            if not TIMEFRAMES[timeframe_key]["enabled"]:
                if DEBUG:
                    debug_print(f"Skipping disabled timeframe: {timeframe_key}")
                return
                
            # Only process confirmed/closed candles to avoid false signals
            if data[0].get("confirm", True):
                # Most recent kline
                kline = data[0]
                
                # Log the full kline for debugging
                if DEBUG:
                    debug_print(f"Processing kline for {symbol} ({timeframe_key}): {json.dumps(kline)}")
                
                try:
                    # Get timestamp - handle different formats
                    timestamp = None
                    if "timestamp" in kline:
                        timestamp = int(kline["timestamp"])
                    elif "start" in kline:
                        timestamp = int(kline["start"])
                    else:
                        # If we can't find the timestamp, try to use current time
                        timestamp = int(time.time() * 1000)
                        print(f"Warning: Could not find timestamp in kline data, using current time")
                    
                    timestamp_dt = datetime.fromtimestamp(timestamp / 1000)
                    
                    # Get price data - ensure we have all values
                    try:
                        close_price = float(kline.get("close", 0))
                        open_price = float(kline.get("open", close_price))
                        high_price = float(kline.get("high", close_price))
                        low_price = float(kline.get("low", close_price))
                        volume = float(kline.get("volume", 0))
                        turnover = float(kline.get("turnover", 0))
                        
                        # Sanity check on price data
                        if close_price <= 0 or high_price <= 0 or low_price <= 0:
                            print(f"Warning: Invalid price data received for {symbol} ({timeframe_key}): close={close_price}, high={high_price}, low={low_price}")
                            return
                            
                    except (ValueError, TypeError) as e:
                        print(f"Error parsing price data: {e}")
                        print(f"Kline data: {kline}")
                        return
                    
                    # Initialize data for this symbol and timeframe if it doesn't exist
                    if symbol not in symbol_data:
                        print(f"Initializing data for {symbol} from websocket message")
                        symbol_data[symbol] = {}
                    
                    if timeframe_key not in symbol_data[symbol]:
                        print(f"Initializing {timeframe_key} timeframe for {symbol}")
                        symbol_data[symbol][timeframe_key] = {
                            "df": pd.DataFrame(),
                            "last_signal": "NEUTRAL",
                            "last_check_time": None,
                            "crossover_time": None,
                            "crossover_price": None,
                            "crossover_candles_ago": 0
                        }
                    
                    # Update our dataframe with the new candle
                    df = symbol_data[symbol][timeframe_key]["df"]
                    last_signal = symbol_data[symbol][timeframe_key]["last_signal"]
                    
                    # First, check if we need to fetch all historical data
                    if df.empty:
                        df = get_historical_klines(symbol, interval)
                        if df.empty:
                            print(f"Failed to load historical data for {symbol} ({timeframe_key}) in websocket handler")
                            return
                    else:
                        # Add the new candle to our dataframe
                        new_row = pd.DataFrame([{
                            "timestamp": timestamp,
                            "open": open_price,
                            "high": high_price,
                            "low": low_price,
                            "close": close_price,
                            "volume": volume,
                            "turnover": turnover,
                            "time": timestamp_dt
                        }])
                        
                        # If this candle already exists, replace it, otherwise append it
                        existing_time = df["time"] == timestamp_dt
                        if existing_time.any():
                            df.loc[existing_time, ["open", "high", "low", "close", "volume", "turnover"]] = [
                                open_price, high_price, low_price, close_price, volume, turnover
                            ]
                        else:
                            df = pd.concat([df, new_row], ignore_index=True)
                            
                        # Keep only the last 500 candles to avoid memory issues
                        if len(df) > 500:
                            df = df.iloc[-500:]
                    
                    # Calculate EMAs with the improved function
                    df["EMA_short"] = calculate_ema(df["close"], EMA_SHORT_PERIOD)
                    df["EMA_long"] = calculate_ema(df["close"], EMA_LONG_PERIOD)
                    df["EMA_trend"] = calculate_ema(df["close"], EMA_TREND_PERIOD)

                    # ===== NEW RSI & MACD =====
                    macd_line, macd_signal, macd_hist = calculate_macd(df["close"])
                    df["MACD_line"] = macd_line
                    df["MACD_signal"] = macd_signal
                    df["MACD_hist"] = macd_hist
                    
                    # ===== ADD SMI CALCULATION HERE =====
                    # Update SMI data for this symbol and timeframe
                    update_smi_for_symbol(symbol, timeframe_key, df)
                    
                    # Verify EMAs are calculated properly - fill any NaNs
                    for col in ["EMA_short", "EMA_long", "EMA_trend"]:
                        if df[col].isna().any():
                            df[col] = df[col].ffill().bfill()
                    # Fill any remaining NaNs in new indicators
                    for col in ["MACD_line", "MACD_signal", "MACD_hist"]:
                        if df[col].isna().any():
                            df[col] = df[col].ffill().bfill()

                    # Get current values for signal detection
                    current_price = df["close"].iloc[-1]
                    current_ema_short = df["EMA_short"].iloc[-1]
                    current_ema_long = df["EMA_long"].iloc[-1]
                    current_ema_trend = df["EMA_trend"].iloc[-1]

                    # Get previous values for crossover detection
                    if len(df) >= 2:
                        prev_ema_short = df["EMA_short"].iloc[-2]
                        prev_ema_long = df["EMA_long"].iloc[-2]
                        
                        # Check for crossover signals; ensure we get a dict back
                        signal_info = check_ema_cross_signals(symbol, current_ema_short, current_ema_long, prev_ema_short, prev_ema_long, current_price, current_ema_trend)
                        if not isinstance(signal_info, dict):
                            # Fallback default signal info
                            signal_info = {
                                'signal': 'NEUTRAL',
                                'crossover_detected': False,
                                'crossover_direction': None,
                                'trend': 'Neutral',
                                'diff': 0,
                                'prev_diff': 0,
                                'current_ema_position': 'equal'
                            }
                        
                        # Add EMA values to signal info, ensure it's a dict
                        if not isinstance(signal_info, dict):
                            signal_info = {}
                        signal_info.update({
                            "ema12": current_ema_short,
                            "ema21": current_ema_long,
                            "ema200": current_ema_trend,
                        })
                        
                        # Check for recent crossover by comparing with last known state
                        last_signal = symbol_data[symbol][timeframe_key].get("last_signal", "NEUTRAL")
                        last_cross_time = symbol_data[symbol][timeframe_key].get("crossover_time")
                        last_cross_candles_ago = symbol_data[symbol][timeframe_key].get("crossover_candles_ago", 999)
                        
                        # Send crossover alert if detected
                        if signal_info["crossover_detected"]:
                            send_crossover_alert(
                                symbol=symbol,
                                timeframe=timeframe_key,
                                direction=signal_info["crossover_direction"],
                                price=current_price,
                                diff=signal_info["diff"]
                            )
                        
                        # Add this code to check for and close positions on opposite crossovers
                        if timeframe_key in ALERT_TIMEFRAMES:
                            print(f"Checking for positions to close due to {signal_info['crossover_direction']} crossover...")
                            close_result = close_positions_on_opposite_crossover()
                            if close_result.get("closed_positions"):
                                print(f"Closed {len(close_result['closed_positions'])} positions due to opposite crossover")
                        
                        # Always update signal data for all timeframes to keep trend information current
                        update_signal_data(symbol, current_price, signal_info, timestamp_dt, timeframe_key)
                        
                        # Update our tracking data every candle, not just on crossovers
                        symbol_data[symbol][timeframe_key]["last_signal"] = signal_info["signal"]
                    
                    # Update the data in our global dictionary
                    symbol_data[symbol][timeframe_key]["df"] = df
                
                    # Always recalculate the last crossover for this symbol/timeframe
                    last_cross = find_last_crossover(df)
                    if last_cross["found"]:
                        # Update in-memory tracking for this symbol/timeframe
                        symbol_data[symbol][timeframe_key]["crossover_time"] = last_cross["time"]
                        symbol_data[symbol][timeframe_key]["crossover_price"] = last_cross["price"]
                        symbol_cross_candles_ago = len(df) - 1 - last_cross["index"]

                        # If this is the main timeframe, also update the signals file entry
                        if timeframe_key == MAIN_TIMEFRAME:
                            signals_data = load_trade_signals()
                            if symbol in signals_data:
                                signals_data[symbol]["crossover_price"] = last_cross["price"]
                                signals_data[symbol]["crossover_direction"] = last_cross["direction"]
                                signals_data[symbol]["last_cross_time"] = last_cross["time"].isoformat()
                                signals_data[symbol]["crossover_candles_ago"] = symbol_cross_candles_ago
                                signals_data[symbol]["crossover_timeframe"] = timeframe_key
                                save_trade_signals(signals_data)
                
                    # Print status update for every closed candle
                    current_time = datetime.now()
                    print(f"\n{symbol} ({timeframe_key}) Update at {current_time.strftime('%Y-%m-%d %H:%M:%S')}:")
                    print(f"Price: ${current_price:.4f}")
                    print(f"EMAs: Short={current_ema_short:.4f}, Long={current_ema_long:.4f}, Trend={current_ema_trend:.4f}")
                    print(f"Diff: {signal_info['diff']:.4f} ({signal_info.get('current_ema_position', 'unknown')})")
                    print(f"Signal: {signal_info['signal']}")
                    print(f"Trend: {signal_info['trend']}")
                    
                    # Calculate and print additional indicators
                    rsi_val = float(calculate_rsi(df["close"], RSI_PERIOD).iloc[-1])
                    macd_line, macd_signal, macd_hist = calculate_macd(df["close"])
                    print(f"RSI: {rsi_val:.2f}")
                    print(f"MACD: {macd_line.iloc[-1]:.4f}, Signal: {macd_signal.iloc[-1]:.4f}, Hist: {macd_hist.iloc[-1]:.4f}")
                    print("-" * 50)
                    if last_cross["found"]:
                        candles_ago = len(df) - 1 - last_cross["index"]
                        print(f"Last Crossover: {last_cross['direction'].upper()} at {last_cross['time'].strftime('%Y-%m-%d %H:%M:%S')}, price: ${last_cross['price']:.4f}, {candles_ago} candles ago.")
                
                except Exception as e:
                    print(f"Error processing kline data: {e}")
                    traceback.print_exc()
            else:
                if DEBUG:
                    debug_print("Skipping unconfirmed candle")
        elif "success" in message:
            # This is a subscription success message
            print(f"WebSocket subscription response: {message}")
        else:
            if DEBUG:
                debug_print(f"Received message with unknown format: {message}")
    
    except Exception as e:
        print(f"Error processing WebSocket message: {e}")
        traceback.print_exc()

def start_websocket(ping_interval=15, ping_timeout=10, reconnect_interval=5):
    """
    Initialize WebSocket connection and subscribe to kline data for all trading pairs and timeframes.
    """
    global symbol_data, active_pairs, ws
    
    try:
        # Make sure we have proper API credentials
        if not API_KEY or not API_SECRET:
            print("ERROR: API credentials not found. Set BYBIT_API_KEY and BYBIT_API_SECRET in .env file.")
            return
            
        # Load trading configuration to get symbols and enabled timeframes
        config = load_config()
        active_pairs = config.get("trading_pairs", ["BTCUSDT"])
        
        # Update timeframe configuration from config if available
        if "timeframes" in config:
            for tf, tf_config in config["timeframes"].items():
                if tf in TIMEFRAMES:
                    TIMEFRAMES[tf]["enabled"] = tf_config.get("enabled", TIMEFRAMES[tf]["enabled"])
        
        # Update alert timeframes from config if available
        global ALERT_TIMEFRAMES
        if "alert_timeframes" in config:
            ALERT_TIMEFRAMES = config["alert_timeframes"]
            
        # Update main timeframe from config if available
        global MAIN_TIMEFRAME
        if "main_timeframe" in config:
            MAIN_TIMEFRAME = config["main_timeframe"]
        
        if not active_pairs:
            print("No trading pairs found in configuration, using default BTCUSDT")
            active_pairs = ["BTCUSDT"]
        
        # Get list of enabled timeframes
        enabled_timeframes = [tf for tf in TIMEFRAMES if TIMEFRAMES[tf]["enabled"]]
        
        print(f"Starting WebSocket connection for {len(active_pairs)} trading pairs: {', '.join(active_pairs)}")
        print(f"Enabled timeframes: {', '.join(enabled_timeframes)}")
        print(f"Alert timeframes: {', '.join(ALERT_TIMEFRAMES)}")
        print(f"Main timeframe: {MAIN_TIMEFRAME}")
        
        # Initialize symbol data dictionary and signals file
        symbol_data = {}
        signals_data = load_trade_signals()
        
        # Initialize all signals as NEUTRAL with proper structure
        for symbol in active_pairs:
            # Initialize with NEUTRAL signal and proper structure
            signal_data = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "signal": "NEUTRAL",
                "strength": "NEUTRAL",
                "noise_level": "Low",
                "trend": "Neutral",
                "price": 0,
                "timeframes": {tf: "Neutral" for tf in enabled_timeframes},
                "ema12": 0,
                "ema21": 0,
                "diff": 0,
                "processed_time": datetime.now().isoformat(),
                "crossovers": {},
                "crossover_detected": False,
                "crossover_direction": None,
                "last_cross_time": None,
                "crossover_price": None,
                "crossover_candles_ago": 0,
                "crossover_timeframe": None
            }
            signals_data[symbol] = signal_data
            
            # Initialize symbol data for each timeframe
            symbol_data[symbol] = {}
            
            for tf in enabled_timeframes:
                interval = TIMEFRAMES[tf]["interval"]
                
                # Initialize data structure for this timeframe
                symbol_data[symbol][tf] = {
                    "df": pd.DataFrame(),
                    "last_signal": "NEUTRAL",
                    "last_check_time": None,
                    "crossover_time": None,
                    "crossover_price": None,
                    "crossover_candles_ago": 0
                }
                
                # Load initial historical data for this symbol and timeframe
                df = get_historical_klines(symbol, interval)
                if df.empty:
                    print(f"Failed to load initial historical data for {symbol} ({tf}). Check your API credentials and connection.")
                else:
                    print(f"Loaded {len(df)} historical candles for {symbol} ({tf}).")
                    
                    # Calculate EMAs on historical data
                    df["EMA_short"] = calculate_ema(df["close"], EMA_SHORT_PERIOD)
                    df["EMA_long"] = calculate_ema(df["close"], EMA_LONG_PERIOD)
                    df["EMA_trend"] = calculate_ema(df["close"], EMA_TREND_PERIOD)
                        
                    # Calculate RSI and MACD
                    macd_line, macd_signal, macd_hist = calculate_macd(df["close"])
                    df["MACD_line"] = macd_line
                    df["MACD_signal"] = macd_signal
                    df["MACD_hist"] = macd_hist
                    
                    # ===== ADD SMI CALCULATION ON HISTORICAL DATA =====
                    # Initialize SMI data for this symbol and timeframe
                    update_smi_for_symbol(symbol, tf, df)
                    
                    # Verify EMAs are calculated properly - fill any NaNs
                    for col in ["EMA_short", "EMA_long", "EMA_trend"]:
                        if df[col].isna().any():
                            df[col] = df[col].ffill().bfill()
                    
                    # Fill any remaining NaNs in new indicators
                    for col in ["MACD_line", "MACD_signal", "MACD_hist"]:
                        if df[col].isna().any():
                            df[col] = df[col].ffill().bfill()
                    
                    # Find the last crossover from historical data
                    last_cross = find_last_crossover(df)
                    
                    # Get current values for signal info
                    current_price = df["close"].iloc[-1]
                    current_ema_short = df["EMA_short"].iloc[-1]
                    current_ema_long = df["EMA_long"].iloc[-1]
                    current_ema_trend = df["EMA_trend"].iloc[-1]
                    
                    # Update signal_data with actual price and EMA values (for main timeframe only)
                    if tf == MAIN_TIMEFRAME:
                        signal_data["price"] = current_price
                        signal_data["ema12"] = current_ema_short
                        signal_data["ema21"] = current_ema_long
                        
                        # Calculate the diff for the signal info
                        diff = current_ema_short - current_ema_long
                        signal_data["diff"] = diff
                    
                    # Determine trend for this timeframe
                    trend = "Neutral"
                    if current_price > current_ema_trend:
                        if current_ema_short > current_ema_long:
                            trend = "Strong Bullish"
                        else:
                            trend = "Bullish"
                    elif current_price < current_ema_trend:
                        if current_ema_short < current_ema_long:
                            trend = "Strong Bearish"
                        else:
                            trend = "Bearish"
                    
                    # Update timeframe-specific trend
                    signal_data["timeframes"][tf] = trend
                    
                    # If this is the main timeframe, it sets the overall trend
                    if tf == MAIN_TIMEFRAME:
                        signal_data["trend"] = trend
                    
                    if last_cross["found"]:
                        # Calculate the number of candles between the crossover and the most recent candle
                        candles_ago = len(df) - 1 - last_cross["index"]
                        
                        # Store historical crossover data
                        symbol_data[symbol][tf]["crossover_time"] = last_cross["time"]
                        symbol_data[symbol][tf]["crossover_price"] = last_cross["price"]
                        symbol_data[symbol][tf]["crossover_candles_ago"] = candles_ago
                        
                        # Store in crossovers section of signal data
                        if "crossovers" not in signal_data:
                            signal_data["crossovers"] = {}
                            
                        signal_data["crossovers"][tf] = {
                            "price": last_cross["price"],
                            "time": last_cross["time"].isoformat(),
                            "direction": last_cross["direction"],
                            "signal": "BUY" if last_cross["direction"] == "bullish" else "SELL",
                            "candles_ago": candles_ago
                        }
                        
                        # For the main timeframe, also add to main signal data section
                        if tf == MAIN_TIMEFRAME:
                            signal_data["crossover_price"] = last_cross["price"]
                            signal_data["crossover_direction"] = last_cross["direction"]
                            signal_data["last_cross_time"] = last_cross["time"].isoformat()
                            signal_data["crossover_candles_ago"] = candles_ago
                            signal_data["crossover_timeframe"] = tf
                    
                    # Store the dataframe
                    symbol_data[symbol][tf]["df"] = df
        
        # Add last update timestamp
        signals_data["_last_update"] = datetime.now().isoformat()
        
        # Save the initial signals to file
        save_trade_signals(signals_data)
        print("Initialized signal file with all NEUTRAL signals")
        
        # Initialize WebSocket with proper channel_type
        ws = WebSocket(
            testnet=False,  # Set to True for testnet
            channel_type=CATEGORY,
            trace_logging=DEBUG,  # Only enable trace logging if DEBUG is True
        )
        
        # Subscribe to kline channel for each trading pair and enabled timeframe
        for symbol in active_pairs:
            for tf, tf_info in TIMEFRAMES.items():
                if tf_info["enabled"]:
                    print(f"Subscribing to {symbol} {tf} kline stream...")
                    ws.kline_stream(
                        symbol=symbol,
                        interval=tf_info["interval"],
                        callback=handle_kline_websocket
                    )
                    time.sleep(0.5)  # Add a small delay between subscriptions to avoid rate limits
            
        print(f"Successfully subscribed to all {len(active_pairs)} trading pairs with {len(enabled_timeframes)} timeframes each")
        print(f"Waiting for EMA crossover signals on timeframes: {', '.join(ALERT_TIMEFRAMES)}")
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            
    except Exception as e:
        print(f"WebSocket error: {e}")
        traceback.print_exc()
        print("Attempting to reconnect in 5 seconds...")
        time.sleep(5)
        start_websocket(ping_interval, ping_timeout, reconnect_interval)

def process_market_data(data):
    """
    Process market data received from Bybit WebSocket.
    
    Args:
        data: Data received from WebSocket
    """
    try:
        if DEBUG:
            debug_print(f"Processing market data: {str(data)[:200]}...")
        
        # Check for topic in data to determine the type of message
        if "topic" in data and data["topic"].startswith("kline."):
            # Handle kline/candlestick data
            handle_kline_websocket(data)
        elif "success" in data:
            # Handle subscription success message
            if data["success"]:
                print(f"Successfully subscribed to {data.get('ret_msg', 'channel')}")
            else:
                print(f"Failed to subscribe: {data.get('ret_msg', 'Unknown error')}")
        elif "type" in data and data["type"] == "snapshot":
            # Handle initial snapshot data
            print(f"Received initial snapshot for {data.get('topic', 'unknown topic')}")
        elif "op" in data and data["op"] == "pong":
            # Handle pong response
            if DEBUG:
                debug_print("Received pong from server")
        else:
            if DEBUG:
                debug_print(f"Unhandled data type: {data.get('type', 'unknown')} for {data.get('topic', 'unknown')}")
    except Exception as e:
        print(f"Error processing market data: {e}")
        traceback.print_exc()

def main():
    """Main function to run the multi-timeframe EMA crossover trading system with SMI"""
    global active_pairs
    
    try:
        print(f"Starting Multi-Timeframe EMA Cross Strategy with SMI Analysis")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Configuration: {CONFIG_FILE}")
        
        # ====== SESSION MANAGEMENT INITIALIZATION ======
        # Initialize session state file if it doesn't exist
        initialize_session_state_file()
        
        # Check current session status on startup
        session_changed, current_session, session_state = check_session_change()
        
        print(f"Signal file: {SIGNALS_FILE}")
        print(f"EMA Periods: Short={EMA_SHORT_PERIOD}, Long={EMA_LONG_PERIOD}, Trend={EMA_TREND_PERIOD}")
        print("-" * 50)

        
        # Start SMI monitoring system
        start_smi_monitor()
        
        # Load configuration FIRST
        config = load_config()
        active_pairs = config.get("trading_pairs", ["BTCUSDT"])
        symbol_config = config.get("symbol_config", {})
        enabled_timeframes = [tf for tf, v in TIMEFRAMES.items() if v["enabled"]]
        alert_timeframes = config.get("alert_timeframes", ALERT_TIMEFRAMES)
        main_timeframe = config.get("main_timeframe", MAIN_TIMEFRAME)

        # Format trading pairs with config
        pairs_lines = []
        for symbol in active_pairs:
            conf = symbol_config.get(symbol, {})
            lev = conf.get("leverage", "N/A")
            pos = conf.get("position_usdt", "N/A")
            pairs_lines.append(f"• <b>{symbol}</b> (Leverage: <code>{lev}x</code>, Size: <code>${pos}</code>)")
        pairs_str = "\n".join(pairs_lines) if pairs_lines else "N/A"

        # Format enabled timeframes
        tf_lines = [f"• <b>{tf}</b> ({TIMEFRAMES[tf]['description']})" for tf in enabled_timeframes]
        tf_str = "\n".join(tf_lines) if tf_lines else "N/A"

        startup_message = (
            "<b>🚀 We win or we learn, let's have a good time!</b>\n\n"
            f"📅 <b>Startup Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"⚙️ <b>Configuration:</b> <code>{CONFIG_FILE}</code>\n"
            f"📊 <b>Signal file:</b> <code>{SIGNALS_FILE}</code>\n"
            f"📈 <b>EMA Periods:</b> Short=<code>{EMA_SHORT_PERIOD}</code>, Long=<code>{EMA_LONG_PERIOD}</code>, Trend=<code>{EMA_TREND_PERIOD}</code>\n\n"
            
            f"🎯 <b>Session Info:</b>\n"
            f"• Current Session: {current_session or 'No active session'}\n"
            f"• Tokyo: {TOKYO_SESSION['start']}-{TOKYO_SESSION['end']} UTC\n"
            f"• London: {LONDON_SESSION['start']}-{LONDON_SESSION['end']} UTC\n"
            f"• NY: {NY_SESSION['start']}-{NY_SESSION['end']} UTC\n"
            f"• Wait Period: {SESSION_WAIT_MINUTES} minutes after session start\n\n"
            
            "<b>💰 Trading pairs:</b>\n"
            f"{pairs_str}\n\n"
            "<b>⏱️ Enabled timeframes:</b>\n"
            f"{tf_str}\n\n"
            f"🚨 <b>Alert timeframes:</b> <code>{', '.join(alert_timeframes)}</code>\n"
            f"🎯 <b>Main timeframe:</b> <code>{main_timeframe}</code>\n"
            f"🤖 <b>Auto Mode:</b> {'✅ ON' if get_auto_mode() else '❌ OFF'}\n"
            f"📱 <b>SMI Monitoring:</b> ✅ ACTIVE"
        )
        send_telegram_message(startup_message)
        
        # Validate signal file structure
        validate_signal_file()
        
        # Update positions with correct ROI calculations at startup
        update_positions_with_roi()
        print("Updated positions with correct ROI calculations")
        
        # Start a background thread to periodically update positions with ROI
        def update_positions_periodically():
            while True:
                try:
                    time.sleep(60)  # Update every minute
                    update_positions_with_roi()
                except Exception as e:
                    print(f"Error in position update thread: {e}")
        
        roi_update_thread = threading.Thread(target=update_positions_periodically, daemon=True)
        roi_update_thread.start()
        print("Started background ROI update thread")
        
        # Create a shutdown flag for proper thread coordination
        shutdown_flag = threading.Event()
        
        try:
            # Start Telegram bot listener in a separate thread ONLY if not in standalone mode
            if not STANDALONE_MODE:
                def telegram_bot_wrapper():
                    """Wrapper to catch and report Telegram bot errors"""
                    try:
                        print("🤖 Starting Telegram bot thread...")
                        from tele import run_telegram_bot_with_shutdown  # Use the shutdown-aware version
                        print("✅ Imported run_telegram_bot_with_shutdown successfully")
                        
                        print("🔄 About to call run_telegram_bot_with_shutdown()...")
                        run_telegram_bot_with_shutdown(shutdown_flag)  # Pass the shutdown flag
                        print("📴 run_telegram_bot_with_shutdown() finished cleanly")
                        
                    except UnicodeEncodeError as e:
                        print(f"❌ TELEGRAM BOT UNICODE ERROR: {e}")
                        print("The console cannot display Unicode characters. Bot functionality may be limited.")
                        traceback.print_exc()
                    except Exception as e:
                        print(f"❌ TELEGRAM BOT ERROR: {e}")
                        traceback.print_exc()
                        print("Telegram bot thread crashed, but main program continues...")

                telegram_thread = threading.Thread(target=telegram_bot_wrapper, daemon=True)  # Make it daemon
                telegram_thread.start()
                print("Started Telegram bot listener thread")
                
                # Give the thread a moment to start and report any immediate errors
                time.sleep(2)
                if not telegram_thread.is_alive():
                    print("❌ Telegram bot thread failed to start!")
                else:
                    print("✅ Telegram bot thread started successfully")
            else:
                print("📱 Telegram bot NOT started - STANDALONE_MODE is True (bot running independently)")
            
            # NOW start WebSocket (this will block forever)
            start_websocket()
            
        except KeyboardInterrupt:
            print("\nShutting down...")
            
            # Signal the Telegram bot to shutdown
            print("🛑 Signaling Telegram bot to shutdown...")
            shutdown_flag.set()
            
            # Wait for Telegram bot thread to finish (with timeout)
            if not STANDALONE_MODE:
                print("⏱️ Waiting for Telegram bot to stop...")
                telegram_thread.join(timeout=5)  # Wait up to 5 seconds
                if telegram_thread.is_alive():
                    print("⚠️ Telegram bot thread didn't stop gracefully within timeout")
                else:
                    print("✅ Telegram bot stopped cleanly")
            
            # Send shutdown message to Telegram
            shutdown_message = "<b>🛑 Trading Bot Stopped</b>\n\n"
            shutdown_message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            shutdown_message += "Bot has been shut down."
            send_telegram_message(shutdown_message)
            
        except Exception as e:
            print(f"Unexpected error in main: {e}")
            traceback.print_exc()
            
            # Signal shutdown to all threads
            shutdown_flag.set()
            
            # Send error message to Telegram
            error_message = "<b>❌ Trading Bot Error</b>\n\n"
            error_message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            error_message += f"Error: {str(e)}\n"
            error_message += "Attempting to restart in 10 seconds..."
            send_telegram_message(error_message)
            
            # Try to reconnect
            print("Attempting to restart in 10 seconds...")
            time.sleep(10)
            main()
        
    except KeyboardInterrupt:
        print("\nShutting down...")
        # Send shutdown message to Telegram
        shutdown_message = "<b>🛑 Trading Bot Stopped</b>\n\n"
        shutdown_message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        shutdown_message += "Bot has been shut down."
        send_telegram_message(shutdown_message)
    except Exception as e:
        print(f"Unexpected error in main: {e}")
        traceback.print_exc()
        
        # Send error message to Telegram
        error_message = "<b>❌ Trading Bot Error</b>\n\n"
        error_message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        error_message += f"Error: {str(e)}\n"
        error_message += "Attempting to restart in 10 seconds..."
        send_telegram_message(error_message)
        
        # Try to reconnect
        print("Attempting to restart in 10 seconds...")
        time.sleep(10)
        main()

def handle_sigterm(signum, frame):
    from tele import send_telegram_message
    send_telegram_message("<b>🛑 Trading Bot Stopped</b>\n\nBot has been shut down via SIGTERM.")
    sys.exit(0)

def save_pending_signal(symbol, signal_data):
    try:
        pending = {}
        if os.path.exists("pending_signals.json"):
            with open("pending_signals.json", "r") as f:
                pending = json.load(f)
        pending[symbol] = signal_data
        with open("pending_signals.json", "w") as f:
            json.dump(pending, f, indent=2)
    except Exception as e:
        print(f"Error saving pending signal: {e}")

def clear_pending_signal(symbol):
    try:
        if os.path.exists("pending_signals.json"):
            with open("pending_signals.json", "r") as f:
                pending = json.load(f)
            if symbol in pending:
                del pending[symbol]
                with open("pending_signals.json", "w") as f:
                    json.dump(pending, f, indent=2)
    except Exception as e:
        print(f"Error clearing pending signal: {e}")

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
                if os.path.exists("all_trade_signals.json"):
                    with open("all_trade_signals.json", "r") as f:
                        signals = json.load(f)
                else:
                    signals = {}
                for symbol, signal_data in pending.items():
                    signals[symbol] = signal_data
                    
                    # INCREMENT SESSION COUNTER FOR AUTO MODE
                    signal_type = signal_data.get("signal")
                    if signal_type in ["BUY", "SELL"]:
                        increment_session_counter_on_execution(symbol, signal_type)
                    
                    send_telegram_message(f"✅ [AUTO MODE] Trade for <b>{symbol}</b> has been <b>ENTERED</b> automatically.")
                with open("all_trade_signals.json", "w") as f:
                    json.dump(signals, f, indent=2)
                with open("pending_signals.json", "w") as f:
                    json.dump({}, f)
    except Exception as e:
        print(f"Error processing pending signals in AUTO mode: {e}")

def close_positions_on_opposite_crossover():
    """
    Monitor EMA crossovers and close positions when a crossover in the opposite direction occurs.
    
    This function:
    1. Reads the current trade signals from all_trade_signals.json
    2. Reads open positions from all_positions.json
    3. For each open position, checks if there's a crossover in the opposite direction
    4. If an opposite crossover is detected, closes the position
    
    Returns:
        dict: Dictionary with results of position closures
    """
    try:
        # Load trade signals
        signals_data = load_trade_signals()
        
        # Load open positions
        positions_data = {}
        try:
            with open("all_positions.json", "r") as f:
                positions_data = json.load(f)
        except Exception as e:
            print(f"Error loading positions: {e}")
            return {"success": False, "error": str(e), "closed_positions": []}
        
        # Get positions dictionary
        positions = positions_data.get("positions", {})
        
        if not positions:
            print("No open positions found")
            return {"success": True, "closed_positions": []}
        
        # Enhance positions with accurate ROI calculations
        positions = enhance_position_data(positions)
        
        # Track closed positions
        closed_positions = []
        
        # Check each open position against signals
        for symbol, position in positions.items():
            # Skip if symbol not in signals
            if symbol not in signals_data:
                continue
            
            # Get position side
            position_side = position.get("side")
            if not position_side:
                print(f"Position for {symbol} has no side information")
                continue
            
            # Get signal data for this symbol
            signal = signals_data[symbol]
            
            # Get crossover direction
            crossover_direction = signal.get("crossover_direction")
            crossover_detected = signal.get("crossover_detected", False)
            
            # Check if this is a recent crossover (within last 3 candles)
            crossover_candles_ago = signal.get("crossover_candles_ago", 999)
            is_recent_crossover = crossover_candles_ago <= 3
            
            # Determine if this crossover is opposite to our position
            is_opposite_crossover = False
            
            if position_side == "Buy" and crossover_direction == "bearish":
                is_opposite_crossover = True
            elif position_side == "Sell" and crossover_direction == "bullish":
                is_opposite_crossover = True
            
            # If we have an opposite direction crossover, close the position
            if is_opposite_crossover and is_recent_crossover:
                print(f"Detected {crossover_direction} crossover opposite to {position_side} position for {symbol}")
                
                # Log current ROI for decision making
                roi_pct = position.get("roi_pct", 0)
                unrealized_pnl = position.get("unrealised_pnl", position.get("unrealized_pnl", 0))
                print(f"{symbol} current ROI: {roi_pct:.2f}%, PnL: {unrealized_pnl}")
                
                try:
                    # Import trade_manager module
                    from trade_manager import close_position
                    
                    # Close the position
                    result = close_position(symbol, position_side)
                    
                    if result:
                        print(f"Successfully closed {position_side} position for {symbol} due to opposite {crossover_direction} crossover")
                        closed_positions.append({
                            "symbol": symbol,
                            "side": position_side,
                            "crossover_direction": crossover_direction,
                            "price": signal.get("price", 0),
                            "roi_at_close": roi_pct,
                            "pnl_at_close": unrealized_pnl,
                            "timestamp": datetime.now().isoformat()
                        })
                        
                        # Send notification via Telegram
                        message = (
                            f"🔄 <b>AUTO-CLOSE:</b> Closed {position_side} position for <b>{symbol}</b>\n"
                            f"Reason: {crossover_direction.upper()} crossover detected\n"
                            f"ROI: {roi_pct:.2f}%, PnL: {unrealized_pnl}\n"
                            f"Price: ${signal.get('price', 0)}\n"
                            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        send_telegram_message(message)
                    else:
                        print(f"Failed to close position for {symbol}")
                except ImportError:
                    print("Error: trade_manager module not found")
                except Exception as e:
                    print(f"Error closing position for {symbol}: {e}")
                    traceback.print_exc()
        
        return {
            "success": True,
            "closed_positions": closed_positions
        }
        
    except Exception as e:
        print(f"Error in close_positions_on_opposite_crossover: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e), "closed_positions": []}

def save_trading_decision(symbol, decision, confidence, price, timestamp=None, ai_analysis=None, market_data=None, smi_data=None):
    """
    Save a trading decision to the history file with enhanced information including SMI data.
    
    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        decision: Decision made (BUY, SELL, CLOSE, NEUTRAL)
        confidence: AI confidence score
        price: Current price when decision was made
        timestamp: Optional timestamp (defaults to current time)
        ai_analysis: Optional AI analysis text and reasoning
        market_data: Optional market data including indicators and recent candles
        smi_data: Optional SMI analysis data
    """
    try:
        # Use current time if not provided
        if timestamp is None:
            timestamp = datetime.now().isoformat()
            
        # Create decision record with basic information
        decision_record = {
            "symbol": symbol,
            "decision": decision,
            "confidence": confidence,
            "price": price,
            "timestamp": timestamp
        }
        
        # Add position data with enhanced ROI if one exists for this symbol
        try:
            positions_data, success = safe_read_json(POSITIONS_FILE)
            if success and isinstance(positions_data, dict):
                positions = positions_data.get("positions", {})
                if symbol in positions:
                    position = positions[symbol]
                    # Calculate correct ROI
                    roi_pct = calculate_position_roi(position)
                    decision_record["position_data"] = {
                        "side": position.get("side", "Unknown"),
                        "size": position.get("size", 0),
                        "entry_price": position.get("entry_price", position.get("entryPrice", 0)),
                        "mark_price": position.get("mark_price", position.get("markPrice", 0)),
                        "leverage": position.get("leverage", 1),
                        "roi_pct": roi_pct,
                        "unrealised_pnl": position.get("unrealised_pnl", position.get("unrealized_pnl", 0))
                    }
        except Exception as e:
            print(f"Error getting position data for decision history: {e}")
        
        # Add AI analysis if provided
        if ai_analysis:
            # Extract key parts of the analysis to avoid storing too much data
            if isinstance(ai_analysis, dict):
                # Store the full analysis text
                decision_record["reasoning"] = ai_analysis.get("analysis", "")
                
                # Extract key parts like recommendation and model
                decision_record["ai_model"] = ai_analysis.get("model", "")
                decision_record["crossover_direction"] = ai_analysis.get("crossover_direction", "")
            elif isinstance(ai_analysis, str):
                # If it's just a string, store it directly
                decision_record["reasoning"] = ai_analysis
        
        # Add market data if provided
        if market_data:
            # Store timeframe trends
            if "timeframes" in market_data:
                decision_record["timeframe_trends"] = market_data["timeframes"]
            
            # Store key technical indicators
            if "indicators" in market_data:
                decision_record["indicators"] = market_data["indicators"]
            
            # Store recent candles (last 5 only to save space)
            if "recent_candles" in market_data and isinstance(market_data["recent_candles"], list):
                # Store only the last 5 candles to save space
                decision_record["recent_candles"] = market_data["recent_candles"][-5:]
            
            # Store key support/resistance levels
            if "key_levels" in market_data:
                decision_record["key_levels"] = market_data["key_levels"]
        
        # Add SMI data if provided
        if smi_data:
            decision_record["smi_analysis"] = smi_data
        
        # Load existing history
        history = load_trading_decision_history()
        
        # Add new decision to symbol's history
        if symbol not in history:
            history[symbol] = []
        
        # Add to the beginning of the list (newest first)
        history[symbol].insert(0, decision_record)
        
        # Trim to max history size
        if len(history[symbol]) > MAX_DECISION_HISTORY:
            history[symbol] = history[symbol][:MAX_DECISION_HISTORY]
        
        # Save updated history
        with open(DECISION_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
            
        return True
    except Exception as e:
        print(f"Error saving trading decision: {e}")
        traceback.print_exc()
        return False

def load_trading_decision_history(symbol=None):
    """
    Load trading decision history from file.
    
    Args:
        symbol: Optional symbol to filter for
        
    Returns:
        Dictionary with decision history by symbol, or list of decisions for a specific symbol
    """
    try:
        if os.path.exists(DECISION_HISTORY_FILE):
            with open(DECISION_HISTORY_FILE, 'r') as f:
                history = json.load(f)
                
                # If symbol specified, return just that symbol's history
                if symbol:
                    # Ensure we return a list even if the symbol doesn't exist
                    return history.get(symbol, [])
                    
                return history
        else:
            # Return empty dict if file doesn't exist
            return {} if symbol is None else []
    except Exception as e:
        print(f"Error loading trading decision history: {e}")
        return {} if symbol is None else []

def should_trade_signal(signal_data):
    """
    Check if a signal should be traded - checks if it's BUY, SELL, or CLOSE
    """
    # Extract the signal and symbol for logging
    signal = signal_data.get("signal", "NEUTRAL")
    symbol = signal_data.get("symbol", "Unknown")
    
    # Use print instead of logger since logger is not defined
    print(f"Evaluating signal for {symbol}: Signal={signal}")
    
    # Skip neutral signals
    if signal == "NEUTRAL":
        print(f"{symbol}: Signal is NEUTRAL, skipping")
        return False
    
    # Accept BUY, SELL, or CLOSE signals
    if signal in ["BUY", "SELL", "CLOSE"]:
        print(f"{symbol}: Signal APPROVED for trading - {signal}")
        return True
    
    # Any other signals are rejected
    print(f"{symbol}: Signal rejected - unknown type: {signal}")
    return False

def get_recent_decisions(symbol, count=10):
    """
    Get the most recent trading decisions for a symbol.
    
    Args:
        symbol: Trading symbol
        count: Number of decisions to retrieve
        
    Returns:
        List of recent decisions
    """
    history = load_trading_decision_history(symbol)
    if not history:
        return []
        
    # Return the specified number of most recent decisions
    return history[:min(count, len(history))]

def calculate_position_roi(position):
    """
    Calculate the correct ROI percentage for a position accounting for leverage.
    
    Args:
        position (dict): Position data dictionary containing side, entry_price, mark_price and leverage
        
    Returns:
        float: The calculated ROI percentage including leverage effect
    """
    try:
        # Extract position data with fallbacks for different field names
        side = position.get("side", "Unknown")
        
        # Get entry price using multiple possible field names
        entry_price = float(position.get("entry_price", 
                     position.get("avgPrice", 
                     position.get("entryPrice", 0))))
        
        # Get mark price using multiple possible field names
        mark_price = float(position.get("mark_price", 
                    position.get("markPrice", 0)))
        
        # Get leverage using multiple possible field names
        leverage = float(position.get("leverage", 1))
        
        # Calculate price change percentage correctly based on position side
        price_diff_pct = 0
        if entry_price > 0 and mark_price > 0:
            if side == "Buy":
                price_diff_pct = ((mark_price / entry_price) - 1) * 100
            else:  # Sell
                price_diff_pct = ((entry_price / mark_price) - 1) * 100
        
        # Apply leverage to get actual ROI percentage
        roi_pct = price_diff_pct * leverage
        
        return roi_pct
    except Exception as e:
        print(f"Error calculating position ROI: {e}")
        return 0

def enhance_position_data(positions):
    """
    Enhance position data with additional calculated fields like correct ROI.
    
    Args:
        positions (dict): Dictionary of positions by symbol
        
    Returns:
        dict: Enhanced positions with additional calculated fields
    """
    if not positions:
        return positions
        
    enhanced_positions = {}
    
    for symbol, position in positions.items():
        # Skip if not a valid position object
        if not isinstance(position, dict):
            print(f"Invalid position data for {symbol}: {position}")
            enhanced_positions[symbol] = position
            continue
            
        # Create a copy to avoid modifying the original
        enhanced_position = position.copy()
        
        # Calculate ROI with leverage effect
        roi_pct = calculate_position_roi(position)
        
        # Update position with calculated values
        enhanced_position["roi_pct"] = roi_pct
        enhanced_position["pnl_percentage"] = roi_pct
        
        # Add unrealized PnL if not present but can be calculated
        if "unrealised_pnl" not in enhanced_position and "unrealized_pnl" not in enhanced_position:
            try:
                size = float(enhanced_position.get("size", 0))
                entry_price = float(enhanced_position.get("entry_price", enhanced_position.get("entryPrice", 0)))
                mark_price = float(enhanced_position.get("mark_price", enhanced_position.get("markPrice", 0)))
                
                if enhanced_position.get("side") == "Buy":
                    unrealized_pnl = size * (mark_price - entry_price)
                else:  # Sell
                    unrealized_pnl = size * (entry_price - mark_price)
                
                enhanced_position["unrealised_pnl"] = unrealized_pnl
            except Exception as e:
                print(f"Error calculating unrealized PnL: {e}")
        
        enhanced_positions[symbol] = enhanced_position
    
    return enhanced_positions

def update_positions_with_roi():
    """
    Update the positions file with correct ROI calculations.
    This can be called periodically to ensure positions have accurate ROI data.
    """
    try:
        # Read positions file
        data, success = safe_read_json(POSITIONS_FILE)
        if not success:
            print(f"Failed to read positions file")
            return False
            
        positions = data.get("positions", {})
        
        # Enhance positions with correct ROI
        enhanced_positions = enhance_position_data(positions)
        
        # Update the positions data
        data["positions"] = enhanced_positions
        data["last_update"] = datetime.now().isoformat()
        
        # Save the updated data
        if safe_write_json(POSITIONS_FILE, data):
            print(f"Updated positions file with enhanced ROI calculations")
            return True
        else:
            print(f"Failed to save enhanced positions data")
            return False
    except Exception as e:
        print(f"Error updating positions with ROI: {e}")
        return False

# Call this function periodically from your main loop or when positions change to ensure accurate ROI data:
# update_positions_with_roi()

def rebuild_session_counters_from_history():
    """
    Rebuild session trade counters from trading decision history.
    This ensures session counters are accurate after bot restarts.
    """
    try:
        current_session = get_current_session()
        if not current_session:
            print("📊 No active session - no session counters to rebuild")
            return
            
        session_state = get_session_state()
        trades_per_symbol = {}
        
        # Load trading decision history
        history = load_trading_decision_history()
        if not history:
            print("📊 No trading history found - session counters remain empty")
            return
            
        trades_found = 0
        current_session_trades = 0
        
        # Scan through all symbols' trading history
        for symbol, decisions in history.items():
            if not decisions:
                continue
                
            # Look for BUY/SELL decisions made in the current session
            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                    
                decision_type = decision.get("decision")
                session_info = decision.get("session_info", {})
                decision_session = session_info.get("session")
                
                # Count BUY/SELL decisions made in the current session
                if decision_type in ["BUY", "SELL"] and decision_session == current_session:
                    trades_per_symbol[symbol] = trades_per_symbol.get(symbol, 0) + 1
                    trades_found += 1
                    current_session_trades += 1
                    break  # Only count one trade per symbol per session
        
        # Update session state with rebuilt counters
        session_state["trades_taken_this_session"] = trades_per_symbol
        
        if save_session_state(session_state):
            session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
            session_name = session_names.get(current_session, current_session)
            
            print(f"✅ REBUILT SESSION COUNTERS for {session_name}:")
            if trades_per_symbol:
                for symbol, count in trades_per_symbol.items():
                    print(f"   📊 {symbol}: {count}/1 trades used")
            else:
                print(f"   📊 No trades found in current {session_name}")
            print(f"   📈 Total symbols traded this session: {len(trades_per_symbol)}")
        else:
            print("❌ Failed to save rebuilt session counters")
            
    except Exception as e:
        print(f"Error rebuilding session counters: {e}")
        import traceback
        traceback.print_exc()

def reset_session_timer():
    """Reset session timer to allow immediate trading"""
    session_state = get_session_state()
    session_state["session_start_time"] = None
    save_session_state(session_state)
    print("✅ Session timer reset - trading allowed immediately")

# Add this function before line 3520 (before if __name__ == "__main__":)

def increment_session_counter_on_execution(symbol, decision):
    """
    Increment session counter when trade is actually executed (not just decided by AI).
    This should be called only when trade is confirmed and executed.
    
    Args:
        symbol: Trading symbol
        decision: Trading decision (BUY, SELL, etc.)
    
    Returns:
        bool: Success status
    """
    try:
        # Only increment for actual trading decisions
        if decision not in ["BUY", "SELL"]:
            return True  # No increment needed for non-trading decisions
            
        increment_success = increment_session_trade_counter(symbol)
        if increment_success:
            current_session = get_current_session()
            if current_session:
                session_names = {"TOKYO": "Tokyo Session", "LONDON": "London Session", "NY": "New York Session"}
                session_name = session_names.get(current_session, current_session)
                print(f"🎯 SESSION TRADE EXECUTED: {decision} for {symbol} in {session_name}")
                return True
        return False
    except Exception as e:
        print(f"Error incrementing session counter for {symbol}: {e}")
        return False

if __name__ == "__main__":
    # Add signal handler here (only when running as main script)
    signal.signal(signal.SIGTERM, handle_sigterm)
        
    rebuild_session_counters_from_history()
    main()
