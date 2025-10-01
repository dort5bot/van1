# utils/binance/binance_a.py
"""
v5
Binance API Aggregator
--------------------------------------------------
Tüm Binance API endpoint'lerine tek bir noktadan erişim sağlar.

🔧 ÖZELLİKLER:
- Gelişmiş caching, retry, rate limiting mekanizmaları
- Singleton pattern + context manager desteği
- Tüm yeni private client'ler entegre (spot, futures, margin, staking, savings, mining, subaccount, userstream, asset)
- Kapsamlı hata yönetimi ve monitoring
- Parallel data fetching ve advanced analytics
# Öneri: Global instance'ı kaldırın, class-based kullanın

🔒 GÜVENLİK POLİTİKASI:
- API key'ler asla tam olarak loglanmaz
- Secret key'ler hiçbir zaman loglanmaz
- Sensitive data'lar sadece debug modunda kısmen gösterilir
- Production'da debug logging kapalı olmalıdır


Notlar:
- rotate_api_key ve _scrub_sensitive_data artık sınıf metodu/private method.
- Global asyncio.Lock()'lar modul import sırasında oluşturuluyor; pratikte acceptable,
  ancak long-running uygulamalarda lazy-initialize tercih edilebilir.
- retry dekoratörü, cache, circuit breaker entegrasyonu korunup hatalı yerler düzeltildi.
- Tip imzaları ve return tipleri belirginleştirildi.

Binance API Aggregator
----------------------
Tek noktadan Binance API erişimi:
- Global key (bot key) -> .env üzerinden (AppSettings, pydantic-settings)
- User key -> DB (apikey_utils) üzerinden
- Aggregator alt class yapısı:
    - BinanceMarketData
    - BinanceAccount
    - BinanceMonitoring
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

from pydantic_settings import BaseSettings
from pydantic import field_validator

# Local imports
from utils.apikey_manager import APIKeyManager  # DB’den user bazlı key

from .binance_request import BinanceHTTPClient
from .binance_circuit_breaker import CircuitBreaker
from .binance_exceptions import BinanceAPIError, BinanceCircuitBreakerError
from .binance_public import BinanceSpotPublicAPI, BinanceFuturesPublicAPI
from .binance_pr_spot import SpotClient
from .binance_pr_futures import FuturesClient

logger = logging.getLogger(__name__)


# =============================
# Config
# =============================

class AppSettings(BaseSettings):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    
    binance_api_key: Optional[str] = None  
    binance_api_secret: Optional[str] = None  
    max_requests_per_minute: Optional[int] = 1200  
    
    base_url: str = "https://api.binance.com"
    fapi_url: str = "https://fapi.binance.com"
    requests_per_second: int = 10
    cache_ttl: int = 30
    max_cache_size: int = 1000
    failure_threshold: int = 5
    reset_timeout: int = 60
    testnet: bool = False

    # Ek1
    debug: Optional[bool] = False
    enable_trading: Optional[bool] = False
    log_level: Optional[str] = "INFO"
    port: Optional[int] = 3000
    request_timeout: Optional[int] = 30
    telegram_name: Optional[str] = None
    telegram_token: Optional[str] = None
    use_webhook: Optional[bool] = False
    webhook_secret: Optional[str] = None
    webhook_path: Optional[str] = "/webhook"
    webapp_host: Optional[str] = "0.0.0.0"
    ngrok_url: Optional[str] = None
    webhook_host: Optional[str] = None
    half_open_timeout: Optional[int] = 15
    scan_symbols: Optional[str] = None
    glassnode_api_key: Optional[str] = None
    onchain_log_level: Optional[str] = "INFO"
    onchain_cache_enabled: Optional[bool] = True
    master_key: Optional[str] = None
    
    # Ek2
    admin_ids: Optional[str] = ""
    aiogram_redis_host: Optional[str] = "localhost"
    aiogram_redis_port: Optional[int] = 6379
    aiogram_redis_db: Optional[int] = 0
    use_redis_fsm: Optional[bool] = True
    fsm_storage_ttl: Optional[int] = 3600
    database_url: Optional[str] = ""
    use_database: Optional[bool] = False
    cache_ttl: Optional[int] = 300
    max_cache_size: Optional[int] = 1000
    causality_window: Optional[int] = 100
    causality_maxlag: Optional[int] = 2
    causality_cache_ttl: Optional[int] = 10
    causality_top_altcoins: Optional[str] = "BNBUSDT,ADAUSDT,SOLUSDT,XRPUSDT,DOTUSDT"
    scan_symbols: Optional[str] = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,TRXUSDT,CAKEUSDT,SUIUSDT,PEPEUSDT,ARPAUSDT,TURBOUSDT"
    enable_trading: Optional[bool] = False
    trading_strategy: Optional[str] = "conservative"
    max_leverage: Optional[int] = 3
    alert_price_change_percent: Optional[float] = 5.0
    enable_price_alerts: Optional[bool] = True
    alert_cooldown: Optional[int] = 300

    @field_validator("requests_per_second")
    @classmethod
    def validate_rps(cls, v: int) -> int:
        if v > 50:
            raise ValueError("Rate limit exceeds allowed threshold")
        return v

    class Config:
        env_file = ".env"
        env_prefix = ""  # Eğer `BINANCE_` değilse burayı boş bırakman gerek
        # extra = "allow"  # Eğer sadece test için eklemek istersen bu satırı geçici kullan




# =============================
# Alt Classlar
# =============================
class BinanceMarketData:
    """Market data metodları (public endpoints)."""

    def __init__(self, spot: BinanceSpotPublicAPI, futures: BinanceFuturesPublicAPI):
        self.spot = spot
        self.futures = futures

    async def get_price(self, symbol: str, futures: bool = False) -> Optional[float]:
        try:
            if futures:
                ticker = await self.futures.get_futures_24hr_ticker(symbol)
                return float(ticker.get("lastPrice", 0))
            else:
                price_data = await self.spot.get_symbol_price(symbol)
                return float(price_data.get("price", 0))
        except Exception as e:
            logger.error(f"Price fetch failed: {e}")
            return None

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 500, futures: bool = False):
        if futures:
            return await self.futures.get_futures_klines(symbol, interval, limit)
        return await self.spot.get_klines(symbol, interval, limit)

    async def get_order_book(self, symbol: str, limit: int = 100, futures: bool = False):
        if futures:
            return await self.futures.get_futures_order_book(symbol, limit)
        return await self.spot.get_order_book(symbol, limit)


class BinanceAccount:
    """Account metodları (private endpoints)."""

    def __init__(self, spot: SpotClient, futures: FuturesClient):
        self.spot = spot
        self.futures = futures

    async def get_account_info(self, futures: bool = False):
        if futures:
            return await self.futures.get_account_info()
        return await self.spot.get_account_info()

    async def get_balance(self, asset: Optional[str] = None, futures: bool = False):
        if futures:
            balances = await self.futures.get_balance()
            if asset:
                return next((b for b in balances if b.get("asset") == asset.upper()), {})
            return balances
        return await self.spot.get_account_balance(asset)


class BinanceMonitoring:
    """Monitoring & Health."""

    def __init__(self, spot: BinanceSpotPublicAPI, breaker: CircuitBreaker):
        self.spot = spot
        self.breaker = breaker

    async def ping(self) -> bool:
        try:
            result = await self.spot.ping()
            return result == {}
        except Exception:
            return False

    async def system_health(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "circuit_breaker": self.breaker.state,
            "ping": await self.ping(),
        }


# =============================
# Main Aggregator
# =============================
class BinanceAPI:
    """Main Binance API aggregator."""

    def __init__(self, api_key: Optional[str], api_secret: Optional[str], settings: AppSettings):
        http = BinanceHTTPClient(
            api_key=api_key,
            secret_key=api_secret,
            base_url=settings.base_url,
            fapi_url=settings.fapi_url,
            config={"requests_per_second": settings.requests_per_second},
        )
        breaker = CircuitBreaker(failure_threshold=settings.failure_threshold, reset_timeout=settings.reset_timeout)

        # public
        spot_pub = BinanceSpotPublicAPI(http, breaker)
        fut_pub = BinanceFuturesPublicAPI(http, breaker)

        # private
        spot_pr = SpotClient(http, breaker)
        fut_pr = FuturesClient(http, breaker)

        # submodules
        self.market = BinanceMarketData(spot_pub, fut_pub)
        self.account = BinanceAccount(spot_pr, fut_pr)
        self.monitoring = BinanceMonitoring(spot_pub, breaker)

        self.http = http
        self.breaker = breaker

    @classmethod
    async def create(cls, user_id: Optional[int] = None) -> "BinanceAPI":
        """user_id verilirse DB’den key alır, yoksa .env’den bot key kullanır."""
        settings = AppSettings()
        api_key, api_secret = settings.api_key, settings.api_secret

        if user_id:
            db = APIKeyManager.get_instance()
            user_keys = await db.get_apikey(user_id)
            if user_keys:
                api_key, api_secret = user_keys
        
        return cls(api_key, api_secret, settings)


# =============================
# Global instance management
# =============================
_instance: Optional[BinanceAPI] = None
_instance_lock = asyncio.Lock()


async def get_or_create_binance_api(user_id: Optional[int] = None) -> BinanceAPI:
    global _instance
    async with _instance_lock:
        if _instance is None:
            _instance = await BinanceAPI.create(user_id=user_id)
        return _instance


async def close_binance_api():
    global _instance
    if _instance:
        await _instance.http.close()
        _instance = None
