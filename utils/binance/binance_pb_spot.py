"""
utils/binance/binance_pb_spot.py
--------------------------------
Spot (public) endpoints wrapper.

- Sadece public spot market verilerine ait endpointleri içerir.
- Async / aiohttp tabanlı BinanceHTTPClient ile çalışır.
- Singleton pattern ile instance yönetimi.
- PEP8, type hints, docstrings ve logging içerir.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .binance_request import BinanceHTTPClient
from .binance_constants import (
    SPOT_PING_ENDPOINT,
    SPOT_TIME_ENDPOINT,
    SPOT_EXCHANGE_INFO_ENDPOINT,
    SPOT_ORDER_BOOK_ENDPOINT,
    SPOT_KLINE_ENDPOINT,
    SPOT_AGG_TRADE_ENDPOINT,
    SPOT_TICKER_24H_ENDPOINT,
    SPOT_TICKER_PRICE_ENDPOINT,
    SPOT_TICKER_BOOK_ENDPOINT,
)
from .binance_types import ExchangeInfo, Kline, OrderBook, Ticker, Trade

logger = logging.getLogger(__name__)


class BinancePBSpot:
    """
    Public-Spot (PB) wrapper exposing commonly used public endpoints.

    Usage:
        client = BinancePBSpot.get_instance(http_client=BinanceHTTPClient(...))
        await client.ping()
    """

    _instance: Optional["BinancePBSpot"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None) -> None:
        """
        Create a wrapper instance. If http_client is not provided, an internal
        default BinanceHTTPClient() will be created (without API keys, since public).
        """
        self._http = http_client or BinanceHTTPClient()
        logger.debug("BinancePBSpot initialized")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinancePBSpot":
        """Return singleton instance (optionally supplying an http client)."""
        if cls._instance is None:
            cls._instance = cls(http_client=http_client)
        elif http_client is not None:
            # allow replacing underlying client if explicitly provided first time
            cls._instance._http = http_client
        return cls._instance

    # -------------------------
    # System / simple helpers
    # -------------------------
    async def ping(self) -> bool:
        """
        Ping endpoint - returns True if Binance responds.
        """
        logger.debug("Spot: ping")
        await self._http.get(SPOT_PING_ENDPOINT)
        return True

    async def server_time(self) -> int:
        """
        Get server time (ms).
        """
        logger.debug("Spot: server_time")
        data = await self._http.get(SPOT_TIME_ENDPOINT)
        ts = int(data.get("serverTime", 0))
        logger.debug("Spot server time: %s", ts)
        return ts

    async def exchange_info(self, symbol: Optional[str] = None) -> ExchangeInfo:
        """
        Return exchangeInfo (optionally filtered by symbol).
        """
        params = {"symbol": symbol} if symbol else None
        logger.debug("Spot: exchange_info (%s)", symbol)
        data = await self._http.get(SPOT_EXCHANGE_INFO_ENDPOINT, params=params)
        # Type hinting to ExchangeInfo (caller should validate)
        return data  # type: ignore[return-value]

    # -------------------------
    # Market Data
    # -------------------------
    async def order_book(self, symbol: str, limit: int = 100) -> OrderBook:
        """
        Get order book for a symbol.
        limit allowed: up to 1000 (Binance); default 100.
        """
        params = {"symbol": symbol.upper(), "limit": int(limit)}
        logger.debug("Spot: order_book %s limit=%s", symbol, limit)
        data = await self._http.get(SPOT_ORDER_BOOK_ENDPOINT, params=params)
        return data  # type: ignore[return-value]

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """
        Get klines/candles.
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": int(limit),
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Spot: klines %s interval=%s start=%s end=%s limit=%s", symbol, interval, start_time, end_time, limit)
        data = await self._http.get(SPOT_KLINE_ENDPOINT, params=params)
        # Binance returns list[list]; caller may map to Kline TypedDict if desired
        return data  # type: ignore[return-value]

    async def agg_trades(
        self,
        symbol: str,
        from_id: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Trade]:
        """
        Aggregated trades list.
        """
        params: Dict[str, Any] = {"symbol": symbol.upper(), "limit": int(limit)}
        if from_id is not None:
            params["fromId"] = int(from_id)
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Spot: agg_trades %s params=%s", symbol, params)
        data = await self._http.get(SPOT_AGG_TRADE_ENDPOINT, params=params)
        return data  # type: ignore[return-value]

    async def ticker_24hr(self, symbol: Optional[str] = None) -> Any:
        """
        24hr ticker price change statistics.
        If symbol is None returns array for all symbols.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Spot: ticker_24hr %s", symbol)
        data = await self._http.get(SPOT_TICKER_24H_ENDPOINT, params=params)
        return data

    async def ticker_price(self, symbol: Optional[str] = None) -> Any:
        """
        Current average price for symbol(s).
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Spot: ticker_price %s", symbol)
        data = await self._http.get(SPOT_TICKER_PRICE_ENDPOINT, params=params)
        return data

    async def ticker_book(self, symbol: Optional[str] = None) -> Any:
        """
        Best bid/ask for symbol(s).
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Spot: ticker_book %s", symbol)
        data = await self._http.get(SPOT_TICKER_BOOK_ENDPOINT, params=params)
        return data
