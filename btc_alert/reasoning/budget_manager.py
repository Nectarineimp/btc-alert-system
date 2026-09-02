import time
from collections import deque

class InferenceBudgetManager:
    def __init__(self, max_per_hour: int = 6, max_per_day: int = 50):
        self.max_per_hour = max_per_hour
        self.max_per_day = max_per_day
        
        self.hourly_calls: deque[float] = deque()
        self.daily_calls: deque[float] = deque()
        self.rate_limit_lockout_until: float = 0.0

    def can_call(self) -> tuple[bool, str]:
        now = time.time()

        # Check if we are in an active 429 backoff lockout
        if now < self.rate_limit_lockout_until:
            remaining_mins = int((self.rate_limit_lockout_until - now) / 60)
            return False, f"429 Cooloff ({remaining_mins}m left)"

        # Prune calls outside the sliding windows
        while self.hourly_calls and now - self.hourly_calls[0] > 3600:
            self.hourly_calls.popleft()

        while self.daily_calls and now - self.daily_calls[0] > 86400:
            self.daily_calls.popleft()

        if len(self.hourly_calls) >= self.max_per_hour:
            return False, f"Hourly budget reached ({len(self.hourly_calls)}/{self.max_per_hour})"

        if len(self.daily_calls) >= self.max_per_day:
            return False, f"Daily budget reached ({len(self.daily_calls)}/{self.max_per_day})"

        return True, "Ready"

    def record_call(self):
        now = time.time()
        self.hourly_calls.append(now)
        self.daily_calls.append(now)

    def trigger_rate_limit_lockout(self, duration_seconds: int = 1800):
        """Called upon receiving a 429: silences calls for 30 minutes."""
        self.rate_limit_lockout_until = time.time() + duration_seconds

    def get_status_str(self) -> str:
        now = time.time()
        while self.hourly_calls and now - self.hourly_calls[0] > 3600:
            self.hourly_calls.popleft()
        while self.daily_calls and now - self.daily_calls[0] > 86400:
            self.daily_calls.popleft()
            
        return f"{len(self.hourly_calls)}/{self.max_per_hour} RPH | {len(self.daily_calls)}/{self.max_per_day} RPD"