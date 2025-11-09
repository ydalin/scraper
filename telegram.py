# bot_telegram.py
from telethon import TelegramClient, events
from collections import deque
import time

client = None
signal_queue = deque()

def init_telegram(api_id, api_hash):
    global client
    client = TelegramClient('session', api_id, api_hash)

async def fetch_and_parse_telegram_signals(credentials_file, channel_details_file, limit, n_signals):
    global signal_queue
    creds = {}
    with open(credentials_file) as f:
        for line in f:
            k, v = line.strip().split(':', 1)
            creds[k.strip()] = v.strip()
    channel_id, access_hash = map(int, open(channel_details_file).read().splitlines()[1:3])

    await client.start(phone=creds['phone'])
    entity = await client.get_entity(int(channel_id))
    messages = await client.get_messages(entity, limit=limit)

    for msg in messages:
        if "PREMIUM SIGNAL" in msg.message and time.time() - msg.date.timestamp() < 60:
            signal = parse_signal(msg.message)
            if signal:
                signal_queue.append(signal)
    return list(signal_queue)[-n_signals:] if n_signals else list(signal_queue)

def parse_signal(text):
    import re
    try:
        symbol = re.search(r'\[([A-Z]+/USDT)\]', text).group(1).replace('/', '-PERP')
        direction = "LONG" if "LONG" in text else "SHORT"
        leverage = int(re.search(r'(\d+)X', text).group(1))
        entry = re.search(r'<([\d.]+)-([\d.]+)>', text)
        entry_min, entry_max = float(entry.group(1)), float(entry.group(2))
        targets = [float(x) for x in re.findall(r'\[`([\d.]+)`\]', text)[:4]]
        stoploss = float(re.search(r'STOPLOSS.*?`([\d.]+)`', text).group(1))
        return {**locals(), 'entry': (entry_min + entry_max)/2}
    except:
        return None