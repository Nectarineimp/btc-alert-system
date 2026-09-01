import time
from rich.live import Live
from btc_alert.ui.dashboard import DashboardUI
from btc_alert.analytics.cvd import CVDMetrics
from btc_alert.analytics.volume_profile import VolumeProfileMetrics
from btc_alert.reasoning.schemas import MicrostructureAnalysis

def main():
    mock_cvd = CVDMetrics(
        spot_cvd_delta=420.50,
        perp_cvd_delta=-120.30,
        cvd_divergence=540.80,
        spot_volume=1850.0,
        perp_volume=3200.0,
        latest_price=78925.50
    )
    mock_vp = VolumeProfileMetrics(
        poc_price=78600.0,
        vah_price=78850.0,
        val_price=78400.0,
        is_above_vah=True,
        is_below_val=False,
        total_profile_volume=5050.0
    )
    mock_analysis = MicrostructureAnalysis(
        regime="Spot-Led Expansion",
        uncertainty_level="Low",
        verbal_summary="Strong spot market bids are lifting price clean through Value Area High with negative perp delta. Directional momentum is firmly backed by genuine spot accumulation.",
        key_risk_factor="Thin liquidity gaps between 79,200 and 80,000"
    )

    print("Rendering TUI preview for 5 seconds...")
    with Live(DashboardUI.render(mock_cvd, mock_vp, mock_analysis, "Awaiting conviction trigger", 14820), refresh_per_second=4, screen=True) as live:
        for _ in range(20):
            mock_cvd.latest_price += 2.5
            live.update(DashboardUI.render(mock_cvd, mock_vp, mock_analysis, "Awaiting conviction trigger", 14820))
            time.sleep(0.25)

if __name__ == "__main__":
    main()