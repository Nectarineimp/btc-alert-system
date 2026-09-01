import asyncio
import time
import logging
from rich.live import Live

from btc_alert.config import config
from btc_alert.ingestion.websocket_client import BinanceStreamClient
from btc_alert.analytics.cvd import RollingCVDTracker
from btc_alert.analytics.volume_profile import RollingVolumeProfile
from btc_alert.reasoning.gemini_engine import GeminiReasoningEngine
from btc_alert.reasoning.schemas import MicrostructureAnalysis
from btc_alert.ui.dashboard import DashboardUI

# Suppress debug logs in production TUI mode
logging.getLogger().setLevel(logging.CRITICAL)

class BTCMicrostructureDaemon:
    def __init__(self):
        self.stream_client = BinanceStreamClient()
        self.cvd_tracker = RollingCVDTracker(window_seconds=config.ROLLING_WINDOW_MINUTES * 60)
        self.vp_tracker = RollingVolumeProfile(
            window_seconds=config.ROLLING_WINDOW_MINUTES * 60, 
            bin_size=config.BIN_SIZE
        )
        self.reasoning_engine = GeminiReasoningEngine()
        
        self.latest_analysis: MicrostructureAnalysis | None = None
        self.last_gemini_call: float = 0.0
        self.ticks_count: int = 0
        self.alert_status: str = "Awaiting initial conviction signal."

    async def run(self):
        # 1-second cadence for Gemini evaluations
        eval_interval = config.POLL_INTERVAL_SECONDS

        with Live(
            DashboardUI.render(
                self.cvd_tracker.get_metrics(),
                self.vp_tracker.compute_profile(0.0),
                None,
                self.alert_status,
                0,
            ),
            refresh_per_second=4,
            screen=True,
        ) as live:
            async for tick in self.stream_client.stream_trades():
                self.ticks_count += 1
                self.cvd_tracker.add_tick(tick)
                self.vp_tracker.add_tick(tick)

                now = time.time()

                # Trigger Gemini inference periodically
                if now - self.last_gemini_call >= eval_interval and self.ticks_count > 50:
                    cvd_metrics = self.cvd_tracker.get_metrics()
                    vp_metrics = self.vp_tracker.compute_profile(cvd_metrics.latest_price)

                    payload = {
                        "price": cvd_metrics.latest_price,
                        "vah": vp_metrics.vah_price,
                        "val": vp_metrics.val_price,
                        "poc_price": vp_metrics.poc_price,
                        "is_above_vah": vp_metrics.is_above_vah,
                        "is_below_val": vp_metrics.is_below_val,
                        f"spot_cvd_delta_{config.ROLLING_WINDOW_MINUTES}m": cvd_metrics.spot_cvd_delta,
                        f"perp_cvd_delta_{config.ROLLING_WINDOW_MINUTES}m": cvd_metrics.perp_cvd_delta,
                        "cvd_divergence": cvd_metrics.cvd_divergence,
                        f"spot_volume_{config.ROLLING_WINDOW_MINUTES}m": cvd_metrics.spot_volume,
                        f"perp_volume_{config.ROLLING_WINDOW_MINUTES}m": cvd_metrics.perp_volume,
                    }

                    try:
                        # Non-blocking run in executor to keep UI snappy
                        loop = asyncio.get_running_loop()
                        self.latest_analysis = await loop.run_in_executor(
                            None, self.reasoning_engine.evaluate_market, payload
                        )
                        self.last_gemini_call = now

                        if self.latest_analysis.uncertainty_level == "Low":
                            self.alert_status = f"[bold green]HIGH CONVICTION ({self.latest_analysis.regime})[/bold green]"
                        else:
                            self.alert_status = f"Tracking ({self.latest_analysis.regime})"
                    except Exception:
                        self.alert_status = "[red]Inference error[/red]"

                # Update live TUI
                cvd = self.cvd_tracker.get_metrics()
                vp = self.vp_tracker.compute_profile(cvd.latest_price)
                live.update(
                    DashboardUI.render(
                        cvd, vp, self.latest_analysis, self.alert_status, self.ticks_count
                    )
                )

def main():
    daemon = BTCMicrostructureDaemon()
    asyncio.run(daemon.run())

if __name__ == "__main__":
    main()