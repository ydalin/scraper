# api.py
import requests, hmac, hashlib, time, asyncio

def sign(params, secret):
    query = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

async def bingx_api_request(method, path, api_key, secret, base_url, params=None, data=None, is_demo=False):
    timestamp = int(time.time() * 1000)
    params = params or {}
    params['timestamp'] = timestamp
    if is_demo: params['isDemo'] = 'true'
    params['signature'] = sign(params, secret)

    url = f"{base_url}{path}"
    headers = {"X-BX-APIKEY": api_key}
    try:
        r = requests.request(method, url, headers=headers, params=params, data=data, timeout=10)
        return r.json()
    except Exception as e:
        return {'code': -1, 'msg': str(e)}

async def connect_bingx_futures(credentials_file, is_demo):
    creds = {}
    with open(credentials_file) as f:
        for line in f:
            k, v = line.strip().split(':', 1)
            creds[k.strip()] = v.strip()
    return {
        'api_key': creds['bingx_api_key'],
        'secret_key': creds['bingx_secret_key'],
        'base_url': 'https://open-api.bingx.com'
    }, is_demo, {}