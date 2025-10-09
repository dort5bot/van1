# analysis/onchain.py - OPTİMAL TTL STRATEJİSİ İLE GÜNCELLENMİŞ
"""
On-Chain & Makro Analiz Modülü - Optimal TTL Stratejili
=======================================================
Akıllı cache yönetimi ile performans ve güncellik dengesi
"""


import asyncio
import logging
import time
import hashlib
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel, validator
from typing import Optional as Opt
from functools import wraps


# Data provider import
from utils.data_sources.data_provider import DataProvider



# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION - External API Endpoints and Parameters
# =============================================================================

CONFIG = {
    # Glassnode API endpoints (requires API key)
    "glassnode": {
        "base_url": "https://api.glassnode.com/v1",
        "endpoints": {
            "stablecoin_supply": "/metrics/supply/current",
            "exchange_flows": "/metrics/transactions/transfers_volume_exchange_net",
            "nvt_ratio": "/metrics/indicators/nvt",
            "mvrv_zscore": "/metrics/indicators/mvrv_zscore",
            "sopr": "/metrics/indicators/sopr",
            "realized_profit_loss": "/metrics/indicators/net_realized_profit_loss",
            "exchange_whale_ratio": "/metrics/transactions/transfers_volume_to_exchanges_sum"
        },
        "required_tier": ["advanced", "professional"]  # Glassnode tier requirements
    },
    
    # CryptoQuant API endpoints (requires API key)
    "cryptoquant": {
        "base_url": "https://api.cryptoquant.com/v1",
        "endpoints": {
            "exchange_netflow": "/btc/exchange-flows/netflow",
            "funding_rates": "/btc/futures/funding-rate",
            "all_exchanges_flow": "/btc/exchange-flows/all-exchanges-flow",
            "miner_to_exchange": "/btc/miner-flows/miner-to-exchange"
        }
    },
    
    # Farside ETF Flows (no API key required)
    "farside": {
        "base_url": "https://farside.co.uk",
        "endpoints": {
            "etf_flows": "/?p=997",
            "etf_net_flow": "/?p=997"
        }
    },
    
    # Timeframes for analysis
    "timeframes": {
        "short_term": "24h",
        "medium_term": "7d",
        "long_term": "30d"
    },
    
    # Weight configuration for composite score calculation
    "weights": {
        "stablecoin_flow": 0.25,
        "etf_flow": 0.30,
        "exchange_netflow": 0.20,
        "mvrv_zscore": 0.15,
        "sopr": 0.10
    },
    
    #Metric Priority Sistemi
    "metric_priority": {
        "critical": ["etf_flow", "stablecoin_flow"],
        "high": ["mvrv_zscore", "exchange_netflow"], 
        "medium": ["sopr", "whale_ratio"],
        "low": ["nvt_ratio", "miner_flows"]
    },
    
    # Thresholds for metric normalization
    "thresholds": {
        "etf_flow_positive": 100,  # $100M positive flow
        "etf_flow_negative": -50,  # $50M negative flow
        "mvrv_zscore_high": 2.0,
        "mvrv_zscore_low": -2.0,
        "sopr_bullish": 1.0,
        "sopr_bearish": 0.95
    }
}



# =============================================================================
# CONFIGURATION - External API Endpoints and Parameters- Data Validation ve Schema Doğrulama
# =============================================================================
class MetricData(BaseModel):
    """Metrik veri modeli"""
    value: float
    timestamp: str
    source: str
    confidence: float = 0.8
    is_fallback: bool = False
    
    @validator('value')
    def validate_range(cls, v):
        if not (-1e6 <= v <= 1e6):  # Makul finansal range
            raise ValueError(f'Value {v} out of expected range')
        return v
    
    @validator('timestamp')
    def validate_timestamp(cls, v):
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
            return v
        except ValueError:
            raise ValueError('Invalid timestamp format')

def validate_metric_data(data: Dict[str, Any], metric_name: str) -> Opt[MetricData]:
    """Metrik verisini validate et"""
    try:
        return MetricData(**data)
    except Exception as e:
        logger.warning(f"Data validation failed for {metric_name}: {e}")
        return None


async def fetch_metrics_with_priority(symbol: str, priority_level: str) -> List[str]:
    """Priority level'a göre metrikleri getir"""
    metrics = CONFIG.get("metric_priority", {}).get(priority_level, [])
    tasks = []
    
    for metric in metrics:
        if metric == "etf_flow":
            tasks.append(fetch_etf_flow(symbol))
        elif metric == "stablecoin_flow":
            tasks.append(fetch_stablecoin_flow(symbol))
        # ... diğer metrikler
    
    return await asyncio.gather(*tasks, return_exceptions=True)


# =============================================================================
# CACHE MANAGEMENT - In-memory cache for API responses
# =============================================================================



class MetricFrequency(Enum):
    """Metrik değişim frekansı sınıflandırması"""
    HIGH = "high"      # 1-5 dakikada değişir (ETF flow, funding)
    MEDIUM = "medium"  # 5-30 dakikada değişir (exchange flows)
    LOW = "low"        # 30+ dakikada değişir (MVRV, whale ratio)
    STATIC = "static"  # Saatler/günlerde değişir (supply metrics)

OPTIMAL_TTL_CONFIG = {
    MetricFrequency.HIGH: {
        "ttl_seconds": 120,      # 2 dakika
        "metrics": [
            "etf_flow", "funding_rate", "liquidations", 
            "orderbook_imbalance", "tick_volume"
        ],
        "description": "Anlık piyasa hareketlerinden hızlı etkilenir"
    },
    
    MetricFrequency.MEDIUM: {
        "ttl_seconds": 300,      # 5 dakika  
        "metrics": [
            "exchange_netflow", "stablecoin_flow", "sopr",
            "open_interest", "long_short_ratio"
        ],
        "description": "Gün içinde makul değişim gösterir"
    },
    
    MetricFrequency.LOW: {
        "ttl_seconds": 1800,     # 30 dakika
        "metrics": [
            "mvrv_zscore", "nvt_ratio", "whale_ratio",
            "hash_rate", "miner_flows", "realized_profit_loss"
        ],
        "description": "Yapısal göstergeler, yavaş değişir"
    },
    
    MetricFrequency.STATIC: {
        "ttl_seconds": 86400,    # 24 saat
        "metrics": [
            "total_supply", "max_supply", "circulating_supply",
            "genesis_date", "block_reward"
        ],
        "description": "Neredeyse hiç değişmeyen veriler"
    }
}




# ✅ ÖNERİ: RATE LIMITING DECORATOR - SmartOnChainCache'den ÖNCE

def rate_limited(requests_per_minute: int = 60):
    """Rate limiting decorator"""
    def decorator(func):
        last_called = [0.0]
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            left_to_wait = 60 / requests_per_minute - elapsed
            
            if left_to_wait > 0:
                logger.debug(f"Rate limiting: waiting {left_to_wait:.2f}s")
                await asyncio.sleep(left_to_wait)
            
            last_called[0] = time.time()
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# =============================================================================
# AKILLI CACHE SİSTEMİ + OPTIMAL TTL
# =============================================================================

class SmartOnChainCache:
    """
    Metrik frekansına göre optimal TTL uygulayan akıllı cache sistemi
    """

    def __init__(self, max_memory_mb: int = 100):  # Memory limit ekle
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._timestamps: Dict[str, float] = {}
        self._access_count: Dict[str, int] = {}
        self._metric_types: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._max_memory_mb = max_memory_mb
        self._estimated_memory = 0
        
        # Performans monitoring
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        
        self._volatility_index = 0.5  # Varsayılan volatilite
    
    def _estimate_size(self, data: Any) -> int:
        """Verinin tahmini boyutunu hesapla"""
        try:
            return len(str(data).encode('utf-8'))
        except:
            return 1024  # Varsayılan 1KB
    
    
    def _get_ttl_for_metric(self, metric_name: str) -> int:
        """Metrik için base TTL'yi getir - BU METOT EKSİK"""
        frequency = self._get_metric_frequency(metric_name)
        return OPTIMAL_TTL_CONFIG[frequency]["ttl_seconds"]
    
    async def _aggressive_cleanup(self):
        """Aggressive cache temizleme"""
        current_time = time.time()
        keys_to_remove = []
        
        # En eski ve en az kullanılan entry'leri bul
        for key, timestamp in self._timestamps.items():
            metric_name = self._metric_types.get(key, "unknown")
            ttl = self._get_ttl_for_metric(metric_name)
            
            # Daha agresif temizleme
            is_old = current_time - timestamp > ttl * 2  # 2x TTL
            is_unused = self._access_count.get(key, 0) == 0
            
            if is_old or is_unused:
                keys_to_remove.append(key)
        
        # İlk 50 entry'yi temizle (en eskiler)
        if not keys_to_remove and self._timestamps:
            sorted_keys = sorted(self._timestamps.keys(), 
                               key=lambda k: self._timestamps[k])
            keys_to_remove = sorted_keys[:50]
        
        for key in keys_to_remove:
            await self._remove_key(key)
        
        if keys_to_remove:
            logger.warning(f"Aggressive cache cleanup: {len(keys_to_remove)} entries removed")
            
    
    def _get_metric_frequency(self, metric_name: str) -> MetricFrequency:
        """Metrik adına göre frekans sınıfını bul"""
        metric_name_lower = metric_name.lower()
        
        for freq, config in OPTIMAL_TTL_CONFIG.items():
            if any(metric in metric_name_lower for metric in config["metrics"]):
                return freq
        
        # Varsayılan olarak medium frequency
        return MetricFrequency.MEDIUM


    def update_volatility_index(self, index: float):
        """Piyasa volatilite indeksini güncelle"""
        self._volatility_index = max(0.0, min(1.0, index))
    
    def get_dynamic_ttl(self, metric_name: str) -> int:
        """Volatiliteye göre dynamic TTL hesapla"""
        base_ttl = self._get_ttl_for_metric(metric_name)
        
        # Yüksek volatilite durumunda TTL'yi kısalt
        if self._volatility_index > 0.7:  # High volatility
            adaptive_ttl = max(30, base_ttl // 2)
            logger.debug(f"High volatility: {metric_name} TTL {base_ttl} -> {adaptive_ttl}")
            return adaptive_ttl
        elif self._volatility_index < 0.3:  # Low volatility
            adaptive_ttl = min(86400, base_ttl * 2)  # Max 1 gün
            return adaptive_ttl
        
        return base_ttl
        
    



    async def get(self, key: str, metric_name: str) -> Optional[Dict[str, Any]]:
        """
        Optimal TTL ile cache'den veri getir
        Args:
            key: Cache key
            metric_name: Metrik adı (TTL belirlemek için)
        Returns:
            Cache'lenmiş veri veya None
        """
        async with self._lock:
            if key in self._cache:
                ttl = self.get_dynamic_ttl(metric_name)
                current_time = time.time()
                
                # TTL kontrolü
                if current_time - self._timestamps[key] < ttl:
                    self._access_count[key] = self._access_count.get(key, 0) + 1
                    self._hits += 1
                    logger.info(f"Cache HIT: {key} (TTL: {ttl}s)")
                    return self._cache[key]
                else:
                    # TTL dolmuş - temizle
                    await self._remove_key(key)
                    self._misses += 1
                    logger.info(f"Cache MISS (TTL expired): {key}")  # DÜZELTİLDİ
            else:
                self._misses += 1
                logger.info(f"Cache MISS (not found): {key}")  # EKLENDİ
            
            return None
            


    async def set(self, key: str, data: Dict[str, Any], metric_name: str):
        """
        Metrik tipine göre cache'e veri kaydet
        
        Args:
            key: Cache key
            data: Cache'lenecek veri
            metric_name: Metrik adı
        """
        # Memory kontrolü
        data_size = self._estimate_size(data)
        if self._estimated_memory + data_size > self._max_memory_mb * 1024 * 1024:
            await self._aggressive_cleanup()
        
        async with self._lock:
            self._cache[key] = data
            self._timestamps[key] = time.time()
            self._access_count[key] = 0
            self._metric_types[key] = metric_name
            
            ttl = self._get_ttl_for_metric(metric_name)
            logger.info(f"Cache SET: {key} (TTL: {ttl}s, Metric: {metric_name})")
            
            # Cache cleanup tetikle
            if len(self._cache) > 500:  # Entry limiti
                await self._cleanup_old_entries()
    
    async def _remove_key(self, key: str):
        """Key'i cache'den temizle"""
        if key in self._cache:
            del self._cache[key]
            del self._timestamps[key]
            del self._access_count[key]
            if key in self._metric_types:
                del self._metric_types[key]
            self._evictions += 1
    
    async def _cleanup_old_entries(self):
        """Eski ve az kullanılan entry'leri temizle"""
        current_time = time.time()
        keys_to_remove = []
        
        for key, timestamp in self._timestamps.items():
            metric_name = self._metric_types.get(key, "unknown")
            ttl = self._get_ttl_for_metric(metric_name)
            
            # Temizleme kriterleri:
            is_very_old = current_time - timestamp > ttl * 3  # 3x TTL
            is_rarely_used = self._access_count.get(key, 0) < 2  # 2'den az erişim
            
            if is_very_old or is_rarely_used:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            await self._remove_key(key)
        
        if keys_to_remove:
            logger.info(f"Cache cleanup: {len(keys_to_remove)} entries removed")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Cache istatistiklerini getir"""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0
        
        # Metric frekansına göre dağılım
        freq_distribution = {}
        for key, metric_name in self._metric_types.items():
            freq = self._get_metric_frequency(metric_name)
            freq_distribution[str(freq)] = freq_distribution.get(str(freq), 0) + 1
        
        return {
            "total_entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(hit_rate, 3),
            "frequency_distribution": freq_distribution,
            "avg_access_count": sum(self._access_count.values()) / len(self._access_count) if self._access_count else 0
        }
    
    def get_detailed_cache_metrics(self) -> Dict[str, Any]:
        """Detaylı cache metriklerini getir"""
        base_stats = self.get_cache_stats()
        
        # Metrik bazlı hit rates
        metric_hit_rates = {}
        metric_access_counts = {}
        
        for metric_name in set(self._metric_types.values()):
            metric_keys = [k for k, v in self._metric_types.items() if v == metric_name]
            hits = sum(1 for k in metric_keys if k in self._access_count and self._access_count[k] > 0)
            total_access = sum(self._access_count.get(k, 0) for k in metric_keys)
            
            metric_hit_rates[metric_name] = hits / len(metric_keys) if metric_keys else 0
            metric_access_counts[metric_name] = total_access
        
        base_stats.update({
            'metric_hit_rates': metric_hit_rates,
            'metric_access_counts': metric_access_counts,
            'memory_usage_mb': self._estimated_memory / (1024 * 1024),
            'volatility_index': self._volatility_index
        })
        
        return base_stats
        
    # Performance Metrics
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Performans metriklerini getir"""
        stats = self.get_detailed_cache_metrics()
        
        # Response time hesaplamaları
        avg_response_time = self._calculate_avg_response_time()
        p95_response_time = self._calculate_percentile_response_time(95)
        
        stats.update({
            'avg_response_time_ms': avg_response_time,
            'p95_response_time_ms': p95_response_time,
            'throughput_rps': self._hits / (time.time() - self._start_time) if hasattr(self, '_start_time') else 0
        })
        
        return stats
    
    

# Global smart cache instance
smart_cache = SmartOnChainCache()

# =============================================================================
# OPTIMAL TTL ENTEGRE EDİLMİŞ DATA FETCHING FONKSİYONLARI
# =============================================================================

# =============================================================================
# OPTIMAL TTL ENTEGRE EDİLMİŞ DATA FETCHING FONKSİYONLARI
# =============================================================================

def generate_cache_key(metric_name: str, symbol: str, **params) -> str:
    """Unique cache key oluştur"""
    param_str = str(sorted(params.items()))
    key_base = f"{metric_name}_{symbol}_{param_str}"
    return hashlib.md5(key_base.encode()).hexdigest()[:16]

async def fetch_with_optimal_ttl(
    metric_func: Callable, 
    symbol: str, 
    metric_name: str, 
    **kwargs
) -> Optional[Dict[str, Any]]:
    """
    Optimal TTL stratejisi ile veri getir - GELİŞTİRİLMİŞ HATA YÖNETİMİ
    """
    # Cache key optimizasyonu - 10 dakikalık window
    ten_min_window = datetime.now().strftime('%Y%m%d%H%M')[:-1]  # Son rakamı at
    cache_key = generate_cache_key(metric_name, symbol, **kwargs)
    
    # Önce cache kontrol et
    cached_data = await smart_cache.get(cache_key, metric_name)
    if cached_data is not None:
        return cached_data
    
    # Cache'de yok - fresh data getir
    try:
        # ✅ ÖNERİ: Retry mekanizması burada
        fresh_data = await fetch_with_retry(metric_func, symbol, metric_name, **kwargs)
        
        # ✅ DÜZELTME
        if fresh_data is not None:
            validated_data = validate_metric_data(fresh_data, metric_name)
            if validated_data:
                await smart_cache.set(cache_key, validated_data.dict(), metric_name)
                logger.info(f"Fresh data fetched and cached: {metric_name} for {symbol}")
                return validated_data.dict()
            else:
                logger.warning(f"Data validation failed for {metric_name}, using unvalidated data")
                await smart_cache.set(cache_key, fresh_data, metric_name)
                return fresh_data
        else:
            logger.warning(f"No data returned for {metric_name} - {symbol}")
            return await get_fallback_data(metric_name, symbol)
            
            
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {metric_name} for {symbol}")
        return await get_cached_fallback(metric_name, symbol)
    except ConnectionError as e:
        logger.warning(f"Connection error for {metric_name}: {e}")
        return await get_fallback_data(metric_name, symbol)
    except Exception as e:
        logger.error(f"Critical error for {metric_name}: {str(e)}")
        return None

# ✅ ÖNERİ: BU FONKSİYONLARI fetch_with_optimal_ttl'den SONRA
async def fetch_with_retry(metric_func: Callable, symbol: str, metric_name: str, 
                          max_retries: int = 3, backoff: float = 1.5, **kwargs):
    """Retry mekanizması ile veri getir"""
    for attempt in range(max_retries):
        try:
            return await metric_func(symbol, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = backoff * (2 ** attempt)
            logger.warning(f"Retry {attempt + 1}/{max_retries} for {metric_name} after {wait_time}s")
            await asyncio.sleep(wait_time)

async def get_fallback_data(metric_name: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Fallback data sağla"""
    # Basit fallback stratejisi - daha gelişmiş yapılabilir
    return {
        "value": 0.0,
        "timestamp": datetime.now().isoformat(),
        "source": "fallback",
        "is_fallback": True
    }

async def get_cached_fallback(metric_name: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Cache'deki en son geçerli veriyi getir"""
   
    # ✅ Yeni formatı kullan
    cache_key = generate_cache_key(metric_name, symbol)
    
    async with smart_cache._lock:
        if cache_key in smart_cache._cache:
            logger.info(f"Using cached fallback for {metric_name}")
            return smart_cache._cache[cache_key]
    
    return await get_fallback_data(metric_name, symbol)

# =============================================================================
# GÜNCELLENMİŞ DATA FETCHING FONKSİYONLARI
# =============================================================================

async def fetch_etf_flow(symbol: str = "BTC") -> Optional[Dict[str, Any]]:
    """Optimal TTL ile ETF flow verisi getir"""
    return await fetch_with_optimal_ttl(_fetch_etf_flow_internal, symbol, "etf_flow")


# ✅ RATE LIMITING UYGULA - data fetching fonksiyonlarına
@rate_limited(requests_per_minute=30)  # API limitlerine göre ayarla
async def _fetch_etf_flow_internal(symbol: str) -> Optional[Dict[str, Any]]:
    """Internal ETF flow fetcher"""
    try:
        data = await DataProvider.get_metric("farside", symbol, "etf_net_flow")
        if data and isinstance(data, dict):
            return {
                "net_flow": data.get("net_flow", 0),
                "timestamp": datetime.now().isoformat(),
                "source": "farside"
            }
        return None
    except Exception as e:
        logger.error(f"Error in ETF flow fetch: {str(e)}")
        return None

async def fetch_stablecoin_flow(symbol: str = "BTC") -> Optional[Dict[str, Any]]:
    """Optimal TTL ile stablecoin flow getir"""
    return await fetch_with_optimal_ttl(_fetch_stablecoin_flow_internal, symbol, "stablecoin_flow")

@rate_limited(requests_per_minute=30)
async def _fetch_stablecoin_flow_internal(symbol: str) -> Optional[Dict[str, Any]]:
    """Internal stablecoin flow fetcher"""
    try:
        data = await DataProvider.get_metric(symbol, "exchange_netflow")
        if data and isinstance(data, dict):
            return {
                "net_flow": data.get("net_flow", 0),
                "timestamp": datetime.now().isoformat(),
                "source": "glassnode"
            }
        return None
    except Exception as e:
        logger.error(f"Error in stablecoin flow fetch: {str(e)}")
        return None

async def fetch_mvrv_zscore(symbol: str = "BTC") -> Optional[Dict[str, Any]]:
    """Optimal TTL ile MVRV Z-Score getir"""
    return await fetch_with_optimal_ttl(_fetch_mvrv_zscore_internal, symbol, "mvrv_zscore")

async def _fetch_mvrv_zscore_internal(symbol: str) -> Optional[Dict[str, Any]]:
    """Internal MVRV Z-Score fetcher"""
    try:
        data = await DataProvider.get_metric("glassnode", symbol, "mvrv_zscore")
        if data and isinstance(data, dict):
            return {
                "zscore": data.get("zscore", 0),
                "timestamp": datetime.now().isoformat(),
                "source": "glassnode"
            }
        return None
    except Exception as e:
        logger.error(f"Error in MVRV Z-Score fetch: {str(e)}")
        return None

async def fetch_sopr(symbol: str = "BTC") -> Optional[Dict[str, Any]]:
    """Optimal TTL ile SOPR getir"""
    return await fetch_with_optimal_ttl(_fetch_sopr_internal, symbol, "sopr")

async def _fetch_sopr_internal(symbol: str) -> Optional[Dict[str, Any]]:
    """Internal SOPR fetcher"""
    try:
        data = await DataProvider.get_metric("glassnode", symbol, "sopr")
        if data and isinstance(data, dict):
            return {
                "sopr": data.get("sopr", 1.0),
                "timestamp": datetime.now().isoformat(),
                "source": "glassnode"
            }
        return None
    except Exception as e:
        logger.error(f"Error in SOPR fetch: {str(e)}")
        return None

async def fetch_exchange_whale_ratio(symbol: str = "BTC") -> Optional[Dict[str, Any]]:
    """Optimal TTL ile whale ratio getir"""
    return await fetch_with_optimal_ttl(_fetch_whale_ratio_internal, symbol, "whale_ratio")

async def _fetch_whale_ratio_internal(symbol: str) -> Optional[Dict[str, Any]]:
    """Internal whale ratio fetcher"""
    try:
        data = await DataProvider.get_metric("glassnode", symbol, "exchange_whale_ratio")
        if data and isinstance(data, dict):
            return {
                "ratio": data.get("ratio", 0.5),
                "timestamp": datetime.now().isoformat(),
                "source": "glassnode"
            }
        return None
    except Exception as e:
        logger.error(f"Error in whale ratio fetch: {str(e)}")
        return None

# =============================================================================
# RUN FONKSİYONU
# =============================================================================

# =============================================================================
# METRIC PROCESSING AND NORMALIZATION 
# =============================================================================

def normalize_metric_value(value: float, min_val: float, max_val: float) -> float:
    """Metrik değerini 0-1 aralığına normalize et"""
    if max_val == min_val:
        return 0.5  # Neutral value
    normalized = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, normalized))

def calculate_etf_flow_score(etf_data: Dict[str, Any]) -> float:
    """ETF flow verisini skora dönüştür"""
    try:
        if not etf_data or 'net_flow' not in etf_data:
            return 0.5
        net_flow = etf_data['net_flow']
        thresholds = CONFIG['thresholds']
        
        if net_flow >= thresholds['etf_flow_positive']:
            return 1.0
        elif net_flow <= thresholds['etf_flow_negative']:
            return 0.0
        else:
            normalized = (net_flow - thresholds['etf_flow_negative']) / (
                thresholds['etf_flow_positive'] - thresholds['etf_flow_negative'])
            return max(0.0, min(1.0, normalized))
    except Exception:
        return 0.5

def calculate_mvrv_zscore_score(mvrv_data: Dict[str, Any]) -> float:
    """MVRV Z-Score'u skora dönüştür"""
    try:
        if not mvrv_data or 'zscore' not in mvrv_data:
            return 0.5
        zscore = mvrv_data['zscore']
        thresholds = CONFIG['thresholds']
        
        if zscore >= thresholds['mvrv_zscore_high']:
            return 0.0  # Overvalued
        elif zscore <= thresholds['mvrv_zscore_low']:
            return 1.0  # Undervalued
        else:
            normalized = 1.0 - (zscore - thresholds['mvrv_zscore_low']) / (
                thresholds['mvrv_zscore_high'] - thresholds['mvrv_zscore_low'])
            return max(0.0, min(1.0, normalized))
    except Exception:
        return 0.5

def calculate_composite_macro_score(scores: Dict[str, float], priority: Optional[str]) -> float:
    """Kompozit makro skor hesapla"""
    if not scores:
        return 0.5
    
    weights = CONFIG['weights']
    total_weight = 0.0
    weighted_sum = 0.0
    
    for metric, score in scores.items():
        if metric in weights:
            weight = weights[metric]
            weighted_sum += score * weight
            total_weight += weight
    
    return weighted_sum / total_weight if total_weight > 0 else 0.5


async def calculate_market_volatility(symbol: str) -> float:
    """Basit piyasa volatilite indeksi hesapla"""
    try:
        # Price data veya diğer metriklerden volatilite hesaplanabilir
        # Şimdilik basit bir implementasyon:
        return 0.5  # 0-1 arası, 0.5 = normal volatilite
    except Exception as e:
        logger.warning(f"Volatility calculation failed: {e}")
        return 0.5


async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    On-Chain & Makro analizini çalıştır - Optimal TTL entegre
    
    Args:
        symbol: Analiz yapılacak sembol (örn: "BTC")
        priority: Öncelik seviyesi ("*", "**", "***")
    
    Returns:
        Analiz sonuçları dict formatında
    """
    start_time = time.time()
    logger.info(f"Starting on-chain analysis for {symbol}, priority: {priority}")
    
    try:
        # Priority-based metric selection
        metrics_to_fetch = []

        # Gerçek uygulamada piyasa volatilitesi hesaplanmalı
        current_volatility = await calculate_market_volatility(symbol)
        smart_cache.update_volatility_index(current_volatility)
        
        
        if priority == "*":  # Basic - essential metrics only
            metrics_to_fetch = ["etf_flow", "stablecoin_flow"]
        elif priority == "**":  # Pro - add MVRV
            metrics_to_fetch = ["etf_flow", "stablecoin_flow", "mvrv_zscore"]
        else:  # Expert/None - all metrics
            metrics_to_fetch = ["etf_flow", "stablecoin_flow", "mvrv_zscore", "sopr", "whale_ratio"]
        
        # Parallel data fetching with optimal TTL
        fetch_tasks = []
        metric_functions = {
            "etf_flow": fetch_etf_flow,
            "stablecoin_flow": fetch_stablecoin_flow,
            "mvrv_zscore": fetch_mvrv_zscore,
            "sopr": fetch_sopr,
            "whale_ratio": fetch_exchange_whale_ratio
        }
        
        for metric in metrics_to_fetch:
            if metric in metric_functions:
                fetch_tasks.append(metric_functions[metric](symbol))
        
        # Wait for all data with timeout
        results = await asyncio.wait_for(
            asyncio.gather(*fetch_tasks, return_exceptions=True),
            timeout=15.0
        )
        
        # Process results
        data_map = {}
        for i, metric_name in enumerate(metrics_to_fetch):
            if i < len(results) and not isinstance(results[i], Exception) and results[i] is not None:
                data_map[metric_name] = results[i]
            else:
                logger.warning(f"Failed to fetch {metric_name} for {symbol}")
                data_map[metric_name] = None
        
        # Calculate scores and composite
        scores = {}
        if data_map.get("etf_flow"):
            scores["etf_flow"] = calculate_etf_flow_score(data_map["etf_flow"])
        if data_map.get("stablecoin_flow"):
            stablecoin_flow = data_map["stablecoin_flow"].get("net_flow", 0)
            scores["stablecoin_flow"] = normalize_metric_value(stablecoin_flow, -1000, 1000)
        if data_map.get("mvrv_zscore"):
            scores["mvrv_zscore"] = calculate_mvrv_zscore_score(data_map["mvrv_zscore"])
        if data_map.get("sopr"):
            sopr_value = data_map["sopr"].get("sopr", 1.0)
            scores["sopr"] = normalize_metric_value(sopr_value, 0.9, 1.1)
        if data_map.get("whale_ratio"):
            whale_ratio = data_map["whale_ratio"].get("ratio", 0.5)
            scores["whale_ratio"] = 1.0 - normalize_metric_value(whale_ratio, 0.0, 1.0)
        
        # 
        # Composite score hesapla
        composite_score = calculate_composite_macro_score(scores, priority)
        
        # Cache stats ekle
        cache_stats = smart_cache.get_cache_stats()
        
        # TEK BİR result tanımı
        result = {
            "symbol": symbol,
            "score": composite_score,  # GERÇEK SKOR
            "priority": priority,
            "execution_time": time.time() - start_time,
            "metrics": scores,  # GERÇEK METRİKLER
            "cache_stats": cache_stats,
            "raw_data_available": {k: v is not None for k, v in data_map.items()},
            "timestamp": datetime.now().isoformat(),
            "analysis_type": "onchain_macro_optimal_ttl"
        }
        
        logger.info(
            f"On-chain analysis completed for {symbol}: "
            f"score={result['score']:.3f}, time={result['execution_time']:.2f}s, "
            f"cache_hit_rate={cache_stats['hit_rate']}"
        )
        
        return result
        
        
    except Exception as e:
        logger.error(f"On-chain analysis failed for {symbol}: {str(e)}", exc_info=True)
        return {
            "symbol": symbol,
            "score": 0.5,
            "priority": priority,
            "error": f"Analysis failed: {str(e)}",
            "execution_time": time.time() - start_time,
            "timestamp": datetime.now().isoformat()
        }

# =============================================================================
# MONITORING VE DEBUG FONKSİYONLARI - INFO kullanıldı
# =============================================================================

async def get_cache_status() -> Dict[str, Any]:
    """Cache durumunu getir (monitoring için)"""
    return smart_cache.get_cache_stats()

async def clear_cache() -> Dict[str, Any]:
    """Cache'i temizle (debug için)"""
    # Basit reset için yeni instance oluştur
    global smart_cache
    stats_before = smart_cache.get_cache_stats()
    

    smart_cache = SmartOnChainCache()
    
    return {
        "cleared": True,
        "stats_before": stats_before,
        "stats_after": smart_cache.get_cache_stats()
    }

async def simulate_requests_for_testing():
    """Test için çeşitli metrik istekleri simüle et"""
    test_symbols = ["BTC", "ETH"]
    test_metrics = ["etf_flow", "mvrv_zscore", "stablecoin_flow"]
    
    for symbol in test_symbols:
        for metric in test_metrics:
            if metric == "etf_flow":
                await fetch_etf_flow(symbol)
            elif metric == "mvrv_zscore":
                await fetch_mvrv_zscore(symbol)
            elif metric == "stablecoin_flow":
                await fetch_stablecoin_flow(symbol)
        
        await asyncio.sleep(1)  # Kısa bekleme
    
    return await get_cache_status()

# =============================================================================
# MODULE INITIALIZATION
# =============================================================================

async def initialize_module():
    """Modül başlangıç initializasyonu"""
    logger.info("Initializing On-Chain analysis module with Optimal TTL Strategy")
    
    # Test istekleri ile cache'i pre-warm
    try:
        # Sadece yavaş değişen metrikleri pre-warm (TTL uzun)
        await fetch_mvrv_zscore("BTC")
        await fetch_exchange_whale_ratio("BTC")
        logger.info("On-Chain module initialized with optimal TTL cache")
        
        # Cache stats log
        cache_stats = await get_cache_status()
        logger.info(f"Initial cache stats: {cache_stats}")
        
        # ✅ ÖNERİ: BACKGROUND WARMER BAŞLAT
        asyncio.create_task(background_cache_warmer())
        
    except Exception as e:
        logger.warning(f"Cache pre-warming failed: {str(e)}")

    # Async initialization on module import
    asyncio.create_task(initialize_module())

# ✅ ÖNERİ: BU FONKSİYONU initialize_module'dan SONRA EKLE
async def background_cache_warmer():
    """Önemli metrikleri periyodik olarak pre-fetch et"""
    await asyncio.sleep(10)  # Başlangıçta 10sn bekle
    
    while True:
        try:
            logger.debug("Background cache warmer running...")
            
            # High-frequency metrics için cache tazele
            await fetch_etf_flow("BTC")
            await fetch_stablecoin_flow("BTC")
            
            # 2 dakika bekle (high frequency TTL'si)
            await asyncio.sleep(120)
            
        except Exception as e:
            logger.error(f"Background warmer failed: {e}")
            await asyncio.sleep(300)  # Hata durumunda 5 dk bekle


async def health_check() -> Dict[str, Any]:
    """Sistem sağlık durumunu kontrol et"""
    cache_stats = await get_cache_status()
    
    # Basit health check
    is_healthy = (
        cache_stats['hit_rate'] > 0.1 and  # Minimum hit rate
        cache_stats['total_entries'] < 1000  # Cache overload kontrolü
    )
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "cache_stats": cache_stats,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

async def enhanced_health_check() -> Dict[str, Any]:
    """Gelişmiş sistem sağlık kontrolü"""
    cache_stats = await get_cache_status()
    
    # Çok yönlü health check
    health_indicators = {
        'cache_hit_rate_healthy': cache_stats['hit_rate'] > 0.1,
        'cache_size_healthy': cache_stats['total_entries'] < 1000,
        'memory_usage_healthy': cache_stats.get('memory_usage_mb', 0) < 80,
        'error_rate_healthy': cache_stats.get('error_rate', 0) < 0.1
    }
    
    is_healthy = all(health_indicators.values())
    health_score = sum(health_indicators.values()) / len(health_indicators)
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "health_score": round(health_score, 3),
        "health_indicators": health_indicators,
        "cache_stats": cache_stats,
        "timestamp": datetime.now().isoformat(),
        "version": "1.1.0"
    }


"""
Önerilen Veri Kaynakları ve API'ler:
Önerilen Veri Kaynakları ve API'ler:

1. Glassnode (Premium - Önerilen)
URL: https://glassnode.com
Özellikler: Profesyonel on-chain metrikler
Metrikler: MVRV Z-Score, SOPR, Exchange Flows, Whale Ratio
API Tier: Advanced/Professional önerilir

2. CryptoQuant (Premium - Önerilen)
URL: https://cryptoquant.com
Özellikler: Exchange flow, funding rates, miner flows
Metrikler: Netflow, Taker Buy Sell Ratio
API Tier: Pro plan önerilir

3. Farside Investors (Ücretsiz)
URL: https://farside.co.uk/?p=997
Özellikler: ETF flow verileri
Metrikler: Günlük ETF net flows
API: Scraping veya REST API

4. Alternative Ücretsiz Kaynaklar:
CoinMetrics (Community edition)
Messari API (Free tier)
Blockchain.com API
BitInfoCharts

API Key Konfigürasyonu:
# Ortam değişkenleri olarak ekleyin
GLASSNODE_API_KEY= "your_glassnode_key"
CRYPTOQUANT_API_KEY= "your_cryptoquant_key"

"""