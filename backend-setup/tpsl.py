import os
import sys
import json
import time
import logging
import threading
import traceback
from datetime import datetime
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import socket

# Load environment variables
load_dotenv()

# Configure logging with UTF-8 encoding to handle emojis
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tpsl_monitor.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('tpsl_monitor')

# Set console encoding to UTF-8 for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# API Configuration
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
USE_TESTNET = os.getenv("USE_TESTNET", "false").lower() == "true"

# TP/SL thresholds for sending alerts
TP_THRESHOLDS = [5.0, 10.0, 25.0, 50.0, 100.0]
SL_THRESHOLDS = [-5.0, -10.0, -15.0, -20.0]

# Dynamic SL Movement Rules
DYNAMIC_SL_RULES = {
    # 1.0: -25.0,
    # 5.0: 3.0,
    # 7.0: 5.0,
    # 9.0: 7.0,
    # 11.0: 9.0,
    # 15.0: 11.0,
    # 20.0: 15.0,
    25.0: 21.0,
    30.0: 26.0,
    35.0: 28.0,
    40.0: 38.0,
    45.0: 43.0,
    50.0: 48.0,
    55.0: 53.0,
    60.0: 58.0,
    70.0: 68.0,
    80.0: 70.0,
    90.0: 80.0,
    100.0: 90.0,
}

# Time intervals (in seconds)
WEBSOCKET_PING_INTERVAL = 5
POSITION_SUMMARY_INTERVAL = 60
POSITION_CHECK_INTERVAL = 5
WEBSOCKET_CHECK_INTERVAL = 10
REST_POLLING_INTERVAL = 0.5

# Trading category
CATEGORY = "linear"

# File paths
POSITIONS_FILE = "tpsl.json"
TP_TRACKING_FILE = "tp_tracking.json"
CONFIG_FILE = "trading_config.json"

# Global variables
position_data = {}
tp_tracking = {}

def get_server_time():
    """Get Bybit server time"""
    try:
        rest_client = HTTP(testnet=USE_TESTNET)
        response = rest_client.get_server_time()
        if response["retCode"] == 0:
            return int(response["result"]["timeSecond"])
        return int(time.time())
    except:
        return int(time.time())

def load_fresh_positions():
    """Load fresh position data from all_positions.json"""
    try:
        if os.path.exists("all_positions.json"):
            with open("all_positions.json", 'r') as f:
                data = json.load(f)
                if "positions" in data:
                    logging.info(f"Loaded {len(data['positions'])} fresh positions from all_positions.json")
                    return data["positions"]
                else:
                    logging.warning("No positions found in all_positions.json")
                    return {}
        else:
            logging.warning("all_positions.json not found")
            return {}
    except Exception as e:
        logging.error(f"Error loading fresh positions: {e}")
        return {}

def fix_tpsl_json():
    """Fix corrupted tpsl.json file"""
    try:
        clean_data = {
            "last_updated": datetime.now().isoformat(),
            "tp_tracking": {}
        }
        with open("tpsl.json", 'w') as f:
            json.dump(clean_data, f, indent=2)
        logging.info("[OK] Fixed corrupted tpsl.json file")
        return clean_data
    except Exception as e:
        logging.error(f"Error fixing tpsl.json: {e}")
        return {}

def load_positions():
    """Load position data from file"""
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, 'r') as f:
                content = f.read().strip()
                if not content:  # Empty file
                    logging.warning("tpsl.json is empty, creating new structure")
                    return fix_tpsl_json()
                    
                data = json.loads(content)
                logging.info(f"Loaded {len(data)} positions from {POSITIONS_FILE}")
                return data
        else:
            logging.info(f"No positions file found, creating new")
            return fix_tpsl_json()
    except Exception as e:
        logging.error(f"Error loading positions: {e}")
        return fix_tpsl_json()

def save_positions(data):
    """Save position data to file"""
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logging.info("Saved position data to tpsl.json")
    except Exception as e:
        logging.error(f"Error saving positions: {e}")

def update_dynamic_stop_loss(symbol, roi_pct, side):
    """Update stop loss based on current ROI percentage"""
    try:
        if not symbol or not isinstance(roi_pct, (int, float)):
            return False
            
        # Load fresh position data
        fresh_positions = load_fresh_positions()
        if symbol not in fresh_positions:
            logging.warning(f"No fresh position data found for {symbol}")
            return False

        fresh_pos = fresh_positions[symbol]
        current_sl_from_api = fresh_pos.get("stop_loss", 0)
        
        # Convert stop_loss to float
        if isinstance(current_sl_from_api, str):
            current_sl_from_api = float(current_sl_from_api) if current_sl_from_api and current_sl_from_api != "0" else 0
        elif current_sl_from_api is None:
            current_sl_from_api = 0
            
        logging.info(f"Fresh data for {symbol}: ROI={roi_pct:.2f}%, Current SL=${current_sl_from_api}")

        # Get tracking data
        positions = load_positions()
        if symbol not in positions:
            positions[symbol] = {
                "sl_level": 0,
                "last_threshold": 0,
                "highest_roi_achieved": 0,
                "highest_sl_level": 0
            }
        
        last_threshold = positions[symbol].get("last_threshold", 0)
        highest_roi_achieved = positions[symbol].get("highest_roi_achieved", 0)
        
        # Update highest ROI achieved
        if roi_pct > highest_roi_achieved:
            positions[symbol]["highest_roi_achieved"] = roi_pct
            highest_roi_achieved = roi_pct
            logging.info(f"New ROI high watermark for {symbol}: {roi_pct:.2f}%")
        
        # Find target threshold
        target_threshold = 0
        target_sl_level = None
        
        for roi_threshold in sorted(DYNAMIC_SL_RULES.keys()):
            if highest_roi_achieved >= roi_threshold:
                target_threshold = roi_threshold
                target_sl_level = DYNAMIC_SL_RULES[roi_threshold]
            else:
                break
                
        # Check if we need to set/update SL
        needs_sl_update = False
        
        if current_sl_from_api == 0 and target_threshold > 0:
            needs_sl_update = True
            logging.info(f"No SL set for {symbol} but ROI {roi_pct:.2f}% >= {target_threshold}% threshold - SETTING SL!")
        elif target_threshold > last_threshold:
            needs_sl_update = True
            logging.info(f"Higher threshold reached for {symbol}: {last_threshold}% -> {target_threshold}%")
        
        if not needs_sl_update:
            logging.info(f"No SL update needed for {symbol}")
            return False
            
        # Calculate new SL price
        entry_price = float(fresh_pos.get("entry_price", 0))
        leverage = float(fresh_pos.get("leverage", 1))
        
        if entry_price <= 0:
            logging.error(f"Invalid entry price for {symbol}: {entry_price}")
            return False
            
        if target_sl_level == "entry":
            new_sl_price = entry_price
        else:
            sl_pct = float(target_sl_level)
            price_pct = sl_pct / leverage
            
            if side == "Buy":
                new_sl_price = entry_price * (1 + (price_pct / 100))
            else:
                new_sl_price = entry_price * (1 - (price_pct / 100))
        
        # Round appropriately
        if entry_price < 1:
            new_sl_price = round(new_sl_price, 4)
        elif entry_price < 10:
            new_sl_price = round(new_sl_price, 3)
        elif entry_price < 1000:
            new_sl_price = round(new_sl_price, 2)
        else:
            new_sl_price = round(new_sl_price, 1)
            
        new_sl_price_str = str(new_sl_price)
            
        # Set SL via API
        rest_client = HTTP(
            testnet=USE_TESTNET,
            api_key=API_KEY,
            api_secret=API_SECRET,
            recv_window=20000
        )
        
        logging.info(f"SETTING SL for {symbol}: ${current_sl_from_api} -> ${new_sl_price_str} (ROI: {roi_pct:.2f}%, Target: {target_sl_level}%)")
        
        try:
            sl_response = rest_client.set_trading_stop(
                category=CATEGORY,
                symbol=symbol,
                stopLoss=new_sl_price_str,
                positionIdx=0,
                slTriggerBy="MarkPrice",
                slOrderType="Market",
                tpslMode="Full"
            )
            
            if sl_response["retCode"] == 0:
                logging.info(f"[SUCCESS] Successfully set SL for {symbol} at ${new_sl_price_str}")
                
                # Update tracking
                positions[symbol]["stop_loss"] = new_sl_price_str
                positions[symbol]["sl_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                positions[symbol]["sl_roi_level"] = target_sl_level
                positions[symbol]["sl_level"] = float(target_sl_level) if target_sl_level != "entry" else 0
                positions[symbol]["last_threshold"] = target_threshold
                
                save_positions(positions)
                return True
            else:
                logging.error(f"[FAILED] Failed to set SL for {symbol}: {sl_response.get('retMsg', 'Unknown error')}")
                return False
                
        except Exception as e:
            error_msg = str(e)
            
            if "34040" in error_msg or "not modified" in error_msg:
                # SL already at optimal level
                logging.info(f"[OK] SL for {symbol} already at optimal level (${new_sl_price_str}) - no change needed")
                
                # Update tracking even though API call wasn't needed
                positions[symbol]["stop_loss"] = new_sl_price_str
                positions[symbol]["sl_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                positions[symbol]["sl_roi_level"] = target_sl_level
                positions[symbol]["sl_level"] = float(target_sl_level) if target_sl_level != "entry" else 0
                positions[symbol]["last_threshold"] = target_threshold
                
                save_positions(positions)
                return True
            else:
                logging.error(f"[ERROR] Error setting SL for {symbol}: {error_msg}")
                return False
        
    except Exception as e:
        logging.error(f"Error in update_dynamic_stop_loss: {e}")
        return False

def check_positions_rest_api():
    """Check positions using fresh data"""
    try:
        fresh_positions = load_fresh_positions()
        
        if not fresh_positions:
            logging.warning("No fresh position data available")
            return
            
        for symbol, pos_data in fresh_positions.items():
            roi_pct = float(pos_data.get("roi_pct", 0))
            side = pos_data.get("side", "")
            stop_loss = pos_data.get("stop_loss", 0)
            
            if isinstance(stop_loss, str):
                stop_loss = float(stop_loss) if stop_loss and stop_loss != "0" else 0
            elif stop_loss is None:
                stop_loss = 0
                
            logging.info(f"Processing {symbol}: ROI={roi_pct:.2f}%, Side={side}, Current SL=${stop_loss}")
            
            if roi_pct > 0:
                logging.info(f"Position {symbol} in profit ({roi_pct:.2f}%) - checking SL thresholds")
                result = update_dynamic_stop_loss(symbol, roi_pct, side)
                if result:
                    logging.info(f"[SUCCESS] SL updated for {symbol}")
                else:
                    logging.info(f"No SL update needed for {symbol}")
            else:
                logging.info(f"Position {symbol} not in profit ({roi_pct:.2f}%) - skipping SL update")
        
    except Exception as e:
        logging.error(f"Error in check_positions_rest_api: {e}")

def start_position_monitor():
    """Start the position monitoring system"""
    try:
        logging.info("Starting position monitor")
        
        # Main loop
        while True:
            try:
                check_positions_rest_api()
                time.sleep(REST_POLLING_INTERVAL)
            except Exception as e:
                logging.error(f"Error in main loop: {e}")
                time.sleep(5)
            
    except KeyboardInterrupt:
        logging.info("Position monitor stopped by user")
    except Exception as e:
        logging.error(f"Error in position monitor: {e}")

if __name__ == "__main__":
    logging.info("=" * 50)
    logging.info(f"Starting TP/SL Monitor at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("=" * 50)
    
    if not API_KEY or not API_SECRET:
        logging.error("API keys not found. Please check your .env file.")
        sys.exit(1)
    
    start_position_monitor() 