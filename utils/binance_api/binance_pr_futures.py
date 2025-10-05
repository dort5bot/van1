# utils/binance_api/binance_pr_futures.py
"""
FuturesClient: Binance USDT-M Coin-M futures endpoints (fapi).
Implements account info, positions, order placement/cancel, leverage changes, income history.
Full compliance with Binance Futures API standard.
"""
from typing import Any, Dict, List, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class FuturesClient(BinancePrivateBase):
    """Futures (fapi) operations."""

    # -------------------- Account & Balance --------------------
    async def get_account_info(self) -> Dict[str, Any]:
        """GET /fapi/v2/account"""
        try:
            await self._require_keys()
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v2/account", signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures account info")
            raise BinanceAPIError(f"Error getting futures account info: {e}")

    async def get_balance(self) -> List[Dict[str, Any]]:
        """Return futures balances (assets list from account info)."""
        try:
            info = await self.get_account_info()
            return info.get("assets", [])
        except Exception as e:
            logger.exception("Error getting futures balance")
            raise BinanceAPIError(f"Error getting futures balance: {e}")

    async def get_positions(self) -> List[Dict[str, Any]]:
        """GET /fapi/v2/positionRisk"""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v2/positionRisk", signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures positions")
            raise BinanceAPIError(f"Error getting futures positions: {e}")

    # -------------------- Orders --------------------
    async def place_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        reduce_only: Optional[bool] = None,
        time_in_force: Optional[str] = None,
        stop_price: Optional[float] = None,
        close_position: Optional[bool] = None,
        working_type: Optional[str] = None,
        price_protect: Optional[bool] = None,
        new_client_order_id: Optional[str] = None,
        new_order_resp_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /fapi/v1/order"""
        try:
            await self._require_keys()
            params: Dict[str, Any] = {
                "symbol": symbol.upper(),
                "side": side,
                "type": type_,
            }
            if quantity is not None:
                params["quantity"] = quantity
            if price is not None:
                params["price"] = price
            if time_in_force:
                params["timeInForce"] = time_in_force
            if reduce_only is not None:
                params["reduceOnly"] = reduce_only
            if stop_price is not None:
                params["stopPrice"] = stop_price
            if close_position is not None:
                params["closePosition"] = close_position
            if working_type:
                params["workingType"] = working_type
            if price_protect is not None:
                params["priceProtect"] = price_protect
            if new_client_order_id:
                params["newClientOrderId"] = new_client_order_id
            if new_order_resp_type:
                params["newOrderRespType"] = new_order_resp_type

            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/order",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error placing futures order")
            raise BinanceAPIError(f"Error placing futures order for {symbol}: {e}")

    async def test_order(self, **kwargs) -> Dict[str, Any]:
        """POST /fapi/v1/order/test (validate order parameters without placing)"""
        try:
            await self._require_keys()
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/order/test",
                params=kwargs, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error testing futures order")
            raise BinanceAPIError(f"Error testing futures order: {e}")

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """DELETE /fapi/v1/order"""
        try:
            params = {"symbol": symbol.upper()}
            if order_id:
                params["orderId"] = order_id
            if orig_client_order_id:
                params["origClientOrderId"] = orig_client_order_id
            return await self.circuit_breaker.execute(
                self.http._request, "DELETE", "/fapi/v1/order",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error canceling futures order")
            raise BinanceAPIError(f"Error canceling futures order for {symbol}: {e}")

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /fapi/v1/openOrders"""
        try:
            params = {"symbol": symbol.upper()} if symbol else {}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/openOrders",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures open orders")
            raise BinanceAPIError(f"Error getting futures open orders: {e}")

    async def get_order_history(
        self,
        symbol: str,
        limit: int = 50,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        order_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """GET /fapi/v1/allOrders"""
        try:
            params: Dict[str, Any] = {"symbol": symbol.upper(), "limit": limit}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if order_id:
                params["orderId"] = order_id
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/allOrders",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures order history")
            raise BinanceAPIError(f"Error getting futures order history for {symbol}: {e}")

    # -------------------- Income & Trades --------------------
    async def get_income_history(
        self,
        symbol: Optional[str] = None,
        income_type: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """GET /fapi/v1/income"""
        try:
            params: Dict[str, Any] = {"limit": limit}
            if symbol:
                params["symbol"] = symbol.upper()
            if income_type:
                params["incomeType"] = income_type.upper()
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/income",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures income history")
            raise BinanceAPIError(f"Error getting futures income history: {e}")

    async def get_user_trades(
        self, symbol: str, limit: int = 50, from_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """GET /fapi/v1/userTrades"""
        try:
            params = {"symbol": symbol.upper(), "limit": limit}
            if from_id:
                params["fromId"] = from_id
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/userTrades",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures user trades")
            raise BinanceAPIError(f"Error getting futures user trades for {symbol}: {e}")

    # -------------------- Risk & Margin --------------------
    async def change_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """POST /fapi/v1/leverage"""
        try:
            params = {"symbol": symbol.upper(), "leverage": leverage}
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/leverage",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error changing futures leverage")
            raise BinanceAPIError(f"Error changing leverage for {symbol}: {e}")

    async def get_leverage_bracket(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /fapi/v1/leverageBracket"""
        try:
            params = {"symbol": symbol.upper()} if symbol else {}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/leverageBracket",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting leverage bracket")
            raise BinanceAPIError(f"Error getting leverage bracket: {e}")

    async def change_margin_type(self, symbol: str, margin_type: str) -> Dict[str, Any]:
        """POST /fapi/v1/marginType"""
        try:
            params = {"symbol": symbol.upper(), "marginType": margin_type.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/marginType",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error changing futures margin type")
            raise BinanceAPIError(f"Error changing margin type for {symbol}: {e}")

    async def set_position_mode(self, dual_side_position: bool) -> Dict[str, Any]:
        """POST /fapi/v1/positionSide/dual"""
        try:
            params = {"dualSidePosition": str(dual_side_position).lower()}
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/positionSide/dual",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error setting futures position mode")
            raise BinanceAPIError(f"Error setting futures position mode: {e}")

    async def get_position_mode(self) -> Dict[str, Any]:
        """GET /fapi/v1/positionSide/dual"""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/positionSide/dual",
                signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures position mode")
            raise BinanceAPIError(f"Error getting futures position mode: {e}")

    async def get_adl_quantile(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /fapi/v1/adlQuantile"""
        try:
            params = {"symbol": symbol.upper()} if symbol else {}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/adlQuantile",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting ADL quantile")
            raise BinanceAPIError(f"Error getting ADL quantile: {e}")

    async def get_commission_rate(self, symbol: str) -> Dict[str, Any]:
        """GET /fapi/v1/commissionRate"""
        try:
            params = {"symbol": symbol.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/commissionRate",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting commission rate")
            raise BinanceAPIError(f"Error getting commission rate for {symbol}: {e}")


    # -------------------- Multi-Orders  --------------------

    async def place_multiple_orders(self, batch_orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """POST /fapi/v1/batchOrders - Place multiple orders."""
        try:
            await self._require_keys()
            params = {"batchOrders": batch_orders}
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/batchOrders",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error placing multiple futures orders")
            raise BinanceAPIError("Error placing multiple futures orders", e)

    async def cancel_multiple_orders(self, symbol: str, 
                                    order_id_list: Optional[List[int]] = None,
                                    orig_client_order_id_list: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """DELETE /fapi/v1/batchOrders - Cancel multiple orders."""
        try:
            params = {"symbol": symbol.upper()}
            if order_id_list:
                params["orderIdList"] = order_id_list
            if orig_client_order_id_list:
                params["origClientOrderIdList"] = orig_client_order_id_list
                
            return await self.circuit_breaker.execute(
                self.http._request, "DELETE", "/fapi/v1/batchOrders",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error canceling multiple futures orders")
            raise BinanceAPIError("Error canceling multiple futures orders", e)

    # -------------------- Account  --------------------

    async def get_account_commission(self, symbol: str) -> Dict[str, Any]:
        """GET /fapi/v1/commissionRate - Get account commission rate."""
        try:
            params = {"symbol": symbol.upper()}
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/commissionRate",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting account commission")
            raise BinanceAPIError("Error getting account commission", e)

    async def get_futures_account_transaction_history(self, asset: str, 
                                                     start_time: Optional[int] = None,
                                                     end_time: Optional[int] = None,
                                                     current: Optional[int] = None,
                                                     size: Optional[int] = None) -> Dict[str, Any]:
        """GET /fapi/v1/account - Get futures account transaction history."""
        try:
            params = {"asset": asset.upper()}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            if current:
                params["current"] = current
            if size:
                params["size"] = size
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/account",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures account transaction history")
            raise BinanceAPIError("Error getting futures account transaction history", e)
            
            
            # utils/binance/binance_pr_futures.py - FuturesClient'a eklenen yeni endpoint'ler

    async def get_force_orders(
        self,
        symbol: Optional[str] = None,
        auto_close_type: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """GET /fapi/v1/forceOrders - Get user's force orders."""
        try:
            params = {"limit": limit}
            if symbol:
                params["symbol"] = symbol.upper()
            if auto_close_type:
                params["autoCloseType"] = auto_close_type
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
                
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/forceOrders",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting force orders")
            raise BinanceAPIError("Error getting force orders", e)

    async def get_multi_assets_margin(
        self
    ) -> Dict[str, Any]:
        """GET /fapi/v1/multiAssetsMargin - Get multi-assets margin mode."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/multiAssetsMargin",
                signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting multi-assets margin")
            raise BinanceAPIError("Error getting multi-assets margin", e)

    async def set_multi_assets_margin(
        self, 
        multi_assets_margin: bool
    ) -> Dict[str, Any]:
        """POST /fapi/v1/multiAssetsMargin - Set multi-assets margin mode."""
        try:
            params = {"multiAssetsMargin": str(multi_assets_margin).upper()}
            
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/fapi/v1/multiAssetsMargin",
                params=params, signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error setting multi-assets margin")
            raise BinanceAPIError("Error setting multi-assets margin", e)

    async def get_api_trading_status(self) -> Dict[str, Any]:
        """GET /fapi/v1/apiTradingStatus - Get API trading status."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/apiTradingStatus",
                signed=True, futures=True
            )
        except Exception as e:
            logger.exception("Error getting API trading status")
            raise BinanceAPIError("Error getting API trading status", e)
            
            