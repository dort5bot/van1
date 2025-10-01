"""
utils/binance/binance_pb_index.py
--------------------------------
Index / Mark Price related public endpoints.

- Mark price / index / premium endpoints (futures) ve ilgili public index verilerini getirir.
- Async / singleton / logging
- Not: bazı index endpoints Binance docs'a göre futures domain altında (/fapi/v1/...).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .binance_request import BinanceHTTPClient

logger = logging.getLogger(__name__)

# Common futures index endpoints (public)
FAPI_MARK_PRICE_ENDPOINT = "/fapi/v1/premiumIndex"  # premiumIndex contains mark/premium data
FAPI_INDEX_PRICE_ENDPOINT = "/api/v3/indexPrice"  # if needed in other setups; keep optional
FAPI_FUNDING_RATE_ENDPOINT = "/fapi/v1/fundingRate"

class BinancePBIndex:
    """
    Wrapper for index and mark-price related public endpoints.
    """

    _instance: Optional["BinancePBIndex"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None) -> None:
        self._http = http_client or BinanceHTTPClient()
        logger.debug("BinancePBIndex initialized")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinancePBIndex":
        if cls._instance is None:
            cls._instance = cls(http_client=http_client)
        elif http_client is not None:
            cls._instance._http = http_client
        return cls._instance

    async def mark_price(self, symbol: Optional[str] = None) -> Any:
        """
        Get current mark/premium index.
        If symbol is provided returns single object, otherwise list for all symbols.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Index: mark_price %s", symbol)
        data = await self._http.get(FAPI_MARK_PRICE_ENDPOINT, params=params, futures=True)
        return data

    async def funding_rate_history(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Funding rate history for a symbol (futures).
        """
        params: Dict[str, Any] = {"limit": int(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Index: funding_rate_history %s params=%s", symbol, params)
        data = await self._http.get(FAPI_FUNDING_RATE_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]
