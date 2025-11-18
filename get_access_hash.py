from telethon import TelegramClient
# 
# (fill with your own values)
api_id = 21062841
api_hash = 'b6c864645d31a8c5fd128de70d5e2f64'
client = TelegramClient('session', api_id, api_hash)

async def main():
    channel = await client.get_entity('https://t.me/volodymyrkovalc')
    print("channel_id:", channel.id)
    print("access_hash:", channel.access_hash)

with client:
    client.loop.run_until_complete(main())
