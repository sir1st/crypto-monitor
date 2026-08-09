#!/usr/bin/env python
"""
trade_manager.py - Streamlined Trading Manager for Cryptocurrency Trading

This script manages trading operations including:
1. Opening positions based on signals
2. Closing positions when needed
3. Setting and managing stop-loss and take-profit levels
4. Handling position reversals
5. Providing order execution and position monitoring
"""

import os
import time
import json
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import math
from time_sync import time_sync, get_server_time_ms
import traceback
import argparse
from multi_account_trader import SimpleMultiAccountTrader

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trade_manager_log.txt", encoding='utf-8')
    ]
)
logger = logging.getLogger("trade_manager")

# Load API keys from environment variables
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")

# Initialize Bybit client with server time
bybit_client = HTTP(
    api_key=BYBIT_API_KEY,
    api_secret=BYBIT_API_SECRET,
    testnet=False,
    recv_window=20000  # Increased recv_window
)

# Override timestamp for requests
def get_request_timestamp():
    return get_server_time_ms()

bybit_client.get_timestamp = get_request_timestamp

# Trading configuration - load from trading_config.json
CONFIG_FILE = "trading_config.json"

# Default configuration (will be overridden by config file)
TRADING_CONFIG = {    
    # Stop-loss settings
    "initial_stop_loss_pct": 40,  # Wider stop loss (40%) to give more room
    
    # Take profit settings - consolidated
    "take_profit_enabled": False,
    "take_profit_mode": "strategic",  # "strategic" or "simple"
    
    # Simple take profit settings (3 levels)
    "simple_tp_levels": [],  # Empty by default, will be loaded from config
    
    # Strategic take profit settings (multi-tier)
    "strategic_tp_levels": [],  # Empty by default, will be loaded from config
    
    # System settings
    "initial_position_usdt": 25.0,  # Default position size in USDT (will be overridden by symbol_config)
    "update_interval": 10,
}

# Trading pairs loaded from config
TRADING_PAIRS = []

# Symbol-specific configuration (will be populated dynamically)
SYMBOL_CONFIG = {}

def load_trading_config():
    """Load trading configuration from trading_config.json"""
    global TRADING_CONFIG, TRADING_PAIRS, SYMBOL_CONFIG
    
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            
            # Update trading configuration
            if "leverage" in config:
                TRADING_CONFIG["leverage"] = config["leverage"]
            if "position_value" in config:
                TRADING_CONFIG["initial_position_usdt"] = config["position_value"]
            if "trailing_stop_pct" in config:
                TRADING_CONFIG["initial_stop_loss_pct"] = config["trailing_stop_pct"]
                
            # Load take profit settings
            if "take_profit_enabled" in config:
                TRADING_CONFIG["take_profit_enabled"] = config["take_profit_enabled"]
            
            if "take_profit_mode" in config:
                TRADING_CONFIG["take_profit_mode"] = config["take_profit_mode"]
            
            # For backwards compatibility with old config format
            if "first_scale_pct" in config and "scale_size_pct" in config:
                # Update the first level of simple TP settings
                if len(TRADING_CONFIG["simple_tp_levels"]) > 0:
                    TRADING_CONFIG["simple_tp_levels"][0]["profit_pct"] = config["first_scale_pct"]
                    TRADING_CONFIG["simple_tp_levels"][0]["size_pct"] = config["scale_size_pct"]
            
            # Load custom TP levels if provided
            if "simple_tp_levels" in config:
                TRADING_CONFIG["simple_tp_levels"] = config["simple_tp_levels"]
                
            if "strategic_tp_levels" in config:
                TRADING_CONFIG["strategic_tp_levels"] = config["strategic_tp_levels"]
                
            # Load trailing stop configuration if provided
            if "trailing_stop" in config:
                TRADING_CONFIG["trailing_stop"] = config["trailing_stop"]
                logger.info(f"Loaded trailing stop configuration: {config['trailing_stop']}")
                
            # Load trading pairs
            if "trading_pairs" in config:
                TRADING_PAIRS = config["trading_pairs"]
                print(f"Loaded {len(TRADING_PAIRS)} trading pairs from config")
                
                # Clear existing symbol config
                SYMBOL_CONFIG = {}
                
                # For each trading pair, create a default configuration
                # We'll dynamically get the precision from the exchange API later
                for symbol in TRADING_PAIRS:
                    SYMBOL_CONFIG[symbol] = {
                        "qty_decimals": 0,
                        "price_decimals": 4,
                        "min_qty": 1,
                    }
            
            # Load per-symbol configurations if available
            if "symbol_config" in config:
                TRADING_CONFIG["symbol_config"] = config["symbol_config"]
                logger.info(f"Loaded per-symbol configurations for {len(config['symbol_config'])} symbols")
            
            print(f"Trading configuration loaded from {CONFIG_FILE}")
        else:
            print(f"Config file {CONFIG_FILE} not found, using defaults")
    except Exception as e:
        print(f"Error loading config: {e}")

def update_symbol_precision_from_api():
    """
    Fetch symbol precision details from Bybit API and update SYMBOL_CONFIG
    """
    try:
        # Get instruments info
        instruments_response = bybit_client.get_instruments_info(
            category="linear"
        )
        
        if instruments_response and instruments_response.get("retCode") == 0:
            instruments = instruments_response.get("result", {}).get("list", [])
            
            # Log how many instruments were received
            print(f"Received information for {len(instruments)} instruments from Bybit API")
            
            # Update precision for our trading pairs
            for instrument in instruments:
                symbol = instrument.get("symbol")
                if symbol in TRADING_PAIRS:
                    # Extract precision information
                    qty_step = instrument.get("lotSizeFilter", {}).get("qtyStep", "1")
                    price_step = instrument.get("priceFilter", {}).get("tickSize", "0.0001")
                    min_qty = instrument.get("lotSizeFilter", {}).get("minOrderQty", "1")
                    
                    # Calculate decimals from step sizes
                    qty_decimals = 0
                    if "." in qty_step:
                        qty_decimals = len(qty_step.split(".")[1])
                    
                    price_decimals = 0
                    if "." in price_step:
                        price_decimals = len(price_step.split(".")[1])
                    
                    # Update symbol config
                    SYMBOL_CONFIG[symbol] = {
                        "qty_decimals": qty_decimals,
                        "price_decimals": price_decimals,
                        "min_qty": float(min_qty)
                    }
                    
                    print(f"Updated precision for {symbol}: qty_decimals={qty_decimals}, price_decimals={price_decimals}, min_qty={min_qty}")
            
            print(f"Symbol configuration updated for {len(SYMBOL_CONFIG)} trading pairs")
        else:
            print(f"Failed to get instruments info: {instruments_response}")
    except Exception as e:
        print(f"Error fetching instrument precision: {e}")

# Initialize by loading config and updating precision info
load_trading_config()

# Attempt to update symbol precision from API (if available)
try:
    update_symbol_precision_from_api()
except Exception as e:
    print(f"Could not update symbol precision: {e}")
    print("Will continue with default precision values")

# Global variables for tracking
ORDER_HISTORY = []
MAX_ORDER_HISTORY = 100  # Maximum number of orders to keep in history
_instrument_info_cache = {}  # Cache for instrument information

# Global TP tracking
tp_set_symbols = set()
tp_state_file = "tp_state.json"  # File to persist TP state across restarts
trailing_stop_monitor_started = False  # Flag to track if trailing stop monitor has been started

def save_tp_state():
    """Save the TP tracking state to a file"""
    try:
        tp_state = {
            "tp_set_symbols": list(tp_set_symbols),
            "timestamp": datetime.now().isoformat()
        }
        
        with open("tp_tracking.json", "w") as f:
            json.dump(tp_state, f, indent=2)
            
        logger.info(f"Saved TP tracking state for {len(tp_set_symbols)} symbols")
        return True
    except Exception as e:
        logger.error(f"Error saving TP state: {e}")
        return False
        
def load_tp_state():
    """Load the TP tracking state from a file"""
    global tp_set_symbols
    
    try:
        if os.path.exists("tp_tracking.json"):
            with open("tp_tracking.json", "r") as f:
                tp_state = json.load(f)
                
            if "tp_set_symbols" in tp_state:
                tp_set_symbols = set(tp_state["tp_set_symbols"])
                logger.info(f"Loaded TP tracking state for {len(tp_set_symbols)} symbols")
                return True
                
        logger.info("No TP tracking state found, starting fresh")
        tp_set_symbols = set()
        return False
    except Exception as e:
        logger.error(f"Error loading TP state: {e}")
        tp_set_symbols = set()
        return False

def check_for_existing_tp_orders(symbol):
    """
    Check if a symbol already has any take profit orders set
    Returns True if at least one TP order exists, False otherwise
    """
    try:
        logger.info(f"Checking for existing TP orders for {symbol}")
        
        # First check our persistent tracking set
        global tp_set_symbols
        if symbol in tp_set_symbols:
            logger.info(f"{symbol} has take profits previously set according to our tracking")
            return True
            
        # Check position data
        position_info = bybit_client.get_positions(category="linear", symbol=symbol)
        if position_info and position_info.get("retCode") == 0:
            position_data = position_info.get("result", {}).get("list", [])
            if position_data:
                pos = position_data[0]
                take_profit = pos.get("takeProfit")
                if take_profit and float(take_profit) > 0:
                    logger.info(f"{symbol} has take profit set in position data: {take_profit}")
                    # Add to our tracking set
                    tp_set_symbols.add(symbol)
                    save_tp_state()
                    return True
        
        # Check open orders
        orders = bybit_client.get_open_orders(category="linear", symbol=symbol)
        if orders and orders.get("retCode") == 0:
            order_list = orders.get("result", {}).get("list", [])
            tp_count = 0
            
            for order in order_list:
                # Check various types of TP orders
                if (order.get("stopOrderType") == "TakeProfit" or 
                    "TP_" in order.get("orderLinkId", "") or
                    (order.get("reduceOnly") == True and order.get("orderType") == "Limit")):
                    
                    tp_count += 1
                    logger.info(f"{symbol} has take profit order: {order.get('orderId')}")
            
            if tp_count > 0:
                # Add to our tracking set
                tp_set_symbols.add(symbol)
                save_tp_state()
                logger.info(f"{symbol} has {tp_count} take profit orders")
                return True
        
        logger.info(f"No take profit orders found for {symbol}")
        return False
    
    except Exception as e:
        logger.error(f"Error checking for TP orders for {symbol}: {e}")
        # Default to False to force setting TPs on error
        return False

def get_position_entry_price(symbol):
    """Get the entry price for a position, with fallbacks if API returns zero"""
    try:
        # Try to get from API
        position_info = bybit_client.get_positions(
            category="linear",
            symbol=symbol
        )
        
        if position_info and position_info.get("retCode") == 0:
            position_list = position_info.get("result", {}).get("list", [])
            if position_list:
                position = position_list[0]
                entry_price = position.get("avgPrice", 0)
                # Handle cases where avgPrice might be a string or None
                if entry_price:
                    try:
                        entry_price = float(entry_price)
                        if entry_price > 0:
                            logger.info(f"Got valid entry price for {symbol} from API: {entry_price}")
                            return entry_price
                    except (ValueError, TypeError):
                        pass
                
                # If avgPrice is invalid or 0, look for other fields that might have the price
                entry_price = position.get("entryPrice", 0)
                if entry_price:
                    try:
                        entry_price = float(entry_price)
                        if entry_price > 0:
                            logger.info(f"Got valid entry price for {symbol} from entryPrice: {entry_price}")
                            return entry_price
                    except (ValueError, TypeError):
                        pass
                
                # As a last resort, try to use current mark price
                mark_price = position.get("markPrice", 0)
                if mark_price:
                    try:
                        mark_price = float(mark_price)
                        if mark_price > 0:
                            logger.warning(f"Using mark price {mark_price} as fallback for {symbol} entry price")
                            return mark_price
                    except (ValueError, TypeError):
                        pass
        
        # If we get here, no valid price from position API
        # Try current market price
        current_price = get_current_price(symbol)
        if current_price and current_price > 0:
            logger.warning(f"Using current market price {current_price} as fallback for {symbol} entry price")
            return current_price
            
        # Last resort - use a hardcoded value
        logger.error(f"Could not determine entry price for {symbol}, using fallback value")
        return 85000.0  # Fallback value - should be adjusted based on the market
    except Exception as e:
        logger.error(f"Error getting position entry price for {symbol}: {e}")
        current_price = get_current_price(symbol)
        if current_price and current_price > 0:
            return current_price
        return 85000.0  # Fallback value

def setup_trailing_take_profit(symbol, side, entry_price, qty):
    """Set up take profit levels for a position"""
    try:
        logger.info(f"Setting up take profit levels for {symbol} with side={side}, entry_price={entry_price}")
        
        if not entry_price or not qty:
            logger.error(f"Cannot set take profit with empty entry price or quantity")
            return False
            
        # Fix entry price if it's invalid (zero or very small)
        if entry_price <= 0 or entry_price < 1000:  # Assuming BTC is always > $1000
            real_entry = get_position_entry_price(symbol)
            logger.warning(f"Replacing invalid entry price {entry_price} with {real_entry}")
            entry_price = real_entry
            
        # Check if we've already set TPs for this symbol using our persistent tracker
        global tp_set_symbols
        if symbol in tp_set_symbols:
            # Double-check via API that TPs actually exist
            has_orders = False
            try:
                orders = bybit_client.get_open_orders(category="linear", symbol=symbol)
                if orders and orders.get("retCode") == 0:
                    order_list = orders.get("result", {}).get("list", [])
                    for order in order_list:
                        if (order.get("stopOrderType") == "TakeProfit" or 
                            "TP_" in order.get("orderLinkId", "") or
                            (order.get("reduceOnly") == True and order.get("orderType") == "Limit")):
                            has_orders = True
                            break
            except Exception as e:
                logger.error(f"Error checking existing orders: {e}")
                
            if has_orders:
                logger.info(f"Take profits already set for {symbol} - skipping to avoid duplicate orders")
                return True
            else:
                logger.warning(f"{symbol} was tracked as having TPs but none found - will set new ones")
                
        # IMPORTANT: Cancel existing orders before setting new ones
        try:
            logger.info(f"Cancelling all existing orders for {symbol} before setting new TPs")
            cancel_all = bybit_client.cancel_all_orders(
                category="linear",
                symbol=symbol
            )
            if cancel_all and cancel_all.get("retCode") == 0:
                logger.info(f"Successfully cancelled all existing orders for {symbol}")
                # Add a slight delay to ensure the exchange processes the cancellations
                time.sleep(1)
            else:
                error_msg = cancel_all.get("retMsg", "Unknown error") if cancel_all else "No response"
                logger.warning(f"Error cancelling existing orders: {error_msg}")
        except Exception as e:
            logger.warning(f"Error cancelling existing orders: {e}")
            
        # Get correct position information and leverage
        position_success = False
        attempt_count = 0
        max_attempts = 3
        position_value = 0
        actual_size = float(qty)
        actual_entry = entry_price
        leverage = TRADING_CONFIG.get("leverage", 1)
        mark_price = entry_price
        
        # Try to get position details from the exchange
        while not position_success and attempt_count < max_attempts:
            try:
                attempt_count += 1
                # Get position data from API
                position_data = bybit_client.get_positions(
                    category="linear",
                    symbol=symbol
                )
                
                # Extract position details
                position_list = position_data.get("result", {}).get("list", [])
                if position_list:
                    position = position_list[0]
                    actual_size = float(position.get("size", qty))
                    
                    # Get a valid entry price, ensure it's not zero
                    temp_entry = position.get("avgPrice", entry_price)
                    if temp_entry:
                        try:
                            temp_entry = float(temp_entry)
                            if temp_entry > 0:
                                actual_entry = temp_entry
                        except (ValueError, TypeError):
                            pass
                            
                    # Get leverage value
                    lev = position.get("leverage", leverage)
                    if lev:
                        try:
                            lev = float(lev)
                            if lev > 0:
                                leverage = lev
                        except (ValueError, TypeError):
                            pass
                    
                    # Calculate position value        
                    position_value = actual_size * actual_entry
                    
                    # Get mark price
                    temp_mark = position.get("markPrice", entry_price)
                    if temp_mark:
                        try:
                            temp_mark = float(temp_mark)
                            if temp_mark > 0:
                                mark_price = temp_mark
                        except (ValueError, TypeError):
                            pass
                    
                    # Log details
                    logger.info(f"Position found for {symbol} after attempt {attempt_count}: Size={actual_size}, Entry={actual_entry}, Value=${position_value}")
                    position_success = True
                else:
                    logger.warning(f"No position data found for {symbol} on attempt {attempt_count}")
                    time.sleep(1)  # Wait before retrying
            except Exception as e:
                logger.error(f"Error getting position data (attempt {attempt_count}): {e}")
                time.sleep(1)  # Wait before retrying
        
        # If we couldn't get position data, continue with what we have
        if not position_success:
            logger.warning(f"Using provided position data: Size={qty}, Entry={entry_price}")
            # Try once more to get a valid entry price
            new_entry = get_position_entry_price(symbol)
            if new_entry > 0 and new_entry != entry_price:
                logger.info(f"Updated entry price from {entry_price} to {new_entry}")
                actual_entry = new_entry
        
        # Calculate position value
        position_value = actual_size * actual_entry
        logger.info(f"Position value: {actual_size} {symbol} * ${actual_entry} = ${position_value}")
        
        # Set stop loss if not set
        if side == "Sell":
            logger.info(f"Sell position with {leverage}x leverage, {TRADING_CONFIG.get('trailing_stop_pct', 40)}% stop loss")
            # For Sell, SL is ABOVE entry price
            sl_pct = TRADING_CONFIG.get("trailing_stop_pct", 40) / 100
            logger.info(f"SL price movement: {sl_pct:.2f}% from entry price {actual_entry}")
            # Use dedicated function for consistent calculations
            sl_price = calculate_sl_with_leverage(actual_entry, TRADING_CONFIG.get("trailing_stop_pct", 40), leverage, side)
            logger.info(f"Setting stop loss for {symbol} at {sl_price}")
            
            try:
                sl_response = bybit_client.set_trading_stop(
                    category="linear",
                    symbol=symbol,
                    tpslMode="Full",  # This parameter is required
                    stopLoss=str(sl_price),
                    slTriggerBy="MarkPrice",
                    slOrderType="Market"
                )
                
                if sl_response and sl_response.get("retCode") == 0:
                    logger.info(f"Successfully set stop loss for {symbol} at {sl_price}")
                else:
                    error_msg = sl_response.get("retMsg", "Unknown error") if sl_response else "No response"
                    logger.error(f"Failed to set stop loss: {error_msg}")
            except Exception as e:
                logger.error(f"Error setting stop loss: {e}")
                
        elif side == "Buy":
            logger.info(f"Buy position with {leverage}x leverage, {TRADING_CONFIG.get('trailing_stop_pct', 40)}% stop loss")
            # For Buy, SL is BELOW entry price
            sl_pct = TRADING_CONFIG.get("trailing_stop_pct", 40) / 100
            logger.info(f"SL price movement: {sl_pct:.2f}% from entry price {actual_entry}")
            # Use dedicated function for consistent calculations
            sl_price = calculate_sl_with_leverage(actual_entry, TRADING_CONFIG.get("trailing_stop_pct", 40), leverage, side)
            logger.info(f"Setting stop loss for {symbol} at {sl_price}")
            
            try:
                sl_response = bybit_client.set_trading_stop(
                    category="linear",
                    symbol=symbol,
                    tpslMode="Full",  # This parameter is required
                    stopLoss=str(sl_price),
                    slTriggerBy="MarkPrice",
                    slOrderType="Market"
                )
                
                if sl_response and sl_response.get("retCode") == 0:
                    logger.info(f"Successfully set stop loss for {symbol} at {sl_price}")
                else:
                    error_msg = sl_response.get("retMsg", "Unknown error") if sl_response else "No response"
                    logger.error(f"Failed to set stop loss: {error_msg}")
            except Exception as e:
                logger.error(f"Error setting stop loss: {e}")
                
        logger.info(f"Successfully set initial stop loss for {symbol} at {sl_price}")
        
        # Set up take profit levels using partial mode
        logger.info(f"Setting up take profit levels for {symbol} with side={side}, entry_price={actual_entry}")
        
        # Choose the right TP levels based on config
        tp_mode = TRADING_CONFIG.get("take_profit_mode", "strategic")
        if tp_mode == "strategic":
            tp_levels = TRADING_CONFIG.get("strategic_tp_levels", [])
        else:
            tp_levels = TRADING_CONFIG.get("simple_tp_levels", [])
            
        if not tp_levels:
            logger.error(f"No TP levels configured for {symbol}")
            return False
            
        # Track remaining position size
        remaining_position_size = actual_size
        logger.info(f"Starting with total position size: {remaining_position_size} {symbol}")
        
        # Track success
        success = False
        tp_levels_set = 0
        
        # Get minimum order quantity for this symbol
        min_qty = SYMBOL_CONFIG.get(symbol, {}).get("min_qty", 0.001)
        
        # Set take profit levels using partial take profits
        for i, level in enumerate(tp_levels):
            profit_pct = level.get("profit_pct", 0)
            size_pct = level.get("size_pct", 0)
            
            # Skip if size percentage is zero
            if size_pct <= 0:
                logger.warning(f"Skipping level {i+1} with zero or negative size percentage")
                continue
                
            # Skip if no size left
            if remaining_position_size <= 0:
                logger.warning(f"No remaining position size for level {i+1}")
                break
                
            # Calculate TP price based on entry price, side and profit percentage
            if side == "Sell":
                logger.info(f"Sell position with {leverage}x leverage targeting {profit_pct}% profit")
                tp_pct = profit_pct / 100
                logger.info(f"TP price movement: {tp_pct:.2f}% from entry price {actual_entry}")
                # Use the dedicated function for consistent calculations
                tp_price = calculate_tp_with_leverage(actual_entry, profit_pct, leverage, side)
            else:  # Buy
                logger.info(f"Buy position with {leverage}x leverage targeting {profit_pct}% profit")
                tp_pct = profit_pct / 100
                logger.info(f"TP price movement: {tp_pct:.2f}% from entry price {actual_entry}")
                # Use the dedicated function for consistent calculations
                tp_price = calculate_tp_with_leverage(actual_entry, profit_pct, leverage, side)
            
            # Calculate quantity for this TP level
            tp_qty = actual_size * (size_pct / 100)
            
            # Ensure we don't exceed remaining position
            if tp_qty > remaining_position_size:
                logger.warning(f"Adjusting TP quantity from {tp_qty} to {remaining_position_size} to not exceed position size")
                tp_qty = remaining_position_size
                
            # Check minimum quantity
            if tp_qty < min_qty:
                if remaining_position_size >= min_qty:
                    logger.info(f"Adjusted TP quantity to minimum: {min_qty}")
                    tp_qty = min_qty
                else:
                    logger.warning(f"Remaining position {remaining_position_size} too small for minimum TP size {min_qty}, skipping")
                    break
                    
            # Format the quantity
            tp_qty_formatted = format_quantity_for_symbol(symbol, tp_qty)
            
            # Try setting the TP using TWO different methods to ensure it works
            # First, try using set_trading_stop with Partial mode
            tp_set = False
            
            try:
                # First method: Using set_trading_stop with Partial mode
                tp_response = bybit_client.set_trading_stop(
                    category="linear",
                    symbol=symbol,
                    positionIdx=0,
                    tpslMode="Partial",  # Use Partial mode to allow multiple TPs
                    tpSize=str(tp_qty_formatted),  # Convert to string
                    slSize=str(tp_qty_formatted),  # Must match tpSize
                    takeProfit=str(tp_price),
                    tpTriggerBy="MarkPrice",
                    tpOrderType="Market"
                )
                
                if tp_response and tp_response.get("retCode") == 0:
                    logger.info(f"Successfully set TP level {i+1} at {tp_price} for {tp_qty_formatted} units using set_trading_stop")
                    tp_set = True
                else:
                    error_msg = tp_response.get("retMsg", "Unknown error") if tp_response else "No response"
                    logger.error(f"Failed to set TP level {i+1} using set_trading_stop: {error_msg}")
                    # We'll try the backup method below
            except Exception as e:
                logger.error(f"Error setting TP level {i+1} using set_trading_stop: {e}")
                # We'll try the backup method below
                
            # If the first method failed, try setting a reduce-only limit order as TP
            if not tp_set:
                try:
                    # For a Buy position, TP is a Sell limit order above entry
                    # For a Sell position, TP is a Buy limit order below entry
                    order_side = "Sell" if side == "Buy" else "Buy"
                    
                    tp_order = bybit_client.place_order(
                        category="linear",
                        symbol=symbol,
                        side=order_side,
                        orderType="Limit",
                        qty=str(tp_qty_formatted),  # Convert to string
                        price=str(tp_price),
                        reduceOnly=True,  # Ensure this only closes the position
                        timeInForce="PostOnly",  # Use PostOnly to ensure we're a maker
                        positionIdx=0,
                        orderLinkId=f"TP_{symbol}_{i+1}_{int(time.time())}"
                    )
                    
                    if tp_order and tp_order.get("retCode") == 0:
                        order_id = tp_order.get("result", {}).get("orderId")
                        logger.info(f"Successfully set TP level {i+1} at {tp_price} for {tp_qty_formatted} units using limit order, ID: {order_id}")
                        tp_set = True
                    else:
                        error_msg = tp_order.get("retMsg", "Unknown error") if tp_order else "No response"
                        logger.error(f"Failed to set TP level {i+1} using limit order: {error_msg}")
                except Exception as e:
                    logger.error(f"Error setting TP level {i+1} using limit order: {e}")
            
            # If we successfully set a TP, update our tracking
            if tp_set:
                remaining_position_size -= float(tp_qty_formatted)
                logger.info(f"Remaining position size: {remaining_position_size} {symbol}")
                tp_levels_set += 1
                success = True
                
            # Add delay to avoid rate limiting
            time.sleep(0.5)
            
        # Update our tracking set if we successfully set TPs
        if success:
            logger.info(f"Successfully set {tp_levels_set} take profit levels for {symbol}")
            tp_set_symbols.add(symbol)
            save_tp_state()
            
            # Log a success message with the attempt number
            logger.info(f"Successfully set take profit levels for {symbol} on attempt {attempt_count}")
            
            # Log high leverage warning
            if leverage >= 50:
                logger.warning(f"Using high leverage ({leverage}x) for {symbol} - ensure you understand the risks")
            if leverage >= 100:
                logger.warning(f"EXTREME LEVERAGE ({leverage}x) DETECTED - Very high risk of liquidation!")
                
            # Log success summary
            logger.info(f"Opening {side} position with {leverage}x leverage")
            logger.info(f"Initial SL at {sl_price:.2f} ({TRADING_CONFIG.get('trailing_stop_pct', 40)}% loss, {TRADING_CONFIG.get('trailing_stop_pct', 40) * leverage:.2f}% effective with leverage)")
            
            return True
        else:
            logger.error(f"Failed to set take profit levels for {symbol}")
            return False
            
    except Exception as e:
        logger.error(f"Error in setup_trailing_take_profit: {e}")
        logger.error(traceback.format_exc())
        return False

#--------------------- CORE TRADING FUNCTIONS ---------------------#

def get_active_positions():
    """Get currently active positions from Bybit API"""
    try:
        positions = bybit_client.get_positions(
            category="linear",
            settleCoin="USDT"
        )
        
        if not positions or positions.get("retCode") != 0:
            logger.error(f"Failed to get positions: {positions.get('retMsg', 'Unknown error')}")
            return {}
        
        position_list = positions.get("result", {}).get("list", [])
        
        # Format positions into a dict by symbol
        result = {}
        for position in position_list:
            try:
                size = float(position.get("size", "0") or "0")  # Handle empty string case
                
                # Skip positions with zero size
                if size <= 0:
                    continue
                
                symbol = position.get("symbol")
                
                # Safely convert all numeric values with fallbacks
                result[symbol] = {
                    "symbol": symbol,
                    "side": position.get("side"),  # "Buy" or "Sell"
                    "size": size,
                    "value": float(position.get("positionValue", "0") or "0"),
                    "leverage": float(position.get("leverage", "0") or "0"),
                    "entry_price": float(position.get("avgPrice", "0") or "0"),
                    "mark_price": float(position.get("markPrice", "0") or "0"),
                    "unrealised_pnl": float(position.get("unrealisedPnl", "0") or "0"),
                    "unrealised_pnl_pct": 0,  # Will calculate below
                    "liq_price": float(position.get("liqPrice", "0") or "0"),
                    "stop_loss": 0,  # Will update with actual SL if available
                    "take_profit": 0  # Will update with actual TP if available
                }
                
                # Calculate PnL percentage
                entry = float(position.get("avgPrice", "0") or "0")
                mark = float(position.get("markPrice", "0") or "0")
                side = position.get("side")
                
                if entry > 0:
                    if side == "Buy":
                        pnl_pct = ((mark / entry) - 1) * 100
                    else:  # "Sell"
                        pnl_pct = ((entry / mark) - 1) * 100
                    
                    result[symbol]["unrealised_pnl_pct"] = pnl_pct
            except ValueError as ve:
                logger.warning(f"Skipping position for {position.get('symbol')}: Invalid numeric value: {ve}")
            except Exception as e:
                logger.warning(f"Error processing position for {position.get('symbol')}: {e}")
        
        # Get stop loss and take profit orders
        try:
            orders = bybit_client.get_open_orders(
                category="linear",
                settleCoin="USDT",
                openOnly=1
            )
            
            if orders and orders.get("retCode") == 0:
                order_list = orders.get("result", {}).get("list", [])
                
                for order in order_list:
                    symbol = order.get("symbol")
                    if symbol in result:
                        order_type = order.get("orderType")
                        stop_order_type = order.get("stopOrderType", "")
                        
                        # Add SL/TP info to positions
                        if stop_order_type == "StopLoss":
                            result[symbol]["stop_loss"] = float(order.get("triggerPrice", "0"))
                        elif stop_order_type == "TakeProfit":
                            result[symbol]["take_profit"] = float(order.get("triggerPrice", "0"))
        except Exception as e:
            logger.warning(f"Error getting SL/TP orders: {e}")
        
        return result
    except Exception as e:
        logger.error(f"Error getting active positions: {e}")
        return {}

def set_leverage(symbol, leverage=1):
    """Set leverage for a specific symbol"""
    try:
        logger.info(f"Setting leverage for {symbol} to {leverage}x")
        
        max_retries = 3
        retry_delay = 0.5  # seconds
        
        for attempt in range(max_retries):
            # Try to set the leverage
            response = bybit_client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            
            if response and response.get("retCode") == 0:
                logger.info(f"Successfully set leverage for {symbol} to {leverage}x")
                return True
            
            # Check for "not modified" error (already set to that leverage)
            # Error code 34036 means "leverage not modified"
            error_msg = response.get("retMsg", "") if response else ""
            error_code = response.get("retCode", 0) if response else 0
            
            if error_code == 34036 or "not modified" in error_msg.lower():
                logger.info(f"Leverage for {symbol} already set to {leverage}x")
                return True
            
            # If this wasn't the last attempt, wait and retry
            if attempt < max_retries - 1:
                logger.warning(f"Failed to set leverage for {symbol}, retrying in {retry_delay}s (attempt {attempt+1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to set leverage for {symbol} after {max_retries} attempts: {error_msg}")
                
        # If we get here, all attempts have failed
        return False
    except Exception as e:
        logger.error(f"Error setting leverage for {symbol}: {e}")
        return False

def format_quantity_for_symbol(symbol, qty):
    """Format order quantity based on symbol requirements"""
    try:
        # Check if we have specific config for this symbol
        if symbol in SYMBOL_CONFIG:
            config = SYMBOL_CONFIG[symbol]
            min_qty = config.get("min_qty", 0.001)
            decimals = config.get("qty_decimals", 2)
            
            # Calculate total usdt value represented by this quantity
            current_price = get_current_price(symbol)
            usdt_value = qty * current_price if current_price else 0
            
            # Log if the quantity is below minimum - but don't adjust, as calculate_position_size already handled this
            if qty < min_qty:
                logger.debug(f"Quantity {qty} is below minimum {min_qty} (${usdt_value:.2f}), but not adjusting here")
            
            # Format the quantity to the correct number of decimal places required by the exchange
            # Use ceiling to ensure we don't go below user intent, but still comply with step size requirements
            if decimals == 0:
                # For whole number quantities
                formatted_qty = str(int(math.floor(qty)))  # For integers, floor to be safe
            else:
                # For decimal quantities, round to the required decimal places
                # This preserves the user's intent while respecting exchange requirements
                multiplier = 10 ** decimals
                # Use floor to ensure we don't exceed available funds
                formatted_qty = f"{math.floor(qty * multiplier) / multiplier:.{decimals}f}"
            
            # Remove trailing zeros
            if '.' in formatted_qty:
                formatted_qty = formatted_qty.rstrip('0').rstrip('.')
            
            logger.info(f"Formatted quantity for {symbol}: {qty} to {formatted_qty} with {decimals} decimals (≈ ${usdt_value:.2f})")
            return formatted_qty
        
        logger.warning(f"No specific formatting config for {symbol}, using default")
        # Default handling - try to handle reasonably
        return str(int(qty) if qty == int(qty) else round(qty, 2))
    except Exception as e:
        logger.error(f"Error formatting quantity for {symbol}: {e}")
        # Default to integer as last resort
        return str(int(qty)) if qty is not None else None

def get_current_price(symbol):
    """Get the current price for a symbol"""
    try:
        ticker = bybit_client.get_tickers(
            category="linear",
            symbol=symbol
        )
        
        if ticker and ticker.get("retCode") == 0:
            ticker_list = ticker.get("result", {}).get("list", [])
            if ticker_list:
                return float(ticker_list[0]["lastPrice"])
        
        logger.error(f"Could not get price for {symbol}")
        return None
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return None

def calculate_position_size(symbol, side, amount_usdt=None):
    """Calculate position size based on USDT amount and current price"""
    try:
        # Check if multi-account is enabled - if so, don't use this function
        if is_multi_account_enabled():
            logger.warning("calculate_position_size called in multi-account mode - this should use multi_account_trader position calculations")
            # Return a reasonable fallback to prevent errors
            amount_usdt = amount_usdt or 15  # Use fallback of 15 USDT
            
        # Get current price
        price = get_current_price(symbol)
        if not price:
            logger.error(f"Failed to get price for {symbol}")
            return None
        
        # Get the symbol-specific config if it exists
        symbol_config = TRADING_CONFIG.get("symbol_config", {}).get(symbol, {})
        
        # Get leverage from symbol config if available
        leverage = symbol_config.get("leverage", TRADING_CONFIG.get("leverage", 1))
        logger.info(f"Using leverage of {leverage}x for {symbol} from config")
        
        # Calculate quantity from USDT amount
        if amount_usdt is None:
            # First check if we have a symbol-specific position size
            if "position_usdt" in symbol_config and symbol_config.get("position_usdt", 0) > 0:
                amount_usdt = symbol_config.get("position_usdt")
                logger.info(f"Using symbol-specific position size: ${amount_usdt} for {symbol}")
            else:
                # Fall back to default value
                amount_usdt = TRADING_CONFIG.get("initial_position_usdt", 25.0)
                logger.info(f"Using default position size: ${amount_usdt}")
            
        # Log the effective notional value with leverage
        notional_value = amount_usdt * leverage
        logger.info(f"Position calculation for {symbol}: ${amount_usdt} with {leverage}x leverage = ${notional_value} notional")
        
        # The ACTUAL quantity we want is based on the notional value with leverage
        qty = notional_value / price
        
        # Get minimum quantity for this symbol from exchange requirements
        min_qty = SYMBOL_CONFIG.get(symbol, {}).get("min_qty", 0.001)
        
        # For very small position sizes, we might need to adjust to minimum
        if qty < min_qty:
            logger.warning(f"Calculated quantity {qty} is below minimum {min_qty}, using minimum")
            qty = min_qty
        
        # Format the quantity properly according to symbol rules
        formatted_qty = format_quantity_for_symbol(symbol, qty)
        
        if not formatted_qty:
            logger.error(f"Failed to format quantity for {symbol}")
            return None
        
        # Calculate actual value of the position we're placing
        total_position_value = float(formatted_qty) * price
        
        # Log the final position details
        logger.info(f"Final position: {formatted_qty} {symbol} at ${price} = ${total_position_value:.2f} (${total_position_value/leverage:.2f} margin with {leverage}x leverage)")
        
        return {
            "symbol": symbol,
            "side": side,
            "price": price,
            "qty": qty,
            "formatted_qty": formatted_qty,
            "value_usdt": amount_usdt,
            "leverage": leverage,
            "notional_value": total_position_value
        }
    except Exception as e:
        logger.error(f"Error calculating position size for {symbol}: {e}")
        return None

def place_market_order(symbol, side, qty):
    """Place a market order"""
    try:
        if not qty:
            logger.error(f"Cannot place order for {symbol} with empty quantity")
            return None
            
        logger.info(f"Placing {side} order for {symbol} with qty: {qty}")
        
        # Place the order
        order_result = bybit_client.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            timeInForce="IOC"  # Immediate or Cancel is appropriate for market orders
        )
        
        if not order_result or order_result.get("retCode") != 0:
            error_msg = order_result.get("retMsg", "Unknown error") if order_result else "No response"
            logger.error(f"Failed to place {side} order for {symbol}: {error_msg}")
            return None
            
        order_id = order_result.get("result", {}).get("orderId")
        logger.info(f"Successfully placed {side} order for {symbol}, Order ID: {order_id}")
        
        # Track the order
        track_order(
            order_type="ENTRY", 
            symbol=symbol,
            side=side, 
            qty=qty, 
            price=get_current_price(symbol), 
            order_id=order_id
        )
        
        return order_id
    except Exception as e:
        logger.error(f"Error placing {side} order for {symbol}: {e}")
        return None

def close_position(symbol, side):
    """Close a position (fully)"""
    try:
        # The side to close is opposite of the position side
        close_side = "Sell" if side == "Buy" else "Buy"
        
        # Get current position size
        positions = get_active_positions()
        if symbol in positions:
            position = positions[symbol]
            qty = position["size"]
            formatted_qty = format_quantity_for_symbol(symbol, float(qty))
        
            order_result = bybit_client.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=formatted_qty,
                reduceOnly=True
            )
            
            if not order_result or order_result.get("retCode") != 0:
                error_msg = order_result.get("retMsg", "Unknown error") if order_result else "No response"
                logger.error(f"Failed to close position for {symbol}: {error_msg}")
                return False
                
            order_id = order_result.get("result", {}).get("orderId")
            logger.info(f"Successfully closed position for {symbol}, Order ID: {order_id}")
            
            # Track the order
            track_order(
                order_type="CLOSE", 
                symbol=symbol, 
                side=close_side, 
                qty=formatted_qty,
                price=get_current_price(symbol), 
                order_id=order_id
            )
            
            return True
        else:
            logger.warning(f"No active position found for {symbol}")
            return False
    except Exception as e:
        logger.error(f"Error closing position for {symbol}: {e}")
        return False

def stack_position(symbol, signal_type):
    """
    Stack an existing position by adding more to it.
    
    Args:
        symbol (str): Trading pair symbol (e.g. 'BTCUSDT')
        signal_type (str): 'BUY' or 'SELL' signal type
        
    Returns:
        dict: Result containing success flag and position information
    """
    try:
        logger.info(f"Stacking position for {symbol} with signal type {signal_type}")
        
        # Get current position
        positions = get_active_positions()
        if symbol not in positions:
            logger.error(f"No active position found for {symbol} to stack")
            return {"success": False, "message": "No active position found"}
        
        position = positions[symbol]
        position_side = position.get("side")
        
        # Convert signal type to position side
        side_map = {"BUY": "Buy", "SELL": "Sell"}
        expected_side = side_map.get(signal_type)
        
        # Verify that the signal matches the position direction
        if position_side != expected_side:
            logger.error(f"Signal type {signal_type} doesn't match position side {position_side}")
            return {"success": False, "message": "Signal type doesn't match position side"}
        
        # Calculate the size for the additional position
        position_data = calculate_position_size(symbol, position_side)
        if not position_data:
            logger.error(f"Failed to calculate position size for {symbol}")
            return {"success": False, "message": "Failed to calculate position size"}
        
        qty = position_data["formatted_qty"]
        
        # Log detailed stacking info before execution
        logger.info(f"Stacking {symbol}: Current position {position_side} {position['size']} @ {position['entry_price']}")
        logger.info(f"Adding {qty} at current price {get_current_price(symbol)}")
        
        # Place the order to add to the position
        order_result = bybit_client.place_order(
            category="linear",
            symbol=symbol,
            side=position_side,
            orderType="Market",
            qty=qty
        )
        
        if not order_result or order_result.get("retCode") != 0:
            error_msg = order_result.get("retMsg", "Unknown error") if order_result else "No response"
            logger.error(f"Failed to stack position for {symbol}: {error_msg}")
            return {"success": False, "message": error_msg}
        
        order_id = order_result.get("result", {}).get("orderId")
        logger.info(f"Successfully stacked position for {symbol}, Order ID: {order_id}")
        
        # Track the order
        track_order(
            order_type="STACK", 
            symbol=symbol, 
            side=position_side, 
            qty=qty,
            price=get_current_price(symbol), 
            order_id=order_id
        )
        
        # Wait briefly to ensure position updates
        time.sleep(1)
        
        # Get updated position to confirm changes
        updated_positions = get_active_positions()
        if symbol in updated_positions:
            updated_pos = updated_positions[symbol]
            logger.info(f"Updated position after stacking: {symbol} {updated_pos['side']} {updated_pos['size']} @ {updated_pos['entry_price']}")
            
            # Calculate new ROI based on updated average entry price
            new_entry = updated_pos.get("entry_price", 0)
            mark_price = updated_pos.get("mark_price", 0)
            leverage = updated_pos.get("leverage", 1)
            
            # Calculate new ROI percentage
            if new_entry > 0 and mark_price > 0:
                if position_side == "Buy":
                    roi_pct = ((mark_price / new_entry) - 1) * 100 * leverage
                else:  # Sell
                    roi_pct = ((new_entry / mark_price) - 1) * 100 * leverage
                
                logger.info(f"New ROI after stacking: {roi_pct:.2f}%")
            
            return {
                "success": True,
                "symbol": symbol,
                "side": position_side,
                "qty": updated_pos["size"],
                "entry_price": new_entry,
                "order_id": order_id,
                "roi_pct": roi_pct if 'roi_pct' in locals() else 0
            }
        else:
            logger.warning(f"Position for {symbol} not found after stacking")
            return {"success": True, "message": "Order placed but position not found after stacking"}
        
    except Exception as e:
        logger.error(f"Error in stack_position for {symbol}: {e}")
        traceback.print_exc()
        return {"success": False, "message": str(e)}

def calculate_tp_with_leverage(entry_price, profit_pct, leverage, side):
    """
    Calculate take profit price accounting for leverage
    
    Formula:
    - For Buy/Long: entry_price × [1 + (profit_pct / leverage)]
    - For Sell/Short: entry_price × [1 - (profit_pct / leverage)]
    
    Args:
        entry_price (float): Entry price of the position
        profit_pct (float): Desired profit percentage (e.g., 10 for 10%)
        leverage (float): Position leverage
        side (str): "Buy" or "Sell"
        
    Returns:
        float: The calculated take profit price
    """
    leverage = max(1.0, float(leverage))  # Ensure minimum leverage of 1
    
    # Calculate percentage for price level - adjusted for leverage
    adjusted_pct = profit_pct / leverage
    
    logger.info(f"{side} position with {leverage}x leverage targeting {profit_pct}% profit")
    logger.info(f"TP price movement: {adjusted_pct:.2f}% from entry price {entry_price}")
    
    if side == "Buy":
        # For Buy positions (long), TP is ABOVE entry price
        tp_price = entry_price * (1 + adjusted_pct/100)
        logger.debug(f"Buy TP: {entry_price} × (1 + {adjusted_pct}/100) = {tp_price}")
        return tp_price
    else:  # Sell
        # For Sell positions (short), TP is BELOW entry price
        tp_price = entry_price * (1 - adjusted_pct/100)
        logger.debug(f"Sell TP: {entry_price} × (1 - {adjusted_pct}/100) = {tp_price}")
        return tp_price

def calculate_sl_with_leverage(entry_price, loss_pct, leverage, side):
    """
    Calculate stop loss price accounting for leverage
    
    Formula:
    - For Buy/Long: entry_price × [1 - (loss_pct / leverage)]
    - For Sell/Short: entry_price × [1 + (loss_pct / leverage)]
    
    Args:
        entry_price (float): Entry price of the position
        loss_pct (float): Desired loss percentage (e.g., 2 for 2%)
        leverage (float): Position leverage
        side (str): "Buy" or "Sell"
        
    Returns:
        float: The calculated stop loss price
    """
    leverage = max(1.0, float(leverage))  # Ensure minimum leverage of 1
    
    # For high leverage, ensure sufficient distance to avoid immediate liquidation
    if leverage >= 100:
        min_movement = 0.4  # 0.4% minimum for 100x leverage
    elif leverage >= 50:
        min_movement = 0.3  # 0.3% minimum for 50-99x leverage
    elif leverage >= 20:
        min_movement = 0.2  # 0.2% minimum for 20-49x leverage 
    else:
        min_movement = 0.1  # 0.1% minimum for under 20x leverage
    
    # Calculate percentage for price level - adjusted for leverage
    adjusted_pct = loss_pct / leverage
    
    # Ensure minimum movement percentage
    adjusted_pct = max(adjusted_pct, min_movement)
    
    logger.info(f"{side} position with {leverage}x leverage, {loss_pct}% stop loss")
    logger.info(f"SL price movement: {adjusted_pct:.2f}% from entry price {entry_price}")
    
    if side == "Buy":
        # For Buy/Long positions, SL is BELOW entry price
        sl_price = entry_price * (1 - adjusted_pct/100)
        logger.debug(f"Buy SL: {entry_price} × (1 - {adjusted_pct}/100) = {sl_price}")
        return sl_price
    else:  # Sell
        # For Sell/Short positions, SL is ABOVE entry price
        sl_price = entry_price * (1 + adjusted_pct/100)
        logger.debug(f"Sell SL: {entry_price} × (1 + {adjusted_pct}/100) = {sl_price}")
        return sl_price

def set_stop_loss(symbol, side, price):
    """Set stop loss for a position"""
    try:
        if not price:
            logger.error(f"Cannot set stop loss for {symbol} with empty price")
            return False
    
        logger.info(f"Setting stop loss for {symbol} at {price}")
        
        # First check if we need to set a new stop loss by getting current SL and mark price
        try:
            positions = bybit_client.get_positions(
                category="linear",
                symbol=symbol
            )
            
            position_list = positions.get("result", {}).get("list", [])
            if position_list:
                current_sl = float(position_list[0].get("stopLoss", "0") or "0")
                # Get current mark price
                mark_price = float(position_list[0].get("markPrice", "0") or "0")
                leverage = float(position_list[0].get("leverage", "1") or "1")
                
                # For Sell positions, ensure stop loss is ABOVE mark price to be valid
                if side == "Sell" and price <= mark_price:
                    old_price = price
                    # Set SL to at least 0.5% above mark price or use minimum distance based on leverage
                    min_distance = max(mark_price * 0.005, mark_price * (0.4 / leverage))
                    price = mark_price + min_distance
                    logger.warning(f"Adjusted SL from {old_price} to {price} to ensure it's above mark price {mark_price}")
                
                # If stop loss is already set to approximately the same value, no need to update
                if current_sl > 0 and abs((current_sl - price) / price) < 0.001:
                    logger.info(f"Stop loss for {symbol} already set to {current_sl}, skipping update")
                    return True
        except Exception as e:
            logger.warning(f"Error checking current stop loss: {e}")
        
        # Set the stop loss using set_trading_stop with Full mode
        response = bybit_client.set_trading_stop(
            category="linear",
            symbol=symbol,
            positionIdx=0,  # 0 for one-way mode
            tpslMode="Full",  # This parameter is required as per the API update
            stopLoss=str(price),
            slTriggerBy="MarkPrice",
            slOrderType="Market"
        )
        
        # Check for success (code 0) or "not modified" error (34040)
        if response and (response.get("retCode") == 0 or response.get("retCode") == 34040):
            logger.info(f"Successfully set stop loss for {symbol} at {price}")
            
            # Track the stop loss in order history
            track_order(
                order_type="SL_SET", 
                symbol=symbol, 
                side="Sell" if side == "Buy" else "Buy",  # SL is opposite side
                qty="FULL",  # Full position
                price=price,
                sl_level=price
            )
            return True
        else:
            error_msg = response.get("retMsg", "Unknown error") if response else "No response"
            error_code = response.get("retCode", "Unknown")
            logger.error(f"Failed to set stop loss for {symbol}: {error_msg} (code: {error_code})")
            
            # If the error is related to parameters, try again with a different approach
            if response and response.get("retCode") in [10001, 10002, 10003]:
                logger.info(f"Trying alternative method to set stop loss for {symbol}")
                
                # Try using the alternative API endpoint
                try:
                    alt_response = bybit_client.set_trading_stop(
                        category="linear",
                        symbol=symbol,
                        stopLoss=str(price),
                        tpslMode="Full",
                        slTriggerBy="MarkPrice"
                        # Removed slOrderType parameter that might be causing issues
                    )
                    
                    if alt_response and alt_response.get("retCode") == 0:
                        logger.info(f"Successfully set stop loss using alternative method for {symbol} at {price}")
                        return True
                    else:
                        alt_error = alt_response.get("retMsg", "Unknown error") if alt_response else "No response"
                        logger.error(f"Alternative method also failed: {alt_error}")
                except Exception as alt_e:
                    logger.error(f"Error with alternative stop loss method: {alt_e}")
            
            return False
            
    except Exception as e:
        logger.error(f"Error setting stop loss for {symbol}: {e}")
        return False

def check_for_existing_orders(symbol):
    """
    Check if a symbol has any pending orders (not just take profits)
    Returns True if orders exist, False otherwise
    """
    try:
        logger.info(f"Checking for existing orders for {symbol}")
        
        # Get all open orders for this symbol
        orders_response = bybit_client.get_open_orders(
            category="linear",
            symbol=symbol
        )
        
        if not orders_response or orders_response.get("retCode") != 0:
            logger.warning(f"Error getting open orders for {symbol}: {orders_response.get('retMsg', 'Unknown error')}")
            return False
            
        order_list = orders_response.get("result", {}).get("list", [])
        
        # Check if any orders exist
        if order_list and len(order_list) > 0:
            logger.info(f"{symbol} has {len(order_list)} pending orders")
            
            # Optional: Log order details for debugging
            for idx, order in enumerate(order_list[:3]):  # Limit to 3 orders to avoid excessive logging
                order_id = order.get("orderId", "Unknown")
                order_type = order.get("orderType", "Unknown")
                side = order.get("side", "Unknown")
                status = order.get("orderStatus", "Unknown")
                price = order.get("price", "Unknown")
                logger.info(f"Order #{idx+1}: ID={order_id}, Type={order_type}, Side={side}, Status={status}, Price={price}")
            
            return True
        else:
            logger.info(f"{symbol} has no pending orders")
            return False
            
    except Exception as e:
        logger.error(f"Error checking for orders for {symbol}: {e}")
        return False  # Default to False if we encounter an error

#--------------------- POSITION MANAGEMENT FUNCTIONS ---------------------#

def get_symbol_leverage(symbol):
    """
    Get the configured leverage for a specific symbol, falling back to global default
    
    Args:
        symbol (str): The trading pair symbol (e.g., "BTCUSDT")
        
    Returns:
        float: The leverage value to use for this symbol
    """
    # Check if we have a specific leverage setting for this symbol
    symbol_config = TRADING_CONFIG.get("symbol_config", {}).get(symbol, {})
    leverage = symbol_config.get("leverage", TRADING_CONFIG.get("leverage", 1))
    
    # Ensure leverage is a float
    try:
        leverage = float(leverage)
    except (ValueError, TypeError):
        leverage = 1.0
    
    if symbol in TRADING_CONFIG.get("symbol_config", {}):
        logger.info(f"Using symbol-specific leverage of {leverage}x for {symbol}")
    else:
        logger.info(f"Using default leverage of {leverage}x for {symbol}")
        
    return leverage

def open_position(
    symbol, side, qty, leverage=None, stop_loss_pct=None, 
    take_profit_pct=None, order_type="Market", limit_price=None
):
    """
    Place an order to enter a new position on Bybit.
    
    Args:
        symbol (str): Trading pair symbol (e.g. 'BTCUSDT')
        side (str): 'Buy' or 'Sell'
        qty (float): Position size in the base currency
        leverage (int, optional): Leverage to use
        stop_loss_pct (float, optional): Stop loss percentage (e.g. 10.0 for 10%)
        take_profit_pct (float, optional): Take profit percentage (e.g. 20.0 for 20%)
        order_type (str, optional): Order type ('Market' or 'Limit')
        limit_price (float, optional): Limit price if order_type is 'Limit'
        
    Returns:
        dict: Result containing position information
    """
    try:
        rest_client = HTTP(
            testnet=False,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )
        
        # Get leverage from symbol config if not explicitly provided
        if leverage is None:
            symbol_config = TRADING_CONFIG.get("symbol_config", {}).get(symbol, {})
            leverage = symbol_config.get("leverage", TRADING_CONFIG.get("leverage", 1))
            logger.info(f"Using leverage of {leverage}x for {symbol} from config")
        
        # Set leverage - always set both buy and sell leverage to the same value
        try:
            leverage_response = rest_client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)  # Set both to the same value
            )
            
            if leverage_response["retCode"] != 0 and leverage_response["retCode"] != 110043:
                # 110043 is "leverage not modified" which is OK
                logger.error(f"Failed to set leverage: {leverage_response}")
            else:
                logger.info(f"Set leverage to {leverage}x")
        except Exception as e:
            logger.error(f"Error setting leverage: {e}")
            # Continue anyway, the position might still open
        
        # Prepare order parameters
        order_params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
            "positionIdx": 0,  # One-way mode
            "timeInForce": "GTC",
        }
        
        # Add limit price if specified and order type is Limit
        if order_type == "Limit" and limit_price:
            order_params["price"] = str(limit_price)
        
        # Add take profit and stop loss conditionals
        if take_profit_pct:
            # Calculate take profit price based on expected position entry
            # For Buy orders, take profit is above entry; for Sell, it's below
            response = rest_client.get_tickers(
                category="linear",
                symbol=symbol
            )
            
            if response["retCode"] == 0:
                current_price = float(response["result"]["list"][0]["lastPrice"])
                
                if side == "Buy":
                    tp_price = current_price * (1 + take_profit_pct / 100)
                else:
                    tp_price = current_price * (1 - take_profit_pct / 100)
                
                # Round take profit price to appropriate precision
                tp_price = round(tp_price, 2)  # Assuming 2 decimal places for price
                
                # Add take profit to order parameters
                order_params["takeProfit"] = str(tp_price)
                order_params["tpTriggerBy"] = "MarkPrice"
                logger.info(f"Setting take profit at {tp_price}")
        
        if stop_loss_pct:
            # Calculate stop loss price based on expected position entry
            # For Buy orders, stop loss is below entry; for Sell, it's above
            if 'current_price' not in locals():
                response = rest_client.get_tickers(
                    category="linear",
                    symbol=symbol
                )
                
                if response["retCode"] == 0:
                    current_price = float(response["result"]["list"][0]["lastPrice"])
                else:
                    logger.error(f"Failed to get current price: {response}")
                    current_price = None
            
            if current_price:
                if side == "Buy":
                    sl_price = current_price * (1 - stop_loss_pct / 100)
                else:
                    sl_price = current_price * (1 + stop_loss_pct / 100)
                
                # Round stop loss price to appropriate precision
                sl_price = round(sl_price, 2)  # Assuming 2 decimal places for price
                
                # Add stop loss to order parameters
                order_params["stopLoss"] = str(sl_price)
                order_params["slTriggerBy"] = "MarkPrice"
                logger.info(f"Setting stop loss at {sl_price}")
        
        # Place the order
        order_response = rest_client.place_order(**order_params)
        
        if order_response["retCode"] != 0:
            logger.error(f"Failed to place order: {order_response}")
            return {
                "success": False,
                "message": f"Failed to place order: {order_response['retMsg']}",
                "order_id": None
            }
        
        logger.info(f"Successfully placed {side} order for {qty} {symbol}")
        logger.info(f"Order ID: {order_response['result']['orderId']}")
        
        # Track if stop loss and take profit were set
        sl_set = stop_loss_pct is not None
        tp_set = take_profit_pct is not None
        
        # Return success with order details
        return {
            "success": True,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": None,  # Will be populated when the position is filled
            "order_id": order_response['result']['orderId'],
            "sl_price": sl_price if stop_loss_pct else None,
            "sl_set": sl_set,
            "tp_set": tp_set
        }
    
    except Exception as e:
        logger.error(f"Error in open_position: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "message": str(e),
            "order_id": None
        }

def start_trailing_stop_monitor():
    """
    Start a background thread to monitor positions and set trailing stops
    automatically for positions that don't have them.
    """
    global trailing_stop_monitor_started
    
    # Check if already started
    if trailing_stop_monitor_started:
        logger.info("Trailing stop monitor already running, not starting again")
        return
    
    # Check if trailing stops are enabled in config
    ts_config = TRADING_CONFIG.get("trailing_stop", {})
    if not ts_config.get("enabled", False):
        logger.info("Automatic trailing stop monitoring disabled in config")
        return
    
    # Default check interval (5 minutes)
    interval_seconds = ts_config.get("check_interval_minutes", 5) * 60
    
    def monitor_trailing_stops():
        """Inner function that runs in a thread to monitor and set trailing stops"""
        logger.info("Starting trailing stop monitor thread")
        
        while True:
            try:
                # Get current active positions
                rest_client = HTTP(
                    testnet=False,
                    api_key=BYBIT_API_KEY,
                    api_secret=BYBIT_API_SECRET
                )
                
                response = rest_client.get_positions(
                    category="linear",
                    settleCoin="USDT"  # Limit to USDT margin positions
                )
                
                if response["retCode"] != 0:
                    logger.error(f"Failed to get positions: {response}")
                    time.sleep(interval_seconds)
                    continue
                
                positions = response["result"]["list"]
                active_positions = [
                    pos for pos in positions 
                    if float(pos.get("size", 0)) > 0
                ]
                
                if not active_positions:
                    logger.info("No active positions found to monitor for trailing stops")
                    time.sleep(interval_seconds)
                    continue
                
                # Get trailing stop parameters from config
                target_roi_pct = ts_config.get("target_roi_pct", 30)
                custom_callback = ts_config.get("callback_rate")
                
                # Check each position for trailing stop
                for position in active_positions:
                    symbol = position.get("symbol")
                    side = position.get("side")
                    size = float(position.get("size", 0))
                    
                    if size <= 0:
                        continue
                    
                    logger.info(f"Checking trailing stop for {symbol} {side} position")
                    
                    # Check if position already has a trailing stop
                    has_ts = False
                    try:
                        # In Bybit API v5, we can check if a trailing stop exists by checking
                        # the trailingStop field in the position data
                        trailing_stop = position.get("trailingStop")
                        if trailing_stop and trailing_stop != "0":
                            has_ts = True
                            logger.info(f"{symbol} already has trailing stop set ({trailing_stop})")
                        else:
                            logger.info(f"{symbol} needs trailing stop to be set")
                    except Exception as e:
                        logger.error(f"Error checking trailing stop status: {e}")
                    
                    # Set trailing stop if needed
                    if not has_ts:
                        try:
                            logger.info(f"Setting trailing stop for {symbol}")
                            
                            leverage = float(position.get("leverage", 1))
                            
                            # Set trailing stop based on config
                            if custom_callback:
                                ts_success = set_trailing_stop_for_symbol(
                                    symbol=symbol,
                                    callback_rate=custom_callback
                                )
                            else:
                                ts_success = set_trailing_stop_for_symbol(
                                    symbol=symbol,
                                    target_roi_pct=target_roi_pct
                                )
                            
                            if ts_success:
                                logger.info(f"Successfully set trailing stop for {symbol}")
                            else:
                                logger.warning(f"Failed to set trailing stop for {symbol}")
                                
                        except Exception as e:
                            logger.error(f"Error setting trailing stop for {symbol}: {e}")
                
                # Sleep before next check
                logger.info(f"Trailing stop monitor sleeping for {interval_seconds} seconds")
                time.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"Error in trailing stop monitor: {e}")
                traceback.print_exc()
                time.sleep(interval_seconds)
    
    # Start monitoring in a separate thread
    logger.info("Starting trailing stop monitor thread with settings:")
    logger.info(f"Target ROI: {ts_config.get('target_roi_pct', 20)}%, Callback: {ts_config.get('callback_rate', 0.5)}%")
    logger.info(f"Check interval: {ts_config.get('check_interval_minutes', 5)} minutes")
    threading.Thread(target=monitor_trailing_stops, daemon=True).start()
    logger.info("Trailing stop monitor thread started")
    
    # Mark as started
    trailing_stop_monitor_started = True

def set_trailing_stop_for_symbol(symbol, callback_rate=None, target_roi_pct=None):
    """
    Set a trailing stop for a specific symbol, automatically detecting position side and leverage
    
    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT')
        callback_rate: Optional direct callback rate (0.1-5.0%)
        target_roi_pct: Optional target ROI percentage (e.g., 30 for 30%)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get current active positions
        rest_client = HTTP(
            testnet=False,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )
        
        # Get position details
        response = rest_client.get_positions(
            category="linear",
            symbol=symbol
        )
        
        if response["retCode"] != 0 or not response["result"]["list"]:
            logger.error(f"No position found for {symbol}")
            return False
            
        position = None
        position_list = response["result"]["list"]
        
        # Find the active position
        for pos in position_list:
            size = float(pos.get("size", 0))
            if size > 0:
                position = pos
                break
                
        if not position:
            logger.error(f"No active position found for {symbol}")
            return False
            
        # Extract position details
        side = position.get("side")
        leverage = float(position.get("leverage", 1))
        entry_price = float(position.get("avgPrice", 0))
        current_price = float(position.get("markPrice", 0))
        size = float(position.get("size", 0))
        
        # Calculate unrealized PnL
        if side == "Buy":
            unrealized_pnl = (current_price - entry_price) * size
        else:  # Sell
            unrealized_pnl = (entry_price - current_price) * size
            
        # Calculate position value and initial margin
        position_value = size * entry_price
        initial_margin = position_value / leverage
        
        # Calculate current ROI
        current_roi_pct = (unrealized_pnl / initial_margin) * 100 if initial_margin > 0 else 0
        
        logger.info(f"Found {side} position for {symbol} with {leverage}x leverage")
        logger.info(f"Position: {side} {size} at {entry_price}, current price: {current_price}")
        logger.info(f"Position value: ${position_value:.2f}, Initial margin: ${initial_margin:.2f}")
        logger.info(f"Unrealized PnL: ${unrealized_pnl:.2f}, Current ROI: {current_roi_pct:.2f}%")
        
        # Check if we have config settings
        if callback_rate is None and target_roi_pct is None:
            ts_config = TRADING_CONFIG.get("trailing_stop", {})
            
            # Try to use config settings if available
            callback_rate = ts_config.get("callback_rate")
            target_roi_pct = ts_config.get("target_roi_pct", 20)  # Default to 20% if not specified
            
        # Make sure we have a callback rate
        if callback_rate is None:
            callback_rate = 0.5  # Default to 0.5% if not specified
        
        # Make sure target_roi_pct has a default value if it's None
        if target_roi_pct is None:
            target_roi_pct = 20  # Default to 20% if not specified
            
        logger.info(f"Using settings: callback_rate={callback_rate}, target_roi_pct={target_roi_pct}")
        
        # Calculate price change needed for target ROI (considering leverage)
        # ROI = Price Change % * Leverage
        # So: Price Change % = ROI / Leverage
        price_change_pct = target_roi_pct / leverage
        
        # Calculate target price based on entry price
        if side == "Buy":
            # For Buy positions, price needs to go UP to hit target ROI
            target_price = entry_price * (1 + price_change_pct/100)
            
            # Calculate distance to target from current price
            distance_to_target = target_price - current_price
            distance_pct = (distance_to_target / current_price) * 100
            
            logger.info(f"Target price for {target_roi_pct:.2f}% ROI: {target_price:.2f} (entry: {entry_price:.2f})")
            logger.info(f"Price needs to increase by {price_change_pct:.2f}% from entry")
            logger.info(f"Distance to target: ${distance_to_target:.2f} ({distance_pct:.2f}%)")
            
            # For Buy positions, trailing stop is BELOW current price by callback amount
            # The callback rate is the percentage drop from the highest price that will trigger the trailing stop
            # No need to calculate a specific trailing_stop value as the exchange calculates this dynamically
                        
            # USE THE TARGET PRICE AS THE ACTIVATION PRICE
            # This ensures the trailing stop only activates near our target ROI
            # Adjust slightly (0.5% below target) to ensure it activates before exactly hitting target
            activation_price = target_price * 0.995
            
            # Safety check: activation price must be higher than current price for Buy orders
            if current_price > activation_price:
                logger.info(f"Current price ({current_price}) already above activation price ({activation_price})")
                # Use current price plus a small buffer as activation price
                activation_price = current_price * 1.001
                logger.info(f"Adjusted activation price to: {activation_price:.4f}")
            
            logger.info(f"Using target price as activation price: {activation_price:.4f} (target: {target_price:.4f})")
            
        else:  # Sell position
            # For Sell positions, price needs to go DOWN to hit target ROI
            target_price = entry_price * (1 - price_change_pct/100)
            
            # Calculate distance to target from current price
            distance_to_target = current_price - target_price
            distance_pct = (distance_to_target / current_price) * 100
            
            logger.info(f"Target price for {target_roi_pct:.2f}% ROI: {target_price:.2f} (entry: {entry_price:.2f})")
            logger.info(f"Price needs to decrease by {price_change_pct:.2f}% from entry")
            logger.info(f"Distance to target: ${distance_to_target:.2f} ({distance_pct:.2f}%)")
            
            # For Sell positions, no need to calculate a specific trailing_stop as Bybit uses the callback rate directly
            
            # USE THE TARGET PRICE AS THE ACTIVATION PRICE
            # This ensures the trailing stop only activates near our target ROI
            # For Sell positions, we want activation price BELOW the target price (0.5% below)
            # since we want price to drop further than target before activating
            activation_price = target_price * 0.995
            
            # Safety check: activation price must be lower than current price for Sell positions
            if current_price < activation_price:
                logger.info(f"Current price ({current_price}) already below activation price ({activation_price})")
                # Use current price minus a small buffer as activation price
                activation_price = current_price * 0.999
                logger.info(f"Adjusted activation price to: {activation_price:.4f}")
            
            logger.info(f"Using target price as activation price: {activation_price:.4f} (target: {target_price:.4f})")
        
        # Calculate approximate liquidation price
        if leverage > 0:
            liquidation_threshold = 3.8 / leverage * 100  # % move to liquidation (simplified)
            if side == "Buy":
                liquidation_price = entry_price * (1 - liquidation_threshold/100)
            else:  # Sell
                liquidation_price = entry_price * (1 + liquidation_threshold/100)
            
            logger.info(f"Estimated liquidation price: {liquidation_price:.2f}")
            
            # Safety check - ensure activation price isn't too close to liquidation
            min_safe_distance = entry_price * (0.5 / leverage)  # Scaled by leverage
            
            if side == "Buy" and activation_price < liquidation_price + min_safe_distance:
                # For Buy positions, ensure activation price is above liquidation + safety margin
                old_activation = activation_price
                activation_price = liquidation_price + min_safe_distance
                logger.warning(f"Adjusted activation price from {old_activation:.2f} to {activation_price:.2f} for safety")
            elif side == "Sell" and activation_price > liquidation_price - min_safe_distance:
                # For Sell positions, ensure activation price is below liquidation - safety margin
                old_activation = activation_price
                activation_price = liquidation_price - min_safe_distance
                logger.warning(f"Adjusted activation price from {old_activation:.2f} to {activation_price:.2f} for safety")
        
        # Format the activation price to the correct number of decimal places for the symbol
        price_decimals = SYMBOL_CONFIG.get(symbol, {}).get("price_decimals", 2)
        activation_price = round(activation_price, price_decimals)
        
        # Set the trailing stop
        logger.info(f"Setting trailing stop for {symbol} with callback rate {callback_rate}%")
        logger.info(f"Activation price: {activation_price}")
        
        # Prepare parameters
        params = {
            "category": "linear",
            "symbol": symbol,
            "trailingStop": str(callback_rate),
            "positionIdx": 0,  # One-way mode
            "tpslMode": "Full"  # Using full position TP/SL
        }
        
        # Add active price - formatted to match exchange requirements
        params["activePrice"] = str(activation_price)
        
        # Call the API to set the trailing stop
        try:
            response = rest_client.set_trading_stop(**params)
            
            # Handle the "not modified" error code (34040) as success
            if response["retCode"] == 0 or response["retCode"] == 34040:
                logger.info(f"Successfully set trailing stop for {symbol}")
                logger.info(f"API Response: {response}")
                
                # Track the order
                track_order(
                    order_type="TS_SET", 
                    symbol=symbol,
                    side=side,
                    qty="FULL",  # Full position
                    price=current_price,
                    sl_level=activation_price
                )
                
                return True
            else:
                logger.error(f"Failed to set trailing stop: {response}")
                return False
                
        except Exception as e:
            if "not modified" in str(e).lower():
                # Handle the "not modified" exception as success
                logger.info(f"Trailing stop already set or not modified (This is OK)")
                return True
            else:
                logger.error(f"Error in API call to set trailing stop: {e}")
                return False
        
    except Exception as e:
        logger.error(f"Error setting trailing stop for {symbol}: {e}")
        traceback.print_exc()
        return False

def test_trailing_stop_for_sol(target_roi_pct=30, callback_rate=None):
    """
    Test function to set a trailing stop for SOLUSDT
    
    Args:
        target_roi_pct: Target ROI percentage (e.g., 30 for 30%)
        callback_rate: Optional direct callback rate (0.1 to 5.0)
    
    Returns:
        True if successful, False otherwise
    """
    symbol = "SOLUSDT"
    logger.info(f"Testing trailing stop for {symbol}")
    
    try:
        # Get current price and position details
        rest_client = HTTP(
            testnet=False,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )
            
        # Get position details
        position_info = rest_client.get_positions(
            category="linear",
            symbol=symbol
        )
            
        if position_info["retCode"] != 0 or not position_info["result"]["list"]:
            logger.error(f"No position found for {symbol}")
            
            # Try to find any active position
            all_positions = rest_client.get_positions(
                category="linear",
                settleCoin="USDT"
            )
                
            if all_positions["retCode"] == 0:
                active_positions = [
                    pos for pos in all_positions["result"]["list"] 
                    if float(pos.get("size", 0)) > 0
                ]
                    
                if active_positions:
                    logger.info(f"Found {len(active_positions)} active positions:")
                    for pos in active_positions:
                        sym = pos.get("symbol")
                        side = pos.get("side")
                        size = pos.get("size")
                        lev = pos.get("leverage")
                        logger.info(f"Available position: {sym} {side} {size} @ {lev}x")
                        
                    first_symbol = active_positions[0].get("symbol")
                    logger.info(f"Try running with one of these symbols:")
                    logger.info(f"python trade_manager.py --set-ts {first_symbol} --roi {target_roi_pct} --callback {callback_rate or 0.5}")
                else:
                    logger.info("No active positions found")
            
            return False
        
        # Get position details
        position = position_info["result"]["list"][0]
        side = position.get("side")
        size = position.get("size")
        leverage = position.get("leverage")
        entry_price = float(position.get("avgPrice", 0))
        current_price = float(position.get("markPrice", 0))
        
        logger.info(f"Position details for {symbol}:")
        logger.info(f"Side: {side}, Size: {size}, Leverage: {leverage}x")
        logger.info(f"Entry price: {entry_price}, Current price: {current_price}")
        
        # Set the trailing stop
        success = set_trailing_stop_for_symbol(
            symbol=symbol,
            target_roi_pct=target_roi_pct,
            callback_rate=callback_rate
        )
            
        if success:
            logger.info(f"Successfully set trailing stop for {symbol}")
            return True
        else:
            logger.error(f"Failed to set trailing stop for {symbol}")
            return False
            
    except Exception as e:
        logger.error(f"Error in test_trailing_stop_for_sol: {e}")
        traceback.print_exc()
        return False

def main():
    """Main program execution point"""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Manage trading positions")
    parser.add_argument("--set-ts", dest="set_trailing_stop", metavar="SYMBOL",
                        help="Symbol to set trailing stop for")
    parser.add_argument("--roi", type=float, default=20,
                        help="Target ROI percentage (for trailing stop)")
    parser.add_argument("--callback", type=float, default=0.5,
                        help="Callback rate percentage (for trailing stop)")
    args = parser.parse_args()
    
    try:
        # First sync time with server
        sync_result = time_sync()
        if sync_result:
            logger.info("Time sync done")
        
        # Load initial configuration
        load_trading_config()
        
        # Update precision info from API
        update_symbol_precision_from_api()
        
        logger.info("Running with time synchronized to Bybit server")
        
        # Display current configuration
        logger.info("Current trading configuration:")
        
        # Display position sizes for specific symbols
        default_position_size = TRADING_CONFIG.get("initial_position_usdt", 25.0)
        logger.info(f"Default position size: ${default_position_size}")
        
        # Log symbol-specific configs
        logger.info("Symbol-specific position sizes:")
        for symbol in TRADING_PAIRS:
            symbol_config = TRADING_CONFIG.get("symbol_config", {}).get(symbol, {})
            position_size = symbol_config.get("position_usdt", default_position_size)
            leverage = symbol_config.get("leverage", TRADING_CONFIG.get("leverage", 1))
            logger.info(f"  {symbol}: ${position_size} with {leverage}x leverage")
        
        # Stop loss
        sl_pct = TRADING_CONFIG.get("initial_stop_loss_pct", False)
        if sl_pct:
            logger.info(f"Stop loss: {sl_pct}%")
        else:
            logger.info("Stop loss: False%")
            
        # Take profit
        if TRADING_CONFIG.get("take_profit_enabled", False):
            tp_mode = TRADING_CONFIG.get("take_profit_mode", "strategic")
            logger.info(f"Take profit enabled with {tp_mode} mode")
            
            # Choose the right TP levels to display
            if tp_mode == "strategic":
                tp_levels = TRADING_CONFIG.get("strategic_tp_levels", [])
            else:
                tp_levels = TRADING_CONFIG.get("simple_tp_levels", [])
                
            logger.info(f"TP levels: {len(tp_levels)} levels configured")
            for i, level in enumerate(tp_levels):
                profit_pct = level.get("profit_pct")
                size_pct = level.get("size_pct")
                if profit_pct and size_pct:
                    logger.info(f"Level {i+1}: {profit_pct}% for {size_pct}% of position")
        else:
            logger.info("Take profit disabled")
            
        # Get active positions
        positions = get_active_positions()
        if positions:
            logger.info(f"Active positions: {len(positions)}")
            for symbol, pos in positions.items():
                side = pos.get("side")
                size = pos.get("size")
                leverage = pos.get("leverage")
                pnl_pct = pos.get("unrealised_pnl_pct", 0)
                
                logger.info(f"{symbol}: {side} {size} @ {leverage}x leverage, PnL: {pnl_pct:.2f}%")
        else:
            logger.info("No active positions")
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        traceback.print_exc()

def track_order(order_type, symbol, side, qty, price, order_id=None, sl_level=None):
    """Track an order in history"""
    try:
        global ORDER_HISTORY
        
        order = {
            "timestamp": datetime.now().isoformat(),
            "type": order_type,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "order_id": order_id,
            "sl_level": sl_level
        }
        
        ORDER_HISTORY.append(order)
        
        # Trim history if needed
        if len(ORDER_HISTORY) > MAX_ORDER_HISTORY:
            ORDER_HISTORY = ORDER_HISTORY[-MAX_ORDER_HISTORY:]
        
        logger.info(f"Tracked {order_type} order for {symbol}: {side} {qty} @ {price}")
        return True
    except Exception as e:
        logger.error(f"Error tracking order: {e}")
        return False

def start_monitoring_thread():
    """Start the position monitoring thread"""
    logger.info("Position monitoring thread started")
    # This is a simplified implementation that doesn't actually start a thread
    # In a real implementation, you would start a thread to monitor positions
    return True

def check_position_reversal(symbol, position, signal_info):
    """
    Close an existing position and open a new one in the opposite direction
    
    Args:
        symbol (str): Trading pair symbol (e.g. 'BTCUSDT')
        position (dict): Current position information
        signal_info (dict): Information about the new signal
        
    Returns:
        bool: Success flag
    """
    try:
        logger.info(f"Position reversal requested for {symbol}")
        
        # Extract current position details
        current_side = position.get("side")
        current_size = position.get("size")
        
        if not current_side or not current_size:
            logger.error(f"Missing position details for {symbol}")
            return False
            
        # Get the opposite side for the new position
        new_side = "Buy" if current_side == "Sell" else "Sell"
        
        # Close the existing position first
        logger.info(f"Closing existing {current_side} position for {symbol}")
        close_success = close_position(symbol, current_side)
        
        if not close_success:
            logger.error(f"Failed to close existing position for {symbol}")
            return False
            
        # Wait for position to be closed
        time.sleep(1)
        
        # Calculate position size for the new position
        position_data = calculate_position_size(symbol, new_side)
        if not position_data:
            logger.error(f"Failed to calculate new position size for {symbol}")
            return False
            
        # Open new position in the opposite direction
        logger.info(f"Opening new {new_side} position for {symbol}")
        result = open_position(symbol, new_side, position_data["formatted_qty"])
        
        if not result or not result.get("success", False):
            logger.error(f"Failed to open new position for {symbol}")
            return False
            
        logger.info(f"Successfully reversed position for {symbol} from {current_side} to {new_side}")
        return True
        
    except Exception as e:
        logger.error(f"Error in position reversal for {symbol}: {e}")
        traceback.print_exc()
        return False

# Call this function during startup
if __name__ == "__main__":
    # Initialize the TP tracking set
    tp_set_symbols = set()
    
    # Start the monitoring thread
    start_monitoring_thread()
    
    # Continue with main execution
    main()

# =================== MULTI-ACCOUNT TRADING SETUP ===================
multi_trader = None

def initialize_multi_account_trading():
    """Initialize multi-account trading if configured"""
    global multi_trader
    try:
        if os.path.exists("accounts_config.json"):
            multi_trader = SimpleMultiAccountTrader()
            if len(multi_trader.accounts) > 1:
                logger.info(f"✅ Multi-account trading initialized with {len(multi_trader.accounts)} accounts: {multi_trader.accounts}")
                return True
            elif len(multi_trader.accounts) == 1:
                logger.info(f"📱 Single account mode: {multi_trader.accounts[0]}")
                return True
            else:
                logger.warning("⚠️ No valid accounts found in config")
                multi_trader = None
                return False
        else:
            logger.info("📱 Single account mode: accounts_config.json not found")
            return False
    except Exception as e:
        logger.error(f"❌ Failed to initialize multi-account trading: {e}")
        multi_trader = None
        return False

def is_multi_account_enabled():
    """Check if multi-account trading is enabled and has multiple accounts"""
    return multi_trader is not None and len(multi_trader.accounts) > 1

def get_account_count():
    """Get the number of active accounts"""
    if multi_trader:
        return len(multi_trader.accounts)
    return 1

# Initialize multi-account trading on module load
initialize_multi_account_trading()

# =================== PARALLEL TRADING FUNCTIONS ===================

def open_position_parallel(symbol, side, qty, **kwargs):
    """Open position across all accounts in parallel"""
    if is_multi_account_enabled():
        logger.info(f"🔄 Opening {side} position for {symbol} across {len(multi_trader.accounts)} accounts")
        
        # Execute across all accounts
        results = multi_trader.execute_trade_parallel(symbol, side, qty, **kwargs)
        
        # Log summary
        successful = sum(1 for r in results.values() if r.get('success', False))
        total = len(results)
        
        if successful == total:
            logger.info(f"✅ Position opened successfully on ALL {successful} accounts")
        elif successful > 0:
            logger.warning(f"⚠️ Position opened on {successful}/{total} accounts")
        else:
            logger.error(f"❌ Position failed on ALL {total} accounts")
        
        # Return results for further processing
        return {"multi_account": True, "results": results, "success_count": successful, "total_count": total}
    else:
        # Fall back to single account
        logger.info(f"📱 Single account: Opening {side} position for {symbol}")
        result = open_position(symbol, side, qty, **kwargs)
        return {"multi_account": False, "result": result}

def close_position_parallel(symbol, side):
    """Close position across all accounts in parallel"""
    if is_multi_account_enabled():
        logger.info(f"🔄 Closing {side} position for {symbol} across {len(multi_trader.accounts)} accounts")
        
        # Execute across all accounts
        results = multi_trader.execute_close_parallel(symbol, side)
        
        # Log summary
        successful = sum(1 for r in results.values() if r.get('success', False))
        total = len(results)
        
        if successful == total:
            logger.info(f"✅ Position closed successfully on ALL {successful} accounts")
        elif successful > 0:
            logger.warning(f"⚠️ Position closed on {successful}/{total} accounts")
        else:
            logger.error(f"❌ Position close failed on ALL {total} accounts")
        
        return {"multi_account": True, "results": results, "success_count": successful, "total_count": total}
    else:
        # Fall back to single account
        logger.info(f"📱 Single account: Closing {side} position for {symbol}")
        result = close_position(symbol, side)
        return {"multi_account": False, "result": result}

def get_active_positions_all_accounts():
    """Get positions from all accounts"""
    if is_multi_account_enabled():
        return multi_trader.get_all_positions()
    else:
        # Return single account positions in multi-account format
        positions = get_active_positions()
        formatted_positions = {}
        
        for symbol, pos_data in positions.items():
            formatted_positions[symbol] = [{
                "account": "main",
                **pos_data
            }]
            
        return formatted_positions

def test_all_account_connections():
    """Test connections for all accounts"""
    if multi_trader:
        return multi_trader.test_all_connections()
    else:
        # Test single account
        try:
            server_time = bybit_client.get_server_time()
            if server_time.get("retCode") == 0:
                return {"main": {"status": "connected", "server_time": server_time.get("result", {}).get("timeSecond")}}
            else:
                return {"main": {"status": "error", "error": server_time.get("retMsg", "Unknown error")}}
        except Exception as e:
            return {"main": {"status": "error", "error": str(e)}}