# analysis/risk.py
"""
Geliştirilmiş Risk Manager with Macro Market Analysis Integration
# ETF flow configden kaynak alacak şekilde olsun - gerçek API bulunana kadar

ÖZELLİKLER:
- Glassnode API entegrasyonu (SSR, Netflow için gerçek veri)
- Fear & Greed Index entegrasyonu  
- Makro sinyallerin risk skoruna ağırlıklı entegrasyonu
- Aiogram 3.x uyumlu router pattern
- Singleton pattern with async initialization
- Comprehensive type hints + PEP8 compliance
- Advanced error handling with circuit breaker
- Configurable parameters via dataclass
- Smart caching with TTL management

# 1. Basit kullanım
risk_manager = RiskManager()
await risk_manager.initialize(binance_api)
metrics = await risk_manager.combined_risk_score("BTCUSDT")

# 2. Context manager ile
async with RiskManager() as risk_manager:
    await risk_manager.initialize(binance_api)
    metrics = await risk_manager.combined_risk_score("BTCUSDT")

# 3. Global instance
risk_manager = await get_global_risk_manager(binance_api)

"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from math import erf, sqrt
from statistics import mean, pstdev
from typing import Dict, List, Optional, Sequence, Tuple, Union, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import aiohttp
import pandas as pd

# Conditional imports for optional dependencies
try:
    from aiogram import Router
    from aiogram.filters import Command
    from aiogram.types import Message
    AIOGRAM_AVAILABLE = True
except ImportError:
    AIOGRAM_AVAILABLE = False
    Router = None
    Command = None
    Message = None

logger = logging.getLogger(__name__)

# Config yönetimi için constants
DEFAULT_ATR_PERIOD = 14
DEFAULT_K_ATR_STOP = 3.0
DEFAULT_VAR_CONFIDENCE = 0.95
DEFAULT_MACRO_WEIGHT = 0.15
DEFAULT_MACRO_CACHE_TIMEOUT = 3600  # 1 saat cache
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3

@dataclass
class RiskManagerConfig:
    """RiskManager yapılandırma sınıfı"""
    atr_period: int = DEFAULT_ATR_PERIOD
    k_atr_stop: float = DEFAULT_K_ATR_STOP
    var_confidence: float = DEFAULT_VAR_CONFIDENCE
    macro_weight: float = DEFAULT_MACRO_WEIGHT
    macro_cache_timeout: int = DEFAULT_MACRO_CACHE_TIMEOUT
    glassnode_api_key: Optional[str] = None
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    enable_macro_analysis: bool = True
    enable_advanced_metrics: bool = True

@dataclass
class MacroMarketSignal:
    """Makro piyasa sinyallerini tutan veri sınıfı"""
    ssr_score: float = 0.0  # -1 (bearish) to +1 (bullish)
    netflow_score: float = 0.0
    etf_flow_score: float = 0.0
    fear_greed_score: float = 0.0
    overall_score: float = 0.0
    confidence: float = 0.0  # Sinyal güvenilirliği 0-1 arası
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class RiskMetrics:
    """Risk metriklerini tutan veri sınıfı"""
    symbol: str
    price: float = 0.0
    atr: float = 0.0
    vol_metric: float = 0.0
    liquidation_proximity: float = 0.0
    correlation_penalty: float = 0.0
    portfolio_var: float = 0.0
    macro_score: float = 0.0
    macro_confidence: float = 0.0
    score: float = 0.0
    score_without_macro: float = 0.0
    market_regime: str = "NEUTRAL"
    recommendation: str = "NEUTRAL"
    timestamp: datetime = field(default_factory=datetime.now)

class CircuitBreaker:
    """Basit circuit breaker implementasyonu"""
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open

    def record_success(self):
        """Başarılı işlem kaydı"""
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"

    def record_failure(self):
        """Başarısız işlem kaydı"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def can_execute(self) -> bool:
        """İşlem yapılabilir mi?"""
        if self.state == "closed":
            return True
        elif self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half-open"
                return True
            return False
        else:  # half-open
            return True

class RiskManager:
    """
    Geliştirilmiş Risk Manager with macro market analysis integration.
    
    Singleton pattern with async context manager support.
    """

    _instance: Optional[RiskManager] = None
    _initialized: bool = False
    _initialization_lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern implementation"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, binance_api=None, config: Optional[RiskManagerConfig] = None):
        """Initialize risk manager (thread-safe)"""
        if not self._initialized:
            self._binance_api = binance_api
            self.config = config or RiskManagerConfig()
            self._session: Optional[aiohttp.ClientSession] = None
            self._circuit_breaker = CircuitBreaker()
            self._cache: Dict[str, Tuple[Any, float]] = {}
            self._initialized = True
            logger.info("✅ RiskManager initialized successfully")

    async def initialize(self, binance_api, config: Optional[RiskManagerConfig] = None):
        """Async initialization method"""
        async with self._initialization_lock:
            if not self._initialized:
                self._binance_api = binance_api
                self.config = config or RiskManagerConfig()
                self._session = None
                self._circuit_breaker = CircuitBreaker()
                self._cache = {}
                self._initialized = True
                logger.info("✅ RiskManager async initialization completed")

    @classmethod
    async def create(cls, binance_api, config: Optional[RiskManagerConfig] = None) -> RiskManager:
        """Factory method for async creation"""
        instance = cls()
        await instance.initialize(binance_api, config)
        return instance

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure HTTP session is available"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _cached_get(self, key: str, ttl: int) -> Optional[Any]:
        """Get cached data with TTL"""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < ttl:
                return data
            else:
                del self._cache[key]
        return None

    async def _cached_set(self, key: str, data: Any):
        """Set data in cache"""
        self._cache[key] = (data, time.time())

    async def _retry_request(self, func, *args, max_retries: int = None, **kwargs) -> Any:
        """Retry mechanism with exponential backoff"""
        max_retries = max_retries or self.config.max_retries
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                if not self._circuit_breaker.can_execute():
                    raise Exception("Circuit breaker is open")
                
                result = await func(*args, **kwargs)
                self._circuit_breaker.record_success()
                return result
                
            except Exception as e:
                last_exception = e
                self._circuit_breaker.record_failure()
                
                if attempt == max_retries - 1:
                    break
                    
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"⚠️ Request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)
        
        logger.error(f"❌ All retries failed: {last_exception}")
        raise last_exception

    # -------------------------
    # GLASSNODE ENTEGRASYONU
    # -------------------------

    async def _fetch_glassnode_data(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """Glassnode API'den veri çekme"""
        if not self.config.glassnode_api_key:
            logger.warning("Glassnode API key not configured")
            return None

        async def fetch():
            session = await self._ensure_session()
            url = f"https://api.glassnode.com/v1/{endpoint}"
            params['api_key'] = self.config.glassnode_api_key
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"API error: {response.status}")

        return await self._retry_request(fetch)

    async def get_ssr_metric(self) -> float:
        """Gerçek SSR metriği - Glassnode implementasyonu"""
        cache_key = "ssr_metric"
        cached = await self._cached_get(cache_key, 3600)  # 1 hour cache
        if cached is not None:
            return cached

        try:
            data = await self._fetch_glassnode_data("metrics/indicators/ssr", {
                'a': 'BTC', 'i': '24h'
            })
            
            if data and len(data) > 0:
                latest_ssr = data[-1]['v']
                # Normalize: Tarihsel verilere göre ayarlanabilir
                if latest_ssr > 20: 
                    score = -1.0
                elif latest_ssr < 5: 
                    score = 1.0
                else:
                    score = (10 - latest_ssr) / 5
                
                await self._cached_set(cache_key, score)
                return score
                
        except Exception as e:
            logger.error(f"SSR metric error: {e}")
        
        return 0.0

    async def get_netflow_metric(self) -> float:
        """Gerçek Netflow metriği - Glassnode implementasyonu"""
        cache_key = "netflow_metric"
        cached = await self._cached_get(cache_key, 3600)
        if cached is not None:
            return cached

        try:
            data = await self._fetch_glassnode_data("metrics/transactions/transfers_volume_exchanges_net", {
                'a': 'BTC', 'i': '24h'
            })
            
            if data and len(data) > 0:
                latest_netflow = data[-1]['v']
                # Normalize
                if latest_netflow > 1000: 
                    score = -1.0
                elif latest_netflow < -1000: 
                    score = 1.0
                else:
                    score = -latest_netflow / 1000
                
                await self._cached_set(cache_key, score)
                return score
                
        except Exception as e:
            logger.error(f"Netflow metric error: {e}")
        
        return 0.0

    async def get_fear_greed_index(self) -> float:
        """Fear & Greed Index - Alternative.me API'si"""
        cache_key = "fear_greed"
        cached = await self._cached_get(cache_key, 3600)
        if cached is not None:
            return cached

        async def fetch():
            session = await self._ensure_session()
            url = "https://api.alternative.me/fng/"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    score = int(data['data'][0]['value'])
                    return (score - 50) / 50  # 0-100 → -1 to +1
                raise Exception(f"API error: {response.status}")

        try:
            score = await self._retry_request(fetch)
            await self._cached_set(cache_key, score)
            return score
        except Exception as e:
            logger.error(f"Fear & Greed index error: {e}")
            return 0.0

    async def get_macro_market_signal(self) -> MacroMarketSignal:
        """Tüm makro metrikleri toplu olarak hesaplar"""
        cache_key = "macro_signal"
        cached = await self._cached_get(cache_key, self.config.macro_cache_timeout)
        if cached is not None:
            return cached

        if not self.config.enable_macro_analysis:
            return MacroMarketSignal()

        try:
            # Paralel olarak tüm metrikleri hesapla
            ssr, netflow, fear_greed = await asyncio.gather(
                self.get_ssr_metric(),
                self.get_netflow_metric(),
                self.get_fear_greed_index(),
                return_exceptions=True
            )
            
            # Exception handling
            ssr = ssr if not isinstance(ssr, Exception) else 0.0
            netflow = netflow if not isinstance(netflow, Exception) else 0.0
            fear_greed = fear_greed if not isinstance(fear_greed, Exception) else 0.0
            
            # ETF flow placeholder
            etf_flow = 0.0
            
            overall_score = (ssr + netflow + fear_greed + etf_flow) / 4
            
            signal = MacroMarketSignal(
                ssr_score=ssr,
                netflow_score=netflow,
                etf_flow_score=etf_flow,
                fear_greed_score=fear_greed,
                overall_score=overall_score,
                confidence=0.7,
                timestamp=datetime.now()
            )
            
            await self._cached_set(cache_key, signal)
            return signal
            
        except Exception as e:
            logger.error(f"Macro market signal error: {e}")
            return MacroMarketSignal()

    # -------------------------
    # TEMEL RİSK METRİKLERİ
    # -------------------------

    async def compute_atr(self, symbol: str, interval: str = "1h", futures: bool = False) -> float:
        """Average True Range hesaplama"""
        if not self._binance_api:
            logger.error("Binance API not available for ATR calculation")
            return 0.0

        try:
            klines = await self._binance_api.get_klines(symbol, interval, limit=20, futures=futures)
            if not klines:
                return 0.0
                
            high_prices = [float(k[2]) for k in klines]
            low_prices = [float(k[3]) for k in klines]
            close_prices = [float(k[4]) for k in klines]
            
            true_ranges = []
            for i in range(1, len(klines)):
                high_low = high_prices[i] - low_prices[i]
                high_close = abs(high_prices[i] - close_prices[i-1])
                low_close = abs(low_prices[i] - close_prices[i-1])
                true_ranges.append(max(high_low, high_close, low_close))
            
            return mean(true_ranges) if true_ranges else 0.0
        except Exception as e:
            logger.error(f"ATR calculation error for {symbol}: {e}")
            return 0.0

    async def liquidation_proximity(self, symbol: str, position: Optional[dict]) -> float:
        """Liquidation proximity hesaplama"""
        if not position or not self._binance_api:
            return 1.0
            
        try:
            price = await self._binance_api.get_price(symbol, futures=True)
            entry_price = float(position.get("entryPrice", price))
            leverage = float(position.get("leverage", 1.0))
            
            if leverage <= 0 or entry_price <= 0:
                return 1.0
                
            price_ratio = min(price / entry_price, entry_price / price)
            safety_margin = 0.1  # 10% safety margin
            
            return max(0.0, min(1.0, (price_ratio - safety_margin) / (1 - safety_margin)))
        except Exception as e:
            logger.error(f"Liquidation proximity calculation error for {symbol}: {e}")
            return 1.0

    async def correlation_risk(self, symbol: str, portfolio_symbols: Sequence[str]) -> float:
        """Correlation risk hesaplama"""
        if len(portfolio_symbols) < 2:
            return 0.0
            
        try:
            # Basit korelasyon hesaplama (gerçek implementasyon için daha karmaşık logic gerekli)
            return 0.3
        except Exception as e:
            logger.error(f"Correlation risk calculation error for {symbol}: {e}")
            return 0.5

    async def portfolio_var(self, symbols: List[str]) -> float:
        """Portfolio Value at Risk hesaplama"""
        if not symbols:
            return 0.0
            
        try:
            # Basit VaR hesaplama
            return 0.05  # 5% VaR
        except Exception as e:
            logger.error(f"Portfolio VaR calculation error: {e}")
            return 0.1

    # -------------------------
    # GELİŞMİŞ RİSK SKORU
    # -------------------------

    async def combined_risk_score(
        self,
        symbol: str,
        account_positions: Optional[List[dict]] = None,
        portfolio_symbols: Optional[Sequence[str]] = None,
        include_macro: bool = True
    ) -> RiskMetrics:
        """
        Geliştirilmiş risk skoru - makro piyasa sinyallerini entegre eder.
        """
        metrics = RiskMetrics(symbol=symbol.upper())
        
        try:
            if not self._binance_api:
                logger.error("Binance API not available for risk calculation")
                return metrics

            # Temel fiyat verileri
            price = await self._binance_api.get_price(symbol, futures=False)
            if not price:
                return metrics
                
            metrics.price = price

            # Mikro metrikleri paralel hesapla
            atr_task = self.compute_atr(symbol)
            liq_task = self.liquidation_proximity(symbol, 
                next((p for p in account_positions or [] 
                     if p.get("symbol", "").upper() == symbol.upper()), None)
            )
            corr_task = self.correlation_risk(symbol, portfolio_symbols or [])
            var_task = self.portfolio_var(list(portfolio_symbols or [symbol]))
            macro_task = self.get_macro_market_signal() if include_macro else None

            # Tüm hesaplamaları bekle
            results = await asyncio.gather(
                atr_task, liq_task, corr_task, var_task,
                return_exceptions=True
            )
            
            # Sonuçları işle
            metrics.atr = results[0] if not isinstance(results[0], Exception) else 0.0
            metrics.liquidation_proximity = results[1] if not isinstance(results[1], Exception) else 1.0
            metrics.correlation_penalty = results[2] if not isinstance(results[2], Exception) else 0.5
            metrics.portfolio_var = results[3] if not isinstance(results[3], Exception) else 0.1

            # Makro sinyal
            if macro_task:
                macro_signal = await macro_task
                metrics.macro_score = macro_signal.overall_score
                metrics.macro_confidence = macro_signal.confidence

            # Volatilite metriği
            metrics.vol_metric = min(1.0, (metrics.price / metrics.atr) / 100.0) if metrics.atr > 0 else 0.0

            # Ağırlıklı skor hesaplama
            weights = {
                'vol': 0.30, 'liq': 0.20, 'corr': 0.20, 'var': 0.20, 'macro': 0.10
            }
            
            scores = {
                'vol': metrics.vol_metric,
                'liq': metrics.liquidation_proximity,
                'corr': 1.0 - metrics.correlation_penalty,
                'var': 1.0 - metrics.portfolio_var,
                'macro': metrics.macro_score
            }

            total_score = sum(weights[key] * scores[key] for key in weights)
            metrics.score = max(0.0, min(1.0, total_score))
            metrics.score_without_macro = metrics.score - weights['macro'] * scores['macro']

            # Piyasa rejimi
            if metrics.macro_score > 0.3:
                metrics.market_regime = "BULL"
                metrics.recommendation = "AGGRESSIVE"
            elif metrics.macro_score < -0.3:
                metrics.market_regime = "BEAR" 
                metrics.recommendation = "CONSERVATIVE"
            else:
                metrics.market_regime = "NEUTRAL"
                metrics.recommendation = "NEUTRAL"

            logger.info(f"✅ Risk skoru {symbol}: {metrics.score:.3f} (macro: {metrics.macro_score:.3f})")
            
        except Exception as e:
            logger.error(f"❌ Risk skoru hesaplama hatası {symbol}: {e}")
            
        return metrics

    # -------------------------
    # CLEANUP VE CONTEXT MANAGER
    # -------------------------

    async def close(self):
        """Resource cleanup"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        logger.info("✅ RiskManager resources cleaned up")

    async def __aenter__(self) -> "RiskManager":
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit"""
        await self.close()

# -------------------------
# AIOGRAM 3.x ROUTER ENTEGRASYONU
# -------------------------

def create_risk_router() -> Optional[Router]:
    """Aiogram 3.x router factory function"""
    if not AIOGRAM_AVAILABLE:
        logger.warning("Aiogram not available - risk router disabled")
        return None

    router = Router()

    @router.message(Command("advanced_risk"))
    async def cmd_advanced_risk(message: Message) -> None:
        """Geliştirilmiş risk analiz komutu"""
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.answer("Usage: /advanced_risk SYMBOL (e.g. /advanced_risk BTCUSDT)")
            return

        symbol = parts[1].upper()
        try:
            binance_api = getattr(message.bot, "binance_api", None)
            if binance_api is None:
                await message.answer("❌ Binance API not configured.")
                return
                
            # Config'i environment'dan al
            config = RiskManagerConfig(
                glassnode_api_key=os.getenv("GLASSNODE_API_KEY"),
                macro_weight=float(os.getenv("MACRO_WEIGHT", DEFAULT_MACRO_WEIGHT))
            )
                
            async with RiskManager() as risk_manager:
                await risk_manager.initialize(binance_api, config)
                metrics = await risk_manager.combined_risk_score(
                    symbol, 
                    portfolio_symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
                    include_macro=True
                )
                
                macro = await risk_manager.get_macro_market_signal()
                
                text = (
                    f"🎯 **Gelişmiş Risk Analizi - {metrics.symbol}**\n\n"
                    f"📊 **Temel Metrikler:**\n"
                    f"• Price: ${metrics.price:,.2f}\n"
                    f"• ATR: {metrics.atr:.4f}\n"
                    f"• Volatility Score: {metrics.vol_metric:.3f}\n"
                    f"• Liquidation Safety: {metrics.liquidation_proximity:.3f}\n"
                    f"• Correlation Penalty: {metrics.correlation_penalty:.3f}\n"
                    f"• Portfolio VaR: {metrics.portfolio_var:.3f}\n\n"
                    f"🌍 **Makro Piyasa:**\n"
                    f"• SSR Score: {macro.ssr_score:.3f}\n"
                    f"• Netflow Score: {macro.netflow_score:.3f}\n"
                    f"• Fear & Greed: {macro.fear_greed_score:.3f}\n"
                    f"• Overall Macro: {macro.overall_score:.3f}\n"
                    f"• Market Regime: {metrics.market_regime}\n\n"
                    f"📈 **Risk Skorları:**\n"
                    f"• Micro-Only Score: {metrics.score_without_macro:.3f}\n"
                    f"• Final Score: {metrics.score:.3f}\n"
                    f"• Recommendation: {metrics.recommendation}\n"
                    f"• Confidence: {metrics.macro_confidence:.3f}"
                )
                
                await message.answer(text, parse_mode="Markdown")
                
        except Exception as e:
            logger.exception(f"Advanced risk command error: {e}")
            await message.answer("❌ Risk analiz hatası. Loglara bakın.")

    @router.message(Command("risk_settings"))
    async def cmd_risk_settings(message: Message) -> None:
        """Risk ayarlarını göster"""
        try:
            config = RiskManagerConfig(
                glassnode_api_key=os.getenv("GLASSNODE_API_KEY"),
                macro_weight=float(os.getenv("MACRO_WEIGHT", DEFAULT_MACRO_WEIGHT))
            )
            
            text = (
                "⚙️ **Risk Manager Ayarları**\n\n"
                f"• ATR Period: {config.atr_period}\n"
                f"• K ATR Stop: {config.k_atr_stop}\n"
                f"• VaR Confidence: {config.var_confidence}\n"
                f"• Macro Weight: {config.macro_weight}\n"
                f"• Macro Analysis: {'✅' if config.enable_macro_analysis else '❌'}\n"
                f"• Glassnode API: {'✅' if config.glassnode_api_key else '❌'}\n"
                f"• Request Timeout: {config.request_timeout}s\n"
                f"• Max Retries: {config.max_retries}"
            )
            
            await message.answer(text, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Risk settings command error: {e}")
            await message.answer("❌ Ayarlar gösterilemedi.")

    return router

# -------------------------
# GLOBAL INSTANCE MANAGEMENT
# -------------------------

_global_risk_manager: Optional[RiskManager] = None
_global_lock = asyncio.Lock()

async def get_global_risk_manager(binance_api=None, config: Optional[RiskManagerConfig] = None) -> RiskManager:
    """Global RiskManager instance getter"""
    global _global_risk_manager
    
    async with _global_lock:
        if _global_risk_manager is None:
            _global_risk_manager = RiskManager()
            await _global_risk_manager.initialize(binance_api, config)
        return _global_risk_manager

async def close_global_risk_manager():
    """Global RiskManager cleanup"""
    global _global_risk_manager
    
    if _global_risk_manager is not None:
        await _global_risk_manager.close()
        _global_risk_manager = None

# Context manager for temporary usage
@asynccontextmanager
async def risk_manager_context(binance_api=None, config: Optional[RiskManagerConfig] = None):
    """Context manager for temporary RiskManager usage"""
    risk_manager = await get_global_risk_manager(binance_api, config)
    try:
        yield risk_manager
    finally:
        await close_global_risk_manager()

# Router instance for easy import
risk_router = create_risk_router()