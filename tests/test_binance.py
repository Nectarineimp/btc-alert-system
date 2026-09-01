import asyncio
from btc_alert.ingestion.websocket_client import BinanceStreamClient

async def check():
    client = BinanceStreamClient()
    print('Testing both streams for 5 seconds...')
    counts = {'spot': 0, 'perp': 0}
    async for tick in client.stream_trades():
        counts[tick.market_type] += 1
        if counts['spot'] > 5 and counts['perp'] > 5:
            break
    print(f'Capture results: {counts}')

asyncio.run(check())