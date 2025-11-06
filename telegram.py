# telegram.py – NO init_telegram
from telethon.tl.types import InputPeerChannel
from collections import deque
import time
import re

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

async def fetch_and_parse_telegram_signals(credentials_file, channel_details_file, limit, n_signals, client):
    signal_queue = deque()
    creds = read_credentials(credentials_file)
    with open(channel_details_file) as f:
        lines = f.readlines()
        channel_id = int(lines[0].split(':')[1].strip())
        access_hash = int(lines[1].split(':')[1].strip())

    try:
        if not client.is_connected():
            await client.start(phone=creds['phone'])

        entity = InputPeerChannel(channel_id, access_hash)
        messages = await client.get_messages(entity, limit=limit)

        for msg in messages:
            if "PREMIUM SIGNAL" in msg.message.upper() and time.time() - msg.date.timestamp() < 60:
                signal = parse_signal(msg.message)
                if signal:
                    signal_queue.append(signal)
                    print(f"New signal: {signal['symbol']} {signal['direction']} {signal['leverage']}x")

        result = list(signal_queue)[-n_signals:] if n_signals else list(signal_queue)
        return result

    except Exception as e:
        print(f"Telegram fetch error: {e}")
        return []

def parse_signal(text):
    try:
        symbol = re.search(r'\[([A-Z]+/USDT)\]', text).group(1).replace('/', '-PERP')
        direction = "LONG" if "LONG" in text.upper() else "SHORT"
        leverage = int(re.search(r'(\d+)X', text.upper()).group(1))
        entry_match = re.search(r'<([\d.]+)-([\d.]+)>', text)
        entry_min = float(entry_match.group(1))
        entry_max = float(entry_match.group(2))
        entry = (entry_min + entry_max) / 2
        targets = [float(x) for x in re.findall(r'\[`([\d.]+)`\]', text)[:4]]
        stoploss = float(re.search(r'STOPLOSS.*?`([\d.]+)`', text).group(1))
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