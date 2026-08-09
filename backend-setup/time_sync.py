import time
import logging
from datetime import datetime
from pybit.unified_trading import HTTP
import threading
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("time_sync")

# Load environment variables
load_dotenv()
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

class TimeSync:
    def __init__(self):
        self.time_offset = 0
        self.last_sync_time = 0
        self.sync_interval = 30  # Sync every 30 seconds
        self.lock = threading.Lock()
        self.session = HTTP(
            testnet=False,
            api_key=API_KEY,
            api_secret=API_SECRET
        )
        self._start_sync_thread()

    def _sync_time(self):
        """Synchronize local time with Bybit server time"""
        try:
            # Try both method names since the API documentation and implementation might differ
            try:
                response = self.session.get_server_time()
            except AttributeError:
                # Fall back to the alternate method name if the first one doesn't exist
                try:
                    response = self.session.server_time()
                except AttributeError:
                    # Direct endpoint call if neither method exists
                    response = self.session.request(
                        method="GET",
                        endpoint="/v5/market/time",
                    )
            
            if response and response.get("retCode") == 0:
                # Get server time from response - could be either format
                if "timeSecond" in response["result"]:
                    server_time = int(response["result"]["timeSecond"])
                elif "timeNano" in response["result"]:
                    server_time_nano = int(response["result"]["timeNano"])
                    server_time = server_time_nano // 1_000_000_000  # Convert nanoseconds to seconds
                else:
                    # Fall back to the 'time' field if available
                    server_time = int(response.get("time", 0)) // 1000
                
                local_time = int(time.time())
                
                with self.lock:
                    self.time_offset = server_time - local_time
                    self.last_sync_time = local_time
                    
                logger.info(f"Time synchronized. Offset: {self.time_offset} seconds")
                return True
            else:
                logger.error(f"Failed to get server time: {response}")
                return False
        except Exception as e:
            logger.error(f"Error synchronizing time: {e}")
            return False

    def _start_sync_thread(self):
        """Start background thread for periodic time synchronization"""
        def sync_thread():
            while True:
                self._sync_time()
                time.sleep(self.sync_interval)

        thread = threading.Thread(target=sync_thread, daemon=True)
        thread.start()
        logger.info("Time sync thread started")

    def get_server_time(self):
        """Get current server time in seconds"""
        with self.lock:
            return int(time.time()) + self.time_offset

    def get_server_time_ms(self):
        """Get current server time in milliseconds"""
        return self.get_server_time() * 1000

    def get_timestamp_ms(self):
        """Get timestamp in milliseconds with offset applied"""
        return int(time.time() * 1000) + (self.time_offset * 1000)

    def format_timestamp(self, timestamp_ms):
        """Format timestamp for Bybit API requests"""
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

# Create a global instance
time_sync = TimeSync()

# Utility functions for easy access
def get_server_time():
    """Get current server time in seconds"""
    return time_sync.get_server_time()

def get_server_time_ms():
    """Get current server time in milliseconds"""
    return time_sync.get_server_time_ms()

def get_timestamp_ms():
    """Get timestamp in milliseconds with offset applied"""
    return time_sync.get_timestamp_ms()

def format_timestamp(timestamp_ms):
    """Format timestamp for Bybit API requests"""
    return time_sync.format_timestamp(timestamp_ms)

# Test function
def test_time_sync():
    """Test time synchronization"""
    try:
        # Initial sync
        result = time_sync._sync_time()
        if not result:
            print("Failed to sync time. Check API credentials and connection.")
            return False
        
        # Get times
        server_time = get_server_time()
        server_time_ms = get_server_time_ms()
        
        print(f"Server time (s): {server_time}")
        print(f"Server time (ms): {server_time_ms}")
        print(f"Formatted time: {format_timestamp(server_time_ms)}")
        print(f"Time offset: {time_sync.time_offset} seconds")
        
        return True
    except Exception as e:
        print(f"Error testing time sync: {e}")
        return False

if __name__ == "__main__":
    # Run test when module is run directly
    test_time_sync() 