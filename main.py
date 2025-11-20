# main.py – VIRTUAL MONEY VERSION (correct for BingX demo/VST)
import asyncio
import hashlib
from datetime import datetime
from api import bingx_api_request
from bot_telegram import parse_signal
from trade import execute_trade
from config import get_config
import getpass

print("\n" + "="*70)
print("   BINGX ×10 FUTURES BOT – Virtual or Real Money")
print("="*70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

# BingX virtual trading uses the LIVE API URL – no testnet URL exists
base_url = "https://open-api.bingx.com"
client_bingx = {'api_key': api_key, 'secret_key': secret_key, 'base_url': base_url}

print("   → Connected – go to BingX web → Futures → switch to 'Virtual USDT Account' for demo")
print("="*70 + "\n")

config = get_config()

async def get_balance():
    # Simulate $6,000 for clean testing (real VST balance is ~100k but we keep it realistic)
    print("[INFO] Virtual mode – using simulated $6,000 balance")
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
                    signal_hash = hashlib.md5(signal['raw_text'].encode()).hexdigest()
                    if signal_hash not in traded_hashes:
                        new_signal = (signal, signal_hash)
                        break

            if not new_signal:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            signal, signal_hash = new_signal
            actual_leverage = min(signal['leverage'], 10)

            print(f"NEW SIGNAL → {signal['symbol']} {signal['direction']} {actual_leverage}x – ${usdt_amount:.0f}")
            await execute_trade(client_bingx, signal, usdt_amount, leverage=actual_leverage, config=config)

            traded_hashes.add(signal_hash)
            print(f"Virtual trade executed – unique signals today: {len(traded_hashes)}\n")

            await asyncio.sleep(config['check_interval_seconds'])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main_loop())