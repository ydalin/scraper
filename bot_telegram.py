# bot_telegram.py – FINAL
from telethon import TelegramClient
import re

client = None

def init_telegram(api_id, api_hash):
    global client
    client = TelegramClient('session', api_id, api_hash)

def read_credentials(credentials_file='credentials.txt'):
    creds = {}
    try:
        with open(credentials_file) as f:
            for line in f:
                if ':' in line:
                    k, v = line.strip().split(':', 1)
                    creds[k.strip()] = v.strip()
    except Exception as e:
        print(f"Error reading credentials: {e}")
    return creds

def parse_signal(text):
    if not text or "PREMIUM SIGNAL" not in text.upper():
        return None

    try:
        # Direction
        direction = "LONG" if "LONG" in text.upper() or "BUY" in text.upper() else "SHORT"

        # Symbol - handles both 🟢 SYMBOL/USDT and plain SYMBOL/USDT
        symbol_match = re.search(r'[🟢🔴]?\s*([A-Z0-9]+/USDT)', text, re.IGNORECASE)
        if not symbol_match:
            return None
        symbol = symbol_match.group(1).upper()

        # Leverage - handles 20X, 50X, 75X, etc.
        lev_match = re.search(r'(\d+)X', text, re.IGNORECASE)
        if not lev_match:
            return None
        leverage = int(lev_match.group(1))

        # Entry range - <0.00117-0.00118>
        entry_match = re.search(r'<([\d.]+)-([\d.]+)>', text)
        if not entry_match:
            return None
        entry_min = float(entry_match.group(1))
        entry_max = float(entry_match.group(2))
        entry = (entry_min + entry_max) / 2

        # Targets - extract all [number] in order
        targets = []
        for m in re.finditer(r'\[([\d.]+)\]', text):
            targets.append(float(m.group(1)))
        if len(targets) < 4:
            return None
        targets = targets[:4]  # Take first 4 only

        # Stoploss - STOPLOSS: [0.00102] or just [0.00102]
        sl_match = re.search(r'STOPLOSS.*?([\d.]+)', text, re.IGNORECASE)
        if not sl_match:
            # Fallback: last [number] after targets
            if len(targets) >= 4:
                # Usually stoploss is the last bracketed number after targets
                all_brackets = [float(m.group(1)) for m in re.finditer(r'\[([\d.]+)\]', text)]
                if len(all_brackets) > 4:
                    stoploss = all_brackets[-1]
                else:
                    return None
            else:
                return None
        else:
            stoploss = float(sl_match.group(1))

        print(f"[PARSED SUCCESS] {symbol} {direction} {leverage}x Entry ~{entry} | TP4: {targets[3]} | SL: {stoploss}")

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
        print(f"[PARSE FAILED] {e}\nFirst 200 chars: {text[:200]}")
        return None
