import json
from btc_alert.reasoning.gemini_engine import GeminiReasoningEngine

def main():
    print("Testing Gemini Structured Output reasoning engine...")
    engine = GeminiReasoningEngine()

    mock_metrics = {
        "price": 79250.00,
        "vah": 78800.00,
        "val": 78200.00,
        "poc_price": 78900.00,
        "is_above_vah": True,
        "is_below_val": False,
        "spot_cvd_delta_60m": 580.45,
        "perp_cvd_delta_60m": 1420.10,
        "cvd_divergence": -839.65,
        "spot_volume_60m": 3100.5,
        "perp_volume_60m": 8900.2
    }

    result = engine.evaluate_market(mock_metrics)

    print("\n=== Gemini Microstructure Synthesis Output ===")
    print(f"Regime: {result.regime}")
    print(f"Uncertainty: {result.uncertainty_level}")
    print(f"Briefing: {result.verbal_summary}")
    print(f"Primary Risk: {result.key_risk_factor}")
    print("\nReasoning test completed successfully!")

if __name__ == "__main__":
    main()