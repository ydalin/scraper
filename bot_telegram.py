# bot_telegram.py – LIVE REAL-TIME SIGNAL LISTENER (Telethon + Event Handler)
from telethon import TelegramClient, events
import hashlib
import re
import asyncio
import os

# === CONFIGURATION ===
API_ID = 12345678          # ← CHANGE TO YOUR TELEGRAM API_ID
API_HASH = "your_api_hash_here"   # ← CHANGE TO YOUR API_HASH
PRIVATE_CHANNEL_ID = -1001682398986   # ← Your private channel ID (keep the -100 prefix)

# Optional: Store session in file to avoid re-login every time
SESSION_NAME = "bingx_bot_session"

# Global queue to send signals to main.py
signal_queue = asyncio.Queue()

# Initialize client globally
client = None


def init_telegram():
    """Call this once at bot startup"""
    global client
    if client is not None:
        return client

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    return client


def parse_signal(text: str):
    """Same parser as before — rock solid"""
    if not text or "PREMIUM SIGNAL" not in text.upper():
        return None

    try:
        direction = "LONG" if any(x in text.upper() for x in ["LONG", "BUY"]) else "SHORT"

        symbol_match = re.search(r'[🟢🔴]?\s*([A-Z0-9]+/?USDT)', text, re.IGNORECASE)
        if not symbol_match:
            return None
        symbol = symbol_match.group(1).upper().replace("/", "")

        lev_match = re.search(r'(\d+)X', text, re.IGNORECASE)
        if not lev_match:
            return None
        leverage = int(lev_match.group(1))

        entry_match = re.search(r'<([\d.]+)-([\d.]+)>', text)
        if not entry_match:
            return None
        entry_min = float(entry_match.group(1))
        entry_max = float(entry_match.group(2))
        entry = (entry_min + entry_max) / 2

        targets = []
        for m in re.finditer(r'\[([\d.]+)\]', text):
            targets.append(float(m.group(1)))
        if len(targets) < 4:
            return None
        targets = targets[:4]

        sl_match = re.search(r'STOPLOSS.*?([\d.]+)', text, re.IGNORECASE)
        if sl_match:
            stoploss = float(sl_match.group(1))
        else:
            all_brackets = [float(m.group(1)) for m in re.finditer(r'\[([\d.]+)\]', text)]
            stoploss = all_brackets[-1] if len(all_brackets) > 4 else None
            if not stoploss:
                return None

        return {
            'symbol': symbol,
            'direction': direction,
            'leverage': leverage,
            'entry': entry,
            'entry_min': entry_min,
            'entry_max': entry_max,
            'targets': targets,
            'stoploss': stoploss,
            'raw_text': text
        }

    except Exception as e:
        print(f"[PARSE ERROR] {e}\n{text[:200]}")
        return None


# === EVENT LISTENER (This runs forever and feeds signals into queue) ===
@events.register(events.NewMessage(chats=PRIVATE_CHANNEL_ID))
async def live_signal_handler(event):
    msg = event.message.message
    if not msg or "PREMIUM SIGNAL" not in msg.upper():
        return

    signal = parse_signal(msg)
    if not signal:
        return

    # Duplicate protection by hash
    signal_hash = hashlib.md5(signal['raw_text'].encode()).hexdigest()

    # Avoid duplicates in the same session
    if hasattr(live_signal_handler, "seen_hashes"):
        if signal_hash in live_signal_handler.seen_hashes:
            return
    else:
        live_signal_handler.seen_hashes = set()

    live_signal_handler.seen_hashes.add(signal_hash)

    print(f"\nNEW LIVE SIGNAL → {signal['symbol']} {signal['direction']} {signal['leverage']}x")
    await signal_queue.put((signal, signal_hash))


async def start_telegram_listener():
    """Start the Telegram client and begin listening"""
    global client
    client = init_telegram()

    print("Connecting to Telegram...")
    await client.start()
    print(f"Logged in as {await client.get_me().then(lambda u: u.first_name)}")
    print(f"Listening to private channel: {PRIVATE_CHANNEL_ID}")

    # Register the event handler
    client.add_event_handler(live_signal_handler)

    # Keep alive
    await client.run_until_disconnected()