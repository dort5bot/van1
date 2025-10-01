# utils/binance/binance_client.py

"""

Public ve private endpoint çağrıları kapsanıyor.
Parametre validation entegre.
HTTP + Binance error handling var (status + Binance code).
Async/await uyumlu, rate limit önlemleri eklenebilir.
Utility fonksiyonlar client içine entegre edilmiş.

"""

import aiohttp
import asyncio
import time
import hmac
import hashlib
from typing import Any, Dict, Optional, List, Union
import pandas as pd
from datetime import datetime
from .binance_constants import KLINE_FIELDS
from .binance_exceptions import (
    BinanceError,
    BinanceAPIError,
    BinanceAuthenticationError,
    BinanceInvalidParameterError
)

BASE_URL = "https://api.binance.com"
SAPI_URL = "https://api.binance.com/sapi/v1"
FUTURES_URL = "https://fapi.binance.com"

class BinanceClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = aiohttp.ClientSession()
    
    # ---------- Utility methods ----------
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        return headers

    def _check_keys(self) -> None:
        if not self.api_key or not self.api_secret:
            raise BinanceAuthenticationError("API key and secret required for this endpoint")

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
        base_url: str = BASE_URL
    ) -> Any:
        if params is None:
            params = {}
        if signed:
            self._check_keys()
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._sign(params)
        url = f"{base_url}{path}"
        headers = self._get_headers()
        try:
            async with self.session.request(method, url, params=params, headers=headers) as resp:
                data = await resp.json()
                if resp.status != 200:
                    code = data.get("code", resp.status)
                    msg = data.get("msg", resp.reason)
                    raise BinanceAPIError(f"{method} {path} failed: {msg}", code=code)
                if isinstance(data, dict) and "code" in data and data["code"] != 0:
                    raise BinanceAPIError(f"{method} {path} error: {data.get('msg')}", code=data.get("code"))
                return data
        except aiohttp.ClientError as e:
            raise BinanceError(f"HTTP request failed: {e}")
    
    async def close(self):
        await self.session.close()

    # ---------- Public Endpoints ----------
    async def get_server_time(self) -> int:
        data = await self._request("GET", "/api/v3/time")
        return data["serverTime"]

    async def get_klines(
        self, 
        symbol: str, 
        interval: str, 
        limit: int = 500
    ) -> pd.DataFrame:
        if not symbol or not interval:
            raise BinanceInvalidParameterError("Symbol and interval required")
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        raw = await self._request("GET", "/api/v3/klines", params)
        return self.klines_to_dataframe(raw)
    
    # ---------- Private Endpoints ----------
    async def get_account_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/api/v3/account", signed=True)
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        quantity: float,
        price: Optional[float] = None,
        timeInForce: str = "GTC"
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
        return await self._request("POST", "/api/v3/order", params, signed=True)
    
    # ---------- Helper functions ----------
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
            step_sizes = {"BTCUSDT": 0.000001, "ETHUSDT": 0.0001, "BNBUSDT": 0.001, "ADAUSDT": 1, "DOGEUSDT": 1}
            step_size = step_sizes.get(symbol.upper(), 0.001)
        if step_size == 0:
            return quantity
        precision = 0
        while step_size < 1:
            step_size *= 10
            precision += 1
        return round(quantity, precision)
    
    def format_price(self, symbol: str, price: float, tick_size: Optional[float] = None) -> float:
        if tick_size is None:
            tick_sizes = {"BTCUSDT": 0.01, "ETHUSDT": 0.01, "BNBUSDT": 0.001, "ADAUSDT": 0.0001, "DOGEUSDT": 0.0001}
            tick_size = tick_sizes.get(symbol.upper(), 0.0001)
        if tick_size == 0:
            return price
        precision = 0
        while tick_size < 1:
            tick_size *= 10
            precision += 1
        return round(price, precision)

    def calculate_pnl(self, entry_price: float, exit_price: float, quantity: float, side: str, fee: float = 0.001) -> Dict[str, float]:
        if side.upper() == 'BUY':
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity
        fee_amount = (entry_price * quantity * fee) + (exit_price * quantity * fee)
        net_pnl = gross_pnl - fee_amount
        return {
            'gross_pnl': gross_pnl,
            'fee_amount': fee_amount,
            'net_pnl': net_pnl,
            'roe': (net_pnl / (entry_price * quantity)) * 100 if entry_price * quantity > 0 else 0
        }

    def validate_order_parameters(self, symbol: str, side: str, type_: str, quantity: float, price: Optional[float] = None) -> None:
        from .binance_utils import validate_symbol  # mevcut utility import
        if not validate_symbol(symbol):
            raise BinanceInvalidParameterError(f"Invalid symbol: {symbol}")
        if side.upper() not in ['BUY', 'SELL']:
            raise BinanceInvalidParameterError(f"Invalid side: {side}")
        if type_.upper() not in ['LIMIT', 'MARKET', 'STOP_LOSS', 'STOP_LOSS_LIMIT',
                                 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
            raise BinanceInvalidParameterError(f"Invalid order type: {type_}")
        if quantity <= 0:
            raise BinanceInvalidParameterError("Quantity must be positive")
        if type_.upper() in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
            if price is None or price <= 0:
                raise BinanceInvalidParameterError("Price required for limit orders")
    
    # ---------- Async sleep ----------
    async def async_sleep_until(self, timestamp: int) -> None:
        current_time = int(time.time() * 1000)
        sleep_time = (timestamp - current_time) / 1000
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
