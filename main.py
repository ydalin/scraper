# main.py – FINAL REAL-TIME ×10 BINGX BOT (Live Telegram Listener)
import asyncio
import getpass
from api import bingx_api_request
from trade import execute_trade
from config import get_config
from bot_telegram import start_telegram_listener, signal_queue

print("\n" + "="*70)
print("   BINGX ×10 FUTURES BOT – LIVE MONEY + REAL-TIME TELEGRAM")
print("="*70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

test_mode = input("   Tiny test mode ($1–$9 + 1–2x) or Normal mode? (t/n) [n]: ").strip().lower() == 't'
mode_text = "TINY TEST MODE – $1–$9 + 1–2x leverage" if test_mode else "NORMAL MODE – 5.8% + 10x leverage"
print(f"   → {mode_text}")
print("="*70 + "\n")

# Global BingX client
client_bingx = {'api_key': api_key, 'secret_key': secret_key}
config = get_config()

# Robust balance fetch
async def get_balance():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/user/balance', api_key, secret_key)
    if resp.get('code') != 0:
        return 6000.0
    data = resp.get('data')
    if not data:
        return 6000.0
    if isinstance(data, list) and data:
        info = data[0]
    else:
        info = data
    bal = info.get('availableBalance') or info.get('balance', {}).get('availableBalance')
    try:
        return float(bal) if bal else 6000.0
    except:
        return 6000.0

# Count only real open positions
async def get_open_positions_count():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', api_key, secret_key)
    if resp.get('code') != 0:
        return 0
    positions = resp.get('data', [])
    if isinstance(positions, dict):
        positions = [positions]
    count = 0
    for p in positions:
        try:
            amt = float(p.get('positionAmt') or 0)
            if abs(amt) > 0.000001:
                count += 1
        except:
            continue
    return count

# Startup summary
async def print_startup_info():
    balance = await get_balance()
    trade_pct = config['usdt_per_trade_percent']
    usdt_amount = balance * (trade_pct / 100)
    if test_mode:
        usdt_amount = max(1.0, min(9.0, usdt_amount))

    print("STARTUP SUMMARY")
    print("-" * 55)
    print(f"Available Balance     : ${balance:,.2f}")
    if test_mode:
        print("Trade Size            : $1–$9 (tiny test mode)")
    else:
        print(f"Trade Size            : {trade_pct}% (~${usdt_amount:,.0f} USDT)")
    print(f"Leverage              : {'1–2x (test)' if test_mode else '10x'}")
    print(f"Max Open Positions    : {config['max_open_positions']}")
    print(f"TP Split              : {config['tp1_close_percent']}% / {config['tp2_close_percent']}% / {config['tp3_close_percent']}% / {config['tp4_close_percent']}%")
    print(f"Trailing Stop         : After TP{config['trailing_activate_after_tp']} → {config['trailing_callback_rate']}% callback")
    print(f"Stop Loss             : Max {config['stop_loss_percent']}% from entry")
    print(f"Order Type            : {config['order_type']}")
    print("-" * 55)
    print("BOT IS LIVE – Waiting for signals from your private Telegram channel...\n")

# Main trading loop (runs alongside Telegram listener)
async def trading_loop():
    await print_startup_info()

    while True:
        try:
            balance = await get_balance()
            usdt_amount = balance * (config['usdt_per_trade_percent'] / 100)
            if test_mode:
                usdt_amount = max(1.0, min(9.0, usdt_amount))

            open_count = await get_open_positions_count()
            if open_count >= config['max_open_positions']:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            # Wait for a new signal from Telegram (real-time!)
            try:
                signal, signal_hash = await asyncio.wait_for(
                    signal_queue.get(),
                    timeout=config['check_interval_seconds']
                )
            except asyncio.TimeoutError:
                continue  # No new signal, loop again

            # Apply leverage cap
            leverage = min(signal['leverage'], 2 if test_mode else 10)

            print(f"\nNEW LIVE SIGNAL → {signal['symbol']} {signal['direction']} {leverage}x")
            print(f"Entry ≈ {signal['entry']} | SL: {signal['stoploss']} | TPs: {signal['targets']}")
            print(f"Risking ${usdt_amount:.2f} USDT\n")

            await execute_trade(
                client=client_bingx,
                signal=signal,
                usdt_amount=usdt_amount,
                leverage=leverage,
                config=config,
                dry_run=False
            )

            print(f"TRADE EXECUTED & ORDERS PLACED – {signal['symbol']}\n")

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(10)

# Final entry point
if __name__ == '__main__':
    async def run_bot():
        print("Starting BingX ×10 Bot with real-time Telegram integration...\n")
        await asyncio.gather(
            start_telegram_listener(),   # Listens to your private channel forever
            trading_loop()               # Handles trading logic
        )

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user. Goodbye!")