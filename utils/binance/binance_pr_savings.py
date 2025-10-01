# utils/binance/binance_pr_savings.py
"""
SavingsClient: daily/flexible/locked savings endpoints.
Savings / Lending endpoints (flexible/locked/customizedFixed) (/sapi/v1/lending/*).
Enhanced with detailed HTTP & Binance error handling.
Includes unified abstraction for all product listings.
"""
from typing import Any, Dict, List, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class BinanceHTTPError(BinanceAPIError):
    """HTTP-level errors with status code."""
    def __init__(self, status_code: int, message: str, code: Optional[int] = None):
        super().__init__(f"HTTP {status_code}: {message} (Binance code: {code})")
        self.status_code = status_code
        self.code = code


class SavingsClient(BinancePrivateBase):
    """Savings / Lending operations (Daily, Flexible & Locked / Customized Fixed)."""

    VALID_PRODUCT_TYPES = ["ACTIVITY", "FLEXIBLE", "CUSTOMIZED_FIXED"]

    # -------------------- Daily / Flexible / Locked Unified --------------------
    async def get_all_products(
        self, product_type: str = "ACTIVITY", asset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Unified method to get all lending products.
        product_type: "ACTIVITY" | "FLEXIBLE" | "CUSTOMIZED_FIXED"
        """
        if product_type not in self.VALID_PRODUCT_TYPES:
            raise ValueError(f"Invalid product_type: {product_type}")

        try:
            params: Dict[str, Any] = {"type": product_type} if product_type != "CUSTOMIZED_FIXED" else {}
            if asset:
                params["asset"] = asset.upper()

            if product_type == "ACTIVITY":
                endpoint = "/sapi/v1/lending/daily/product/list"
            elif product_type == "FLEXIBLE":
                endpoint = "/sapi/v1/lending/flexible/product/list"
            else:  # CUSTOMIZED_FIXED
                endpoint = "/sapi/v1/lending/customizedFixed/product/list"

            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", endpoint, params=params, signed=True
            )
            return resp

        except BinanceAPIError as e:
            logger.exception(f"Binance API error getting {product_type} product list: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error getting {product_type} product list")
            status = getattr(e, "status_code", None)
            code = getattr(e, "code", None)
            raise BinanceHTTPError(status or 0, str(e), code)

    # -------------------- Daily / Flexible / Locked Purchase --------------------
    async def purchase_product(
        self, product_id: str, amount: float, product_type: str = "ACTIVITY"
    ) -> Dict[str, Any]:
        """
        Unified method to purchase a product.
        product_type: "ACTIVITY" | "FLEXIBLE" | "CUSTOMIZED_FIXED"
        """
        if product_type not in self.VALID_PRODUCT_TYPES:
            raise ValueError(f"Invalid product_type: {product_type}")
        if amount <= 0:
            raise ValueError("Amount must be positive")

        try:
            params = {"productId": product_id, "amount": amount}
            if product_type == "ACTIVITY":
                endpoint = "/sapi/v1/lending/daily/purchase"
            elif product_type == "FLEXIBLE":
                endpoint = "/sapi/v1/lending/flexible/purchase"
            else:  # CUSTOMIZED_FIXED
                endpoint = "/sapi/v1/lending/customizedFixed/purchase"

            resp = await self.circuit_breaker.execute(
                self.http._request, "POST", endpoint, params=params, signed=True
            )
            return resp

        except BinanceAPIError as e:
            logger.exception(f"Binance API error purchasing {product_type} product: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error purchasing {product_type} product")
            status = getattr(e, "status_code", None)
            code = getattr(e, "code", None)
            raise BinanceHTTPError(status or 0, str(e), code)

    # -------------------- Daily / Flexible Balance --------------------
    async def get_balance(self, asset: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            params: Dict[str, Any] = {"asset": asset.upper()} if asset else {}
            endpoint = "/sapi/v1/lending/daily/token/position"
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", endpoint, params=params, signed=True
            )
            return resp
        except BinanceAPIError as e:
            logger.exception(f"Binance API error getting balance: {e}")
            raise
        except Exception as e:
            logger.exception("Unexpected error getting savings balance")
            status = getattr(e, "status_code", None)
            code = getattr(e, "code", None)
            raise BinanceHTTPError(status or 0, str(e), code)

    # -------------------- Locked / Customized Fixed Positions --------------------
    async def get_locked_positions(
        self, asset: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """GET /sapi/v1/lending/customizedFixed/position/list"""
        try:
            params: Dict[str, Any] = {"asset": asset.upper()} if asset else {}
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET",
                "/sapi/v1/lending/customizedFixed/position/list",
                params=params, signed=True
            )
            return resp
        except BinanceAPIError as e:
            logger.exception(f"Binance API error getting locked positions: {e}")
            raise
        except Exception as e:
            logger.exception("Unexpected error getting locked positions")
            status = getattr(e, "status_code", None)
            code = getattr(e, "code", None)
            raise BinanceHTTPError(status or 0, str(e), code)
