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
    """Parse trading signal from Telegram message text.
    Returns None if the message is not a valid PREMIUM SIGNAL."""
    try:
        # Early return if not a PREMIUM SIGNAL message
        if not text or "PREMIUM SIGNAL" not in text.upper():
            return None
        
        # Additional check: Must contain ENTRY, TARGETS, and STOPLOSS keywords
        # This prevents target update messages like "TARGET #2 DONE" from being parsed
        required_keywords = ["ENTRY", "TARGETS", "STOPLOSS"]
        if not all(keyword in text.upper() for keyword in required_keywords):
            return None
        
        # Check for symbol - handle both formats:
        # Format 1: [SYMBOL/USDT] (with brackets)
        # Format 2: 🔴SYMBOL/USDT or 🔵SYMBOL/USDT (with emoji, no brackets)
        # Match SYMBOL/USDT where SYMBOL can be alphanumeric
        symbol_match = re.search(r'(?:\[([A-Z0-9]+/USDT)\]|([A-Z0-9]+/USDT)\s+(?:SHORT|LONG))', text, re.IGNORECASE)
        if not symbol_match:
            return None
        # Get the first non-None group (whichever format matched)
        symbol = symbol_match.group(1) or symbol_match.group(2)
        
        # Check for direction
        direction = "LONG" if "LONG" in text.upper() else "SHORT"
        
        # Check for leverage - handle both "50X" and "50x" formats
        leverage_match = re.search(r'(\d+)[Xx]', text)
        if not leverage_match:
            return None
        leverage = int(leverage_match.group(1))
        
        # Check for entry range
        entry_match = re.search(r'<([\d.]+)-([\d.]+)>', text)
        if not entry_match:
            return None
        entry_min = float(entry_match.group(1))
        entry_max = float(entry_match.group(2))
        if entry_min > entry_max:
            entry_min, entry_max = entry_max, entry_min
        entry = (entry_min + entry_max) / 2
        
        # Check for targets - look for numbered targets section
        # Format: 1. [0.05261] 2. [0.05208] etc.
        targets = []
        # First try to find targets in the TARGETS section
        targets_section = re.search(r'TARGETS:.*?STOPLOSS', text, re.DOTALL | re.IGNORECASE)
        if targets_section:
            targets_text = targets_section.group(0)
            targets_match = re.findall(r'\[([\d.]+)\]', targets_text)
            targets = [float(x) for x in targets_match[:4]]
        else:
            # Fallback: find all [number] patterns and take first 4
            targets_match = re.findall(r'\[([\d.]+)\]', text)
            targets = [float(x) for x in targets_match[:4]]
        
        if not targets:
            return None
        
        # Check for stoploss - look for STOPLOSS: [number] format
        stoploss_match = re.search(r'STOPLOSS.*?\[([\d.]+)\]', text, re.IGNORECASE)
        if not stoploss_match:
            # Fallback: try without brackets
            stoploss_match = re.search(r'STOPLOSS.*?([\d.]+)', text, re.IGNORECASE)
            if not stoploss_match:
                return None
        stoploss = float(stoploss_match.group(1))
        
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
        # Only print error if it's not a simple None return (i.e., actual parsing error)
        print(f"[PARSE ERROR] {e}")
        return None
