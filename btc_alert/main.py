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
from btc_alert.reasoning.budget_manager import InferenceBudgetManager
from btc_alert.alerts.whatsapp import WhatsAppNotifier
from btc_alert.ui.dashboard import DashboardUI
from btc_alert.alerts.git_syncer import GitSyncer

logging.getLogger().setLevel(logging.CRITICAL)

class BTCMicrostructureDaemon:
    def __init__(self):
        # if the BTCSunrise repository is moved, you need to update this line.
        self.git_syncer = GitSyncer(repo_path="/mnt/c/Users/manra/var/BTCSunrise")
        self.last_snapshot_export: float = 0.0
        self.stream_client = MultiExchangeStreamClient()
        self.cvd_tracker = RollingCVDTracker(window_seconds=config.ROLLING_WINDOW_MINUTES * 60)
        self.vp_tracker = RollingVolumeProfile(
            window_seconds=config.ROLLING_WINDOW_MINUTES * 60, 
            bin_size=config.BIN_SIZE
        )
        self.reasoning_engine = GeminiReasoningEngine()
        self.budget_mgr = InferenceBudgetManager(max_per_hour=30, max_per_day=500)
        self.notifier = WhatsAppNotifier()
        
        self.latest_analysis: MicrostructureAnalysis | None = None
        self.last_gemini_call: float = 0.0
        self.last_alert_sent: float = 0.0
        self.last_alert_regime: str = ""
        self.ticks_count: int = 0
        self.start_time: float = time.time()
        self.alert_status: str = "Accumulating order flow buffer..."
        
        # High-Conviction Gating
        self.inference_cooldown: int = 180      # 3 minutes between LLM inferences during breakouts
        self.whatsapp_cooldown: int = 1200      # 20 minutes between phone notifications
        self.min_warmup_seconds: int = 180      # 3 minutes warmup on startup
        self.min_volume_threshold: float = 75.0 # Require 75 BTC traded in 60m window
        self.min_cvd_divergence: float = 20.0   # Require 20 BTC delta divergence

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
        """Constructs the high-conviction WhatsApp payload with verified float formatting."""
        msg = (
            f"⚡ *BTC ORDER FLOW BREAKOUT*\n\n"
            f"*Regime:* {analysis.regime}\n"
            f"*Price:* {cvd.latest_price:,.2f} USD\n"
            f"*Spot CVD:* {cvd.spot_cvd_delta:+,.2f} BTC\n"
            f"*Perp CVD:* {cvd.perp_cvd_delta:+,.2f} BTC\n"
            f"*Divergence:* {cvd.cvd_divergence:+,.2f} BTC\n"
            f"*POC:* {vp.poc_price:,.2f} USD | *VAH:* {vp.vah_price:,.2f} USD | *VAL:* {vp.val_price:,.2f} USD\n\n"
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

                    budget_allowed, budget_msg = self.budget_mgr.can_call()

                    # Only run inference if BOTH quantitative trigger and budget permit
                    if is_outside_va and has_warmup and has_volume and has_divergence and cooldown_ready and budget_allowed:
                        self.last_gemini_call = now
                        self.alert_status = f"[bold yellow]Evaluating Breakout... ({self.budget_mgr.get_status_str()})[/bold yellow]"

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
                            # Record successful call in budget tracker
                            self.budget_mgr.record_call()

                            if (
                                self.latest_analysis.uncertainty_level == "Low"
                                and (now - self.last_alert_sent >= self.whatsapp_cooldown)
                                and (self.latest_analysis.regime != self.last_alert_regime)
                            ):
                                self.last_alert_sent = now
                                self.last_alert_regime = self.latest_analysis.regime
                                
                                # 1. Dispatch WhatsApp notification
                                asyncio.create_task(self._format_and_dispatch_alert(cvd_metrics, vp_metrics, self.latest_analysis))
                                
                                # 2. Write new SVG and JSON snapshot to disk
                                DashboardUI.export_snapshot(
                                    cvd_metrics, vp_metrics, self.latest_analysis, self.alert_status, self.ticks_count
                                )
                                
                                # 3. Push updates to the Git repository
                                asyncio.create_task(self.git_syncer.push_updates("alert: high conviction breakout"))
                                
                                self.alert_status = f"[bold green]ALERT DISPATCHED ({self.latest_analysis.regime})[/bold green]"
                            else:
                                self.alert_status = f"Tracking ({self.latest_analysis.regime}) | {self.budget_mgr.get_status_str()}"
                        except Exception as exc:
                            err_str = str(exc)
                            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                                # Trigger 30-minute lockout to avoid spamming the exhausted quota
                                self.budget_mgr.trigger_rate_limit_lockout(1800)
                                self.alert_status = f"[yellow]Quota Cap Hit (Backing off 30m) | {self.budget_mgr.get_status_str()}[/yellow]"
                            else:
                                err_detail = getattr(exc, "code", None) or err_str[:25]
                                self.alert_status = f"[red]Inference error: {err_detail}[/red]"

                    elif self.latest_analysis is None or (now - self.last_gemini_call > 60):
                        self.latest_analysis = self._generate_rule_based_synthesis(cvd_metrics, vp_metrics)
                        budget_info = self.budget_mgr.get_status_str()
                        if not is_outside_va:
                            self.alert_status = f"Inside Value Area | {budget_info}"
                        else:
                            self.alert_status = f"Monitoring Outside VA | {budget_msg} | {budget_info}"

                live.update(
                    DashboardUI.render(
                        cvd_metrics, vp_metrics, self.latest_analysis, self.alert_status, self.ticks_count
                    )
                )
                if now - self.last_snapshot_export >= 300:  # Every 5 minutes
                    self.last_snapshot_export = now
                    DashboardUI.export_snapshot(
                        cvd_metrics,
                        vp_metrics,
                        self.latest_analysis,
                        self.alert_status,
                        self.ticks_count
                    )
                    asyncio.create_task(self.git_syncer.push_updates())

def main():
    daemon = BTCMicrostructureDaemon()
    try:
        asyncio.run(daemon.run())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()