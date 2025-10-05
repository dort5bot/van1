# utils/binance_api/binance_pr_spot.py
"""
SpotClient: Spot account, order, market data, and OCO endpoints (signed).
Endpoints mirror Binance API v3 (/api/v3/*).
"""
from typing import Any, Dict, List, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class SpotClient(BinancePrivateBase):
    """Spot account & order operations."""

    # ------------------------- ACCOUNT -------------------------
    async def get_account_info(self) -> Dict[str, Any]:
        """GET /api/v3/account"""
        try:
            await self._require_keys()
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/account", signed=True
            )
        except Exception as e:
            logger.exception("Error getting spot account info")
            raise BinanceAPIError(f"Error getting spot account info: {e}")

    async def get_account_balance(self, asset: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return full account info or specific asset balance."""
        try:
            info = await self.get_account_info()
            if asset:
                asset = asset.upper()
                for balance in info.get("balances", []):
                    if balance.get("asset") == asset:
                        return balance
                return None
            return info
        except Exception as e:
            logger.exception("Error getting spot account balance")
            raise BinanceAPIError(f"Error getting spot account balance: {e}")

    # ------------------------- ORDERS -------------------------
    async def place_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: Optional[str] = None,
        stop_price: Optional[float] = None,
        new_client_order_id: Optional[str] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """POST /api/v3/order"""
        try:
            await self._require_keys()
            symbol = symbol.upper()
            side = side.upper()
            type_ = type_.upper()

            params: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "type": type_,
                "quantity": quantity,
            }
            if price is not None:
                params["price"] = price
            if time_in_force:
                params["timeInForce"] = time_in_force
            if stop_price is not None:
                params["stopPrice"] = stop_price
            if new_client_order_id:
                params["newClientOrderId"] = new_client_order_id
            if recv_window:
                params["recvWindow"] = recv_window

            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/api/v3/order", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error placing spot order for {symbol}")
            raise BinanceAPIError(f"Error placing spot order for {symbol}: {e}")

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """DELETE /api/v3/order"""
        try:
            await self._require_keys()
            params = {"symbol": symbol.upper()}
            if order_id:
                params["orderId"] = order_id
            if orig_client_order_id:
                params["origClientOrderId"] = orig_client_order_id
            if recv_window:
                params["recvWindow"] = recv_window

            return await self.circuit_breaker.execute(
                self.http._request, "DELETE", "/api/v3/order", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error canceling spot order for {symbol}")
            raise BinanceAPIError(f"Error canceling spot order for {symbol}: {e}")

    async def get_open_orders(
        self, symbol: Optional[str] = None, recv_window: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """GET /api/v3/openOrders"""
        try:
            params = {"symbol": symbol.upper()} if symbol else {}
            if recv_window:
                params["recvWindow"] = recv_window
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/openOrders", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting open spot orders")
            raise BinanceAPIError(f"Error getting open spot orders: {e}")
    
    async def get_order_history(
        self, symbol: str, limit: int = 50, recv_window: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """GET /api/v3/allOrders"""
        try:
            params = {"symbol": symbol.upper(), "limit": limit}
            if recv_window:
                params["recvWindow"] = recv_window
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/allOrders", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error getting spot order history for {symbol}")
            raise BinanceAPIError(f"Error getting spot order history for {symbol}: {e}")

    async def get_my_trades(
        self, symbol: str, limit: int = 50, recv_window: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """GET /api/v3/myTrades"""
        try:
            params = {"symbol": symbol.upper(), "limit": limit}
            if recv_window:
                params["recvWindow"] = recv_window
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/myTrades", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error getting trades for {symbol}")
            raise BinanceAPIError(f"Error getting trades for {symbol}: {e}")





    # ------------------------- OCO ORDERS -------------------------
    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
        stop_limit_price: Optional[float] = None,
        list_client_order_id: Optional[str] = None,
        limit_client_order_id: Optional[str] = None,
        stop_client_order_id: Optional[str] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """POST /api/v3/order/oco"""
        try:
            await self._require_keys()
            params = {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "quantity": quantity,
                "price": price,
                "stopPrice": stop_price,
            }
            if stop_limit_price:
                params["stopLimitPrice"] = stop_limit_price
            if list_client_order_id:
                params["listClientOrderId"] = list_client_order_id
            if limit_client_order_id:
                params["limitClientOrderId"] = limit_client_order_id
            if stop_client_order_id:
                params["stopClientOrderId"] = stop_client_order_id
            if recv_window:
                params["recvWindow"] = recv_window

            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/api/v3/order/oco", params=params, signed=True
            )
        except Exception as e:
            logger.exception(f"Error placing OCO order for {symbol}")
            raise BinanceAPIError(f"Error placing OCO order for {symbol}: {e}")

    # ------------------------- MARKET DATA -------------------------
    async def get_exchange_info(self) -> Dict[str, Any]:
        """GET /api/v3/exchangeInfo"""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/exchangeInfo"
            )
        except Exception as e:
            logger.exception("Error getting exchange info")
            raise BinanceAPIError(f"Error getting exchange info: {e}")

    async def get_symbol_price(self, symbol: str) -> Dict[str, Any]:
        """GET /api/v3/ticker/price"""
        try:
            params = {"symbol": symbol.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/ticker/price", params=params
            )
        except Exception as e:
            logger.exception(f"Error getting price for {symbol}")
            raise BinanceAPIError(f"Error getting price for {symbol}: {e}")

    async def get_book_ticker(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """GET /api/v3/ticker/bookTicker"""
        try:
            params = {"symbol": symbol.upper()} if symbol else {}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/ticker/bookTicker", params=params
            )
        except Exception as e:
            logger.exception(f"Error getting book ticker for {symbol}")
            raise BinanceAPIError(f"Error getting book ticker for {symbol}: {e}")

    # ------------------------- OCO ORDERS -------------------------

    async def get_oco_order(self, order_list_id: Optional[int] = None,
                           orig_client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """GET /api/v3/orderList - Get OCO order."""
        try:
            params = {}
            if order_list_id:
                params["orderListId"] = order_list_id
            if orig_client_order_id:
                params["origClientOrderId"] = orig_client_order_id
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/orderList", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting OCO order")
            raise BinanceAPIError("Error getting OCO order", e)

    async def get_all_oco_orders(self, from_id: Optional[int] = None,
                                start_time: Optional[int] = None,
                                end_time: Optional[int] = None,
                                limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /api/v3/allOrderList - Get all OCO orders."""
        try:
            params = {}
            if from_id:
                params["fromId"] = from_id
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if limit:
                params["limit"] = limit
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/allOrderList", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting all OCO orders")
            raise BinanceAPIError("Error getting all OCO orders", e)

    async def get_open_oco_orders(self) -> List[Dict[str, Any]]:
        """GET /api/v3/openOrderList - Get open OCO orders."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/openOrderList", signed=True
            )
        except Exception as e:
            logger.exception("Error getting open OCO orders")
            raise BinanceAPIError("Error getting open OCO orders", e)

    # ------------------------- ACCOUNT  -------------------------

    async def get_account_api_trading_status(self) -> Dict[str, Any]:
        """GET /api/v3/account/apiTradingStatus - Get API trading status."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/account/apiTradingStatus", signed=True
            )
        except Exception as e:
            logger.exception("Error getting API trading status")
            raise BinanceAPIError("Error getting API trading status", e)

    async def get_account_api_permissions(self) -> Dict[str, Any]:
        """GET /sapi/v1/account/apiRestrictions - Get API key permissions."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/account/apiRestrictions", signed=True
            )
        except Exception as e:
            logger.exception("Error getting API permissions")
            raise BinanceAPIError("Error getting API permissions", e)
    
    # utils/binance/binance_pr_spot.py - SpotClient'a eklenen yeni endpoint'ler

    async def get_order_rate_limits(self) -> List[Dict[str, Any]]:
        """GET /api/v3/rateLimit/order - Get current order count for all symbols."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/rateLimit/order", signed=True
            )
        except Exception as e:
            logger.exception("Error getting order rate limits")
            raise BinanceAPIError("Error getting order rate limits", e)

    async def get_dust_log(
        self, 
        start_time: Optional[int] = None, 
        end_time: Optional[int] = None
    ) -> Dict[str, Any]:
        """GET /sapi/v1/asset/dribblet - Get dust conversion history."""
        try:
            params = {}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/asset/dribblet", 
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting dust log")
            raise BinanceAPIError("Error getting dust log", e)

    async def get_account_snapshot(
        self,
        type_: str = "SPOT",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """GET /sapi/v1/accountSnapshot - Get account snapshot."""
        try:
            params = {
                "type": type_.upper(),
                "limit": limit
            }
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/accountSnapshot", 
                params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting account snapshot")
            raise BinanceAPIError("Error getting account snapshot", e)
            
    #
            
            