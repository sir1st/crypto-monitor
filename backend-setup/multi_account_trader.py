import os
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pybit.unified_trading import HTTP
from datetime import datetime

# Set up logging
logger = logging.getLogger("multi_account_trader")

class SimpleMultiAccountTrader:
    def __init__(self):
        self.accounts = []
        self.clients = {}
        self.account_configs = {}
        self.trading_symbol = "BTCUSDT"  # Default, will be overridden by config
        self.load_accounts()
        
    def load_config(self):
        """Load accounts configuration from file"""
        try:
            with open("accounts_config.json", "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading accounts config: {e}")
            return {"accounts": [], "parallel_execution": True, "trading_symbol": "BTCUSDT"}
        
    def load_accounts(self):
        """Load account configs and create API clients"""
        config = self.load_config()
        
        # Set trading symbol from config
        self.trading_symbol = config.get('trading_symbol', 'BTCUSDT')
        logger.info(f"Trading symbol set to: {self.trading_symbol}")
        
        for account in config['accounts']:
            if account['enabled']:
                try:
                    api_key = os.getenv(account['api_key_env'])
                    api_secret = os.getenv(account['api_secret_env'])
                    
                    if not api_key or not api_secret:
                        logger.error(f"Missing API credentials for {account['name']}")
                        continue
                        
                    client = HTTP(
                        api_key=api_key,
                        api_secret=api_secret,
                        testnet=False,
                        recv_window=20000
                    )
                    
                    # Test connection
                    client.get_server_time()
                    
                    self.clients[account['name']] = client
                    self.account_configs[account['name']] = account
                    self.accounts.append(account['name'])
                    
                    position_usdt = account.get('position_usdt', 15)
                    leverage = account.get('leverage', 40)
                    logger.info(f"✅ {account['name']}: Position ${position_usdt} USDT @ {leverage}x leverage")
                    
                except Exception as e:
                    logger.error(f"Failed to initialize account {account['name']}: {e}")
                    
        logger.info(f"Multi-account trader initialized with {len(self.accounts)} accounts for {self.trading_symbol}")
                
    def calculate_account_position_size(self, account_name, symbol, side):
        """Calculate position size for a specific account"""
        try:
            account_config = self.account_configs.get(account_name)
            if not account_config:
                logger.error(f"No config found for account {account_name}")
                return None
                
            position_usdt = account_config.get('position_usdt', 15)
            leverage = account_config.get('leverage', 40)
            
            # Get current price
            client = self.clients[account_name]
            ticker_response = client.get_tickers(category="linear", symbol=symbol)
            
            if ticker_response.get("retCode") != 0:
                logger.error(f"Failed to get ticker for {symbol}")
                return None
                
            current_price = float(ticker_response.get("result", {}).get("list", [{}])[0].get("lastPrice", 0))
            
            if current_price <= 0:
                logger.error(f"Invalid price for {symbol}: {current_price}")
                return None
            
            # Calculate quantity: position_usdt * leverage / current_price
            qty = (position_usdt * leverage) / current_price
            
            # Get precision for this symbol
            instruments_response = client.get_instruments_info(category="linear", symbol=symbol)
            
            if instruments_response.get("retCode") == 0:
                instruments = instruments_response.get("result", {}).get("list", [])
                if instruments:
                    qty_step = instruments[0].get("lotSizeFilter", {}).get("qtyStep", "0.001")
                    # Calculate decimals from step size
                    qty_decimals = 0
                    if "." in qty_step:
                        qty_decimals = len(qty_step.split(".")[1])
                    
                    # Format quantity to proper precision
                    formatted_qty = round(qty, qty_decimals)
                else:
                    formatted_qty = round(qty, 3)  # Default to 3 decimals
            else:
                formatted_qty = round(qty, 3)  # Default to 3 decimals
            
            logger.info(f"{account_name}: Calculated position size: {formatted_qty} {symbol} (${position_usdt} USDT @ {leverage}x @ ${current_price})")
            
            return {
                "qty": qty,
                "formatted_qty": str(formatted_qty),
                "position_usdt": position_usdt,
                "leverage": leverage,
                "current_price": current_price
            }
            
        except Exception as e:
            logger.error(f"Error calculating position size for {account_name}: {e}")
            return None
                
    def execute_trade_parallel(self, symbol, side, base_qty=None, **kwargs):
        """Execute the same trade across all accounts in parallel with individual position sizes"""
        if not self.accounts:
            logger.warning("No accounts available for trading")
            return {}
            
        # Only trade the configured symbol
        if symbol != self.trading_symbol:
            logger.warning(f"Ignoring trade for {symbol} - only trading {self.trading_symbol}")
            return {}
            
        logger.info(f"🚀 Executing {side} trade for {symbol} across {len(self.accounts)} accounts with individual position sizes")
        
        with ThreadPoolExecutor(max_workers=len(self.accounts)) as executor:
            futures = {
                executor.submit(self._execute_single_account_with_individual_size, account, symbol, side, **kwargs): account 
                for account in self.accounts
            }
            
            results = {}
            for future in as_completed(futures):
                account = futures[future]
                try:
                    results[account] = future.result()
                    if results[account].get('success'):
                        position_info = results[account]
                        qty = position_info.get('qty', 'unknown')
                        usdt_value = position_info.get('position_usdt', 'unknown')
                        logger.info(f"✅ {account}: {side} {qty} {symbol} (${usdt_value} USDT)")
                    else:
                        logger.error(f"❌ {account}: Trade failed - {results[account].get('error', 'Unknown error')}")
                except Exception as e:
                    logger.error(f"❌ {account}: Exception during trade execution: {e}")
                    results[account] = {"success": False, "error": str(e)}
                    
        successful = sum(1 for r in results.values() if r.get('success', False))
        logger.info(f"🎯 Trade execution completed: {successful}/{len(results)} accounts successful")
        
        return results
        
    def execute_close_parallel(self, symbol, side):
        """Execute position closing across all accounts in parallel"""
        if not self.accounts:
            logger.warning("No accounts available for closing")
            return {}
            
        # Only close positions for the configured symbol
        if symbol != self.trading_symbol:
            logger.warning(f"Ignoring close for {symbol} - only trading {self.trading_symbol}")
            return {}
            
        logger.info(f"🔄 Closing {side} position for {symbol} across {len(self.accounts)} accounts")
        
        with ThreadPoolExecutor(max_workers=len(self.accounts)) as executor:
            futures = {
                executor.submit(self._close_single_account, account, symbol, side): account 
                for account in self.accounts
            }
            
            results = {}
            for future in as_completed(futures):
                account = futures[future]
                try:
                    results[account] = future.result()
                    if results[account].get('success'):
                        logger.info(f"✅ {account}: Position closed successfully")
                    else:
                        logger.error(f"❌ {account}: Close failed - {results[account].get('error', 'Unknown error')}")
                except Exception as e:
                    logger.error(f"❌ {account}: Exception during position close: {e}")
                    results[account] = {"success": False, "error": str(e)}
                    
        successful = sum(1 for r in results.values() if r.get('success', False))
        logger.info(f"🎯 Position close completed: {successful}/{len(results)} accounts successful")
        
        return results
        
    def _execute_single_account_with_individual_size(self, account_name, symbol, side, **kwargs):
        """Execute trade on a single account with account-specific position size"""
        try:
            # Calculate position size for this specific account
            position_data = self.calculate_account_position_size(account_name, symbol, side)
            
            if not position_data:
                return {"success": False, "error": "Failed to calculate position size", "account": account_name}
            
            client = self.clients[account_name]
            account_config = self.account_configs[account_name]
            
            leverage = account_config.get('leverage', 40)
            qty = position_data['formatted_qty']
            
            # Set leverage for this account
            try:
                leverage_response = client.set_leverage(
                    category="linear",
                    symbol=symbol,
                    buyLeverage=str(leverage),
                    sellLeverage=str(leverage)
                )
                logger.debug(f"{account_name}: Set leverage to {leverage}x")
            except Exception as e:
                logger.warning(f"{account_name}: Error setting leverage: {e}")
            
            # Place the order
            result = client.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=qty,
                positionIdx=0,
                timeInForce="GTC"
            )
            
            if result and result.get("retCode") == 0:
                order_id = result.get("result", {}).get("orderId")
                return {
                    "success": True, 
                    "account": account_name,
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "position_usdt": position_data['position_usdt'],
                    "leverage": leverage,
                    "current_price": position_data['current_price']
                }
            else:
                error_msg = result.get("retMsg", "Unknown error") if result else "No response"
                return {"success": False, "error": error_msg, "account": account_name}
                
        except Exception as e:
            logger.error(f"Error executing trade on {account_name}: {e}")
            return {"success": False, "error": str(e), "account": account_name}
            
    def _close_single_account(self, account_name, symbol, side):
        """Close position on a single account"""
        try:
            client = self.clients[account_name]
            
            # Get current position size for this account
            positions_response = client.get_positions(category="linear", symbol=symbol)
            
            if positions_response.get("retCode") != 0:
                return {"success": False, "error": "Failed to get position info", "account": account_name}
                
            positions = positions_response.get("result", {}).get("list", [])
            position = None
            
            for pos in positions:
                if pos.get("symbol") == symbol and float(pos.get("size", 0)) > 0:
                    position = pos
                    break
                    
            if not position:
                return {"success": False, "error": "No position found", "account": account_name}
                
            # The side to close is opposite of the position side
            position_side = position.get("side")
            close_side = "Sell" if position_side == "Buy" else "Buy"
            qty = position.get("size")
            
            # Place closing order
            result = client.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(qty),
                reduceOnly=True
            )
            
            if result and result.get("retCode") == 0:
                order_id = result.get("result", {}).get("orderId")
                return {
                    "success": True,
                    "account": account_name, 
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": close_side,
                    "qty": qty
                }
            else:
                error_msg = result.get("retMsg", "Unknown error") if result else "No response"
                return {"success": False, "error": error_msg, "account": account_name}
                
        except Exception as e:
            logger.error(f"Error closing position on {account_name}: {e}")
            return {"success": False, "error": str(e), "account": account_name}
            
    def get_all_positions(self):
        """Get positions from all accounts"""
        all_positions = {}
        
        for account_name in self.accounts:
            try:
                client = self.clients[account_name]
                positions_response = client.get_positions(category="linear", symbol=self.trading_symbol)
                
                if positions_response.get("retCode") == 0:
                    positions = positions_response.get("result", {}).get("list", [])
                    
                    for pos in positions:
                        if float(pos.get("size", 0)) > 0:  # Only active positions
                            symbol = pos.get("symbol")
                            if symbol not in all_positions:
                                all_positions[symbol] = []
                                
                            # Add account config info to position data
                            account_config = self.account_configs.get(account_name, {})
                            configured_position_usdt = account_config.get('position_usdt', 'unknown')
                            
                            all_positions[symbol].append({
                                "account": account_name,
                                "side": pos.get("side"),
                                "size": pos.get("size"), 
                                "entry_price": pos.get("avgPrice"),
                                "mark_price": pos.get("markPrice"),
                                "unrealised_pnl": pos.get("unrealisedPnl"),
                                "leverage": pos.get("leverage"),
                                "configured_position_usdt": configured_position_usdt
                            })
                            
            except Exception as e:
                logger.error(f"Error getting positions for {account_name}: {e}")
                
        return all_positions
        
    def test_all_connections(self):
        """Test API connections for all accounts"""
        results = {}
        
        for account_name in self.accounts:
            try:
                client = self.clients[account_name]
                server_time = client.get_server_time()
                
                if server_time.get("retCode") == 0:
                    account_config = self.account_configs.get(account_name, {})
                    position_usdt = account_config.get('position_usdt', 'unknown')
                    leverage = account_config.get('leverage', 'unknown')
                    
                    results[account_name] = {
                        "status": "connected", 
                        "server_time": server_time.get("result", {}).get("timeSecond"),
                        "position_usdt": position_usdt,
                        "leverage": leverage
                    }
                else:
                    results[account_name] = {"status": "error", "error": server_time.get("retMsg", "Unknown error")}
                    
            except Exception as e:
                results[account_name] = {"status": "error", "error": str(e)}
                
        return results
        
    def get_account_summary(self):
        """Get a summary of all account configurations"""
        summary = {
            "total_accounts": len(self.accounts),
            "trading_symbol": self.trading_symbol,
            "accounts": []
        }
        
        total_usdt = 0
        for account_name in self.accounts:
            account_config = self.account_configs.get(account_name, {})
            position_usdt = account_config.get('position_usdt', 0)
            leverage = account_config.get('leverage', 40)
            
            summary["accounts"].append({
                "name": account_name,
                "position_usdt": position_usdt,
                "leverage": leverage,
                "enabled": account_config.get('enabled', False)
            })
            
            total_usdt += position_usdt
            
        summary["total_position_usdt"] = total_usdt
        
        return summary
