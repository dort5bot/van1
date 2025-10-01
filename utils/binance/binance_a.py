# utils/binance/binance_a.py
"""
v8
Aggregator for Binance API (Public + Private).

+ Instance-Based yaklaşıma dönüştürüldü, public eklme kolaylığı
Aggregator for Binance API (Public + Private).
- Async / await
- Aiogram 3.x Router uyumlu
- Singleton pattern
- PEP8 + logging + monitoring
-+ Instance-based dependency injection
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable

# Public imports
from . import binance_pb_spot, binance_pb_futures, binance_pb_system, binance_pb_index

# Private imports
from .binance_pr_spot import SpotClient
from .binance_pr_futures import FuturesClient
from .binance_pr_margin import MarginClient
from .binance_pr_asset import AssetClient
from .binance_pr_savings import SavingsClient
from .binance_pr_staking import StakingClient
from .binance_pr_mining import MiningClient
from .binance_pr_subaccount import SubAccountClient
from .binance_pr_userstream import UserStreamClient
from .binance_pr_base import BinancePrivateBase

# Common imports
from .binance_request import BinanceHTTPClient
from .binance_circuit_breaker import CircuitBreaker
from ..apikey_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AggregatorSettings:
    """
    Common configuration for Binance API aggregator.
    Dependency Injection ve konfigürasyon yönetimi için merkezi settings.
    """
    _instance: Optional["AggregatorSettings"] = None

    def __init__(self, default_user: Optional[int] = None, http_client: Optional[BinanceHTTPClient] = None):
        self.default_user = default_user
        self.http_client = http_client or BinanceHTTPClient()
        self.apikey_db = APIKeyManager.get_instance()
        self.circuit_breaker = CircuitBreaker()
        logger.debug("AggregatorSettings initialized with custom HTTP client: %s", http_client is not None)

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "AggregatorSettings":
        """Return singleton instance with optional HTTP client configuration."""
        if cls._instance is None:
            cls._instance = AggregatorSettings(http_client=http_client)
        elif http_client is not None:
            # Runtime'da HTTP client güncelleme
            cls._instance.http_client = http_client
            logger.info("AggregatorSettings HTTP client updated")
        return cls._instance

    async def build_private_client(self, user_id: Optional[int] = None) -> BinancePrivateBase:
        """Factory: build a private API base client with user's keys."""
        creds = await self.apikey_db.get_apikey(user_id or self.default_user)
        if not creds:
            raise ValueError("No API key found for user")
        api_key, api_secret = creds
        # Private işlemler için yeni HTTP client oluştur (API key'li)
        http_client = BinanceHTTPClient(api_key=api_key, secret_key=api_secret)
        return BinancePrivateBase(http_client, self.circuit_breaker)


# ===============================
# PUBLIC API - INSTANCE BASED
# ===============================
class PublicApi:
    """
    Group Binance Public API calls with instance-based dependency injection.
    Bu yapı test edilebilirlik ve esneklik sağlar.
    """

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
        """
        Initialize Public API with optional HTTP client.
        
        Args:
            http_client: Özelleştirilmiş HTTP client (timeout, retry, vs.)
        """
        self.http_client = http_client
        self.spot = self.PublicSpot(http_client)
        self.futures = self.PublicFutures(http_client)
        self.system = self.PublicSystem(http_client)
        self.index = self.PublicIndex(http_client)
        logger.debug("PublicApi initialized with %d custom HTTP clients", 
                   1 if http_client else 0)

    class PublicSpot:
        """Instance-based Public Spot API with comprehensive endpoint coverage."""

        def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
            """
            Spot API client'ını başlat.
            
            Args:
                http_client: Mevcut HTTP client veya yeni oluşturulacak
            """
            self.spot_client = binance_pb_spot.BinancePBSpot.get_instance(http_client)
            self._endpoint_coverage = self._init_endpoint_coverage()
            logger.debug("PublicSpot instance created")

        def _init_endpoint_coverage(self) -> Dict[str, bool]:
            """
            Endpoint implementasyon takibi için coverage map.
            Monitoring ve health check için kullanılır.
            """
            return {
                'ping': True,
                'server_time': True,
                'exchange_info': True,
                'order_book': True,
                'klines': True,
                'agg_trades': True,
                'ticker_24hr': True,
                'ticker_price': True,
                'ticker_book': True,
            }

        async def ping(self) -> bool:
            """Test connectivity to Binance API."""
            return await self.spot_client.ping()

        async def server_time(self) -> int:
            """Get server time in milliseconds."""
            return await self.spot_client.server_time()

        async def exchange_info(self, symbol: Optional[str] = None) -> Any:
            """
            Get exchange information and trading rules.
            
            Args:
                symbol: Optional symbol filter
            """
            return await self.spot_client.exchange_info(symbol)

        async def order_book(self, symbol: str, limit: int = 100) -> Any:
            """
            Get order book depth.
            
            Args:
                symbol: Trading pair symbol
                limit: Depth limit (default: 100, max: 1000)
            """
            return await self.spot_client.order_book(symbol, limit)

        async def get_klines(self, symbol: str, interval: str, limit: int = 500,
                           start_time: Optional[int] = None,
                           end_time: Optional[int] = None) -> Any:
            """
            Get Kline/candlestick data.
            
            Args:
                symbol: Trading pair symbol
                interval: Kline interval (1m, 5m, 1h, etc.)
                limit: Number of klines to return
                start_time: Start time in milliseconds
                end_time: End time in milliseconds
            """
            return await self.spot_client.klines(
                symbol=symbol, interval=interval, limit=limit,
                start_time=start_time, end_time=end_time
            )

        async def agg_trades(self, symbol: str, from_id: Optional[int] = None,
                           start_time: Optional[int] = None,
                           end_time: Optional[int] = None,
                           limit: int = 500) -> Any:
            """
            Get compressed/aggregated trades list.
            
            Args:
                symbol: Trading pair symbol
                from_id: ID to get aggregate trades from
                start_time: Start time in milliseconds
                end_time: End time in milliseconds
                limit: Number of trades to return
            """
            return await self.spot_client.agg_trades(
                symbol=symbol, from_id=from_id, start_time=start_time,
                end_time=end_time, limit=limit
            )

        async def ticker_24hr(self, symbol: Optional[str] = None) -> Any:
            """
            24hr ticker price change statistics.
            
            Args:
                symbol: Optional symbol filter (None returns all symbols)
            """
            return await self.spot_client.ticker_24hr(symbol)

        async def get_ticker_price(self, symbol: Optional[str] = None) -> Dict[str, Any]:
            """
            Get current price for symbol(s).
            
            Args:
                symbol: Optional symbol filter (None returns all symbols)
            """
            return await self.spot_client.ticker_price(symbol)

        async def ticker_book(self, symbol: Optional[str] = None) -> Any:
            """
            Get best bid/ask prices (symbol ticker).
            
            Args:
                symbol: Optional symbol filter (None returns all symbols)
            """
            return await self.spot_client.ticker_book(symbol)

        # === MONITORING ve GELİŞİM TAKİP ===
        def get_coverage_report(self) -> Dict[str, Any]:
            """
            Endpoint implementasyon raporu.
            Health check ve monitoring için kullanılır.
            """
            total = len(self._endpoint_coverage)
            implemented = sum(self._endpoint_coverage.values())
            return {
                'total_endpoints': total,
                'implemented': implemented,
                'coverage_percentage': round((implemented / total) * 100, 2),
                'details': self._endpoint_coverage,
                'status': 'complete' if implemented == total else 'partial'
            }

        def add_custom_endpoint(self, endpoint_name: str, handler: Callable):
            """
            Runtime'da yeni endpoint ekleme imkanı.
            
            Args:
                endpoint_name: Yeni endpoint method adı
                handler: Callable function/method
            """
            setattr(self, endpoint_name, handler)
            self._endpoint_coverage[endpoint_name] = True
            logger.info(f"✅ Custom endpoint added: {endpoint_name}")

    class PublicFutures:
        """Instance-based Public Futures API."""

        def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
            self.http_client = http_client
            logger.debug("PublicFutures instance created")

        async def get_futures_klines(self, symbol: str, interval: str, limit: int = 500) -> Any:
            """Get futures klines data."""
            return await binance_pb_futures.get_klines(symbol=symbol, interval=interval, limit=limit)

        async def get_mark_price(self, symbol: str) -> Dict[str, Any]:
            """Get futures mark price."""
            return await binance_pb_futures.get_mark_price(symbol)

    class PublicSystem:
        """Instance-based Public System API."""

        def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
            self.http_client = http_client
            logger.debug("PublicSystem instance created")

        async def ping(self) -> bool:
            """Test API connectivity."""
            return await binance_pb_system.ping()

        async def get_exchange_info(self) -> Dict[str, Any]:
            """Get exchange information."""
            return await binance_pb_system.get_exchange_info()

    class PublicIndex:
        """Instance-based Public Index API."""

        def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
            self.http_client = http_client
            logger.debug("PublicIndex instance created")

        async def get_index_price(self, symbol: str) -> Dict[str, Any]:
            """Get index price for symbol."""
            return await binance_pb_index.get_index_price(symbol)


# ===============================
# PRIVATE API - ORİJİNAL YAPI KORUNDU
# ===============================
class PrivateApi:
    """
    Group Binance Private API calls (requires API Key).
    Private API'ler zaten instance-based olduğu için yapı korundu.
    """

    class PrivateSpot:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> SpotClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return SpotClient(base.http, base.circuit_breaker)

    class PrivateFutures:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> FuturesClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return FuturesClient(base.http, base.circuit_breaker)

    class PrivateMargin:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> MarginClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return MarginClient(base.http, base.circuit_breaker)

    class PrivateAsset:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> AssetClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return AssetClient(base.http, base.circuit_breaker)

    class PrivateSavings:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> SavingsClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return SavingsClient(base.http, base.circuit_breaker)

    class PrivateStaking:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> StakingClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return StakingClient(base.http, base.circuit_breaker)

    class PrivateMining:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> MiningClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return MiningClient(base.http, base.circuit_breaker)

    class PrivateSubAccount:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> SubAccountClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return SubAccountClient(base.http, base.circuit_breaker)

    class PrivateUserStream:
        @staticmethod
        async def client(user_id: Optional[int] = None) -> UserStreamClient:
            settings = AggregatorSettings.get_instance()
            base = await settings.build_private_client(user_id)
            return UserStreamClient(base.http, base.circuit_breaker)


# ===============================
# MAIN AGGREGATOR - GELİŞTİRİLMİŞ
# ===============================
class BinanceAggregator:
    """
    Unified Binance Aggregator for Public + Private APIs (async singleton).
    Instance-based dependency injection ile geliştirilmiş versiyon.
    """

    _instance: Optional["BinanceAggregator"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
        """
        Initialize aggregator with optional HTTP client.
        
        Args:
            http_client: Özelleştirilmiş HTTP client (timeout, retry, proxy, vs.)
        """
        self._http_client = http_client
        self.public = PublicApi(http_client)
        self.private = PrivateApi()
        self._version = "2.0.0"
        self._init_time = datetime.now()
        logger.info("✅ BinanceAggregator v%s initialized with instance-based architecture", self._version)

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinanceAggregator":
        """
        Get singleton instance with configurable HTTP client.
        
        Args:
            http_client: Özelleştirilmiş HTTP client
            
        Returns:
            BinanceAggregator instance
        """
        if cls._instance is None:
            cls._instance = BinanceAggregator(http_client)
            logger.info("BinanceAggregator singleton instance created")
        elif http_client is not None and cls._instance._http_client != http_client:
            # Runtime'da HTTP client güncelleme
            cls._instance = BinanceAggregator(http_client)
            logger.info("BinanceAggregator HTTP client updated and instance recreated")
        return cls._instance

    # === MONITORING ve HEALTH CHECK ===
    async def health_check(self) -> Dict[str, Any]:
        """
        Comprehensive health check for all API services.
        Tüm servislerin durumunu kontrol eder ve detaylı rapor döndürür.
        """
        health_report = {
            'status': 'healthy',
            'version': self._version,
            'timestamp': datetime.now().isoformat(),
            'uptime': str(datetime.now() - self._init_time),
            'architecture': 'instance-based',
            'services': {}
        }

        try:
            # Public Spot API health check
            ping_ok = await self.public.spot.ping()
            coverage_report = self.public.spot.get_coverage_report()
            
            health_report['services']['public_spot'] = {
                'status': 'healthy' if ping_ok else 'unhealthy',
                'ping': ping_ok,
                'coverage': coverage_report,
                'endpoints_implemented': coverage_report['implemented'],
                'coverage_percentage': coverage_report['coverage_percentage']
            }
            
            if not ping_ok:
                health_report['status'] = 'degraded'
                
        except Exception as e:
            health_report['services']['public_spot'] = {
                'status': 'error', 
                'error': str(e)
            }
            health_report['status'] = 'degraded'
            logger.error("Public Spot health check failed: %s", e)

        # Diğer servisler için health check'ler buraya eklenebilir
        health_report['services']['public_futures'] = {'status': 'not_checked'}
        health_report['services']['private_apis'] = {'status': 'requires_auth'}

        return health_report

    def get_stats(self) -> Dict[str, Any]:
        """
        Get aggregator statistics and configuration.
        Monitoring ve debugging için kullanışlı metrikler sağlar.
        """
        return {
            'version': self._version,
            'initialized': self._init_time.isoformat(),
            'uptime_seconds': (datetime.now() - self._init_time).total_seconds(),
            'http_client_configured': self._http_client is not None,
            'public_apis': {
                'spot': self.public.spot.get_coverage_report(),
                'futures': 'available',
                'system': 'available',
                'index': 'available'
            },
            'private_apis': {
                'spot': 'available',
                'futures': 'available',
                'margin': 'available',
                'asset': 'available'
            }
        }

    def get_public_spot_coverage(self) -> Dict[str, Any]:
        """
        Public Spot API endpoint coverage report.
        Gelişim takibi ve dokümantasyon için kullanılır.
        """
        return self.public.spot.get_coverage_report()


# ===============================
# KULLANIM ÖRNEKLERİ - TEST ve DEBUG
# ===============================
async def debug_aggregator():
    """Test ve debug için yardımcı fonksiyon"""
    aggregator = BinanceAggregator.get_instance()
    
    # Health check
    health = await aggregator.health_check()
    print("Health Check:", health)
    
    # Coverage report
    coverage = aggregator.get_public_spot_coverage()
    print("Coverage Report:", coverage)
    
    # Basic functionality test
    try:
        ping_result = await aggregator.public.spot.ping()
        print("Ping Result:", ping_result)
        
        time_result = await aggregator.public.spot.server_time()
        print("Server Time:", time_result)
        
    except Exception as e:
        print("Test failed:", e)


if __name__ == "__main__":
    import asyncio
    asyncio.run(debug_aggregator())