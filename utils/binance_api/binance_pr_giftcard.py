# utils/binance_api/binance_pr_giftcard.py
"""
GiftCardClient: Binance Gift Card endpoints (sapi/v1/giftcard/*).
Covers gift card creation, redemption, and verification.
"""
from typing import Any, Dict, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)

class GiftCardClient(BinancePrivateBase):
    """Binance Gift Card operations."""

    async def create_gift_card(
        self,
        token: str,
        amount: float
    ) -> Dict[str, Any]:
        """POST /sapi/v1/giftcard/create - Create a Binance Gift Card."""
        try:
            params = {
                "token": token.upper(),
                "amount": amount
            }
            
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/giftcard/create",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error creating gift card")
            raise BinanceAPIError("Error creating gift card", e)

    async def redeem_gift_card(
        self,
        code: str,
        external_uid: Optional[str] = None
    ) -> Dict[str, Any]:
        """POST /sapi/v1/giftcard/redeem - Redeem a Binance Gift Card."""
        try:
            params = {"code": code}
            if external_uid:
                params["externalUid"] = external_uid
                
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/giftcard/redeem",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error redeeming gift card")
            raise BinanceAPIError("Error redeeming gift card", e)

    async def verify_gift_card(
        self,
        reference_no: str
    ) -> Dict[str, Any]:
        """GET /sapi/v1/giftcard/verify - Verify Binance Gift Card."""
        try:
            params = {"referenceNo": reference_no}
            
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/giftcard/verify",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error verifying gift card")
            raise BinanceAPIError("Error verifying gift card", e)