
# download_100_signals_private_FORCED.py
from telethon import TelegramClient
import re
from datetime import datetime
import asyncio

# ==================== EDIT ONLY THESE 3 LINES ====================
API_ID = 21062841                                 # ← your real number
API_HASH = "b6c864645d31a8c5fd128de70d5e2f64"     # ← your real hash (quotes!)
PRIVATE_CHANNEL_ID = -1001682398986               # ← your real -100... number
# =================================================================
# download_100_signals_private_FORCED.py


OUTPUT_FILE = 'telegram_messages.txt'
MAX_SIGNALS = 100

client = TelegramClient('download_forced_session', API_ID, API_HASH)

async def main():
    print("Step 1: Logging in to Telegram...")
    print("   → Open your Telegram app – you should receive a login code in a few seconds")

    # This FORCES visible prompts – you WILL see where to type
    await client.start(
        phone=lambda: input("   Enter phone number (with +country code): "),
        code_callback=lambda: input("   Enter the 5-digit code from Telegram: "),
        password=lambda: input("   Enter 2FA password (if you have one, else press Enter): ") or None
    )

    print("Login successful! Now downloading the last 100 PREMIUM SIGNALS...")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# Last {MAX_SIGNALS} PREMIUM SIGNALS – {datetime.now()}\n\n")

    count = 0
    async for message in client.iter_messages(PRIVATE_CHANNEL_ID, limit=None):
        if count >= MAX_SIGNALS:
            break
        if not message.message:
            continue

        text = message.message

        if ("PREMIUM SIGNAL" in text.upper() and
            "TARGET" not in text.upper() and
            "DONE" not in text.upper() and
            re.search(r'<[\d.]+-[\d.]+>', text)):

            timestamp = message.date.strftime("%Y-%m-%d %H:%M:%S")
            separator = "\n" + "="*80 + "\n"
            block = f"{separator}[{timestamp}] ID: {message.id}\n{text.strip()}\n"

            with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                f.write(block + "\n")

            count += 1
            print(f"Saved signal {count}/100 – {message.date.date()}")

    print(f"\nCOMPLETED! {count} signals saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        print("Double-check your API_ID, API_HASH and PRIVATE_CHANNEL_ID are correct and have no extra spaces.")