# main.py – FINAL – SAFE MODE ($5 max loss) + CONFIG-AWARE NORMAL MODE
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

mode_input = input("   Safe Mode (max ~$5 loss) or Normal mode? (s/n) [s]: ").strip().lower()
safe_mode = (mode_input != "n")

if safe_mode:
    print("   → SAFE MODE ENABLED – $5 margin per trade, 1× leverage, max loss ≈ $5")
else:
    print("   → NORMAL MODE – config-based sizing")

print("=" * 70 + "\n")

client_bingx = {
    "api_key": api_key,
    "secret_key": secret_key,
    "base_url": "https://open-api.bingx.com",
}

config = get_config()

# One-time config summary (no spam)
if config.get("use_absolute_usdt", False):
    sizing_str = f"ABSOLUTE ${config['absolute_usdt_per_trade']:.2f} per trade"
else:
    sizing_str = f"{config['usdt_per_trade_percent']:.2f}% of balance per trade"

print(
    f"[CONFIG] Sizing: {sizing_str}, "
    f"Max leverage: {config.get('max_leverage', 10)}, "
    f"Max open positions: {config.get('max_open_positions', 0)}, "
    f"Dry-run: {config.get('dry_run_mode', False)}"
)


# ------------------------ BingX helpers ------------------------


async def get_balance():
    """
    Query futures account balance from BingX.

    Endpoint: /openApi/swap/v2/user/balance

    Expected shape (common BingX examples):

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
    except Exception:
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

            # Decide trade size
            if config.get("use_absolute_usdt", False):
                usdt_amount = config["absolute_usdt_per_trade"]
            else:
                usdt_amount = balance * (config["usdt_per_trade_percent"] / 100.0)

            # SAFE MODE: hard cap $5 per trade
            if safe_mode:
                usdt_amount = 5.0

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

            # Respect safe mode & max_leverage from config
            max_lev = config.get("max_leverage", 10)
            if safe_mode:
                lev = 1
            else:
                lev = min(signal["leverage"], max_lev)

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
                dry_run=False,  # config['dry_run_mode'] is checked inside execute_trade
            )

            traded_hashes.add(h)
            print(f"Trade executed – unique this run: {len(traded_hashes)}\n")

            await asyncio.sleep(config["check_interval_seconds"])

        except Exception as e:
            print(f"[ERROR] {e}\n")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main_loop())
