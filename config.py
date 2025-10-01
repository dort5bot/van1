"""bot/config.py - Aiogram 3.x uyumlu optimal config yönetimi

Binance ve Aiogram için yapılandırma sınıfı. Default değerler ile gelir,
.env dosyasındaki değerlerle override edilir.
"""

import os
import logging
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
from dotenv import load_dotenv
from enum import Enum

# Environment variables'ı yükle
load_dotenv()

# Logging yapılandırması
logger = logging.getLogger(__name__)
logger.setLevel(logging.getLevelName(os.getenv("LOG_LEVEL", "INFO")))

# Global cache instance
_CONFIG_INSTANCE: Optional["BotConfig"] = None




#=====================================================
#Bİnance config işlemleri class yada alt class şeklinde
#binance ile ilgili tüm configler buraya eklenecek
#=====================================================
"""Binance API Aggregator - Organized Config Structure"""


class BinanceConfig:
    """Main Binance configuration with nested classes"""
    
    class Public:
        """Public API configuration"""
        
        class Spot:
            """Spot Public API settings"""
            enabled: bool = True
            timeout: int = 10
            retry_attempts: int = 3
            requests_per_second: int = 10
            cache_ttl: int = 60  # Cache duration in seconds
            
            # Endpoint specific limits
            depth_limit: int = 100
            trades_limit: int = 500
            klines_limit: int = 500
            
        class Futures:
            """Futures Public API settings"""
            enabled: bool = True
            timeout: int = 10
            retry_attempts: int = 3
            requests_per_second: int = 10
            cache_ttl: int = 60
            
            # Futures specific
            depth_limit: int = 100
            trades_limit: int = 500
            klines_limit: int = 500
            funding_rate_limit: int = 100
            open_interest_limit: int = 30
    
    class Private:
        """Private API configuration"""
        
        class Spot:
            """Spot Private API settings"""
            enabled: bool = True
            timeout: int = 10
            orders_per_second: int = 10
            max_orders_per_batch: int = 5
            
        class Futures:
            """Futures Private API settings"""
            enabled: bool = True
            timeout: int = 10
            orders_per_second: int = 10
            max_orders_per_batch: int = 5
            leverage_validation: bool = True
    
    class CircuitBreaker:
        """Circuit breaker configuration"""
        failure_threshold: int = 5
        reset_timeout: int = 60
        half_open_timeout: int = 30
        max_failures_before_alert: int = 10
    
    class URLs:
        """API endpoint URLs"""
        base_url: str = "https://api.binance.com"
        fapi_url: str = "https://fapi.binance.com"
        wss_url: str = "wss://stream.binance.com:9443"
        fapi_wss_url: str = "wss://fstream.binance.com"
    
    class Security:
        """Security and rate limiting"""
        api_key: Optional[str] = None
        api_secret: Optional[str] = None
        requests_per_second: int = 10
        max_connections: int = 100
        enable_rate_limiting: bool = True
        
    class Logging:
        """Logging configuration"""
        level: str = "INFO"
        format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        log_requests: bool = True
        log_errors: bool = True
        
    def __init__(self, **kwargs):
        """Initialize config with optional overrides"""
        # Apply kwargs to override defaults
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                # Try to set nested attributes
                self._set_nested_attribute(key, value)
    
    def _set_nested_attribute(self, key: str, value: Any):
        """Set nested class attributes"""
        parts = key.split('__')
        current = self
        
        for part in parts[:-1]:
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return  # Attribute not found
        
        if hasattr(current, parts[-1]):
            setattr(current, parts[-1], value)


# Global config instance
_binance_config = None

def get_binance_config() -> BinanceConfig:
    """Get or create global Binance config instance"""
    global _binance_config
    if _binance_config is None:
        _binance_config = BinanceConfig()
    return _binance_config

def set_binance_config(config: BinanceConfig):
    """Set global Binance config instance"""
    global _binance_config
    _binance_config = config


class BinanceAPI:
    """Binance API with organized config management"""
    
    def __init__(self, api_key: Optional[str], api_secret: Optional[str], config: Optional[BinanceConfig] = None):
        # Use provided config or get default
        self.config = config or get_binance_config()
        
        self.http = BinanceHTTPClient(
            api_key=api_key or self.config.Security.api_key,
            secret_key=api_secret or self.config.Security.api_secret, 
            base_url=self.config.URLs.base_url,
            fapi_url=self.config.URLs.fapi_url,
            config={
                "requests_per_second": self.config.Security.requests_per_second,
                "timeout": self.config.Public.Spot.timeout,
                "max_connections": self.config.Security.max_connections
            },
        )
        
        self.breaker = CircuitBreaker(
            failure_threshold=self.config.CircuitBreaker.failure_threshold,
            reset_timeout=self.config.CircuitBreaker.reset_timeout
        )
        
        logger.info("BinanceAPI initialized with organized config structure")

    @classmethod
    async def create(cls, user_id: Optional[int] = None, config: Optional[BinanceConfig] = None):
        """Create instance with flexible config source"""
        # Config can come from main bot or be standalone
        final_config = config or get_binance_config()
        
        # Use config security credentials if not provided via other means
        api_key = final_config.Security.api_key
        api_secret = final_config.Security.api_secret
        
        if user_id:
            # User-specific key loading logic here
            # This could override the global config keys
            pass
            
        return cls(api_key, api_secret, final_config)


class BinancePublicAPI:
    """Dedicated Public API client using the organized config"""
    
    def __init__(self, config: Optional[BinanceConfig] = None):
        self.config = config or get_binance_config()
        
        # Public API doesn't need credentials
        self.http = BinanceHTTPClient(
            api_key=None,
            secret_key=None,
            base_url=self.config.URLs.base_url,
            fapi_url=self.config.URLs.fapi_url,
            config={
                "requests_per_second": self.config.Security.requests_per_second,
                "timeout": self.config.Public.Spot.timeout,
                "max_connections": self.config.Security.max_connections
            },
        )
        
        self.breaker = CircuitBreaker(
            failure_threshold=self.config.CircuitBreaker.failure_threshold,
            reset_timeout=self.config.CircuitBreaker.reset_timeout
        )
        
        logger.info("BinancePublicAPI initialized for public endpoints only")

    @classmethod
    async def create(cls, config: Optional[BinanceConfig] = None):
        """Create public API instance"""
        instance = cls(config)
        
        # Import here to avoid circular imports
        from .binance_public import create_binance_public_api
        
        # Initialize public API instances based on config
        if instance.config.Public.Spot.enabled:
            instance.spot = create_binance_public_api(instance.http, instance.breaker, futures=False)
            
        if instance.config.Public.Futures.enabled:
            instance.futures = create_binance_public_api(instance.http, instance.breaker, futures=True)
            
        return instance
  ##binace config sonu




class BinanceEndpointGroup(Enum):
    """Binance endpoint grupları"""
    MARKET_DATA = "market_data"
    ACCOUNT = "account"
    TRADING = "trading"
    USER_DATA = "user_data"
    WEBSOCKET = "websocket"


@dataclass
class BinancePublicAPIConfig:
    """Binance Public API için özel konfigürasyon"""
    
    # Base URLs
    SPOT_BASE_URL: str = field(default_factory=lambda: os.getenv("BINANCE_SPOT_BASE_URL", "https://api.binance.com"))
    FUTURES_BASE_URL: str = field(default_factory=lambda: os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com"))
    TESTNET_BASE_URL: str = field(default_factory=lambda: os.getenv("BINANCE_TESTNET_BASE_URL", "https://testnet.binance.vision"))
    
    # Rate limiting
    REQUESTS_PER_SECOND: int = field(default_factory=lambda: int(os.getenv("BINANCE_REQUESTS_PER_SECOND", "10")))
    REQUESTS_PER_MINUTE: int = field(default_factory=lambda: int(os.getenv("BINANCE_REQUESTS_PER_MINUTE", "1200")))
    REQUEST_TIMEOUT: int = field(default_factory=lambda: int(os.getenv("BINANCE_REQUEST_TIMEOUT", "30")))
    
    # Retry settings
    MAX_RETRIES: int = field(default_factory=lambda: int(os.getenv("BINANCE_MAX_RETRIES", "3")))
    RETRY_DELAY: float = field(default_factory=lambda: float(os.getenv("BINANCE_RETRY_DELAY", "1.0")))
    RETRY_BACKOFF: float = field(default_factory=lambda: float(os.getenv("BINANCE_RETRY_BACKOFF", "2.0")))
    
    # Circuit breaker settings
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = field(default_factory=lambda: int(os.getenv("BINANCE_CB_FAILURE_THRESHOLD", "5")))
    CIRCUIT_BREAKER_RESET_TIMEOUT: int = field(default_factory=lambda: int(os.getenv("BINANCE_CB_RESET_TIMEOUT", "60")))
    CIRCUIT_BREAKER_HALF_OPEN_TIMEOUT: int = field(default_factory=lambda: int(os.getenv("BINANCE_CB_HALF_OPEN_TIMEOUT", "30")))
    
    # Cache settings
    CACHE_TTL: Dict[str, int] = field(default_factory=lambda: {
        "exchange_info": 3600,  # 1 hour
        "symbols": 1800,        # 30 minutes
        "ticker": 30,           # 30 seconds
        "orderbook": 10,        # 10 seconds
        "klines": 60,           # 1 minute
        "trades": 15,           # 15 seconds
    })
    
    # Endpoint specific timeouts
    ENDPOINT_TIMEOUTS: Dict[str, int] = field(default_factory=lambda: {
        "ping": 5,
        "exchange_info": 15,
        "orderbook": 10,
        "ticker": 10,
        "klines": 15,
        "trades": 10,
        "historical_trades": 20,
    })
    
    # Validation settings
    VALID_INTERVALS: Set[str] = field(default_factory=lambda: {
        "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"
    })
    
    VALID_DEPTH_LIMITS: Set[int] = field(default_factory=lambda: {5, 10, 20, 50, 100, 500, 1000, 5000})
    VALID_FUTURES_DEPTH_LIMITS: Set[int] = field(default_factory=lambda: {5, 10, 20, 50, 100, 500, 1000})
    
    # Symbol settings
    DEFAULT_SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT", 
        "LINKUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT", "EOSUSDT"
    ])
    
    # WebSocket settings
    WS_BASE_URL: str = field(default_factory=lambda: os.getenv("BINANCE_WS_BASE_URL", "wss://stream.binance.com:9443/ws"))
    WS_FUTURES_URL: str = field(default_factory=lambda: os.getenv("BINANCE_WS_FUTURES_URL", "wss://fstream.binance.com/ws"))
    WS_RECONNECT_DELAY: int = field(default_factory=lambda: int(os.getenv("BINANCE_WS_RECONNECT_DELAY", "5")))
    WS_HEARTBEAT_INTERVAL: int = field(default_factory=lambda: int(os.getenv("BINANCE_WS_HEARTBEAT_INTERVAL", "30")))
    
    # Monitoring & Health checks
    HEALTH_CHECK_INTERVAL: int = field(default_factory=lambda: int(os.getenv("BINANCE_HEALTH_CHECK_INTERVAL", "300")))
    CONNECTION_POOL_SIZE: int = field(default_factory=lambda: int(os.getenv("BINANCE_CONNECTION_POOL_SIZE", "100")))
    
    # Feature flags
    ENABLE_SPOT_API: bool = field(default_factory=lambda: os.getenv("BINANCE_ENABLE_SPOT_API", "true").lower() == "true")
    ENABLE_FUTURES_API: bool = field(default_factory=lambda: os.getenv("BINANCE_ENABLE_FUTURES_API", "true").lower() == "true")
    ENABLE_TESTNET: bool = field(default_factory=lambda: os.getenv("BINANCE_ENABLE_TESTNET", "false").lower() == "true")
    ENABLE_CACHE: bool = field(default_factory=lambda: os.getenv("BINANCE_ENABLE_CACHE", "true").lower() == "true")
    ENABLE_CIRCUIT_BREAKER: bool = field(default_factory=lambda: os.getenv("BINANCE_ENABLE_CIRCUIT_BREAKER", "true").lower() == "true")
    
    @property
    def base_url(self) -> str:
        """Aktif base URL'i döndürür (testnet veya production)"""
        if self.ENABLE_TESTNET:
            return self.TESTNET_BASE_URL
        return self.SPOT_BASE_URL
    
    @property
    def futures_url(self) -> str:
        """Futures base URL'i döndürür"""
        return self.FUTURES_BASE_URL
    
    @property
    def ws_url(self) -> str:
        """WebSocket URL'i döndürür"""
        return self.WS_BASE_URL
    
    def get_cache_ttl(self, endpoint_type: str) -> int:
        """Endpoint tipine göre cache TTL süresini döndürür"""
        return self.CACHE_TTL.get(endpoint_type, 60)
    
    def get_endpoint_timeout(self, endpoint: str) -> int:
        """Endpoint'e özel timeout süresini döndürür"""
        return self.ENDPOINT_TIMEOUTS.get(endpoint, self.REQUEST_TIMEOUT)


@dataclass 
class BinancePublicAPIRouterConfig:
    """Binance Public API Router için konfigürasyon"""
    
    # Command prefixes
    COMMAND_PREFIX: str = field(default_factory=lambda: os.getenv("BINANCE_ROUTER_PREFIX", "/binance"))
    
    # Available commands
    ENABLED_COMMANDS: Set[str] = field(default_factory=lambda: {
        "price", "depth", "klines", "ticker", "trades", "info", 
        "symbols", "ping", "time", "book", "stats"
    })
    
    # Command aliases
    COMMAND_ALIASES: Dict[str, str] = field(default_factory=lambda: {
        "p": "price",
        "d": "depth", 
        "k": "klines",
        "t": "ticker",
        "tr": "trades",
        "i": "info",
        "s": "symbols",
        "b": "book",
        "stat": "stats"
    })
    
    # Response formatting
    MAX_RESPONSE_LENGTH: int = field(default_factory=lambda: int(os.getenv("BINANCE_MAX_RESPONSE_LENGTH", "2000")))
    TRUNCATE_RESPONSE: bool = field(default_factory=lambda: os.getenv("BINANCE_TRUNCATE_RESPONSE", "true").lower() == "true")
    
    # Default parameters
    DEFAULT_SYMBOL: str = field(default_factory=lambda: os.getenv("BINANCE_DEFAULT_SYMBOL", "BTCUSDT"))
    DEFAULT_INTERVAL: str = field(default_factory=lambda: os.getenv("BINANCE_DEFAULT_INTERVAL", "1h"))
    DEFAULT_LIMIT: int = field(default_factory=lambda: int(os.getenv("BINANCE_DEFAULT_LIMIT", "100")))
    
    # Rate limiting per user
    USER_RATE_LIMIT: Tuple[int, int] = field(default_factory=lambda: (
        int(os.getenv("BINANCE_USER_RATE_LIMIT_COUNT", "10")),
        int(os.getenv("BINANCE_USER_RATE_LIMIT_PERIOD", "60"))
    ))
    
    # Cache settings for router responses
    ROUTER_CACHE_TTL: int = field(default_factory=lambda: int(os.getenv("BINANCE_ROUTER_CACHE_TTL", "30")))




@dataclass
class OnChainConfig:
    GLASSNODE_API_KEY: str = field(default_factory=lambda: os.getenv("GLASSNODE_API_KEY", "your_glassnode_api_key_here"))
    METRIC_WEIGHTS: Dict[str, float] = field(default_factory=lambda: {
        "stablecoin_supply_ratio": 0.3,
        "exchange_net_flow": 0.3,
        "etf_flows": 0.2,
        "fear_greed_index": 0.2
    })
    SSR_THRESHOLDS: Dict[str, float] = field(default_factory=lambda: {
        "bearish": 20.0,
        "bullish": 5.0,
        "neutral": 10.0
    })
    NETFLOW_THRESHOLDS: Dict[str, float] = field(default_factory=lambda: {
        "bearish": 1000,
        "bullish": -1000
    })
    ETF_THRESHOLDS: Dict[str, float] = field(default_factory=lambda: {
        "max_flow": 50000000
    })
    API_TIMEOUTS: Dict[str, int] = field(default_factory=lambda: {
        "glassnode": 30,
        "fear_greed": 10,
        "binance": 15
    })
    CACHE_TTL: Dict[str, int] = field(default_factory=lambda: {
        "ssr": 3600,
        "netflow": 1800,
        "etf_flows": 3600,
        "fear_greed": 3600
    })
    FALLBACK_VALUES: Dict[str, float] = field(default_factory=lambda: {
        "ssr": 0.0,
        "netflow": 0.0,
        "etf_flows": 0.0,
        "fear_greed": 0.0
    })



@dataclass
class AioGramConfig:
    """Aiogram 3.x için özel konfigürasyon"""
    
    # Router settings
    ROUTER_PREFIX: str = field(default_factory=lambda: os.getenv("AIOGRAM_ROUTER_PREFIX", ""))
    INCLUDE_ROUTERS: List[str] = field(default_factory=lambda: [
        router.strip() for router in os.getenv("AIOGRAM_INCLUDE_ROUTERS", "binance,analysis,alerts").split(",") 
        if router.strip()
    ])
    
    # Middleware settings
    ENABLE_RATE_LIMITING: bool = field(default_factory=lambda: os.getenv("AIOGRAM_ENABLE_RATE_LIMITING", "true").lower() == "true")
    RATE_LIMIT_DEFAULT: Tuple[int, int] = field(default_factory=lambda: (
        int(os.getenv("AIOGRAM_RATE_LIMIT_DEFAULT_COUNT", "5")),
        int(os.getenv("AIOGRAM_RATE_LIMIT_DEFAULT_PERIOD", "60"))
    ))
    
    # FSM settings
    FSM_STORAGE_TYPE: str = field(default_factory=lambda: os.getenv("AIOGRAM_FSM_STORAGE_TYPE", "redis"))
    FSM_DATA_TTL: int = field(default_factory=lambda: int(os.getenv("AIOGRAM_FSM_DATA_TTL", "86400")))  # 24 hours
    
    # Handler settings
    DEFAULT_PARSER_MODE: str = field(default_factory=lambda: os.getenv("AIOGRAM_DEFAULT_PARSER_MODE", "HTML"))
    ALLOWED_UPDATES: List[str] = field(default_factory=lambda: [
        update.strip() for update in os.getenv(
            "AIOGRAM_ALLOWED_UPDATES", 
            "message,callback_query,inline_query,chosen_inline_result"
        ).split(",") if update.strip()
    ])
    
    # Bot settings
    BOT_NAME: str = field(default_factory=lambda: os.getenv("AIOGRAM_BOT_NAME", "CryptoAnalysisBot"))
    BOT_USERNAME: str = field(default_factory=lambda: os.getenv("AIOGRAM_BOT_USERNAME", ""))
    BOT_DESCRIPTION: str = field(default_factory=lambda: os.getenv("AIOGRAM_BOT_DESCRIPTION", "Advanced Crypto Analysis Bot"))
    
    # Webhook settings (aiogram specific)
    WEBHOOK_MAX_CONNECTIONS: int = field(default_factory=lambda: int(os.getenv("AIOGRAM_WEBHOOK_MAX_CONNECTIONS", "40")))
    WEBHOOK_SECRET_TOKEN_LENGTH: int = field(default_factory=lambda: int(os.getenv("AIOGRAM_WEBHOOK_SECRET_TOKEN_LENGTH", "32")))
    
    # Logging settings
    LOG_UPDATES: bool = field(default_factory=lambda: os.getenv("AIOGRAM_LOG_UPDATES", "false").lower() == "true")
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv("AIOGRAM_LOG_LEVEL", "INFO"))
    
    @property
    def rate_limit_config(self) -> Dict[str, Any]:
        """Rate limiting konfigürasyonu"""
        return {
            "default": self.RATE_LIMIT_DEFAULT,
            "enabled": self.ENABLE_RATE_LIMITING
        }
    
    @property
    def fsm_config(self) -> Dict[str, Any]:
        """FSM konfigürasyonu"""
        return {
            "storage_type": self.FSM_STORAGE_TYPE,
            "data_ttl": self.FSM_DATA_TTL,
            "redis_config": get_redis_config() if self.FSM_STORAGE_TYPE == "redis" else None
        }



@dataclass
class AnalysisConfig:
    """Analiz modülü konfigürasyonu"""
    # Cache ayarları
    ANALYSIS_CACHE_TTL: int = field(default_factory=lambda: int(os.getenv("ANALYSIS_CACHE_TTL", "60")))
    MAX_CACHE_SIZE: int = field(default_factory=lambda: int(os.getenv("MAX_CACHE_SIZE", "1000")))
    
    # Skor threshold'ları
    SIGNAL_THRESHOLDS: Dict[str, float] = field(default_factory=lambda: {
        "strong_bull": 0.7,
        "bull": 0.3, 
        "bear": -0.3,
        "strong_bear": -0.7
    })
    
    # Modül ağırlıkları
    MODULE_WEIGHTS: Dict[str, float] = field(default_factory=lambda: {
        "tremo": 0.20,
        "regime": 0.18,
        "derivs": 0.16,
        "causality": 0.14,
        "orderflow": 0.12,
        "onchain": 0.10,
        "risk": 0.10
    })
    
    # Timeout ayarları
    MODULE_TIMEOUTS: Dict[str, int] = field(default_factory=lambda: {
        "causality": 30,
        "derivs": 25,
        "onchain": 40,
        "orderflow": 20,
        "regime": 35,
        "tremo": 30,
        "risk": 25
    })
    
    # Risk yönetimi
    MIN_CONFIDENCE: float = field(default_factory=lambda: float(os.getenv("MIN_CONFIDENCE", "0.3")))
    MAX_POSITION_SIZE: float = field(default_factory=lambda: float(os.getenv("MAX_POSITION_SIZE", "0.1")))


@dataclass
class BotConfig:
    """Aiogram 3.x uyumlu bot yapılandırma sınıfı."""
    
    # ========================
    # 🤖 TELEGRAM BOT SETTINGS
    # ========================
    TELEGRAM_TOKEN: str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    NGROK_URL: str = field(default_factory=lambda: os.getenv("NGROK_URL", "https://2fce5af7336f.ngrok-free.app"))
    
    DEFAULT_LOCALE: str = field(default_factory=lambda: os.getenv("DEFAULT_LOCALE", "en"))
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
    ])
    
    # 🔐 ENCRYPTION SETTINGS
    MASTER_KEY: str = field(default_factory=lambda: os.getenv("MASTER_KEY", ""))
    
    
    # Webhook settings
    USE_WEBHOOK: bool = field(default_factory=lambda: os.getenv("USE_WEBHOOK", "false").lower() == "true")
    WEBHOOK_HOST: str = field(default_factory=lambda: os.getenv("WEBHOOK_HOST", ""))
    WEBHOOK_SECRET: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", ""))
    WEBAPP_HOST: str = field(default_factory=lambda: os.getenv("WEBAPP_HOST", "0.0.0.0"))
    WEBAPP_PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "3000")))
    
    # Aiogram specific settings
    AIOGRAM_REDIS_HOST: str = field(default_factory=lambda: os.getenv("AIOGRAM_REDIS_HOST", "localhost"))
    AIOGRAM_REDIS_PORT: int = field(default_factory=lambda: int(os.getenv("AIOGRAM_REDIS_PORT", "6379")))
    AIOGRAM_REDIS_DB: int = field(default_factory=lambda: int(os.getenv("AIOGRAM_REDIS_DB", "0")))
    
    # FSM storage settings
    USE_REDIS_FSM: bool = field(default_factory=lambda: os.getenv("USE_REDIS_FSM", "true").lower() == "true")
    FSM_STORAGE_TTL: int = field(default_factory=lambda: int(os.getenv("FSM_STORAGE_TTL", "3600")))
    
    # ========================
    # 🔐 BINANCE API SETTINGS
    # ========================
    #   ALTIİNCELE-SİL
    BINANCE_API_KEY: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    BINANCE_API_SECRET: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    BINANCE_BASE_URL: str = field(default_factory=lambda: os.getenv("BINANCE_BASE_URL", "https://api.binance.com"))
    BINANCE_FAPI_URL: str = field(default_factory=lambda: os.getenv("BINANCE_FAPI_URL", "https://fapi.binance.com"))
    BINANCE_WS_URL: str = field(default_factory=lambda: os.getenv("BINANCE_WS_URL", "wss://stream.binance.com:9443/ws"))


    # ========================
    # 🔗 BINANCE PUBLIC API SETTINGS
    # ========================
    BINANCE_PUBLIC: BinancePublicAPIConfig = field(default_factory=BinancePublicAPIConfig)
    
    # ========================
    # 🤖 AIOGRAM SPECIFIC SETTINGS  
    # ========================
    AIOGRAM: AioGramConfig = field(default_factory=AioGramConfig)

    # ========================
    # 🚦 BINANCE ROUTER SETTINGS
    # ========================
    BINANCE_ROUTER: BinancePublicAPIRouterConfig = field(default_factory=BinancePublicAPIRouterConfig)
    


    # ========================
    # ⚙️ TECHNICAL SETTINGS
    # ========================
    DEBUG: bool = field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    
    # Rate limiting
    # Devre kesici ayarları
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = field(default_factory=lambda: int(os.getenv("FAILURE_THRESHOLD", "5")))
    CIRCUIT_BREAKER_RESET_TIMEOUT: int = field(default_factory=lambda: int(os.getenv("RESET_TIMEOUT", "30")))
    CIRCUIT_BREAKER_HALF_OPEN_TIMEOUT: int = field(default_factory=lambda: int(os.getenv("HALF_OPEN_TIMEOUT", "15")))

    # On-chain analiz için alt config nesnesi
    ONCHAIN: OnChainConfig = field(default_factory=OnChainConfig)

    # Analiz için alt config nesnesi
    ANALYSIS: AnalysisConfig = field(default_factory=AnalysisConfig)
    
    # Database settings
    DATABASE_URL: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    USE_DATABASE: bool = field(default_factory=lambda: os.getenv("USE_DATABASE", "false").lower() == "true")
    
    # Cache settings
    CACHE_TTL: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL", "300")))
    MAX_CACHE_SIZE: int = field(default_factory=lambda: int(os.getenv("MAX_CACHE_SIZE", "1000")))

    # Analytics specific settings
    CAUSALITY_WINDOW: int = field(default_factory=lambda: int(os.getenv("CAUSALITY_WINDOW", "100")))
    CAUSALITY_MAXLAG: int = field(default_factory=lambda: int(os.getenv("CAUSALITY_MAXLAG", "2")))
    CAUSALITY_CACHE_TTL: int = field(default_factory=lambda: int(os.getenv("CAUSALITY_CACHE_TTL", "10")))
    CAUSALITY_TOP_ALTCOINS: List[str] = field(default_factory=lambda: [
        symbol.strip() for symbol in os.getenv(
            "CAUSALITY_TOP_ALTCOINS", 
            "BNBUSDT,ADAUSDT,SOLUSDT,XRPUSDT,DOTUSDT"
        ).split(",") if symbol.strip()
    ])

    # ========================
    # 📊 TRADING SETTINGS
    # ========================
    SCAN_SYMBOLS: List[str] = field(default_factory=lambda: [
        symbol.strip() for symbol in os.getenv(
            "SCAN_SYMBOLS", 
            "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,TRXUSDT,CAKEUSDT,SUIUSDT,PEPEUSDT,ARPAUSDT,TURBOUSDT"
        ).split(",") if symbol.strip()
    ])
    
    ENABLE_TRADING: bool = field(default_factory=lambda: os.getenv("ENABLE_TRADING", "false").lower() == "true")
    TRADING_STRATEGY: str = field(default_factory=lambda: os.getenv("TRADING_STRATEGY", "conservative"))
    MAX_LEVERAGE: int = field(default_factory=lambda: int(os.getenv("MAX_LEVERAGE", "3")))
    
    # Alert settings
    ALERT_PRICE_CHANGE_PERCENT: float = field(default_factory=lambda: float(os.getenv("ALERT_PRICE_CHANGE_PERCENT", "5.0")))
    ENABLE_PRICE_ALERTS: bool = field(default_factory=lambda: os.getenv("ENABLE_PRICE_ALERTS", "true").lower() == "true")
    ALERT_COOLDOWN: int = field(default_factory=lambda: int(os.getenv("ALERT_COOLDOWN", "300")))

    # ========================
    # 🛠️ METHODS & PROPERTIES
    # ========================
    @property
    def WEBHOOK_PATH(self) -> str:
        """Webhook path'i dinamik olarak oluşturur (Telegram formatına uygun)."""
        if not self.TELEGRAM_TOKEN:
            return "/webhook/default"
        return f"/webhook/{self.TELEGRAM_TOKEN}"

    @property
    def WEBHOOK_URL(self) -> str:
        """Webhook URL'ini döndürür. Sadece USE_WEBHOOK=True ise anlamlı değer üretir."""
        if not self.USE_WEBHOOK or not self.WEBHOOK_HOST:
            return ""
        return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"

    @classmethod
    def load(cls) -> "BotConfig":
        """Environment'dan config yükler."""
        return cls()

    def validate(self) -> bool:
        """Config değerlerini doğrular. Hata durumunda kontrollü çıkış yapar."""
        errors = []
        
        # Telegram bot validation
        if not self.TELEGRAM_TOKEN:
            errors.append("❌ TELEGRAM_TOKEN gereklidir")
        
        # Webhook validation (eğer webhook kullanılıyorsa)
        if self.USE_WEBHOOK:
            if not self.WEBHOOK_HOST:
                errors.append("❌ WEBHOOK_HOST gereklidir (USE_WEBHOOK=true)")
        
        # Binance validation (eğer trading enabled ise)
        if self.ENABLE_TRADING:
            if not self.BINANCE_API_KEY:
                errors.append("❌ BINANCE_API_KEY gereklidir (trading enabled)")
            if not self.BINANCE_API_SECRET:
                errors.append("❌ BINANCE_API_SECRET gereklidir (trading enabled)")
        
        if errors:
            logger.critical("Config validation hatası:\n%s", "\n".join(errors))
            sys.exit(1)
        
        return True

    def is_admin(self, user_id: int) -> bool:
        """Kullanıcının admin olup olmadığını kontrol eder."""
        return user_id in self.ADMIN_IDS

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """Config'i dict olarak döndürür (debug/log amaçlı).
        
        Args:
            include_sensitive: Hassas bilgileri gösterilsin mi? (default: False)
        """
        sensitive_fields = {"TELEGRAM_TOKEN", "BINANCE_API_KEY", "BINANCE_API_SECRET", "WEBHOOK_SECRET"}
        result = {}
        
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if field_name in sensitive_fields and value and not include_sensitive:
                result[field_name] = "***HIDDEN***"
            else:
                result[field_name] = value
        
        # Property'leri de ekle
        result["WEBHOOK_PATH"] = self.WEBHOOK_PATH
        result["WEBHOOK_URL"] = self.WEBHOOK_URL
        
        return result

    def to_safe_dict(self) -> Dict[str, Any]:
        """Güvenli config dict'i (hassas bilgiler olmadan)."""
        return self.to_dict(include_sensitive=False)


def reload_config() -> BotConfig:
    """Config'i yeniden yükler ve cache'i temizler."""
    global _CONFIG_INSTANCE
    _CONFIG_INSTANCE = None
    logger.info("🔄 Config cache temizlendi, yeniden yükleniyor...")
    return get_config_sync()


def get_config_sync() -> BotConfig:
    """Sync config instance'ını döndürür."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = BotConfig.load()
        _CONFIG_INSTANCE.validate()
        logger.info("✅ Bot config yüklendi ve doğrulandı")
        
        # Debug log'da sadece güvenli bilgileri göster
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Config (güvenli): {_CONFIG_INSTANCE.to_safe_dict()}")
    
    return _CONFIG_INSTANCE


async def get_config() -> BotConfig:
    """Global config instance'ını döndürür (async wrapper)."""
    return get_config_sync()


def get_telegram_token() -> str:
    """Aiogram için Telegram bot token'ını döndürür."""
    config = get_config_sync()
    return config.TELEGRAM_TOKEN


def get_admins() -> List[int]:
    """Admin kullanıcı ID'lerini döndürür."""
    config = get_config_sync()
    return config.ADMIN_IDS


def get_webhook_config() -> Dict[str, Any]:
    """Webhook konfigürasyonu döndürür."""
    config = get_config_sync()
    return {
        "path": config.WEBHOOK_PATH,
        "url": config.WEBHOOK_URL,
        "secret_token": config.WEBHOOK_SECRET,
        "host": config.WEBAPP_HOST,
        "port": config.WEBAPP_PORT,
        "enabled": config.USE_WEBHOOK,
    }


def get_redis_config() -> Dict[str, Any]:
    """Aiogram için Redis konfigürasyonu döndürür."""
    config = get_config_sync()
    return {
        "host": config.AIOGRAM_REDIS_HOST,
        "port": config.AIOGRAM_REDIS_PORT,
        "db": config.AIOGRAM_REDIS_DB,
    }
    
    
# Yeni yardımcı fonksiyonlar
def get_binance_public_config() -> BinancePublicAPIConfig:
    """Binance Public API konfigürasyonunu döndürür"""
    config = get_config_sync()
    return config.BINANCE_PUBLIC

def get_aiogram_config() -> AioGramConfig:
    """Aiogram konfigürasyonunu döndürür"""
    config = get_config_sync()
    return config.AIOGRAM

def get_binance_router_config() -> BinancePublicAPIRouterConfig:
    """Binance Router konfigürasyonunu döndürür"""
    config = get_config_sync()
    return config.BINANCE_ROUTER

def get_binance_rate_limits() -> Dict[str, int]:
    """Binance rate limit konfigürasyonunu döndürür"""
    binance_config = get_binance_public_config()
    return {
        "requests_per_second": binance_config.REQUESTS_PER_SECOND,
        "requests_per_minute": binance_config.REQUESTS_PER_MINUTE,
        "request_timeout": binance_config.REQUEST_TIMEOUT,
        "max_retries": binance_config.MAX_RETRIES
    }

def get_circuit_breaker_config() -> Dict[str, Any]:
    """Circuit breaker konfigürasyonunu döndürür"""
    binance_config = get_binance_public_config()
    return {
        "failure_threshold": binance_config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        "reset_timeout": binance_config.CIRCUIT_BREAKER_RESET_TIMEOUT,
        "half_open_timeout": binance_config.CIRCUIT_BREAKER_HALF_OPEN_TIMEOUT,
        "enabled": binance_config.ENABLE_CIRCUIT_BREAKER
    }



