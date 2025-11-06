# test_bot.py – THOROUGH TESTING SUITE (DRY-RUN MODE – NO REAL ORDERS)
import asyncio
from telegram import read_credentials
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel
from api import bingx_api_request

# === CONFIG (MATCHES main.py) ===
CREDENTIALS_FILE = 'credentials.txt'
CHANNEL_FILE = 'channel_details.txt'
SAFE_USDT = 1000.0
LEVERAGE = 20
SYMBOL = "XNY-USDT"
POSITION_SIDE = "SHORT"
ENTRY_PRICE = 0.00463
MAX_POSITION_VALUE = 25000.0  # BingX limit for 20x

async def test_telegram_connection():
    print("\n1. Testing Telegram Connection...")
    creds = read_credentials(CREDENTIALS_FILE)
    api_id = int(creds['api_id'])
    api_hash = creds['api_hash']
    phone = input("Enter Phone Number (with +): ").strip()

    client = TelegramClient('test_session', api_id, api_hash)
    try:
        await client.start(phone=phone)
        print("Telegram connected!")
        await client.disconnect()
        return True
    except Exception as e:
        print(f"Telegram failed: {e}")
        return False

async def test_channel_access():
    print("\n2. Testing Channel Access...")
    try:
        with open(CHANNEL_FILE) as f:
            lines = f.readlines()
            channel_id = int(lines[0].split(':')[1].strip())
            access_hash = int(lines[1].split(':')[1].strip())
    except Exception as e:
        print(f"Channel file error: {e}")
        return False

    creds = read_credentials(CREDENTIALS_FILE)
    api_id = int(creds['api_id'])
    api_hash = creds['api_hash']
    phone = input("Enter Phone Number (with +): ").strip()

    client = TelegramClient('test_session', api_id, api_hash)
    try:
        await client.start(phone=phone)
        entity = InputPeerChannel(channel_id, access_hash)
        messages = await client.get_messages(entity, limit=5)
        print(f"Channel access OK – {len(messages)} messages")
        await client.disconnect()
        return True
    except Exception as e:
        print(f"Channel access failed: {e}")
        return False

async def test_bingx_balance():
    print("\n3. Testing BingX Balance...")
    creds = read_credentials(CREDENTIALS_FILE)
    api_key = creds['bingx_api_key']
    secret_key = input("Enter BingX Secret Key: ").strip()

    try:
        bal = await bingx_api_request('GET', '/openApi/swap/v2/user/balance', api_key, secret_key)
        if bal.get('code') == 0:
            available = float(bal['data']['balance']['availableMargin'])
            print(f"BingX balance: {available} USDT")
            return available >= SAFE_USDT
        else:
            print(f"BingX API error: {bal.get('msg')}")
            return False
    except Exception as e:
        print(f"BingX connection failed: {e}")
        return False

async def test_place_order():
    print("\n4. Testing Order Placement (DRY-RUN MODE – NO REAL ORDER)...")
    creds = read_credentials(CREDENTIALS_FILE)
    api_key = creds['bingx_api_key']
    secret_key = input("Enter BingX Secret Key: ").strip()

    # === SET LEVERAGE (REAL CALL – REQUIRED BY BINGX) ===
    try:
        await bingx_api_request('POST', '/openApi/swap/v2/trade/leverage', api_key, secret_key,
                                data={'symbol': SYMBOL, 'leverage': LEVERAGE, 'openType': 'cross'})
        print(f"Leverage set to {LEVERAGE}x")
    except Exception as e:
        print(f"Leverage set failed: {e}")
        return False

    # === DRY-RUN ORDER (NO REAL TRADE) ===
    qty = (SAFE_USDT * LEVERAGE) / ENTRY_PRICE
    position_value = SAFE_USDT * LEVERAGE

    if position_value > MAX_POSITION_VALUE:
        print(f"Position value {position_value} USDT exceeds max {MAX_POSITION_VALUE} USDT for 20x")
        return False

    order_data = {
        'symbol': SYMBOL,
        'side': 'SELL',
        'positionSide': POSITION_SIDE,
        'type': 'MARKET',
        'quantity': f"{qty:.6f}",
        'leverage': LEVERAGE
    }

    print(f"[DRY-RUN] Would place order: {order_data}")
    print(f"Position value: {position_value} USDT (max {MAX_POSITION_VALUE})")
    return True  # Simulate success

async def run_all_tests():
    print("THOROUGH TEST SUITE – WEEK 1 BOT (DRY-RUN MODE)")
    print("="*60)

    results = {
        "Telegram Connection": await test_telegram_connection(),
        "Channel Access": await test_channel_access(),
        "BingX Balance": await test_bingx_balance(),
        "Place Order (Dry-Run)": await test_place_order()
    }

    print("\n" + "="*60)
    print("TEST RESULTS")
    print("="*60)
    for test, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"{test:25}: {status}")

    if all(results.values()):
        print("\nALL TESTS PASSED – BOT IS READY FOR WEEK 1 (DRY-RUN)!")
        print("No real orders placed. Safe to run.")
    else:
        print("\nFix failures before going live.")

if __name__ == '__main__':
    asyncio.run(run_all_tests())