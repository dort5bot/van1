"""utils/binance/binance_public.py
v4 class mod - Strict Binance Public API Compliance
Binance Public API endpoints.

Bu modül, Binance spot ve futures public endpoint'lerini kapsayan asenkron client'lar sağlar.
Strict mode: Binance dokümantasyonu ile birebir uyumlu method isimleri ve endpoint'ler.

"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union, TypedDict

from enum import Enum
from pydantic import BaseModel, Field
from aiogram import Router
from aiogram.types import Message
from contextlib import asynccontextmanager

from config import settings  # Config yönetimi için
# Lokal bağımlılıklar
from .binance_request import BinanceHTTPClient
from .binance_circuit_breaker import CircuitBreaker
from .binance_exceptions import BinanceAPIError
from .binance_types import Interval, Symbol

logger = logging.getLogger(__name__)

# Parametre validasyonu için sabitler - Genişletilmiş
VALID_PERIODS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
VALID_DEPTH_LIMITS = {5, 10, 20, 50, 100, 500, 1000, 5000}
VALID_FUTURES_DEPTH_LIMITS = {5, 10, 20, 50, 100, 500, 1000}


# MAJOR - Config Yönetimi
class BinanceConfig(BaseModel):
    """Binance API configuration using Pydantic"""
    base_url: str = Field(default="https://api.binance.com")
    futures_base_url: str = Field(default="https://fapi.binance.com")
    timeout: int = Field(default=30)
    rate_limit_per_second: int = Field(default=10)
    
    class Config:
        env_prefix = "BINANCE_"
        

# MAJOR - Router Pattern (aiogram 3.x)
class BinancePublicRouter:
    """AIogram 3.x Router for Binance Public API"""
    
    def __init__(self, spot_api: BinanceSpotPublicAPI, futures_api: BinanceFuturesPublicAPI):
        self.router = Router()
        self.spot_api = spot_api
        self.futures_api = futures_api
        self._register_handlers()
    
    def _register_handlers(self):
        """Register AIogram handlers"""
        self.router.message()(self.price_handler)
        self.router.message()(self.depth_handler)
    
    async def price_handler(self, message: Message):
        """Handle price requests"""
        symbol = message.text.upper()
        price = await self.spot_api.get_ticker_price(symbol)
        await message.answer(f"{symbol} price: {price}")


# Return type tanımlamaları
class TickerPrice(TypedDict):
    symbol: str
    price: str

class DepthSnapshot(TypedDict):
    lastUpdateId: int
    bids: List[List[str]]
    asks: List[List[str]]

class Kline(TypedDict):
    openTime: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    closeTime: int
    quoteAssetVolume: str
    numberOfTrades: int
    takerBuyBaseAssetVolume: str
    takerBuyQuoteAssetVolume: str
    ignore: str

class Trade(TypedDict):
    id: int
    price: str
    qty: str
    quoteQty: str
    time: int
    isBuyerMaker: bool
    isBestMatch: bool

class AvgPrice(TypedDict):
    mins: int
    price: str

class BookTicker(TypedDict):
    symbol: str
    bidPrice: str
    bidQty: str
    askPrice: str
    askQty: str

class Ticker24hr(TypedDict):
    symbol: str
    priceChange: str
    priceChangePercent: str
    weightedAvgPrice: str
    prevClosePrice: str
    lastPrice: str
    lastQty: str
    bidPrice: str
    askPrice: str
    openPrice: str
    highPrice: str
    lowPrice: str
    volume: str
    quoteVolume: str
    openTime: int
    closeTime: int
    firstId: int
    lastId: int
    count: int

class MarkPrice(TypedDict):
    symbol: str
    markPrice: str
    indexPrice: str
    estimatedSettlePrice: str
    lastFundingRate: str
    nextFundingTime: int
    interestRate: str
    time: int

class FundingRate(TypedDict):
    symbol: str
    fundingRate: str
    fundingTime: int

class OpenInterest(TypedDict):
    openInterest: str
    symbol: str
    time: int


# EKLENMESİ GEREKEN ENUM'lar
class Interval(Enum):
    """Kline intervals"""
    MINUTE_1 = "1m"
    MINUTE_3 = "3m"
    MINUTE_5 = "5m"
    HOUR_1 = "1h"
    HOUR_2 = "2h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    # ... diğer interval'ler

class SymbolStatus(Enum):
    """Symbol statuses"""
    TRADING = "TRADING"
    HALT = "HALT"
    BREAK = "BREAK"



# MEVCUT YERİNE DAHA İYİ BİR YAKLAŞIM
class BaseBinanceAPI:
    def __init__(self, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker, config: BinanceConfig) -> None:
        self.http: BinanceHTTPClient = http_client
        self.circuit_breaker: CircuitBreaker = circuit_breaker
        self.config: BinanceConfig = config
        self._router: Optional[Router] = None
        logger.info(f"{self.__class__.__name__} initialized.")

    def _make_request(self, method: str, endpoint: str, params: Dict[str, Any] = None, futures: bool = False) -> Any:
        """Unified request method to reduce code duplication"""
        base_url = self.config.futures_base_url if futures else self.config.base_url
        return self.circuit_breaker.execute(
            self.http._request, method, endpoint, params or {}, base_url
        )

    # Ortak validation metodları burada kalabilir
    def _validate_period(self, period: str) -> None:
        if period not in VALID_PERIODS:
            raise ValueError(f"Invalid period {period}, must be one of {VALID_PERIODS}")

    # Property for AIogram router
    @property
    def router(self) -> Router:
        if self._router is None:
            self._router = Router()
        return self._router
        
    # CONTEXT MANAGER EKSİK
    @asynccontextmanager
    async def session_context(self):
        """Context manager for proper resource cleanup"""
        try:
            yield self
        except Exception as e:
            logger.error(f"Session error: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def _cleanup(self):
        """Cleanup resources"""
        if hasattr(self.http, 'session'):
            await self.http.session.close()
    
    
    



class BinanceSpotPublicAPI(BaseBinanceAPI):
    """
    Binance Spot Public API işlemleri - Strict Mode.
    """
    
    _instance: Optional["BinanceSpotPublicAPI"] = None
    _initialized: bool = False
    _lock = asyncio.Lock()

    def __new__(cls, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> "BinanceSpotPublicAPI":
        """Singleton implementasyonu."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(http_client, circuit_breaker)
        return cls._instance

    def _initialize(self, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> None:
        """Internal initialization method."""
        if not self._initialized:
            super().__init__(http_client, circuit_breaker)
            self._initialized = True

    def __init__(self, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> None:
        """Initialization is handled in __new__ and _initialize."""
        pass

    # -------------------------
    # Basic endpoints - Strict Binance naming
    # -------------------------
    async def ping(self) -> Dict[str, Any]:
        """Test connectivity to the Rest API."""
        try:
            logger.debug("Pinging Binance Spot API.")
            return await self.circuit_breaker.execute(self.http._request, "GET", "/api/v3/ping")
        except Exception as e:
            logger.exception("Ping to Binance Spot API failed.")
            raise BinanceAPIError(f"Error pinging Binance Spot API: {e}")

    async def get_server_time(self) -> Dict[str, Any]:
        """Check server time."""
        try:
            logger.debug("Requesting server time.")
            return await self.circuit_breaker.execute(self.http._request, "GET", "/api/v3/time")
        except Exception as e:
            logger.exception("Error getting server time.")
            raise BinanceAPIError(f"Error getting server time: {e}")

    async def get_exchange_info(self) -> Dict[str, Any]:
        """Exchange information."""
        try:
            logger.debug("Requesting exchange info.")
            return await self.circuit_breaker.execute(self.http._request, "GET", "/api/v3/exchangeInfo")
        except Exception as e:
            logger.exception("Error getting exchange info.")
            raise BinanceAPIError(f"Error getting exchange info: {e}")

    async def get_order_book(self, symbol: str, limit: int = 100) -> DepthSnapshot:
        """Get order book (depth) for a symbol."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            self._validate_depth_limit(limit, futures=False)
            
            logger.debug("Requesting order book for %s limit=%s", symbol_clean, limit)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/depth", {"symbol": symbol_clean, "limit": limit}
            )
        except Exception as e:
            logger.exception("Error getting order book for %s", symbol)
            raise BinanceAPIError(f"Error getting order book for {symbol}: {e}")

    async def get_recent_trades(self, symbol: str, limit: int = 500) -> List[Trade]:
        """Get recent trades."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            logger.debug("Requesting recent trades for %s limit=%s", symbol_clean, limit)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/trades", {"symbol": symbol_clean, "limit": limit}
            )
        except Exception as e:
            logger.exception("Error getting recent trades for %s", symbol)
            raise BinanceAPIError(f"Error getting recent trades for {symbol}: {e}")

    async def get_historical_trades(self, symbol: str, limit: int = 500, from_id: Optional[int] = None) -> List[Trade]:
        """Get older market trades."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "limit": limit}
            if from_id is not None:
                params["fromId"] = from_id
                
            logger.debug("Requesting historical trades for %s limit=%s", symbol_clean, limit)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/historicalTrades", params
            )
        except Exception as e:
            logger.exception("Error getting historical trades for %s", symbol)
            raise BinanceAPIError(f"Error getting historical trades for {symbol}: {e}")

    async def get_agg_trades(
        self, symbol: str, from_id: Optional[int] = None, 
        start_time: Optional[int] = None, end_time: Optional[int] = None, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get compressed/aggregate trades."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean}
            
            if from_id is not None:
                params["fromId"] = from_id
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting agg trades for %s params=%s", symbol_clean, params)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/aggTrades", params
            )
        except Exception as e:
            logger.exception("Error getting agg trades for %s", symbol)
            raise BinanceAPIError(f"Error getting agg trades for {symbol}: {e}")

    async def get_klines(
        self, symbol: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """Kline/candlestick data."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting klines for %s interval=%s", symbol_clean, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/klines", params
            )
        except Exception as e:
            logger.exception("Error getting klines for %s", symbol)
            raise BinanceAPIError(f"Error getting klines for {symbol}: {e}")

    async def get_ui_klines(
        self, symbol: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """UI klines (modified klines)."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting ui klines for %s interval=%s", symbol_clean, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/uiKlines", params
            )
        except Exception as e:
            logger.exception("Error getting ui klines for %s", symbol)
            raise BinanceAPIError(f"Error getting ui klines for {symbol}: {e}")

    async def get_current_avg_price(self, symbol: str) -> AvgPrice:
        """Current average price."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            logger.debug("Requesting current avg price for %s", symbol_clean)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/avgPrice", {"symbol": symbol_clean}
            )
        except Exception as e:
            logger.exception("Error getting current avg price for %s", symbol)
            raise BinanceAPIError(f"Error getting current avg price for {symbol}: {e}")

    async def get_24hr_ticker(self, symbol: Optional[str] = None) -> Union[Ticker24hr, List[Ticker24hr]]:
        """24 hour rolling window price change statistics."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)

            logger.debug("Requesting 24hr ticker for symbol=%s", symbol or "ALL")
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/ticker/24hr", params
            )
        except Exception as e:
            logger.exception("Error getting 24hr ticker for %s", symbol or "ALL")
            raise BinanceAPIError(f"Error getting 24hr ticker for {symbol or 'ALL'}: {e}")

    async def get_ticker_price(self, symbol: Optional[str] = None) -> Union[TickerPrice, List[TickerPrice]]:
        """Latest price for a symbol or symbols."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)

            logger.debug("Requesting ticker price for symbol=%s", symbol or "ALL")
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/ticker/price", params
            )
        except Exception as e:
            logger.exception("Error getting ticker price for %s", symbol or "ALL")
            raise BinanceAPIError(f"Error getting ticker price for {symbol or 'ALL'}: {e}")

    async def get_book_ticker(self, symbol: Optional[str] = None) -> Union[BookTicker, List[BookTicker]]:
        """Best price/qty on the order book for a symbol or symbols."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting book ticker for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/api/v3/ticker/bookTicker", params
            )
        except Exception as e:
            logger.exception("Error getting book ticker for %s", symbol)
            raise BinanceAPIError(f"Error getting book ticker for {symbol or 'ALL'}: {e}")


    # SPOT API'de Eksik Endpoint'ler
    async def get_system_status(self) -> Dict[str, Any]:
        """System status endpoint"""
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/wapi/v3/systemStatus.html"
        )

    async def get_coins_info(self) -> List[Dict[str, Any]]:
        """All coins information"""
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/sapi/v1/capital/config/getall"
        )

    async def get_daily_account_snapshot(self, account_type: str = "SPOT") -> Dict[str, Any]:
        """Daily account snapshot (public but needs auth)"""
        params = {"type": account_type}
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/sapi/v1/accountSnapshot", params
        )

    async def get_dust_log(self) -> Dict[str, Any]:
        """Dust log"""
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/sapi/v1/asset/dribblet"
        )

    async def get_trade_fee(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Trade fee"""
        params = {}
        if symbol:
            params["symbol"] = self._validate_symbol(symbol)
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/sapi/v1/asset/tradeFee", params
        )



    # -------------------------
    # Convenience methods
    # -------------------------
    async def get_all_symbols(self, trading_only: bool = True) -> List[str]:
        """Get list of all symbols from exchangeInfo."""
        try:
            logger.debug("Requesting all symbols via exchangeInfo.")
            data = await self.get_exchange_info()
            
            if trading_only:
                symbols = [s["symbol"] for s in data.get("symbols", []) 
                          if s.get("status") == "TRADING"]
            else:
                symbols = [s["symbol"] for s in data.get("symbols", [])]
                
            logger.debug("Retrieved %d symbols.", len(symbols))
            return symbols
        except Exception as e:
            logger.exception("Error getting all symbols.")
            raise BinanceAPIError(f"Error getting all symbols: {e}")

    async def symbol_exists(self, symbol: str) -> bool:
        """Check if a symbol exists on the exchange."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            logger.debug("Checking if symbol exists: %s", symbol_clean)
            info = await self.get_exchange_info()
            
            for s in info.get("symbols", []):
                if s.get("symbol") == symbol_clean:
                    return True
            return False
        except Exception as e:
            logger.exception("Error checking if symbol exists: %s", symbol)
            raise BinanceAPIError(f"Error checking if symbol exists {symbol}: {e}")


class BinanceFuturesPublicAPI(BaseBinanceAPI):
    """
    Binance Futures Public API işlemleri - Strict Mode.
    """
    
    _instance: Optional["BinanceFuturesPublicAPI"] = None
    _initialized: bool = False
    _lock = asyncio.Lock()

    def __new__(cls, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> "BinanceFuturesPublicAPI":
        """Singleton implementasyonu."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(http_client, circuit_breaker)
        return cls._instance

    def _initialize(self, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> None:
        """Internal initialization method."""
        if not self._initialized:
            super().__init__(http_client, circuit_breaker)
            self._initialized = True

    def __init__(self, http_client: BinanceHTTPClient, circuit_breaker: CircuitBreaker) -> None:
        """Initialization is handled in __new__ and _initialize."""
        pass

    # -------------------------
    # Futures Basic endpoints - Strict Binance naming
    # -------------------------
    async def ping(self) -> Dict[str, Any]:
        """Test connectivity to the Rest API."""
        try:
            logger.debug("Pinging Binance Futures API.")
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/ping", futures=True
            )
        except Exception as e:
            logger.exception("Ping to Binance Futures API failed.")
            raise BinanceAPIError(f"Error pinging Binance Futures API: {e}")

    async def get_exchange_info(self) -> Dict[str, Any]:
        """Exchange information."""
        try:
            logger.debug("Requesting futures exchange info.")
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/exchangeInfo", futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures exchange info.")
            raise BinanceAPIError(f"Error getting futures exchange info: {e}")

    async def get_order_book(self, symbol: str, limit: int = 100) -> DepthSnapshot:
        """Get order book (depth) for a symbol."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            self._validate_depth_limit(limit, futures=True)
            
            logger.debug("Requesting futures order book for %s limit=%s", symbol_clean, limit)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/depth", 
                {"symbol": symbol_clean, "limit": limit}, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures order book for %s", symbol)
            raise BinanceAPIError(f"Error getting futures order book for {symbol}: {e}")

    async def get_recent_trades(self, symbol: str, limit: int = 500) -> List[Trade]:
        """Get recent trades."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            logger.debug("Requesting futures recent trades for %s limit=%s", symbol_clean, limit)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/trades", 
                {"symbol": symbol_clean, "limit": limit}, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures recent trades for %s", symbol)
            raise BinanceAPIError(f"Error getting futures recent trades for {symbol}: {e}")

    async def get_historical_trades(self, symbol: str, limit: int = 500, from_id: Optional[int] = None) -> List[Trade]:
        """Get older market trades."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "limit": limit}
            if from_id is not None:
                params["fromId"] = from_id
                
            logger.debug("Requesting futures historical trades for %s limit=%s", symbol_clean, limit)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/historicalTrades", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures historical trades for %s", symbol)
            raise BinanceAPIError(f"Error getting futures historical trades for {symbol}: {e}")

    async def get_agg_trades(
        self, symbol: str, from_id: Optional[int] = None, 
        start_time: Optional[int] = None, end_time: Optional[int] = None, 
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get compressed/aggregate trades."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean}
            
            if from_id is not None:
                params["fromId"] = from_id
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting futures agg trades for %s params=%s", symbol_clean, params)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/aggTrades", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures agg trades for %s", symbol)
            raise BinanceAPIError(f"Error getting futures agg trades for {symbol}: {e}")

    async def get_klines(
        self, symbol: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """Kline/candlestick data."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting futures klines for %s interval=%s", symbol_clean, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/klines", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures klines for %s", symbol)
            raise BinanceAPIError(f"Error getting futures klines for {symbol}: {e}")

    async def get_continuous_klines(
        self, pair: str, contractType: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """Continuous contract kline/candlestick data."""
        try:
            params: Dict[str, Any] = {"pair": pair, "contractType": contractType, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting continuous klines for %s contractType=%s interval=%s", pair, contractType, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/continuousKlines", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting continuous klines for %s", pair)
            raise BinanceAPIError(f"Error getting continuous klines for {pair}: {e}")

    async def get_index_price_klines(
        self, pair: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """Index price kline/candlestick data."""
        try:
            params: Dict[str, Any] = {"pair": pair, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting index price klines for %s interval=%s", pair, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/indexPriceKlines", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting index price klines for %s", pair)
            raise BinanceAPIError(f"Error getting index price klines for {pair}: {e}")

    async def get_mark_price_klines(
        self, symbol: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """Mark price kline/candlestick data."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting mark price klines for %s interval=%s", symbol_clean, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/markPriceKlines", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting mark price klines for %s", symbol)
            raise BinanceAPIError(f"Error getting mark price klines for {symbol}: {e}")

    async def get_mark_price(self, symbol: Optional[str] = None) -> Union[MarkPrice, List[MarkPrice]]:
        """Mark price and funding rate."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting mark price for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/premiumIndex", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting mark price for %s", symbol)
            raise BinanceAPIError(f"Error getting mark price for {symbol or 'ALL'}: {e}")

    async def get_funding_rate(
        self, symbol: str, start_time: Optional[int] = None, 
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[FundingRate]:
        """Funding rate history."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting funding rate for %s", symbol_clean)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/fundingRate", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting funding rate for %s", symbol)
            raise BinanceAPIError(f"Error getting funding rate for {symbol}: {e}")

    async def get_24hr_ticker(self, symbol: Optional[str] = None) -> Union[Ticker24hr, List[Ticker24hr]]:
        """24 hour rolling window price change statistics."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting futures 24hr ticker for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/ticker/24hr", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures 24hr ticker for %s", symbol)
            raise BinanceAPIError(f"Error getting futures 24hr ticker for {symbol or 'ALL'}: {e}")

    async def get_ticker_price(self, symbol: Optional[str] = None) -> Union[TickerPrice, List[TickerPrice]]:
        """Latest price for a symbol or symbols."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting futures ticker price for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/ticker/price", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures ticker price for %s", symbol)
            raise BinanceAPIError(f"Error getting futures ticker price for {symbol or 'ALL'}: {e}")

    async def get_book_ticker(self, symbol: Optional[str] = None) -> Union[BookTicker, List[BookTicker]]:
        """Best price/qty on the order book for a symbol or symbols."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting futures book ticker for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/ticker/bookTicker", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting futures book ticker for %s", symbol)
            raise BinanceAPIError(f"Error getting futures book ticker for {symbol or 'ALL'}: {e}")

    async def get_open_interest(self, symbol: str) -> OpenInterest:
        """Get present open interest of a specific symbol."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            logger.debug("Requesting open interest for %s", symbol_clean)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/openInterest", 
                {"symbol": symbol_clean}, futures=True
            )
        except Exception as e:
            logger.exception("Error getting open interest for %s", symbol)
            raise BinanceAPIError(f"Error getting open interest for {symbol}: {e}")

    async def get_open_interest_hist(
        self, symbol: str, period: str = "5m", limit: int = 30, 
        start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get historical open interest of a specific symbol."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            self._validate_period(period)
            
            params: Dict[str, Any] = {"symbol": symbol_clean, "period": period, "limit": limit}
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
                
            logger.debug("Requesting open interest history for %s period=%s", symbol_clean, period)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/futures/data/openInterestHist", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting open interest history for %s", symbol)
            raise BinanceAPIError(f"Error getting open interest history for {symbol}: {e}")

    async def get_top_long_short_ratio(
        self, symbol: str, period: str = "5m", limit: int = 30,
        start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get top trader long/short account ratio."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            self._validate_period(period)
            
            params: Dict[str, Any] = {"symbol": symbol_clean, "period": period, "limit": limit}
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
                
            logger.debug("Requesting top long/short ratio for %s period=%s", symbol_clean, period)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/futures/data/topLongShortAccountRatio", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting top long/short ratio for %s", symbol)
            raise BinanceAPIError(f"Error getting top long/short ratio for {symbol}: {e}")

    async def get_global_long_short_ratio(
        self, symbol: str, period: str = "5m", limit: int = 30,
        start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get global long/short account ratio."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            self._validate_period(period)
            
            params: Dict[str, Any] = {"symbol": symbol_clean, "period": period, "limit": limit}
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
                
            logger.debug("Requesting global long/short ratio for %s period=%s", symbol_clean, period)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/futures/data/globalLongShortAccountRatio", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting global long/short ratio for %s", symbol)
            raise BinanceAPIError(f"Error getting global long/short ratio for {symbol}: {e}")

    async def get_taker_buy_sell_volume(
        self, symbol: str, period: str = "5m", limit: int = 30,
        start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get taker buy/sell volume."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            self._validate_period(period)
            
            params: Dict[str, Any] = {"symbol": symbol_clean, "period": period, "limit": limit}
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
                
            logger.debug("Requesting taker buy/sell volume for %s period=%s", symbol_clean, period)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/futures/data/takerlongshortRatio", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting taker buy/sell volume for %s", symbol)
            raise BinanceAPIError(f"Error getting taker buy/sell volume for {symbol}: {e}")

    async def get_lvt_klines(
        self, symbol: str, interval: str, start_time: Optional[int] = None,
        end_time: Optional[int] = None, limit: Optional[int] = None
    ) -> List[Kline]:
        """LVT (Leveraged Token) Kline/candlestick data."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            params: Dict[str, Any] = {"symbol": symbol_clean, "interval": interval}
            
            if start_time is not None:
                params["startTime"] = start_time
            if end_time is not None:
                params["endTime"] = end_time
            if limit is not None:
                params["limit"] = limit
                
            logger.debug("Requesting LVT klines for %s interval=%s", symbol_clean, interval)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/lvtKlines", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting LVT klines for %s", symbol)
            raise BinanceAPIError(f"Error getting LVT klines for {symbol}: {e}")

    async def get_index_info(self, symbol: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Get index composite information."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting index info for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/indexInfo", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting index info for %s", symbol)
            raise BinanceAPIError(f"Error getting index info for {symbol or 'ALL'}: {e}")

    async def get_asset_index(self, symbol: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Get asset index for multi-asset mode."""
        try:
            params: Dict[str, Any] = {}
            if symbol:
                params["symbol"] = self._validate_symbol(symbol)
                
            logger.debug("Requesting asset index for symbol=%s", symbol)
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/fapi/v1/assetIndex", params, futures=True
            )
        except Exception as e:
            logger.exception("Error getting asset index for %s", symbol)
            raise BinanceAPIError(f"Error getting asset index for {symbol or 'ALL'}: {e}")

    # FUTURES API'de 
    async def get_force_orders(
        self, symbol: Optional[str] = None, 
        start_time: Optional[int] = None, end_time: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """User's Force Orders"""
        params = {}
        if symbol:
            params["symbol"] = self._validate_symbol(symbol)
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if limit:
            params["limit"] = limit
            
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/fapi/v1/forceOrders", params, futures=True
        )

    async def get_adl_quantile(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Position ADL Quantile Estimation"""
        params = {}
        if symbol:
            params["symbol"] = self._validate_symbol(symbol)
            
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/fapi/v1/adlQuantile", params, futures=True
        )

    async def get_commission_rate(self, symbol: str) -> Dict[str, Any]:
        """Commission Rate"""
        symbol_clean = self._validate_symbol(symbol)
        return await self.circuit_breaker.execute(
            self.http._request, "GET", "/fapi/v1/commissionRate", 
            {"symbol": symbol_clean}, futures=True
        )








    # -------------------------
    # Convenience methods
    # -------------------------
    async def get_all_symbols(self, trading_only: bool = True) -> List[str]:
        """Get list of all symbols from exchangeInfo."""
        try:
            logger.debug("Requesting all futures symbols via exchangeInfo.")
            data = await self.get_exchange_info()
            
            if trading_only:
                symbols = [s["symbol"] for s in data.get("symbols", []) 
                          if s.get("status") == "TRADING"]
            else:
                symbols = [s["symbol"] for s in data.get("symbols", [])]
                
            logger.debug("Retrieved %d futures symbols.", len(symbols))
            return symbols
        except Exception as e:
            logger.exception("Error getting all futures symbols.")
            raise BinanceAPIError(f"Error getting all futures symbols: {e}")

    async def symbol_exists(self, symbol: str) -> bool:
        """Check if a symbol exists on the futures exchange."""
        try:
            symbol_clean = self._validate_symbol(symbol)
            logger.debug("Checking if futures symbol exists: %s", symbol_clean)
            info = await self.get_exchange_info()
            
            for s in info.get("symbols", []):
                if s.get("symbol") == symbol_clean:
                    return True
            return False
        except Exception as e:
            logger.exception("Error checking if futures symbol exists: %s", symbol)
            raise BinanceAPIError(f"Error checking if futures symbol exists {symbol}: {e}")


# Factory function for creating API instances
def create_binance_public_api(
    http_client: BinanceHTTPClient, 
    circuit_breaker: CircuitBreaker,
    futures: bool = False
) -> Union[BinanceSpotPublicAPI, BinanceFuturesPublicAPI]:
    """
    Factory function to create Binance Public API instances.
    
    Args:
        http_client: BinanceHTTPClient instance
        circuit_breaker: CircuitBreaker instance
        futures: If True, returns Futures API, else Spot API
        
    Returns:
        BinanceSpotPublicAPI or BinanceFuturesPublicAPI instance
    """
    if futures:
        return BinanceFuturesPublicAPI(http_client, circuit_breaker)
    else:
        return BinanceSpotPublicAPI(http_client, circuit_breaker)
