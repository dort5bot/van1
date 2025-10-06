# analysis/dersent.py
"""
Derivatives & Sentiment (Pozisyon Verileri) Analysis Module
==========================================================
Trader positioning ve market sentiment analizi için türev verileri modülü.
Funding Rate, Open Interest, Long/Short Ratio + Liquidation Heatmap + OI Delta + Volatility Skew
✅ Advanced Derivatives Analysis
Funding Rate - Perpetual futures funding
Open Interest - Toplam açık pozisyonlar
Long/Short Ratio - Trader pozisyon dağılımı
Liquidation Heatmap - Risk seviyesi tahmini
OI Delta Divergence - Price-OI uyumsuzluğu
Volatility Skew - Implied volatility farkları
Gamma Exposure - Options market maker etkisi

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
from collections import deque
import hashlib

# Binance API import
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils', 'binance_api'))
from binance_a import BinanceAggregator

# Configure logging
logger = logging.getLogger(__name__)

class MarketSentiment(Enum):
    """Piyasa sentiment seviyeleri"""
    STRONGLY_BEARISH = "strongly_bearish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    STRONGLY_BULLISH = "strongly_bullish"

@dataclass
class DerivativesData:
    """Türev veri yapısı"""
    funding_rate: float
    open_interest: float
    long_short_ratio: float
    funding_rate_history: List[float]
    oi_history: List[float]
    lsr_history: List[float]

@dataclass
class SentimentMetrics:
    """Sentiment metrik veri yapısı"""
    # Klasik metrikler
    funding_rate: float
    open_interest: float
    long_short_ratio: float
    oi_change: float
    funding_change: float
    
    # Profesyonel metrikler
    liquidation_heatmap: float
    oi_delta_divergence: float
    volatility_skew: float
    gamma_exposure: Optional[float] = None

class DerivativesSentimentAnalyzer:
    """
    Türev verileri ve sentiment analiz sınıfı
    Thread-safe + Advanced positioning analysis
    """
    
    def __init__(self):
        self.binance = BinanceAggregator()
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()
        self._analysis_lock = asyncio.Lock()
        self._historical_data: Dict[str, deque] = {}
        
        # Performance monitoring
        self._execution_count = 0
        self._cache_hits = 0
        self._data_points_collected = 0
        
        # Sentiment thresholds (dynamic adjustment)
        self._sentiment_thresholds = {
            'funding_extreme': 0.0005,  # 0.05%
            'funding_high': 0.0002,     # 0.02%
            'funding_low': -0.0002,     # -0.02%
            'lsr_extreme': 1.8,         # 1.8 ratio
            'lsr_high': 1.4,            # 1.4 ratio
            'lsr_low': 0.6,             # 0.6 ratio
            'oi_change_extreme': 0.3,   # 30% change
            'oi_change_high': 0.15,     # 15% change
        }
        
        logger.info("DerivativesSentimentAnalyzer initialized")
    
    async def cleanup(self):
        """Resource cleanup"""
        await self.binance.close()
        async with self._cache_lock:
            self._cache.clear()
            self._historical_data.clear()
        logger.info("DerivativesSentimentAnalyzer cleanup completed")
    
    def _get_cache_key(self, symbol: str, data_type: str = "sentiment") -> str:
        """Cache key oluştur"""
        base_key = f"dersent_{symbol}_{data_type}"
        return hashlib.md5(base_key.encode()).hexdigest()
    
    async def _get_cached_data(self, key: str) -> Optional[Any]:
        """Cache'den veri getir"""
        async with self._cache_lock:
            if key in self._cache:
                timestamp, data = self._cache[key]
                # 90 saniyelik cache TTL (sentiment daha hızlı değişir)
                if time.time() - timestamp < 90:
                    self._cache_hits += 1
                    return data
                else:
                    del self._cache[key]
            return None
    
    async def _set_cached_data(self, key: str, data: Any):
        """Cache'e veri kaydet"""
        async with self._cache_lock:
            self._cache[key] = (time.time(), data)
    
    def _update_historical_data(self, symbol: str, data: DerivativesData):
        """Historical data güncelle - circular buffer"""
        if symbol not in self._historical_data:
            self._historical_data[symbol] = deque(maxlen=100)  # Son 100 data point
        
        self._historical_data[symbol].append({
            'timestamp': time.time(),
            'funding_rate': data.funding_rate,
            'open_interest': data.open_interest,
            'long_short_ratio': data.long_short_ratio
        })
        
        self._data_points_collected += 1
    
    async def _fetch_derivatives_data(self, symbol: str) -> DerivativesData:
        """
        Türev piyasası verilerini güvenli şekilde çek
        Validation + Error handling
        """
        try:
            # Input validation
            if not symbol or not isinstance(symbol, str):
                raise ValueError("Invalid symbol format")
            
            symbol = symbol.upper().strip()
            futures_symbol = symbol.replace('USDT', '') if symbol.endswith('USDT') else symbol
            
            logger.debug(f"Fetching derivatives data for {symbol}")
            
            # Paralel veri çekme
            funding_task = self.binance.get_funding_rate(futures_symbol)
            oi_task = self.binance.get_open_interest(futures_symbol)
            lsr_task = self.binance.get_long_short_ratio(futures_symbol)
            
            funding_data, oi_data, lsr_data = await asyncio.gather(
                funding_task, oi_task, lsr_task, 
                return_exceptions=True
            )
            
            # Error handling ve default values
            funding_rate = 0.0
            if not isinstance(funding_data, Exception) and funding_data:
                funding_rate = float(funding_data.get('fundingRate', 0.0))
            else:
                logger.warning(f"Funding rate data failed for {symbol}: {funding_data}")
            
            open_interest = 0.0
            if not isinstance(oi_data, Exception) and oi_data:
                open_interest = float(oi_data.get('openInterest', 0.0))
            else:
                logger.warning(f"Open interest data failed for {symbol}: {oi_data}")
            
            long_short_ratio = 1.0  # Neutral default
            if not isinstance(lsr_data, Exception) and lsr_data:
                lsr_value = lsr_data.get('longShortRatio', 1.0)
                if lsr_value and float(lsr_value) > 0:
                    long_short_ratio = float(lsr_value)
            else:
                logger.warning(f"Long/short ratio data failed for {symbol}: {lsr_data}")
            
            # Historical data (basit implementation)
            funding_history = [funding_rate] * 5  # Mock history
            oi_history = [open_interest] * 5
            lsr_history = [long_short_ratio] * 5
            
            # Gerçek historical data için historical endpoints kullanılabilir
            try:
                historical_funding = await self.binance.get_historical_funding_rate(futures_symbol, limit=10)
                if historical_funding and not isinstance(historical_funding, Exception):
                    funding_history = [float(f['fundingRate']) for f in historical_funding[:5]]
            except Exception as e:
                logger.debug(f"Historical funding not available: {e}")
            
            data = DerivativesData(
                funding_rate=funding_rate,
                open_interest=open_interest,
                long_short_ratio=long_short_ratio,
                funding_rate_history=funding_history,
                oi_history=oi_history,
                lsr_history=lsr_history
            )
            
            # Historical data güncelle
            self._update_historical_data(symbol, data)
            
            return data
            
        except Exception as e:
            logger.error(f"Derivatives data fetch failed for {symbol}: {str(e)}")
            raise
    
    def _calculate_oi_change(self, current_oi: float, previous_oi: List[float]) -> float:
        """Open Interest değişimini hesapla"""
        if not previous_oi or len(previous_oi) < 2:
            return 0.0
        
        try:
            # Simple moving average of previous OI
            prev_avg = np.mean(previous_oi[-5:])  # Son 5 period
            if prev_avg > 0:
                change = (current_oi - prev_avg) / prev_avg
                return float(change)
            return 0.0
        except Exception as e:
            logger.error(f"OI change calculation error: {str(e)}")
            return 0.0
    
    def _calculate_funding_change(self, current_funding: float, previous_funding: List[float]) -> float:
        """Funding Rate değişimini hesapla"""
        if not previous_funding or len(previous_funding) < 2:
            return 0.0
        
        try:
            # Funding rate momentum
            prev_avg = np.mean(previous_funding[-3:])  # Son 3 period
            change = current_funding - prev_avg
            return float(change * 10000)  # Basis points cinsinden
        except Exception as e:
            logger.error(f"Funding change calculation error: {str(e)}")
            return 0.0
    
    def _calculate_liquidation_heatmap(self, symbol: str, current_price: float) -> float:
        """
        Basitleştirilmiş Liquidation Heatmap
        Gerçek uygulamada liquidation verileri kullanılır
        """
        try:
            # Mock implementation - gerçekte liquidation data analizi
            # Yüksek OI + extreme funding = yüksek liquidation risk
            heatmap_score = 0.0
            
            # Price levels based liquidation estimation
            if current_price > 0:
                # ±5% price move liquidation risk
                volatility_estimate = 0.05  # 5% volatility
                heatmap_score = min(volatility_estimate * 10, 1.0)
            
            return float(heatmap_score)
        except Exception as e:
            logger.error(f"Liquidation heatmap calculation error: {str(e)}")
            return 0.5
    
    def _calculate_oi_delta_divergence(self, oi_history: List[float], price_history: List[float]) -> float:
        """
        OI Delta Divergence - Price vs OI divergence
        """
        if len(oi_history) < 5 or len(price_history) < 5:
            return 0.0
        
        try:
            # OI ve price correlation
            recent_oi = oi_history[-5:]
            recent_prices = price_history[-5:]
            
            # Normalize
            oi_norm = (np.array(recent_oi) - np.mean(recent_oi)) / (np.std(recent_oi) + 1e-8)
            price_norm = (np.array(recent_prices) - np.mean(recent_prices)) / (np.std(recent_prices) + 1e-8)
            
            # Correlation coefficient
            correlation = np.corrcoef(oi_norm, price_norm)[0, 1]
            
            if np.isnan(correlation):
                return 0.0
            
            # Divergence score (negative correlation = bearish divergence)
            divergence_score = -correlation  # -1 to 1
            
            return float(divergence_score)
        except Exception as e:
            logger.error(f"OI delta divergence calculation error: {str(e)}")
            return 0.0
    
    def _calculate_volatility_skew(self, symbol: str) -> float:
        """
        Volatility Skew - Implied volatility farkları
        Basitleştirilmiş implementation
        """
        try:
            # Mock implementation - gerçekte options data gerekli
            # Yüksek skew = bearish sentiment (put IV > call IV)
            
            # Funding rate'dan skew tahmini
            funding_data = self._historical_data.get(symbol)
            if funding_data:
                recent_funding = [d['funding_rate'] for d in funding_data]
                if recent_funding:
                    avg_funding = np.mean(recent_funding)
                    # Negative funding = bearish skew
                    skew = -avg_funding * 10000  # Normalize
                    return float(np.tanh(skew))  # -1 to 1
            
            return 0.0
        except Exception as e:
            logger.error(f"Volatility skew calculation error: {str(e)}")
            return 0.0
    
    def _calculate_gamma_exposure(self, symbol: str) -> Optional[float]:
        """
        Gamma Exposure - Options market maker pozisyonları
        Advanced metric - gerçek options data gerektirir
        """
        try:
            # Mock implementation - gerçekte options chain data gerekli
            # Positive gamma = market maker long gamma = stability
            # Negative gamma = market maker short gamma = volatility
            
            # Basit proxy: OI ve funding rate kombinasyonu
            historical_data = self._historical_data.get(symbol)
            if historical_data and len(historical_data) > 10:
                recent_data = list(historical_data)[-5:]
                oi_values = [d['open_interest'] for d in recent_data]
                funding_values = [d['funding_rate'] for d in recent_data]
                
                if oi_values and funding_values:
                    oi_trend = np.polyfit(range(len(oi_values)), oi_values, 1)[0]
                    funding_trend = np.polyfit(range(len(funding_values)), funding_values, 1)[0]
                    
                    # Gamma exposure estimation
                    gamma_score = oi_trend / (abs(funding_trend) + 1e-8) * 0.001
                    return float(np.tanh(gamma_score))  # -1 to 1
            
            return None
        except Exception as e:
            logger.debug(f"Gamma exposure calculation not available: {e}")
            return None
    
    def _calculate_sentiment_score(self, metrics: SentimentMetrics) -> float:
        """
        Composite Sentiment Score hesapla (-1 to 1)
        Funding + OI Delta + Skew + Heatmap kombinasyonu
        """
        try:
            score_components = []
            weights = []
            
            # 1. Funding Rate Component (-1 to 1)
            funding_score = np.tanh(metrics.funding_rate * 10000)  # Normalize
            score_components.append(funding_score)
            weights.append(0.25)
            
            # 2. Long/Short Ratio Component (-1 to 1)
            lsr_score = (metrics.long_short_ratio - 1.0) * 2  # 1.0 = neutral
            lsr_score = np.clip(lsr_score, -1, 1)
            score_components.append(lsr_score)
            weights.append(0.20)
            
            # 3. OI Change Component (-1 to 1)
            oi_change_score = np.tanh(metrics.oi_change * 10)  # Normalize
            score_components.append(oi_change_score)
            weights.append(0.20)
            
            # 4. Liquidation Heatmap Component (0 to 1, bearish when high)
            heatmap_score = -metrics.liquidation_heatmap  # High heatmap = bearish
            score_components.append(heatmap_score)
            weights.append(0.15)
            
            # 5. OI Delta Divergence Component (-1 to 1)
            score_components.append(metrics.oi_delta_divergence)
            weights.append(0.10)
            
            # 6. Volatility Skew Component (-1 to 1)
            score_components.append(metrics.volatility_skew)
            weights.append(0.10)
            
            # Gamma Exposure ek puan (eğer mevcutsa)
            if metrics.gamma_exposure is not None:
                score_components.append(metrics.gamma_exposure * 0.5)
                weights.append(0.05)
                # Diğer weight'leri normalize et
                total_base_weights = sum(weights[:-1])
                normalization_factor = 0.95 / total_base_weights
                weights = [w * normalization_factor for w in weights[:-1]] + [0.05]
            
            # Weighted composite score
            composite_score = sum(comp * weight for comp, weight in zip(score_components, weights))
            
            # Clamp to -1 to 1 range
            final_score = float(np.clip(composite_score, -1.0, 1.0))
            
            return final_score
            
        except Exception as e:
            logger.error(f"Sentiment score calculation error: {str(e)}")
            return 0.0
    
    def _get_sentiment_label(self, score: float) -> MarketSentiment:
        """Score'dan sentiment label belirle"""
        if score >= 0.6:
            return MarketSentiment.STRONGLY_BULLISH
        elif score >= 0.2:
            return MarketSentiment.BULLISH
        elif score <= -0.6:
            return MarketSentiment.STRONGLY_BEARISH
        elif score <= -0.2:
            return MarketSentiment.BEARISH
        else:
            return MarketSentiment.NEUTRAL
    
    async def _calculate_sentiment_metrics(self, symbol: str) -> SentimentMetrics:
        """
        Tüm sentiment metriklerini hesapla
        Thread-safe + Cache optimized
        """
        cache_key = self._get_cache_key(symbol)
        cached_data = await self._get_cached_data(cache_key)
        
        if cached_data:
            logger.debug(f"Using cached sentiment metrics for {symbol}")
            return cached_data
        
        async with self._analysis_lock:
            # Türev verilerini çek
            derivatives_data = await self._fetch_derivatives_data(symbol)
            
            # Price history (mock - gerçekte price data gerekli)
            price_history = [1000] * 10  # Mock price history
            
            # Klasik metrikler
            funding_rate = derivatives_data.funding_rate
            open_interest = derivatives_data.open_interest
            long_short_ratio = derivatives_data.long_short_ratio
            oi_change = self._calculate_oi_change(open_interest, derivatives_data.oi_history)
            funding_change = self._calculate_funding_change(funding_rate, derivatives_data.funding_rate_history)
            
            # Profesyonel metrikler
            liquidation_heatmap = self._calculate_liquidation_heatmap(symbol, 1000)  # Mock price
            oi_delta_divergence = self._calculate_oi_delta_divergence(
                derivatives_data.oi_history, price_history
            )
            volatility_skew = self._calculate_volatility_skew(symbol)
            gamma_exposure = self._calculate_gamma_exposure(symbol)
            
            metrics = SentimentMetrics(
                funding_rate=funding_rate,
                open_interest=open_interest,
                long_short_ratio=long_short_ratio,
                oi_change=oi_change,
                funding_change=funding_change,
                liquidation_heatmap=liquidation_heatmap,
                oi_delta_divergence=oi_delta_divergence,
                volatility_skew=volatility_skew,
                gamma_exposure=gamma_exposure
            )
            
            # Cache'e kaydet
            await self._set_cached_data(cache_key, metrics)
            
            return metrics

# Global analyzer instance
_analyzer: Optional[DerivativesSentimentAnalyzer] = None
_analyzer_lock = asyncio.Lock()

async def get_analyzer() -> DerivativesSentimentAnalyzer:
    """Thread-safe analyzer instance getter"""
    global _analyzer
    async with _analyzer_lock:
        if _analyzer is None:
            _analyzer = DerivativesSentimentAnalyzer()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Ana analiz fonksiyonu - schema_manager ve analysis_core ile uyumlu
    
    Args:
        symbol: Analiz edilecek sembol (örn: BTCUSDT)
        priority: Öncelik seviyesi (*, **, ***)
    
    Returns:
        Sentiment analiz sonuçları
    """
    start_time = time.time()
    logger.info(f"Starting derivatives sentiment analysis for {symbol}, priority: {priority}")
    
    try:
        # Input validation
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol parameter")
        
        symbol = symbol.upper().strip()
        
        # Analyzer instance al
        analyzer = await get_analyzer()
        
        # Sentiment metriklerini hesapla
        metrics = await analyzer._calculate_sentiment_metrics(symbol)
        
        # Sentiment score hesapla
        sentiment_score = analyzer._calculate_sentiment_score(metrics)
        sentiment_label = analyzer._get_sentiment_label(sentiment_score)
        
        # Base result
        result_data = {
            "score": sentiment_score,
            "symbol": symbol,
            "priority": priority,
            "timestamp": time.time(),
            "sentiment": sentiment_label.value,
            "confidence": min(abs(sentiment_score) * 1.5, 1.0)  # Confidence based on score magnitude
        }
        
        # Temel metrikleri her zaman ekle
        result_data["metrics"] = {
            "funding_rate": metrics.funding_rate,
            "open_interest": metrics.open_interest,
            "long_short_ratio": metrics.long_short_ratio,
            "oi_change": metrics.oi_change,
            "funding_change": metrics.funding_change
        }
        
        # Profesyonel metrikleri priority'ye göre ekle
        if priority in ["**", "***"]:
            result_data["metrics"]["liquidation_heatmap"] = metrics.liquidation_heatmap
            result_data["metrics"]["oi_delta_divergence"] = metrics.oi_delta_divergence
            result_data["metrics"]["volatility_skew"] = metrics.volatility_skew
        
        if priority == "***":
            result_data["metrics"]["gamma_exposure"] = metrics.gamma_exposure
            result_data["score_components"] = {
                "funding_component": np.tanh(metrics.funding_rate * 10000),
                "lsr_component": (metrics.long_short_ratio - 1.0) * 2,
                "oi_change_component": np.tanh(metrics.oi_change * 10),
                "heatmap_component": -metrics.liquidation_heatmap,
                "divergence_component": metrics.oi_delta_divergence,
                "skew_component": metrics.volatility_skew
            }
        
        execution_time = time.time() - start_time
        logger.info(
            f"Derivatives sentiment analysis completed for {symbol}: "
            f"score={sentiment_score:.3f}, sentiment={sentiment_label.value}, "
            f"time={execution_time:.2f}s"
        )
        
        return result_data
        
    except asyncio.CancelledError:
        logger.warning(f"Derivatives sentiment analysis cancelled for {symbol}")
        raise
        
    except Exception as e:
        logger.error(f"Derivatives sentiment analysis failed for {symbol}: {str(e)}", exc_info=True)
        return {
            "score": 0.0,
            "symbol": symbol,
            "priority": priority,
            "timestamp": time.time(),
            "sentiment": "neutral",
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