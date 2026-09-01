import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Literal
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Standardized trade structure for downstream analytics
@dataclass(slots=True)
class TradeTick:
    market_type: Literal["spot", "perp"]
    symbol: str
    price: float
    quantity: float
    is_buyer_maker: bool  # True: sell aggressive (hit bid); False: buy aggressive (lift ask)
    timestamp_ms: int


class BinanceStreamClient:
    SPOT_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
    PERP_WS_URL = "wss://fstream.binance.com/ws/btcusdt@aggTrade"

    async def _stream_endpoint(
        self, url: str, market_type: Literal["spot", "perp"], queue: asyncio.Queue[TradeTick]
    ) -> None:
        """Maintains an auto-reconnecting WebSocket connection and pushes ticks to the queue."""
        retry_delay = 2
        while True:
            try:
                logger.info(f"Connecting to {market_type.upper()} stream...")
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info(f"Connected to {market_type.upper()} stream.")
                    retry_delay = 2  # Reset retry backoff on successful connect
                    
                    async for raw_msg in ws:
                        data = json.loads(raw_msg)
                        
                        tick = TradeTick(
                            market_type=market_type,
                            symbol=data.get("s", "BTCUSDT"),
                            price=float(data["p"]),
                            quantity=float(data["q"]),
                            is_buyer_maker=bool(data["m"]),
                            timestamp_ms=int(data["E"]),
                        )
                        await queue.put(tick)
            except (websockets.ConnectionClosed, OSError, Exception) as exc:
                logger.warning(f"{market_type.upper()} stream disconnected ({exc}). Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    async def stream_trades(self) -> AsyncGenerator[TradeTick, None]:
        """Runs Spot and Perp ingestion tasks concurrently and yields incoming ticks."""
        queue: asyncio.Queue[TradeTick] = asyncio.Queue(maxsize=10000)

        spot_task = asyncio.create_task(self._stream_endpoint(self.SPOT_WS_URL, "spot", queue))
        perp_task = asyncio.create_task(self._stream_endpoint(self.PERP_WS_URL, "perp", queue))

        try:
            while True:
                tick = await queue.get()
                yield tick
                queue.task_done()
        finally:
            spot_task.cancel()
            perp_task.cancel()
            await asyncio.gather(spot_task, perp_task, return_exceptions=True)