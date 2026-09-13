import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class AlertSnippetExporter:
    """Exports alert events to structured JSON and self-contained HTML components."""

    def __init__(self, datashare_dir: Path, auto_git_push: bool = False):
        self.datashare_dir = Path(datashare_dir)
        self.alerts_dir = self.datashare_dir / "btc-alerts"
        self.archive_dir = self.alerts_dir / "archive"
        self.auto_git_push = auto_git_push

        # Ensure directory structure exists
        self.alerts_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def export(self, payload: Dict[str, Any]) -> None:
        """Writes the JSON and HTML files and optionally triggers Git sync."""
        timestamp = payload.get(
            "timestamp", datetime.now(timezone.utc).isoformat()
        )
        file_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # 1. Write structured JSON
        latest_json = self.alerts_dir / "btc-alert-latest.json"
        archive_json = self.archive_dir / f"btc-alert-{file_ts}.json"
        json_str = json.dumps(payload, indent=2)

        latest_json.write_text(json_str, encoding="utf-8")
        archive_json.write_text(json_str, encoding="utf-8")

        # 2. Render and write HTML component
        html_str = self._render_html(payload)
        latest_html = self.alerts_dir / "btc-alert-latest.html"
        archive_html = self.archive_dir / f"btc-alert-{file_ts}.html"

        latest_html.write_text(html_str, encoding="utf-8")
        archive_html.write_text(html_str, encoding="utf-8")

        # 3. Optional automated Git commit and push
        if self.auto_git_push:
            self._sync_to_github(file_ts)

    def _render_html(self, data: Dict[str, Any]) -> str:
        price = data.get("price", 0.0)
        regime = data.get("regime", "Unknown")
        spot_cvd = data.get("spot_cvd", 0.0)
        perp_cvd = data.get("perp_cvd", 0.0)
        divergence = data.get("divergence", 0.0)
        poc = data.get("poc", 0.0)
        vah = data.get("vah", 0.0)
        val = data.get("val", 0.0)
        analysis = data.get("analysis", "")
        key_risk = data.get("key_risk", "")
        ts = data.get("timestamp", datetime.now(timezone.utc).isoformat())

        def fmt_cvd(val: float) -> str:
            sign = "+" if val > 0 else ""
            return f"{sign}{val:,.2f} BTC"

        def cvd_class(val: float) -> str:
            return "btc-pos" if val >= 0 else "btc-neg"

        return f"""<!-- BTC Alert Web Component -->
<div class="btc-alert" data-timestamp="{ts}">
  <style>
    .btc-alert {{
      --bg: #0d1117;
      --border: #30363d;
      --text: #c9d1d9;
      --accent: #58a6ff;
      --green: #3fb950;
      --red: #f85149;
      --muted: #8b949e;
      --font: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      font-family: var(--font);
      font-size: 13px;
      line-height: 1.45;
      max-width: 480px;
      padding: 16px;
      box-sizing: border-box;
    }}
    .btc-alert * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    .btc-alert-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
      margin-bottom: 12px;
      font-weight: 700;
      color: var(--accent);
    }}
    .btc-alert-grid {{
      display: grid;
      grid-template-columns: 1fr auto;
      row-gap: 5px;
      margin-bottom: 12px;
    }}
    .btc-alert-label {{ color: var(--muted); }}
    .btc-alert-val {{ text-align: right; font-weight: 600; }}
    .btc-pos {{ color: var(--green); }}
    .btc-neg {{ color: var(--red); }}
    .btc-alert-body {{
      background: rgba(255, 255, 255, 0.03);
      border-left: 3px solid var(--accent);
      padding: 8px 12px;
      font-size: 12px;
      color: #e6edf3;
      margin-bottom: 8px;
    }}
    .btc-alert-risk {{
      border-left: 3px solid var(--red);
      background: rgba(248, 81, 73, 0.05);
      padding: 8px 12px;
      font-size: 12px;
      color: #e6edf3;
    }}
  </style>

  <div class="btc-alert-header">
    <span>⚡ BTC ORDER FLOW BREAKOUT</span>
    <span>{price:,.2f} USD</span>
  </div>

  <div class="btc-alert-grid">
    <span class="btc-alert-label">Regime</span>
    <span class="btc-alert-val">{regime}</span>

    <span class="btc-alert-label">Spot CVD (60m)</span>
    <span class="btc-alert-val {cvd_class(spot_cvd)}">{fmt_cvd(spot_cvd)}</span>

    <span class="btc-alert-label">Perp CVD (60m)</span>
    <span class="btc-alert-val {cvd_class(perp_cvd)}">{fmt_cvd(perp_cvd)}</span>

    <span class="btc-alert-label">Divergence</span>
    <span class="btc-alert-val {cvd_class(divergence)}">{fmt_cvd(divergence)}</span>

    <span class="btc-alert-label">POC | VAH | VAL</span>
    <span class="btc-alert-val">{poc:,.0f} | {vah:,.0f} | {val:,.0f} USD</span>
  </div>

  <div class="btc-alert-body">
    <strong>Analysis:</strong> {analysis}
  </div>

  {f'<div class="btc-alert-risk"><strong>Key Risk:</strong> {key_risk}</div>' if key_risk else ''}
</div>
"""

    def _sync_to_github(self, batch_id: str) -> None:
        """Stages files and pushes to the repository non-blockingly."""
        try:
            subprocess.run(
                ["git", "add", "btc-alerts/"],
                cwd=self.datashare_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"chore(alerts): update alert snapshot {batch_id} [skip ci]",
                ],
                cwd=self.datashare_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=self.datashare_dir,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            # Avoid crashing daemon if the remote is temporarily unreachable
            print(f"[AlertSnippetExporter] Git push warning: {e}")