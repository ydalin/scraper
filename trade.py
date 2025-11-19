# trade.py – FINAL: TP/SL WITH positionSide + NO PARAMS ERROR
import asyncio
from api import bingx_api_request

def print_payload(title, data):
    print(f"\n{title} PAYLOAD TO BINGX:")
    for k, v in data.items():
        print(f"  {k}: {v}")
    print("-" * 50)

async def get_order_status(client, symbol, order_id):
    """Get order status from BingX"""
    try:
        resp = await bingx_api_request(
            'GET', '/openApi/swap/v2/trade/queryOrder',
            client['api_key'], client['secret_key'], client['base_url'],
            params={
                'symbol': symbol,
                'orderId': order_id
            }
        )
        if resp.get('code') == 0:
            order_data = resp.get('data', {})
            return order_data.get('status')  # FILLED, NEW, CANCELED, etc.
        return None
    except Exception as e:
        print(f"[ORDER STATUS ERROR] {e}")
        return None

async def cancel_order(client, symbol, order_id):
    """Cancel an order on BingX"""
    try:
        resp = await bingx_api_request(
            'DELETE', '/openApi/swap/v2/trade/order',
            client['api_key'], client['secret_key'], client['base_url'],
            data={
                'symbol': symbol,
                'orderId': order_id
            }
        )
        if resp.get('code') == 0:
            return True
        else:
            print(f"[CANCEL ORDER ERROR] {resp.get('msg')}")
            return False
    except Exception as e:
        print(f"[CANCEL ORDER ERROR] {e}")
        return False

async def get_position_size(client, symbol, position_side):
    """Get current position size for a specific position side"""
    try:
        resp = await bingx_api_request(
            'GET', '/openApi/swap/v2/trade/position',
            client['api_key'], client['secret_key'], client['base_url'],
            params={'symbol': symbol}
        )
        if resp.get('code') == 0 and resp.get('data'):
            position_data = resp['data']
            # Check if data is a list or dict
            if isinstance(position_data, list):
                for pos in position_data:
                    if pos.get('positionSide') == position_side:
                        return abs(float(pos.get('positionAmt', 0)))
            elif isinstance(position_data, dict):
                if position_data.get('positionSide') == position_side:
                    return abs(float(position_data.get('positionAmt', 0)))
        return 0.0
    except Exception as e:
        print(f"[POSITION SIZE ERROR] {e}")
        return 0.0

async def get_open_orders(client, symbol):
    """Get all open orders for a symbol"""
    try:
        resp = await bingx_api_request(
            'GET', '/openApi/swap/v2/trade/openOrders',
            client['api_key'], client['secret_key'], client['base_url'],
            params={'symbol': symbol}
        )
        if resp.get('code') == 0:
            return resp.get('data', {}).get('orders', [])
        return []
    except Exception as e:
        print(f"[OPEN ORDERS ERROR] {e}")
        return []

async def find_stop_loss_order(client, symbol, position_side):
    """Find the current stop-loss order for a position"""
    try:
        orders = await get_open_orders(client, symbol)
        for order in orders:
            # Check if it's a stop-loss order for this position side
            if (order.get('type') == 'STOP_MARKET' and 
                order.get('positionSide') == position_side):
                return order.get('orderId')
        return None
    except Exception as e:
        print(f"[FIND SL ORDER ERROR] {e}")
        return None

async def monitor_tp_and_trail_sl(client, symbol, position_side, entry, qty, tp_orders, sl_id, trail_tp_level, config):
    """Monitor TP orders and add conditional stop-loss when target TP is hit"""
    try:
        if trail_tp_level == 0 or trail_tp_level > len(tp_orders):
            return
        
        print(f"\n[TP MONITOR {symbol}] Starting monitoring for TP{trail_tp_level} fill...")
        target_tp = None
        for tp_order in tp_orders:
            if tp_order['tp_level'] == trail_tp_level:
                target_tp = tp_order
                break
        
        if not target_tp:
            print(f"[TP MONITOR {symbol}] TP{trail_tp_level} not found in TP orders list")
            return
    
        check_interval = 5  # Check every 5 seconds
        max_checks = 3600  # Monitor for up to 5 hours (3600 * 5s = 5h)
        checks = 0
        
        while checks < max_checks:
            await asyncio.sleep(check_interval)
            checks += 1
            
            # First, check if position still exists
            position_size = await get_position_size(client, symbol, position_side)
            if position_size == 0:
                print(f"\n[TP MONITOR {symbol}] Position closed. Stopping monitoring.")
                break
            
            # Check if target TP order is filled
            status = await get_order_status(client, symbol, target_tp['order_id'])
            
            if status == 'FILLED':
                print(f"\n✅ [TP MONITOR {symbol}] TP{trail_tp_level} FILLED! Adding conditional stop-loss at breakeven...")
                
                # Get actual remaining position size from exchange
                remaining_qty = await get_position_size(client, symbol, position_side)
                
                if remaining_qty == 0:
                    print(f"[TP MONITOR {symbol}] Position fully closed. No breakeven SL needed.")
                    break
                
                # Add new conditional stop-loss: triggers when price reaches TP, then protects at entry (breakeven)
                opposite_side = 'SELL' if position_side == 'LONG' else 'BUY'
                tp_price = target_tp['price']
                
                # Calculate direction-aware breakeven price with buffer
                breakeven_buffer = 0.0005  # 0.05% buffer is enough for BingX
                if position_side == "LONG":
                    breakeven_price = entry * (1 + breakeven_buffer)  # slightly above entry
                else:  # SHORT
                    breakeven_price = entry * (1 - breakeven_buffer)  # slightly below entry
                
                # Conditional stop-loss: When price reaches TP, this order becomes active
                # For LONG: stopPrice = TP (triggers when price reaches/hits TP), price = entry (breakeven)
                # For SHORT: stopPrice = TP (triggers when price reaches/hits TP), price = entry (breakeven)
                # Once TP is reached, if price moves back to entry, the stop-loss executes
                conditional_sl_payload = {
                    'symbol': symbol,
                    'side': opposite_side,
                    'positionSide': position_side,
                    'type': 'STOP',  # Conditional limit order
                    'quantity': f"{remaining_qty:.6f}",
                    'price': str(entry),  # Limit price = breakeven (execute at entry)
                    'stopPrice': str(tp_price),  # Trigger = TP price (activate when TP is reached)
                    'timeInForce': 'GTC',
                    'workingType': 'MARK_PRICE',
                    'priceProtect': 'TRUE'  # Add this for safety
                }
                
                print_payload(f"CONDITIONAL BREAKEVEN SL (triggers at TP{trail_tp_level})", conditional_sl_payload)
                print(f"   Logic: When price reaches TP{trail_tp_level} ({tp_price}), this stop-loss activates")
                print(f"   If price then moves to entry ({entry}), position closes at breakeven")
                
                conditional_sl_resp = await bingx_api_request(
                    'POST', '/openApi/swap/v2/trade/order',
                    client['api_key'], client['secret_key'], client['base_url'],
                    data=conditional_sl_payload
                )
                
                if conditional_sl_resp.get('code') == 0:
                    conditional_sl_id = conditional_sl_resp.get('data', {}).get('order', {}).get('orderId')
                    print(f"✅ CONDITIONAL BREAKEVEN SL SET: ID = {conditional_sl_id}")
                    print(f"   Trigger: {tp_price} (TP{trail_tp_level} price)")
                    print(f"   Execute: {entry} (breakeven/entry price)")
                    print(f"   Remaining position: {remaining_qty:.6f} ({remaining_qty/qty*100:.1f}%)")
                    print(f"   Note: Original stop-loss remains active until this triggers")
                else:
                    print(f"❌ FAILED to set conditional breakeven SL: {conditional_sl_resp.get('msg')}")
                
                # Stop monitoring after adding conditional SL
                break
            elif status == 'CANCELED':
                print(f"[TP MONITOR {symbol}] TP{trail_tp_level} was canceled. Stopping monitoring.")
                break
            elif status is None:
                # Order might not exist or API error - continue monitoring
                if checks % 12 == 0:  # Log every minute
                    print(f"[TP MONITOR {symbol}] Still monitoring TP{trail_tp_level}... (check {checks}/{max_checks})")
        
        if checks >= max_checks:
            print(f"[TP MONITOR {symbol}] Monitoring timeout reached. TP{trail_tp_level} may not have filled yet.")
    
    except Exception as e:
        print(f"[TP MONITOR {symbol}] ERROR: {e}")
        import traceback
        traceback.print_exc()

async def execute_trade(client, signal, usdt_amount, dry_run, custom_leverage, config=None):
    """Execute trade with configurable parameters"""
    if config is None:
        from config import DEFAULT_CONFIG
        config = DEFAULT_CONFIG
    
    symbol = signal['symbol'].replace('/', '-')
    side = 'BUY' if signal['direction'] == 'LONG' else 'SELL'
    opposite_side = 'SELL' if signal['direction'] == 'LONG' else 'BUY'
    position_side = signal['direction']  # LONG or SHORT
    leverage = custom_leverage
    entry = signal['entry']
    qty = (usdt_amount * leverage) / entry
    
    # === CHECK FOR EXISTING POSITION ===
    if not dry_run:
        try:
            pos_resp = await bingx_api_request(
                'GET', '/openApi/swap/v2/trade/position',
                client['api_key'], client['secret_key'], client['base_url'],
                params={'symbol': symbol}
            )
            if pos_resp.get('code') == 0 and pos_resp.get('data'):
                position_data = pos_resp['data']
                # Check if data is a list or dict
                if isinstance(position_data, list):
                    position_data = position_data[0] if position_data else {}
                
                # Check if there's an existing position with the same side
                position_amt = float(position_data.get('positionAmt', 0))
                if position_amt != 0:
                    existing_side = position_data.get('positionSide', 'unknown')
                    print(f"\n⚠️  SKIPPING TRADE: Existing {existing_side} position found for {symbol}")
                    print(f"   Position Amount: {position_amt}")
                    print(f"   Cannot open duplicate position. Close existing position first.\n")
                    return
        except Exception as e:
            print(f"⚠️  Could not check existing position: {e}")
            print(f"   Proceeding with trade anyway (position check failed)")
    
    
    # Position mode: Cross or Isolated
    position_mode = config.get('position_mode', 'Cross').upper()
    # For marginType endpoint: ISOLATED or CROSSED
    margin_type = 'CROSSED' if position_mode == 'CROSS' else 'ISOLATED'
    # For openType in orders: isolated or cross (lowercase)
    open_type = 'cross' if position_mode == 'CROSS' else 'isolated'
    
    # Order type: MARKET or LIMIT
    order_type = config.get('order_type', 'MARKET').upper()
    
    # === SL VALIDATION: Ensure SL is -2% from entry ===
    direction = signal['direction']
    expected_sl = entry * (1.02 if direction == 'SHORT' else 0.98)
    sl_diff = abs((signal['stoploss'] - expected_sl) / entry)
    # if sl_diff > 0.001:  # Allow 0.1% tolerance
    #     print(f"[SL ADJUSTMENT] Signal SL {signal['stoploss']} adjusted to {expected_sl:.6f} (-2% from entry)")
    #     signal['stoploss'] = expected_sl

    # === DRY-RUN: FULL DETAILS ===
    if dry_run:
        print("\n" + "="*70)
        print("DRY-RUN TRADE SIMULATION")
        print("="*70)
        print(f"Symbol:       {symbol}")
        print(f"Direction:    {signal['direction']} ({side})")
        print(f"Leverage:     {leverage}x")
        print(f"Position Mode: {position_mode}")
        print(f"Order Type:   {order_type}")
        print(f"Entry:        {entry}")
        print(f"Quantity:     {qty:.6f}")
        print(f"Position $:   {usdt_amount * leverage:.2f} USDT")
        print(f"Take Profits: {signal['targets']}")
        print(f"TP Close %:   TP1={config['tp1_close_percent']}%, TP2={config['tp2_close_percent']}%, TP3={config['tp3_close_percent']}%, TP4={config['tp4_close_percent']}%")
        print(f"Stop Loss:    {signal['stoploss']}")
        if config.get('trail_sl_on_tp', 0) > 0:
            print(f"Trail SL:     Move to breakeven on TP{config['trail_sl_on_tp']}")
        rr = (signal['targets'][-1] - entry) / (entry - signal['stoploss'])
        print(f"Risk/Reward:  {rr:.2f}:1 (to final TP)")
        print("="*70 + "\n")
        return

    # === SET MARGIN MODE (Cross/Isolated) ===
    # First, set the margin type using the dedicated endpoint
    try:
        margin_resp = await bingx_api_request(
            'POST', '/openApi/swap/v2/trade/marginType',
            client['api_key'], client['secret_key'], client['base_url'],
            data={
                'symbol': symbol,
                'marginType': margin_type  # ISOLATED or CROSSED
            }
        )
        if margin_resp.get('code') == 0:
            print(f"✓ Margin mode set to {position_mode} (marginType: {margin_type})")
            await asyncio.sleep(0.5)  # Wait for margin mode to be applied
        else:
            print(f"⚠️  Margin mode setting failed: {margin_resp.get('msg')}")
            print(f"⚠️  Response: {margin_resp}")
    except Exception as e:
        print(f"⚠️  Margin mode setting error: {e}")
    
    # === SET LEVERAGE (with openType) ===
    try:
        leverage_resp = await bingx_api_request(
            'POST', '/openApi/swap/v2/trade/leverage',
            client['api_key'], client['secret_key'], client['base_url'],
            data={
                'symbol': symbol,
                'side': position_side,  # LONG or SHORT (not BUY/SELL)
                'leverage': leverage,
                'openType': open_type  # isolated or cross (lowercase)
            }
        )
        if leverage_resp.get('code') == 0:
            print(f"✓ Leverage set to {leverage}x with openType: {open_type}")
            await asyncio.sleep(0.5)  # Wait for leverage to be applied
        else:
            print(f"⚠️  Leverage setting failed: {leverage_resp.get('msg')}")
            print(f"⚠️  Response: {leverage_resp}")
    except Exception as e:
        print(f"⚠️  Leverage setting error: {e}")

    # === ENTRY ORDER ===
    entry_payload = {
        'symbol': symbol,
        'side': side,
        'positionSide': position_side,
        'type': order_type,
        'quantity': f"{qty:.6f}",
        'leverage': leverage,
        'openType': open_type  # Ensure margin mode is set on the order
    }
    
    # Add price for LIMIT orders
    if order_type == 'LIMIT':
        entry_payload['price'] = str(entry)
        entry_payload['timeInForce'] = 'GTC'
    
    print_payload("ENTRY ORDER", entry_payload)

    order = await bingx_api_request(
        'POST', '/openApi/swap/v2/trade/order',
        client['api_key'], client['secret_key'], client['base_url'],
        data=entry_payload
    )

    if order.get('code') != 0:
        print(f"ENTRY FAILED: {order.get('msg')}")
        return

    order_id = order.get('data', {}).get('order', {}).get('orderId')
    if not order_id:
        print("ENTRY: No orderId in response")
        return
    print(f"ENTRY SUCCESS: Order ID = {order_id}")
    
    # Wait a moment for the position to be created, then verify position mode
    await asyncio.sleep(1)
    try:
        pos_resp = await bingx_api_request(
            'GET', '/openApi/swap/v2/trade/position',
            client['api_key'], client['secret_key'], client['base_url'],
            params={'symbol': symbol}
        )
        if pos_resp.get('code') == 0 and pos_resp.get('data'):
            position_data = pos_resp['data'][0] if isinstance(pos_resp['data'], list) else pos_resp['data']
            actual_mode = position_data.get('marginType', 'unknown')
            # Check if margin mode matches expected
            expected_mode_lower = 'isolated' if margin_type == 'ISOLATED' else 'cross'
            if actual_mode.lower() == expected_mode_lower:
                print(f"✓ Position mode verified: {actual_mode.upper()}")
            else:
                print(f"❌ WARNING: Position opened as {actual_mode.upper()}, expected {position_mode}")
                print(f"   This may indicate the margin mode setting failed. Check your BingX account settings.")
                print(f"   Try manually setting margin mode to {position_mode} in BingX UI for {symbol}")
    except Exception as e:
        print(f"⚠️  Could not verify position mode: {e}")

    # === TAKE PROFIT ORDERS (configurable percentages) ===
    tp_percentages = [
        config.get('tp1_close_percent', 25.0),
        config.get('tp2_close_percent', 25.0),
        config.get('tp3_close_percent', 25.0),
        config.get('tp4_close_percent', 25.0)
    ]
    
    tp_orders = []  # Store TP order IDs for trail SL feature
    for i, tp in enumerate(signal['targets'][:4], 1):  # Ensure max 4 TPs
        tp_percent = tp_percentages[i-1] / 100.0  # Convert to decimal
        tp_qty = qty * tp_percent
        
        tp_payload = {
            'symbol': symbol,
            'side': opposite_side,
            'positionSide': position_side,
            'type': 'LIMIT',  # Use LIMIT orders for TP
            'quantity': f"{tp_qty:.6f}",
            'price': str(tp),  # Limit price for TP
            'timeInForce': 'GTC'
            # Note: reduceOnly is NOT used in Hedge mode (causes error)
            # The opposite side + positionSide combination ensures it closes the position
        }
        print_payload(f"TAKE PROFIT #{i} ({tp_percentages[i-1]}%)", tp_payload)

        tp_resp = await bingx_api_request(
            'POST', '/openApi/swap/v2/trade/order',
            client['api_key'], client['secret_key'], client['base_url'],
            data=tp_payload
        )
        if tp_resp.get('code') == 0:
            tp_id = tp_resp.get('data', {}).get('order', {}).get('orderId')
            tp_orders.append({'tp_level': i, 'order_id': tp_id, 'price': tp})
            print(f"TP #{i} SET ({tp_percentages[i-1]}%): ID = {tp_id}")
        else:
            print(f"TP #{i} FAILED: {tp_resp.get('msg')}")

    # === STOP LOSS ===
    # Use STOP (not STOP_MARKET) for precise trigger - only activates at exact trigger price
    sl_payload = {
        'symbol': symbol,
        'side': opposite_side,
        'positionSide': position_side,
        'type': 'STOP',  # Conditional limit order - triggers at stopPrice, executes at price
        'quantity': f"{qty:.6f}",
        'price': str(signal['stoploss']),  # Limit price (sell at this or better)
        'stopPrice': str(signal['stoploss']),  # Trigger price (activate when hit)
        'timeInForce': 'GTC',
        'workingType': 'MARK_PRICE'
        # Note: reduceOnly is NOT used in Hedge mode (causes error)
        # The opposite side + positionSide combination ensures it closes the position
    }
    print_payload("STOP LOSS", sl_payload)

    sl_resp = await bingx_api_request(
        'POST', '/openApi/swap/v2/trade/order',
        client['api_key'], client['secret_key'], client['base_url'],
        data=sl_payload
    )
    sl_id = None
    if sl_resp.get('code') == 0:
        sl_id = sl_resp.get('data', {}).get('order', {}).get('orderId')
        print(f"SL SET: ID = {sl_id}")
    else:
        print(f"SL FAILED: {sl_resp.get('msg')}")
        return  # Can't continue without SL
    
    # === CONDITIONAL BREAKEVEN SL (if configured) ===
    # This is placed IMMEDIATELY, no loop/monitoring needed.
    # It will only activate once price reaches the chosen TP (via stopPrice trigger).
    trail_tp_level = config.get('trail_sl_on_tp', 0)
    if trail_tp_level > 0 and trail_tp_level <= len(signal['targets']) and len(tp_orders) > 0:
        tp_price = signal['targets'][trail_tp_level - 1]

        # Calculate how much of the position should still be open after TP1..TP{trail_tp_level}
        closed_before = sum(tp_percentages[:trail_tp_level])
        remaining_percent = max(0.0, 100.0 - closed_before)
        remaining_qty = qty * (remaining_percent / 100.0)

        if remaining_qty > 0:
            print(f"\n✅ Conditional breakeven SL enabled (no monitoring loop)")
            print(f"   Original SL: {signal['stoploss']} (remains active)")
            print(f"   TP trigger level: TP{trail_tp_level} @ {tp_price}")
            print(f"   Protected size after TP{trail_tp_level}: {remaining_qty:.6f} ({remaining_percent:.1f}% of original)")

            # Calculate direction-aware breakeven price with buffer
            breakeven_buffer = 0.0005  # 0.05% buffer is enough for BingX
            if position_side == "LONG":
                breakeven_price = entry * (1 + breakeven_buffer)  # slightly above entry
            else:  # SHORT
                breakeven_price = entry * (1 - breakeven_buffer)  # slightly below entry
            
            # Conditional stop-loss: when price reaches TP, this order becomes active.
            # For LONG: stopPrice = TP (trigger), price = entry (breakeven sell limit).
            # For SHORT: stopPrice = TP (trigger), price = entry (breakeven buy limit).
            conditional_sl_payload = {
                'symbol': symbol,
                'side': opposite_side,
                'positionSide': position_side,
                'type': 'STOP',  # Conditional limit order
                'quantity': f"{remaining_qty:.6f}",
                'price': str(entry),  # Limit price = breakeven (execute at entry)
                'stopPrice': str(tp_price),  # Trigger = TP price (activate when TP is reached)
                'timeInForce': 'GTC',
                'workingType': 'MARK_PRICE',
                'priceProtect': 'TRUE'  # Add this for safety
            }

            print_payload(f"CONDITIONAL BREAKEVEN SL (placed immediately for TP{trail_tp_level})", conditional_sl_payload)

            conditional_sl_resp = await bingx_api_request(
                'POST', '/openApi/swap/v2/trade/order',
                client['api_key'], client['secret_key'], client['base_url'],
                data=conditional_sl_payload
            )

            if conditional_sl_resp.get('code') == 0:
                conditional_sl_id = conditional_sl_resp.get('data', {}).get('order', {}).get('orderId')
                print(f"✅ CONDITIONAL BREAKEVEN SL ORDER SET: ID = {conditional_sl_id}")
            else:
                print(f"❌ FAILED to set conditional breakeven SL: {conditional_sl_resp.get('msg')}")
        else:
            print(f"\n[CONDITIONAL SL] Remaining size after TP{trail_tp_level} is 0%. No conditional SL created.")
    
    # Trade execution complete - return to main loop to process next signal
    print(f"✅ Trade setup complete for {symbol}.")
