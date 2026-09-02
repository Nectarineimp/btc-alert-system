from datetime import datetime
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from btc_alert.analytics.cvd import CVDMetrics
from btc_alert.analytics.volume_profile import VolumeProfileMetrics
from btc_alert.reasoning.schemas import MicrostructureAnalysis
import json
import time
from pathlib import Path
from rich.console import Console

class DashboardUI:
    @classmethod
    def export_snapshot(
        cls,
        cvd,
        vp,
        analysis,
        status_msg: str,
        ticks_count: int,
        output_dir: str = "web_export"
    ):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # 1. Render crisp vector SVG
        record_console = Console(record=True, width=110, height=26)
        layout = cls.render(cvd, vp, analysis, status_msg, ticks_count)
        record_console.print(layout)
        record_console.save_svg(f"{output_dir}/microstructure.svg", title="BTC Microstructure Monitor")

        # 2. Save companion JSON
        data = {
            "timestamp": int(time.time()),
            "price": cvd.latest_price,
            "poc": vp.poc_price,
            "vah": vp.vah_price,
            "val": vp.val_price,
            "spot_cvd": cvd.spot_cvd_delta,
            "perp_cvd": cvd.perp_cvd_delta,
            "divergence": cvd.cvd_divergence,
            "regime": analysis.regime if analysis else "Consolidation",
            "uncertainty": analysis.uncertainty_level if analysis else "High",
            "summary": analysis.verbal_summary if analysis else "",
            "risk": analysis.key_risk_factor if analysis else "",
        }
        with open(f"{output_dir}/latest_regime.json", "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def render(
        cvd: CVDMetrics,
        vp: VolumeProfileMetrics,
        analysis: MicrostructureAnalysis | None,
        last_alert_msg: str,
        ticks_processed: int
    ) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="narrative", size=7),
            Layout(name="body")
        )
        layout["body"].split_row(
            Layout(name="left_metrics", ratio=3),
            Layout(name="right_status", ratio=2)
        )

        # 1. Header
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_text = Text(f"⚡ BTC MICROSTRUCTURE DAEMON | {now_str} | Ticks: {ticks_processed:,}", style="bold white on blue")
        layout["header"].update(Panel(Align.center(header_text), style="blue"))

        # 2. Gemini Narrative Panel
        if analysis:
            color = "green" if analysis.uncertainty_level == "Low" else ("yellow" if analysis.uncertainty_level == "Medium" else "red")
            narrative_body = (
                f"[bold cyan]Regime:[/bold cyan] [{color}]{analysis.regime}[/{color}]  |  "
                f"[bold cyan]Uncertainty:[/bold cyan] [{color}]{analysis.uncertainty_level}[/{color}]\n"
                f"[bold white]{analysis.verbal_summary}[/bold white]\n"
                f"[yellow]Primary Risk: {analysis.key_risk_factor}[/yellow]"
            )
        else:
            narrative_body = "[dim yellow]Aggregating order flow... Awaiting initial Gemini synthesis.[/dim yellow]"

        layout["narrative"].update(Panel(narrative_body, title="[bold magenta]Gemini Microstructure Synthesis[/bold magenta]", border_style="magenta"))

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
        table.add_row("Value Area High (VAH)", f"${vp.vah_price:,.2f} {'[green](Above)[/green]' if vp.is_above_vah else ''}")
        table.add_row("Value Area Low (VAL)", f"${vp.val_price:,.2f} {'[red](Below)[/red]' if vp.is_below_val else ''}")

        layout["left_metrics"].update(Panel(table, title="[bold cyan]Order Flow & Volume Profile[/bold cyan]", border_style="cyan"))

        # 4. Right Status Panel
        status_text = (
            f"[bold green]Daemon:[/bold green] Active (WebSockets Streaming)\n"
            f"[bold green]Spot Volume:[/bold green] {cvd.spot_volume:,.2f} BTC\n"
            f"[bold green]Perp Volume:[/bold green] {cvd.perp_volume:,.2f} BTC\n\n"
            f"[bold yellow]Alert Gateway:[/bold yellow]\n{last_alert_msg}"
        )
        layout["right_status"].update(Panel(status_text, title="[bold yellow]System Status[/bold yellow]", border_style="yellow"))

        return layout