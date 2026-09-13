from pathlib import Path
from btc_alert.exporters.html_exporter import AlertSnippetExporter

test_repo = Path.home() / "projects" / "BTCSunrise-datashare"
exporter = AlertSnippetExporter(datashare_dir=test_repo, auto_git_push=False)

sample_data = {
    "price": 79581.40,
    "regime": "Spot-Led Expansion",
    "spot_cvd": 58.50,
    "perp_cvd": -4.25,
    "divergence": 62.75,
    "poc": 78900.0,
    "vah": 79050.0,
    "val": 78700.0,
    "analysis": "Bitcoin is executing a spot-led expansion above the Value Area High, backed by positive spot CVD accumulation absorbing perpetual selling pressure.",
    "key_risk": "Acceptance failure below VAH (79,050) triggering a sharp mean-reversion back toward POC (78,900).",
}

exporter.export(sample_data)
print("Files successfully generated in:", test_repo / "btc-alerts")