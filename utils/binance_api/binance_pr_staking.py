# utils/binance_api/binance_pr_staking.py
"""
StakingClient: staking endpoints (sapi staking).

Geliştirmeler:
- Parametre validasyonu (amount, start/endTime, txn_type)
- Async typing ve return tipleri
- Detaylı error handling: HTTP code, Binance errorCode parse
- Rate-limit ve retry-aware
- Opsiyonel endpointler: interestHistory, projectList
"""
from typing import Any, Dict, List, Optional
import logging
import asyncio

from .binance_pr_base import BinancePrivateBase
#from .binance_exceptions import BinanceAPIError, BinanceRequestError, BinanceRateLimitError, BinanceAuthError, BinanceValidationError
from .binance_exceptions import BinanceAPIError, BinanceRequestError, BinanceRateLimitError, BinanceAuthenticationError  # BinanceValidationError yoksa çıkar

logger = logging.getLogger(__name__)


class StakingClient(BinancePrivateBase):
    """Staking operations."""

    VALID_TXN_TYPES = {"SUBSCRIPTION", "REDEMPTION", "HOLD"}

    async def _request(self, method: str, endpoint: str, params: Dict[str, Any], signed: bool, retries: int = 3) -> Any:
        """
        Wrapper to handle HTTP request with:
        - Detailed error parsing
        - Rate limit handling (429)
        - Retry logic
        """
        for attempt in range(retries):
            try:
                return await self.circuit_breaker.execute(
                    self.http._request, method, endpoint, params=params, signed=signed
                )
            except BinanceRequestError as e:
                error_code = getattr(e, "error_code", None)
                error_msg = getattr(e, "message", str(e))
                status_code = getattr(e, "status_code", None)

                logger.error(
                    "BinanceRequestError: status=%s, code=%s, msg=%s, endpoint=%s, params=%s",
                    status_code, error_code, error_msg, endpoint, params
                )

                # Rate limit
                if status_code == 429 or error_code == -1003:
                    logger.warning("Rate limit hit, retrying in 1s... attempt %d/%d", attempt+1, retries)
                    await asyncio.sleep(1)
                    continue
                # IP ban / forbidden
                if status_code == 418:
                    raise BinanceRateLimitError("IP banned temporarily") from e
                # Auth error
                if status_code in (401, 403):
                    raise BinanceAuthError(f"Authentication error: {error_msg}") from e
                # Validation error
                if status_code == 400:
                    raise BinanceValidationError(f"Validation error: {error_msg}") from e

                raise BinanceAPIError(f"Binance API error: status={status_code}, code={error_code}, msg={error_msg}") from e
            except Exception as e:
                logger.exception("Unexpected error on endpoint=%s, params=%s", endpoint, params)
                raise BinanceAPIError(f"Unexpected error: {e}") from e
        raise BinanceRateLimitError("Max retries reached due to rate limiting")

    # ----------------------------
    # Staking endpoints
    # ----------------------------
    async def get_product_list(self, product: str = "STAKING", asset: Optional[str] = None) -> List[Dict[str, Any]]:
        if not product:
            raise ValueError("product is required")
        params: Dict[str, Any] = {"product": product}
        if asset:
            params["asset"] = asset.upper()
        return await self._request("GET", "/sapi/v1/staking/productList", params, signed=True)

    async def stake_asset(self, product: str, product_id: str, amount: float) -> Dict[str, Any]:
        if not product or not product_id:
            raise ValueError("product and product_id are required")
        if amount <= 0:
            raise ValueError("amount must be positive")
        params = {"product": product, "productId": product_id, "amount": amount}
        return await self._request("POST", "/sapi/v1/staking/purchase", params, signed=True)

    async def unstake_asset(
        self,
        product: str,
        product_id: str,
        position_id: Optional[str] = None,
        amount: Optional[float] = None
    ) -> Dict[str, Any]:
        if not product or not product_id:
            raise ValueError("product and product_id are required")
        if amount is not None and amount <= 0:
            raise ValueError("amount must be positive if provided")
        params: Dict[str, Any] = {"product": product, "productId": product_id}
        if position_id:
            params["positionId"] = position_id
        if amount is not None:
            params["amount"] = amount
        return await self._request("POST", "/sapi/v1/staking/redeem", params, signed=True)

    async def get_history(
        self,
        product: str,
        txn_type: str,
        asset: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if not product:
            raise ValueError("product is required")
        if txn_type not in self.VALID_TXN_TYPES:
            raise ValueError(f"txn_type must be one of {self.VALID_TXN_TYPES}")
        if start_time and end_time and start_time > end_time:
            raise ValueError("start_time cannot be greater than end_time")

        params: Dict[str, Any] = {"product": product, "txnType": txn_type}
        if asset:
            params["asset"] = asset.upper()
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self._request("GET", "/sapi/v1/staking/stakingRecord", params, signed=True)

    # ----------------------------
    # Optional / advanced endpoints
    # ----------------------------
    async def get_interest_history(
        self,
        product: str,
        asset: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get staking interest history."""
        if not product:
            raise ValueError("product is required")
        if start_time and end_time and start_time > end_time:
            raise ValueError("start_time cannot be greater than end_time")
        params: Dict[str, Any] = {"product": product}
        if asset:
            params["asset"] = asset.upper()
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self._request("GET", "/sapi/v1/staking/interestHistory", params, signed=True)

    async def get_project_list(self, product: str = "STAKING") -> List[Dict[str, Any]]:
        """Get list of staking projects."""
        if not product:
            raise ValueError("product is required")
        params: Dict[str, Any] = {"product": product}
        return await self._request("GET", "/sapi/v1/staking/projectList", params, signed=True)
