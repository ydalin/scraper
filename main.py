# main.py – FINAL ×10 BOT (tiny test mode or full power)
import asyncio
import hashlib
from api import bingx_api_request
from bot_telegram import parse_signal
from trade import execute_trade
from config import get_config
import getpass

print("\n" + "="*70)
print("   BINGX ×10 FUTURES BOT – LIVE MONEY")
print("="*70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

test = input("   Tiny test mode ($1–$9 + 1–2x) or Normal mode? (t/n) [n]: ").strip().lower() == 't'
if test:
    print("   → TINY TEST MODE – $1–$9 per trade + 1–2x leverage")
else:
    print("   → NORMAL MODE – 5.8% per trade + 10x leverage")
print("="*70 + "\n")

client_bingx = {'api_key': api_key, 'secret_key': secret_key, 'base_url': "https://open-api.bingx.com"}
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

    while True:
        try:
            balance = await get_balance()
            usdt_amount = balance * (config['usdt_per_trade_percent'] / 100)
            if test:
                usdt_amount = max(1.0, min(9.0, usdt_amount))

            open_count = await get_open_positions_count()
            if open_count >= config['max_open_positions']:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            with open('telegram_messages.txt', 'r', encoding='utf-8') as f:
                content = f.read()

            new_signal = None
            for block in content.split('==='):
                signal = parse_signal(block)
                if signal:
                    h = hashlib.md5(signal['raw_text'].encode()).hexdigest()
                    if h not in traded_hashes:
                        new_signal = (signal, h)
                        break

            if not new_signal:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            signal, h = new_signal
            lev = min(signal['leverage'], 2 if test else 10)

            print(f"NEW SIGNAL → {signal['symbol']} {signal['direction']} {lev}x – ${usdt_amount:.2f}")
            await execute_trade(client_bingx, signal, usdt_amount, leverage=lev, config=config)

            traded_hashes.add(h)
            print(f"Trade executed – unique today: {len(traded_hashes)}\n")

            await asyncio.sleep(config['check_interval_seconds'])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main_loop())