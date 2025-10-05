"""
utils/binance_api/binance_pb_system.py
---------------------------------
System related public endpoints and helpers.

- Exchange info, ping, health helpers and small convenience wrappers.
- Kullanıcıların hem spot hem futures için ortak system işlemlerini sağlar.
- Async / singleton / logging
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .binance_request import BinanceHTTPClient
from .binance_constants import (
    SPOT_PING_ENDPOINT,
    SPOT_TIME_ENDPOINT,
    SPOT_EXCHANGE_INFO_ENDPOINT,
    FUTURES_PING_ENDPOINT,
    FUTURES_TIME_ENDPOINT,
    FUTURES_EXCHANGE_INFO_ENDPOINT,
)
from .binance_metrics import AdvancedMetrics
from .binance_types import ExchangeInfo

logger = logging.getLogger(__name__)


class BinancePBSystem:
    """
    System helpers for both Spot and Futures public endpoints.

    Responsibilities:
    - ping/time for spot & futures
    - exchange_info shortcuts
    - small health check using metrics module
    """

    _instance: Optional["BinancePBSystem"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None) -> None:
        self._http = http_client or BinanceHTTPClient()
        self._metrics = AdvancedMetrics.get_instance()
        logger.debug("BinancePBSystem initialized")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinancePBSystem":
        if cls._instance is None:
            cls._instance = cls(http_client=http_client)
        elif http_client is not None:
            cls._instance._http = http_client
        return cls._instance

    async def ping_spot(self) -> bool:
        """Ping spot public endpoint."""
        logger.debug("System: ping_spot")
        await self._http.get(SPOT_PING_ENDPOINT)
        return True

    async def ping_futures(self) -> bool:
        """Ping futures public endpoint."""
        logger.debug("System: ping_futures")
        await self._http.get(FUTURES_PING_ENDPOINT, futures=True)
        return True

    async def server_time_spot(self) -> int:
        logger.debug("System: server_time_spot")
        data = await self._http.get(SPOT_TIME_ENDPOINT)
        return int(data.get("serverTime", 0))

    async def server_time_futures(self) -> int:
        logger.debug("System: server_time_futures")
        data = await self._http.get(FUTURES_TIME_ENDPOINT, futures=True)
        return int(data.get("serverTime", 0))

    async def exchange_info_spot(self, symbol: Optional[str] = None) -> ExchangeInfo:
        logger.debug("System: exchange_info_spot %s", symbol)
        params = {"symbol": symbol} if symbol else None
        return await self._http.get(SPOT_EXCHANGE_INFO_ENDPOINT, params=params)  # type: ignore[return-value]

    async def exchange_info_futures(self, symbol: Optional[str] = None) -> ExchangeInfo:
        logger.debug("System: exchange_info_futures %s", symbol)
        params = {"symbol": symbol} if symbol else None
        return await self._http.get(FUTURES_EXCHANGE_INFO_ENDPOINT, params=params, futures=True)  # type: ignore[return-value]

    async def health_check(self) -> Dict[str, Any]:
        """
        Combined health check using metrics (AdvancedMetrics).
        Returns dict with status, issues, metrics.
        """
        logger.debug("System: health_check")
        return await self._metrics.get_health_status()
