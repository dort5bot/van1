"""
utils/binance/binance_pb_futures.py
----------------------------------
Futures (public) endpoints wrapper.

- Futures public endpoints (market data) için metodlar içerir.
- Async / aiohttp tabanlı BinanceHTTPClient ile çalışır.
- Singleton pattern, PEP8, type hints, docstrings ve logging içerir.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .binance_request import BinanceHTTPClient
from .binance_constants import (
    FUTURES_PING_ENDPOINT,
    FUTURES_TIME_ENDPOINT,
    FUTURES_EXCHANGE_INFO_ENDPOINT,
    FUTURES_ORDER_BOOK_ENDPOINT,
    FUTURES_KLINE_ENDPOINT,
)
from .binance_types import ExchangeInfo, Kline, OrderBook

logger = logging.getLogger(__name__)


class BinancePBFutures:
    """
    Public-Futures (PB) wrapper exposing commonly used futures public endpoints.

    Usage:
        fut = BinancePBFutures.get_instance()
        await fut.ping()
    """

    _instance: Optional["BinancePBFutures"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None) -> None:
        # futures flag will be passed to underlying HTTP client methods
        self._http = http_client or BinanceHTTPClient()
        logger.debug("BinancePBFutures initialized")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinancePBFutures":
        """Return singleton instance."""
        if cls._instance is None:
            cls._instance = cls(http_client=http_client)
        elif http_client is not None:
            cls._instance._http = http_client
        return cls._instance

    # -------------------------
    # System / simple helpers
    # -------------------------
    async def ping(self) -> bool:
        """Ping futures endpoint."""
        logger.debug("Futures: ping")
        await self._http.get(FUTURES_PING_ENDPOINT, futures=True)
        return True

    async def server_time(self) -> int:
        """Get futures server time (ms)."""
        logger.debug("Futures: server_time")
        data = await self._http.get(FUTURES_TIME_ENDPOINT, futures=True)
        return int(data.get("serverTime", 0))

    async def exchange_info(self, symbol: Optional[str] = None) -> ExchangeInfo:
        """
        Futures exchange info.
        """
        params = {"symbol": symbol} if symbol else None
        logger.debug("Futures: exchange_info %s", symbol)
        data = await self._http.get(FUTURES_EXCHANGE_INFO_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    # -------------------------
    # Market Data
    # -------------------------
    async def order_book(self, symbol: str, limit: int = 100) -> OrderBook:
        """Get futures order book."""
        params = {"symbol": symbol.upper(), "limit": int(limit)}
        logger.debug("Futures: order_book %s limit=%s", symbol, limit)
        data = await self._http.get(FUTURES_ORDER_BOOK_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """Get futures klines."""
        params: Dict[str, Any] = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Futures: klines %s interval=%s start=%s end=%s limit=%s", symbol, interval, start_time, end_time, limit)
        data = await self._http.get(FUTURES_KLINE_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]
