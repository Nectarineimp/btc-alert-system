import asyncio
import time
import logging
from rich.live import Live

from btc_alert.config import config
from btc_alert.ingestion.websocket_client import MultiExchangeStreamClient
from btc_alert.analytics.cvd import RollingCVDTracker, CVDMetrics
from btc_alert.analytics.volume_profile import RollingVolumeProfile, VolumeProfileMetrics
from btc_alert.reasoning.gemini_engine import GeminiReasoningEngine
from btc_alert.reasoning.schemas import MicrostructureAnalysis
from btc_alert.alerts.whatsapp import WhatsAppNotifier
from btc_alert.ui.dashboard import DashboardUI

logging.getLogger().setLevel(logging.CRITICAL)

class BTCMicrostructureDaemon:
    def __init__(self):
        self.stream_client = MultiExchangeStreamClient()
        self.cvd_tracker = RollingCVDTracker(window_seconds=config.ROLLING_WINDOW_MINUTES * 60)
        self.vp_tracker = RollingVolumeProfile(
            window_seconds=config.ROLLING_WINDOW_MINUTES * 60, 
            bin_size=config.BIN_SIZE
        )
        self.reasoning_engine = GeminiReasoningEngine()
        self.notifier = WhatsAppNotifier()
        
        self.latest_analysis: MicrostructureAnalysis | None = None
        self.last_gemini_call: float = 0.0
        self.last_alert_sent: float = 0.0
        self.last_alert_regime: str = ""
        self.ticks_count: int = 0
        self.start_time: float = time.time()
        self.alert_status: str = "Accumulating order flow buffer..."
        
        # High-Conviction Thresholds
        self.inference_cooldown: int = 900     # 15 min between LLM queries
        self.whatsapp_cooldown: int = 1800     # 30 min between phone pings
        self.min_warmup_seconds: int = 300     # 5 min startup accumulation
        self.min_volume_threshold: float = 100.0
        self.min_cvd_divergence: float = 25.0

    def _generate_rule_based_synthesis(
        self, cvd: CVDMetrics, vp: VolumeProfileMetrics
    ) -> MicrostructureAnalysis:
        if cvd.spot_volume + cvd.perp_volume < 10.0:
            return MicrostructureAnalysis(
                regime="Mean Reverting / Consolidation",
                uncertainty_level="High",
                verbal_summary="Initializing rolling microstructure buffers. Volume profile accumulating baseline order flow.",
                key_risk_factor="Insufficient tick sample size for regime identification."
            )

        if not vp.is_above_vah and not vp.is_below_val:
            bias = "positive" if cvd.spot_cvd_delta > 0 else "negative"
            return MicrostructureAnalysis(
                regime="Mean Reverting / Consolidation",
                uncertainty_level="High",
                verbal_summary=f"Price rotating inside Value Area near POC (${vp.poc_price:,.2f}). Spot CVD delta is {bias} ({cvd.spot_cvd_delta:+,.2f} BTC).",
                key_risk_factor=f"Range chop between VAL (${vp.val_price:,.2f}) and VAH (${vp.vah_price:,.2f})."
            )

        direction = "above VAH" if vp.is_above_vah else "below VAL"
        return MicrostructureAnalysis(
            regime="Leverage Squeeze / Exhaustion Risk",
            uncertainty_level="Medium",
            verbal_summary=f"Price testing liquidity {direction} at ${cvd.latest_price:,.2f}. Delta volume lacks high-conviction institutional participation.",
            key_risk_factor=f"Mean-reversion trap back toward Value Area POC (${vp.poc_price:,.2f})."
        )

    async def _format_and_dispatch_alert(self, cvd: CVDMetrics, vp: VolumeProfileMetrics, analysis: MicrostructureAnalysis):
        """Constructs the high-conviction WhatsApp payload."""
        msg = (
            f"⚡ *BTC ORDER FLOW BREAKOUT*\n\n"
            f"*Regime:* {analysis.regime}\n"
            f"*Price:* ${cvd.latest_price:,.2f}\n"
            f"*Spot CVD:* {cvd.spot_cvd_delta:+,.2f} BTC\n"
            f"*Perp CVD:* {cvd.perp_cvd_delta:+,.2f} BTC\n"
            f"*Divergence:* {cvd.cvd_divergence:+,.2f} BTC\n"
            f"*POC:* ${vp.poc_price:,.2f} | *VAH:* ${vp.vah_price:,.2f} | *VAL:* ${vp.val_price:,.2f}\n\n"
            f"*Analysis:* {analysis.verbal_summary}\n\n"
            f"*Key Risk:* {analysis.key_risk_factor}"
        )
        await self.notifier.send_alert(msg)

    async def run(self):
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
                cvd_metrics = self.cvd_tracker.get_metrics()
                vp_metrics = self.vp_tracker.compute_profile(cvd_metrics.latest_price)

                if self.ticks_count > 50:
                    total_vol = cvd_metrics.spot_volume + cvd_metrics.perp_volume
                    is_outside_va = vp_metrics.is_above_vah or vp_metrics.is_below_val
                    has_warmup = (now - self.start_time) >= self.min_warmup_seconds
                    has_volume = total_vol >= self.min_volume_threshold
                    has_divergence = abs(cvd_metrics.cvd_divergence) >= self.min_cvd_divergence
                    cooldown_ready = (now - self.last_gemini_call) >= self.inference_cooldown

                    # Trigger Gemini inference only under verified order flow displacement
                    if is_outside_va and has_warmup and has_volume and has_divergence and cooldown_ready:
                        self.last_gemini_call = now
                        self.alert_status = "[bold yellow]Evaluating High-Conviction Breakout...[/bold yellow]"

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
                            loop = asyncio.get_running_loop()
                            self.latest_analysis = await loop.run_in_executor(
                                None, self.reasoning_engine.evaluate_market, payload
                            )

                            # Dispatch WhatsApp ping ONLY if uncertainty is Low and regime changed
                            if (
                                self.latest_analysis.uncertainty_level == "Low"
                                and (now - self.last_alert_sent >= self.whatsapp_cooldown)
                                and (self.latest_analysis.regime != self.last_alert_regime)
                            ):
                                self.last_alert_sent = now
                                self.last_alert_regime = self.latest_analysis.regime
                                asyncio.create_task(self._format_and_dispatch_alert(cvd_metrics, vp_metrics, self.latest_analysis))
                                self.alert_status = f"[bold green]WHATSAPP DISPATCHED ({self.latest_analysis.regime})[/bold green]"
                            else:
                                self.alert_status = f"Tracking ({self.latest_analysis.regime})"
                        except Exception as exc:
                            err_detail = getattr(exc, "code", None) or str(exc)[:30]
                            self.alert_status = f"[red]Inference error: {err_detail}[/red]"

                    elif self.latest_analysis is None or (now - self.last_gemini_call > 60):
                        self.latest_analysis = self._generate_rule_based_synthesis(cvd_metrics, vp_metrics)
                        if not is_outside_va:
                            self.alert_status = "Consolidating within Value Area"

                live.update(
                    DashboardUI.render(
                        cvd_metrics, vp_metrics, self.latest_analysis, self.alert_status, self.ticks_count
                    )
                )

def main():
    daemon = BTCMicrostructureDaemon()
    try:
        asyncio.run(daemon.run())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()