import asyncio
from btc_alert.ingestion.websocket_client import MultiExchangeStreamClient

async def check():
    client = MultiExchangeStreamClient()
    print('Testing Binance Spot + Bybit Perp feeds...')
    counts = {'spot': 0, 'perp': 0}
    async for tick in client.stream_trades():
        counts[tick.market_type] += 1
        if counts['spot'] >= 5 and counts['perp'] >= 5:
            break
    print(f'Verification passed! Received: {counts}')

asyncio.run(check())