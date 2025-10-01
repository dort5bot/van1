# analysis/regime.py
"""
Piyasa Modu (Trend vs Range) Analizi - Geliştirilmiş Versiyon

Metodlar:
- ADX (14) - Average Directional Index
- BBW (20) - Bollinger Band Width → normalize 0-1
- Hurst Exponent (100) - Trend kalıcılık analizi
- ATR (14) - Average True Range → volatilite ölçümü
- RSI (14) - Relative Strength Index → momentum
- Volume Analysis - Hacim trend analizi

Sonuç: -1 (Strong Range) ↔ +1 (Strong Trend) arasında skor
"""

import logging
import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple
import asyncio
from dataclasses import dataclass

from utils.binance.binance_a import BinanceAPI

logger = logging.getLogger(__name__)

@dataclass
class RegimeResult:
    """Regime analiz sonuçlarını tutan data class"""
    symbol: str
    interval: str
    close: float
    adx: float
    bbw: float
    hurst: float
    atr: float
    rsi: float
    volume_trend: float
    score: float
    regime: str
    confidence: float

class RegimeAnalyzer:
    """
    Piyasa modu (trend / range) analizi yapan sınıf.
    BinanceAPI instance'ını constructor'dan alır.
    """

    def __init__(self, binance_api: BinanceAPI):
        """
        RegimeAnalyzer constructor.
        
        Args:
            binance_api: BinanceAPI instance
        """
        self.binance = binance_api
        self._cache = {}
        logger.info(f"RegimeAnalyzer initialized for BinanceAPI")

    async def get_klines_data(self, symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
        """
        Binance'dan kline verilerini al ve DataFrame'e dönüştür.
        
        Args:
            symbol: İşlem çifti (örn: BTCUSDT)
            interval: Kline periyodu
            limit: Kline sayısı
            
        Returns:
            Pandas DataFrame with OHLCV data
        """
        cache_key = f"{symbol}_{interval}_{limit}"
        
        # Cache kontrolü
        if cache_key in self._cache:
            cached_time, df = self._cache[cache_key]
            if asyncio.get_event_loop().time() - cached_time < 300:  # 5 dakika cache
                logger.debug(f"Using cached klines for {cache_key}")
                return df.copy()
        
        try:
            logger.info(f"Fetching klines for {symbol} {interval} (limit: {limit})")
            klines = await self.binance.get_klines(symbol, interval, limit)
            
            # DataFrame oluştur
            df = pd.DataFrame(klines, columns=[
                "time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "taker_base", "taker_quote", "ignore"
            ])
            
            # Numeric columns'ı convert et
            numeric_columns = ["open", "high", "low", "close", "volume"]
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # NaN values'ı temizle
            df = df.dropna(subset=numeric_columns)
            
            # Cache'e kaydet
            self._cache[cache_key] = (asyncio.get_event_loop().time(), df.copy())
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching klines for {symbol}: {e}")
            raise

    # -------------------------
    # Teknik İndikatörler - Geliştirilmiş
    # -------------------------
    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        ADX (Average Directional Index) hesapla.
        Trend gücünü ölçer. >25 trend, <20 range.
        """
        try:
            # True Range hesapla
            df['H-L'] = df['high'] - df['low']
            df['H-PC'] = abs(df['high'] - df['close'].shift(1))
            df['L-PC'] = abs(df['low'] - df['close'].shift(1))
            df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)

            # Directional Movement
            df['+DM'] = np.where(
                (df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']),
                np.maximum(df['high'] - df['high'].shift(1), 0), 
                0.0
            )
            df['-DM'] = np.where(
                (df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)),
                np.maximum(df['low'].shift(1) - df['low'], 0),
                0.0
            )

            # Smooth the values
            df['TR_smooth'] = df['TR'].rolling(period).sum()
            df['+DM_smooth'] = df['+DM'].rolling(period).sum()
            df['-DM_smooth'] = df['-DM'].rolling(period).sum()

            # Directional Indicators
            df['+DI'] = 100 * (df['+DM_smooth'] / df['TR_smooth'])
            df['-DI'] = 100 * (df['-DM_smooth'] / df['TR_smooth'])

            # Directional Index
            df['DX'] = (abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])) * 100

            # ADX
            adx = df['DX'].rolling(period).mean().iloc[-1]
            
            # Normalize: 0-100 → 0-1, >25 = trend
            normalized_adx = max(0, min(1, (adx - 20) / 30)) if adx > 20 else 0
            return float(normalized_adx)
            
        except Exception as e:
            logger.error(f"ADX calculation error: {e}")
            return 0.0

    def calculate_bbw(self, df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> float:
        """
        Bollinger Band Width hesapla.
        Volatilite ölçer. Yüksek BBW = yüksek volatilite = trend.
        """
        try:
            df['MA'] = df['close'].rolling(period).mean()
            df['STD'] = df['close'].rolling(period).std()
            df['Upper'] = df['MA'] + (std_dev * df['STD'])
            df['Lower'] = df['MA'] - (std_dev * df['STD'])
            
            bbw = (df['Upper'].iloc[-1] - df['Lower'].iloc[-1]) / df['MA'].iloc[-1]
            
            # Normalize: Tipik aralık 0.02-0.20 → 0-1
            normalized_bbw = max(0, min(1, (bbw - 0.02) / 0.18))
            return float(normalized_bbw)
            
        except Exception as e:
            logger.error(f"BBW calculation error: {e}")
            return 0.0

    def calculate_hurst_exponent(self, series: pd.Series, lags: int = 100) -> float:
        """
        Hurst exponent hesapla.
        H > 0.5: Trend, H < 0.5: Mean-reversion, H = 0.5: Random walk.
        """
        try:
            if len(series) < lags:
                lags = len(series) - 2
                if lags < 2:
                    return 0.5
            
            lags_range = range(2, lags)
            tau = []
            
            for lag in lags_range:
                if lag >= len(series):
                    continue
                # Log returns
                returns = np.log(series[lag:]).values - np.log(series[:-lag]).values
                if len(returns) > 0:
                    tau.append(np.std(returns))
            
            if len(tau) < 2:
                return 0.5
            
            # Linear fit
            poly = np.polyfit(np.log(lags_range[:len(tau)]), np.log(tau), 1)
            hurst = poly[0]
            
            # Normalize: 0.3-0.7 → -1 to +1
            normalized_hurst = max(-1, min(1, (hurst - 0.5) * 5))
            return float(normalized_hurst)
            
        except Exception as e:
            logger.error(f"Hurst exponent calculation error: {e}")
            return 0.0

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        ATR (Average True Range) hesapla.
        Volatilite ölçer. Yüksek ATR = yüksek volatilite.
        """
        try:
            df['H-L'] = df['high'] - df['low']
            df['H-C'] = abs(df['high'] - df['close'].shift(1))
            df['L-C'] = abs(df['low'] - df['close'].shift(1))
            
            tr = df[['H-L', 'H-C', 'L-C']].max(axis=1)
            atr_val = tr.rolling(period).mean().iloc[-1]
            
            # Normalize: Fiyatın yüzdesi olarak (0.005-0.05 → 0-1)
            norm_atr = atr_val / df['close'].iloc[-1]
            normalized_atr = max(0, min(1, (norm_atr - 0.005) / 0.045))
            return float(normalized_atr)
            
        except Exception as e:
            logger.error(f"ATR calculation error: {e}")
            return 0.0

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        RSI hesapla ve trend yönü için kullan.
        """
        try:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            rsi_value = rsi.iloc[-1]
            
            # RSI trend strength: 30-70 aralığında trend, extremes'da reversal
            if 30 <= rsi_value <= 70:
                # RSI trend yönü
                rsi_trend = np.polyfit(range(period), rsi.iloc[-period:], 1)[0]
                normalized_trend = max(-1, min(1, rsi_trend / 2))
                return float(normalized_trend)
            else:
                # Extreme levels - potential reversal
                return 0.0
                
        except Exception as e:
            logger.error(f"RSI trend calculation error: {e}")
            return 0.0

    def calculate_volume_trend(self, df: pd.DataFrame, period: int = 20) -> float:
        """
        Hacim trend analizi.
        Artan hacim + trend → trend confirmation.
        """
        try:
            # Volume SMA
            volume_sma = df['volume'].rolling(period).mean()
            current_volume = df['volume'].iloc[-1]
            volume_ratio = current_volume / volume_sma.iloc[-1]
            
            # Volume trend (slope)
            volume_trend = np.polyfit(range(period), df['volume'].iloc[-period:], 1)[0]
            
            # Combine ratio and trend
            volume_score = (volume_ratio - 1) * 0.5 + volume_trend * 10
            
            # Normalize
            normalized_volume = max(-1, min(1, volume_score))
            return float(normalized_volume)
            
        except Exception as e:
            logger.error(f"Volume trend calculation error: {e}")
            return 0.0

    def determine_regime(self, score: float) -> Tuple[str, float]:
        """
        Skora göre piyasa rejimini belirle.
        
        Returns:
            (regime_name, confidence)
        """
        if score >= 0.7:
            return "STRONG_TREND", 0.9
        elif score >= 0.3:
            return "TREND", 0.7
        elif score >= -0.3:
            return "RANGE", 0.6
        elif score >= -0.7:
            return "STRONG_RANGE", 0.8
        else:
            return "EXTREME_RANGE", 0.9

    # -------------------------
    # Ana Analiz Metodu - Geliştirilmiş
    # -------------------------
    async def analyze(self, symbol: str, interval: str = "1h", limit: int = 500) -> RegimeResult:
        """
        Kapsamlı piyasa rejimi analizi yap.
        
        Args:
            symbol: İşlem çifti (örn: "BTCUSDT")
            interval: Kline periyodu
            limit: Kline sayısı

        Returns:
            RegimeResult: Tüm metrikler ve sonuçlar
        """
        try:
            logger.info(f"Starting regime analysis for {symbol} {interval}")
            
            # Verileri al
            df = await self.get_klines_data(symbol, interval, limit)
            
            if len(df) < 100:
                logger.warning(f"Insufficient data for {symbol}: {len(df)} points")
                # Fallback result
                return RegimeResult(
                    symbol=symbol,
                    interval=interval,
                    close=df['close'].iloc[-1] if len(df) > 0 else 0,
                    adx=0.0,
                    bbw=0.0,
                    hurst=0.0,
                    atr=0.0,
                    rsi=0.0,
                    volume_trend=0.0,
                    score=0.0,
                    regime="UNKNOWN",
                    confidence=0.0
                )

            # Tüm indikatörleri hesapla
            adx_val = self.calculate_adx(df)
            bbw_val = self.calculate_bbw(df)
            hurst_val = self.calculate_hurst_exponent(df['close'])
            atr_val = self.calculate_atr(df)
            rsi_trend = self.calculate_rsi(df)
            volume_trend = self.calculate_volume_trend(df)

            # Ağırlıklı skor hesapla
            weights = {
                "adx": 0.25,      # Trend strength
                "bbw": 0.20,      # Volatility
                "hurst": 0.20,    # Trend persistence
                "atr": 0.15,      # Volatility magnitude
                "rsi": 0.10,      # Momentum direction
                "volume": 0.10    # Volume confirmation
            }

            score = (
                weights["adx"] * adx_val +
                weights["bbw"] * bbw_val +
                weights["hurst"] * hurst_val +
                weights["atr"] * atr_val +
                weights["rsi"] * rsi_trend +
                weights["volume"] * volume_trend
            )

            # Rejim ve confidence belirle
            regime, confidence = self.determine_regime(score)

            result = RegimeResult(
                symbol=symbol.upper(),
                interval=interval,
                close=float(df['close'].iloc[-1]),
                adx=adx_val,
                bbw=bbw_val,
                hurst=hurst_val,
                atr=atr_val,
                rsi=rsi_trend,
                volume_trend=volume_trend,
                score=float(score),
                regime=regime,
                confidence=float(confidence)
            )

            logger.info(f"Regime analysis completed for {symbol}: {regime} (score: {score:.3f})")
            return result

        except Exception as e:
            logger.error(f"Regime analysis failed for {symbol}: {e}")
            # Fallback result
            return RegimeResult(
                symbol=symbol.upper(),
                interval=interval,
                close=0.0,
                adx=0.0,
                bbw=0.0,
                hurst=0.0,
                atr=0.0,
                rsi=0.0,
                volume_trend=0.0,
                score=0.0,
                regime="ERROR",
                confidence=0.0
            )

    async def analyze_multiple_timeframes(self, symbol: str) -> Dict[str, RegimeResult]:
        """
        Multiple timeframe analizi yap.
        
        Returns:
            Dict with results for different timeframes
        """
        timeframes = ["15m", "1h", "4h", "1d"]
        results = {}
        
        for tf in timeframes:
            try:
                result = await self.analyze(symbol, tf, 200)
                results[tf] = result
            except Exception as e:
                logger.error(f"Multi-timeframe analysis failed for {symbol} {tf}: {e}")
                continue
        
        return results

    async def close(self):
        """Temizlik"""
        self._cache.clear()
        logger.info("RegimeAnalyzer cache cleared")

# -------------------------
# Aiogram Router Entegrasyonu
# -------------------------
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command(commands=["regime", "marketregime"]))
async def regime_handler(message: Message):
    """Piyasa rejimi analiz handler"""
    try:
        text = message.text or ""
        parts = text.strip().split()
        
        if len(parts) < 2:
            await message.reply("Kullanım: /regime SYMBOL [INTERVAL]\nÖrnek: /regime BTCUSDT 1h")
            return
        
        symbol = parts[1].upper()
        interval = parts[2] if len(parts) > 2 else "1h"
        
        # BinanceAPI instance'ını al
        binance_api = getattr(message.bot, 'binance_api', None)
        if not binance_api:
            await message.reply("❌ Binance API bağlantısı kurulamadı")
            return
        
        await message.reply(f"📊 {symbol} için piyasa rejimi analizi yapılıyor...")
        
        analyzer = RegimeAnalyzer(binance_api)
        result = await analyzer.analyze(symbol, interval)
        
        # Formatlı response
        response = (
            f"🎯 <b>PİYASA REJİMİ ANALİZİ - {result.symbol} {result.interval}</b>\n\n"
            f"📈 <b>Rejim:</b> <code>{result.regime}</code>\n"
            f"🔢 <b>Skor:</b> <code>{result.score:.3f}</code>\n"
            f"💪 <b>Confidence:</b> <code>{result.confidence:.2f}</code>\n"
            f"💰 <b>Fiyat:</b> <code>{result.close:.2f}</code>\n\n"
            f"<b>📊 Metrikler:</b>\n"
            f"• ADX: <code>{result.adx:.3f}</code>\n"
            f"• BB Width: <code>{result.bbw:.3f}</code>\n"
            f"• Hurst: <code>{result.hurst:.3f}</code>\n"
            f"• ATR: <code>{result.atr:.3f}</code>\n"
            f"• RSI Trend: <code>{result.rsi:.3f}</code>\n"
            f"• Volume Trend: <code>{result.volume_trend:.3f}</code>"
        )
        
        await message.reply(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Regime handler error: {e}")
        await message.reply(f"❌ Analiz sırasında hata: {e}")

# Singleton pattern için helper
def get_regime_analyzer(binance_api: BinanceAPI) -> RegimeAnalyzer:
    """
    RegimeAnalyzer instance'ını döndürür.
    
    Args:
        binance_api: BinanceAPI instance
        
    Returns:
        RegimeAnalyzer instance
    """
    return RegimeAnalyzer(binance_api)

# Test
async def test_regime_analyzer():
    """Test function"""
    from utils.binance.binance_request import BinanceHTTPClient
    from utils.binance.binance_circuit_breaker import CircuitBreaker
    
    # Mock setup
    http_client = BinanceHTTPClient(api_key="test", secret_key="test")
    cb = CircuitBreaker()
    binance_api = BinanceAPI(http_client, cb)
    
    analyzer = get_regime_analyzer(binance_api)
    result = await analyzer.analyze("BTCUSDT", "1h")
    print("Regime analysis result:", result)
    
    await analyzer.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_regime_analyzer())