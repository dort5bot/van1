# analysis/regimdetect.py
"""
Regime Change Detection & Anomaly Module
=========================================
Ani piyasa rejimi değişimlerini ve anomalileri tespit etmek için 
çoklu detection algoritmaları kullanır.
CUSUM, Isolation Forest ve Spectral Residual methodları ile 
yüksek hassasiyetli değişim tespiti.

🎯 Temel Özellikler:
CUSUM (Cumulative Sum) - Change point detection
Isolation Forest - Anomali tespiti (scikit-learn ile)
Spectral Residual - Spektral analiz ile anomali tespiti
Z-Score - Klasik istatistiksel anomali tespiti
Ensemble Method - Tüm methodların kombinasyonu

🔧 Teknik Detaylar:
Thread-safe design with user-specific locks
Cache management with TTL support (5 dakika)
Singleton pattern for resource management
Comprehensive error handling and logging
Type hints and detailed docstrings
Performance monitoring with metrics collection

"""

import asyncio
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import warnings
from dataclasses import dataclass
from contextlib import asynccontextmanager
from enum import Enum
import hashlib

# Scikit-learn for advanced detection methods
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.covariance import EllipticEnvelope
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logging.warning("scikit-learn not available, some methods will be disabled")

# Binance API
from utils.binance_api.binance_a import BinanceAggregator, MultiUserBinanceAggregator

# Configure logging
logger = logging.getLogger(__name__)

# Constants
EPSILON = 1e-10
CACHE_TTL = 300  # 5 minutes

class RegimeType(Enum):
    """Piyasa rejimi tipleri"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down" 
    RANGING = "ranging"
    VOLATILE = "volatile"
    CALM = "calm"
    ANOMALY = "anomaly"

class DetectionMethod(Enum):
    """Tespit methodları"""
    CUSUM = "cusum"
    ISOLATION_FOREST = "isolation_forest"
    SPECTRAL_RESIDUAL = "spectral_residual"
    ZSCORE = "zscore"
    COMBINED = "combined"

@dataclass
class RegimeChange:
    """Rejim değişimi tespiti sonucu"""
    timestamp: datetime
    regime_from: RegimeType
    regime_to: RegimeType
    confidence: float
    method: DetectionMethod
    metrics: Dict[str, float]

@dataclass
class AnomalyDetection:
    """Anomali tespiti sonucu"""
    timestamp: datetime
    score: float
    is_anomaly: bool
    method: DetectionMethod
    features: Dict[str, float]

class RegimeDetector:
    """
    Piyasa rejimi değişimi ve anomali tespiti için ana sınıf
    Thread-safe + Cache management + Multi-user support
    """
    
    _instance: Optional['RegimeDetector'] = None
    _lock: asyncio.Lock = asyncio.Lock()
    
    def __new__(cls):
        """Singleton pattern implementation"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize detector with thread-safe lazy loading"""
        if self._initialized:
            return
            
        self.binance = MultiUserBinanceAggregator.get_instance()
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._user_locks: Dict[int, asyncio.Lock] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running = False
        
        # Performance metrics
        self._detection_times: List[float] = []
        self._cache_hits = 0
        self._cache_misses = 0
        
        self._initialized = True
        logger.info("RegimeDetector initialized successfully")
    
    async def start(self):
        """Detector'ü başlat"""
        if self._is_running:
            return
            
        self._is_running = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("RegimeDetector started with periodic cleanup")
    
    async def stop(self):
        """Detector'ü durdur"""
        self._is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        self._cache.clear()
        self._user_locks.clear()
        logger.info("RegimeDetector stopped and cleaned up")
    
    @asynccontextmanager
    async def _get_user_lock(self, user_id: int):
        """User-specific lock context manager"""
        async with self._lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
        
        lock = self._user_locks[user_id]
        async with lock:
            yield
    
    def _get_cache_key(self, symbol: str, interval: str, method: str, user_id: Optional[int] = None) -> str:
        """Cache key oluştur"""
        key_parts = [symbol.upper(), interval, method]
        if user_id:
            key_parts.append(str(user_id))
        
        key_string = ":".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    async def _get_market_data(self, symbol: str, interval: str = "1h", 
                             limit: int = 500, user_id: Optional[int] = None) -> pd.DataFrame:
        """
        Market verilerini getir - cache ve validation ile
        """
        cache_key = self._get_cache_key(symbol, interval, "market_data", user_id)
        
        # Cache check
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if (datetime.now() - timestamp).total_seconds() < CACHE_TTL:
                self._cache_hits += 1
                return data
        
        self._cache_misses += 1
        
        try:
            # Input validation
            if not symbol or not isinstance(symbol, str):
                raise ValueError("Invalid symbol provided")
            
            symbol = symbol.strip().upper()
            
            # Binance'ten veri al
            klines = await self.binance.public.spot.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                user_id=user_id
            )
            
            if not klines or len(klines) < 50:
                raise ValueError(f"Insufficient data for {symbol}")
            
            # DataFrame oluştur
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # Numeric columns'ı convert et
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Timestamp conversion
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Cache'e kaydet
            self._cache[cache_key] = (df, datetime.now())
            
            return df
            
        except Exception as e:
            logger.error(f"Market data fetch failed for {symbol}: {str(e)}")
            raise
    
    class CUSUMDetector:
        """CUSUM (Cumulative Sum) change point detection"""
        
        def __init__(self, threshold: float = 5.0, drift: float = 0.0):
            self.threshold = threshold
            self.drift = drift
        
        def detect_changes(self, data: np.ndarray) -> Tuple[List[int], np.ndarray]:
            """
            CUSUM ile change point'leri tespit et
            
            Args:
                data: Input time series data
                
            Returns:
                Tuple of (change_points, cusum_values)
            """
            if len(data) < 10:
                return [], np.array([])
            
            # Normalize data
            data_normalized = (data - np.mean(data)) / (np.std(data) + EPSILON)
            
            # CUSUM calculation
            cusum_pos = np.zeros(len(data_normalized))
            cusum_neg = np.zeros(len(data_normalized))
            change_points = []
            
            for i in range(1, len(data_normalized)):
                cusum_pos[i] = max(0, cusum_pos[i-1] + data_normalized[i] - self.drift)
                cusum_neg[i] = max(0, cusum_neg[i-1] - data_normalized[i] - self.drift)
                
                if cusum_pos[i] > self.threshold or cusum_neg[i] > self.threshold:
                    change_points.append(i)
                    cusum_pos[i] = 0
                    cusum_neg[i] = 0
            
            return change_points, cusum_pos + cusum_neg
    
    class SpectralResidualDetector:
        """Spectral Residual anomali tespiti"""
        
        def __init__(self, window_size: int = 10, scale: float = 1.5):
            self.window_size = window_size
            self.scale = scale
        
        def detect_anomalies(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
            """
            Spectral Residual ile anomalileri tespit et
            
            Args:
                data: Input time series data
                
            Returns:
                Tuple of (anomaly_scores, saliency_map)
            """
            if len(data) < self.window_size * 2:
                return np.zeros(len(data)), np.zeros(len(data))
            
            # Fast Fourier Transform
            fft = np.fft.fft(data)
            amplitude = np.abs(fft)
            phase = np.angle(fft)
            
            # Spectral residual
            log_amplitude = np.log(amplitude + EPSILON)
            smoothed_log_amplitude = self._moving_average(log_amplitude, self.window_size)
            spectral_residual = log_amplitude - smoothed_log_amplitude
            
            # Saliency map
            saliency_map = np.abs(np.fft.ifft(np.exp(spectral_residual + 1j * phase)))
            
            # Anomaly scores
            anomaly_scores = (saliency_map - np.mean(saliency_map)) / (np.std(saliency_map) + EPSILON)
            
            return anomaly_scores, saliency_map
        
        def _moving_average(self, data: np.ndarray, window: int) -> np.ndarray:
            """Moving average hesapla"""
            return np.convolve(data, np.ones(window)/window, mode='same')
    
    class ZScoreDetector:
        """Z-Score based anomaly detection"""
        
        def __init__(self, window: int = 20, threshold: float = 2.5):
            self.window = window
            self.threshold = threshold
        
        def detect_anomalies(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
            """
            Z-Score ile anomalileri tespit et
            
            Args:
                data: Input time series data
                
            Returns:
                Tuple of (z_scores, is_anomaly)
            """
            if len(data) < self.window:
                return np.zeros(len(data)), np.zeros(len(data), dtype=bool)
            
            z_scores = np.zeros(len(data))
            is_anomaly = np.zeros(len(data), dtype=bool)
            
            for i in range(self.window, len(data)):
                window_data = data[i-self.window:i]
                mean = np.mean(window_data)
                std = np.std(window_data) + EPSILON
                
                z_scores[i] = (data[i] - mean) / std
                is_anomaly[i] = abs(z_scores[i]) > self.threshold
            
            return z_scores, is_anomaly
    
    async def detect_regime_changes(self, symbol: str, interval: str = "1h",
                                  method: DetectionMethod = DetectionMethod.COMBINED,
                                  user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Rejim değişimlerini tespit et
        
        Args:
            symbol: Sembol (örn: "BTCUSDT")
            interval: Zaman aralığı
            method: Tespit methodu
            user_id: Kullanıcı ID'si
            
        Returns:
            Dict containing regime detection results
        """
        start_time = datetime.now()
        
        async with self._get_user_lock(user_id or 0):
            try:
                # Market verilerini al
                market_data = await self._get_market_data(symbol, interval, user_id=user_id)
                close_prices = market_data['close'].values
                
                if len(close_prices) < 50:
                    raise ValueError(f"Insufficient data points: {len(close_prices)}")
                
                # Returns hesapla
                returns = np.diff(close_prices) / close_prices[:-1]
                
                # Method'a göre tespit yap
                if method == DetectionMethod.CUSUM:
                    result = await self._detect_with_cusum(returns, close_prices)
                elif method == DetectionMethod.ISOLATION_FOREST:
                    result = await self._detect_with_isolation_forest(returns, close_prices)
                elif method == DetectionMethod.SPECTRAL_RESIDUAL:
                    result = await self._detect_with_spectral_residual(returns, close_prices)
                elif method == DetectionMethod.ZSCORE:
                    result = await self._detect_with_zscore(returns, close_prices)
                else:  # COMBINED
                    result = await self._detect_combined(returns, close_prices)
                
                # Performance metrics
                execution_time = (datetime.now() - start_time).total_seconds()
                self._detection_times.append(execution_time)
                
                result.update({
                    "symbol": symbol,
                    "interval": interval,
                    "method": method.value,
                    "execution_time": execution_time,
                    "data_points": len(close_prices),
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                })
                
                logger.info(f"Regime detection completed for {symbol}: "
                           f"{result['regime_changes']} changes, "
                           f"score: {result['anomaly_score']:.3f}")
                
                return result
                
            except Exception as e:
                logger.error(f"Regime detection failed for {symbol}: {str(e)}")
                execution_time = (datetime.now() - start_time).total_seconds()
                
                return {
                    "symbol": symbol,
                    "interval": interval,
                    "method": method.value,
                    "regime_changes": 0,
                    "anomaly_score": 0.0,
                    "current_regime": "unknown",
                    "confidence": 0.0,
                    "execution_time": execution_time,
                    "error": str(e),
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                }
    
    async def _detect_with_cusum(self, returns: np.ndarray, prices: np.ndarray) -> Dict[str, Any]:
        """CUSUM methodu ile tespit"""
        detector = self.CUSUMDetector(threshold=3.0, drift=0.1)
        change_points, cusum_values = detector.detect_changes(prices)
        
        # Regime analysis
        current_regime = self._analyze_current_regime(returns[-50:])
        confidence = min(len(change_points) / 10, 1.0) if change_points else 0.0
        
        return {
            "regime_changes": len(change_points),
            "anomaly_score": self._calculate_anomaly_score(cusum_values),
            "current_regime": current_regime.value,
            "confidence": confidence,
            "change_points": change_points[-5:],  # Son 5 değişim
            "metrics": {
                "cusum_max": float(np.max(cusum_values)),
                "cusum_mean": float(np.mean(cusum_values)),
                "volatility": float(np.std(returns))
            }
        }
    
    async def _detect_with_isolation_forest(self, returns: np.ndarray, prices: np.ndarray) -> Dict[str, Any]:
        """Isolation Forest ile tespit"""
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not available for Isolation Forest")
        
        # Feature engineering
        features = self._create_features(returns, prices)
        
        # Isolation Forest
        iso_forest = IsolationForest(
            contamination=0.1,
            random_state=42,
            n_estimators=100
        )
        
        anomaly_scores = iso_forest.fit_predict(features)
        decision_scores = iso_forest.decision_function(features)
        
        # Normalize scores to 0-1
        normalized_scores = (decision_scores - decision_scores.min()) / (decision_scores.max() - decision_scores.min() + EPSILON)
        anomaly_score = float(np.mean(normalized_scores[-10:]))  # Son 10 period
        
        current_regime = self._analyze_current_regime(returns[-50:])
        
        return {
            "regime_changes": int(np.sum(anomaly_scores == -1)),
            "anomaly_score": anomaly_score,
            "current_regime": current_regime.value,
            "confidence": min(np.sum(anomaly_scores == -1) / len(anomaly_scores), 1.0),
            "metrics": {
                "anomaly_count": int(np.sum(anomaly_scores == -1)),
                "contamination": 0.1,
                "feature_count": features.shape[1]
            }
        }
    
    async def _detect_with_spectral_residual(self, returns: np.ndarray, prices: np.ndarray) -> Dict[str, Any]:
        """Spectral Residual ile tespit"""
        detector = self.SpectralResidualDetector(window_size=10, scale=1.5)
        anomaly_scores, saliency_map = detector.detect_anomalies(prices)
        
        # Recent anomalies
        recent_scores = anomaly_scores[-20:]
        anomaly_count = np.sum(np.abs(recent_scores) > 2.0)
        
        current_regime = self._analyze_current_regime(returns[-50:])
        
        return {
            "regime_changes": int(anomaly_count),
            "anomaly_score": float(np.mean(np.abs(recent_scores))),
            "current_regime": current_regime.value,
            "confidence": min(anomaly_count / 20, 1.0),
            "metrics": {
                "saliency_max": float(np.max(saliency_map)),
                "anomaly_peaks": int(anomaly_count),
                "spectral_power": float(np.mean(saliency_map))
            }
        }
    
    async def _detect_with_zscore(self, returns: np.ndarray, prices: np.ndarray) -> Dict[str, Any]:
        """Z-Score ile tespit"""
        detector = self.ZScoreDetector(window=20, threshold=2.5)
        z_scores, is_anomaly = detector.detect_anomalies(prices)
        
        recent_anomalies = is_anomaly[-20:]
        anomaly_count = np.sum(recent_anomalies)
        
        current_regime = self._analyze_current_regime(returns[-50:])
        
        return {
            "regime_changes": int(anomaly_count),
            "anomaly_score": float(np.mean(np.abs(z_scores[-20:])) / 2.5),
            "current_regime": current_regime.value,
            "confidence": min(anomaly_count / 20, 1.0),
            "metrics": {
                "zscore_max": float(np.max(np.abs(z_scores))),
                "zscore_mean": float(np.mean(np.abs(z_scores))),
                "anomaly_threshold": 2.5
            }
        }
    
    async def _detect_combined(self, returns: np.ndarray, prices: np.ndarray) -> Dict[str, Any]:
        """Kombine method ile tespit"""
        results = []
        
        # Tüm methodları çalıştır
        methods = [
            self._detect_with_cusum(returns, prices),
            self._detect_with_zscore(returns, prices)
        ]
        
        if SKLEARN_AVAILABLE:
            methods.append(self._detect_with_isolation_forest(returns, prices))
        
        method_results = await asyncio.gather(*methods, return_exceptions=True)
        
        # Valid results'ları topla
        for result in method_results:
            if isinstance(result, dict) and 'anomaly_score' in result:
                results.append(result)
        
        if not results:
            raise RuntimeError("All detection methods failed")
        
        # Ensemble scoring
        anomaly_scores = [r['anomaly_score'] for r in results]
        regime_changes = [r['regime_changes'] for r in results]
        confidences = [r.get('confidence', 0.0) for r in results]
        
        current_regime = self._analyze_current_regime(returns[-50:])
        
        return {
            "regime_changes": int(np.mean(regime_changes)),
            "anomaly_score": float(np.mean(anomaly_scores)),
            "current_regime": current_regime.value,
            "confidence": float(np.mean(confidences)),
            "ensemble_methods": len(results),
            "metrics": {
                "score_std": float(np.std(anomaly_scores)),
                "method_agreement": float(np.mean(confidences)),
                "volatility_regime": self._get_volatility_regime(returns)
            }
        }
    
    def _create_features(self, returns: np.ndarray, prices: np.ndarray) -> np.ndarray:
        """Feature engineering for machine learning methods"""
        features = []
        
        # Basic price features
        features.append(returns)
        features.append(np.diff(prices) / prices[:-1])
        
        # Volatility features
        volatility_5 = self._rolling_volatility(returns, 5)
        volatility_20 = self._rolling_volatility(returns, 20)
        features.append(volatility_5)
        features.append(volatility_20)
        
        # Momentum features
        momentum_5 = prices[5:] / prices[:-5] - 1
        momentum_10 = prices[10:] / prices[:-10] - 1
        features.append(np.concatenate([np.zeros(5), momentum_5]))
        features.append(np.concatenate([np.zeros(10), momentum_10]))
        
        # Align feature lengths
        min_length = min(len(f) for f in features)
        aligned_features = [f[-min_length:] for f in features]
        
        return np.column_stack(aligned_features)
    
    def _rolling_volatility(self, returns: np.ndarray, window: int) -> np.ndarray:
        """Rolling volatility hesapla"""
        volatility = np.zeros_like(returns)
        for i in range(window, len(returns)):
            volatility[i] = np.std(returns[i-window:i])
        return volatility
    
    def _analyze_current_regime(self, recent_returns: np.ndarray) -> RegimeType:
        """Mevcut rejimi analiz et"""
        if len(recent_returns) < 10:
            return RegimeType.RANGING
        
        volatility = np.std(recent_returns)
        mean_return = np.mean(recent_returns)
        abs_returns = np.abs(recent_returns)
        
        # High volatility check
        if volatility > np.percentile(abs_returns, 75):
            return RegimeType.VOLATILE
        
        # Low volatility check
        if volatility < np.percentile(abs_returns, 25):
            return RegimeType.CALM
        
        # Trend detection
        if mean_return > 0.001:  # Positive trend
            return RegimeType.TRENDING_UP
        elif mean_return < -0.001:  # Negative trend
            return RegimeType.TRENDING_DOWN
        else:  # Ranging
            return RegimeType.RANGING
    
    def _get_volatility_regime(self, returns: np.ndarray) -> str:
        """Volatility rejimini belirle"""
        volatility = np.std(returns)
        if volatility > 0.02:
            return "high_volatility"
        elif volatility < 0.005:
            return "low_volatility"
        else:
            return "normal_volatility"
    
    def _calculate_anomaly_score(self, detection_values: np.ndarray) -> float:
        """Anomali skoru hesapla (0-1 arası)"""
        if len(detection_values) == 0:
            return 0.0
        
        recent_values = detection_values[-20:]
        max_val = np.max(np.abs(recent_values))
        
        # Normalize to 0-1 range
        score = min(max_val / 10.0, 1.0)  # Assuming threshold of 10 for max anomaly
        return float(score)
    
    async def _periodic_cleanup(self):
        """Periyodik cache cleanup"""
        logger.info("Starting periodic cleanup for RegimeDetector")
        
        while self._is_running:
            try:
                await asyncio.sleep(300)  # 5 dakika
                
                # Eski cache entry'lerini temizle
                current_time = datetime.now()
                keys_to_remove = []
                
                for key, (data, timestamp) in self._cache.items():
                    if (current_time - timestamp).total_seconds() > CACHE_TTL:
                        keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del self._cache[key]
                
                # Performance metrics trim
                if len(self._detection_times) > 1000:
                    self._detection_times = self._detection_times[-500:]
                
                logger.debug(f"RegimeDetector cleanup: removed {len(keys_to_remove)} cache entries")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup task error: {str(e)}")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Performance metriklerini getir"""
        avg_time = np.mean(self._detection_times) if self._detection_times else 0
        cache_hit_rate = (self._cache_hits / (self._cache_hits + self._cache_misses) 
                         if (self._cache_hits + self._cache_misses) > 0 else 0)
        
        return {
            "average_detection_time": avg_time,
            "total_detections": len(self._detection_times),
            "cache_hit_rate": cache_hit_rate,
            "cache_size": len(self._cache),
            "active_user_locks": len(self._user_locks)
        }

# Global detector instance
detector = RegimeDetector()

async def get_detector() -> RegimeDetector:
    """Dependency injection için detector instance'ı"""
    return detector

async def run(symbol: str, priority: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Regime Change Detection ana fonksiyonu
    
    Args:
        symbol: Sembol (örn: "BTCUSDT")
        priority: Öncelik seviyesi ("basic", "pro", "expert")
        user_id: Kullanıcı ID'si
        
    Returns:
        Dict containing regime detection results
    """
    # Detector'ü başlat (eğer başlatılmadıysa)
    if not detector._is_running:
        await detector.start()
    
    # Priority'ye göre method seç
    if priority == "basic" or priority is None:
        method = DetectionMethod.ZSCORE
    elif priority == "pro":
        method = DetectionMethod.CUSUM
    elif priority == "expert":
        method = DetectionMethod.COMBINED
    else:
        method = DetectionMethod.COMBINED
    
    # Detection çalıştır
    result = await detector.detect_regime_changes(
        symbol=symbol,
        interval="1h",
        method=method,
        user_id=user_id
    )
    
    return result

# Test fonksiyonu
async def test_regimdetect():
    """Test fonksiyonu"""
    try:
        # Detector'ü başlat
        await detector.start()
        
        # Test detection
        result = await run("BTCUSDT", priority="pro", user_id=12345)
        
        print("Regime Detection Test Result:")
        print(f"Symbol: {result['symbol']}")
        print(f"Method: {result['method']}")
        print(f"Regime Changes: {result['regime_changes']}")
        print(f"Anomaly Score: {result['anomaly_score']:.3f}")
        print(f"Current Regime: {result['current_regime']}")
        print(f"Confidence: {result['confidence']:.3f}")
        print(f"Execution Time: {result['execution_time']:.2f}s")
        
        # Performance metrics
        metrics = detector.get_performance_metrics()
        print(f"\nPerformance Metrics:")
        print(f"Average Detection Time: {metrics['average_detection_time']:.3f}s")
        print(f"Cache Hit Rate: {metrics['cache_hit_rate']:.2%}")
        
        return result
        
    except Exception as e:
        print(f"Test failed: {e}")
        return None
    finally:
        await detector.stop()

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_regimdetect())