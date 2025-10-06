# analysis/tremo.py
"""
Trend & Momentum (TA) Analysis Module
=====================================
Trend yönü ve momentum gücü analizi için teknik analiz modülü.
EMA, RSI, MACD, Bollinger Bands, ATR + Kalman Filter + Wavelet Transform

Modül şu metriklere sahip:
✅ Klasik: EMA, RSI, MACD, Bollinger Bands, ATR
✅ Profesyonel: Kalman Filter, Z-Score, Wavelet Transform, Hilbert Slope
✅ Composite: EMA + RSI + MACD + Kalman Filter kombinasyonu
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from dataclasses import dataclass
from contextlib import asynccontextmanager

# Binance API import
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils', 'binance_api'))
from binance_a import BinanceAggregator

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class TechnicalIndicators:
    """Teknik gösterge veri yapısı"""
    ema_fast: float
    ema_slow: float
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bollinger_upper: float
    bollinger_lower: float
    bollinger_middle: float
    atr: float
    kalman_trend: float
    z_score: float
    wavelet_coefficient: Optional[float] = None
    hilbert_slope: Optional[float] = None

class TrendMomentumAnalyzer:
    """
    Trend ve Momentum analiz sınıfı
    Thread-safe + Cache optimized + Error handling
    """
    
    def __init__(self):
        self.binance = BinanceAggregator()
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()
        self._analysis_lock = asyncio.Lock()
        
        # Performance monitoring
        self._execution_count = 0
        self._cache_hits = 0
        
        logger.info("TrendMomentumAnalyzer initialized")
    
    async def cleanup(self):
        """Resource cleanup"""
        await self.binance.close()
        async with self._cache_lock:
            self._cache.clear()
        logger.info("TrendMomentumAnalyzer cleanup completed")
    
    def _get_cache_key(self, symbol: str, interval: str = "1h", lookback: int = 100) -> str:
        """Cache key oluştur"""
        return f"{symbol}_{interval}_{lookback}"
    
    async def _get_cached_data(self, key: str) -> Optional[Any]:
        """Cache'den veri getir"""
        async with self._cache_lock:
            if key in self._cache:
                timestamp, data = self._cache[key]
                # 60 saniyelik cache TTL
                if time.time() - timestamp < 60:
                    self._cache_hits += 1
                    return data
                else:
                    del self._cache[key]
            return None
    
    async def _set_cached_data(self, key: str, data: Any):
        """Cache'e veri kaydet"""
        async with self._cache_lock:
            self._cache[key] = (time.time(), data)
    
    async def _fetch_klines_data(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """
        Binance klines verisini güvenli şekilde çek
        Validation + Error handling
        """
        try:
            # Input validation
            if not symbol or not isinstance(symbol, str):
                raise ValueError("Invalid symbol format")
            
            symbol = symbol.upper().strip()
            valid_intervals = ["1m", "5m", "15m", "1h", "4h", "1d"]
            if interval not in valid_intervals:
                raise ValueError(f"Invalid interval. Must be one of {valid_intervals}")
            
            logger.debug(f"Fetching klines for {symbol} with interval {interval}")
            
            # Binance aggregator üzerinden veri çek
            klines_data = await self.binance.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            if not klines_data or len(klines_data) < 20:
                raise ValueError(f"Insufficient data for {symbol}")
            
            return klines_data
            
        except Exception as e:
            logger.error(f"Klines data fetch failed for {symbol}: {str(e)}")
            raise
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Exponential Moving Average hesapla"""
        if len(prices) < period:
            return np.mean(prices) if prices else 0.0
        
        try:
            prices_array = np.array(prices[-period:])
            weights = np.exp(np.linspace(-1., 0., period))
            weights /= weights.sum()
            return float(np.dot(prices_array, weights))
        except Exception as e:
            logger.error(f"EMA calculation error: {str(e)}")
            return float(np.mean(prices)) if prices else 0.0
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Relative Strength Index hesapla"""
        if len(prices) < period + 1:
            return 50.0  # Neutral RSI
        
        try:
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            
            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])
            
            if avg_loss == 0:
                return 100.0 if avg_gain > 0 else 50.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return float(np.clip(rsi, 0, 100))
        except Exception as e:
            logger.error(f"RSI calculation error: {str(e)}")
            return 50.0
    
    def _calculate_macd(self, prices: List[float]) -> Tuple[float, float, float]:
        """MACD, Signal ve Histogram hesapla"""
        if len(prices) < 26:
            return 0.0, 0.0, 0.0
        
        try:
            ema_12 = self._calculate_ema(prices, 12)
            ema_26 = self._calculate_ema(prices, 26)
            macd = ema_12 - ema_26
            
            # MACD signal (EMA of MACD)
            macd_values = [self._calculate_ema(prices[i-8:i+1], 9) for i in range(8, len(prices))]
            if macd_values:
                macd_signal = macd_values[-1]
            else:
                macd_signal = macd
            
            macd_histogram = macd - macd_signal
            
            return float(macd), float(macd_signal), float(macd_histogram)
        except Exception as e:
            logger.error(f"MACD calculation error: {str(e)}")
            return 0.0, 0.0, 0.0
    
    def _calculate_bollinger_bands(self, prices: List[float], period: int = 20) -> Tuple[float, float, float]:
        """Bollinger Bands hesapla"""
        if len(prices) < period:
            avg = np.mean(prices) if prices else 0.0
            return avg, avg, avg
        
        try:
            recent_prices = prices[-period:]
            middle = np.mean(recent_prices)
            std = np.std(recent_prices)
            
            upper = middle + (std * 2)
            lower = middle - (std * 2)
            
            return float(upper), float(middle), float(lower)
        except Exception as e:
            logger.error(f"Bollinger Bands calculation error: {str(e)}")
            avg = np.mean(prices) if prices else 0.0
            return avg, avg, avg
    
    def _calculate_atr(self, high: List[float], low: List[float], close: List[float], period: int = 14) -> float:
        """Average True Range hesapla"""
        if len(high) < period or len(low) < period or len(close) < period:
            return 0.0
        
        try:
            true_ranges = []
            for i in range(1, len(high)):
                tr1 = high[i] - low[i]
                tr2 = abs(high[i] - close[i-1])
                tr3 = abs(low[i] - close[i-1])
                true_ranges.append(max(tr1, tr2, tr3))
            
            if len(true_ranges) < period:
                return float(np.mean(true_ranges)) if true_ranges else 0.0
            
            return float(np.mean(true_ranges[-period:]))
        except Exception as e:
            logger.error(f"ATR calculation error: {str(e)}")
            return 0.0
    
    def _calculate_kalman_filter(self, prices: List[float]) -> float:
        """
        Basitleştirilmiş Kalman Filter trend tespiti
        """
        if len(prices) < 5:
            return 0.0
        
        try:
            # Basit lineer regresyon ile trend
            x = np.arange(len(prices))
            y = np.array(prices)
            
            # Robust lineer regresyon
            A = np.vstack([x, np.ones(len(x))]).T
            slope, _ = np.linalg.lstsq(A, y, rcond=None)[0]
            
            # Normalize trend skoru (-1 to 1)
            price_range = max(prices) - min(prices)
            if price_range > 0:
                trend_strength = slope / (price_range / len(prices))
                return float(np.tanh(trend_strength))  # -1 to 1 aralığına sıkıştır
            else:
                return 0.0
                
        except Exception as e:
            logger.error(f"Kalman filter calculation error: {str(e)}")
            return 0.0
    
    def _calculate_z_score(self, prices: List[float]) -> float:
        """Z-Score normalization"""
        if len(prices) < 10:
            return 0.0
        
        try:
            recent_prices = prices[-10:]
            mean = np.mean(recent_prices)
            std = np.std(recent_prices)
            
            if std > 0:
                return float((prices[-1] - mean) / std)
            else:
                return 0.0
        except Exception as e:
            logger.error(f"Z-Score calculation error: {str(e)}")
            return 0.0
    
    def _calculate_wavelet_transform(self, prices: List[float]) -> Optional[float]:
        """
        Basitleştirilmiş Wavelet Transform katsayısı
        Gerçek uygulamada pywt kütüphanesi kullanılabilir
        """
        if len(prices) < 8:
            return None
        
        try:
            # Basit high-pass filter (difference)
            differences = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            if differences:
                return float(np.mean(differences[-4:]))
            return None
        except Exception as e:
            logger.error(f"Wavelet transform calculation error: {str(e)}")
            return None
    
    def _calculate_hilbert_slope(self, prices: List[float]) -> Optional[float]:
        """
        Basitleştirilmiş Hilbert Transform slope
        """
        if len(prices) < 10:
            return None
        
        try:
            # Fiyat değişimlerinin slope'u
            recent_prices = prices[-10:]
            x = np.arange(len(recent_prices))
            slope, _ = np.polyfit(x, recent_prices, 1)
            return float(slope)
        except Exception as e:
            logger.error(f"Hilbert slope calculation error: {str(e)}")
            return None
    
    async def _calculate_technical_indicators(self, symbol: str) -> TechnicalIndicators:
        """
        Tüm teknik göstergeleri hesapla
        Thread-safe + Cache optimized
        """
        cache_key = self._get_cache_key(symbol)
        cached_data = await self._get_cached_data(cache_key)
        
        if cached_data:
            logger.debug(f"Using cached indicators for {symbol}")
            return cached_data
        
        async with self._analysis_lock:
            # Veriyi çek
            klines_data = await self._fetch_klines_data(symbol)
            
            # Price arrays oluştur
            closes = [float(k[4]) for k in klines_data]  # close price
            highs = [float(k[2]) for k in klines_data]   # high price
            lows = [float(k[3]) for k in klines_data]    # low price
            
            # Klasik metrikler
            ema_fast = self._calculate_ema(closes, 12)
            ema_slow = self._calculate_ema(closes, 26)
            rsi = self._calculate_rsi(closes)
            macd, macd_signal, macd_histogram = self._calculate_macd(closes)
            bollinger_upper, bollinger_middle, bollinger_lower = self._calculate_bollinger_bands(closes)
            atr = self._calculate_atr(highs, lows, closes)
            
            # Profesyonel metrikler
            kalman_trend = self._calculate_kalman_filter(closes)
            z_score = self._calculate_z_score(closes)
            wavelet_coefficient = self._calculate_wavelet_transform(closes)
            hilbert_slope = self._calculate_hilbert_slope(closes)
            
            indicators = TechnicalIndicators(
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                rsi=rsi,
                macd=macd,
                macd_signal=macd_signal,
                macd_histogram=macd_histogram,
                bollinger_upper=bollinger_upper,
                bollinger_lower=bollinger_lower,
                bollinger_middle=bollinger_middle,
                atr=atr,
                kalman_trend=kalman_trend,
                z_score=z_score,
                wavelet_coefficient=wavelet_coefficient,
                hilbert_slope=hilbert_slope
            )
            
            # Cache'e kaydet
            await self._set_cached_data(cache_key, indicators)
            
            return indicators
    
    def _calculate_trend_score(self, indicators: TechnicalIndicators) -> float:
        """
        Trend skorunu hesapla (0-1 arası)
        EMA + RSI + MACD histogram + Kalman Filter kombinasyonu
        """
        try:
            score_components = []
            
            # EMA trend (0-1)
            ema_trend = 1.0 if indicators.ema_fast > indicators.ema_slow else 0.0
            ema_strength = abs(indicators.ema_fast - indicators.ema_slow) / indicators.ema_slow
            ema_score = ema_trend * min(ema_strength * 10, 1.0)
            score_components.append(ema_score * 0.25)
            
            # RSI momentum (0-1)
            rsi_score = 0.0
            if indicators.rsi > 70:  # Overbought - uptrend
                rsi_score = (indicators.rsi - 70) / 30
            elif indicators.rsi < 30:  # Oversold - downtrend
                rsi_score = (30 - indicators.rsi) / 30
            else:  # Neutral
                rsi_score = 0.5 - abs(50 - indicators.rsi) / 40
            score_components.append(max(0, min(rsi_score, 1)) * 0.25)
            
            # MACD momentum (0-1)
            macd_strength = abs(indicators.macd_histogram) / (abs(indicators.macd) + 0.001)
            macd_direction = 1.0 if indicators.macd_histogram > 0 else 0.0
            macd_score = macd_direction * min(macd_strength * 5, 1.0)
            score_components.append(macd_score * 0.25)
            
            # Kalman Filter trend (0-1)
            kalman_score = (indicators.kalman_trend + 1) / 2  # -1,1 -> 0,1
            score_components.append(kalman_score * 0.25)
            
            # Composite score
            composite_score = sum(score_components)
            
            # Wavelet ve Hilbert ek destek
            if indicators.wavelet_coefficient is not None and indicators.wavelet_coefficient > 0:
                composite_score += 0.05
            if indicators.hilbert_slope is not None and indicators.hilbert_slope > 0:
                composite_score += 0.05
            
            return float(np.clip(composite_score, 0.0, 1.0))
            
        except Exception as e:
            logger.error(f"Trend score calculation error: {str(e)}")
            return 0.5  # Neutral score on error

# Global analyzer instance
_analyzer: Optional[TrendMomentumAnalyzer] = None
_analyzer_lock = asyncio.Lock()

async def get_analyzer() -> TrendMomentumAnalyzer:
    """Thread-safe analyzer instance getter"""
    global _analyzer
    async with _analyzer_lock:
        if _analyzer is None:
            _analyzer = TrendMomentumAnalyzer()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Ana analiz fonksiyonu - schema_manager ve analysis_core ile uyumlu
    
    Args:
        symbol: Analiz edilecek sembol (örn: BTCUSDT)
        priority: Öncelik seviyesi (*, **, ***)
    
    Returns:
        Analiz sonuçları dictionary
    """
    start_time = time.time()
    logger.info(f"Starting trend analysis for {symbol}, priority: {priority}")
    
    try:
        # Input validation
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol parameter")
        
        symbol = symbol.upper().strip()
        
        # Analyzer instance al
        analyzer = await get_analyzer()
        
        # Teknik göstergeleri hesapla
        indicators = await analyzer._calculate_technical_indicators(symbol)
        
        # Trend skorunu hesapla
        trend_score = analyzer._calculate_trend_score(indicators)
        
        # Priority-based result filtering
        result_data = {
            "score": trend_score,
            "symbol": symbol,
            "priority": priority,
            "timestamp": time.time(),
            "indicators": {
                "ema_fast": indicators.ema_fast,
                "ema_slow": indicators.ema_slow,
                "rsi": indicators.rsi,
                "macd": indicators.macd,
                "macd_histogram": indicators.macd_histogram,
                "bollinger_upper": indicators.bollinger_upper,
                "bollinger_lower": indicators.bollinger_lower,
                "atr": indicators.atr,
                "kalman_trend": indicators.kalman_trend,
                "z_score": indicators.z_score,
            }
        }
        
        # Profesyonel metrikleri priority'ye göre ekle
        if priority in ["**", "***"]:
            result_data["indicators"]["wavelet_coefficient"] = indicators.wavelet_coefficient
            result_data["indicators"]["hilbert_slope"] = indicators.hilbert_slope
        
        execution_time = time.time() - start_time
        logger.info(f"Trend analysis completed for {symbol}: score={trend_score:.3f}, time={execution_time:.2f}s")
        
        return result_data
        
    except asyncio.CancelledError:
        logger.warning(f"Trend analysis cancelled for {symbol}")
        raise
        
    except Exception as e:
        logger.error(f"Trend analysis failed for {symbol}: {str(e)}", exc_info=True)
        return {
            "score": 0.5,
            "symbol": symbol,
            "priority": priority,
            "timestamp": time.time(),
            "error": f"Analysis failed: {str(e)}",
            "indicators": {}
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
        result = await run("BTCUSDT", priority="**")
        print("Test Result:", result)
    
    asyncio.run(test_analysis())