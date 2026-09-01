import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    WHATSAPP_PHONE: str = os.getenv("WHATSAPP_PHONE_NUMBER", "")
    WHATSAPP_API_KEY: str = os.getenv("WHATSAPP_API_KEY", "")
    
    # Analysis & Engine Parameters
    ROLLING_WINDOW_MINUTES: int = int(os.getenv("ROLLING_WINDOW_MINUTES", "60"))
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
    BIN_SIZE: float = 50.0  # Dollar granularity for Volume Profile bins

config = Config()
