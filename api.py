# api.py – Updated for BingX Swap V2 (November 2025) – No File Read for Secret
from __future__ import annotations

import requests
import hmac
import hashlib
import time
import asyncio

API_URL = "https://open-api.bingx.com"


def _sign_query(secret_key: str, query: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _build_query(params=None) -> str:
    if not params:
        params = {}
    params = dict(params)
    params.setdefault("recvWindow", 5000)
    params["timestamp"] = int(time.time() * 1000)
    keys = sorted(params.keys())
    return "&".join(f"{k}={params[k]}" for k in keys)


async def bingx_api_request(
    method: str,
    path: str,
    api_key: str,
    secret_key: str,
    params: dict | None = None,
    retries: int = 3,
    delay: float = 0.5,
):
    method = method.upper()
    for attempt in range(retries):
        try:
            query = _build_query(params)
            signature = _sign_query(secret_key, query)
            url = f"{API_URL}{path}?{query}&signature={signature}"

            headers = {
                "X-BX-APIKEY": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == "DELETE":
                resp = requests.delete(url, headers=headers, timeout=10)
            else:
                resp = requests.post(url, headers=headers, timeout=10)

            try:
                data = resp.json()
            except Exception:
                data = {"code": -1, "msg": f"Non-JSON response: {resp.text}"}

            return data

        except Exception as e:
            print(f"API request failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)

    return {"code": -1, "msg": "Request failed"}