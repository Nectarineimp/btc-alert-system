import asyncio
import time
from btc_alert.ingestion.websocket_client import BinanceStreamClient
from btc_alert.analytics.cvd import RollingCVDTracker
from btc_alert.analytics.volume_profile import RollingVolumeProfile

async def main():
    client = BinanceStreamClient()
    cvd_tracker = RollingCVDTracker(window_seconds=60)
    vp_tracker = RollingVolumeProfile(window_seconds=60, bin_size=25.0)
    
    print("Aggregating live ticks for 10 seconds to compute indicators...")
    start_time = time.time()
    
    async for tick in client.stream_trades():
        cvd_tracker.add_tick(tick)
        vp_tracker.add_tick(tick)
        
        if time.time() - start_time >= 10.0:
            break
            
    cvd = cvd_tracker.get_metrics()
    vp = vp_tracker.compute_profile(cvd.latest_price)
    
    print("\n=== 10-Second Live Analytics Snapshot ===")
    print(f"Latest Price: ${cvd.latest_price:.2f}")
    print(f"Spot CVD Delta: {cvd.spot_cvd_delta:+.4f} BTC (Vol: {cvd.spot_volume:.2f} BTC)")
    print(f"Perp CVD Delta: {cvd.perp_cvd_delta:+.4f} BTC (Vol: {cvd.perp_volume:.2f} BTC)")
    print(f"CVD Divergence: {cvd.cvd_divergence:+.4f} BTC")
    print(f"POC: ${vp.poc_price:.2f} | VAH: ${vp.vah_price:.2f} | VAL: ${vp.val_price:.2f}")
    print(f"Above VAH: {vp.is_above_vah} | Below VAL: {vp.is_below_val}")
    print("Analytics test completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())