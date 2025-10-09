"""
main.py - Telegram Bot Ana Giriş Noktası (FİNAL)
----------------------------------------
Aiogram 3.x + Router pattern + Webhook + Render uyumlu.
- Yeni config yapısına tam uyumlu
- Gelişmiş error handling
- Health check endpoints
- Graceful shutdown
- Local polling desteği eklendi
free tier platformlarla tam uyumludur.
+ (Webhook path now uses /webhook/<BOT_TOKEN> format)
Aiogram 3.x’te Bot sınıfı default olarak data dict’i içermez.
hem lifespan() fonksiyonunda hem de initialize_polling_mode() içinde bot yaratıldıktan hemen sonra şu satırı eklemelisiniz:
bot.data = {}
📌 
2. Bot token sızma riski → Maskeleme iyileştirmesi
/webhook/{token} GET endpoint'inde token'ın sadece ilk ve son birkaç karakteri gösteriliyor. Ancak bir yerde log’lanması hâlinde bu risk olabilir.
🛡️ Öneri: Token'ı direkt olarak hiçbir response içine koymamak daha güvenlidir, ya da sadece sabit "***********" göstermek.

eğer response’lar bir yerde loglanıyorsa, bu endpoint kullanılmaya devam ettikçe sızıntı olabilir.
✅ Ne yapılabilir?
Daha güvenli öneri:

return web.json_response({
    "status": "active",
    "bot_token": "***********",  # veya bu alanı tamamen kaldır
    "method": "POST",
    "message": "Webhook is active. Use POST method for Telegram updates."
})
"""

import os
import asyncio
import logging
import signal
import time
from typing import Optional, Dict, Any, Union
from contextlib import asynccontextmanager

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router
from datetime import datetime
from aiogram.types import Update, Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter
from aiogram.types import ErrorEvent

from utils.handler_loader import load_handlers, clear_handler_cache

from utils.binance_api.binance_exceptions import BinanceAPIError, BinanceAuthenticationError
from utils.binance_api.binance_request import BinanceHTTPClient
from utils.binance_api.binance_circuit_breaker import CircuitBreaker
#from utils.binance_api.binance_a import
from utils.binance_api.binance_a import (
    BinanceAggregator, 
    MultiUserBinanceAggregator,
)

from utils.apikey_manager import APIKeyManager, AlarmManager, TradeSettingsManager
from utils.context_logger import setup_context_logging, get_context_logger, ContextAwareLogger
from utils.performance_monitor import monitor_performance, PerformanceMonitor
from utils.security_auditor import security_auditor

from config import BotConfig, get_config, get_telegram_token, get_admins


#-1-
# Merkezi Bot Factory Fonksiyonu
async def create_bot_instance(config: Optional[BotConfig] = None) -> Bot:
    """Merkezi bot instance oluşturucu"""
    bot_instance = Bot(
        token=get_telegram_token(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            # Config'den diğer ayarlar
        )
    )
    init_bot_data(bot_instance)
    
    if config:
        bot_instance.data['config'] = config

    
    logger.info("✅ Bot instance created with consistent data dict")
    return bot_instance

# -2-
# Bot.data İçin Standardize Edilmiş Structure

def init_bot_data(bot_instance: Bot) -> None:
    """Bot data structure'ını standardize et"""
    if not hasattr(bot_instance, 'data') or bot_instance.data is None:
        bot_instance.data = {}
    
    # ✅ DAHA GÜVENLİ STRUCTURE
    standard_data = {
        'binance_api': None,
        'start_time': datetime.now(),
        'user_sessions': {},
        'circuit_breakers': {},
        'metrics': {
            'messages_processed': 0,
            'errors_count': 0,
            'last_health_check': None,
            'active_users': 0  # ✅ YENİ METRİK
        },
        'config': None,
        'aggregator': None,
        'health_status': 'initializing'  # ✅ YENİ DURUM TAKİBİ
    }
    
    # Deep merge yap (sadece eksik key'leri ekle)
    for key, default_value in standard_data.items():
        if key not in bot_instance.data:
            bot_instance.data[key] = default_value
        elif isinstance(default_value, dict) and isinstance(bot_instance.data[key], dict):
            # Nested dict'leri merge et
            for sub_key, sub_value in default_value.items():
                if sub_key not in bot_instance.data[key]:
                    bot_instance.data[key][sub_key] = sub_value
                    
# ---------------------------------------------------------------------
# Config & Logging Setup
# ---------------------------------------------------------------------
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
# Mevcut logging setup'tan SONRA ekle:
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ✅ CONTEXT-AWARE LOGGING SETUP
setup_context_logging()
logger = get_context_logger(__name__)


# Global instances
bot: Optional[Bot] = None
dispatcher: Optional[Dispatcher] = None
#binance_api: Optional[Any] = None  # yerine
binance_api: Optional[Union[BinanceAggregator, MultiUserBinanceAggregator]] = None
app_config: Optional[BotConfig] = None
runner: Optional[web.AppRunner] = None
polling_task: Optional[asyncio.Task] = None

# Graceful shutdown flag
shutdown_event = asyncio.Event()

# ---------------------------------------------------------------------
# Signal Handling for Graceful Shutdown
# ---------------------------------------------------------------------
def handle_shutdown(signum, frame) -> None:
    """Handle shutdown signals gracefully."""
    logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
    # set the asyncio event in an async-safe way
    try:
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(shutdown_event.set)
    except Exception:
        # If loop closed or unavailable, set directly (best-effort)
        shutdown_event.set()

# Register signal handlers
signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)

# ---------------------------------------------------------------------
# apikeys
# ---------------------------------------------------------------------
async def startup():
    # Database tablolarını oluştur
    apimanager = APIKeyManager.get_instance()
    await apimanager.init_db()


# ---------------------------------------------------------------------
# Error Handler
# ---------------------------------------------------------------------
async def error_handler(event: ErrorEvent) -> None:
    """Global error handler for aiogram."""
    exception = event.exception
    
    # Security audit log
    try:
        user_id = getattr(event.update, 'from_user', None)
        if user_id:
            user_id = user_id.id
            await security_auditor.audit_request(
                user_id, 
                "error", 
                {"error_type": type(exception).__name__, "message": str(exception)}
            )
    except Exception as audit_error:
        logger.error(f"Security audit failed: {audit_error}")
    
    # ✅ METRİK GÜNCELLEME
    if bot and hasattr(bot, 'data') and 'metrics' in bot.data:
        bot.data['metrics']['errors_count'] = bot.data['metrics'].get('errors_count', 0) + 1
        
    # Kritik hatalarda admin'e bildir
    if isinstance(exception, (BinanceAuthenticationError, ConnectionError)):
        await notify_admins_about_critical_error(exception)
    
    # ✅ YENİ: Circuit breaker durumu kontrolü
    if isinstance(exception, (ConnectionError, asyncio.TimeoutError)):
        user_id = getattr(event.update, 'from_user', None)
        if user_id and hasattr(bot, 'data') and 'circuit_breakers' in bot.data:
            user_id = user_id.id
            if user_id in bot.data['circuit_breakers']:
                await bot.data['circuit_breakers'][user_id].record_failure()

    # Hata türlerine göre loglama
    if isinstance(exception, (ConnectionError, asyncio.TimeoutError)):
        logger.warning(f"🌐 Network error in update {event.update.update_id}: {exception}")
        
    elif isinstance(exception, BinanceAuthenticationError):
        logger.error(f"🔐 Authentication error: {exception}")
        # Admin'e bildirim zaten yukarıda yapıldı
        
    elif isinstance(exception, BinanceAPIError):
        error_code = getattr(exception, 'code', 'N/A')
        logger.error(f"📊 Binance API error (code: {error_code}): {exception}")
        
    elif isinstance(exception, ValueError):
        logger.warning(f"⚠️ Validation error: {exception}")
        
    elif hasattr(exception, 'code'):  # Diğer API exception'ları için
        logger.error(f"🔧 API error (code: {exception.code}): {exception}")
        
    elif "auth" in str(exception).lower() or "token" in str(exception).lower():
        logger.error(f"🔐 Authentication error (detected): {exception}")
        
    else:
        logger.error(f"❌ Unexpected error in update {event.update.update_id}: {exception}", 
                    exc_info=True)  # Stack trace için exc_info

    # Kullanıcıya hata mesajı gönder (güvenli şekilde)
    try:
        if getattr(event.update, "message", None):
            await event.update.message.answer("❌ Bir hata oluştu, lütfen daha sonra tekrar deneyin.")
    except Exception as e:
        logger.error(f"❌ Failed to send error message: {e}")


# ---------------------------------------------------------------------
# Rate Limiting Filter
# ---------------------------------------------------------------------
class RateLimitFilter(BaseFilter):
    """Rate limiting filter for messages."""
    
    def __init__(self, rate: float = 1.0):
        self.rate = rate
        self.last_called = 0.0

    async def __call__(self, message: Message) -> bool:
        current_time = asyncio.get_event_loop().time()
        if current_time - self.last_called >= self.rate:
            self.last_called = current_time
            return True
        return False

# ---------------------------------------------------------------------
# Middleware Implementation
# ---------------------------------------------------------------------
class LoggingMiddleware:
    """Middleware for request logging and monitoring."""
    
    async def __call__(self, handler, event, data):
        # Pre-processing
        logger.info(f"📨 Update received: {getattr(event, 'update_id', 'unknown')}")
        start_time = asyncio.get_event_loop().time()
        
        try:
            result = await handler(event, data)
            processing_time = asyncio.get_event_loop().time() - start_time
            logger.info(f"✅ Update processed: {getattr(event, 'update_id', 'unknown')} in {processing_time:.2f}s")
            return result
        except Exception as e:
            logger.error(f"❌ Error processing update {getattr(event, 'update_id', 'unknown')}: {e}")
            raise

class AuthenticationMiddleware:
    """Middleware for user authentication and authorization."""
    
    async def __call__(self, handler, event, data):
        global app_config
        
        # Some events may not have from_user (like callback query wrappers), guard accordingly
        user = getattr(event, "from_user", None)
        if user:
            user_id = user.id
            data['user_id'] = user_id
            data['is_admin'] = app_config.is_admin(user_id) if app_config else False
            logger.debug(f"👤 User {user_id} - Admin: {data['is_admin']}")
        
        return await handler(event, data)

# ---------------------------------------------------------------------
# Dependency Injection Container
# ---------------------------------------------------------------------
class DIContainer:
    """Simple dependency injection container for global instances."""
    
    _instances: Dict[str, Any] = {}
    
    @classmethod
    def register(cls, key: str, instance: Any) -> None:
        """Register an instance with a key."""
        cls._instances[key] = instance
        logger.debug(f"📦 DI Container: Registered {key}")
    
    @classmethod
    def resolve(cls, key: str) -> Optional[Any]:
        """Resolve an instance by key."""
        return cls._instances.get(key)
    
    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        """Get all registered instances."""
        return cls._instances.copy()

# ---------------------------------------------------------------------
# Polling Setup for Local Development
# ---------------------------------------------------------------------
async def start_polling() -> None:
    """Start polling for local development when webhook is not configured."""
    global bot, dispatcher
    
    if not bot or not dispatcher:
        logger.error("❌ Bot or dispatcher not initialized for polling")
        return
    
    try:
        logger.info("🔄 Starting polling mode for local development...")
        # start_polling will run until cancelled
        await dispatcher.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("⏹️ Polling task cancelled")
    except Exception as e:
        logger.error(f"❌ Polling failed: {e}")

# ---------------------------------------------------------------------
# Binance API Initialization Function
# ---------------------------------------------------------------------

async def initialize_binance_api() -> Optional[Any]:
    """
    Initialize Binance API with proper factory pattern.
    
    Returns:
        BinanceAPI instance or None if trading disabled
        
    Raises:
        Exception: If initialization fails
    """
    global app_config
    
    if not app_config.ENABLE_TRADING:
        logger.info("ℹ️ Binance API not initialized (trading disabled)")
        return None
    
    try:
        logger.info("🔄 Initializing Binance API...")
        
        # ✅ Async çağrı ve user_id parametresi
        #binance_api_instance = await get_or_create_binance_api(user_id=None)
        #binance_api_instance = await get_or_create_binance_api(user_id=None)
        aggregator = BinanceAggregator.get_instance()

        logger.info("✅ Binance API initialized successfully")
        #return binance_api_instance
        return aggregator
        
    # YENİ:
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"🌐 Network error during Binance API init: {e}")
        raise ConnectionError(f"Binance API connection failed: {e}") from e
    except BinanceAuthenticationError as e:
        logger.error(f"🔐 Authentication error during Binance API init: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error during Binance API init: {e}")
        raise

# ---------------------------------------------------------------------
# Handler Loading with Debug Information
# ---------------------------------------------------------------------
async def initialize_handlers(dispatcher_instance: Dispatcher) -> Dict[str, int]:
    """
    Initialize handlers with comprehensive logging.
    
    Args:
        dispatcher_instance: Dispatcher instance to load handlers into
        
    Returns:
        Loading statistics
    """
    try:
        load_results = await load_handlers(dispatcher_instance)
        
        # ✅ DÜZELTME: Detaylı debug bilgisi
        logger.info(f"📊 Handler yükleme sonuçları: {load_results}")
        
        # Hangi handler'ların yüklendiğini logla
        if dispatcher_instance and hasattr(dispatcher_instance, 'sub_routers'):
            router_names = [getattr(router, 'name', 'unnamed') for router in dispatcher_instance.sub_routers]
            logger.info(f"📋 Yüklenen router'lar: {router_names}")
        
        if load_results.get("failed", 0) > 0:
            logger.warning(f"⚠️ {load_results['failed']} handlers failed to load")
        
        logger.info(f"✅ {load_results.get('loaded', 0)} handlers loaded successfully")
        return load_results
        
    # YENİ:
    except (ImportError, AttributeError) as e:
        logger.error(f"📁 Handler import error: {e}")
        return {"loaded": 0, "failed": 1, "error_type": "import"}
    except Exception as e:
        logger.error(f"❌ Unexpected handler loading error: {e}")
        return {"loaded": 0, "failed": 1, "error_type": "unknown"}

# ---------------------------------------------------------------------
# Lifespan Management (Async Context Manager)
# ---------------------------------------------------------------------

@asynccontextmanager
async def lifespan():
    """Manage application lifecycle with async context manager."""
    global bot, dispatcher, binance_api, app_config, polling_task
    
    try:
        # ✅ PERFORMANCE MONITORING CONTEXT
        ContextAwareLogger.add_context('lifecycle_phase', 'initialization')
        
        # Load configuration
        app_config = await get_config()
        ContextAwareLogger.add_context('trading_enabled', app_config.ENABLE_TRADING)
        ContextAwareLogger.add_context('webhook_mode', app_config.USE_WEBHOOK)
        
        # ✅ Aggregator başlat (binance_a)
        aggregator = await MultiUserBinanceAggregator.create()
        DIContainer.register('binance_aggregator', aggregator)
        
        # Initialize bot with default properties
        bot = await create_bot_instance()
        
        # ✅ PERFORMANCE METRICS'I BOT DATA'YA EKLE (bot oluşturulduktan sonra)
        if bot and hasattr(bot, 'data'):
            bot.data['performance_monitor'] = PerformanceMonitor.get_instance()
            logger.info("✅ Performance monitor added to bot.data")
        
        # Initialize dispatcher with main router and error handler
        main_router = Router()
        dispatcher = Dispatcher()
        dispatcher.include_router(main_router)
        dispatcher.errors.register(error_handler)
        
        # Register middleware
        dispatcher.update.outer_middleware(LoggingMiddleware())
        dispatcher.update.outer_middleware(AuthenticationMiddleware())
        logger.info("✅ Middleware registered: Logging, Authentication")
        
        # Register instances in DI container
        DIContainer.register('bot', bot)
        DIContainer.register('dispatcher', dispatcher)
        DIContainer.register('config', app_config)
        
        # Initialize Binance API (only if trading is enabled)
        binance_api = await initialize_binance_api()
        
        if binance_api:
            # Binance API'yi bot instance'ına da ekle (handler'lar için)
            bot.data["binance_api"] = binance_api
            DIContainer.register('binance_api', binance_api)
        
        # Load handlers with debug information
        await initialize_handlers(dispatcher)
        
        # Start polling if webhook is not configured (local development)
        if not app_config.USE_WEBHOOK:
            polling_task = asyncio.create_task(start_polling())
            logger.info("✅ Polling mode started for local development")
        
        # ✅ LIFECYCLE CONTEXT'İ TEMİZLE (yield'den önce)
        ContextAwareLogger.remove_context('lifecycle_phase')
        
        logger.info("✅ Application components initialized with enhanced logging")
        yield
        
    # YENİ:
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"🌐 Network error during app initialization: {e}")
        raise
    except BinanceAuthenticationError as e:
        logger.error(f"🔐 Auth error during app initialization: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Critical app initialization error: {e}", exc_info=True)
        raise
        
    finally:
        # ✅ LIFECYCLE CONTEXT'İ TEMİZLE (finally'de de temizle)
        ContextAwareLogger.remove_context('lifecycle_phase')
        
        # Cleanup resources
        cleanup_tasks = []
        
        # Cancel polling task if running
        if polling_task and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                logger.info("✅ Polling task cancelled successfully")
            except Exception as e:
                logger.warning(f"⚠️ Error cancelling polling task: {e}")
        
        if binance_api:
            cleanup_tasks.append(binance_api.close())
        
        if bot and hasattr(bot, 'session'):
            cleanup_tasks.append(bot.session.close())
        
        # Clear DI container
        DIContainer._instances.clear()
        
        if cleanup_tasks:
            results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(f"⚠️ Cleanup task failed: {result}")
        
        logger.info("🛑 Application resources cleaned up")
        


# ---------------------------------------------------------------------
# Health Check Endpoints
# ---------------------------------------------------------------------

async def health_check(request: web.Request) -> web.Response:
    """Enhanced health check with comprehensive metrics and timeout.
    # Farklı timeout değerleri:
    async with asyncio.timeout(5):   # ⚡ AGGRESSIVE - internal monitoring
    async with asyncio.timeout(10):  # ✅ BALANCED - production için ideal  
    async with asyncio.timeout(30):  # 🐌 LENIENT - development için
    """
    try:
        # ✅ 10 saniye timeout ekle
        
        
        
        async with asyncio.timeout(10):  # 10 second timeout
            return await _perform_health_check()
    except TimeoutError:
        logger.warning("⏰ Health check timeout - services responding slowly")
        return web.json_response({
            "status": "timeout", 
            "message": "Health check took too long",
            "timestamp": datetime.now().isoformat()
        }, status=503)
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return web.json_response({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "critical": True
        }, status=500)


async def _perform_health_check() -> web.Response:
    """Internal health check implementation without timeout.    """
    services_status = await check_services()
    
    # ✅ PERFORMANCE METRİKLERİNİ AL
    performance_metrics = {}
    try:
        monitor = PerformanceMonitor.get_instance()
        performance_summary = monitor.get_summary()
        performance_metrics = {
            'monitored_functions': performance_summary['total_functions_monitored'],
            'total_calls': performance_summary['total_calls'],
            'avg_call_time': round(performance_summary['average_call_time'], 3),
            'top_slow_functions': performance_summary['top_slow_functions']
        }
    except Exception as e:
        performance_metrics = {'error': str(e)}
        
    
    # ✅ AGGREGATOR DURUMU KONTROLÜ EKLE
    aggregator_status = "unknown"
    aggregator_metrics = {}
    try:
        aggregator = DIContainer.resolve('binance_aggregator')
        if aggregator:
            aggregator_status = "healthy"
            # Aggregator metrics'ını da ekle
            aggregator_metrics = aggregator.get_stats()
    except Exception as e:
        aggregator_status = f"error: {str(e)}"

    # Handler durumunu da kontrol et
    handler_status = {
        "total_handlers": len(dispatcher.sub_routers) if dispatcher else 0,
        "handlers_loaded": True if dispatcher and dispatcher.sub_routers else False,
        "router_names": [getattr(r, 'name', 'unnamed') for r in dispatcher.sub_routers] if dispatcher else []
    }
    
    # ✅ GELİŞMİŞ BOT METRİKLERİ
    bot_metrics = {
        "basic": {},
        "performance": {},
        "business": {}
    }
    
    if bot and hasattr(bot, 'data') and bot.data:
        # Basic metrics
        basic_metrics = bot.data.get('metrics', {})
        bot_metrics["basic"] = basic_metrics
        
        # Performance metrics
        if 'start_time' in bot.data:
            uptime = datetime.now() - bot.data['start_time']
            bot_metrics["performance"]["uptime_seconds"] = uptime.total_seconds()
            bot_metrics["performance"]["uptime_human"] = str(uptime).split('.')[0]
            bot_metrics["performance"]["start_time"] = bot.data['start_time'].isoformat()
        
        # Business metrics
        if 'user_sessions' in bot.data:
            bot_metrics["business"]["active_users"] = len(bot.data['user_sessions'])
            bot_metrics["business"]["user_ids"] = list(bot.data['user_sessions'].keys())[:10]
        
        if 'circuit_breakers' in bot.data:
            bot_metrics["business"]["active_circuit_breakers"] = len(bot.data['circuit_breakers'])
            
        # Binance API status
        if 'binance_api' in bot.data and bot.data['binance_api']:
            bot_metrics["business"]["binance_api_connected"] = True
        else:
            bot_metrics["business"]["binance_api_connected"] = False
    
    # ✅ MEMORY USAGE
    import psutil
    process = psutil.Process()
    memory_info = process.memory_info()
    
    return web.json_response({
        "status": "healthy",
        "service": "mbot1-telegram-bot",
        "platform": "render" if "RENDER" in os.environ else ("railway" if "RAILWAY" in os.environ else "local"),
        "timestamp": asyncio.get_event_loop().time(),
        "timestamp_iso": datetime.now().isoformat(),
        "handlers": handler_status,
        "services": services_status,
        "bot_metrics": bot_metrics,
        "performance_metrics": performance_metrics,
        "aggregator_status": aggregator_status,
        "aggregator_metrics": aggregator_metrics,
        "multi_user_enabled": True,  # ✅ YENİ
        "system": {
            "python_version": os.sys.version.split()[0],
            "aiohttp_version": aiohttp.__version__,
            "environment": "production" if not app_config.DEBUG else "development",
            "memory_usage_mb": round(memory_info.rss / 1024 / 1024, 2),
            "cpu_percent": psutil.cpu_percent(interval=0.1)
        }
    })
    


async def readiness_check(request: web.Request) -> web.Response:
    """Readiness check for Kubernetes and load balancers."""
    global bot, binance_api, app_config
    
    if bot and app_config:
        # Binance API is only required if trading is enabled
        if app_config.ENABLE_TRADING and not binance_api:
            return web.json_response({"status": "not_ready"}, status=503)
        
        # Check DI container health
        essential_services = ['bot', 'dispatcher', 'config']
        missing_services = [svc for svc in essential_services if not DIContainer.resolve(svc)]
        
        if missing_services:
            return web.json_response({
                "status": "not_ready",
                "missing_services": missing_services
            }, status=503)
            
        return web.json_response({"status": "ready"})
    else:
        return web.json_response({"status": "not_ready"}, status=503)

async def version_info(request: web.Request) -> web.Response:
    """Version and system information endpoint."""
    return web.json_response(await get_system_info())

# ---------------------------------------------------------------------
# Webhook Setup Functions
# ---------------------------------------------------------------------
async def on_startup(bot: Bot) -> None:
    """Execute on application startup."""
    global app_config
    aggregator = await MultiUserBinanceAggregator.create()
    # aggregator'ı global bir yerde saklayın
    
    try:
        # Set webhook if webhook is configured
        if app_config.USE_WEBHOOK and app_config.WEBHOOK_HOST:
            # Ensure WEBHOOK_HOST doesn't end with slash
            host = app_config.WEBHOOK_HOST.rstrip("/")
            token = get_telegram_token()
            webhook_url = f"{host}/webhook/{token}"
            await bot.delete_webhook(drop_pending_updates=True)
            
            # set secret_token if provided in config, else None
            secret = getattr(app_config, "WEBHOOK_SECRET", None) or None
            if secret:
                await bot.set_webhook(webhook_url, secret_token=secret)
            else:
                await bot.set_webhook(webhook_url)
            
            logger.info(f"✅ Webhook set successfully: {webhook_url}")
        else:
            logger.info("ℹ️ Webhook not configured, using polling mode")
        
        # Log health check URL (use configured host/port if available)
        try:
            host = app_config.WEBAPP_HOST
            port = app_config.WEBAPP_PORT
            logger.info(f"🌐 Health check: http://{host}:{port}/health")
        except Exception:
            logger.info("🌐 Health check endpoint available at /health")
        
        # 🔔 Adminlere "Bot başlatıldı" mesajı gönder
        for admin_id in get_admins():
            try:
                await bot.send_message(admin_id, "🤖 Bot başlatıldı ve çalışıyor!")
            except Exception as e:
                logger.warning(f"⚠️ Admin {admin_id} mesaj gönderilemedi: {e}")
    
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise

async def on_shutdown(bot: Bot) -> None:
    """Execute on application shutdown."""
    logger.info("🛑 Shutting down application...")
    
    try:
        # Delete webhook if it was set
        if app_config and app_config.USE_WEBHOOK and getattr(app_config, "WEBHOOK_HOST", None):
            try:
                await bot.delete_webhook()
                logger.info("✅ Webhook deleted")
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete webhook: {e}")
    except Exception as e:
        logger.warning(f"⚠️ on_shutdown encountered an error: {e}")

# ---------------------------------------------------------------------
# Main Application Factory
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
async def create_app() -> web.Application:
    """Create and configure aiohttp web application."""
    global bot, dispatcher, app_config
    
    # Initialize components inside lifespan context
    async with lifespan():
        # Create aiohttp app
        app = web.Application()
        
        # Register routes
        app.router.add_get("/", health_check)
        app.router.add_get("/health", health_check)
        app.router.add_get("/ready", readiness_check)
        app.router.add_get("/version", version_info)
        
        # Configure webhook handler using path /webhook/{token}
        if app_config.USE_WEBHOOK and app_config.WEBHOOK_HOST:
            webhook_handler = SimpleRequestHandler(
                dispatcher=dispatcher,
                bot=bot,
                secret_token=getattr(app_config, "WEBHOOK_SECRET", None) or None
            )
            
            # Use /webhook/{token} pattern
            webhook_route = "/webhook/{token}"
            webhook_handler.register(app, path=webhook_route)
            
            # GET endpoint for basic info/test (verifies token)
            async def webhook_info(request: web.Request):
                token = request.match_info.get('token', '')
                valid_token = get_telegram_token()
                
                if token == valid_token:
                    return web.json_response({
                        "status": "active",
                        "bot_token": "***********",  # Token gizlendi
                        "method": "POST",
                        "message": "Webhook is active. Use POST method for Telegram updates."
                    })
                else:
                    return web.json_response({
                        "status": "invalid_token",
                        "message": "The provided token is invalid."
                    }, status=400)
            
            app.router.add_get(webhook_route, webhook_info)
            logger.info(f"📨 Webhook endpoint configured: {webhook_route}")
        
        # Setup startup/shutdown hooks
        app.on_startup.append(lambda app: on_startup(bot))
        app.on_shutdown.append(lambda app: on_shutdown(bot))
        
        # Setup aiogram application (registers internal routes/handlers)
        setup_application(app, dispatcher, bot=bot)
        
        logger.info(f"🚀 Application configured on port {app_config.WEBAPP_PORT}")
        
        return app


# ---------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------
async def check_services() -> Dict[str, Any]:
    """Check connectivity to all external services."""
    global bot, binance_api, app_config
    
    services_status = {}
    
    # Check Telegram API
    try:
        if bot:
            me = await bot.get_me()
            services_status["telegram"] = {
                "status": "connected",
                "bot_username": me.username,
                "bot_id": me.id,
                "first_name": me.first_name
            }
        else:
            services_status["telegram"] = {"status": "disconnected", "error": "Bot not initialized"}
    except Exception as e:
        services_status["telegram"] = {
            "status": "disconnected",
            "error": str(e)
        }
    
    # Check Binance API (only if trading is enabled)
    if app_config.ENABLE_TRADING:
        try:
            if binance_api:
                ping_result = await binance_api.ping()
                services_status["binance"] = {
                    "status": "connected" if ping_result else "disconnected",
                    "ping": ping_result,
                    "trading_enabled": True
                }
            else:
                services_status["binance"] = {"status": "disconnected", "error": "Binance API not initialized", "trading_enabled": True}
        except Exception as e:
            services_status["binance"] = {
                "status": "disconnected",
                "error": str(e),
                "trading_enabled": True
            }
    else:
        services_status["binance"] = {
            "status": "disabled",
            "trading_enabled": False
        }
    
    return services_status

async def get_system_info() -> Dict[str, Any]:
    """Get system information and status."""
    global app_config
    
    return {
        "version": "1.0.0",
        "platform": "render" if "RENDER" in os.environ else "local",
        "environment": "production" if not app_config.DEBUG else "development",
        "python_version": os.sys.version,
        "aiohttp_version": aiohttp.__version__,
        "debug_mode": app_config.DEBUG,
        "trading_enabled": app_config.ENABLE_TRADING,
        "webhook_enabled": app_config.USE_WEBHOOK,
        "services": await check_services(),
        "di_container_services": list(DIContainer.get_all().keys())
    }

# ---------------------------------------------------------------------
# Polling Mode Initialization
# ---------------------------------------------------------------------
async def initialize_polling_mode() -> None:
    """Initialize and start polling mode."""
    global bot, dispatcher, binance_api, app_config
    
    try:
        # Bot ve Dispatcher oluştur
        bot = await create_bot_instance()

        
        dispatcher = Dispatcher()

        # Middleware ve handler'ları yükle
        dispatcher.update.outer_middleware(LoggingMiddleware())
        dispatcher.update.outer_middleware(AuthenticationMiddleware())
        dispatcher.errors.register(error_handler)

        # Binance API'yi initialize et
        binance_api = await initialize_binance_api()
        
        if binance_api:
            # Binance API'yi bot instance'ına ekle (handler'lar için)
            bot.data["binance_api"] = binance_api
            logger.info("✅ Binance API initialized and added to bot.data")

        # Handler'ları yükle (debug bilgisi ile)
        await initialize_handlers(dispatcher)

        logger.info("✅ Handler ve middleware yüklendi")

        # Webhook sil
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook silindi")

        # Polling başlat
        logger.info("🤖 Bot polling modunda başlatılıyor...")
        await dispatcher.start_polling(bot)

    # YENİ:
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"🌐 Network error in polling mode: {e}")
        raise
    except BinanceAuthenticationError as e:
        logger.error(f"🔐 Auth error in polling mode: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error in polling mode: {e}")
        raise
# ---------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------
async def main() -> None:
    global app_config, runner, bot, dispatcher
    
    try:
        # Config yükle
        app_config = await get_config()
        # ✅ Aggregator'ı burada oluşturma - lifespan'de yapılıyor
        
        logger.info(f"🏗️ Platform detected: {'Render' if 'RENDER' in os.environ else 'Local'}")
        logger.info(f"🌐 Environment: {'production' if not app_config.DEBUG else 'development'}")
        logger.info(f"🚪 Port: {app_config.WEBAPP_PORT}")
        logger.info(f"🏠 Host: {app_config.WEBAPP_HOST}")
        logger.info(f"🤖 Trading enabled: {app_config.ENABLE_TRADING}")
        logger.info(f"🌐 Webhook mode: {'enabled' if app_config.USE_WEBHOOK else 'disabled (polling)'}")

        if not app_config.USE_WEBHOOK:
            # ✅ POLLING MODU
            await initialize_polling_mode()
        else:
            # ✅ WEBHOOK MODU
            app = await create_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host=app_config.WEBAPP_HOST, port=app_config.WEBAPP_PORT)
            await site.start()

            logger.info(f"✅ Server started on port {app_config.WEBAPP_PORT}")
            logger.info(f"📊 Health check: http://{app_config.WEBAPP_HOST}:{app_config.WEBAPP_PORT}/health")

            await shutdown_event.wait()
            logger.info("👋 Shutdown signal received, exiting...")


    # YENİ:
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Application terminated by user")
        raise
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"🌐 Network critical error: {e}")
        raise
    except Exception as e:
        logger.critical(f"💥 Fatal error in main(): {e}")
        raise
        
    finally:
        # Cleanup
        if runner:
            await runner.cleanup()
        if bot and hasattr(bot, 'session'):
            await bot.session.close()
        logger.info("✅ Application cleanup completed")


if __name__ == "__main__":
    # Run the application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Application terminated by user")
    except Exception as e:
        logger.critical(f"💥 Fatal error: {e}")
        exit(1)