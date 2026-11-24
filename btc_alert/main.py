import asyncio
import time
import logging
from rich.live import Live

from btc_alert.config import config
from btc_alert.analytics.rsi import DailyRSITracker, RSIMetrics
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
        self.rsi_tracker = DailyRSITracker(period=14, warmup_days=250)
        # if the BTCSunrise repository is moved, you need to update this line.
        self.git_syncer = GitSyncer(repo_path="~/projects/BTCSunrise-datashare")
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
        self.min_volume_threshold: float = 30.0 # Require 30 BTC traded in 60m window
        self.min_cvd_divergence: float = 10.0   # Require 10 BTC delta divergence

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

    async def _format_and_dispatch_rsi_alert(self, rsi: RSIMetrics):
        """Dispatches the daily 16:00 ET Wilder RSI close alert via WhatsApp."""
        msg = (
            f"📊 *BTC DAILY RSI CLOSE (16:00 ET)*\n\n"
            f"*Date:* {rsi.last_close_date_et}\n"
            f"*16:00 ET Close:* ${rsi.last_close_price:,.2f}\n"
            f"*14d Wilder RSI:* {rsi.finalized_rsi:.2f} ({rsi.label.upper()})\n"
            f"*24h Delta:* {rsi.rsi_delta:+.2f}"
        )
        await self.notifier.send_alert(msg)

    async def run(self):
        # Warm up 14d Wilder RSI (16:00 ET) before launching the live TUI
        await self.rsi_tracker.warmup()
        initial_rsi = self.rsi_tracker.get_metrics(0.0)

        with Live(
            DashboardUI.render(
                self.cvd_tracker.get_metrics(),
                self.vp_tracker.compute_profile(0.0),
                None,
                self.alert_status,
                0,
                initial_rsi,
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

                # Check for 16:00 ET Daily RSI rollover (fires once per calendar day)
                finalized_rsi = self.rsi_tracker.check_and_finalize_close(cvd_metrics.latest_price)
                rsi_metrics = finalized_rsi or self.rsi_tracker.get_metrics(cvd_metrics.latest_price)

                if finalized_rsi is not None:
                    asyncio.create_task(self._format_and_dispatch_rsi_alert(finalized_rsi))
                    DashboardUI.export_snapshot(
                        cvd_metrics, vp_metrics, self.latest_analysis, self.alert_status, self.ticks_count, rsi_metrics
                    )
                    asyncio.create_task(self.git_syncer.push_updates("alert: 16:00 ET daily RSI close"))
                    self.alert_status = f"[bold cyan]16:00 ET RSI LOCKED ({finalized_rsi.finalized_rsi:.2f} | {finalized_rsi.rsi_delta:+.2f})[/bold cyan]"

                if self.ticks_count > 50:
                    total_vol = cvd_metrics.spot_volume + cvd_metrics.perp_volume
                    is_outside_va = vp_metrics.is_above_vah or vp_metrics.is_below_val
                    has_warmup = (now - self.start_time) >= self.min_warmup_seconds
                    has_volume = total_vol >= self.min_volume_threshold
                    has_divergence = abs(cvd_metrics.cvd_divergence) >= self.min_cvd_divergence
                    cooldown_ready = (now - self.last_gemini_call) >= self.inference_cooldown

                    budget_allowed, budget_msg = self.budget_mgr.can_call()

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
                            "daily_rsi_16et": rsi_metrics.finalized_rsi,
                            "daily_rsi_delta": rsi_metrics.rsi_delta,
                            "provisional_rsi": rsi_metrics.provisional_rsi,
                            "daily_rsi_zone": rsi_metrics.label,
                        }

                        try:
                            loop = asyncio.get_running_loop()
                            self.latest_analysis = await loop.run_in_executor(
                                None, self.reasoning_engine.evaluate_market, payload
                            )
                            self.budget_mgr.record_call()

                            # FIXED: 'in ("Low", "Medium")' instead of '== ["Low", "medium"]'
                            if (
                                self.latest_analysis.uncertainty_level in ("Low", "Medium")
                                and (now - self.last_alert_sent >= self.whatsapp_cooldown)
                            ):
                                self.last_alert_sent = now
                                self.last_alert_regime = self.latest_analysis.regime

                                asyncio.create_task(self._format_and_dispatch_alert(cvd_metrics, vp_metrics, self.latest_analysis))

                                DashboardUI.export_snapshot(
                                    cvd_metrics, vp_metrics, self.latest_analysis, self.alert_status, self.ticks_count, rsi_metrics
                                )

                                asyncio.create_task(self.git_syncer.push_updates("alert: high conviction breakout"))
                                self.alert_status = f"[bold green]ALERT DISPATCHED ({self.latest_analysis.regime})[/bold green]"
                            else:
                                self.alert_status = f"Tracking ({self.latest_analysis.regime}) | {self.budget_mgr.get_status_str()}"
                        except Exception as exc:
                            err_str = str(exc)
                            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
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
                        cvd_metrics, vp_metrics, self.latest_analysis, self.alert_status, self.ticks_count, rsi_metrics
                    )
                )
                if now - self.last_snapshot_export >= 300:  # Every 5 minutes
                    self.last_snapshot_export = now
                    DashboardUI.export_snapshot(
                        cvd_metrics,
                        vp_metrics,
                        self.latest_analysis,
                        self.alert_status,
                        self.ticks_count,
                        rsi_metrics,
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