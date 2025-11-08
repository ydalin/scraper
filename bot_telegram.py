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
    try:
        symbol = re.search(r'\[([A-Z]+/USDT)\]', text).group(1)
        direction = "LONG" if "LONG" in text.upper() else "SHORT"
        leverage = int(re.search(r'(\d+)X', text.upper()).group(1))
        entry_match = re.search(r'<([\d.]+)-([\d.]+)>', text)
        entry_min = float(entry_match.group(1))
        entry_max = float(entry_match.group(2))
        if entry_min > entry_max:
            entry_min, entry_max = entry_max, entry_min
        entry = (entry_min + entry_max) / 2
        targets = [float(x) for x in re.findall(r'\[`?([\d.]+)`?\]', text)[:4]]
        stoploss = float(re.search(r'STOPLOSS.*?`?([\d.]+)`?', text).group(1))
        return {
            'symbol': symbol,
            'direction': direction,
            'leverage': leverage,
            'entry_min': entry_min,
            'entry_max': entry_max,
            'entry': entry,
            'targets': targets,
            'stoploss': stoploss,
            'text': text
        }
    except Exception as e:
        print(f"[PARSE ERROR] {e}")
        return None