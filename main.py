# main.py – FINAL ×10 BOT – FILE MODE or REAL TELEGRAM MODE
import asyncio
import hashlib
from api import bingx_api_request
from bot_telegram import parse_signal, client as tg_client
from trade import execute_trade
from config import get_config
import getpass

print("\n" + "="*70)
print("   BINGX ×10 FUTURES BOT – LIVE MONEY")
print("="*70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

# Choose mode
mode = ""
while mode not in ['f', 'r']:
    mode = input("   File mode (f) or Real Telegram mode (r)? (f/r): ").strip().lower()

if mode == 'r':
    print("   → REAL TELEGRAM MODE – live signals from channel")
else:
    print("   → FILE MODE – reading from telegram_messages.txt")

print("="*70 + "\n")

base_url = "https://open-api.bingx.com"
client_bingx = {'api_key': api_key, 'secret_key': secret_key, 'base_url': base_url}
config = get_config()

async def get_balance():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/user/balance', client_bingx['api_key'], client_bingx['secret_key'])
    if resp.get('code') == 0 and resp.get('data'):
        bal = resp['data'][0].get('balance', {}).get('availableBalance')
        if bal is not None:
            return float(bal)
    return 6000.0

async def get_open_positions_count():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', client_bingx['api_key'], client_bingx['secret_key'])
    return len(resp.get('data', [])) if resp.get('code') == 0 else 0

async def main_loop():
    print("×10 BOT STARTED – Waiting for new signals...\n")
    traded_hashes = set()
    last_id = 0

    while True:
        try:
            balance = await get_balance()
            usdt_amount = balance * (config['usdt_per_trade_percent'] / 100)
            open_count = await get_open_positions_count()

            if open_count >= config['max_open_positions']:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            new_signal = None

            if mode == 'r':  # REAL TELEGRAM MODE
                messages = await tg_client.get_messages('me', limit=20)  # or your channel entity
                for msg in reversed(messages):
                    if msg.id <= last_id or not msg.message:
                        continue
                    signal = parse_signal(msg.message)
                    if signal:
                        signal_hash = hashlib.md5(signal['raw_text'].encode()).hexdigest()
                        if signal_hash not in traded_hashes:
                            new_signal = (signal, signal_hash, msg.id)
                            break

            else:  # FILE MODE
                with open('telegram_messages.txt', 'r', encoding='utf-8') as f:
                    content = f.read()
                for block in content.split('==='):
                    signal = parse_signal(block)
                    if signal:
                        signal_hash = hashlib.md5(signal['raw_text'].encode()).hexdigest()
                        if signal_hash not in traded_hashes:
                            new_signal = (signal, signal_hash, 0)
                            break

            if not new_signal:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            signal, signal_hash, msg_id = new_signal
            if msg_id > last_id:
                last_id = msg_id

            actual_leverage = min(signal['leverage'], 10)

            print(f"NEW SIGNAL → {signal['symbol']} {signal['direction']} {actual_leverage}x – ${usdt_amount:.0f}")
            await execute_trade(client_bingx, signal, usdt_amount, leverage=actual_leverage, config=config)

            traded_hashes.add(signal_hash)
            print(f"Trade executed – unique signals today: {len(traded_hashes)}\n")

            await asyncio.sleep(config['check_interval_seconds'])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main_loop())