# api.py – NO FILE READ FOR SECRET
import requests, hmac, hashlib, time, asyncio

API_URL = "https://open-api.bingx.com"

def parse_param(params_map):
    sorted_keys = sorted(params_map.keys())
    params_str = "&".join([f"{k}={params_map[k]}" for k in sorted_keys])
    return params_str + "&timestamp=" + str(int(time.time() * 1000)) if params_str else "timestamp=" + str(int(time.time() * 1000))

def get_sign(api_secret, payload):
    return hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

def send_request(method, path, url_params, payload, api_key, secret_key, base_url=None):
    if base_url is None:
        base_url = API_URL
    signature = get_sign(secret_key, url_params)
    url = f"{base_url}{path}?{url_params}&signature={signature}"
    headers = {'X-BX-APIKEY': api_key}
    response = requests.request(method, url, headers=headers, data=payload)
    return response.json()

async def bingx_api_request(method, endpoint, api_key, secret_key, base_url=None, params=None, data=None, retries=3, delay=5):
    """Make BingX API request with proper params/data handling"""
    if base_url is None:
        base_url = API_URL
    for attempt in range(retries):
        try:
            params_map = {'recvWindow': 5000}

            # Merge params if provided (for GET requests)
            if params:
                params_map.update(params)

            # Merge data if provided (for POST requests)
            if data:
                params_map.update(data)

            url_params = parse_param(params_map)
            return send_request(method, endpoint, url_params, None, api_key, secret_key, base_url)
        except Exception as e:
            print(f"API request failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
    return {'code': -1, 'msg': 'Request failed'}
