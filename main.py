# main.py – FINAL – LIVE TELEGRAM + FORCED PROMPTS (never hangs silently)
import asyncio
import hashlib
import getpass
from telethon import TelegramClient, events
from api import bingx_api_request
from trade import execute_trade
from config import get_config

print("\n" + "="*70)
print("   BINGX ×10 FUTURES BOT – LIVE FROM TELEGRAM CHANNEL")
print("="*70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

test = input("   Tiny test mode ($1–$9 + 1–2x) or Normal mode? (t/n) [n]: ").strip().lower() == 't'
print("   → TINY TEST MODE – $1–$9 + 1–2x leverage" if test else "   → NORMAL MODE – 5.8% + 10x leverage")
print("="*70 + "\n")

# === YOUR TELEGRAM CREDENTIALS (CHANGE THESE) ===
API_ID = 12345678                                   # ← your api_id
API_HASH = 'your_api_hash_here'                     # ← your api_hash
CHANNEL_ID = -1001682398986                         # ← your private channel ID

tg_client = TelegramClient('live_bot_session', API_ID, API_HASH)

client_bingx = {'api_key': api_key, 'secret_key': secret_key, 'base_url': "https://open-api.bingx.com"}
config = get_config()

# === FORCE VISIBLE LOGIN PROMPTS ===
async def telegram_login():
    print("Connecting to Telegram...")
    await tg_client.start(
        phone=lambda: input("   Enter phone number (with +country code): "),
        code_callback=lambda: input("   Enter the 5-digit code from Telegram: "),
        password=lambda: input("   2FA password (if any, else press Enter): ") or None
    )
    print("Telegram login successful!\n")

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

# === REAL-TIME LISTENER ===
traded_hashes = set()

@tg_client.on(events.NewMessage(chats=CHANNEL_ID))
async def handler(event):
    global traded_hashes
    if not event.message or not event.message.message:
        return

    from bot_telegram import parse_signal
    signal = parse_signal(event.message.message)
    if not signal:
        return

    h = hashlib.md5(signal['raw_text'].encode()).hexdigest()
    if h in traded_hashes:
        return

    balance = await get_balance()
    usdt_amount = balance * (config['usdt_per_trade_percent'] / 100)
    if test:
        usdt_amount = max(1.0, min(9.0, usdt_amount))

    open_count = await get_open_positions_count()
    if open_count >= config['max_open_positions']:
        print(f"[SAFETY] Max {config['max_open_positions']} positions open – skipping")
        return

    lev = min(signal['leverage'], 2 if test else 10)

    print(f"\nLIVE SIGNAL → {signal['symbol']} {signal['direction']} {lev}x – ${usdt_amount:.2f}")
    await execute_trade(client_bingx, signal, usdt_amount, leverage=lev, config=config)

    traded_hashes.add(h)
    print(f"Trade executed – total today: {len(traded_hashes)}\n")

async def main():
    await telegram_login()
    print("×10 BOT STARTED – Listening to channel 24/7...\n")
    await tg_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())