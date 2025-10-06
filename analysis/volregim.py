# analysis/volregim.py
"""
Piyasa Rejimi (Volatilite & Yapı) Analysis Module
=================================================
Trend/Range modu ayrımı için volatilite ve piyasa yapısı analizi.
Historical Volatility, ATR, GARCH, Entropy, Hurst Exponent, Regime Switching

✅ Advanced Volatility Modeling
Historical Volatility (σ) - Annualized volatility
ATR - Average True Range
Bollinger Width - Normalized band genişliği
GARCH(1,1) - Volatilite modelleme
Entropy Index - Piyasa düzensizliği ölçümü
Hurst Exponent - Trend kalıcılık analizi
Regime Switching Model - Trend/Range ayrımı

"""

import asyncio
import logging
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Literal
from dataclasses import dataclass
from enum import Enum
from contextlib import asynccontextmanager
import scipy.stats as stats
from scipy.optimize import minimize

# Binance API import
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils', 'binance_api'))
from binance_a import BinanceAggregator

# Configure logging
logger = logging.getLogger(__name__)

class MarketRegime(Enum):
    """Piyasa rejimleri"""
    TREND = "trend"
    RANGE = "range"
    TRANSITION = "transition"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"

@dataclass
class VolatilityMetrics:
    """Volatilite metrik veri yapısı"""
    historical_volatility: float
    atr: float
    bollinger_width: float
    garch_volatility: float
    entropy_index: float
    hurst_exponent: float
    regime_probability: float

class VolatilityRegimeAnalyzer:
    """
    Volatilite ve Piyasa Rejimi analiz sınıfı
    Thread-safe + GARCH modelleme + Entropy analizi
    """
    
    def __init__(self):
        self.binance = BinanceAggregator()
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()
        self._analysis_lock = asyncio.Lock()
        self._garch_cache: Dict[str, Any] = {}
        
        # Performance monitoring
        self._execution_count = 0
        self._cache_hits = 0
        
        logger.info("VolatilityRegimeAnalyzer initialized")
    
    async def cleanup(self):
        """Resource cleanup"""
        await self.binance.close()
        async with self._cache_lock:
            self._cache.clear()
            self._garch_cache.clear()
        logger.info("VolatilityRegimeAnalyzer cleanup completed")
    
    def _get_cache_key(self, symbol: str, interval: str = "1h", lookback: int = 100) -> str:
        """Cache key oluştur"""
        return f"volregime_{symbol}_{interval}_{lookback}"
    
    async def _get_cached_data(self, key: str) -> Optional[Any]:
        """Cache'den veri getir"""
        async with self._cache_lock:
            if key in self._cache:
                timestamp, data = self._cache[key]
                # 120 saniyelik cache TTL (volatilite daha yavaş değişir)
                if time.time() - timestamp < 120:
                    self._cache_hits += 1
                    return data
                else:
                    del self._cache[key]
            return None
    
    async def _set_cached_data(self, key: str, data: Any):
        """Cache'e veri kaydet"""
        async with self._cache_lock:
            self._cache[key] = (time.time(), data)
    
    async def _fetch_market_data(self, symbol: str) -> Tuple[List[float], List[float], List[float]]:
        """
        Spot ve futures verilerini paralel çek
        Validation + Error handling
        """
        try:
            # Input validation
            if not symbol or not isinstance(symbol, str):
                raise ValueError("Invalid symbol format")
            
            symbol = symbol.upper().strip()
            
            # Paralel veri çekme
            spot_task = self.binance.get_klines(symbol, "1h", 200)
            futures_task = self.binance.get_futures_data(symbol, "1h", 200)
            
            spot_data, futures_data = await asyncio.gather(
                spot_task, futures_task, return_exceptions=True
            )
            
            # Error handling
            if isinstance(spot_data, Exception):
                logger.warning(f"Spot data failed, using futures: {spot_data}")
                spot_data = []
            if isinstance(futures_data, Exception):
                logger.warning(f"Futures data failed, using spot: {futures_data}")
                futures_data = []
            
            # Price arrays oluştur
            closes = []
            if spot_data and len(spot_data) > 20:
                closes = [float(k[4]) for k in spot_data]  # close price
            elif futures_data and len(futures_data) > 20:
                closes = [float(k[4]) for k in futures_data]
            else:
                raise ValueError("Insufficient market data")
            
            # High/Low arrays (volatilite için)
            highs = []
            lows = []
            if spot_data:
                highs = [float(k[2]) for k in spot_data]
                lows = [float(k[3]) for k in spot_data]
            elif futures_data:
                highs = [float(k[2]) for k in futures_data]
                lows = [float(k[3]) for k in futures_data]
            
            return closes, highs, lows
            
        except Exception as e:
            logger.error(f"Market data fetch failed for {symbol}: {str(e)}")
            raise
    
    def _calculate_historical_volatility(self, prices: List[float], window: int = 20) -> float:
        """Historical volatility (σ) hesapla - annualized"""
        if len(prices) < window + 1:
            return 0.0
        
        try:
            returns = []
            for i in range(1, len(prices)):
                if prices[i-1] > 0:
                    ret = np.log(prices[i] / prices[i-1])
                    returns.append(ret)
            
            if len(returns) < window:
                return 0.0
            
            recent_returns = returns[-window:]
            std_daily = np.std(recent_returns)
            
            # Annualize (sqrt(365) for hourly data)
            annualized_vol = std_daily * np.sqrt(365)
            
            return float(annualized_vol)
        except Exception as e:
            logger.error(f"Historical volatility calculation error: {str(e)}")
            return 0.0
    
    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Average True Range hesapla"""
        if len(highs) < period or len(lows) < period or len(closes) < period:
            return 0.0
        
        try:
            true_ranges = []
            for i in range(1, len(highs)):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1])
                tr3 = abs(lows[i] - closes[i-1])
                true_ranges.append(max(tr1, tr2, tr3))
            
            if len(true_ranges) < period:
                return float(np.mean(true_ranges)) if true_ranges else 0.0
            
            return float(np.mean(true_ranges[-period:]))
        except Exception as e:
            logger.error(f"ATR calculation error: {str(e)}")
            return 0.0
    
    def _calculate_bollinger_width(self, prices: List[float], period: int = 20) -> float:
        """Bollinger Bands width hesapla (normalized)"""
        if len(prices) < period:
            return 0.0
        
        try:
            recent_prices = prices[-period:]
            middle = np.mean(recent_prices)
            std = np.std(recent_prices)
            
            upper = middle + (std * 2)
            lower = middle - (std * 2)
            
            # Normalized width
            width = (upper - lower) / middle if middle > 0 else 0.0
            
            return float(width)
        except Exception as e:
            logger.error(f"Bollinger width calculation error: {str(e)}")
            return 0.0
    
    def _garch_model(self, returns: List[float]) -> float:
        """
        Basitleştirilmiş GARCH(1,1) volatilite tahmini
        """
        if len(returns) < 30:
            return np.std(returns) if returns else 0.0
        
        try:
            # GARCH(1,1) parametre tahmini (basitleştirilmiş)
            omega = 0.05  # Constant
            alpha = 0.1   # ARCH parameter
            beta = 0.85   # GARCH parameter
            
            # Başlangıç volatilitesi
            sigma2 = [np.var(returns)]
            
            # GARCH recursion
            for i in range(1, len(returns)):
                new_sigma2 = omega + alpha * (returns[i-1] ** 2) + beta * sigma2[i-1]
                sigma2.append(new_sigma2)
            
            # Son volatilite (annualized)
            current_vol = np.sqrt(sigma2[-1]) * np.sqrt(365)
            
            return float(current_vol)
        except Exception as e:
            logger.error(f"GARCH model error: {str(e)}")
            return float(np.std(returns)) if returns else 0.0
    
    def _calculate_entropy_index(self, prices: List[float], window: int = 50) -> float:
        """
        Piyasa düzensizliği için Entropy Index
        Yüksek entropy = düzensiz/range, Düşük entropy = trend
        """
        if len(prices) < window:
            return 0.5  # Neutral
        
        try:
            recent_prices = prices[-window:]
            
            # Returns hesapla
            returns = []
            for i in range(1, len(recent_prices)):
                if recent_prices[i-1] > 0:
                    ret = np.log(recent_prices[i] / recent_prices[i-1])
                    returns.append(ret)
            
            if len(returns) < 10:
                return 0.5
            
            # Returns'ü binned histograma dönüştür
            hist, bin_edges = np.histogram(returns, bins=10, density=True)
            
            # Shannon entropy hesapla
            entropy = 0.0
            for prob in hist:
                if prob > 0:
                    entropy -= prob * np.log(prob)
            
            # Normalize et (0-1 arası)
            max_entropy = np.log(len(hist))
            normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.5
            
            return float(normalized_entropy)
        except Exception as e:
            logger.error(f"Entropy calculation error: {str(e)}")
            return 0.5
    
    def _calculate_hurst_exponent(self, prices: List[float], max_lag: int = 20) -> float:
        """
        Hurst Exponent - Piyasa hafızası ve trend kalıcılığı
        H > 0.5: Trend (persistent), H < 0.5: Mean-reverting (anti-persistent)
        """
        if len(prices) < max_lag * 2:
            return 0.5  # Random walk
        
        try:
            # Log returns
            returns = []
            for i in range(1, len(prices)):
                if prices[i-1] > 0:
                    ret = np.log(prices[i] / prices[i-1])
                    returns.append(ret)
            
            if len(returns) < max_lag * 2:
                return 0.5
            
            # R/S analysis
            lags = range(2, min(max_lag, len(returns)//2))
            rs_values = []
            
            for lag in lags:
                # Split into subsets
                n_subsets = len(returns) // lag
                if n_subsets < 2:
                    continue
                
                subset_r_s = []
                for i in range(n_subsets):
                    subset = returns[i*lag:(i+1)*lag]
                    if len(subset) < 2:
                        continue
                    
                    # Cumulative deviations
                    mean_subset = np.mean(subset)
                    deviations = subset - mean_subset
                    cumulative_deviations = np.cumsum(deviations)
                    
                    # Range
                    data_range = np.max(cumulative_deviations) - np.min(cumulative_deviations)
                    std_subset = np.std(subset)
                    
                    if std_subset > 0:
                        r_s = data_range / std_subset
                        subset_r_s.append(r_s)
                
                if subset_r_s:
                    rs_values.append(np.mean(subset_r_s))
            
            if len(rs_values) < 2:
                return 0.5
            
            # Linear regression for Hurst exponent
            lags_array = np.log(np.array(lags[:len(rs_values)]))
            rs_array = np.log(np.array(rs_values))
            
            if len(lags_array) < 2:
                return 0.5
            
            hurst, _ = np.polyfit(lags_array, rs_array, 1)
            
            return float(hurst)
        except Exception as e:
            logger.error(f"Hurst exponent calculation error: {str(e)}")
            return 0.5
    
    def _regime_switching_model(self, metrics: VolatilityMetrics) -> Tuple[MarketRegime, float]:
        """
        Regime Switching Model - Trend/Range ayrımı
        GARCH + Entropy + Hurst kombinasyonu
        """
        try:
            # Feature weighting
            volatility_weight = 0.3
            entropy_weight = 0.3
            hurst_weight = 0.4
            
            # Volatilite sinyali (yüksek volatilite = trend/transition)
            vol_signal = min(metrics.historical_volatility / 0.5, 1.0)  # 50% vol threshold
            
            # Entropy sinyali (yüksek entropy = range)
            entropy_signal = metrics.entropy_index
            
            # Hurst sinyali (H > 0.6 = trend, H < 0.4 = mean-reverting)
            hurst_signal = 0.0
            if metrics.hurst_exponent > 0.6:
                hurst_signal = (metrics.hurst_exponent - 0.6) / 0.4  # 0.6-1.0 -> 0-1
            elif metrics.hurst_exponent < 0.4:
                hurst_signal = -((0.4 - metrics.hurst_exponent) / 0.4)  # 0-0.4 -> 0 to -1
            
            # Composite regime score
            regime_score = (
                vol_signal * volatility_weight +
                (1 - entropy_signal) * entropy_weight +  # Low entropy favors trend
                hurst_signal * hurst_weight
            )
            
            # Regime classification
            if regime_score > 0.3:
                regime = MarketRegime.TREND
                probability = min((regime_score - 0.3) / 0.7, 1.0)
            elif regime_score < -0.2:
                regime = MarketRegime.RANGE
                probability = min((-regime_score - 0.2) / 0.8, 1.0)
            elif vol_signal > 0.7:
                regime = MarketRegime.HIGH_VOLATILITY
                probability = vol_signal
            elif vol_signal < 0.3:
                regime = MarketRegime.LOW_VOLATILITY
                probability = 1 - vol_signal
            else:
                regime = MarketRegime.TRANSITION
                probability = 0.5
            
            return regime, probability
            
        except Exception as e:
            logger.error(f"Regime switching model error: {str(e)}")
            return MarketRegime.TRANSITION, 0.5
    
    async def _calculate_volatility_metrics(self, symbol: str) -> VolatilityMetrics:
        """
        Tüm volatilite metriklerini hesapla
        Thread-safe + Cache optimized
        """
        cache_key = self._get_cache_key(symbol)
        cached_data = await self._get_cached_data(cache_key)
        
        if cached_data:
            logger.debug(f"Using cached volatility metrics for {symbol}")
            return cached_data
        
        async with self._analysis_lock:
            # Market verisini çek
            closes, highs, lows = await self._fetch_market_data(symbol)
            
            if len(closes) < 50:
                raise ValueError(f"Insufficient data for volatility analysis: {len(closes)} points")
            
            # Returns hesapla
            returns = []
            for i in range(1, len(closes)):
                if closes[i-1] > 0:
                    ret = np.log(closes[i] / closes[i-1])
                    returns.append(ret)
            
            # Klasik metrikler
            historical_vol = self._calculate_historical_volatility(closes)
            atr = self._calculate_atr(highs, lows, closes)
            bollinger_width = self._calculate_bollinger_width(closes)
            
            # Profesyonel metrikler
            garch_vol = self._garch_model(returns)
            entropy_index = self._calculate_entropy_index(closes)
            hurst_exponent = self._calculate_hurst_exponent(closes)
            
            metrics = VolatilityMetrics(
                historical_volatility=historical_vol,
                atr=atr,
                bollinger_width=bollinger_width,
                garch_volatility=garch_vol,
                entropy_index=entropy_index,
                hurst_exponent=hurst_exponent,
                regime_probability=0.0  # Will be calculated later
            )
            
            # Cache'e kaydet
            await self._set_cached_data(cache_key, metrics)
            
            return metrics
    
    def _determine_market_regime(self, metrics: VolatilityMetrics) -> Dict[str, Any]:
        """
        Piyasa rejimini belirle ve detaylı sonuç oluştur
        """
        regime, probability = self._regime_switching_model(metrics)
        
        # Confidence scoring
        confidence = 0.0
        if probability > 0.7:
            confidence = probability
        elif probability > 0.5:
            confidence = 0.7
        else:
            confidence = 0.5
        
        result = {
            "regime": regime.value,
            "probability": probability,
            "confidence": confidence,
            "volatility_level": "high" if metrics.historical_volatility > 0.4 else "low",
            "market_structure": "trending" if regime == MarketRegime.TREND else "ranging",
            "metrics": {
                "historical_volatility": metrics.historical_volatility,
                "atr": metrics.atr,
                "bollinger_width": metrics.bollinger_width,
                "garch_volatility": metrics.garch_volatility,
                "entropy_index": metrics.entropy_index,
                "hurst_exponent": metrics.hurst_exponent
            }
        }
        
        return result

# Global analyzer instance
_analyzer: Optional[VolatilityRegimeAnalyzer] = None
_analyzer_lock = asyncio.Lock()

async def get_analyzer() -> VolatilityRegimeAnalyzer:
    """Thread-safe analyzer instance getter"""
    global _analyzer
    async with _analyzer_lock:
        if _analyzer is None:
            _analyzer = VolatilityRegimeAnalyzer()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Ana analiz fonksiyonu - schema_manager ve analysis_core ile uyumlu
    
    Args:
        symbol: Analiz edilecek sembol (örn: BTCUSDT)
        priority: Öncelik seviyesi (*, **, ***)
    
    Returns:
        Piyasa rejimi analiz sonuçları
    """
    start_time = time.time()
    logger.info(f"Starting volatility regime analysis for {symbol}, priority: {priority}")
    
    try:
        # Input validation
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol parameter")
        
        symbol = symbol.upper().strip()
        
        # Analyzer instance al
        analyzer = await get_analyzer()
        
        # Volatilite metriklerini hesapla
        metrics = await analyzer._calculate_volatility_metrics(symbol)
        
        # Piyasa rejimini belirle
        regime_result = analyzer._determine_market_regime(metrics)
        
        # Priority-based result filtering
        result_data = {
            "symbol": symbol,
            "priority": priority,
            "timestamp": time.time(),
            "regime": regime_result["regime"],
            "probability": regime_result["probability"],
            "confidence": regime_result["confidence"],
            "volatility_level": regime_result["volatility_level"],
            "market_structure": regime_result["market_structure"]
        }
        
        # Temel metrikleri her zaman ekle
        result_data["metrics"] = {
            "historical_volatility": metrics.historical_volatility,
            "atr": metrics.atr,
            "bollinger_width": metrics.bollinger_width
        }
        
        # Profesyonel metrikleri priority'ye göre ekle
        if priority in ["**", "***"]:
            result_data["metrics"]["garch_volatility"] = metrics.garch_volatility
            result_data["metrics"]["entropy_index"] = metrics.entropy_index
        
        if priority == "***":
            result_data["metrics"]["hurst_exponent"] = metrics.hurst_exponent
            result_data["regime_components"] = {
                "volatility_contribution": metrics.historical_volatility,
                "entropy_contribution": metrics.entropy_index,
                "hurst_contribution": metrics.hurst_exponent
            }
        
        execution_time = time.time() - start_time
        logger.info(
            f"Volatility regime analysis completed for {symbol}: "
            f"regime={regime_result['regime']}, probability={regime_result['probability']:.3f}, "
            f"time={execution_time:.2f}s"
        )
        
        return result_data
        
    except asyncio.CancelledError:
        logger.warning(f"Volatility regime analysis cancelled for {symbol}")
        raise
        
    except Exception as e:
        logger.error(f"Volatility regime analysis failed for {symbol}: {str(e)}", exc_info=True)
        return {
            "symbol": symbol,
            "priority": priority,
            "timestamp": time.time(),
            "regime": "unknown",
            "probability": 0.5,
            "confidence": 0.0,
            "error": f"Analysis failed: {str(e)}",
            "metrics": {}
        }

async def cleanup():
    """Global cleanup fonksiyonu"""
    global _analyzer
    if _analyzer:
        await _analyzer.cleanup()
        _analyzer = None

# Test için
if __name__ == "__main__":
    import asyncio
    
    async def test_analysis():
        result = await run("BTCUSDT", priority="***")
        print("Test Result:", result)
    
    asyncio.run(test_analysis())