import time
from collections import deque
from dataclasses import dataclass
from btc_alert.ingestion.websocket_client import TradeTick

@dataclass(slots=True)
class CVDMetrics:
    spot_cvd_delta: float
    perp_cvd_delta: float
    cvd_divergence: float  # Spot CVD - Perp CVD
    spot_volume: float
    perp_volume: float
    latest_price: float


class RollingCVDTracker:
    def __init__(self, window_seconds: int = 3600):
        self.window_seconds = window_seconds
        # Stores tuples of (timestamp_sec, signed_delta, total_volume)
        self.spot_trades: deque[tuple[float, float, float]] = deque()
        self.perp_trades: deque[tuple[float, float, float]] = deque()
        self.latest_price: float = 0.0

    def add_tick(self, tick: TradeTick) -> None:
        now = tick.timestamp_ms / 1000.0
        self.latest_price = tick.price
        
        # Aggressive buy: +qty; Aggressive sell: -qty
        delta = -tick.quantity if tick.is_buyer_maker else tick.quantity
        trade_entry = (now, delta, tick.quantity)

        if tick.market_type == "spot":
            self.spot_trades.append(trade_entry)
        else:
            self.perp_trades.append(trade_entry)

        self._prune(now)

    def _prune(self, current_time: float) -> None:
        cutoff = current_time - self.window_seconds
        while self.spot_trades and self.spot_trades[0][0] < cutoff:
            self.spot_trades.popleft()
        while self.perp_trades and self.perp_trades[0][0] < cutoff:
            self.perp_trades.popleft()

    def get_metrics(self) -> CVDMetrics:
        spot_delta = sum(t[1] for t in self.spot_trades)
        perp_delta = sum(t[1] for t in self.perp_trades)
        spot_vol = sum(t[2] for t in self.spot_trades)
        perp_vol = sum(t[2] for t in self.perp_trades)

        return CVDMetrics(
            spot_cvd_delta=round(spot_delta, 4),
            perp_cvd_delta=round(perp_delta, 4),
            cvd_divergence=round(spot_delta - perp_delta, 4),
            spot_volume=round(spot_vol, 4),
            perp_volume=round(perp_vol, 4),
            latest_price=self.latest_price,
        )