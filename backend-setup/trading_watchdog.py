import os
import sys
import time
import signal
import traceback
import subprocess
import logging
import json
from datetime import datetime, timedelta
import psutil  # Make sure to pip install psutil
import importlib.util
import trade_manager  # Import the whole module instead of a specific name
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler  # pip install watchdog
from time_sync import time_sync, get_server_time_ms
import shutil
import glob
import requests

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG to see more detailed logs during troubleshooting
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("watchdog.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("watchdog")

# Optional: Set console output to INFO level while keeping file at DEBUG level
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
file_handler = logging.FileHandler("watchdog.log")
file_handler.setLevel(logging.DEBUG)
logger.handlers = [file_handler, console_handler]

# Global variables for tracking file errors and cooldowns
file_error_counts = {
    "positions": 0,
    "signals": 0
}
MAX_CONSECUTIVE_ERRORS = 5
FILE_ERROR_COOLDOWN = 5  # seconds to wait after consecutive errors

# File locking to prevent race conditions with other processes
file_last_mod_times = {
    "positions": 0,
    "signals": 0
}
FILE_WRITE_EXCLUSION_PERIOD = 0.5  # seconds to wait after file modification before reading

# Configuration
MONITOR_PROCESS_NAME = "s1.py"
CHECK_INTERVAL = 0.1  # seconds - reduced to check more frequently
RESTART_DELAY = 5  # seconds
MAX_RESTARTS = 5  # Maximum restarts within restart window
RESTART_WINDOW = 300  # 5 minutes in seconds
restart_history = []

# File paths
POSITIONS_FILE = "all_positions.json"
SIGNALS_FILE = "all_trade_signals.json"
TRIGGER_LOG_FILE = "trigger_log.json"
CONFIG_FILE = "trading_config.json"

# Trigger tracking
# last_trigger_time = {}  # Comment out or remove this line
TRIGGER_COOLDOWN = 300  # 5 minutes cooldown (reduced from 3600)

# Add new constant for signal logging
SIGNAL_LOG_FILE = "signal_history.json"

# Add these constants near the top of the file
VOLATILITY_WINDOW = 20  # Number of price points to consider for volatility
VOLATILITY_THRESHOLD = 0.5  # Minimum volatility threshold (0.5%)
MAX_VOLATILITY_THRESHOLD = 3.0  # Maximum volatility threshold (3%)

# Add this after the file imports but before other code
class CooldownTracker:
    """
    Centralized system for tracking and enforcing cooldowns across different operations.
    This replaces multiple scattered cooldown tracking dictionaries.
    """
    def __init__(self):
        # Main cooldown storage: {category: {key: expiration_timestamp}}
        self.cooldowns = {
            'signal': {},      # For trade signals
            'position': {},    # For position management
            'file': {},        # For file operations
            'api': {}          # For API calls
        }
        
        # Default cooldown durations (in seconds)
        self.default_durations = {
            'signal': 300,     # 5 minutes for trade signals
            'position': 600,   # 10 minutes for position operations
            'file': 5,         # 5 seconds for file operations
            'api': 60          # 1 minute for API calls
        }
    
    def set_cooldown(self, category, key, duration=None):
        """
        Set a cooldown for a specific key in a category
        
        Args:
            category: The category of cooldown (signal, position, file, api)
            key: The specific identifier (e.g., symbol name)
            duration: Custom duration in seconds, or None to use default
        """
        if category not in self.cooldowns:
            return False
            
        if duration is None:
            duration = self.default_durations.get(category, 60)
            
        self.cooldowns[category][key] = time.time() + duration
        return True
    
    def is_in_cooldown(self, category, key):
        """
        Check if a key is currently in cooldown
        
        Args:
            category: The category of cooldown
            key: The specific identifier
            
        Returns:
            bool: True if in cooldown, False otherwise
        """
        if category not in self.cooldowns:
            return False
            
        cooldown_time = self.cooldowns[category].get(key, 0)
        return time.time() < cooldown_time
    
    def get_remaining(self, category, key):
        """
        Get remaining cooldown time in seconds
        
        Returns:
            float: Remaining time in seconds, or 0 if not in cooldown
        """
        if category not in self.cooldowns:
            return 0
            
        cooldown_time = self.cooldowns[category].get(key, 0)
        remaining = cooldown_time - time.time()
        return max(0, remaining)
    
    def clear_cooldown(self, category, key):
        """Remove a cooldown before it expires"""
        if category in self.cooldowns and key in self.cooldowns[category]:
            del self.cooldowns[category][key]
    
    def get_all_in_cooldown(self, category=None):
        """
        Get all items currently in cooldown
        
        Args:
            category: Optional category filter
            
        Returns:
            dict: {key: remaining_time} for all items in cooldown
        """
        current_time = time.time()
        result = {}
        
        if category:
            if category not in self.cooldowns:
                return {}
                
            categories = [category]
        else:
            categories = self.cooldowns.keys()
        
        for cat in categories:
            result[cat] = {}
            for key, expiry in list(self.cooldowns[cat].items()):
                if current_time < expiry:
                    result[cat][key] = expiry - current_time
                else:
                    # Auto-cleanup expired cooldowns
                    del self.cooldowns[cat][key]
        
        return result

# Create a global instance
cooldown_tracker = CooldownTracker()

# Load trade_manager.py as a module for direct function calls - no longer needed since we import directly
def load_trade_manager():
    """
    DEPRECATED: No longer used since we import trade_manager directly.
    This function is kept for backward compatibility.
    """
    return trade_manager  # Just return the imported module

# Global reference to trade manager is now the imported module

def is_process_running(process_name):
    """Check if a process is running by name"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Check if the process name contains our target
            cmdline = proc.info.get('cmdline')
            if cmdline and any(process_name in cmd for cmd in cmdline):
                return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None

def start_monitor():
    """Start the trigger_monitor.py process"""
    try:
        logger.info("Starting trigger_monitor.py process")
        process = subprocess.Popen(
            [sys.executable, MONITOR_PROCESS_NAME],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Started process with PID: {process.pid}")
        return process.pid
    except Exception as e:
        logger.error(f"Failed to start monitor process: {e}")
        return None

def check_file_freshness(file_path, max_age_seconds=300):
    """Check if a file exists and has been updated within max_age_seconds"""
    if not os.path.exists(file_path):
        logger.warning(f"File does not exist: {file_path}")
        return False
    
    file_mod_time = os.path.getmtime(file_path)
    current_time = time.time()
    file_age = current_time - file_mod_time
    
    if file_age > max_age_seconds:
        logger.warning(f"File {file_path} is stale: {file_age:.1f} seconds old (max: {max_age_seconds})")
        return False
    
    return True

def safe_read_json(file_path):
    """
    Read a JSON file safely with multiple retries and atomic file handling.
    Returns (data, success_flag)
    """
    max_retries = 3
    retry_delay = 0.3  # seconds
    
    for attempt in range(max_retries):
        try:
            # First, check if file exists and is non-empty
            if not os.path.exists(file_path) or os.path.getsize(file_path) < 2:
                logger.debug(f"File {file_path} does not exist or is empty (attempt {attempt+1}/{max_retries})")
                return None, False
                
            # Wait a small amount to ensure file writing is complete
            if attempt > 0:
                time.sleep(retry_delay)
                
            # Try to read the file
            with open(file_path, "r") as f:
                content = f.read().strip()
                if not content:
                    logger.debug(f"File {file_path} is empty after reading (attempt {attempt+1}/{max_retries})")
                    return None, False
                
                # First, check if the content is a raw string and not proper JSON
                if (content.startswith('"') and content.endswith('"')) or \
                   (not content.startswith('{') and not content.startswith('[')):
                    logger.warning(f"File {file_path} contains a raw string instead of JSON object")
                    
                    # Try to parse it as a JSON string
                    try:
                        if content.startswith('"') and content.endswith('"'):
                            # If it's a quoted string, try to parse the inner content
                            inner_content = content[1:-1].replace('\\"', '"')
                            data = json.loads(inner_content)
                            logger.info(f"Successfully parsed inner content of JSON string")
                            return data, True
                        else:
                            # Return the string as is
                            logger.info(f"Returning raw string content")
                            return content, True
                    except json.JSONDecodeError:
                        logger.warning(f"Inner content is not valid JSON either")
                        return content, True
                
                # Try to parse JSON
                try:
                    data = json.loads(content)
                    return data, True
                except json.JSONDecodeError as e:
                    # Look for common JSON corruption patterns
                    logger.warning(f"JSON parse error: {e}")
                    
                    # Try some common fixes
                    # 1. Check for trailing commas in objects/arrays
                    fixed_content = content.replace(",\n}", "\n}").replace(",\n]", "\n]")
                    
                    # 2. Check for unclosed quotes
                    quote_count = content.count('"')
                    if quote_count % 2 != 0:
                        logger.warning(f"Odd number of quotes ({quote_count}) - trying to fix")
                        fixed_content = fixed_content + '"'
                    
                    # 3. Check for missing closing braces
                    open_braces = content.count('{')
                    close_braces = content.count('}')
                    if open_braces > close_braces:
                        logger.warning(f"Missing {open_braces - close_braces} closing braces - trying to fix")
                        fixed_content = fixed_content + ("}" * (open_braces - close_braces))
                    
                    # 4. Check for missing closing brackets
                    open_brackets = content.count('[')
                    close_brackets = content.count(']')
                    if open_brackets > close_brackets:
                        logger.warning(f"Missing {open_brackets - close_brackets} closing brackets - trying to fix")
                        fixed_content = fixed_content + ("]" * (open_brackets - close_brackets))
                    
                    # Try parsing with fixes
                    try:
                        data = json.loads(fixed_content)
                        logger.info(f"Successfully fixed and parsed corrupted JSON")
                        
                        # Write the fixed content back to the file
                        with open(file_path, "w") as f:
                            f.write(fixed_content)
                        logger.info(f"Saved fixed JSON back to file")
                        
                        return data, True
                    except json.JSONDecodeError:
                        logger.warning(f"Could not fix corrupted JSON with simple fixes")
                        
                        # If this is the last attempt, create and return an empty object
                        if attempt == max_retries - 1:
                            logger.error(f"All attempts to read {file_path} failed, returning empty object")
                            
                            # Create a backup of the corrupted file
                            backup_path = f"{file_path}.corrupted.{int(time.time())}"
                            try:
                                shutil.copy2(file_path, backup_path)
                                logger.info(f"Created backup of corrupted file at {backup_path}")
                            except Exception as backup_err:
                                logger.error(f"Error creating backup of corrupted file: {backup_err}")
                            
                            # Create a new empty file with proper structure based on filename
                            empty_data = {}
                            if file_path.endswith('all_positions.json'):
                                empty_data = {"positions": {}, "last_update": datetime.now().isoformat()}
                            elif file_path.endswith('all_trade_signals.json'):
                                empty_data = {"_last_update": datetime.now().isoformat()}
                            
                            # Write empty data structure
                            with open(file_path, "w") as f:
                                json.dump(empty_data, f, indent=2)
                            logger.info(f"Created new empty file structure at {file_path}")
                            
                            return empty_data, True
                
        except json.JSONDecodeError as e:
            # File exists but JSON is invalid
            logger.debug(f"Invalid JSON in {file_path}: {e} (attempt {attempt+1}/{max_retries})")
            
            # On the last attempt, try to read the file as text to see what's wrong
            if attempt == max_retries - 1:
                try:
                    with open(file_path, "r") as f:
                        content = f.read(500)  # First 500 chars to diagnose
                        logger.debug(f"Content of invalid JSON file (first 500 chars): {content}")
                except Exception as read_error:
                    logger.debug(f"Error reading file content for diagnosis: {read_error}")
                    
            time.sleep(retry_delay * (attempt + 1))  # Progressive backoff
            
        except Exception as e:
            logger.debug(f"Error reading {file_path}: {e} (attempt {attempt+1}/{max_retries})")
            time.sleep(retry_delay)
            
    # All retries failed
    return None, False

def safe_write_json(file_path, data, backup_count=3):
    """
    Write data to a JSON file safely with atomic file handling and transaction-style recovery.
    
    Args:
        file_path: Path to the target JSON file
        data: Data to write to the file
        backup_count: Number of backup files to maintain
        
    Returns:
        bool: Success flag
    """
    try:
        # Verify data is a proper JSON serializable object
        if data is None:
            logger.warning(f"Attempted to write None to {file_path}, using empty dict instead")
            data = {}
        
        # Handle the case where data might be a string instead of a dict
        if isinstance(data, str):
            logger.warning(f"Attempted to write string to {file_path}, parsing or converting to dict")
            try:
                # Try to parse as JSON first
                parsed_data = json.loads(data)
                if isinstance(parsed_data, dict):
                    logger.info(f"Successfully parsed string data as JSON")
                    data = parsed_data
                else:
                    logger.warning(f"Parsed data is not a dictionary, using empty dict")
                    data = {}
            except Exception as e:
                logger.error(f"Could not parse string as JSON: {e}")
                data = {}
        
        # Create backup directory if it doesn't exist
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(file_path)), 'backups')
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
                logger.debug(f"Created backup directory: {backup_dir}")
            except Exception as e:
                logger.warning(f"Could not create backup directory: {e}")
                # Continue even if backup directory creation fails
        
        # Create a backup of the existing file if it exists
        if os.path.exists(file_path) and os.path.getsize(file_path) > 2:
            backup_filename = f"{os.path.basename(file_path)}.{int(time.time())}.bak"
            backup_path = os.path.join(backup_dir, backup_filename)
            try:
                shutil.copy2(file_path, backup_path)
                logger.debug(f"Created backup of {file_path} at {backup_path}")
                
                # Clean up old backups (keep only backup_count most recent)
                try:
                    backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) 
                                     if f.startswith(os.path.basename(file_path)) and f.endswith('.bak')],
                                    key=os.path.getmtime,
                                    reverse=True)
                    for old_backup in backups[backup_count:]:
                        os.remove(old_backup)
                        logger.debug(f"Removed old backup: {old_backup}")
                except Exception as cleanup_error:
                    logger.warning(f"Error cleaning up old backups: {cleanup_error}")
            except Exception as backup_error:
                logger.warning(f"Error creating backup: {backup_error}")
                # Continue even if backup fails
        
        # Validate the data object has the expected structure for positions file
        if file_path.endswith('all_positions.json'):
            # Ensure we have proper structure for positions file
            if not isinstance(data, dict):
                logger.warning("Converting positions data to proper dictionary structure")
                data = {"positions": {}, "last_update": datetime.now().isoformat()}
            elif "positions" not in data:
                logger.warning("Adding missing 'positions' key to positions data")
                data["positions"] = {}
            elif not isinstance(data["positions"], dict):
                logger.warning("Fixing corrupted 'positions' value in positions data")
                data["positions"] = {}
                
            # Always ensure last_update field is present
            data["last_update"] = datetime.now().isoformat()
            
            # Validate individual position entries
            for symbol, position in list(data["positions"].items()):
                if not isinstance(position, dict):
                    logger.warning(f"Removing invalid position entry for {symbol}")
                    del data["positions"][symbol]
                    continue
                
                # Ensure required fields are present
                if "side" not in position:
                    logger.warning(f"Position for {symbol} missing 'side' field, removing")
                    del data["positions"][symbol]
        
        # Special validation for signals file - ensure correct structure
        if file_path.endswith('all_trade_signals.json'):
            # The signals file should be a flat dictionary with symbol keys
            if not isinstance(data, dict):
                logger.warning("Converting signals data to proper dictionary structure")
                data = {}  # Create empty dict for signals
            
            # Validate each signal entry
            for symbol, signal_data in list(data.items()):
                # Skip metadata keys that start with underscore
                if symbol.startswith('_'):
                    continue
                
                # Ensure each signal is a dictionary
                if not isinstance(signal_data, dict):
                    logger.warning(f"Removing invalid signal entry for {symbol}: {type(signal_data).__name__}")
                    del data[symbol]
                    continue
                
                # Ensure required fields exist
                if "symbol" not in signal_data:
                    signal_data["symbol"] = symbol
                
                if "signal" not in signal_data:
                    signal_data["signal"] = "NEUTRAL"
                
                if "timestamp" not in signal_data:
                    signal_data["timestamp"] = datetime.now().isoformat()
            
            # Add last update timestamp
            data["_last_update"] = datetime.now().isoformat()
        
        # First write to a temporary file, then rename for atomicity
        temp_file = f"{file_path}.tmp"
        
        # Make multiple attempts to write and rename the file (retry mechanism for Windows file locks)
        max_attempts = 5
        retry_delay = 0.5
        
        for attempt in range(max_attempts):
            try:
                # Write to temp file
                with open(temp_file, "w") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                
                # Windows-specific: try to ensure file is not locked
                time.sleep(0.1)  # Small pause to let any filesystem operations complete
                
                # Rename the temp file to the actual file (atomic operation)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)  # Remove existing file if it exists
                    except PermissionError:
                        # If we can't remove it, try a slight delay
                        time.sleep(0.3)
                        try:
                            os.remove(file_path)
                        except:
                            # If we still can't remove it, try alternative approach
                            if os.path.exists(file_path + ".old"):
                                os.remove(file_path + ".old")
                            os.rename(file_path, file_path + ".old")
                
                os.rename(temp_file, file_path)
                
                # Break out of the retry loop if successful
                break
                
            except PermissionError as e:
                # Windows PermissionError usually means the file is being used by another process
                if attempt < max_attempts - 1:
                    logger.warning(f"Permission error writing file (attempt {attempt+1}/{max_attempts}): {e}")
                    time.sleep(retry_delay * (attempt + 1))  # Increase delay with each attempt
                else:
                    logger.error(f"All attempts to write file failed due to permission errors: {e}")
                    return False
                    
            except OSError as e:
                # This includes WinError 32 - file in use by another process
                if attempt < max_attempts - 1:
                    logger.warning(f"OS error writing file (attempt {attempt+1}/{max_attempts}): {e}")
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    logger.error(f"All attempts to write file failed due to OS errors: {e}")
                    return False
        
        # Validate the written file
        try:
            with open(file_path, 'r') as f:
                json.load(f)  # Try to parse the JSON to ensure it's valid
            logger.debug(f"Successfully wrote and validated data to {file_path}")
            return True
        except json.JSONDecodeError:
            logger.error(f"Written file {file_path} contains invalid JSON, attempting recovery...")
            # Try to recover from the most recent backup
            if os.path.exists(backup_dir):
                backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) 
                                 if f.startswith(os.path.basename(file_path)) and f.endswith('.bak')],
                                key=os.path.getmtime,
                                reverse=True)
                if backups:
                    try:
                        shutil.copy2(backups[0], file_path)
                        logger.info(f"Recovered {file_path} from backup {backups[0]}")
                        return False
                    except Exception as recovery_error:
                        logger.error(f"Error recovering from backup: {recovery_error}")
            return False
    except Exception as e:
        logger.error(f"Error writing data to {file_path}: {e}")
        return False

def get_active_positions():
    """Get currently active positions from positions file"""
    global file_error_counts, file_last_mod_times
    
    # Check if we're in a cooldown period for consecutive errors
    if file_error_counts["positions"] >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(f"Too many consecutive errors reading positions file, cooling down for {FILE_ERROR_COOLDOWN} seconds")
        time.sleep(FILE_ERROR_COOLDOWN)
        file_error_counts["positions"] = 0  # Reset after cooldown
    
    try:
        # Check if file exists and if it was recently modified
        if os.path.exists(POSITIONS_FILE):
            curr_mod_time = os.path.getmtime(POSITIONS_FILE)
            time_since_mod = time.time() - curr_mod_time
            
            # If file was recently modified, wait to avoid reading during write
            if time_since_mod < FILE_WRITE_EXCLUSION_PERIOD:
                logger.debug(f"Positions file was modified {time_since_mod:.2f}s ago, waiting to avoid conflict")
                time.sleep(FILE_WRITE_EXCLUSION_PERIOD - time_since_mod)
            
            # Update stored modification time
            file_last_mod_times["positions"] = curr_mod_time
            
        # Use safe_read_json to handle atomic reads
        data, success = safe_read_json(POSITIONS_FILE)
        
        if not success:
            # Check if we already recreated the file recently (within 60 seconds)
            # to avoid constant recreations
            curr_time = time.time()
            last_recreate_key = "positions_last_recreate"
            last_recreate_time = getattr(get_active_positions, last_recreate_key, 0)
            
            # Add more debug info to see what's happening with the file
            try:
                if os.path.exists(POSITIONS_FILE):
                    file_size = os.path.getsize(POSITIONS_FILE)
                    logger.warning(f"Positions file exists but could not be read: Size={file_size} bytes")
                    if file_size > 0:
                        try:
                            with open(POSITIONS_FILE, 'r') as f:
                                content = f.read(100)  # Read first 100 chars
                                logger.warning(f"First 100 chars of positions file: {content}")
                        except Exception as read_err:
                            logger.warning(f"Error reading positions file content: {read_err}")
                else:
                    logger.warning("Positions file does not exist")
            except Exception as e:
                logger.warning(f"Error checking positions file: {e}")
            
            if curr_time - last_recreate_time < 60:
                logger.warning(f"Positions file recreated less than 60 seconds ago, skipping recreation")
                file_error_counts["positions"] += 1
                return {}
            
            # If read failed, create a new valid file structure
            logger.warning(f"Failed to read positions file, creating new structure")
            new_data = {"positions": {}, "last_update": datetime.now().isoformat()}
            
            # Use safe_write_json for atomic file writes
            if safe_write_json(POSITIONS_FILE, new_data):
                # Track when we last recreated the file
                setattr(get_active_positions, last_recreate_key, curr_time)
                logger.info(f"Created new positions file with valid structure at {os.path.abspath(POSITIONS_FILE)}")
            else:
                logger.error("Failed to create new positions file")
            
            file_error_counts["positions"] += 1  # Count this as an error
            return {}
        
        # Read succeeded, reset error counter
        file_error_counts["positions"] = 0
        positions = data.get("positions", {})
        
        # Check if the positions are actually in the expected format
        if positions and len(positions) > 0:
            # Log how many positions were found
            position_symbols = list(positions.keys())
            logger.info(f"Loaded {len(positions)} active positions: {', '.join(position_symbols)}")
            
            # Check one position to make sure it has the required fields
            first_symbol = next(iter(positions))
            first_position = positions[first_symbol]
            if not isinstance(first_position, dict) or "side" not in first_position:
                logger.warning(f"Positions data found but has invalid format: {first_position}")
                positions = {}  # Reset to empty if invalid
        elif positions:
            logger.info(f"Loaded positions file, but it contains an empty positions dictionary")
        else:
            logger.info(f"No active positions found in positions file")
            
        return positions
            
    except Exception as e:
        logger.error(f"Error loading positions: {e}")
        # Add more debug information
        try:
            logger.error(f"File exists: {os.path.exists(POSITIONS_FILE)}, Size: {os.path.getsize(POSITIONS_FILE) if os.path.exists(POSITIONS_FILE) else 'N/A'}")
            logger.error(f"Permissions: {oct(os.stat(POSITIONS_FILE).st_mode)[-3:] if os.path.exists(POSITIONS_FILE) else 'N/A'}")
        except Exception as inner_e:
            logger.error(f"Could not get file details: {inner_e}")
        file_error_counts["positions"] += 1  # Count this as an error
        return {}

def get_signal_data():
    """Get trading signals from signals file"""
    global file_error_counts, file_last_mod_times
    
    # Check if we're in a cooldown period for consecutive errors
    if file_error_counts["signals"] >= MAX_CONSECUTIVE_ERRORS:
        logger.warning(f"Too many consecutive errors reading signals file, cooling down for {FILE_ERROR_COOLDOWN} seconds")
        time.sleep(FILE_ERROR_COOLDOWN)
        file_error_counts["signals"] = 0  # Reset after cooldown
    
    try:
        # Check if file exists and if it was recently modified
        if os.path.exists(SIGNALS_FILE):
            curr_mod_time = os.path.getmtime(SIGNALS_FILE)
            time_since_mod = time.time() - curr_mod_time
            
            # If file was recently modified, wait to avoid reading during write
            if time_since_mod < FILE_WRITE_EXCLUSION_PERIOD:
                logger.debug(f"Signals file was modified {time_since_mod:.2f}s ago, waiting to avoid conflict")
                time.sleep(FILE_WRITE_EXCLUSION_PERIOD - time_since_mod)
            
            # Update stored modification time
            file_last_mod_times["signals"] = curr_mod_time
            
            # Check if the signals file is fresh (less than 5 minutes old)
            current_time = time.time()
            file_age = current_time - curr_mod_time
            
            # Increased from 60 seconds to 300 seconds (5 minutes)
            if file_age > 300:  # 5 minutes max age
                logger.warning(f"Signals file is stale: {file_age:.1f} seconds old (older than 5 minutes)")
                return {}
        
        # Use safe_read_json to handle atomic reads
        data, success = safe_read_json(SIGNALS_FILE)
        
        if not success:
            # If read failed, create a new valid file structure
            logger.warning(f"Failed to read signals file, creating new structure")
            empty_data = {}
            if safe_write_json(SIGNALS_FILE, empty_data):
                logger.info(f"Created new signals file with valid structure at {os.path.abspath(SIGNALS_FILE)}")
            else:
                logger.error(f"Failed to create new signals file")
            file_error_counts["signals"] += 1  # Count this as an error
            return {}
        
        # Read succeeded, reset error counter
        file_error_counts["signals"] = 0
        
        # Check if data is a string instead of a dictionary (corrupted file)
        if isinstance(data, str):
            logger.warning(f"Signal data is a string instead of a dictionary. Recreating file structure.")
            try:
                # Try to parse the string as JSON
                parsed_data = json.loads(data)
                if isinstance(parsed_data, dict):
                    logger.info(f"Successfully parsed string data as JSON dictionary")
                    data = parsed_data
                else:
                    logger.error(f"Parsed data is not a dictionary, creating empty structure")
                    data = {}
                    if safe_write_json(SIGNALS_FILE, data):
                        logger.info(f"Created new signals file with valid structure")
                    return data
            except Exception as e:
                logger.error(f"Error parsing string data: {e}")
                data = {}
                if safe_write_json(SIGNALS_FILE, data):
                    logger.info(f"Created new signals file with valid structure")
                return data
        
        # Ensure data is a dictionary
        if not isinstance(data, dict):
            logger.warning(f"Signal data is not a dictionary: {type(data).__name__}, creating empty structure")
            data = {}
            if safe_write_json(SIGNALS_FILE, data):
                logger.info(f"Created new signals file with valid structure")
            return data
        
        # Validate and fix the data structure if needed
        fixed_data = {}
        data_was_fixed = False
        
        # Preserve metadata keys (those starting with underscore)
        for key in list(data.keys()):
            if key.startswith('_'):
                fixed_data[key] = data[key]
        
        # Process regular symbol keys
        for symbol in list(data.keys()):
            # Skip metadata keys (starting with underscore)
            if symbol.startswith('_'):
                continue
                
            signal_data = data[symbol]
            if not isinstance(signal_data, dict):
                logger.warning(f"Signal data for {symbol} is not a dictionary, creating default structure")
                fixed_data[symbol] = {"symbol": symbol, "signal": "NEUTRAL", "timestamp": datetime.now().isoformat()}
                data_was_fixed = True
                continue
                
            # Create a copy to modify
            try:
                fixed_signal = signal_data.copy()
            except AttributeError:
                # Handle the case where signal_data might not be a dict
                logger.warning(f"Invalid signal data for {symbol}: {type(signal_data).__name__}, creating new structure")
                fixed_data[symbol] = {"symbol": symbol, "signal": "NEUTRAL", "timestamp": datetime.now().isoformat()}
                data_was_fixed = True
                continue
            
            # Check if the symbol field is incorrect (contains a signal value)
            if "symbol" in fixed_signal and fixed_signal["symbol"] in ["BUY", "SELL", "NEUTRAL", "PREPARE BUY", "PREPARE SELL"]:
                logger.warning(f"Found incorrect symbol field in {symbol}: {fixed_signal['symbol']}")
                
                # Swap symbol and signal if they're reversed
                if "signal" in fixed_signal and fixed_signal["signal"] not in ["BUY", "SELL", "NEUTRAL", "PREPARE BUY", "PREPARE SELL"]:
                    logger.warning(f"Symbol and signal appear to be swapped for {symbol}, fixing")
                    temp = fixed_signal["symbol"]
                    fixed_signal["symbol"] = symbol
                    fixed_signal["signal"] = temp
                else:
                    # Just fix the symbol field
                    fixed_signal["symbol"] = symbol
                
                data_was_fixed = True
            
            # Ensure symbol field exists and is correct
            if "symbol" not in fixed_signal or fixed_signal["symbol"] != symbol:
                fixed_signal["symbol"] = symbol
                data_was_fixed = True
            
            # Ensure signal field exists
            if "signal" not in fixed_signal:
                fixed_signal["signal"] = "NEUTRAL"  # Default if missing
                data_was_fixed = True
            
            # Ensure timestamp field exists
            if "timestamp" not in fixed_signal:
                fixed_signal["timestamp"] = datetime.now().isoformat()
                data_was_fixed = True
            
            # Add to the fixed data
            fixed_data[symbol] = fixed_signal
        
        # Make sure we have an updated timestamp
        if "_last_update" not in fixed_data:
            fixed_data["_last_update"] = datetime.now().isoformat()
            data_was_fixed = True
        
        # If we fixed any data, save the fixed version
        if data_was_fixed:
            logger.info(f"Fixed corrupted signal data structure, saving corrected version")
            try:
                if safe_write_json(SIGNALS_FILE, fixed_data):
                    logger.info(f"Successfully saved corrected signal data")
                else:
                    logger.error(f"Failed to save corrected signal data")
            except Exception as save_error:
                logger.error(f"Error saving fixed signal data: {save_error}")
            
            return fixed_data
        
        return data
            
    except Exception as e:
        logger.error(f"Error loading signals: {e}")
        # Add more debug information
        try:
            logger.error(f"File exists: {os.path.exists(SIGNALS_FILE)}, Size: {os.path.getsize(SIGNALS_FILE) if os.path.exists(SIGNALS_FILE) else 'N/A'}")
            logger.error(f"Permissions: {oct(os.stat(SIGNALS_FILE).st_mode)[-3:] if os.path.exists(SIGNALS_FILE) else 'N/A'}")
        except Exception as inner_e:
            logger.error(f"Could not get file details: {inner_e}")
        file_error_counts["signals"] += 1  # Count this as an error
        return {}

def check_positions_file():
    """Check if positions file exists and contains data"""
    try:
        data, success = safe_read_json(POSITIONS_FILE)
        if not success:
            logger.warning("Positions file does not exist or could not be read")
            return False
            
        # Check last update time
        last_update = data.get("last_update", "")
        if last_update:
            try:
                update_time = datetime.fromisoformat(last_update)
                now = datetime.now()
                age_seconds = (now - update_time).total_seconds()
                logger.debug(f"Positions file age: {age_seconds:.1f} seconds")
                
                # Log positions only if there's been a change
                positions = data.get("positions", {})
                if positions:
                    position_symbols = list(positions.keys())
                    logger.debug(f"Active positions: {', '.join(position_symbols)}")
            except Exception as e:
                logger.error(f"Error parsing position timestamp: {e}")
        
        return True
    except Exception as e:
        logger.error(f"Error checking positions file: {e}")
        return False

def should_restart(pid):
    """Determine if the monitor process should be restarted"""
    # This function should not try to restart trigger_monitor.py since you're not using it
    return False  # Always return False to prevent restarts

def kill_process(pid):
    """Kill a process by PID"""
    if pid is None:
        return
    
    try:
        process = psutil.Process(pid)
        logger.info(f"Terminating process {pid}")
        process.terminate()
        
        # Wait for process to terminate
        gone, alive = psutil.wait_procs([process], timeout=3)
        if alive:
            logger.warning(f"Process {pid} did not terminate gracefully, killing")
            process.kill()
    except psutil.NoSuchProcess:
        logger.info(f"Process {pid} already gone")
    except Exception as e:
        logger.error(f"Error killing process {pid}: {e}")

def log_signal(signal_data):
    """Log buy/sell signals to history file"""
    try:
        # Only log BUY and SELL signals, skip NEUTRAL
        if signal_data.get("signal") not in ["BUY", "SELL"]:
            return
            
        # Load existing log or create new one
        log_data = {"signals": []}
        data, success = safe_read_json(SIGNAL_LOG_FILE)
        if success:
            log_data = data
        else:
            # Create new log structure if file doesn't exist or is invalid
            logger.debug(f"Creating new signal log structure")
        
        # Add new signal with timestamp
        signal_entry = {
            "timestamp": datetime.now().isoformat(),
            "symbol": signal_data.get("symbol"),
            "signal": signal_data.get("signal"),
            "price": signal_data.get("price"),
            "strength": signal_data.get("strength"),
            "trend": signal_data.get("trend"),
            "timeframes": signal_data.get("timeframes", {}),
            "indicators": signal_data.get("indicators", {})
        }
        
        # Add to signals list
        log_data["signals"].append(signal_entry)
        
        # Keep only last 1000 signals
        if len(log_data["signals"]) > 1000:
            log_data["signals"] = log_data["signals"][-1000:]
        
        # Save updated log using safe_write_json
        if safe_write_json(SIGNAL_LOG_FILE, log_data):
            logger.info(f"Logged {signal_data.get('signal')} signal for {signal_data.get('symbol')}")
        else:
            logger.error(f"Failed to log signal for {signal_data.get('symbol')}")
        
    except Exception as e:
        logger.error(f"Error logging signal: {e}")

def validate_signals():
    """
    DEPRECATED: This function is no longer used with the event-based architecture.
    """
    logger.warning("validate_signals() is deprecated and should not be called")
    return []

def execute_trades(validated_signals):
    """
    DEPRECATED: This function is no longer used with the event-based architecture.
    """
    logger.warning("execute_trades() is deprecated and should not be called")
    return []

def check_signal_triggers():
    """
    DEPRECATED: This function is no longer used with the event-based architecture.
    Use process_signals_change() instead.
    """
    logger.warning("check_signal_triggers() is deprecated and should not be called")
    return []

def get_current_price(symbol):
    """Get the current price for a symbol from available data sources"""
    try:
        # Try to get price from stream_data.json
        data, success = safe_read_json("stream_data.json")
        if success and symbol in data and "ticker" in data[symbol]:
            return data[symbol]["ticker"].get("lastPrice", 0)
        
        # If not found, check signals file
        signals_data, signals_success = safe_read_json(SIGNALS_FILE)
        if signals_success and symbol in signals_data:
            return signals_data[symbol].get("price", 0)
        
        return 0  # Default if price not found
    except Exception as e:
        logger.error(f"Error getting price for {symbol}: {e}")
        return 0

def save_trigger_log(trigger_info):
    """Save trigger information to log file"""
    try:
        # Load existing log or create new one
        log_data = {"triggers": []}
        data, success = safe_read_json(TRIGGER_LOG_FILE)
        if success:
            log_data = data
        else:
            # Create new log structure if file doesn't exist or is invalid
            logger.debug(f"Creating new trigger log structure")
        
        # Add new trigger info
        log_data["triggers"].append(trigger_info)
        
        # Keep only last 100 triggers
        if len(log_data["triggers"]) > 100:
            log_data["triggers"] = log_data["triggers"][-100:]
        
        # Save updated log using safe_write_json
        if not safe_write_json(TRIGGER_LOG_FILE, log_data):
            logger.error(f"Failed to save trigger log")
        
    except Exception as e:
        logger.error(f"Error saving trigger log: {e}")

def log_status(self):
        """Log current watchdog status"""
        try:
            logger.info("===================== WATCHDOG STATUS =====================")
            
            # Get positions directly from API for most accurate data
            positions = {}
            try:
                if trade_manager and hasattr(trade_manager, 'get_active_positions'):
                    positions = trade_manager.get_active_positions()
                    # Also update the positions file
                    update_positions_file(positions)
                    logger.info(f"Updated positions file with {len(positions)} active positions")
                else:
                    # Fall back to file
                    positions_data, success = safe_read_json(POSITIONS_FILE)
                    if success and isinstance(positions_data, dict):
                        positions = positions_data.get("positions", {})
                        logger.info(f"Loaded {len(positions)} positions from file")
            except Exception as e:
                logger.error(f"Error getting positions for status log: {e}")
                # Fall back to file
                positions_data, success = safe_read_json(POSITIONS_FILE)
                if success and isinstance(positions_data, dict):
                    positions = positions_data.get("positions", {})
                    logger.info(f"Loaded {len(positions)} positions from file (fallback)")
            
            # Log active positions
            if positions:
                total_pnl = 0
                total_position_value = 0
                winning_positions = 0
                losing_positions = 0
                position_info = []
                
                # First pass to calculate values for each position
                for symbol, pos in positions.items():
                    # Skip if not a valid position object
                    if not isinstance(pos, dict):
                        logger.warning(f"Invalid position data for {symbol}: {pos}")
                        continue
                    
                    side = pos.get("side", "Unknown")
                    size = float(pos.get("size", "0"))
                    
                    # Get entry price using multiple possible field names
                    entry_price = float(pos.get("entry_price", 
                                    pos.get("avgPrice", 
                                    pos.get("entryPrice", 0))))
                    
                    # Get mark price 
                    mark_price = float(pos.get("mark_price", 
                                  pos.get("markPrice", 0)))
                    
                    # Get position leverage
                    leverage = float(pos.get("leverage", 1))
                    
                    # Calculate position value
                    position_value = size * mark_price
                    total_position_value += position_value
                    
                    # Store value in position for later use
                    pos["position_value"] = position_value
                    
                    # Get PnL information using multiple possible field names
                    unrealized_pnl = float(pos.get("unrealised_pnl", 
                                         pos.get("unrealisedPnl", 
                                         pos.get("unrealized_pnl", 0))))
                    
                    # Update total PnL
                    total_pnl += unrealized_pnl
                    
                    # Calculate price change percentage correctly
                    price_diff_pct = 0
                    if entry_price > 0 and mark_price > 0:
                        if side == "Buy":
                            price_diff_pct = ((mark_price / entry_price) - 1) * 100
                        else:  # Sell
                            price_diff_pct = ((entry_price / mark_price) - 1) * 100
                    
                    # Apply leverage to get actual ROI percentage
                    roi_pct = price_diff_pct * leverage
                    
                    # Store ROI in position for weighted average calculation
                    pos["roi_pct"] = roi_pct
                    
                    # Get PnL percentage using multiple possible field names OR use calculated ROI if unavailable
                    pnl_percentage = pos.get("pnl_percentage", 
                                     pos.get("unrealised_pnl_pct", 
                                     pos.get("unrealizedPnlPct", roi_pct)))
                    
                    # If PnL percentage is available but too different from calculated ROI, use calculated ROI
                    if isinstance(pnl_percentage, (int, float)) and abs(pnl_percentage - roi_pct) > 5:
                        logger.info(f"PnL percentage from API ({pnl_percentage:.2f}%) differs from calculated ROI ({roi_pct:.2f}%). Using calculated ROI.")
                        pnl_percentage = roi_pct
                    
                    # Format PnL percentage for display
                    if isinstance(pnl_percentage, (int, float)):
                        pnl_percentage_display = f"{pnl_percentage:.2f}%"
                    else:
                        pnl_percentage_display = f"{pnl_percentage}"
                    
                    # Update summary stats
                    if unrealized_pnl > 0:
                        winning_positions += 1
                    elif unrealized_pnl < 0:
                        losing_positions += 1
                    
                    # Format the position info with PnL
                    position_info.append(f"{symbol}: {side} {size}@{entry_price} | PnL: {unrealized_pnl:.2f} ({pnl_percentage_display})")
                
                # Calculate weighted average portfolio ROI based on position sizes
                weighted_roi = 0
                if total_position_value > 0:
                    for symbol, pos in positions.items():
                        if not isinstance(pos, dict):
                            continue
                        
                        position_value = pos.get("position_value", 0)
                        roi_pct = pos.get("roi_pct", 0)
                        
                        # Weight ROI by position value
                        position_weight = position_value / total_position_value
                        weighted_roi += roi_pct * position_weight
                
                # Log positions with PnL information
                logger.info(f"Active positions ({len(positions)}): {', '.join(position_info)}")
                
                # Log overall PnL summary
                logger.info(f"Portfolio PnL: ${total_pnl:.2f} ({weighted_roi:.2f}%) | Winning: {winning_positions}, Losing: {losing_positions}")
            else:
                logger.info("No active positions")
            
            # Check signal file
            signals_age = get_signals_file_age()
            if signals_age > 300:  # 5 minutes
                logger.warning(f"Signals file is stale: {signals_age:.1f} seconds old (older than 5 minutes)")
            
        except Exception as e:
            logger.error(f"Error logging status: {e}")
            logger.error(traceback.format_exc())

def check_file_ready(file_path, file_type):
    """
    Check if a file is ready to be read - not currently being written to.
    Returns True if file is ready, False otherwise.
    """
    global file_last_mod_times
    
    try:
        if not os.path.exists(file_path):
            return False
            
        # Get current modification time
        curr_mod_time = os.path.getmtime(file_path)
        last_mod_time = file_last_mod_times.get(file_type, 0)
        
        # If modification time changed, the file might be actively written to
        if curr_mod_time > last_mod_time:
            file_last_mod_times[file_type] = curr_mod_time
            logger.debug(f"{file_path} was modified, waiting for {FILE_WRITE_EXCLUSION_PERIOD}s")
            return False
            
        # Check how much time passed since last modification
        time_since_mod = time.time() - curr_mod_time
        if time_since_mod < FILE_WRITE_EXCLUSION_PERIOD:
            logger.debug(f"{file_path} was modified {time_since_mod:.2f}s ago, not ready")
            return False
            
        # Check file size to make sure it's reasonable
        file_size = os.path.getsize(file_path)
        if file_size < 2:  # Practically empty
            logger.debug(f"{file_path} is empty or too small: {file_size} bytes")
            return False
            
        # File seems ready
        return True
    except Exception as e:
        logger.error(f"Error checking file readiness for {file_path}: {e}")
        return False

# File system event handlers
class PositionsFileHandler(FileSystemEventHandler):
    """
    Handler for file system events on positions file.
    Triggers actions when positions file is modified.
    """
    def __init__(self, callback_fn):
        self.callback_fn = callback_fn
        self.max_consecutive_errors = 3
        self.consecutive_errors = 0
        
    def on_modified(self, event):
        """Called when positions file is modified"""
        if not event.is_directory and os.path.basename(event.src_path) == os.path.basename(POSITIONS_FILE):
            # Check if we're in error cooldown period
            if self.consecutive_errors >= self.max_consecutive_errors:
                if cooldown_tracker.is_in_cooldown('file', 'positions_handler_error'):
                    remaining = cooldown_tracker.get_remaining('file', 'positions_handler_error')
                    logger.warning(f"In error cooldown period for {remaining:.1f} more seconds")
                    return
                else:
                    # Reset error counter after cooldown period
                    self.consecutive_errors = 0
            
            # Ensure we don't process events too frequently (debounce)
            if cooldown_tracker.is_in_cooldown('file', 'positions_handler'):
                remaining = cooldown_tracker.get_remaining('file', 'positions_handler')
                logger.debug(f"Skipping position file change, still in cooldown for {remaining:.1f}s")
                return
                
            logger.debug(f"Positions file changed: {event.src_path}")
            time.sleep(0.5)  # Pause to ensure file write is complete
            cooldown_tracker.set_cooldown('file', 'positions_handler', 5.0)  # 5 second cooldown
            
            try:
                # Execute callback function
                self.callback_fn()
                
                # Reset error counter on success
                if self.consecutive_errors > 0:
                    self.consecutive_errors = 0
                    
            except Exception as e:
                logger.error(f"Error processing positions file change: {e}")
                
                # Track consecutive errors
                self.consecutive_errors += 1
                
                if self.consecutive_errors >= self.max_consecutive_errors:
                    cooldown_tracker.set_cooldown('file', 'positions_handler_error', 30.0)  # 30 second error cooldown
                    logger.warning(f"Too many consecutive errors ({self.consecutive_errors}), entering 30s cooldown")


class SignalsFileHandler(FileSystemEventHandler):
    """
    Handler for file system events on signals file.
    Triggers actions when signals file is modified.
    """
    def __init__(self, callback_fn):
        self.callback_fn = callback_fn
        self.max_consecutive_errors = 3
        self.consecutive_errors = 0
        # Track which signals we've already processed
        self.processed_signals = {}
    
    def on_modified(self, event):
        """Called when signals file is modified"""
        if not event.is_directory and os.path.basename(event.src_path) == os.path.basename(SIGNALS_FILE):
            # Check if we're in error cooldown period
            if self.consecutive_errors >= self.max_consecutive_errors:
                if cooldown_tracker.is_in_cooldown('file', 'signals_handler_error'):
                    remaining = cooldown_tracker.get_remaining('file', 'signals_handler_error')
                    logger.warning(f"In signal file error cooldown period for {remaining:.1f} more seconds")
                    return
                else:
                    # Reset error counter after cooldown period
                    self.consecutive_errors = 0
            
            # Ensure we don't process events too frequently (debounce)
            if cooldown_tracker.is_in_cooldown('file', 'signals_handler'):
                remaining = cooldown_tracker.get_remaining('file', 'signals_handler')
                logger.debug(f"Skipping signal file change, still in cooldown for {remaining:.1f}s")
                return
                
            logger.debug(f"Signals file changed: {event.src_path}")
            time.sleep(0.5)  # Pause to ensure file write is complete
            cooldown_tracker.set_cooldown('file', 'signals_handler', 5.0)  # 5 second cooldown
            
            try:
                # Validate that processed_signals is a dictionary before passing
                if not isinstance(self.processed_signals, dict):
                    logger.warning(f"Invalid processed_signals object: {type(self.processed_signals).__name__}, creating new dictionary")
                    self.processed_signals = {}
                    
                # Execute callback function
                self.callback_fn(self.processed_signals)
                
                # Reset error counter on success
                if self.consecutive_errors > 0:
                    self.consecutive_errors = 0
                    
            except Exception as e:
                logger.error(f"Error processing signals file change: {e}")
                logger.error(traceback.format_exc())
                
                # Track consecutive errors
                self.consecutive_errors += 1
                
                # If there's a persistent error, try resetting the processed_signals tracking
                if self.consecutive_errors >= 2:
                    logger.warning("Multiple consecutive errors, resetting processed_signals tracking")
                    self.processed_signals = {}
                
                if self.consecutive_errors >= self.max_consecutive_errors:
                    cooldown_tracker.set_cooldown('file', 'signals_handler_error', 30.0)  # 30 second error cooldown
                    logger.warning(f"Too many consecutive signals errors ({self.consecutive_errors}), entering 30s cooldown")

def process_positions_change(self):
        """Process changes to the positions file"""
        try:
            # Throttle processing using the centralized cooldown system
            if cooldown_tracker.is_in_cooldown('file', 'position_processing'):
                remaining = cooldown_tracker.get_remaining('file', 'position_processing')
                logger.debug(f"Skipping position processing, in cooldown for {remaining:.1f}s more")
                return
                
            # Set cooldown to prevent frequent processing
            cooldown_tracker.set_cooldown('file', 'position_processing', 10)  # 10 second cooldown
            
            # Get positions from API first
            positions = {}
            try:
                if trade_manager and hasattr(trade_manager, 'get_active_positions'):
                    positions = trade_manager.get_active_positions()
                    if positions:
                        logger.info(f"Found {len(positions)} active positions from API")
                        
                        # Process each position to ensure ROI is calculated correctly
                        for symbol, pos in positions.items():
                            side = pos.get("side", "Unknown")
                            size = pos.get("size", "0")
                            
                            # Get entry price using multiple fields that could contain it
                            entry_price = pos.get("entry_price", 
                                           pos.get("entryPrice", 
                                           pos.get("avgPrice", 0)))
                            
                            # Get mark price
                            mark_price = pos.get("mark_price", 
                                           pos.get("markPrice", 0))
                            
                            # Get position leverage
                            leverage = pos.get("leverage", 1)
                            
                            # Calculate price change percentage
                            price_diff_pct = 0
                            if entry_price > 0 and mark_price > 0:
                                if side == "Buy":
                                    price_diff_pct = ((mark_price / entry_price) - 1) * 100
                                else:  # Sell
                                    price_diff_pct = ((entry_price / mark_price) - 1) * 100
                            
                            # Apply leverage to get actual ROI percentage
                            roi_pct = price_diff_pct * leverage
                            
                            # Update position with correct ROI values
                            pos["roi_pct"] = roi_pct
                            pos["pnl_percentage"] = roi_pct
                                
                            logger.info(f"  Position: {symbol}: {side} {size}@{entry_price} | ROI: {roi_pct:.2f}%")
                    else:
                        # Double check with the exchange in case there's an issue
                        logger.info("No active positions found from API")
                        positions = {}
                else:
                    logger.warning("Trade manager not available for position lookup - using file-based positions")
                    positions = get_active_positions()
            except Exception as e:
                logger.error(f"Error getting positions from API: {e}")
                # Fall back to file-based positions
                positions = get_active_positions()
                
                if not positions:
                    logger.info("No active positions found - nothing to process")
                    return
            
            # Save positions to file for tracking
            update_positions_file(positions)
            
        except Exception as e:
            logger.error(f"Error processing positions change: {e}")
            logger.error(traceback.format_exc())

def process_signals_change(processed_signals=None):
    """Process changes to the signals file"""
    global trade_manager
    
    # Log that signals change detection was triggered
    logger.info("Signal file change detected, processing updated signals")
    
    # Reload trade manager if not available
    if not trade_manager:
        trade_manager = load_trade_manager()
    
    # Default to empty dict if None or not a dictionary
    if processed_signals is None or not isinstance(processed_signals, dict):
        logger.warning(f"Invalid processed_signals parameter: {type(processed_signals).__name__}, using empty dict")
        processed_signals = {}
    
    # Get signals and active positions
    signals_data = get_signal_data()
    if not signals_data:
        logger.error("Error getting signal data")
        return
    
    # Check if signals_data is a string (corrupt JSON)
    if isinstance(signals_data, str):
        logger.error(f"Signals data is a string instead of a dictionary: {signals_data[:100]}...")
        try:
            # Try to recover by creating a fresh signals file
            logger.info("Attempting to recover by creating a fresh signals file")
            signals_data = {"_last_update": datetime.now().isoformat()}
            if safe_write_json(SIGNALS_FILE, signals_data):
                logger.info("Successfully created fresh signals file")
            return  # Exit now and wait for the next file change event
        except Exception as e:
            logger.error(f"Error recovering corrupted signals file: {e}")
            return
    
    active_positions = get_active_positions()
    if active_positions is None:
        logger.error("Error getting active positions")
        return
    
    # Check for stacking trigger flag at the top level
    if "_stack_trigger" in signals_data and isinstance(signals_data["_stack_trigger"], dict):
        stack_trigger = signals_data["_stack_trigger"]
        symbol = stack_trigger.get("symbol")
        signal_type = stack_trigger.get("signal")
        timestamp = stack_trigger.get("timestamp")
        
        logger.info(f"DETECTED STACK TRIGGER: {symbol} {signal_type} at {timestamp}")
        
        # Skip if already processed recently
        stack_id = f"stack_{symbol}_{timestamp}"
        if stack_id in processed_signals:
            logger.info(f"Stack trigger for {symbol} ({timestamp}) already processed, skipping")
        else:
            # Check if we have an active position
            if symbol in active_positions:
                position = active_positions[symbol]
                position_side = position.get("side", "")
                
                # Check if position side matches signal type
                if (position_side == "Buy" and signal_type == "BUY") or (position_side == "Sell" and signal_type == "SELL"):
                    logger.info(f"STACKING: Position {position_side} matches signal {signal_type} for {symbol}")
                    
                    # Check stacking cooldown
                    stacking_cooldown_key = f"stack_{symbol}"
                    if cooldown_tracker.is_in_cooldown('position', stacking_cooldown_key):
                        remaining = cooldown_tracker.get_remaining('position', stacking_cooldown_key)
                        logger.info(f"STACKING COOLDOWN: {symbol} in cooldown for {remaining:.1f} seconds")
                    else:
                        logger.info(f"ATTEMPTING TO STACK POSITION: {symbol} {position_side}")
                        
                        # Attempt to stack the position
                        try:
                            if trade_manager and hasattr(trade_manager, 'calculate_position_size'):
                                position_data = trade_manager.calculate_position_size(symbol, position_side)
                                
                                if position_data:
                                    # Open an additional position in the same direction
                                    if trade_manager and hasattr(trade_manager, 'open_position_parallel'):
                                        result = trade_manager.open_position_parallel(
                                            symbol, 
                                            position_side, 
                                            position_data["formatted_qty"]
                                        )
                                        
                                        if result and (result.get("success", False) or (result.get("multi_account") and result.get("success_count", 0) > 0)):
                                            logger.info(f"🚀 STACK SUCCESS: Stacked {position_side} position for {symbol}")
                                            
                                            # Mark this signal as processed
                                            processed_signals[stack_id] = {
                                                "timestamp": datetime.now().isoformat(),
                                                "status": "STACKED_POSITION",
                                            }
                                            
                                            # Set a cooldown for stacking this position again
                                            stacking_cooldown = 300  # 5 minutes between stack operations
                                            cooldown_tracker.set_cooldown('position', f"stack_{symbol}", stacking_cooldown)
                                            logger.info(f"Set stacking cooldown of {stacking_cooldown} seconds for {symbol}")
                                            
                                            # Update positions file
                                            updated_positions = trade_manager.get_active_positions()
                                            update_positions_file(updated_positions)
                                            logger.info(f"Updated positions file after stacking position")
                                            
                                            # IMPORTANT: Clear the stacking trigger and set signal to NEUTRAL
                                            if "_stack_trigger" in signals_data:
                                                signals_data.pop("_stack_trigger")
                                                logger.info(f"Removed _stack_trigger from signals file")
                                                
                                            if symbol in signals_data:
                                                signals_data[symbol]["signal"] = "NEUTRAL"
                                                signals_data[symbol]["processed_time"] = datetime.now().isoformat()
                                                logger.info(f"Reset {symbol} signal to NEUTRAL to prevent loop")
                                                
                                            # Write the changes back to the file
                                            safe_write_json(SIGNALS_FILE, signals_data)
                                            logger.info(f"Updated signals file after stacking")
                                            
                                            # Clean up any stack flag files
                                            try:
                                                stack_files = [
                                                    f"{SIGNALS_FILE}.stack.{symbol}",
                                                    f"stack_trigger_{symbol}.json",
                                                    f"STACK_{symbol}.flag"
                                                ]
                                                for file in stack_files:
                                                    if os.path.exists(file):
                                                        os.remove(file)
                                                        logger.info(f"Removed stack trigger file: {file}")
                                            except Exception as e:
                                                logger.error(f"Error cleaning up stack files: {e}")
                                        else:
                                            logger.error(f"Failed to stack position for {symbol}")
                                else:
                                    logger.error(f"Failed to calculate position size for stacking {symbol}")
                            else:
                                logger.error(f"Trade manager not available for stacking")
                        except Exception as e:
                            logger.error(f"Error during position stacking: {e}")
                            logger.error(traceback.format_exc())
                else:
                    logger.info(f"Signal type {signal_type} does not match position side {position_side} for {symbol}")
            else:
                logger.info(f"No existing position for {symbol}, cannot stack")
    
    # Check each signal in the file
    for symbol in list(signals_data.keys()):
        # Skip metadata keys that start with underscore
        if symbol.startswith('_'):
            continue
            
        signal_info = signals_data[symbol]
        
        # Check if signal_info is actually a dictionary
        if not isinstance(signal_info, dict):
            logger.warning(f"Invalid signal data for {symbol}: {type(signal_info).__name__}, skipping")
            continue
            
        signal_type = signal_info.get("signal", "NEUTRAL")
        
        # Skip symbols that are marked as processed
        signal_timestamp = signal_info.get("timestamp", "")
        signal_id = f"{symbol}_{signal_type}_{signal_timestamp}"
        
        if signal_id in processed_signals:
            logger.debug(f"Skipping already processed signal {signal_id}")
            continue
        
        # For NEUTRAL signals, we don't take any action
        if signal_type == "NEUTRAL":
            logger.info(f"Neutral signal for {symbol}, no action required")
            processed_signals[signal_id] = {
                "timestamp": datetime.now().isoformat(),
                "status": "SKIPPED_NEUTRAL"
            }
            continue
        
        # Check if we have an active position for this symbol
        has_position = symbol in active_positions
        
        # Log position check results
        logger.info(f"Position check for {symbol}: Has position: {has_position}")
        
        if has_position:
            position = active_positions[symbol]
            position_side = position.get("side", "")
            
            # Compare position side to signal type for matching
            matches_signal = False
            if (position_side == "Buy" and signal_type == "BUY") or (position_side == "Sell" and signal_type == "SELL"):
                matches_signal = True
            
            logger.info(f"Existing position for {symbol}: {position_side}, Signal: {signal_type}, Matches: {matches_signal}")
            
            if matches_signal:
                # Check for stacking cooldown before allowing position stacking
                stacking_cooldown_key = f"stack_{symbol}"
                if cooldown_tracker.is_in_cooldown('position', stacking_cooldown_key):
                    remaining = cooldown_tracker.get_remaining('position', stacking_cooldown_key)
                    logger.info(f"Position stacking for {symbol} is in cooldown. {remaining:.1f} seconds remaining")
                    
                    processed_signals[signal_id] = {
                        "timestamp": datetime.now().isoformat(),
                        "status": "SKIPPED_STACKING_COOLDOWN",
                        "remaining_cooldown": remaining
                    }
                    continue
                
                # Signal matches existing position, stack the position instead of skipping
                logger.info(f"Signal {signal_type} matches existing position {position_side} for {symbol}, checking for stacking opportunity")
                
                # Check special stack flag
                is_stack_signal = signal_info.get("stack_position", False)
                if is_stack_signal:
                    logger.info(f"STACKING FLAG DETECTED for {symbol}")
                    stack_timestamp = signal_info.get("stack_timestamp", "")
                    stack_id = f"stack_{symbol}_{stack_timestamp}"
                    
                    # Skip if already processed this specific stack request
                    if stack_id in processed_signals:
                        logger.info(f"Stack signal for {symbol} ({stack_timestamp}) already processed, skipping")
                        continue
                        
                    # Attempt to stack position
                    try:
                        if trade_manager and hasattr(trade_manager, 'calculate_position_size'):
                            position_data = trade_manager.calculate_position_size(symbol, position_side)
                            
                            if position_data:
                                # Open an additional position in the same direction
                                if trade_manager and hasattr(trade_manager, 'open_position_parallel'):
                                    result = trade_manager.open_position_parallel(
                                        symbol, 
                                        position_side, 
                                        position_data["formatted_qty"]
                                    )
                                    
                                    if result and (result.get("success", False) or (result.get("multi_account") and result.get("success_count", 0) > 0)):
                                        logger.info(f"🚀 STACK SUCCESS: Stacked {position_side} position for {symbol}")
                                        
                                        # Mark this signal as processed
                                        processed_signals[stack_id] = {
                                            "timestamp": datetime.now().isoformat(),
                                            "status": "STACKED_POSITION_FLAG",
                                        }
                                        
                                        # Set a cooldown for stacking this position again
                                        stacking_cooldown = 300  # 5 minutes between stack operations
                                        cooldown_tracker.set_cooldown('position', f"stack_{symbol}", stacking_cooldown)
                                        logger.info(f"Set stacking cooldown of {stacking_cooldown} seconds for {symbol}")
                                        
                                        # Clear the stack flag
                                        signal_info["stack_position"] = False
                                        signal_info["signal"] = "NEUTRAL"  # Reset to neutral
                                        signal_info["processed_time"] = datetime.now().isoformat()
                                        
                                        # Save the changes
                                        safe_write_json(SIGNALS_FILE, signals_data)
                                        logger.info(f"Reset {symbol} signal to NEUTRAL and cleared stack flag")
                                        
                                        # Update positions file
                                        updated_positions = trade_manager.get_active_positions()
                                        update_positions_file(updated_positions)
                                        logger.info(f"Updated positions file after stacking position")
                                        continue
                            else:
                                logger.error(f"Failed to calculate position size for stacking {symbol}")
                        else:
                            logger.error(f"Trade manager not available for stacking via flag")
                    except Exception as e:
                        logger.error(f"Error during flag-based position stacking: {e}")
                        logger.error(traceback.format_exc())
                
                # Continue with normal signal processing with cross check
                # Check cross tracking to determine if this is a new signal from a different EMA cross
                cross_type, is_new_cross, cross_direction = get_signal_cross_type(signal_info)
                
                # Just mark the signal as processed and continue
                processed_signals[signal_id] = {
                    "timestamp": datetime.now().isoformat(),
                    "status": "POSITION_EXISTS_SAME_DIRECTION",
                    "cross_type": cross_type,
                    "is_new_cross": is_new_cross
                }
                
                # If an existing position is in the same direction, we simply mark as processed
                logger.info(f"Existing position for {symbol} is already in the {position_side} direction, marking signal as processed")
                continue
        # New code added here to handle case when there's no existing position for a symbol with BUY/SELL signal 
        else:  # No existing position, this is a new position signal
            # Skip if in opening cooldown
            opening_cooldown_key = f"open_{symbol}"
            if cooldown_tracker.is_in_cooldown('position', opening_cooldown_key):
                remaining = cooldown_tracker.get_remaining('position', opening_cooldown_key)
                logger.info(f"Opening position for {symbol} is in cooldown. {remaining:.1f} seconds remaining")
                
                processed_signals[signal_id] = {
                    "timestamp": datetime.now().isoformat(),
                    "status": "SKIPPED_OPENING_COOLDOWN",
                    "remaining_cooldown": remaining
                }
                continue
            
            # Check if the signal should be traded based on configured filters
            if not should_trade_signal(signal_info):
                logger.info(f"Signal for {symbol} did not pass trading filters, skipping")
                processed_signals[signal_id] = {
                    "timestamp": datetime.now().isoformat(),
                    "status": "FAILED_TRADING_FILTERS"
                }
                continue
            
            # Determine position side from signal type
            position_side = "Buy" if signal_type == "BUY" else "Sell"
            logger.info(f"Opening new {position_side} position for {symbol} based on {signal_type} signal")
            
            # Calculate position size
            try:
                if trade_manager and hasattr(trade_manager, 'calculate_position_size'):
                    position_data = trade_manager.calculate_position_size(symbol, position_side)
                    
                    if position_data:
                        # Open the position
                        if trade_manager and hasattr(trade_manager, 'open_position_parallel'):
                            result = trade_manager.open_position_parallel(
                                symbol, 
                                position_side, 
                                position_data["formatted_qty"]
                            )
                            
                            if result and (result.get("success", False) or (result.get("multi_account") and result.get("success_count", 0) > 0)):
                                logger.info(f"🚀 POSITION OPENED: New {position_side} position for {symbol}")
                                
                                # Mark this signal as processed
                                processed_signals[signal_id] = {
                                    "timestamp": datetime.now().isoformat(),
                                    "status": "NEW_POSITION_OPENED",
                                }
                                
                                # Set a cooldown for opening another position for this symbol
                                opening_cooldown = 300  # 5 minutes between new position operations
                                cooldown_tracker.set_cooldown('position', opening_cooldown_key, opening_cooldown)
                                logger.info(f"Set opening cooldown of {opening_cooldown} seconds for {symbol}")
                                
                                # Update the signal to NEUTRAL to prevent duplicate orders
                                signal_info["signal"] = "NEUTRAL"
                                signal_info["processed_time"] = datetime.now().isoformat()
                                signal_info["processed"] = True
                                
                                # Save the updated signals
                                safe_write_json(SIGNALS_FILE, signals_data)
                                logger.info(f"Reset {symbol} signal to NEUTRAL after opening position")
                                
                                # Update positions file
                                updated_positions = trade_manager.get_active_positions()
                                update_positions_file(updated_positions)
                                logger.info(f"Updated positions file after opening new position")
                                continue
                            else:
                                error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else "Failed to open position"
                                logger.error(f"Failed to open position for {symbol}: {error_msg}")
                                
                                # Mark signal as failed
                                processed_signals[signal_id] = {
                                    "timestamp": datetime.now().isoformat(),
                                    "status": "POSITION_OPEN_FAILED",
                                    "error": error_msg
                                }
                        else:
                            logger.error(f"Trade manager does not have open_position method")
                    else:
                        logger.error(f"Failed to calculate position size for {symbol}")
                else:
                    logger.error(f"Trade manager not available for opening position")
            except Exception as e:
                logger.error(f"Error opening new position for {symbol}: {e}")
                logger.error(traceback.format_exc())
                
                # Mark signal as errored
                processed_signals[signal_id] = {
                    "timestamp": datetime.now().isoformat(),
                    "status": "POSITION_OPEN_ERROR",
                    "error": str(e)
                }

def update_positions_file(positions):
    """
    Update the positions file with the given positions data
    
    Args:
        positions (dict): Dictionary of active positions
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure proper PnL percentage calculation for each position
        for symbol, pos in positions.items():
            # Skip if not a valid position object
            if not isinstance(pos, dict):
                logger.warning(f"Invalid position data for {symbol}: {pos}")
                continue
                
            side = pos.get("side", "Unknown")
            
            # Get entry and mark prices
            entry_price = pos.get("entry_price", 
                            pos.get("avgPrice", 
                            pos.get("entryPrice", 0)))
            
            mark_price = pos.get("mark_price", 
                          pos.get("markPrice", 0))
            
            leverage = pos.get("leverage", 1)
            
            # Calculate price change percentage
            price_diff_pct = 0
            if entry_price > 0 and mark_price > 0:
                if side == "Buy":
                    price_diff_pct = ((mark_price / entry_price) - 1) * 100
                else:  # Sell
                    price_diff_pct = ((entry_price / mark_price) - 1) * 100
            
            # Apply leverage to get actual ROI percentage
            roi_pct = price_diff_pct * leverage
            
            # Update position data with correct ROI
            pos["roi_pct"] = roi_pct
            pos["pnl_percentage"] = roi_pct  # Use same value for both fields
            
            logger.debug(f"Updated {symbol} ROI: {roi_pct:.2f}%")
        
        # Create a clean positions file structure
        positions_data = {
            "positions": positions,
            "last_update": datetime.now().isoformat()
        }
        
        # Save to file
        if safe_write_json(POSITIONS_FILE, positions_data):
            logger.info(f"Updated positions file with {len(positions)} active positions")
            return True
        else:
            logger.error("Failed to update positions file")
            return False
    except Exception as e:
        logger.error(f"Error updating positions file: {e}")
        return False

def refresh_positions_at_startup():
    """
    Get fresh positions data from the API and update the positions file at startup
    
    Returns:
        dict: Dictionary of active positions
    """
    try:
        logger.info("Refreshing positions data at startup")
        
        # Get positions from the API
        positions = {}
        if trade_manager and hasattr(trade_manager, 'get_active_positions'):
            positions = trade_manager.get_active_positions()
            if positions:
                logger.info(f"Found {len(positions)} active positions from API during startup")
                
                # Log details about existing positions
                for symbol, position in positions.items():
                    side = position.get("side", "Unknown")
                    size = position.get("size", "0")
                    entry = position.get("entryPrice", position.get("entry_price", "0"))
                    logger.info(f"  Active position on startup: {symbol}: {side} {size}@{entry}")
                
                # Update positions file with fresh data
                update_positions_file(positions)
            else:
                logger.info("No active positions found - creating empty positions file")
                update_positions_file({})
        else:
            logger.warning("Trade manager not available - cannot refresh positions")
            
        return positions
    except Exception as e:
        logger.error(f"Error refreshing positions at startup: {e}")
        return {}

def log_signal_summary():
    """Log a summary of current trading signals"""
    try:
        signals = get_signal_data()
        if not signals:
            logger.info("Signal summary: No signals found")
            return
            
        # Count by signal type
        signal_counts = {"BUY": 0, "SELL": 0, "NEUTRAL": 0, "PREPARE BUY": 0, "PREPARE SELL": 0, "OTHER": 0}
        
        # Track actionable signals
        actionable_signals = []
        
        # Process signals
        for symbol, data in signals.items():
            signal = data.get("signal", "NEUTRAL")
            
            # Update counts
            if signal in signal_counts:
                signal_counts[signal] += 1
            else:
                signal_counts["OTHER"] += 1
                
            # Track actionable signals
            if signal in ["BUY", "SELL"]:
                price = data.get("price", 0)
                trend = data.get("trend", "Unknown")
                actionable_signals.append(f"{symbol} ({signal}, {trend}, ${price})")
        
        # Log summary
        summary = ", ".join([f"{k}: {v}" for k, v in signal_counts.items() if v > 0])
        logger.info(f"Signal summary: {summary}")
        
        # Log actionable signals if any
        if actionable_signals:
            logger.info(f"Actionable signals: {', '.join(actionable_signals)}")
    except Exception as e:
        logger.error(f"Error logging signal summary: {e}")

def calculate_volatility(prices):
    """Calculate price volatility as percentage"""
    if len(prices) < 2:
        return 0
        
    # Calculate price changes as percentages
    changes = []
    for i in range(1, len(prices)):
        if prices[i-1] != 0:  # Avoid division by zero
            change = ((prices[i] - prices[i-1]) / prices[i-1]) * 100
            changes.append(abs(change))
    
    if not changes:
        return 0
        
    # Calculate average volatility
    return sum(changes) / len(changes)

def get_signal_cross_type(signal_info):
    """
    Extract the cross type that generated a signal
    
    Args:
        signal_info (dict): The signal information
        
    Returns:
        tuple: (cross_type, is_new_cross, cross_direction)
            - cross_type: String identifier like "ema12_21", "price_50", etc.
            - is_new_cross: Boolean indicating if this is a new crossover
            - cross_direction: "bullish" or "bearish"
    """
    # Default values
    cross_type = None
    is_new_cross = False
    cross_direction = None
    
    # Check if signal has direct cross_type information
    if "cross_type" in signal_info:
        cross_type = signal_info.get("cross_type")
        is_new_cross = signal_info.get("crossover_detected", False)
        cross_direction = signal_info.get("crossover_direction")
        return cross_type, is_new_cross, cross_direction
    
    # Try to get cross info from crossovers data
    if "crossovers" in signal_info:
        # Get the first timeframe's crossover info (usually there's only one)
        timeframe = next(iter(signal_info["crossovers"]), None)
        if timeframe:
            cross_info = signal_info["crossovers"][timeframe]
            cross_type = cross_info.get("cross_type")
            cross_direction = cross_info.get("direction")
            
            # Check if this is a recent cross
            cross_time_str = cross_info.get("time")
            if cross_time_str:
                try:
                    cross_time = datetime.fromisoformat(cross_time_str)
                    # Consider it a new cross if it happened in the last 5 minutes
                    is_new_cross = (datetime.now() - cross_time).total_seconds() < 300
                except (ValueError, TypeError):
                    pass
    
    # Try to get info from cross_tracking
    if not cross_type and "cross_tracking" in signal_info:
        # Look for the most recently active cross
        most_recent_time = None
        for ct_key, ct_data in signal_info["cross_tracking"].items():
            if ct_data.get("active", False) and ct_data.get("direction") in ["bullish", "bearish"]:
                last_cross_time_str = ct_data.get("last_cross_time")
                if last_cross_time_str:
                    try:
                        last_cross_time = datetime.fromisoformat(last_cross_time_str)
                        if most_recent_time is None or last_cross_time > most_recent_time:
                            most_recent_time = last_cross_time
                            cross_type = ct_key
                            cross_direction = ct_data.get("direction")
                            is_new_cross = (datetime.now() - last_cross_time).total_seconds() < 300
                    except (ValueError, TypeError):
                        pass
    
    return cross_type, is_new_cross, cross_direction

def should_trade_signal(signal_data):
    """
    Check if a signal should be traded - only checks if it's BUY or SELL
    """
    # Extract the signal and symbol for logging
    signal = signal_data.get("signal", "NEUTRAL")
    symbol = signal_data.get("symbol", "Unknown")
    
    # Log what we're evaluating
    logger.info(f"Evaluating signal for {symbol}: Signal={signal}")
    
    # Skip neutral signals
    if signal == "NEUTRAL":
        logger.info(f"{symbol}: Signal is NEUTRAL, skipping")
        return False
    
    # Only accept BUY or SELL signals, nothing else matters
    if signal in ["BUY", "SELL"]:
        logger.info(f"{symbol}: Signal APPROVED for trading - {signal}")
        return True
    
    # Any other signals are rejected
    logger.info(f"{symbol}: Signal rejected - Not a BUY or SELL signal")
    return False

# Add this class wrapper around the core functionality

class TradingWatchdog:
    def __init__(self):
        # Initialize any required variables
        self.running = False
        self.observer = None
        self.observer_active = False
        self.positions_handler = None
        self.signals_handler = None
        
        # Set interval durations for status logging only
        self.status_log_interval = 300  # 5 minutes between status logs
        
        # Check file permissions on initialization
        self.check_and_fix_file_permissions()
        
        # Initialize cooldowns for periodic tasks
        cooldown_tracker.set_cooldown('check', 'status_log', 0)  # Allow immediate first log
        
        logger.info("TradingWatchdog instance initialized with event-based monitoring")
    
    def check_and_fix_file_permissions(self):
        """Check and fix file permissions for critical files"""
        files_to_check = [POSITIONS_FILE, SIGNALS_FILE, "stream_data.json"]
        
        for file in files_to_check:
            # Create the file if it doesn't exist
            if not os.path.exists(file):
                try:
                    logger.info(f"Creating missing file: {file}")
                    
                    if file == POSITIONS_FILE:
                        data = {"positions": {}, "last_update": datetime.now().isoformat()}
                    else:
                        data = {}
                    
                    if safe_write_json(file, data):
                        logger.info(f"Successfully created {file}")
                    else:
                        logger.error(f"Failed to create {file}")
                except Exception as e:
                    logger.error(f"Error creating {file}: {e}")
            
            # Check if file is writable
            try:
                # Try to open in append mode to verify we can write
                with open(file, 'a') as f:
                    pass
                logger.info(f"File {file} is accessible and writable")
            except PermissionError:
                try:
                    # Try to fix permissions
                    logger.warning(f"Fixing permissions for {file}")
                    os.chmod(file, 0o666)  # Set to read/write for everyone
                    logger.info(f"Fixed permissions for {file}")
                except Exception as e:
                    logger.error(f"Failed to fix permissions for {file}: {e}")
            except Exception as e:
                logger.error(f"Error checking permissions for {file}: {e}")
        
        logger.info("File permission check completed")
    
    def process_positions_change(self):
        """Process changes to the positions file"""
        try:
            # Throttle processing using the centralized cooldown system
            if cooldown_tracker.is_in_cooldown('file', 'position_processing'):
                remaining = cooldown_tracker.get_remaining('file', 'position_processing')
                logger.debug(f"Skipping position processing, in cooldown for {remaining:.1f}s more")
                return
                
            # Set cooldown to prevent frequent processing
            cooldown_tracker.set_cooldown('file', 'position_processing', 10)  # 10 second cooldown
            
            # Get positions from API first
            positions = {}
            try:
                if trade_manager and hasattr(trade_manager, 'get_active_positions'):
                    positions = trade_manager.get_active_positions()
                    if positions:
                        logger.info(f"Found {len(positions)} active positions from API")
                        
                        # Process each position to ensure ROI is calculated correctly
                        for symbol, pos in positions.items():
                            side = pos.get("side", "Unknown")
                            size = pos.get("size", "0")
                            
                            # Get entry price using multiple fields that could contain it
                            entry_price = pos.get("entry_price", 
                                           pos.get("entryPrice", 
                                           pos.get("avgPrice", 0)))
                            
                            # Get mark price
                            mark_price = pos.get("mark_price", 
                                           pos.get("markPrice", 0))
                            
                            # Get position leverage
                            leverage = pos.get("leverage", 1)
                            
                            # Calculate price change percentage
                            price_diff_pct = 0
                            if entry_price > 0 and mark_price > 0:
                                if side == "Buy":
                                    price_diff_pct = ((mark_price / entry_price) - 1) * 100
                                else:  # Sell
                                    price_diff_pct = ((entry_price / mark_price) - 1) * 100
                            
                            # Apply leverage to get actual ROI percentage
                            roi_pct = price_diff_pct * leverage
                            
                            # Update position with correct ROI values
                            pos["roi_pct"] = roi_pct
                            pos["pnl_percentage"] = roi_pct
                                
                            logger.info(f"  Position: {symbol}: {side} {size}@{entry_price} | ROI: {roi_pct:.2f}%")
                    else:
                        # Double check with the exchange in case there's an issue
                        logger.info("No active positions found from API")
                        positions = {}
                else:
                    logger.warning("Trade manager not available for position lookup - using file-based positions")
                    positions = get_active_positions()
            except Exception as e:
                logger.error(f"Error getting positions from API: {e}")
                # Fall back to file-based positions
                positions = get_active_positions()
                
                if not positions:
                    logger.info("No active positions found - nothing to process")
                    return
            
            # Save positions to file for tracking
            update_positions_file(positions)
            
        except Exception as e:
            logger.error(f"Error processing positions change: {e}")
            logger.error(traceback.format_exc())
    
    def log_status(self):
        """Log current watchdog status"""
        try:
            logger.info("===================== WATCHDOG STATUS =====================")
            
            # Get positions directly from API for most accurate data
            positions = {}
            try:
                if trade_manager and hasattr(trade_manager, 'get_active_positions'):
                    positions = trade_manager.get_active_positions()
                    # Also update the positions file
                    update_positions_file(positions)
                    logger.info(f"Updated positions file with {len(positions)} active positions")
                else:
                    # Fall back to file
                    positions_data, success = safe_read_json(POSITIONS_FILE)
                    if success and isinstance(positions_data, dict):
                        positions = positions_data.get("positions", {})
                        logger.info(f"Loaded {len(positions)} positions from file")
            except Exception as e:
                logger.error(f"Error getting positions for status log: {e}")
                # Fall back to file
                positions_data, success = safe_read_json(POSITIONS_FILE)
                if success and isinstance(positions_data, dict):
                    positions = positions_data.get("positions", {})
                    logger.info(f"Loaded {len(positions)} positions from file (fallback)")
            
            # Log active positions
            if positions:
                total_pnl = 0
                total_position_value = 0
                winning_positions = 0
                losing_positions = 0
                position_info = []
                
                # First pass to calculate values for each position
                for symbol, pos in positions.items():
                    # Skip if not a valid position object
                    if not isinstance(pos, dict):
                        logger.warning(f"Invalid position data for {symbol}: {pos}")
                        continue
                    
                    side = pos.get("side", "Unknown")
                    size = float(pos.get("size", "0"))
                    
                    # Get entry price using multiple possible field names
                    entry_price = float(pos.get("entry_price", 
                                    pos.get("avgPrice", 
                                    pos.get("entryPrice", 0))))
                    
                    # Get mark price 
                    mark_price = float(pos.get("mark_price", 
                                  pos.get("markPrice", 0)))
                    
                    # Get position leverage
                    leverage = float(pos.get("leverage", 1))
                    
                    # Calculate position value
                    position_value = size * mark_price
                    total_position_value += position_value
                    
                    # Store value in position for later use
                    pos["position_value"] = position_value
                    
                    # Get PnL information using multiple possible field names
                    unrealized_pnl = float(pos.get("unrealised_pnl", 
                                         pos.get("unrealisedPnl", 
                                         pos.get("unrealized_pnl", 0))))
                    
                    # Update total PnL
                    total_pnl += unrealized_pnl
                    
                    # Calculate price change percentage correctly
                    price_diff_pct = 0
                    if entry_price > 0 and mark_price > 0:
                        if side == "Buy":
                            price_diff_pct = ((mark_price / entry_price) - 1) * 100
                        else:  # Sell
                            price_diff_pct = ((entry_price / mark_price) - 1) * 100
                    
                    # Apply leverage to get actual ROI percentage
                    roi_pct = price_diff_pct * leverage
                    
                    # Store ROI in position for weighted average calculation
                    pos["roi_pct"] = roi_pct
                    
                    # Get PnL percentage using multiple possible field names OR use calculated ROI if unavailable
                    pnl_percentage = pos.get("pnl_percentage", 
                                     pos.get("unrealised_pnl_pct", 
                                     pos.get("unrealizedPnlPct", roi_pct)))
                    
                    # If PnL percentage is available but too different from calculated ROI, use calculated ROI
                    if isinstance(pnl_percentage, (int, float)) and abs(pnl_percentage - roi_pct) > 5:
                        logger.info(f"PnL percentage from API ({pnl_percentage:.2f}%) differs from calculated ROI ({roi_pct:.2f}%). Using calculated ROI.")
                        pnl_percentage = roi_pct
                    
                    # Format PnL percentage for display
                    if isinstance(pnl_percentage, (int, float)):
                        pnl_percentage_display = f"{pnl_percentage:.2f}%"
                    else:
                        pnl_percentage_display = f"{pnl_percentage}"
                    
                    # Update summary stats
                    if unrealized_pnl > 0:
                        winning_positions += 1
                    elif unrealized_pnl < 0:
                        losing_positions += 1
                    
                    # Format the position info with PnL
                    position_info.append(f"{symbol}: {side} {size}@{entry_price} | PnL: {unrealized_pnl:.2f} ({pnl_percentage_display})")
                
                # Calculate weighted average portfolio ROI based on position sizes
                weighted_roi = 0
                if total_position_value > 0:
                    for symbol, pos in positions.items():
                        if not isinstance(pos, dict):
                            continue
                        
                        position_value = pos.get("position_value", 0)
                        roi_pct = pos.get("roi_pct", 0)
                        
                        # Weight ROI by position value
                        position_weight = position_value / total_position_value
                        weighted_roi += roi_pct * position_weight
                
                # Log positions with PnL information
                logger.info(f"Active positions ({len(positions)}): {', '.join(position_info)}")
                
                # Log overall PnL summary
                logger.info(f"Portfolio PnL: ${total_pnl:.2f} ({weighted_roi:.2f}%) | Winning: {winning_positions}, Losing: {losing_positions}")
            else:
                logger.info("No active positions")
            
            # Check signal file
            signals_age = get_signals_file_age()
            if signals_age > 300:  # 5 minutes
                logger.warning(f"Signals file is stale: {signals_age:.1f} seconds old (older than 5 minutes)")
            
        except Exception as e:
            logger.error(f"Error logging status: {e}")
            logger.error(traceback.format_exc())
    
    def setup_observers(self):
        """Setup file system observers"""
        try:
            if self.observer_active:
                try:
                    self.observer.stop()
                    self.observer.join(timeout=5.0)
                except:
                    pass
            
            self.observer = Observer()
            self.positions_handler = PositionsFileHandler(callback_fn=self.process_positions_change)
            self.observer.schedule(self.positions_handler, path=os.path.dirname(os.path.abspath(POSITIONS_FILE)), recursive=False)
            self.signals_handler = SignalsFileHandler(callback_fn=process_signals_change)
            self.observer.schedule(self.signals_handler, path=os.path.dirname(os.path.abspath(SIGNALS_FILE)), recursive=False)
            self.observer.start()
            self.observer_active = True
            logger.info("Successfully started file system observers")
            return True
        except Exception as e:
            logger.error(f"Failed to setup observers: {e}")
            self.observer_active = False
            return False
        
    def main_loop(self):
        """Main monitoring loop"""
        self.running = True
        
        # Start with a status log
        self.log_status()
        
        logger.info("Starting main monitoring loop")
        
        try:
            # Setup watchers for file changes
            self.setup_observers()
            
            # Initialize or refresh signals file at startup if needed
            if initialize_or_refresh_signals_file():
                logger.info("Initialized signals file at startup")
            
            # Main loop
            while self.running:
                try:
                    # Check for stack triggers
                    check_for_stack_triggers()
                    
                    # Sleep briefly to avoid high CPU usage
                    time.sleep(1)
                    
                    # Check if it's time for a status log update
                    if not cooldown_tracker.is_in_cooldown('check', 'status_log'):
                        self.log_status()
                        cooldown_tracker.set_cooldown('check', 'status_log', self.status_log_interval)
                    
                    # Periodically check if signals file needs refresh (every 5 minutes)
                    if not cooldown_tracker.is_in_cooldown('check', 'signals_refresh'):
                        initialize_or_refresh_signals_file()
                        cooldown_tracker.set_cooldown('check', 'signals_refresh', 300)  # 5 minutes
                    
                    # In the main_loop method
                    if not cooldown_tracker.is_in_cooldown('check', 'cooldown_sync'):
                        synchronize_cooldowns()
                        cooldown_tracker.set_cooldown('check', 'cooldown_sync', 60)  # Sync every minute
                    
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    logger.error(traceback.format_exc())
                    time.sleep(5)  # Sleep longer on error
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt detected, shutting down...")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            logger.error(traceback.format_exc())
        finally:
            # Cleanup
            if self.observer and self.observer.is_alive():
                self.observer.stop()
                self.observer.join()
                logger.info("File observers stopped")
            
            self.running = False
            logger.info("Trading watchdog stopped")

def check_for_stack_triggers():
    """Check for position stacking trigger files"""
    logger.info("Checking for stack trigger files")
    
    # Define the patterns to check for
    patterns = [
        f"{SIGNALS_FILE}.stack.*",
        "stack_trigger_*.json",
        "STACK_*.flag"
    ]
    
    found_triggers = []
    
    # Look for each pattern of stack trigger files
    for pattern in patterns:
        matching_files = glob.glob(pattern)
        for trigger_file in matching_files:
            try:
                # Extract symbol from the filename
                symbol = None
                if trigger_file.startswith(f"{SIGNALS_FILE}.stack."):
                    symbol = trigger_file.split(".")[-1]
                elif trigger_file.startswith("stack_trigger_") and trigger_file.endswith(".json"):
                    symbol = trigger_file[14:-5]  # Extract between stack_trigger_ and .json
                elif trigger_file.startswith("STACK_") and trigger_file.endswith(".flag"):
                    symbol = trigger_file[6:-5]  # Extract between STACK_ and .flag
                
                logger.info(f"Found stack trigger for {symbol}: {trigger_file}")
                
                # Get the trigger data if available
                threshold = None
                side = None
                
                # Load the JSON content if it's a JSON file
                if trigger_file.endswith(".json"):
                    try:
                        with open(trigger_file, "r") as f:
                            trigger_data = json.load(f)
                            if "threshold" in trigger_data:
                                threshold = float(trigger_data["threshold"])
                            if "side" in trigger_data:
                                side = trigger_data["side"]
                            elif "signal" in trigger_data:
                                side = trigger_data["signal"]
                    except Exception as e:
                        logger.error(f"Error reading trigger file {trigger_file}: {e}")
                        # Delete invalid trigger file
                        os.remove(trigger_file)
                        continue
                
                logger.info(f"Processing stack for {symbol} (threshold: {threshold}%, side: {side})")
                
                # Load positions data
                positions_data = {}
                if os.path.exists(POSITIONS_FILE):
                    with open(POSITIONS_FILE, "r") as f:
                        positions_data = json.load(f)
                
                # If no positions data available or symbol not in positions, skip
                if not positions_data or symbol not in positions_data.get("positions", {}):
                    logger.error(f"No position data found for {symbol}, cannot stack")
                    # Remove the trigger file since we can't process it
                    os.remove(trigger_file)
                    continue
                
                # Get position details
                position = positions_data["positions"][symbol]
                
                # Get position side from position data if not set in trigger
                if not side:
                    side = position.get("side")
                    if not side:
                        logger.error(f"No side information for {symbol}, cannot stack")
                        os.remove(trigger_file)
                        continue
                
                # Check if this threshold has already been triggered for this position
                if "stacking" in position:
                    triggered_thresholds = position["stacking"].get("triggered_thresholds", [])
                    if threshold is not None and threshold in triggered_thresholds:
                        logger.warning(f"Threshold {threshold}% already triggered for {symbol}, skipping")
                        os.remove(trigger_file)
                        continue
                
                # Determine signal type based on position side
                signal_type = "BUY" if side == "Buy" else "SELL"
                
                # Check cooldown
                if os.path.exists("cooldowns.json"):
                    try:
                        with open("cooldowns.json", "r") as f:
                            cooldowns = json.load(f)
                        
                        if "stacking" in cooldowns and symbol in cooldowns["stacking"]:
                            expiry_time = datetime.fromisoformat(cooldowns["stacking"][symbol])
                            if datetime.now() < expiry_time:
                                time_left = (expiry_time - datetime.now()).total_seconds()
                                logger.warning(f"Symbol {symbol} is in stacking cooldown for {time_left:.1f} seconds, skipping")
                                continue
                    except Exception as cooldown_error:
                        logger.error(f"Error checking cooldown: {cooldown_error}")
                
                # Stack the position
                logger.info(f"Stacking {side} position for {symbol} at threshold {threshold}%")
                
                try:
                    # Import the stack_position function from trade_manager
                    from trade_manager import stack_position
                    
                    # Call the function directly
                    stack_result = stack_position(symbol, signal_type)
                    
                    if stack_result and stack_result.get("success") == True:
                        logger.info(f"Successfully stacked position for {symbol}")
                        
                        # Update position tracking for stacking
                        if "stacking" not in position:
                            position["stacking"] = {
                                "triggered_thresholds": [],
                                "stack_count": 0,
                                "last_stack_time": None
                            }
                        
                        # Add threshold to triggered list if not already there
                        if threshold is not None and threshold not in position["stacking"].get("triggered_thresholds", []):
                            position["stacking"]["triggered_thresholds"] = position["stacking"].get("triggered_thresholds", []) + [threshold]
                        
                        # Update stack count and time
                        position["stacking"]["stack_count"] = position["stacking"].get("stack_count", 0) + 1
                        position["stacking"]["last_stack_time"] = datetime.now().isoformat()
                        
                        # Save updated position data
                        positions_data["positions"][symbol] = position
                        safe_write_json(POSITIONS_FILE, positions_data)
                        logger.info(f"Updated positions file for {symbol} after stacking")
                        
                        # Send notification
                        try:
                            notification_message = f"{symbol} position stacked at {threshold}% ROI\nNew size: {stack_result.get('qty', 'unknown')}\nNew entry: {stack_result.get('entry_price', 'unknown')}"
                            send_telegram_message(f"✅ Position Stacked: {symbol}", notification_message)
                        except Exception as notify_error:
                            logger.error(f"Error sending stack notification: {notify_error}")
                    else:
                        error_msg = stack_result.get("message", "Unknown error") if stack_result else "Stack function failed"
                        logger.error(f"Failed to stack position: {error_msg}")
                except Exception as e:
                    logger.error(f"Error stacking position for {symbol}: {e}")
                    logger.error(traceback.format_exc())
                
                # Remove the trigger file to prevent reprocessing
                os.remove(trigger_file)
                logger.info(f"Removed stack trigger file: {trigger_file}")
                
                # Set a cooldown
                try:
                    if os.path.exists("cooldowns.json"):
                        with open("cooldowns.json", "r") as f:
                            cooldowns = json.load(f)
                    else:
                        cooldowns = {}
                    
                    if "stacking" not in cooldowns:
                        cooldowns["stacking"] = {}
                    
                    # Set 5 minute cooldown after stacking
                    cooldown_expiry = (datetime.now() + timedelta(minutes=5)).isoformat()
                    cooldowns["stacking"][symbol] = cooldown_expiry
                    
                    with open("cooldowns.json", "w") as f:
                        json.dump(cooldowns, f, indent=2)
                    
                    logger.info(f"Set stacking cooldown for {symbol} (5 minutes)")
                except Exception as cooldown_error:
                    logger.error(f"Error setting cooldown after stacking: {cooldown_error}")
                
            except Exception as e:
                logger.error(f"Error processing stack trigger: {e}")
                logger.error(traceback.format_exc())
                
                # Remove the trigger file to prevent endless retries
                try:
                    os.remove(trigger_file)
                    logger.info(f"Removed problematic stack trigger file: {trigger_file}")
                except Exception as rm_error:
                    logger.error(f"Could not remove trigger file: {rm_error}")

def cleanup_all_trigger_files(symbol):
    """Remove all stack trigger files for a specific symbol"""
    try:
        # Define all patterns to check (expanded)
        patterns = [
            f"{SIGNALS_FILE}.stack.{symbol}",
            f"stack_trigger_{symbol}.json",
            f"STACK_{symbol}.flag",
            f"*stack*{symbol}*",  # More aggressive pattern
            f"*{symbol}*stack*"   # Alternative pattern
        ]
        
        # Find and remove all matching files
        for pattern in patterns:
            matching_files = glob.glob(pattern)
            for file_path in matching_files:
                try:
                    os.remove(file_path)
                    logger.info(f"Removed stack trigger file during cleanup: {file_path}")
                except Exception as e:
                    logger.error(f"Error removing file during cleanup: {file_path} - {e}")
        
        # Also ensure the signal is reset to NEUTRAL
        signals_data = get_signal_data()
        if signals_data and symbol in signals_data:
            signals_data[symbol]["signal"] = "NEUTRAL"
            signals_data[symbol]["processed_time"] = datetime.now().isoformat()
            signals_data[symbol]["stack_position"] = False
            safe_write_json(SIGNALS_FILE, signals_data)
            logger.info(f"Reset {symbol} signal to NEUTRAL during cleanup")
            
    except Exception as e:
        logger.error(f"Error in cleanup_all_trigger_files for {symbol}: {e}")

def get_signals_file_age():
    """Get the age of the signals file in seconds"""
    try:
        if os.path.exists(SIGNALS_FILE):
            file_mtime = os.path.getmtime(SIGNALS_FILE)
            current_time = time.time()
            return current_time - file_mtime
        else:
            return float('inf')  # Return infinity if file doesn't exist
    except Exception as e:
        logger.error(f"Error checking signals file age: {e}")
        return float('inf')  # Return infinity on error

def initialize_or_refresh_signals_file():
    """
    Create a fresh signals file if it doesn't exist or is stale
    Returns whether the file was refreshed
    """
    try:
        file_age = get_signals_file_age()
        if file_age > 300 or file_age == float('inf'):  # Older than 5 minutes or doesn't exist
            logger.info(f"Signals file is stale ({file_age:.1f} seconds old) or missing, creating a fresh one")
            
            # Get list of configured symbols
            symbols = []
            try:
                config_data, success = safe_read_json(CONFIG_FILE)
                if success and isinstance(config_data, dict):
                    symbols = config_data.get("symbol_config", {}).keys()
                    logger.info(f"Got {len(symbols)} symbols from config file")
            except Exception as e:
                logger.error(f"Error reading config file: {e}")
            
            # Fallback to using active positions if no symbols from config
            if not symbols and trade_manager:
                positions = trade_manager.get_active_positions()
                symbols = positions.keys()
                logger.info(f"Using {len(symbols)} symbols from active positions")
            
            # Create signals file with neutral signals for all symbols
            signals_data = {}
            current_time = datetime.now().isoformat()
            
            for symbol in symbols:
                signals_data[symbol] = {
                    "timestamp": current_time,
                    "symbol": symbol,
                    "signal": "NEUTRAL",
                    "confidence": 0,
                    "processed_time": current_time,
                    "processed": True,
                    "stack_position": False
                }
            
            # Save the signals file
            if signals_data:
                safe_write_json(SIGNALS_FILE, signals_data)
                logger.info(f"Created fresh signals file with {len(signals_data)} symbols set to NEUTRAL")
                return True
            else:
                logger.warning("No symbols found to initialize signals file")
        else:
            logger.debug(f"Signals file is fresh ({file_age:.1f} seconds old)")
        
        return False
    except Exception as e:
        logger.error(f"Error initializing signals file: {e}")
        logger.error(traceback.format_exc())
        return False

def synchronize_cooldowns():
    """Ensure cooldowns are synchronized across components"""
    try:
        # Get all active cooldowns
        position_cooldowns = cooldown_tracker.get_all_in_cooldown('position')
        
        # Write them to a file that tpsl.py can read
        cooldown_data = {
            "timestamp": datetime.now().isoformat(),
            "cooldowns": position_cooldowns
        }
        
        with open("cooldown_sync.json", "w") as f:
            json.dump(cooldown_data, f, indent=2)
            
        logger.info(f"Synchronized {len(position_cooldowns)} cooldowns to file")
    except Exception as e:
        logger.error(f"Error synchronizing cooldowns: {e}")

# Add this near the top of the file, after imports but before other function definitions

def send_telegram_message(title, message):
    """Send a notification message via Telegram"""
    try:
        # Check if we have telegram notifications configured
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not telegram_bot_token or not telegram_chat_id:
            logger.debug("Telegram notifications not configured, skipping")
            return False
            
        # Format the message
        formatted_message = f"*{title}*\n{message}"
        
        # Construct the API URL
        url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
        
        # Send the request
        response = requests.post(
            url, 
            json={
                "chat_id": telegram_chat_id,
                "text": formatted_message,
                "parse_mode": "Markdown"
            }
        )
        
        # Check the response
        if response.status_code == 200:
            logger.info(f"Sent Telegram notification: {title}")
            return True
        else:
            logger.warning(f"Failed to send Telegram notification: {response.text}")
            return False
    except Exception as e:
        logger.warning(f"Error sending Telegram notification: {e}")
        return False

# Keep the main execution for backward compatibility
if __name__ == "__main__":
    watchdog = TradingWatchdog()
    # Make the instance globally available for other functions
    watchdog_instance = watchdog
    watchdog.main_loop() 