import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)
ET_TZ = ZoneInfo("America/New_York")


def classify_rsi(value: float) -> str:
    """Maps a 0-100 RSI reading to a human-readable momentum zone."""
    if value < 20.0:
        return "Extreme Oversold"
    if value < 30.0:
        return "Oversold"
    if value < 45.0:
        return "Bearish"
    if value <= 55.0:
        return "Neutral"
    if value <= 70.0:
        return "Bullish"
    if value <= 80.0:
        return "Overbought"
    return "Extreme Overbought"


@dataclass(slots=True)
class RSIMetrics:
    finalized_rsi: float
    rsi_delta: float
    provisional_rsi: float
    last_close_price: float
    last_close_date_et: str
    is_warmed_up: bool = False

    @property
    def label(self) -> str:
        return classify_rsi(self.finalized_rsi) if self.is_warmed_up else "Warming Up"

    @property
    def provisional_label(self) -> str:
        return classify_rsi(self.provisional_rsi) if self.is_warmed_up else "Warming Up"


class DailyRSITracker:
    """Computes 14-period Wilder Daily RSI anchored to the 16:00 ET US equity close."""

    BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, period: int = 14, warmup_days: int = 250, symbol: str = "BTCUSDT"):
        self.period = period
        self.warmup_days = warmup_days
        self.symbol = symbol

        self.avg_gain: float = 0.0
        self.avg_loss: float = 0.0
        self.finalized_rsi: float = 0.0
        self.rsi_delta: float = 0.0
        self.last_close_price: float = 0.0
        self.last_close_date_et: str = ""
        self.is_warmed_up: bool = False

    @staticmethod
    def _calc_rsi(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0.0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    async def warmup(self) -> None:
        """Fetches historical 1h klines from Binance Spot and seeds Wilder's RSI at 16:00 ET."""
        hours_needed = self.warmup_days * 24
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = now_ms - (hours_needed * 3600 * 1000)

        rows: list[list] = []
        cursor = start_ms

        try:
            async with aiohttp.ClientSession() as session:
                while cursor < now_ms:
                    params = {
                        "symbol": self.symbol,
                        "interval": "1h",
                        "startTime": cursor,
                        "limit": 1000,
                    }
                    async with session.get(
                        self.BINANCE_KLINES_URL,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status != 200:
                            logger.error("Binance klines HTTP %s during RSI warmup", resp.status)
                            return
                        batch = await resp.json()
                        if not batch:
                            break
                        rows.extend(batch)
                        last_open_ms = int(batch[-1][0])
                        if last_open_ms <= cursor or len(batch) < 1000:
                            break
                        cursor = last_open_ms + 3600 * 1000
        except Exception as exc:
            logger.error("RSI warmup network error: %s", exc)
            return

        if len(rows) < (self.period + 2) * 24:
            logger.error("Insufficient kline data for RSI warmup (%d rows)", len(rows))
            return

        df = pd.DataFrame(rows, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        df["open_dt_et"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(ET_TZ)
        df["close_time"] = df["close_time"].astype("int64")

        # Only include completed 15:00 ET candles (which close at 16:00:00 ET)
        completed_16et = df[(df["open_dt_et"].dt.hour == 15) & (df["close_time"] <= now_ms)].copy()
        completed_16et = completed_16et.drop_duplicates(subset=["open_time"]).sort_values("open_time")

        closes = completed_16et["close"].to_list()
        dates_et = completed_16et["open_dt_et"].dt.strftime("%Y-%m-%d").to_list()

        if len(closes) <= self.period + 1:
            return

        # Compute price changes
        gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
        losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]

        # Step 1: Initial 14-period simple average seed
        avg_gain = sum(gains[: self.period]) / self.period
        avg_loss = sum(losses[: self.period]) / self.period
        prev_rsi = self._calc_rsi(avg_gain, avg_loss)
        curr_rsi = prev_rsi

        # Step 2: Wilder's recursive smoothing forward
        for g, l in zip(gains[self.period :], losses[self.period :]):
            prev_rsi = curr_rsi
            avg_gain = ((avg_gain * (self.period - 1)) + g) / self.period
            avg_loss = ((avg_loss * (self.period - 1)) + l) / self.period
            curr_rsi = self._calc_rsi(avg_gain, avg_loss)

        self.avg_gain = avg_gain
        self.avg_loss = avg_loss
        self.finalized_rsi = round(curr_rsi, 2)
        self.rsi_delta = round(curr_rsi - prev_rsi, 2)
        self.last_close_price = closes[-1]
        self.last_close_date_et = dates_et[-1]
        self.is_warmed_up = True

    def get_metrics(self, live_price: float) -> RSIMetrics:
        """Returns finalized 16:00 ET RSI plus a live provisional intraday RSI without mutating state."""
        if not self.is_warmed_up or live_price <= 0.0:
            return RSIMetrics(
                finalized_rsi=self.finalized_rsi,
                rsi_delta=self.rsi_delta,
                provisional_rsi=self.finalized_rsi,
                last_close_price=self.last_close_price,
                last_close_date_et=self.last_close_date_et,
                is_warmed_up=self.is_warmed_up,
            )

        gain = max(live_price - self.last_close_price, 0.0)
        loss = max(self.last_close_price - live_price, 0.0)
        prov_gain = ((self.avg_gain * (self.period - 1)) + gain) / self.period
        prov_loss = ((self.avg_loss * (self.period - 1)) + loss) / self.period
        prov_rsi = round(self._calc_rsi(prov_gain, prov_loss), 2)

        return RSIMetrics(
            finalized_rsi=self.finalized_rsi,
            rsi_delta=self.rsi_delta,
            provisional_rsi=prov_rsi,
            last_close_price=self.last_close_price,
            last_close_date_et=self.last_close_date_et,
            is_warmed_up=True,
        )

    def check_and_finalize_close(self, live_price: float) -> RSIMetrics | None:
        """Locks in the 16:00 ET close once per calendar day and returns updated metrics."""
        if not self.is_warmed_up or live_price <= 0.0:
            return None

        now_et = datetime.now(ET_TZ)
        today_str = now_et.strftime("%Y-%m-%d")

        if now_et.hour >= 16 and today_str > self.last_close_date_et:
            prev_rsi = self.finalized_rsi
            gain = max(live_price - self.last_close_price, 0.0)
            loss = max(self.last_close_price - live_price, 0.0)

            self.avg_gain = ((self.avg_gain * (self.period - 1)) + gain) / self.period
            self.avg_loss = ((self.avg_loss * (self.period - 1)) + loss) / self.period

            new_rsi = round(self._calc_rsi(self.avg_gain, self.avg_loss), 2)
            self.rsi_delta = round(new_rsi - prev_rsi, 2)
            self.finalized_rsi = new_rsi
            self.last_close_price = live_price
            self.last_close_date_et = today_str

            return self.get_metrics(live_price)

        return None