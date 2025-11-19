# main.py – FINAL ×10 VERSION
import asyncio
from datetime import datetime
from api import bingx_api_request
from bot_telegram import parse_signal
from trade import execute_trade
from config import get_config

config = get_config()
client_bingx = {'api_key': 'YOUR_KEY', 'secret_key': 'YOUR_SECRET', 'base_url': 'https://open-api.bingx.com'}

async def get_balance():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/user/balance', client_bingx['api_key'], client_bingx['secret_key'])
    if resp.get('code') == 0:
        data = resp.get('data', [{}])[0]
        return float(data.get('balance', {}).get('availableBalance', 6000))
    return 6000.0

async def get_open_positions_count():
    resp = await bingx_api_request('GET', '/openApi/swap/v2/trade/position', client_bingx['api_key'], client_bingx['secret_key'])
    if resp.get('code') == 0:
        return len(resp.get('data', []))
    return 0

async def main_loop():
    print("×10 BOT STARTED – $6k → $1k–$2k+ daily plan")
    traded_today = set()

    while True:
        try:
            balance = await get_balance()
            usdt_amount = balance * (config['usdt_per_trade_percent'] / 100)
            open_count = await get_open_positions_count()

            if open_count >= config['max_open_positions']:
                print(f"[SAFETY] {open_count} positions open – waiting...")
                await asyncio.sleep(config['check_interval_seconds'])
                continue

            # Read signals from file (replace with live Telegram if you want)
            with open('telegram_messages.txt', 'r', encoding='utf-8') as f:
                content = f.read()

            signals = [parse_signal(block) for block in content.split('===')]
            signals = [s for s in signals if s and s['symbol'] not in traded_today]

            for signal in signals[:1]:  # Process one new signal at a time
                if open_count >= config['max_open_positions']:
                    break

                # CAP LEVERAGE TO 10x
                actual_leverage = min(signal['leverage'], 10)
                print(f"\nEXECUTING {signal['symbol']} {signal['direction']} {actual_leverage}x – ${usdt_amount:.0f}")

                await execute_trade(client_bingx, signal, usdt_amount, leverage=actual_leverage, config=config)

                traded_today.add(signal['symbol'])
                open_count += 1

            await asyncio.sleep(config['check_interval_seconds'])

        except Exception as e:
            print(f"[ERROR] {e}")
            await asyncio.sleep(30)

if __name__ == '__main__':
    asyncio.run(main_loop())