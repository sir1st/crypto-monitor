import os
import json
import logging
from datetime import datetime
from trade_manager import get_active_positions, calculate_position_size, bybit_client

# Set up proper logging for martingale manager
logger = logging.getLogger("martingale_manager")

def add_martingale_position(symbol, multiplier=2.0):
    """
    Add to existing position using martingale strategy across all accounts
    
    Args:
        symbol (str): Trading pair (e.g., 'BTCUSDT')
        multiplier (float): Position size multiplier (default 2.0)
        
    Returns:
        dict: Result with success flag and position details
    """
    try:
        import trade_manager
        
        # Check if multi-account is enabled
        if hasattr(trade_manager, 'is_multi_account_enabled') and trade_manager.is_multi_account_enabled():
            # Multi-account mode
            logger.info(f"🏦 Multi-account martingale: Adding {multiplier}x to {symbol} across all accounts")
            
            # 1. Check existing positions across all accounts
            all_positions = trade_manager.get_active_positions_all_accounts()
            if symbol not in all_positions:
                return {
                    "success": False,
                    "message": f"No existing positions found for {symbol} across any account"
                }
            
            account_positions = all_positions[symbol]
            position_side = account_positions[0]['side']  # Should be same across all accounts
            
            # 2. Execute martingale addition across all accounts in parallel
            result = execute_martingale_parallel(symbol, position_side, multiplier)
            
            if result and result.get("success_count", 0) > 0:
                # 3. Log the multi-account martingale operation
                martingale_log = {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "side": position_side,
                    "multiplier": multiplier,
                    "accounts": result.get("total_count", 0),
                    "successful_accounts": result.get("success_count", 0),
                    "account_details": result.get("results", {}),
                    "type": "multi_account_martingale"
                }
                
                save_martingale_log(martingale_log)
                
                logger.info(f"✅ Multi-account martingale completed: {result.get('success_count')}/{result.get('total_count')} accounts successful")
                
                return {
                    "success": True,
                    "symbol": symbol,
                    "side": position_side,
                    "multiplier": multiplier,
                    "accounts": result.get("success_count"),
                    "total_accounts": result.get("total_count"),
                    "results": result.get("results", {}),
                    "message": f"Added {multiplier}x to {symbol} position across {result.get('success_count')}/{result.get('total_count')} accounts"
                }
            else:
                logger.error(f"❌ Multi-account martingale failed for {symbol}")
                return {
                    "success": False,
                    "message": f"Failed to add martingale position for {symbol} across all accounts"
                }
        
        else:
            # Single account mode - use original logic with direct imports
            logger.info(f"📱 Single account martingale: Adding {multiplier}x to {symbol}")
            return add_martingale_position_single_account(symbol, multiplier)
            
    except Exception as e:
        logger.error(f"Error in add_martingale_position: {e}")
        return {
            "success": False,
            "message": str(e)
        }

def execute_martingale_parallel(symbol, position_side, multiplier):
    """Execute martingale addition across all accounts in parallel"""
    try:
        import trade_manager
        
        if not trade_manager.multi_trader:
            logger.error("Multi trader not available")
            return {"success_count": 0, "total_count": 0, "results": {}}
        
        # Use the multi-account trader to execute across all accounts
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        results = {}
        accounts = trade_manager.multi_trader.accounts
        logger.info(f"Executing martingale across {len(accounts)} accounts: {accounts}")
        
        with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
            futures = {
                executor.submit(add_martingale_single_account, account, symbol, position_side, multiplier): account 
                for account in accounts
            }
            
            for future in as_completed(futures):
                account = futures[future]
                try:
                    results[account] = future.result()
                    if results[account].get('success'):
                        logger.info(f"✅ {account}: Martingale executed successfully")
                    else:
                        logger.error(f"❌ {account}: Martingale failed - {results[account].get('error', 'Unknown error')}")
                except Exception as e:
                    logger.error(f"❌ {account}: Exception during martingale execution: {e}")
                    results[account] = {"success": False, "error": str(e)}
        
        successful = sum(1 for r in results.values() if r.get('success', False))
        logger.info(f"Martingale parallel execution completed: {successful}/{len(results)} accounts successful")
        
        return {
            "success_count": successful,
            "total_count": len(results),
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Error in execute_martingale_parallel: {e}")
        return {"success_count": 0, "total_count": 0, "results": {}}

def add_martingale_single_account(account_name, symbol, position_side, multiplier):
    """Add martingale position for a single account"""
    try:
        import trade_manager
        
        # Get account config and client
        account_config = trade_manager.multi_trader.account_configs.get(account_name)
        client = trade_manager.multi_trader.clients.get(account_name)
        
        if not account_config or not client:
            logger.error(f"Account {account_name} not found or not configured")
            return {"success": False, "error": f"Account {account_name} not found or not configured"}
        
        # Get original position size for this account
        original_position_usdt = account_config.get('position_usdt', 15)
        
        # Calculate martingale amount for this account
        martingale_amount = original_position_usdt * multiplier
        
        logger.info(f"{account_name}: Calculating martingale position: ${original_position_usdt} × {multiplier} = ${martingale_amount}")
        
        # Calculate position size for this account
        position_data = trade_manager.multi_trader.calculate_account_position_size(account_name, symbol, position_side)
        if not position_data:
            logger.error(f"Failed to calculate position size for {account_name}")
            return {"success": False, "error": f"Failed to calculate position size for {account_name}"}
        
        # Adjust quantity based on multiplier
        base_qty = float(position_data['formatted_qty'])
        martingale_qty = base_qty * multiplier
        
        # Format the quantity properly
        formatted_qty = str(round(martingale_qty, 3))  # Assuming 3 decimals for BTC
        
        logger.info(f"{account_name}: Placing martingale order: {formatted_qty} {symbol} {position_side}")
        
        # Place the martingale order
        order_result = client.place_order(
            category="linear",
            symbol=symbol,
            side=position_side,
            orderType="Market",
            qty=formatted_qty
        )
        
        if order_result and order_result.get("retCode") == 0:
            order_id = order_result.get("result", {}).get("orderId")
            logger.info(f"✅ {account_name}: Martingale order placed successfully, Order ID: {order_id}")
            return {
                "success": True,
                "account": account_name,
                "order_id": order_id,
                "added_amount_usdt": martingale_amount,
                "added_qty": formatted_qty,
                "multiplier": multiplier
            }
        else:
            error_msg = order_result.get("retMsg", "Unknown error") if order_result else "No response"
            logger.error(f"❌ {account_name}: Martingale order failed: {error_msg}")
            return {"success": False, "error": error_msg, "account": account_name}
            
    except Exception as e:
        logger.error(f"Error executing martingale for {account_name}: {e}")
        return {"success": False, "error": str(e), "account": account_name}

def add_martingale_position_single_account(symbol, multiplier=2.0):
    """Original single-account martingale logic (fallback)"""
    try:
        logger.info(f"Executing single-account martingale for {symbol} with {multiplier}x multiplier")
        
        # 1. Check existing position
        positions = get_active_positions()
        if symbol not in positions:
            return {
                "success": False, 
                "message": f"No existing position found for {symbol}"
            }
        
        position = positions[symbol]
        position_side = position.get("side")
        current_size = float(position.get("size", 0))
        current_value = float(position.get("value", 0))
        
        logger.info(f"Current position: {symbol} {position_side} {current_size}")
        
        # 2. Get original position size from config
        with open("trading_config.json", "r") as f:
            config = json.load(f)
        
        symbol_config = config.get("symbol_config", {}).get(symbol, {})
        original_position_usdt = symbol_config.get("position_usdt", 
                                config.get("initial_position_usdt", 25.0))
        
        # 3. Calculate martingale position size
        martingale_amount = original_position_usdt * multiplier
        logger.info(f"Martingale amount: ${original_position_usdt} × {multiplier} = ${martingale_amount}")
        
        # 4. Calculate position data for the additional amount
        position_data = calculate_position_size(symbol, position_side, martingale_amount)
        if not position_data:
            return {
                "success": False,
                "message": f"Failed to calculate position size for {symbol}"
            }
        
        # 5. Place the martingale order
        logger.info(f"Placing martingale order: {position_data['formatted_qty']} {symbol} {position_side}")
        
        order_result = bybit_client.place_order(
            category="linear",
            symbol=symbol,
            side=position_side,
            orderType="Market",
            qty=position_data["formatted_qty"]
        )
        
        if not order_result or order_result.get("retCode") != 0:
            error_msg = order_result.get("retMsg", "Unknown error") if order_result else "No response"
            logger.error(f"Martingale order failed: {error_msg}")
            return {
                "success": False,
                "message": f"Order failed: {error_msg}"
            }
        
        order_id = order_result.get("result", {}).get("orderId")
        logger.info(f"✅ Single-account martingale order placed successfully, Order ID: {order_id}")
        
        # 6. Track the martingale addition
        martingale_log = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "side": position_side,
            "multiplier": multiplier,
            "added_amount_usdt": martingale_amount,
            "added_qty": position_data["formatted_qty"],
            "order_id": order_id,
            "previous_size": current_size,
            "previous_value": current_value,
            "type": "single_account_martingale"
        }
        
        save_martingale_log(martingale_log)
        
        return {
            "success": True,
            "symbol": symbol,
            "side": position_side,
            "multiplier": multiplier,
            "added_amount": martingale_amount,
            "added_qty": position_data["formatted_qty"],
            "order_id": order_id,
            "message": f"Added {multiplier}x to {symbol} position (${martingale_amount})"
        }
        
    except Exception as e:
        logger.error(f"Error in add_martingale_position_single_account: {e}")
        return {
            "success": False,
            "message": str(e)
        }

def save_martingale_log(log_entry):
    """Save martingale operation to log file"""
    try:
        log_file = "martingale_log.json"
        
        # Load existing logs
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                logs = json.load(f)
        else:
            logs = []
        
        # Add new log entry
        logs.append(log_entry)
        
        # Keep only last 50 entries
        if len(logs) > 50:
            logs = logs[-50:]
        
        # Save back to file
        with open(log_file, "w") as f:
            json.dump(logs, f, indent=2)
            
        logger.info(f"Martingale operation logged to {log_file}")
            
    except Exception as e:
        logger.error(f"Error saving martingale log: {e}")
