"""
utils/binance_api/binance_pb_spot.py
--------------------------------
Spot (public) endpoints wrapper.

- Sadece public spot market verilerine ait endpointleri içerir.
- Async / aiohttp tabanlı BinanceHTTPClient ile çalışır.
- Singleton pattern ile instance yönetimi.
- PEP8, type hints, docstrings ve logging içerir.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .binance_request import BinanceHTTPClient
from .binance_constants import (
    SPOT_PING_ENDPOINT,
    SPOT_TIME_ENDPOINT,
    SPOT_EXCHANGE_INFO_ENDPOINT,
    SPOT_ORDER_BOOK_ENDPOINT,
    SPOT_KLINE_ENDPOINT,
    SPOT_AGG_TRADE_ENDPOINT,
    SPOT_TICKER_24H_ENDPOINT,
    SPOT_TICKER_PRICE_ENDPOINT,
    SPOT_TICKER_BOOK_ENDPOINT,
    SPOT_AVG_PRICE_ENDPOINT,
    SPOT_TRADES_ENDPOINT,
    SPOT_HISTORICAL_TRADES_ENDPOINT,
    SPOT_TICKER_GENERIC_ENDPOINT,
    SPOT_UI_KLINES_ENDPOINT,

)
from .binance_types import ExchangeInfo, Kline, OrderBook, Ticker, Trade

logger = logging.getLogger(__name__)


class BinancePBSpot:
    """
    Public-Spot (PB) wrapper exposing commonly used public endpoints.

    Usage:
        client = BinancePBSpot.get_instance(http_client=BinanceHTTPClient(...))
        await client.ping()
    """

    _instance: Optional["BinancePBSpot"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None) -> None:
        """
        Create a wrapper instance. If http_client is not provided, an internal
        default BinanceHTTPClient() will be created (without API keys, since public).
        """
        self._http = http_client or BinanceHTTPClient()
        logger.debug("BinancePBSpot initialized")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinancePBSpot":
        """Return singleton instance (optionally supplying an http client)."""
        if cls._instance is None:
            cls._instance = cls(http_client=http_client)
        elif http_client is not None:
            # allow replacing underlying client if explicitly provided first time
            cls._instance._http = http_client
        return cls._instance

    # -------------------------
    # System / simple helpers
    # -------------------------
    async def ping(self) -> bool:
        """
        Ping endpoint - returns True if Binance responds.
        """
        logger.debug("Spot: ping")
        await self._http.get(SPOT_PING_ENDPOINT)
        return True



    # 1
    # -------------------------
    
    #adlandırma get_ticker_price_all = ticker_price → /api/v3/ticker/price
    async def ticker_price(self, symbol: Optional[str] = None) -> Any:
        """
        Current average price for symbol(s).
        Bu endpoint tek sembol veya tüm sembollerin anlık fiyatını döner.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Spot: ticker_price %s", symbol)
        data = await self._http.get(SPOT_TICKER_PRICE_ENDPOINT, params=params)
        return data

    async def ticker_24hr(self, symbol: Optional[str] = None) -> Any:
        """
        Eğer symbol verilmezse, tüm sembollerin 24h verisi gelir (liste).
        Eğer sembol verilirse, sadece o sembolün verisi gelir (dict).
        symbol.upper()  çünkü Binance sembolleri büyük harf kullanır.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Spot: ticker_24hr %s", symbol)
        data = await self._http.get(SPOT_TICKER_24H_ENDPOINT, params=params)
        return data

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """
        Get klines/candles.
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": int(limit),
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Spot: klines %s interval=%s start=%s end=%s limit=%s", symbol, interval, start_time, end_time, limit)
        data = await self._http.get(SPOT_KLINE_ENDPOINT, params=params)
        # Binance returns list[list]; caller may map to Kline TypedDict if desired
        return data  # type: ignore[return-value]

    async def avg_price(self, symbol: str) -> Dict[str, Any]:
        """
        Current average price for a symbol.
        GET /api/v3/avgPrice
        """
        params = {"symbol": symbol.upper()}
        logger.debug("Spot: avg_price %s", symbol)
        data = await self._http.get(SPOT_AVG_PRICE_ENDPOINT, params=params)
        return data

    async def ticker_book(self, symbol: Optional[str] = None) -> Any:
        """
        Best bid/ask for symbol(s).
        En iyi alış (bid) ve satış (ask) fiyatlarını verir.
        symbol verilmezse, tüm semboller için liste döner.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Spot: ticker_book %s", symbol)
        data = await self._http.get(SPOT_TICKER_BOOK_ENDPOINT, params=params)
        return data


    async def exchange_info(self, symbol: Optional[str] = None) -> ExchangeInfo:
        """
        Return exchangeInfo (optionally filtered by symbol).
        """
        params = {"symbol": symbol} if symbol else None
        logger.debug("Spot: exchange_info (%s)", symbol)
        data = await self._http.get(SPOT_EXCHANGE_INFO_ENDPOINT, params=params)
        # Type hinting to ExchangeInfo (caller should validate)
        return data  # type: ignore[return-value]


    async def ui_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """
        Get UI Klines (modified kline data for UI)
        GET /api/v3/uiKlines
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": int(limit),
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Spot: ui_klines %s interval=%s start=%s end=%s limit=%s", 
                    symbol, interval, start_time, end_time, limit)
        data = await self._http.get(SPOT_UI_KLINES_ENDPOINT, params=params)
        return data  # type: ignore[return-value]

    #
    # 2
    # -------------------------
    async def trades(self, symbol: str, limit: int = 500) -> List[Trade]:
        """
        Recent trades list.
        GET /api/v3/trades
        """
        params = {"symbol": symbol.upper(), "limit": int(limit)}
        logger.debug("Spot: trades %s limit=%s", symbol, limit)
        data = await self._http.get(SPOT_TRADES_ENDPOINT, params=params)
        return data  # type: ignore[return-value]

    async def agg_trades(
        self,
        symbol: str,
        from_id: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Trade]:
        """
        Aggregated trades list.
        """
        params: Dict[str, Any] = {"symbol": symbol.upper(), "limit": int(limit)}
        if from_id is not None:
            params["fromId"] = int(from_id)
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Spot: agg_trades %s params=%s", symbol, params)
        data = await self._http.get(SPOT_AGG_TRADE_ENDPOINT, params=params)
        return data  # type: ignore[return-value]

    #diğer adı get_depth = order_book
    async def order_book(self, symbol: str, limit: int = 100) -> OrderBook:
        """
        Get order book for a symbol.
        limit allowed: up to 1000 (Binance); default 100.
        """
        params = {"symbol": symbol.upper(), "limit": int(limit)}
        logger.debug("Spot: order_book %s limit=%s", symbol, limit)
        data = await self._http.get(SPOT_ORDER_BOOK_ENDPOINT, params=params)
        return data  # type: ignore[return-value]


    async def historical_trades(
        self, 
        symbol: str, 
        limit: int = 500, 
        from_id: Optional[int] = None
    ) -> List[Trade]:
        """
        Older trades (requires API key for higher limits).
        GET /api/v3/historicalTrades
        """
        params: Dict[str, Any] = {"symbol": symbol.upper(), "limit": int(limit)}
        if from_id is not None:
            params["fromId"] = int(from_id)
        logger.debug("Spot: historical_trades %s limit=%s from_id=%s", symbol, limit, from_id)
        data = await self._http.get(SPOT_HISTORICAL_TRADES_ENDPOINT, params=params)
        return data  # type: ignore[return-value]

    #
    # 3 - bu bölüm için gereklilik yok
    # -------------------------

    #
    # 4 - get_exchange_info(1 ile ortak)
    # -------------------------
    #ortak (1 ve 4) adlandırma get_ticker_price_all = ticker_price → /api/v3/ticker/pric

    async def server_time(self) -> int:
        """
        Get server time (ms).
        """
        logger.debug("Spot: server_time")
        data = await self._http.get(SPOT_TIME_ENDPOINT)
        ts = int(data.get("serverTime", 0))
        logger.debug("Spot server time: %s", ts)
        return ts
    
    
    async def symbol_ticker(
        self,
        symbol: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        type: Optional[str] = None,
        window_size: Optional[str] = None
    ) -> Any:
        """
        General ticker info from /api/v3/ticker endpoint.

        Args:
            symbol: Single symbol (e.g., "BTCUSDT")
            symbols: List of symbols (e.g., ["BTCUSDT", "ETHUSDT"])
            type: Specific ticker type (e.g., "FULL", "MINI", etc.)
            window_size: Rolling window size (e.g., "1h", "24h")

        Returns:
            API response as dict or list depending on parameters.
        """
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        if symbols:
            import json
            params["symbols"] = json.dumps([s.upper() for s in symbols])
        if type:
            params["type"] = type
        if window_size:
            params["windowSize"] = window_size

        logger.debug("Spot: symbol_ticker %s", params)
        data = await self._http.get(SPOT_TICKER_GENERIC_ENDPOINT, params=params)
        return data

    
    
        
    #

"""
sadece public spot market verilerine ait endpointleri içerir
kullanıcı kimlik doğrulaması gerektirmez.
genel piyasa bilgisi veren API'leri kapsar
Genel piyasa verilerini çekmek için kullanılır.
API anahtarı gerektirmeyen, yani public endpointleri çağıran bir yapı.
Async / aiohttp tabanlı HTTP client ile hızlı ve etkin veri alma imkanı sağlar.
Singleton pattern ile tek bir örnek üzerinden API çağrısı yapılmasını sağlar.
PEP8, type hints, docstrings ve logging ile temiz, okunabilir ve anlaşılır yapıdadır.

-1-
get_price	/api/v3/ticker/price	Tüm sembollerin güncel spot fiyatları	Temel fiyat takibi	🔹 Zorunlu	spot-public
get_ticker_24hr	/api/v3/ticker/24hr	24 saatlik fiyat değişim istatistikleri	Trend ve volatilite analizi	🔹 Zorunlu	spot-public
get_klines	/api/v3/klines	Kline/OHLCV verileri	Teknik analiz ve grafik oluşturma	🔹 Zorunlu	spot-public
get_avg_price	/api/v3/avgPrice	5 dakikalık ortalama fiyat	Anlık piyasa ortalaması	🔸 Opsiyonel	spot-public
get_ticker_book	/api/v3/ticker/bookTicker	En iyi alış-satış fiyatları	Spread takibi	🔸 Opsiyonel	spot-public
get_exchange_info	/api/v3/exchangeInfo	Sembol bilgileri ve kısıtlamalar	Sembol filtresi doğrulama	🔹 Zorunlu	spot-public
get_ui_klines	/api/v3/uiKlines	UI optimizeli kline verileri	Hızlandırılmış grafik verisi	🔸 Opsiyonel	spot-public

-2-
order_book = get_depth	/api/v3/depth	Emir defteri derinlik verisi	Likidite ve order flow analizi	🔹 Zorunlu	spot-public
get_trades	/api/v3/trades	Son işlemler	Piyasa hareketliliği	🔹 Zorunlu	spot-public
get_agg_trades	/api/v3/aggTrades	Toplu işlem verileri	Büyük işlem takibi	🔸 Opsiyonel	spot-public

-3-
yook

-4-
ticker_price = get_ticker_price_all	/api/v3/ticker/price	Tüm spot fiyatlar	Arbitraj fırsatları	🔹 Zorunlu	spot-public
get_symbol_ticker	/api/v3/ticker	Sembol bazlı ticker	Spread hesaplama	🔹 Zorunlu	spot-public
get_exchange_info	/api/v3/exchangeInfo	Sembol kısıtlamaları	Arbitraj uygunluk kontrolü	🔹 Zorunlu	spot-public
get_server_time	/api/v3/time	Sunucu zamanı	Zaman senkronizasyonu	🔹 Zorunlu	spot-public



"""