# main.py – FINAL ×10 BOT (November 20, 2025) – READY TO RUN
import asyncio
import hashlib
from datetime import datetime
from api import bingx_api_request
from bot_telegram import parse_signal
from trade import execute_trade
from config import get_config
import getpass

print("\n" + "="*60)
print("   BINGX ×10 BOT – ENTER CREDENTIALS (never saved)")
print("="*60)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

env = input("   Testnet (t) or Live (l)? [l]: ").strip().lower() or 'l'
base_url = "https://open-api-vst.bingx.com" if env == 't' else "https://open-api.bingx.com"

client_bingx = {
    'api_key': api_key,
    'secret_key': secret_key,
    'base_url': base_url
}

print(f"   Connected to {'TESTNET (virtual money)' if env == 't' else 'LIVE ACCOUNT'}")
print("="*60 + "\n")

config = get_config()


async def get_balance():
    if 'vst' in client_bingx['base_url']:  # ← TESTNET detected
        print("[TESTNET MODE] Using virtual $6,000 balance (same as live)")
        return 6000.0  # ← Forces same as real account

    # LIVE account – get real balance
    resp = await bingx_api_request('GET', '/openApi/swap/v2/user/balance', client_bingx['api_key'],
                                   client_bingx['secret_key'])
    if resp.get('code') == 0 and resp.get('data'):
        bal = resp['data'][0].get('balance', {}).get('availableBalance')
        if bal is not None:
            return float(bal)
    return 6000.0  # fallback

async def get_open_positions_count():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', client_bingx['api_key'], client_bingx['secret_key'])
    if resp.get('code') == 0:
        return len(resp.get('data', []))
    return 0

async def main_loop():
    print("×10 BOT STARTED – $6k → $1k–$2k+ daily plan")
    traded_hashes = set()          # ← DUPLICATE PROTECTION (by exact signal text)

    while True:
        try:
            balance = await get_balance()
            usdt_amount = balance * (config['usdt_per_trade_percent'] / 100)
            open_count = await get_open_positions_count()

            if open_count >= config['max_open_positions']:
                print(f"[SAFETY] {open_count}/{config['max_open_positions']} positions open – waiting 8s...")
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            with open('telegram_messages.txt', 'r', encoding='utf-8') as f:
                content = f.read()

            new_signals = []
            for block in content.split('==='):
                signal = parse_signal(block)
                if signal:
                    signal_hash = hashlib.md5(signal['raw_text'].encode()).hexdigest()
                    if signal_hash not in traded_hashes:
                        new_signals.append((signal, signal_hash))

            if not new_signals:
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            # Take the newest signal only
            signal, signal_hash = new_signals[-1]
            actual_leverage = min(signal['leverage'], 10)

            print(f"\nNEW SIGNAL → {signal['symbol']} {signal['direction']} {actual_leverage}x – ${usdt_amount:.0f}")
            await execute_trade(client_bingx, signal, usdt_amount, leverage=actual_leverage, config=config)

            traded_hashes.add(signal_hash)
            print(f"Signal processed – total unique signals today: {len(traded_hashes)}")

            await asyncio.sleep(config['check_interval_seconds'])

        except Exception as e:
            print(f"[ERROR] {e}")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main_loop())