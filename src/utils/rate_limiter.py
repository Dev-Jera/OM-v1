"""
Rate limiting utility for web scraping
"""

import time
from collections import deque
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter that enforces requests per minute limit
    Uses sliding window algorithm
    """

    def __init__(self, requests_per_minute: int):
        """
        Initialize rate limiter

        Args:
            requests_per_minute: Maximum number of requests allowed per minute
        """
        self.requests_per_minute = requests_per_minute
        self.request_times: deque = deque()
        self.last_request_time: Optional[float] = None

    def _cleanup_old_requests(self, current_time: float) -> None:
        """Remove requests older than 1 minute"""
        while self.request_times and current_time - self.request_times[0] > 60.0:
            self.request_times.popleft()

    def wait_if_needed(self) -> None:
        """
        Wait if necessary to respect rate limit
        Should be called before each request
        """
        if not self.requests_per_minute:
            return

        current_time = time.time()
        self._cleanup_old_requests(current_time)

        # Check if we've hit the limit
        if len(self.request_times) >= self.requests_per_minute:
            # Calculate wait time until oldest request expires
            oldest_time = self.request_times[0]
            wait_time = 60.0 - (current_time - oldest_time) + 0.1  # Add small buffer
            if wait_time > 0:
                logger.debug(f"Rate limit reached. Waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
                # Clean up again after waiting
                current_time = time.time()
                self._cleanup_old_requests(current_time)

        # Record this request
        self.request_times.append(time.time())
        self.last_request_time = time.time()

    def get_stats(self) -> dict:
        """Get current rate limiter statistics"""
        current_time = time.time()
        self._cleanup_old_requests(current_time)

        return {"requests_in_last_minute": len(self.request_times), "limit": self.requests_per_minute, "last_request_time": self.last_request_time}
