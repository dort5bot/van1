"""
Common base for all private domain clients.
Includes http client, circuit breaker, key validation, and error handling.
"""
from typing import Any, Optional, Dict
import logging

from .binance_request import BinanceHTTPClient
from .binance_circuit_breaker import CircuitBreaker
from .binance_exceptions import (
    BinanceAPIError,
    BinanceAuthenticationError,
    BinanceRequestError,
    BinanceServerError,
    BinanceRateLimitError,
    BinanceBannedError,
    BinanceTimestampError,
)

logger = logging.getLogger(__name__)


class BinancePrivateBase:
    """
    Base class for private Binance clients.

    Attributes:
        http: BinanceHTTPClient instance
        circuit_breaker: CircuitBreaker instance
    """

    def __init__(self, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> None:
        self.http = http_client
        self.circuit_breaker = circuit_breaker

    def _require_keys(self) -> None:
        """Require API key and secret for private endpoints."""
        if not getattr(self.http, "api_key", None) or not getattr(self.http, "secret_key", None):
            logger.error("Binance API key/secret not found on http client")
            raise BinanceAuthenticationError("API key and secret required for private endpoints")

    async def _handle_response(self, response: Any) -> Any:
        """
        Parse Binance API response and raise appropriate errors.

        Args:
            response: HTTP response object (with .status and .json())
        Returns:
            Parsed response JSON
        Raises:
            BinanceAPIError or subclass depending on error
        """
        status = getattr(response, "status", None)
        try:
            data = await response.json()
        except Exception:
            data = None

        # --- HTTP Status-based handling ---
        if status == 400:
            raise BinanceRequestError("Bad request", status, data)
        if status in (401, 403):
            raise BinanceAuthenticationError("Unauthorized", status, data)
        if status == 418:
            raise BinanceBannedError("IP banned by Binance", status, data)
        if status == 429:
            await self.circuit_breaker.trip()
            raise BinanceRateLimitError("Rate limit exceeded", status, data)
        if status and status >= 500:
            raise BinanceServerError("Binance server error", status, data)

        # --- Binance JSON code-based handling ---
        if isinstance(data, dict) and "code" in data and data["code"] != 0:
            code = data.get("code")
            msg = data.get("msg", "Unknown Binance error")

            if code in (-2014, -2015):
                raise BinanceAuthenticationError(msg, code, data)
            if code == -1021:
                raise BinanceTimestampError(msg, code, data)
            if code == -1003:
                await self.circuit_breaker.trip()
                raise BinanceRateLimitError(msg, code, data)
            if -1199 <= code <= -1100:
                raise BinanceRequestError(msg, code, data)

            raise BinanceAPIError(msg, code, data)

        return data
