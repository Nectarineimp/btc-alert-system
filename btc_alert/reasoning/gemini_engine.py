import json
import logging
from google import genai
from google.genai import types
from btc_alert.config import config
from btc_alert.reasoning.schemas import MicrostructureAnalysis

# Suppress verbose AFC/SDK informational notices
logging.getLogger("google.genai").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

class GeminiReasoningEngine:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.model_name = "gemini-3.6-flash"

    def evaluate_market(self, payload: dict) -> MicrostructureAnalysis:
        """Sends quantitative metrics to Gemini and parses the structured response."""
        system_instruction = (
            "You are an institutional crypto market microstructure quantitative analyst. "
            "Analyze the provided Bitcoin order flow metrics (Spot/Perp CVD, Volume Profile, POC, VAH/VAL) "
            "and produce a concise, grounded assessment without hype or fluff."
        )

        prompt = f"Evaluate the following live Bitcoin order flow metrics:\n{json.dumps(payload, indent=2)}"

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=MicrostructureAnalysis,
                    temperature=0.2,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            return MicrostructureAnalysis.model_validate_json(response.text)
        except Exception as exc:
            logger.error(f"Gemini API inference error: {exc}")
            raise