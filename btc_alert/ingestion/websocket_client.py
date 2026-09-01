import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Literal
import websockets

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class TradeTick:
    market_type: Literal["spot", "perp"]
    symbol: str
    price: float
    quantity: float
    is_buyer_maker: bool
    timestamp_ms: int


class MultiExchangeStreamClient:
    BINANCE_SPOT_WS = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
    BYBIT_PERP_WS = "wss://stream.bybit.com/v5/public/linear"

    async def _stream_binance_spot(self, queue: asyncio.Queue[TradeTick]) -> None:
        retry_delay = 2
        while True:
            try:
                async with websockets.connect(self.BINANCE_SPOT_WS, ping_interval=20, ping_timeout=10) as ws:
                    retry_delay = 2
                    async for raw_msg in ws:
                        data = json.loads(raw_msg)
                        if "p" in data and "q" in data:
                            tick = TradeTick(
                                market_type="spot",
                                symbol=data.get("s", "BTCUSDT"),
                                price=float(data["p"]),
                                quantity=float(data["q"]),
                                is_buyer_maker=bool(data["m"]),
                                timestamp_ms=int(data.get("E", data.get("T", 0))),
                            )
                            await queue.put(tick)
            except Exception:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    async def _stream_bybit_perp(self, queue: asyncio.Queue[TradeTick]) -> None:
        retry_delay = 2
        subscribe_msg = json.dumps({"op": "subscribe", "args": ["publicTrade.BTCUSDT"]})
        while True:
            try:
                async with websockets.connect(self.BYBIT_PERP_WS, ping_interval=20, ping_timeout=10) as ws:
                    await ws.send(subscribe_msg)
                    retry_delay = 2
                    async for raw_msg in ws:
                        payload = json.loads(raw_msg)
                        if payload.get("topic") == "publicTrade.BTCUSDT" and "data" in payload:
                            for item in payload["data"]:
                                tick = TradeTick(
                                    market_type="perp",
                                    symbol=item["s"],
                                    price=float(item["p"]),
                                    quantity=float(item["v"]),
                                    # In Bybit: S = Sell side aggressive (hits bid/buyer is maker)
                                    is_buyer_maker=(item["S"] == "Sell"),
                                    timestamp_ms=int(item["T"]),
                                )
                                await queue.put(tick)
            except Exception:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    async def stream_trades(self) -> AsyncGenerator[TradeTick, None]:
        queue: asyncio.Queue[TradeTick] = asyncio.Queue(maxsize=30000)
        spot_task = asyncio.create_task(self._stream_binance_spot(queue))
        perp_task = asyncio.create_task(self._stream_bybit_perp(queue))

        try:
            while True:
                tick = await queue.get()
                yield tick
                queue.task_done()
        finally:
            spot_task.cancel()
            perp_task.cancel()
            await asyncio.gather(spot_task, perp_task, return_exceptions=True)