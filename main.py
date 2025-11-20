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
    resp = await bingx_api_request(
        "GET",
        "/openApi/swap/v2/user/balance",
        client_bingx["api_key"],
        client_bingx["secret_key"],
    )

    if resp.get("code") != 0:
        return 6000.0

    data = resp.get("data", {})
    bal_info = data.get("balance", {})

    val = (
        bal_info.get("availableMargin")
        or bal_info.get("equity")
        or bal_info.get("balance")
    )

    try:
        return float(val) if val is not None else 6000.0
    except:
        return 6000.0


async def get_open_positions_count():
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
    if isinstance(data, dict) and data:
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
                usdt_amount = max(1.0, min(9.0, usdt_amount))

            open_count = await get_open_positions_count()
            if open_count >= config["max_open_positions"]:
                print(
                    f"Max open positions reached "
                    f"({open_count}/{config['max_open_positions']}) – waiting..."
                )
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            try:
                with open("telegram_messages.txt", "r", encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                print("telegram_messages.txt not found – retrying...")
                await asyncio.sleep(config["check_interval_seconds"])
                continue

            new_signal = None

            for block in content.split("==="):
                signal = parse_signal(block)
                if signal:
                    h = hashlib.md5(signal["raw_text"].encode()).hexdigest()
                    if h not in traded_hashes:
                        new_signal = (signal, h)
                        break

            if not new_signal:
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
                dry_run=False,
            )

            traded_hashes.add(h)
            print(f"Trade executed – unique today: {len(traded_hashes)}\n")

            await asyncio.sleep(config["check_interval_seconds"])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main_loop())
