from collections import deque
from dataclasses import dataclass
import numpy as np
from btc_alert.ingestion.websocket_client import TradeTick

@dataclass(slots=True)
class VolumeProfileMetrics:
    poc_price: float
    vah_price: float
    val_price: float
    is_above_vah: bool
    is_below_val: bool
    total_profile_volume: float


class RollingVolumeProfile:
    def __init__(self, window_seconds: int = 3600, bin_size: float = 50.0, value_area_pct: float = 0.70):
        self.window_seconds = window_seconds
        self.bin_size = bin_size
        self.value_area_pct = value_area_pct
        # Stores (timestamp_sec, price, quantity)
        self.trades: deque[tuple[float, float, float]] = deque()

    def add_tick(self, tick: TradeTick) -> None:
        now = tick.timestamp_ms / 1000.0
        self.trades.append((now, tick.price, tick.quantity))
        self._prune(now)

    def _prune(self, current_time: float) -> None:
        cutoff = current_time - self.window_seconds
        while self.trades and self.trades[0][0] < cutoff:
            self.trades.popleft()

    def compute_profile(self, current_price: float) -> VolumeProfileMetrics:
        if not self.trades:
            return VolumeProfileMetrics(
                poc_price=current_price,
                vah_price=current_price,
                val_price=current_price,
                is_above_vah=False,
                is_below_val=False,
                total_profile_volume=0.0,
            )

        prices = np.array([t[1] for t in self.trades])
        quantities = np.array([t[2] for t in self.trades])

        # Bin prices into fixed steps (e.g. $50 increments)
        binned_prices = (prices // self.bin_size) * self.bin_size
        unique_bins, inverse_indices = np.unique(binned_prices, return_inverse=True)
        bin_volumes = np.bincount(inverse_indices, weights=quantities)

        # 1. Point of Control (POC)
        poc_idx = np.argmax(bin_volumes)
        poc_price = float(unique_bins[poc_idx])
        total_vol = float(np.sum(bin_volumes))

        # 2. Value Area Calculation (70% total volume radiating outward from POC)
        target_vol = total_vol * self.value_area_pct
        accumulated_vol = bin_volumes[poc_idx]
        low_idx = poc_idx
        high_idx = poc_idx

        while accumulated_vol < target_vol and (low_idx > 0 or high_idx < len(unique_bins) - 1):
            next_low_vol = bin_volumes[low_idx - 1] if low_idx > 0 else 0
            next_high_vol = bin_volumes[high_idx + 1] if high_idx < len(unique_bins) - 1 else 0

            if next_high_vol >= next_low_vol and high_idx < len(unique_bins) - 1:
                high_idx += 1
                accumulated_vol += next_high_vol
            elif low_idx > 0:
                low_idx -= 1
                accumulated_vol += next_low_vol
            else:
                break

        val_price = float(unique_bins[low_idx])
        vah_price = float(unique_bins[high_idx] + self.bin_size)

        return VolumeProfileMetrics(
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            is_above_vah=current_price > vah_price,
            is_below_val=current_price < val_price,
            total_profile_volume=round(total_vol, 4),
        )