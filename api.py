# api.py – FINAL BINGX API WRAPPER (WORKS 100% – November 23, 2025)
import requests
import hashlib
import hmac
import time
import asyncio

API_URL = "https://open-api.bingx.com"

def _build_params(params=None):
    if params is None:
        params = {}
    params = dict(params)
    params.setdefault("recvWindow", 5000)
    params["timestamp"] = int(time.time() * 1000)
    # Sort keys for stable signature
    return "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))

def _sign(secret_key: str, query_string: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

async def bingx_api_request(
    method: str,
    path: str,
    api_key: str,
    secret_key: str,
    params: dict | None = None,
    data: dict | None = None,
    retries: int = 3,
    delay: float = 0.5,
):
    """
    Unified BingX API request (GET/POST/DELETE)
    All parameters go in query string (BingX requirement)
    """
    method = method.upper()

    for attempt in range(retries):
        try:
            query_params = _build_params(params)
            if data:
                query_params += "&" + "&".join(f"{k}={v}" for k, v in data.items())

            signature = _sign(secret_key, query_params)
            url = f"{API_URL}{path}?{query_params}&signature={signature}"

            headers = {"X-BX-APIKEY": api_key}

            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                resp = requests.post(url, headers=headers, timeout=10)
            elif method == "DELETE":
                resp = requests.delete(url, headers=headers, timeout=10)
            else:
                return {"code": -1, "msg": "Invalid method"}

            try:
                result = resp.json()
            except:
                result = {"code": -1, "msg": f"Non-JSON response: {resp.text}"}

            return result

        except Exception as e:
            print(f"[API] Request failed (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)

    return {"code": -1, "msg": "All retries failed"}