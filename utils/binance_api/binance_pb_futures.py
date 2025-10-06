"""
utils/binance_api/binance_pb_futures.py
----------------------------------
Futures (public) endpoints wrapper.

- Futures public endpoints (market data) için metodlar içerir.
- Async / aiohttp tabanlı BinanceHTTPClient ile çalışır.
- Singleton pattern, PEP8, type hints, docstrings ve logging içerir.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .binance_request import BinanceHTTPClient
from .binance_constants import (
    FUTURES_PING_ENDPOINT,
    FUTURES_TIME_ENDPOINT,
    FUTURES_EXCHANGE_INFO_ENDPOINT,
    FUTURES_ORDER_BOOK_ENDPOINT,
    FUTURES_KLINE_ENDPOINT,
    FUTURES_PING_ENDPOINT,
    FUTURES_PREMIUM_INDEX_ENDPOINT,
    FUTURES_CONTINUOUS_KLINES_ENDPOINT,
    FUTURES_INDEX_PRICE_KLINES_ENDPOINT,
    FUTURES_MARK_PRICE_KLINES_ENDPOINT,
    FUTURES_FUNDING_RATE_ENDPOINT,
    FUTURES_TICKER_24HR_ENDPOINT,
    FUTURES_TICKER_PRICE_ENDPOINT,
    FUTURES_TICKER_BOOK_ENDPOINT,
    FUTURES_OPEN_INTEREST_ENDPOINT,
    FUTURES_OPEN_INTEREST_HIST_ENDPOINT,
    FUTURES_TOP_LONG_SHORT_POSITION_RATIO_ENDPOINT,
    FUTURES_TOP_LONG_SHORT_ACCOUNT_RATIO_ENDPOINT,
    FUTURES_GLOBAL_LONG_SHORT_ACCOUNT_RATIO_ENDPOINT,
    FUTURES_TAKER_BUY_SELL_VOL_ENDPOINT,
    FUTURES_BASIS_ENDPOINT,
)
from .binance_types import ExchangeInfo, Kline, OrderBook

logger = logging.getLogger(__name__)


class BinancePBFutures:
    """
    Public-Futures (PB) wrapper exposing commonly used futures public endpoints.

    Usage:
        fut = BinancePBFutures.get_instance()
        await fut.ping()
    """

    _instance: Optional["BinancePBFutures"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None) -> None:
        # futures flag will be passed to underlying HTTP client methods
        self._http = http_client or BinanceHTTPClient()
        logger.debug("BinancePBFutures initialized")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinancePBFutures":
        """Return singleton instance."""
        if cls._instance is None:
            cls._instance = cls(http_client=http_client)
        elif http_client is not None:
            cls._instance._http = http_client
        return cls._instance

    # -------------------------
    # System / simple helpers
    # -------------------------
    async def ping(self) -> bool:
        """Ping futures endpoint."""
        logger.debug("Futures: ping")
        await self._http.get(FUTURES_PING_ENDPOINT, futures=True)
        return True

    async def server_time(self) -> int:
        """Get futures server time (ms)."""
        logger.debug("Futures: server_time")
        data = await self._http.get(FUTURES_TIME_ENDPOINT, futures=True)
        return int(data.get("serverTime", 0))

    #4
    async def exchange_info(self, symbol: Optional[str] = None) -> ExchangeInfo:
        """
        Futures exchange info.
        """
        params = {"symbol": symbol} if symbol else None
        logger.debug("Futures: exchange_info %s", symbol)
        data = await self._http.get(FUTURES_EXCHANGE_INFO_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    #1
    async def order_book(self, symbol: str, limit: int = 100) -> OrderBook:
        """Get futures order book."""
        params = {"symbol": symbol.upper(), "limit": int(limit)}
        logger.debug("Futures: order_book %s limit=%s", symbol, limit)
        data = await self._http.get(FUTURES_ORDER_BOOK_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    #1
    async def klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """Get futures klines."""
        params: Dict[str, Any] = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Futures: klines %s interval=%s start=%s end=%s limit=%s", symbol, interval, start_time, end_time, limit)
        data = await self._http.get(FUTURES_KLINE_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    # 1
    # -------------------------
    async def continuous_klines(
        self,
        pair: str,
        contract_type: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """
        Get continuous contract klines.
        GET /fapi/v1/continuousKlines
        """
        params: Dict[str, Any] = {
            "pair": pair.upper(),
            "contractType": contract_type,
            "interval": interval,
            "limit": int(limit),
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Futures: continuous_klines %s contract_type=%s interval=%s", 
                    pair, contract_type, interval)
        data = await self._http.get(FUTURES_CONTINUOUS_KLINES_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def index_price_klines(
        self,
        pair: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """
        Get index price klines.
        GET /fapi/v1/indexPriceKlines
        """
        params: Dict[str, Any] = {
            "pair": pair.upper(),
            "interval": interval,
            "limit": int(limit),
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        logger.debug("Futures: index_price_klines %s interval=%s", pair, interval)
        data = await self._http.get(FUTURES_INDEX_PRICE_KLINES_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def mark_price_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
    ) -> List[Kline]:
        """
        Get mark price klines.
        GET /fapi/v1/markPriceKlines
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
        logger.debug("Futures: mark_price_klines %s interval=%s", symbol, interval)
        data = await self._http.get(FUTURES_MARK_PRICE_KLINES_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def funding_rate(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get current funding rate.
        GET /fapi/v1/fundingRate
        """
        params: Dict[str, Any] = {"limit": int(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: funding_rate %s", symbol)
        data = await self._http.get(FUTURES_FUNDING_RATE_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    #1
    async def ticker_24hr(
        self, 
        symbol: Optional[str] = None
    ) -> Any:
        """
        24hr ticker price change statistics.
        GET /fapi/v1/ticker/24hr
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Futures: ticker_24hr %s", symbol)
        data = await self._http.get(FUTURES_TICKER_24HR_ENDPOINT, params=params, futures=True)
        return data

    #4
    async def ticker_price(
        self, 
        symbol: Optional[str] = None
    ) -> Any:
        """
        Symbol price ticker.
        GET /fapi/v1/ticker/price
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Futures: ticker_price %s", symbol)
        data = await self._http.get(FUTURES_TICKER_PRICE_ENDPOINT, params=params, futures=True)
        return data

    async def ticker_book(
        self, 
        symbol: Optional[str] = None
    ) -> Any:
        """
        Symbol order book ticker.
        GET /fapi/v1/ticker/bookTicker
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Futures: ticker_book %s", symbol)
        data = await self._http.get(FUTURES_TICKER_BOOK_ENDPOINT, params=params, futures=True)
        return data

    #1
    async def open_interest(
        self, 
        symbol: str
    ) -> Dict[str, Any]:
        """
        Get present open interest of a specific symbol.
        GET /fapi/v1/openInterest
        """
        params = {"symbol": symbol.upper()}
        logger.debug("Futures: open_interest %s", symbol)
        data = await self._http.get(FUTURES_OPEN_INTEREST_ENDPOINT, params=params, futures=True)
        return data

    async def open_interest_hist(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Open Interest History (for indicators)
        GET /futures/data/openInterestHist
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": int(limit),
        }
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: open_interest_hist %s period=%s", symbol, period)
        data = await self._http.get(FUTURES_OPEN_INTEREST_HIST_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def top_long_short_position_ratio(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Top Trader Long/Short Ratio (Positions)
        GET /futures/data/topLongShortPositionRatio
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": int(limit),
        }
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: top_long_short_position_ratio %s period=%s", symbol, period)
        data = await self._http.get(FUTURES_TOP_LONG_SHORT_POSITION_RATIO_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def top_long_short_account_ratio(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Top Trader Long/Short Ratio (Accounts)
        GET /futures/data/topLongShortAccountRatio
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": int(limit),
        }
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: top_long_short_account_ratio %s period=%s", symbol, period)
        data = await self._http.get(FUTURES_TOP_LONG_SHORT_ACCOUNT_RATIO_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def long_short_ratio(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Long/Short Ratio
        GET /futures/data/globalLongShortAccountRatio
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": int(limit),
        }
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: long_short_ratio %s period=%s", symbol, period)
        data = await self._http.get(FUTURES_GLOBAL_LONG_SHORT_ACCOUNT_RATIO_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def taker_buy_sell_volume(
        self,
        symbol: str,
        period: str,
        limit: int = 30,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Taker Buy/Sell Volume
        GET /futures/data/takerBuySellVol
        """
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": int(limit),
        }
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: taker_buy_sell_volume %s period=%s", symbol, period)
        data = await self._http.get(FUTURES_TAKER_BUY_SELL_VOL_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]

    async def basis(
        self,
        pair: str,
        contract_type: str,
        period: str,
        limit: int = 30,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Basis
        GET /futures/data/basis
        """
        params: Dict[str, Any] = {
            "pair": pair.upper(),
            "contractType": contract_type,
            "period": period,
            "limit": int(limit),
        }
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)
        logger.debug("Futures: basis %s contract_type=%s period=%s", pair, contract_type, period)
        data = await self._http.get(FUTURES_BASIS_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]
 
    #4
    async def premium_index(
        self, 
        symbol: Optional[str] = None
    ) -> Any:
        """
        Get Mark Price and Funding Rate (Premium Index)
        GET /fapi/v1/premiumIndex
        
        - If symbol is provided, returns data for that symbol.
        - If not, returns for all symbols.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        logger.debug("Futures: premium_index %s", symbol)
        data = await self._http.get(FUTURES_PREMIUM_INDEX_ENDPOINT, params=params, futures=True)
        return data
    
    
    # # 📕 BÖLÜM 5: Likidasyon Verileri
    #5 - FUTURES_LIQUIDATION_ORDERS_ENDPOINT = "/fapi/v1/liquidationOrders"
    async def liquidation_orders(
        self,
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get force liquidation orders.
        GET /fapi/v1/liquidationOrders
        """
        params: Dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol.upper()
        logger.debug("Futures: liquidation_orders %s", symbol)
        data = await self._http.get(FUTURES_LIQUIDATION_ORDERS_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]
    

    async def force_orders(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get force orders.
        GET /fapi/v1/forceOrders

        Args:
            symbol (Optional[str]): Symbol to filter by.
            start_time (Optional[int]): Start timestamp (ms).
            end_time (Optional[int]): End timestamp (ms).
            limit (int): Number of results, default 50.

        Returns:
            List of force orders.
        """
        params: Dict[str, Any] = {"limit": int(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)

        logger.debug("Futures: force_orders %s", symbol)
        data = await self._http.get(FUTURES_FORCE_ORDERS_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]


    async def all_force_orders(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get all force orders.
        GET /fapi/v1/allForceOrders

        Args:
            symbol (Optional[str]): Symbol to filter by.
            start_time (Optional[int]): Start timestamp (ms).
            end_time (Optional[int]): End timestamp (ms).
            limit (int): Number of results, default 50.

        Returns:
            List of all force orders.
        """
        params: Dict[str, Any] = {"limit": int(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        if start_time:
            params["startTime"] = int(start_time)
        if end_time:
            params["endTime"] = int(end_time)

        logger.debug("Futures: all_force_orders %s", symbol)
        data = await self._http.get(FUTURES_ALL_FORCE_ORDERS_ENDPOINT, params=params, futures=True)
        return data  # type: ignore[return-value]


    async def leverage_bracket(
        self,
        symbol: Optional[str] = None
    ) -> Any:
        """
        Get leverage bracket.
        GET /fapi/v1/leverageBracket

        Args:
            symbol (Optional[str]): Symbol to filter by.

        Returns:
            Leverage bracket info.
        """
        params = {"symbol": symbol.upper()} if symbol else None

        logger.debug("Futures: leverage_bracket %s", symbol)
        data = await self._http.get(FUTURES_LEVERAGE_BRACKET_ENDPOINT, params=params, futures=True)
        return data

    
    #



 
 
 
"""
Public Future Endpointleri: Evet, sınıf futures market verilerini sağlayan tamamen public endpointler içeriyor.
Görevleri: Piyasa verisi sağlamak (emir defteri, mumlar, fiyatlar), piyasa istatistikleri (open interest, funding rate), trader davranış analizleri (long/short oranları) gibi.
İç Kullanım: Bu veri metotları piyasa durumu izleme, grafik/chart oluşturma, trading stratejileri geliştirme, risk ve likidite analizi gibi uygulamalarda kullanılabilir.
Tüm endpoint URL’lerini binance_constants.py içinde tanımlı oradan import edildi.
✅ Örnek Olarak Dosyada Bulunanlar:

/fapi/v1/ping
/fapi/v1/time
/fapi/v1/exchangeInfo
/fapi/v1/depth (order_book)
/fapi/v1/klines
/fapi/v1/markPriceKlines
/fapi/v1/fundingRate
/fapi/v1/ticker/24hr,
/fapi/v1/ticker/price,
/fapi/v1/ticker/bookTicker
/fapi/v1/openInterest
/futures/data/openInterestHist
/futures/data/topLongShortPositionRatio
/futures/data/globalLongShortAccountRatio
/fapi/v1/liquidationOrders


"""