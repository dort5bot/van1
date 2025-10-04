# utils/binance/binance_pr_convert.py
"""
ConvertClient: Binance Convert endpoints (sapi/v1/convert/*).
Covers convert operations, trade history, and exchange limits.
"""
from typing import Any, Dict, List, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class ConvertClient(BinancePrivateBase):
    """Binance Convert operations."""

    async def get_convert_trade_history(self,
                                      start_time: Optional[int] = None,
                                      end_time: Optional[int] = None,
                                      limit: Optional[int] = None) -> Dict[str, Any]:
        """GET /sapi/v1/convert/tradeFlow - Get convert trade history."""
        try:
            params = {}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if limit:
                params["limit"] = limit
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/convert/tradeFlow",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting convert trade history")
            raise BinanceAPIError("Error getting convert trade history", e)

    async def get_convert_exchange_info(self, from_asset: Optional[str] = None,
                                      to_asset: Optional[str] = None) -> Dict[str, Any]:
        """GET /sapi/v1/convert/exchangeInfo - Get convert exchange info."""
        try:
            params = {}
            if from_asset:
                params["fromAsset"] = from_asset.upper()
            if to_asset:
                params["toAsset"] = to_asset.upper()
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/convert/exchangeInfo",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting convert exchange info")
            raise BinanceAPIError("Error getting convert exchange info", e)
    
    # utils/binance/binance_pr_convert.py - ConvertClient'a eklenen endpoint'ler

    async def create_convert_order(
        self,
        from_asset: str,
        to_asset: str,
        from_amount: Optional[float] = None,
        to_amount: Optional[float] = None,
        wallet_type: str = "SPOT",
        valid_time: str = "10s"
    ) -> Dict[str, Any]:
        """POST /sapi/v1/convert/acceptQuote - Create convert order."""
        try:
            if not from_asset or not to_asset:
                raise ValueError("from_asset and to_asset are required")
            if not from_amount and not to_amount:
                raise ValueError("Either from_amount or to_amount is required")
                
            params = {
                "fromAsset": from_asset.upper(),
                "toAsset": to_asset.upper(),
                "walletType": wallet_type.upper(),
                "validTime": valid_time
            }
            
            if from_amount:
                params["fromAmount"] = from_amount
            if to_amount:
                params["toAmount"] = to_amount
                
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/convert/acceptQuote",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error creating convert order")
            raise BinanceAPIError("Error creating convert order", e)

    async def get_convert_order_status(self, order_id: str) -> Dict[str, Any]:
        """GET /sapi/v1/convert/orderStatus - Get convert order status."""
        try:
            params = {"orderId": order_id}
            
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/convert/orderStatus",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting convert order status")
            raise BinanceAPIError("Error getting convert order status", e)

    async def get_convert_asset_quantity(
        self, 
        from_asset: str, 
        to_asset: str
    ) -> Dict[str, Any]:
        """GET /sapi/v1/convert/assetQuantity - Get convert asset quantity."""
        try:
            params = {
                "fromAsset": from_asset.upper(),
                "toAsset": to_asset.upper()
            }
            
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/convert/assetQuantity",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting convert asset quantity")
            raise BinanceAPIError("Error getting convert asset quantity", e)
            