import urllib.parse
import aiohttp
import logging
from btc_alert.config import config

logger = logging.getLogger(__name__)

class WhatsAppNotifier:
    def __init__(self):
        self.phone = config.WHATSAPP_PHONE_NUMBER
        self.api_key = config.WHATSAPP_API_KEY
        self.base_url = "https://api.callmebot.com/whatsapp.php"

    async def send_alert(self, message: str) -> bool:
        """Sends a high-priority encoded message via CallMeBot API."""
        if not self.phone or not self.api_key:
            return False

        encoded_msg = urllib.parse.quote(message)
        url = f"{self.base_url}?phone={self.phone}&text={encoded_msg}&apikey={self.api_key}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status == 200
        except Exception:
            return False