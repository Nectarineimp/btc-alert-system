import json
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.align import Align
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from btc_alert.analytics.cvd import CVDMetrics
from btc_alert.analytics.volume_profile import VolumeProfileMetrics
from btc_alert.exporters.html_exporter import AlertSnippetExporter
from btc_alert.reasoning.schemas import MicrostructureAnalysis

from btc_alert.analytics.rsi import RSIMetrics


class DashboardUI:
    _exporter: AlertSnippetExporter | None = None

    @classmethod
    def get_exporter(cls) -> AlertSnippetExporter:
        if cls._exporter is None:
            datashare_path = Path.home() / "projects" / "BTCSunrise-datashare"
            cls._exporter = AlertSnippetExporter(
                datashare_dir=datashare_path,
                auto_git_push=False,  # GitSyncer handles git pushes in main.py
            )
        return cls._exporter

    @classmethod
    def export_snapshot(
        cls,
        cvd: CVDMetrics,
        vp: VolumeProfileMetrics,
        analysis: MicrostructureAnalysis | None,
        status_msg: str,
        ticks_count: int,
        rsi: RSIMetrics | None = None,
        output_dir: str = "web_export",
    ):
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        exporter = cls.get_exporter()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": float(cvd.latest_price),
            "regime": analysis.regime if analysis else "Consolidation",
            "spot_cvd": float(cvd.spot_cvd_delta),
            "perp_cvd": float(cvd.perp_cvd_delta),
            "divergence": float(cvd.cvd_divergence),
            "poc": float(vp.poc_price),
            "vah": float(vp.vah_price),
            "val": float(vp.val_price),
            "daily_rsi": float(rsi.finalized_rsi) if (rsi and rsi.is_warmed_up) else None,
            "rsi_delta": float(rsi.rsi_delta) if (rsi and rsi.is_warmed_up) else None,
            "provisional_rsi": float(rsi.provisional_rsi) if (rsi and rsi.is_warmed_up) else None,
            "rsi_close_date_et": rsi.last_close_date_et if (rsi and rsi.is_warmed_up) else None,
            "analysis": analysis.verbal_summary if analysis else "",
            "key_risk": analysis.key_risk_factor if analysis else "",
            "rsi_label": rsi.label if (rsi and rsi.is_warmed_up) else None,
        }
        exporter.export(payload)

        local_data = {
            "timestamp": int(time.time()),
            "price": cvd.latest_price,
            "poc": vp.poc_price,
            "vah": vp.vah_price,
            "val": vp.val_price,
            "spot_cvd": cvd.spot_cvd_delta,
            "perp_cvd": cvd.perp_cvd_delta,
            "divergence": cvd.cvd_divergence,
            "daily_rsi": rsi.finalized_rsi if (rsi and rsi.is_warmed_up) else None,
            "rsi_delta": rsi.rsi_delta if (rsi and rsi.is_warmed_up) else None,
            "provisional_rsi": rsi.provisional_rsi if (rsi and rsi.is_warmed_up) else None,
            "regime": analysis.regime if analysis else "Consolidation",
            "uncertainty": analysis.uncertainty_level if analysis else "High",
            "summary": analysis.verbal_summary if analysis else "",
            "risk": analysis.key_risk_factor if analysis else "",
            "rsi_label": rsi.label if (rsi and rsi.is_warmed_up) else None,
        }
        with open(f"{output_dir}/latest_regime.json", "w") as f:
            json.dump(local_data, f, indent=2)


    @staticmethod
    def render(
        cvd: CVDMetrics,
        vp: VolumeProfileMetrics,
        analysis: MicrostructureAnalysis | None,
        last_alert_msg: str,
        ticks_processed: int,
        rsi: RSIMetrics | None = None,
    ) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="narrative", size=7),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="left_metrics", ratio=3),
            Layout(name="right_status", ratio=2),
        )

        # 1. Header
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_text = Text(
            f"⚡ BTC MICROSTRUCTURE DAEMON | {now_str} | Ticks: {ticks_processed:,}",
            style="bold white on blue",
        )
        layout["header"].update(Panel(Align.center(header_text), style="blue"))

        # 2. Gemini Narrative Panel
        if analysis:
            color = (
                "green"
                if analysis.uncertainty_level == "Low"
                else ("yellow" if analysis.uncertainty_level == "Medium" else "red")
            )
            narrative_body = (
                f"[bold cyan]Regime:[/bold cyan] [{color}]{analysis.regime}[/{color}]  |  "
                f"[bold cyan]Uncertainty:[/bold cyan] [{color}]{analysis.uncertainty_level}[/{color}]\n"
                f"[bold white]{analysis.verbal_summary}[/bold white]\n"
                f"[yellow]Primary Risk: {analysis.key_risk_factor}[/yellow]"
            )
        else:
            narrative_body = "[dim yellow]Aggregating order flow... Awaiting initial Gemini synthesis.[/dim yellow]"

        layout["narrative"].update(
            Panel(
                narrative_body,
                title="[bold magenta]Gemini Microstructure Synthesis[/bold magenta]",
                border_style="magenta",
            )
        )

        # 3. Left Table: Microstructure Order Flow Metrics
        table = Table(expand=True, box=None)
        table.add_column("Metric", style="bold cyan")
        table.add_column("Value", style="bold white", justify="right")

        spot_color = "green" if cvd.spot_cvd_delta >= 0 else "red"
        perp_color = "green" if cvd.perp_cvd_delta >= 0 else "red"
        div_color = "green" if cvd.cvd_divergence >= 0 else "red"

        table.add_row("Current Price", f"${cvd.latest_price:,.2f}")
        table.add_row("Spot CVD (60m)", f"[{spot_color}]{cvd.spot_cvd_delta:+,.4f} BTC[/{spot_color}]")
        table.add_row("Perp CVD (60m)", f"[{perp_color}]{cvd.perp_cvd_delta:+,.4f} BTC[/{perp_color}]")
        table.add_row("CVD Divergence", f"[{div_color}]{cvd.cvd_divergence:+,.4f} BTC[/{div_color}]")
        table.add_row("Point of Control (POC)", f"${vp.poc_price:,.2f}")
        table.add_row(
            "Value Area High (VAH)",
            f"${vp.vah_price:,.2f} {'[green](Above)[/green]' if vp.is_above_vah else ''}",
        )
        table.add_row(
            "Value Area Low (VAL)",
            f"${vp.val_price:,.2f} {'[red](Below)[/red]' if vp.is_below_val else ''}",
        )

        layout["left_metrics"].update(
            Panel(table, title="[bold cyan]Order Flow & Volume Profile[/bold cyan]", border_style="cyan")
        )

        if rsi and rsi.is_warmed_up:
            rsi_val = rsi.finalized_rsi
            rsi_color = (
                "bold green" if rsi_val < 20
                else "green" if rsi_val < 30
                else "yellow" if rsi_val < 45
                else "white" if rsi_val <= 55
                else "cyan" if rsi_val <= 70
                else "red" if rsi_val <= 80
                else "bold red"
            )
            delta_color = "green" if rsi.rsi_delta >= 0 else "red"
            table.add_row(
                "Daily RSI (16:00 ET)",
                f"[{rsi_color}]{rsi.finalized_rsi:.2f}[/{rsi_color}] "
                f"[{delta_color}]({rsi.rsi_delta:+.2f})[/{delta_color}] "
                f"[dim]| Live: {rsi.provisional_rsi:.2f}[/dim]",
            )
            table.add_row(
                "RSI Zone",
                f"[{rsi_color}]{rsi.label}[/{rsi_color}]",
            )
        else:
            table.add_row("Daily RSI (16:00 ET)", "[dim]Warming up...[/dim]")
            
        # 4. Right Status Panel
        status_text = (
            f"[bold green]Daemon:[/bold green] Active (WebSockets Streaming)\n"
            f"[bold green]Spot Volume:[/bold green] {cvd.spot_volume:,.2f} BTC\n"
            f"[bold green]Perp Volume:[/bold green] {cvd.perp_volume:,.2f} BTC\n\n"
            f"[bold yellow]Alert Gateway:[/bold yellow]\n{last_alert_msg}"
        )
        layout["right_status"].update(
            Panel(status_text, title="[bold yellow]System Status[/bold yellow]", border_style="yellow")
        )

        return layout