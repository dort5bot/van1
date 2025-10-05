# utils/binance_api/binance_client.py
#v104

import aiohttp
import asyncio
import time
import hmac
import hashlib
from typing import Any, Dict, Optional, List, Union, Callable
import pandas as pd
from datetime import datetime
import logging

from .binance_constants import KLINE_FIELDS
from .binance_exceptions import (
    BinanceError,
    BinanceAPIError,
    BinanceAuthenticationError,
    BinanceInvalidParameterError
)

#buna GEREKSİZ > from utils.apikey_manager import APIKeyManager

    
# Ayarlar
BASE_URL = "https://api.binance.com"
SAPI_URL = "https://api.binance.com/sapi/v1"
FUTURES_URL = "https://fapi.binance.com"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Validation Helpers ----------
def validate_symbol(symbol: str) -> bool:
    """Validate symbol format"""
    if not symbol or not isinstance(symbol, str):
        return False
    # Basic symbol validation (e.g., BTCUSDT, ETHUSDT)
    return len(symbol) >= 5 and symbol.isalnum()


# ---------- API Key Manager Integration ----------
class BinanceClientManager:
    """Multi-user BinanceClient yöneticisi"""
    
    def __init__(self):
        self._user_clients: Dict[int, BinanceClient] = {}
        self._apikey_manager = None
        
    async def get_client_for_user(self, user_id: int) -> Optional['BinanceClient']:
        """Kullanıcı için BinanceClient instance'ı döndürür"""
        if user_id in self._user_clients:
            return self._user_clients[user_id]
            
        # API Key Manager'dan credential'ları al
        try:
            from utils.apikey_manager import APIKeyManager
            if self._apikey_manager is None:
                self._apikey_manager = APIKeyManager.get_instance()
                await self._apikey_manager.init_db()
                
            credentials = await self._apikey_manager.get_apikey(user_id)
            if credentials:
                api_key, secret_key = credentials
                client = BinanceClient(api_key=api_key, api_secret=secret_key)
                self._user_clients[user_id] = client
                return client
                
        except ImportError as e:
            logger.warning(f"APIKeyManager not available: {e}")
        except Exception as e:
            logger.error(f"Error getting client for user {user_id}: {e}")
            
        return None
    
    async def validate_user_credentials(self, user_id: int) -> bool:
        """Kullanıcının API key'lerini doğrular"""
        try:
            from utils.apikey_manager import APIKeyManager
            if self._apikey_manager is None:
                self._apikey_manager = APIKeyManager.get_instance()
                
            return await self._apikey_manager.validate_binance_credentials(user_id)
        except Exception as e:
            logger.error(f"Validation error for user {user_id}: {e}")
            return False
    
    def remove_user_client(self, user_id: int):
        """Kullanıcının client'ını temizler"""
        if user_id in self._user_clients:
            del self._user_clients[user_id]
    
    async def cleanup_all(self):
        """Tüm client'ları temizle"""
        for client in self._user_clients.values():
            await client.close()
        self._user_clients.clear()

# Global manager instance
binance_client_manager = BinanceClientManager()



class BinanceClient:
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        api_secret: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = session or aiohttp.ClientSession()
        self._owns_session = session is None


    # Context Manager Improvement
    async def __aenter__(self):
        await self.session.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()



    async def close(self):
        if self._owns_session:
            await self.session.close()

    # ---------- Utility Methods ----------
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        return headers

    def _check_keys(self) -> None:
        if not self.api_key or not self.api_secret:
            raise BinanceAuthenticationError("API key and secret required")

    def _sign(self, params: Dict[str, Any]) -> str:
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()


    async def _request(
        self, 
        method: str, 
        path: str, 
        params: Optional[Dict[str, Any]] = None, 
        signed: bool = False, 
        base_url: str = BASE_URL,
        user_id: Optional[int] = None  # Yeni parametre
    ) -> Any:
        if params is None:
            params = {}
        if signed:
            self._check_keys()
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._sign(params)

        url = f"{base_url}{path}"
        headers = self._get_headers()
        
        # Rate limit monitoring with user context
        user_context = f"user_{user_id}" if user_id else "public"

        try:
            async with self.session.request(method, url, params=params, headers=headers) as resp:
                data = await resp.json()

                # Enhanced rate limit logging with user context
                if 'x-mbx-used-weight-1m' in resp.headers:
                    used_weight = int(resp.headers['x-mbx-used-weight-1m'])
                    if used_weight > 1000:
                        logger.warning(f"Rate limit approaching for {user_context}: {used_weight}/1200")
                    elif used_weight > 800:
                        logger.info(f"Rate limit warning for {user_context}: {used_weight}/1200")

                if resp.status != 200:
                    code = data.get("code", resp.status)
                    msg = data.get("msg", resp.reason)
                    raise BinanceAPIError(f"{method} {path} failed for {user_context}: {msg}", code=code)

                if isinstance(data, dict) and "code" in data and data["code"] != 0:
                    raise BinanceAPIError(f"{method} {path} error for {user_context}: {data.get('msg')}", code=data.get("code"))

                return data
        except aiohttp.ClientError as e:
            logger.error(f"HTTP request failed for {user_context}: {e}")
            raise BinanceError(f"HTTP request failed: {e}")
            



    # ---------- User-specific Methods ----------
    # -------------------------------------------
    async def get_user_account_info(self, user_id: int) -> Dict[str, Any]:
        """Kullanıcı-specific account info"""
        client = await binance_client_manager.get_client_for_user(user_id)
        if client:
            return await client.get_account_info(user_id=user_id)  # ✅ user_id parametresi eklendi
        raise BinanceAuthenticationError(f"No client found for user {user_id}")


    # ---------- User-specific Methods ----------
    async def get_user_open_orders(self, user_id: int, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Kullanıcı-specific open orders"""
        client = await binance_client_manager.get_client_for_user(user_id)
        if client:
            return await client.get_open_orders(symbol=symbol, user_id=user_id)  # ✅ parametreleri doğru ver
        raise BinanceAuthenticationError(f"No client found for user {user_id}")

    async def place_user_order(
        self,
        user_id: int,
        symbol: str,
        side: str,
        type_: str,
        quantity: float,
        price: Optional[float] = None,
        timeInForce: str = "GTC"
    ) -> Dict[str, Any]:
        """Kullanıcı-specific order placement"""
        client = await binance_client_manager.get_client_for_user(user_id)
        if client:
            return await client.place_order(
                symbol=symbol,
                side=side,
                type_=type_,
                quantity=quantity,
                price=price,
                timeInForce=timeInForce,
                user_id=user_id  # ✅ user_id parametresi eklendi
            )
        raise BinanceAuthenticationError(f"No client found for user {user_id}")
    
        


    async def get_user_balances(self, user_id: int) -> Dict[str, float]:
        """Kullanıcı bakiye bilgilerini getir"""
        account_info = await self.get_user_account_info(user_id)
        balances = {}
        for balance in account_info.get('balances', []):
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])
            if free > 0 or locked > 0:
                balances[asset] = {'free': free, 'locked': locked}
        return balances
        



    # ---------- Public Endpoints ----------
    async def get_server_time(self) -> int:
        data = await self._request("GET", "/api/v3/time")
        return data["serverTime"]

    async def get_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        if not symbol or not interval:
            raise BinanceInvalidParameterError("Symbol and interval required")
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        raw = await self._request("GET", "/api/v3/klines", params)
        return self.klines_to_dataframe(raw)


    async def get_exchange_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get exchange information for all symbols or a specific symbol"""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/api/v3/exchangeInfo", params)

    async def get_order_book(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """Get order book for a symbol"""
        if not symbol:
            raise BinanceInvalidParameterError("Symbol required")
        params = {"symbol": symbol.upper(), "limit": limit}
        return await self._request("GET", "/api/v3/depth", params)

    async def get_ticker_24h(self, symbol: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Get 24hr ticker for a symbol or all symbols"""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/api/v3/ticker/24hr", params)

    async def get_symbol_price(self, symbol: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Get current price for a symbol or all symbols"""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/api/v3/ticker/price", params)
        




    # ---------- Private Endpoints ----------
    async def get_account_info(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        return await self._request("GET", "/api/v3/account", signed=True, user_id=user_id)

    async def place_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        quantity: float,
        price: Optional[float] = None,
        timeInForce: str = "GTC",
        user_id: Optional[int] = None  # Yeni parametre
    ) -> Dict[str, Any]:
        self.validate_order_parameters(symbol, side, type_, quantity, price)
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type_.upper(),
            "quantity": quantity
        }
        if type_.upper() in ["LIMIT", "LIMIT_MAKER", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]:
            params["price"] = price
            params["timeInForce"] = timeInForce
        #return await self._request("POST", "/api/v3/order", params, signed=True)
        return await self._request("POST", "/api/v3/order", params, signed=True, user_id=user_id)


    # ---------- Private Endpoints ----------
    async def get_open_orders(self, symbol: Optional[str] = None, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get open orders for a symbol or all symbols"""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/api/v3/openOrders", params, signed=True, user_id=user_id)  # ✅ GET + correct endpoint

    async def get_order(self, symbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get order status"""
        if not order_id and not orig_client_order_id:
            raise BinanceInvalidParameterError("Either order_id or orig_client_order_id required")
        
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        
        return await self._request("GET", "/api/v3/order", params, signed=True, user_id=user_id)  # ✅ GET

    async def cancel_order(self, symbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Cancel an active order"""
        if not order_id and not orig_client_order_id:
            raise BinanceInvalidParameterError("Either order_id or orig_client_order_id required")
        
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        
        return await self._request("DELETE", "/api/v3/order", params, signed=True, user_id=user_id)  # ✅ DELETE

    async def get_my_trades(self, symbol: str, limit: int = 500, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get trade history for a symbol"""
        if not symbol:
            raise BinanceInvalidParameterError("Symbol required")
        params = {"symbol": symbol.upper(), "limit": limit}
        return await self._request("GET", "/api/v3/myTrades", params, signed=True, user_id=user_id)  # ✅ GET + correct endpoint
        
 


    # ---------- Futures Endpoints ----------


    # ---------- Futures Endpoints ----------
    async def get_futures_account_info(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get futures account information"""
        return await self._request("GET", "/fapi/v2/account", signed=True, base_url=FUTURES_URL, user_id=user_id)

    async def place_futures_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        quantity: float,
        price: Optional[float] = None,
        timeInForce: str = "GTC",
        reduceOnly: bool = False,
        user_id: Optional[int] = None  # Yeni parametre
    ) -> Dict[str, Any]:
        """Place a futures order"""
        self.validate_order_parameters(symbol, side, type_, quantity, price)
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": type_.upper(),
            "quantity": quantity,
            "reduceOnly": "true" if reduceOnly else "false"
        }
        if type_.upper() in ["LIMIT", "STOP", "TAKE_PROFIT"]:
            params["price"] = price
            params["timeInForce"] = timeInForce
        return await self._request("POST", "/fapi/v1/order", params, signed=True, base_url=FUTURES_URL, user_id=user_id)
        

    async def get_futures_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        """Get futures klines data"""
        if not symbol or not interval:
            raise BinanceInvalidParameterError("Symbol and interval required")
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        raw = await self._request("GET", "/fapi/v1/klines", params, base_url=FUTURES_URL)
        return self.klines_to_dataframe(raw)



    # ---------- Helper Functions ----------
    def klines_to_dataframe(self, klines: List[List[Any]]) -> pd.DataFrame:
        if not klines:
            return pd.DataFrame(columns=KLINE_FIELDS)
        df = pd.DataFrame(klines, columns=KLINE_FIELDS)
        numeric_columns = ['open', 'high', 'low', 'close', 'volume',
                           'quote_asset_volume', 'taker_buy_base_asset_volume',
                           'taker_buy_quote_asset_volume', 'ignore']
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        df.set_index('open_time', inplace=True)
        return df

    def format_quantity(self, symbol: str, quantity: float, step_size: Optional[float] = None) -> float:
        if step_size is None:
            step_sizes = {"BTCUSDT": 0.000001, "ETHUSDT": 0.0001}
            step_size = step_sizes.get(symbol.upper(), 0.001)
        precision = 0
        while step_size < 1:
            step_size *= 10
            precision += 1
        return round(quantity, precision)

    def format_price(self, symbol: str, price: float, tick_size: Optional[float] = None) -> float:
        if tick_size is None:
            tick_sizes = {"BTCUSDT": 0.01, "ETHUSDT": 0.01}
            tick_size = tick_sizes.get(symbol.upper(), 0.0001)
        precision = 0
        while tick_size < 1:
            tick_size *= 10
            precision += 1
        return round(price, precision)

    def calculate_pnl(self, entry_price: float, exit_price: float, quantity: float, side: str, fee: float = 0.001) -> Dict[str, float]:
        gross_pnl = (exit_price - entry_price) * quantity if side.upper() == 'BUY' else (entry_price - exit_price) * quantity
        fee_amount = (entry_price + exit_price) * quantity * fee
        net_pnl = gross_pnl - fee_amount
        return {
            'gross_pnl': gross_pnl,
            'fee_amount': fee_amount,
            'net_pnl': net_pnl,
            'roe': (net_pnl / (entry_price * quantity)) * 100 if entry_price * quantity > 0 else 0
        }

    def validate_order_parameters(self, symbol: str, side: str, type_: str, quantity: float, price: Optional[float] = None) -> None:
        if not validate_symbol(symbol):
            raise BinanceInvalidParameterError(f"Invalid symbol: {symbol}")
        if side.upper() not in ['BUY', 'SELL']:
            raise BinanceInvalidParameterError(f"Invalid side: {side}")
        if type_.upper() not in ['LIMIT', 'MARKET', 'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
            raise BinanceInvalidParameterError(f"Invalid order type: {type_}")
        if quantity <= 0:
            raise BinanceInvalidParameterError("Quantity must be positive")
        if type_.upper() in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER'] and (price is None or price <= 0):
            raise BinanceInvalidParameterError("Price required for limit orders")

    async def async_sleep_until(self, timestamp: int) -> None:
        current_time = int(time.time() * 1000)
        sleep_time = (timestamp - current_time) / 1000
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    async def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get symbol information including filters"""
        exchange_info = await self.get_exchange_info(symbol)
        symbols = exchange_info.get('symbols', [])
        for s in symbols:
            if s['symbol'] == symbol.upper():
                return s
        return None

    async def get_precision(self, symbol: str) -> Dict[str, int]:
        """Get price and quantity precision for a symbol"""
        symbol_info = await self.get_symbol_info(symbol)
        if not symbol_info:
            raise BinanceInvalidParameterError(f"Symbol {symbol} not found")
        
        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
        price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
        
        return {
            'quantity_precision': self._get_precision_from_step_size(lot_size_filter['stepSize'] if lot_size_filter else '0.001'),
            'price_precision': self._get_precision_from_tick_size(price_filter['tickSize'] if price_filter else '0.01')
        }

    def _get_precision_from_step_size(self, step_size: str) -> int:
        """Calculate precision from step size"""
        step = float(step_size)
        precision = 0
        while step < 1:
            step *= 10
            precision += 1
        return precision

    def _get_precision_from_tick_size(self, tick_size: str) -> int:
        """Calculate precision from tick size"""
        tick = float(tick_size)
        precision = 0
        while tick < 1:
            tick *= 10
            precision += 1
        return precision
        




# WebSocket Client
class BinanceWebSocketClient:
    def __init__(self, base_url: str = "wss://stream.binance.com:9443/stream"):
        self.base_url = base_url
        self.session = aiohttp.ClientSession()
        self.ws = None
        self._listen_task = None
        self._callback: Optional[Callable[[dict], None]] = None
        self._streams: List[str] = []

    async def connect(self, streams: List[str], message_callback: Callable[[dict], None]):
        self._callback = message_callback
        self._streams = streams
        stream_path = '/'.join(streams)
        url = f"{self.base_url}?streams={stream_path}"
        self.ws = await self.session.ws_connect(url)
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.json()
                    if self._callback:
                        self._callback(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("WebSocket error received.")
                    break
        except Exception as e:
            logger.exception(f"WebSocket listen error: {e}")
            await self._reconnect()

    async def _reconnect(self):
        logger.warning("Reconnecting WebSocket...")
        await asyncio.sleep(5)
        await self.connect(self._streams, self._callback)

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self._listen_task:
            self._listen_task.cancel()
        await self.session.close()



#
"""
BinanceClient artık context manager (async with) destekliyor.
BinanceWebSocketClient artık birden fazla stream dinliyor (örnek: ['btcusdt@kline_1m', 'ethusdt@trade']).
Otomatik yeniden bağlanma özelliği var.
aiohttp.ClientSession çakışmalarına karşı izole.
Rate limit loglanıyor.
✅ Multi-user desteği
✅ API Key Manager entegrasyonu
✅ Rate limit monitoring
✅ User-specific method'lar
Public İşlemler (user_id gerekmez)


"""