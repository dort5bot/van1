# utils/binance_api/binance_pr_crypto_loans.py
"""
CryptoLoansClient: Binance Crypto Loans endpoints (sapi/v1/loan/*).
Covers loan operations, collateral assets, and loan history.
"""
from typing import Any, Dict, List, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class CryptoLoansClient(BinancePrivateBase):
    """Binance Crypto Loans operations."""

    async def get_loan_income(self,
                            asset: Optional[str] = None,
                            type_: Optional[str] = None,
                            start_time: Optional[int] = None,
                            end_time: Optional[int] = None,
                            limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /sapi/v1/loan/income - Get crypto loans income history."""
        try:
            params = {}
            if asset:
                params["asset"] = asset.upper()
            if type_:
                params["type"] = type_
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if limit:
                params["limit"] = limit
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/loan/income",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting crypto loans income")
            raise BinanceAPIError("Error getting crypto loans income", e)

    async def get_loanable_assets(self) -> List[Dict[str, Any]]:
        """GET /sapi/v1/loan/loanable/data - Get loanable assets data."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/loan/loanable/data", signed=True
            )
        except Exception as e:
            logger.exception("Error getting loanable assets")
            raise BinanceAPIError("Error getting loanable assets", e)

    async def get_collateral_assets(self) -> List[Dict[str, Any]]:
        """GET /sapi/v1/loan/collateral/data - Get collateral assets data."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/loan/collateral/data", signed=True
            )
        except Exception as e:
            logger.exception("Error getting collateral assets")
            raise BinanceAPIError("Error getting collateral assets", e)