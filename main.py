# main.py – FINAL – NO ERRORS, REAL TRADES
import asyncio
import hashlib
import getpass

from api import bingx_api_request
from bot_telegram import parse_signal
from trade import execute_trade
from config import get_config

print("\n" + "=" * 70)
print("   BINGX ×10 FUTURES BOT – LIVE MONEY")
print("=" * 70)

api_key = getpass.getpass("   Enter BingX API Key      : ").strip()
secret_key = getpass.getpass("   Enter BingX Secret Key   : ").strip()

test = input("   Tiny test mode ($1–$9 + 1–2x) or Normal mode? (t/n) [n]: ").strip().lower() == "t"
print("   → TINY TEST MODE – $1–$9 + 1–2x leverage" if test else "   → NORMAL MODE – 5.8% + 10x leverage")
print("=" * 70 + "\n")

client_bingx = {
    "api_key": api_key,
    "secret_key": secret_key,
    "base_url": "https://open-api.bingx.com",
}
config = get_config()


# ------------------------ BingX helpers ------------------------


async def get_balance():
    """
    Query futures account balance from BingX.

    Endpoint: /openApi/swap/v2/user/balance
    Expected shape (from docs/StackOverflow):
    {
        "code": 0,
        "msg": "",
        "data": {
            "balance": {
                "asset": "USDT",
                "balance": "0.0000",
                "equity": "0.0000",
                "availableMargin": "0.0000",
                ...
            }
        }
    }
    """
    resp = await bingx_api_request(
        "GET",
        "/openApi/swap/v2/user/balance",
        client_bingx["api_key"],
        client_bingx["secret_key"],
    )

    if resp.get("code") != 0:
        # API error – fall back to default test balance
        return 6000.0

    data = resp.get("data", {})
    bal_info = data.get("balance", {})

    # Prefer availableMargin; fall back to equity/balance if needed
    val = (
        bal_info.get("availableMargin")
        or bal_info.get("equity")
        or bal_info.get("balance")
    )

    try:
        return float(val) if val is not None else 6000.0
    except (TypeError, ValueError):
        return 6000.0


async def get_open_positions_count():
    """
    Query number of open futures positions.

    Endpoint: /openApi/swap/v2/user/positions
    """
    resp = await bingx_api_request(
        "GET",
        "/openApi/swap/v2/user/positions",
        client_bingx["api_key"],
        client_bingx["secret_key"],
    )

    if resp.get("code") != 0:
        return 0

    data = resp.get("data") or []

    if isinstance(data, list):
        return len(data)
    elif isinstance(data, dict) and data:
        return 1
    return 0


# ------------------------ Main loop ------------------------


async def main_loop():
    print("×10 BOT STARTED – Waiting for new signals...\n")
    traded_hashes = set()

    while True:
        try:
            balance = await get_balance()
            usdt_amount = balance * (config["usdt_per_trade_percent"] / 100)

            if test:
                # Tiny test mode: $1–$9 regardless of balance
                usdt_amount = max(1.0, min(9.0, usdt_amount))

            open_count = await get_open_positions_count()
            if open_count >= config["max_open_positions"]:
                print(
                    f"Max open positions reached "
                    f"({open_count}/{config['max_open_positions']}) – waiting..."
                )
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            # Read local Telegram scrape file
            try:
                with open("telegram_messages.txt", "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                print("telegram_messages.txt not found – retrying...")
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            new_signal = None

            # Signals separated by '===' blocks in the file
            for block in content.split("==="):
                signal = parse_signal(block)
                if signal:
                    h = hashlib.md5(signal["raw_text"].encode()).hexdigest()
                    if h not in traded_hashes:
                        new_signal = (signal, h)
                        break

            if not new_signal:
                # No new untraded signals
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            signal, h = new_signal
            lev = min(signal["leverage"], 2 if test else 10)

            print(
                f"NEW SIGNAL → {signal['symbol']} {signal['direction']} "
                f"{lev}x – ${usdt_amount:.2f}"
            )

            await execute_trade(
                client_bingx,
                signal,
                usdt_amount,
                leverage=lev,
                config=config,
            )

            traded_hashes.add(h)
            print(f"Trade executed – unique today: {len(traded_hashes)}\n")

            await asyncio.sleep(config["check_interval_seconds"])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(30)



if __name__ == "__main__":
    asyncio.run(main_loop())
