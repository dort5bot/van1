"""
bot/analiz/tremo.py
Modüler Yapı:Singleton pattern+Async/await uyumlu+Cache mekanizması+Type hints ve docstrings+
Aiogram Entegrasyonu:Router pattern ile /tremo komutu+Markdown formatlı çıktı

Yön ve Momentum indikatörleri hesaplama modülü.
EMA Ribbon (20, 50, 200), RSI (14), MACD (12, 26, 9), 
SuperTrend (10, 3), Volume-Weighted MACD indikatörlerini hesaplar.

Özellikler:
- -1 (Bearish) ile +1 (Bullish) arası sinyal skoru
- BinanceAPI async/await uyumlu
- aiogram 3.x Router pattern ile entegrasyon
- Singleton pattern ile IndicatorService
- PEP8, type hints, docstrings, logging

Kullanım örneği:
    from utils.binance.binance_a import BinanceAPI
    from bot.analiz.tremo import TremoAnalyzer
    
    analyzer = TremoAnalyzer(binance_api)
    result = await analyzer.analyze("BTCUSDT", "1h")
    print(f"Sinyal Skoru: {result.signal_score}")
 5 Ana İndikatör:
EMA Ribbon (20, 50, 200)
RSI (14)
MACD (12, 26, 9)
SuperTrend (10, 3)
Volume-Weighted MACD

Sinyal Skoru Açıklaması:
- +1.0: Güçlü Bullish
- +0.5: Bullish
- 0.0: Nötr
- -0.5: Bearish
- -1.0: Güçlü Bearish
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

# Local imports
try:
    from utils.binance.binance_a import BinanceAPI
except ImportError:
    # Fallback for direct testing
    class BinanceAPI:
        pass

logger = logging.getLogger(__name__)

class SignalStrength(Enum):
    """Sinyal gücü enum."""
    STRONG_BULLISH = 1.0
    BULLISH = 0.5
    NEUTRAL = 0.0
    BEARISH = -0.5
    STRONG_BEARISH = -1.0

# -------------------------
# Numeric calculation helpers
# -------------------------

def sma(values: List[float], period: int) -> List[Optional[float]]:
    """Simple moving average."""
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    
    out: List[Optional[float]] = [None] * len(values)
    window_sum = 0.0
    
    for i in range(len(values)):
        window_sum += values[i]
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            out[i] = window_sum / period
    
    return out

def ema(values: List[float], period: int) -> List[Optional[float]]:
    """Exponential moving average."""
    if period <= 0 or not values:
        return [None] * len(values)
    
    out: List[Optional[float]] = [None] * len(values)
    alpha = 2.0 / (period + 1)
    
    # Initialize with SMA
    sma_vals = sma(values, period)
    prev_ema = None
    
    for i in range(len(values)):
        if sma_vals[i] is not None and prev_ema is None:
            prev_ema = sma_vals[i]
            out[i] = prev_ema
        elif prev_ema is not None:
            prev_ema = (values[i] * alpha) + (prev_ema * (1 - alpha))
            out[i] = prev_ema
        else:
            out[i] = None
    
    return out

def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index."""
    if len(values) < period + 1:
        return [None] * len(values)
    
    out: List[Optional[float]] = [None] * len(values)
    gains: List[float] = [0.0]
    losses: List[float] = [0.0]
    
    # Calculate gains and losses
    for i in range(1, len(values)):
        change = values[i] - values[i-1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    
    # Calculate initial averages
    avg_gain = sum(gains[1:period+1]) / period
    avg_loss = sum(losses[1:period+1]) / period
    
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    
    # Calculate subsequent values with Wilder smoothing
    for i in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - (100.0 / (1.0 + rs))
    
    return out

def macd(values: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """MACD indicator."""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    
    macd_line: List[Optional[float]] = []
    for i in range(len(values)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line.append(ema_fast[i] - ema_slow[i])
        else:
            macd_line.append(None)
    
    # For signal line, replace None with 0 for calculation
    macd_vals = [v if v is not None else 0.0 for v in macd_line]
    signal_line = ema(macd_vals, signal)
    
    histogram: List[Optional[float]] = []
    for i in range(len(values)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram.append(macd_line[i] - signal_line[i])
        else:
            histogram.append(None)
    
    return macd_line, signal_line, histogram

def supertrend(highs: List[float], lows: List[float], closes: List[float], period: int = 10, multiplier: float = 3.0) -> List[Optional[float]]:
    """SuperTrend indicator."""
    length = len(closes)
    if length < period:
        return [None] * length
    
    # Calculate True Range
    tr: List[float] = [0.0] * length
    for i in range(1, length):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr[i] = max(tr1, tr2, tr3)
    
    # Calculate ATR
    atr: List[Optional[float]] = [None] * length
    atr_sum = sum(tr[1:period+1])
    atr[period] = atr_sum / period
    
    for i in range(period+1, length):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    
    # Calculate SuperTrend
    st: List[Optional[float]] = [None] * length
    upper_band: List[Optional[float]] = [None] * length
    lower_band: List[Optional[float]] = [None] * length
    final_upper_band: List[Optional[float]] = [None] * length
    final_lower_band: List[Optional[float]] = [None] * length
    
    for i in range(period, length):
        if atr[i] is None:
            continue
            
        hl2 = (highs[i] + lows[i]) / 2.0
        upper_band[i] = hl2 + (multiplier * atr[i])
        lower_band[i] = hl2 - (multiplier * atr[i])
        
        if i == period:
            final_upper_band[i] = upper_band[i]
            final_lower_band[i] = lower_band[i]
            st[i] = lower_band[i]
        else:
            # Update upper band
            if upper_band[i] < final_upper_band[i-1] or closes[i-1] > final_upper_band[i-1]:
                final_upper_band[i] = upper_band[i]
            else:
                final_upper_band[i] = final_upper_band[i-1]
            
            # Update lower band
            if lower_band[i] > final_lower_band[i-1] or closes[i-1] < final_lower_band[i-1]:
                final_lower_band[i] = lower_band[i]
            else:
                final_lower_band[i] = final_lower_band[i-1]
            
            # Determine SuperTrend value
            if st[i-1] == final_upper_band[i-1]:
                if closes[i] <= final_upper_band[i]:
                    st[i] = final_upper_band[i]
                else:
                    st[i] = final_lower_band[i]
            else:
                if closes[i] >= final_lower_band[i]:
                    st[i] = final_lower_band[i]
                else:
                    st[i] = final_upper_band[i]
    
    return st

def vwmacd(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], 
           fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Volume Weighted MACD."""
    # Calculate VWAP-like price (typical price weighted by volume)
    vwap_prices: List[Optional[float]] = [None] * len(closes)
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    
    for i in range(len(closes)):
        typical_price = (highs[i] + lows[i] + closes[i]) / 3.0
        cumulative_pv += typical_price * volumes[i]
        cumulative_volume += volumes[i]
        
        if cumulative_volume > 0:
            vwap_prices[i] = cumulative_pv / cumulative_volume
        else:
            vwap_prices[i] = None
    
    # Use VWAP prices for MACD calculation
    vwap_vals = [v if v is not None else 0.0 for v in vwap_prices]
    return macd(vwap_vals, fast, slow, signal)

# -------------------------
# Data classes
# -------------------------

@dataclass
class TremoResult:
    """Tremo analiz sonuçları."""
    symbol: str
    interval: str
    close: float
    ema20: Optional[float]
    ema50: Optional[float]
    ema200: Optional[float]
    rsi14: Optional[float]
    macd_line: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    supertrend: Optional[float]
    vwmacd_line: Optional[float]
    vwmacd_signal: Optional[float]
    vwmacd_hist: Optional[float]
    signal_score: float
    signal_strength: SignalStrength
    
    def __str__(self) -> str:
        """String representation for easy reading."""
        lines = [
            f"=== TREMO ANALİZ: {self.symbol} {self.interval} ===",
            f"Fiyat: {self.close:.8f}",
            f"EMA Ribbon: 20={self.ema20:.8f}, 50={self.ema50:.8f}, 200={self.ema200:.8f}",
            f"RSI14: {self.rsi14:.2f}" if self.rsi14 else "RSI14: N/A",
            f"MACD: Line={self.macd_line:.8f}, Signal={self.macd_signal:.8f}, Hist={self.macd_hist:.8f}",
            f"SuperTrend: {self.supertrend:.8f}" if self.supertrend else "SuperTrend: N/A",
            f"VW-MACD: Line={self.vwmacd_line:.8f}, Signal={self.vwmacd_signal:.8f}, Hist={self.vwmacd_hist:.8f}",
            f"Sinyal Skoru: {self.signal_score:.2f} ({self.signal_strength.name})",
            "=== SONUÇ ==="
        ]
        return "\n".join(lines)

# -------------------------
# Main analyzer class
# -------------------------

class TremoAnalyzer:
    """Tremo Yön ve Momentum analiz sınıfı."""
    
    _instance: Optional[TremoAnalyzer] = None
    
    def __init__(self, binance_api: BinanceAPI, cache_ttl: float = 60.0):
        self.binance_api = binance_api
        self.cache_ttl = cache_ttl  # seconds
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        logger.info("TremoAnalyzer initialized")
    
    @classmethod
    def get_instance(cls, binance_api: BinanceAPI) -> TremoAnalyzer:
        """Singleton instance getter."""
        if cls._instance is None:
            cls._instance = cls(binance_api)
        return cls._instance
    
    async def _get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[List[Any]]:
        """Get klines data with caching."""
        cache_key = f"{symbol}_{interval}_{limit}"
        current_time = asyncio.get_event_loop().time()
        
        async with self._lock:
            if cache_key in self._cache:
                cached_time, data = self._cache[cache_key]
                if current_time - cached_time < self.cache_ttl:
                    logger.debug("Using cached klines for %s", cache_key)
                    return data
            
            logger.debug("Fetching fresh klines for %s", cache_key)
            klines = await self.binance_api.get_klines(symbol, interval, limit)
            self._cache[cache_key] = (current_time, klines)
            return klines
    
    def _parse_klines(self, klines: List[List[Any]]) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
        """Parse klines data into individual lists."""
        opens, highs, lows, closes, volumes = [], [], [], [], []
        
        for kline in klines:
            opens.append(float(kline[1]))
            highs.append(float(kline[2]))
            lows.append(float(kline[3]))
            closes.append(float(kline[4]))
            volumes.append(float(kline[5]))
        
        return opens, highs, lows, closes, volumes
    
    def _calculate_signal_score(self, result: TremoResult) -> float:
        """Calculate overall signal score from -1 (bearish) to +1 (bullish)."""
        signals = []
        
        # EMA Ribbon signals
        if result.ema20 and result.ema50 and result.ema200:
            if result.ema20 > result.ema50 > result.ema200:
                signals.append(1.0)  # Strong bullish trend
            elif result.ema20 > result.ema50:
                signals.append(0.5)  # Bullish trend
            elif result.ema20 < result.ema50 < result.ema200:
                signals.append(-1.0)  # Strong bearish trend
            elif result.ema20 < result.ema50:
                signals.append(-0.5)  # Bearish trend
        
        # RSI signals
        if result.rsi14:
            if result.rsi14 > 70:
                signals.append(-0.3)  # Overbought
            elif result.rsi14 < 30:
                signals.append(0.3)   # Oversold
            elif result.rsi14 > 50:
                signals.append(0.2)   # Bullish momentum
            else:
                signals.append(-0.2)  # Bearish momentum
        
        # MACD signals
        if result.macd_line and result.macd_signal:
            if result.macd_line > result.macd_signal and result.macd_hist and result.macd_hist > 0:
                signals.append(0.4)  # Bullish crossover
            elif result.macd_line < result.macd_signal and result.macd_hist and result.macd_hist < 0:
                signals.append(-0.4)  # Bearish crossover
        
        # SuperTrend signals
        if result.supertrend and result.close:
            if result.close > result.supertrend:
                signals.append(0.3)  # Bullish trend
            else:
                signals.append(-0.3)  # Bearish trend
        
        # VW-MACD signals
        if result.vwmacd_line and result.vwmacd_signal:
            if result.vwmacd_line > result.vwmacd_signal and result.vwmacd_hist and result.vwmacd_hist > 0:
                signals.append(0.3)  # Volume-confirmed bullish
            elif result.vwmacd_line < result.vwmacd_signal and result.vwmacd_hist and result.vwmacd_hist < 0:
                signals.append(-0.3)  # Volume-confirmed bearish
        
        # Calculate weighted average
        if not signals:
            return 0.0
        
        return sum(signals) / len(signals)
    
    def _get_signal_strength(self, score: float) -> SignalStrength:
        """Convert numeric score to SignalStrength enum."""
        if score >= 0.7:
            return SignalStrength.STRONG_BULLISH
        elif score >= 0.3:
            return SignalStrength.BULLISH
        elif score <= -0.7:
            return SignalStrength.STRONG_BEARISH
        elif score <= -0.3:
            return SignalStrength.BEARISH
        else:
            return SignalStrength.NEUTRAL
    
    async def analyze(self, symbol: str, interval: str = "1h", limit: int = 500) -> TremoResult:
        """Perform complete Tremo analysis."""
        logger.info("Starting Tremo analysis for %s %s", symbol, interval)
        
        # Get market data
        klines = await self._get_klines(symbol, interval, limit)
        opens, highs, lows, closes, volumes = self._parse_klines(klines)
        
        if len(closes) < 200:
            logger.warning("Insufficient data points for %s. Need at least 200, got %d", symbol, len(closes))
        
        # Calculate all indicators
        ema20_vals = ema(closes, 20)
        ema50_vals = ema(closes, 50)
        ema200_vals = ema(closes, 200)
        rsi_vals = rsi(closes, 14)
        macd_line, macd_signal, macd_hist = macd(closes, 12, 26, 9)
        st_vals = supertrend(highs, lows, closes, 10, 3.0)
        vwmacd_line, vwmacd_signal, vwmacd_hist = vwmacd(highs, lows, closes, volumes, 12, 26, 9)
        
        # Get latest values
        last_idx = len(closes) - 1
        
        result = TremoResult(
            symbol=symbol.upper(),
            interval=interval,
            close=closes[last_idx],
            ema20=ema20_vals[last_idx] if last_idx < len(ema20_vals) else None,
            ema50=ema50_vals[last_idx] if last_idx < len(ema50_vals) else None,
            ema200=ema200_vals[last_idx] if last_idx < len(ema200_vals) else None,
            rsi14=rsi_vals[last_idx] if last_idx < len(rsi_vals) else None,
            macd_line=macd_line[last_idx] if last_idx < len(macd_line) else None,
            macd_signal=macd_signal[last_idx] if last_idx < len(macd_signal) else None,
            macd_hist=macd_hist[last_idx] if last_idx < len(macd_hist) else None,
            supertrend=st_vals[last_idx] if last_idx < len(st_vals) else None,
            vwmacd_line=vwmacd_line[last_idx] if last_idx < len(vwmacd_line) else None,
            vwmacd_signal=vwmacd_signal[last_idx] if last_idx < len(vwmacd_signal) else None,
            vwmacd_hist=vwmacd_hist[last_idx] if last_idx < len(vwmacd_hist) else None,
            signal_score=0.0,
            signal_strength=SignalStrength.NEUTRAL
        )
        
        # Calculate signal score
        result.signal_score = self._calculate_signal_score(result)
        result.signal_strength = self._get_signal_strength(result.signal_score)
        
        logger.info("Tremo analysis completed for %s: score=%.2f", symbol, result.signal_score)
        return result

# -------------------------
# Aiogram integration
# -------------------------

try:
    from aiogram import Router, F
    from aiogram.types import Message
    from aiogram.filters import Command
    
    router = Router()
    
    @router.message(Command("tremo"))
    async def handle_tremo_command(message: Message):
        """Handle /tremo command for Tremo analysis."""
        try:
            parts = message.text.split()
            if len(parts) < 2:
                await message.reply("Kullanım: /tremo SYMBOL [INTERVAL]\nÖrnek: /tremo BTCUSDT 1h")
                return
            
            symbol = parts[1].upper()
            interval = parts[2] if len(parts) > 2 else "1h"
            
            # Get analyzer instance (assuming binance_api is available in context)
            from your_main_bot_file import binance_api  # Adjust import as needed
            
            analyzer = TremoAnalyzer.get_instance(binance_api)
            await message.reply(f"⏳ {symbol} {interval} için Tremo analizi yapılıyor...")
            
            result = await analyzer.analyze(symbol, interval)
            
            # Create formatted response
            response = (
                f"📊 *TREMO ANALİZ: {result.symbol} {result.interval}*\n\n"
                f"💰 Fiyat: `{result.close:.8f}`\n"
                f"📈 EMA Ribbon: 20=`{result.ema20:.8f}`, 50=`{result.ema50:.8f}`, 200=`{result.ema200:.8f}`\n"
                f"🔍 RSI14: `{result.rsi14:.2f}`\n"
                f"📉 MACD: Line=`{result.macd_line:.8f}`, Signal=`{result.macd_signal:.8f}`\n"
                f"🎯 SuperTrend: `{result.supertrend:.8f}`\n"
                f"💧 VW-MACD: Line=`{result.vwmacd_line:.8f}`, Signal=`{result.vwmacd_signal:.8f}`\n\n"
                f"⚡ *Sinyal Skoru: {result.signal_score:.2f}* \n"
                f"🎯 *Durum: {result.signal_strength.name}*"
            )
            
            await message.reply(response, parse_mode="Markdown")
            
        except Exception as e:
            logger.error("Tremo command error: %s", e)
            await message.reply(f"❌ Hata: {str(e)}")
    
except ImportError:
    # aiogram not available, skip router creation
    router = None
    logger.warning("aiogram not available, skipping router creation")

# -------------------------
# Quick test function
# -------------------------

async def test_tremo_analyzer():
    """Test function for TremoAnalyzer."""
    # Mock BinanceAPI for testing
    class MockBinanceAPI:
        async def get_klines(self, symbol, interval, limit):
            # Return mock data
            return [
                [0, 50000, 51000, 49000, 50500, 1000],
                [0, 50500, 51500, 49500, 51000, 1200],
                # Add more mock data as needed
            ] * 200
    
    mock_api = MockBinanceAPI()
    analyzer = TremoAnalyzer(mock_api)
    
    try:
        result = await analyzer.analyze("BTCUSDT", "1h")
        print(result)
    except Exception as e:
        print(f"Test error: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_tremo_analyzer())
