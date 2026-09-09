import asyncio
import json
import sys
import aiohttp
import websockets

BINANCE_SPOT_WS = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
BINANCE_REST_PING = "https://api.binance.com/api/v3/ping"
BYBIT_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"

async def check_binance_rest_status():
    print("\n[1/3] Checking Binance REST API reachability & geofencing...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BINANCE_REST_PING, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                print(f"  -> HTTP Status: {resp.status}")
                if resp.status == 200:
                    print("  -> Binance REST: REACHABLE (Status OK)")
                elif resp.status in (403, 451):
                    body = await resp.text()
                    print(f"  -> [WARNING] Potential Geo-blocking / WAF block detected: {resp.status}")
                    print(f"  -> Response: {body.strip()}")
                else:
                    body = await resp.text()
                    print(f"  -> Non-200 Status: {resp.status} - {body.strip()}")
    except Exception as e:
        print(f"  -> [ERROR] Failed to reach Binance REST endpoint: {e}")

async def test_binance_spot_ws(sample_seconds: int = 5):
    print(f"\n[2/3] Sampling Binance Spot WebSocket ({sample_seconds}s)...")
    print(f"  -> Connecting to: {BINANCE_SPOT_WS}")
    ticks = 0
    total_qty = 0.0

    try:
        async with websockets.connect(BINANCE_SPOT_WS, ping_interval=20, ping_timeout=10) as ws:
            print("  -> Connected successfully. Listening for trades...")
            start = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start) < sample_seconds:
                try:
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw_msg)
                    ticks += 1
                    qty = float(msg.get("q", 0.0))
                    price = float(msg.get("p", 0.0))
                    total_qty += qty

                    if ticks == 1:
                        print(f"  -> Sample trade parsed: Price={price:,.2f}, Qty={qty:.4f} BTC")
                except asyncio.TimeoutError:
                    print("  -> [TIMEOUT] Connected, but no trades received for 3s.")

            print(f"  -> Results: {ticks} ticks received | Volume sampled: {total_qty:,.4f} BTC")
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"  -> [CRITICAL] Binance WS Connection Rejected: HTTP {e.status_code}")
        if e.status_code in (403, 451):
            print("     Likely cause: US IP geoblock / Cloudflare rate-limit.")
    except Exception as e:
        print(f"  -> [ERROR] Binance WebSocket failure: {type(e).__name__} - {e}")

async def test_bybit_linear_ws(sample_seconds: int = 5):
    print(f"\n[3/3] Sampling Bybit Linear WebSocket ({sample_seconds}s)...")
    print(f"  -> Connecting to: {BYBIT_LINEAR_WS}")
    ticks = 0
    total_qty = 0.0

    sub_payload = {
        "op": "subscribe",
        "args": ["publicTrade.BTCUSDT"]
    }

    try:
        async with websockets.connect(BYBIT_LINEAR_WS, ping_interval=20, ping_timeout=10) as ws:
            await ws.send(json.dumps(sub_payload))
            print("  -> Subscription sent: publicTrade.BTCUSDT")
            start = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start) < sample_seconds:
                try:
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw_msg)
                    
                    if "data" in msg:
                        for trade in msg["data"]:
                            ticks += 1
                            qty = float(trade.get("v", 0.0))
                            price = float(trade.get("p", 0.0))
                            total_qty += qty
                            if ticks == 1:
                                print(f"  -> Sample trade parsed: Price={price:,.2f}, Qty={qty:.4f} BTC")
                except asyncio.TimeoutError:
                    print("  -> [TIMEOUT] Connected, but no trades received for 3s.")

            print(f"  -> Results: {ticks} ticks received | Volume sampled: {total_qty:,.4f} BTC")
    except Exception as e:
        print(f"  -> [ERROR] Bybit WebSocket failure: {type(e).__name__} - {e}")

async def main():
    print("========================================")
    print(" BTC ALERT SYSTEM STREAM DIAGNOSTIC")
    print("========================================")
    await check_binance_rest_status()
    await test_binance_spot_ws(sample_seconds=5)
    await test_bybit_linear_ws(sample_seconds=5)
    print("\nDiagnostic complete.")

if __name__ == "__main__":
    asyncio.run(main())