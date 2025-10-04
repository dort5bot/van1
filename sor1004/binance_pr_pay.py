# utils/binance/binance_pr_pay.py
"""
PayClient: Binance Pay endpoints (sapi/v1/pay/*).
Covers payment transactions, merchant queries, and payment history.
"""
from typing import Any, Dict, List, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class PayClient(BinancePrivateBase):
    """Binance Pay operations."""

    async def get_pay_transactions(self, 
                                  start_time: Optional[int] = None,
                                  end_time: Optional[int] = None,
                                  limit: Optional[int] = None,
                                  offset: Optional[int] = None) -> Dict[str, Any]:
        """GET /sapi/v1/pay/transactions - Get Pay transaction history."""
        try:
            params = {}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if limit:
                params["limit"] = limit
            if offset:
                params["offset"] = offset
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/pay/transactions",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting Pay transactions")
            raise BinanceAPIError("Error getting Pay transactions", e)

    async def get_merchant_status(self) -> Dict[str, Any]:
        """GET /sapi/v1/pay/merchant - Get merchant status."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/pay/merchant", signed=True
            )
        except Exception as e:
            logger.exception("Error getting merchant status")
            raise BinanceAPIError("Error getting merchant status", e)