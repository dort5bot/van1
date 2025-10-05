# utils/binance_api/binance_pr_margin.py
"""
MarginClient: Margin account & order endpoints (sapi margin).
Endpoints covered:
- /sapi/v1/margin/account
- /sapi/v1/margin/order
- /sapi/v1/margin/openOrders
- /sapi/v1/margin/allOrders
- /sapi/v1/margin/myTrades
- /sapi/v1/margin/loan
- /sapi/v1/margin/repay
- /sapi/v1/margin/interestHistory
- /sapi/v1/margin/maxBorrowable
- /sapi/v1/margin/maxTransferable
- /sapi/v1/margin/isolated/pairs
"""
from typing import Any, Dict, List, Optional, Union
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)

class MarginClient(BinancePrivateBase):
    """Margin trading operations."""

    # ----------------------
    # Account
    # ----------------------
    async def get_account_info(self) -> Dict[str, Any]:
        """GET /sapi/v1/margin/account
        Returns margin account details.
        """
        try:
            await self._require_keys()
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/account", signed=True
            )
        except Exception as e:
            logger.exception("Error getting margin account info")
            raise BinanceAPIError(f"Error getting margin account info: {e}")

    # ----------------------
    # Orders
    # ----------------------
    async def create_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        quantity: float,
        price: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """POST /sapi/v1/margin/order
        Create a margin order.

        Args:
            symbol: Trading pair e.g. 'BTCUSDT'
            side: 'BUY' or 'SELL'
            type_: 'LIMIT', 'MARKET', etc.
            quantity: Order quantity
            price: Order price (for LIMIT orders)
            **kwargs: Additional Binance params (e.g., timeInForce)
        """
        side = side.upper()
        type_ = type_.upper()
        if side not in ["BUY", "SELL"]:
            raise ValueError("Invalid side, must be 'BUY' or 'SELL'")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if type_ == "LIMIT" and (price is None or price <= 0):
            raise ValueError("LIMIT orders require a positive price")

        params: Dict[str, Any] = {"symbol": symbol.upper(), "side": side, "type": type_, "quantity": quantity}
        if price is not None:
            params["price"] = price
        params.update(kwargs)

        try:
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/margin/order", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error creating margin order for {symbol}")
            raise BinanceAPIError(f"Error creating margin order for {symbol}: {e}")

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /sapi/v1/margin/openOrders
        Returns all open margin orders.
        """
        params = {"symbol": symbol.upper()} if symbol else {}
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/openOrders", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting margin open orders")
            raise BinanceAPIError(f"Error getting margin open orders: {e}")

    async def get_all_orders(self, symbol: str, **kwargs) -> List[Dict[str, Any]]:
        """GET /sapi/v1/margin/allOrders
        Returns all margin orders for a symbol.

        Args:
            symbol: Trading pair
            **kwargs: Optional Binance parameters (orderId, limit, etc.)
        """
        params: Dict[str, Any] = {"symbol": symbol.upper()}
        params.update(kwargs)
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/allOrders", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error getting all margin orders for {symbol}")
            raise BinanceAPIError(f"Error getting all margin orders for {symbol}: {e}")

    async def get_my_trades(self, symbol: str, **kwargs) -> List[Dict[str, Any]]:
        """GET /sapi/v1/margin/myTrades
        Get margin trade history for a symbol.
        """
        params: Dict[str, Any] = {"symbol": symbol.upper()}
        params.update(kwargs)
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/myTrades", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error getting margin trades for {symbol}")
            raise BinanceAPIError(f"Error getting margin trades for {symbol}: {e}")

    # ----------------------
    # Margin Loans
    # ----------------------
    async def borrow(self, asset: str, amount: float) -> Dict[str, Any]:
        """POST /sapi/v1/margin/loan
        Borrow margin asset.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        params = {"asset": asset.upper(), "amount": amount}
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/margin/loan", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error borrowing {asset}")
            raise BinanceAPIError(f"Error borrowing {asset}: {e}")

    async def repay(self, asset: str, amount: float) -> Dict[str, Any]:
        """POST /sapi/v1/margin/repay
        Repay borrowed margin asset.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        params = {"asset": asset.upper(), "amount": amount}
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/margin/repay", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error repaying {asset}")
            raise BinanceAPIError(f"Error repaying {asset}: {e}")

    # ----------------------
    # Interest History
    # ----------------------
    async def get_interest_history(self, **kwargs) -> List[Dict[str, Any]]:
        """GET /sapi/v1/margin/interestHistory
        Returns interest history.
        """
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/interestHistory", params=kwargs, signed=True
            )
        except Exception as e:
            logger.exception("Error getting margin interest history")
            raise BinanceAPIError(f"Error getting margin interest history: {e}")

    # ----------------------
    # Max Borrow/Transferable
    # ----------------------
    async def get_max_borrowable(self, asset: str) -> Dict[str, Any]:
        """GET /sapi/v1/margin/maxBorrowable
        Returns maximum borrowable amount for an asset.
        """
        params = {"asset": asset.upper()}
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/maxBorrowable", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error getting max borrowable for {asset}")
            raise BinanceAPIError(f"Error getting max borrowable for {asset}: {e}")

    async def get_max_transferable(self, asset: str) -> Dict[str, Any]:
        """GET /sapi/v1/margin/maxTransferable
        Returns maximum transferable amount for an asset.
        """
        params = {"asset": asset.upper()}
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/maxTransferable", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error getting max transferable for {asset}")
            raise BinanceAPIError(f"Error getting max transferable for {asset}: {e}")

    # ----------------------
    # Isolated Margin Pairs
    # ----------------------
    async def get_isolated_pairs(self) -> List[Dict[str, Any]]:
        """GET /sapi/v1/margin/isolated/pairs
        Returns isolated margin trading pairs.
        """
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/isolated/pairs", signed=True
            )
        except Exception as e:
            logger.exception("Error getting isolated margin pairs")
            raise BinanceAPIError(f"Error getting isolated margin pairs: {e}")

    # ---------------------- Isolated Margin  ----------------------

    async def get_isolated_account_info(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """GET /sapi/v1/margin/isolated/account - Get isolated margin account info."""
        try:
            params = {}
            if symbols:
                params["symbols"] = ",".join([s.upper() for s in symbols])
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/isolated/account",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting isolated margin account info")
            raise BinanceAPIError("Error getting isolated margin account info", e)

    async def create_isolated_margin_account(self, symbol: str) -> Dict[str, Any]:
        """POST /sapi/v1/margin/isolated/create - Create isolated margin account."""
        try:
            params = {"symbol": symbol.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/margin/isolated/create",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error creating isolated margin account")
            raise BinanceAPIError("Error creating isolated margin account", e)

    # ---------------------- Cross Margin ----------------------

    async def get_cross_margin_pair(self, symbol: str) -> Dict[str, Any]:
        """GET /sapi/v1/margin/crossMarginPair - Get cross margin pair info."""
        try:
            params = {"symbol": symbol.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/crossMarginPair",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting cross margin pair info")
            raise BinanceAPIError("Error getting cross margin pair info", e)

    async def get_margin_asset(self, asset: str) -> Dict[str, Any]:
        """GET /sapi/v1/margin/asset - Get margin asset info."""
        try:
            params = {"asset": asset.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/margin/asset",
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting margin asset info")
            raise BinanceAPIError("Error getting margin asset info", e)
            