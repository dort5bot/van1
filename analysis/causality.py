# analytics/causality.py

"""
Causality Analyzer - Lider-Takipçi Dinamiği Modülü (Geliştirilmiş)

Bu modül, BTC Dominance, BTC/Altcoin korelasyonu ve Granger Causality (BTC->ALT) 
analizini yapar. Sonuçlar -1 (Altcoin Bear) ile +1 (Altcoin Bull) arasında normalize edilir.

✅ Geliştirmeler:
- Her altcoin için BTC korelasyonu (ETH yerine symbol parametresi)
- Sabit veri, eksik veri, NaN kontrolleri
- Logger.exception ile tam stack trace
- Basit cache ile performans optimizasyonu (10 saniye TTL)
- Geliştirilmiş dominance hesaplaması (BTC + ETH + top altcoin)
- Rate limit/performans iyileştirmeleri
- Config yönetimi entegrasyonu

Kullanım:
    from analytics.causality import CausalityAnalyzer
    
    analyzer = CausalityAnalyzer()
    await analyzer.set_binance_api(binance_api_instance)
    score = await analyzer.get_causality_score("ETHUSDT")

🔧 Özellikler:
- Singleton pattern
- Async/await uyumlu
- Aiogram 3.x Router pattern ile entegre
- Type hints + comprehensive docstrings
- PEP8 compliant
- Structured logging
- Error handling with proper cleanup
"""

import logging
from typing import Optional, Dict, List, Tuple
import numpy as np
from statsmodels.tsa.stattools import grangercausalitytests
from datetime import datetime, timedelta
import asyncio

from utils.binance.binance_a import BinanceAPI
from config import get_config

logger = logging.getLogger(__name__)


class CausalityAnalyzer:
    """BTC liderliği ve altcoin takibi için Granger causality tabanlı analiz."""

    _instance: Optional["CausalityAnalyzer"] = None
    _initialization_lock = asyncio.Lock()

    def __new__(cls) -> "CausalityAnalyzer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            logger.info("✅ CausalityAnalyzer singleton instance created")
        return cls._instance

    async def initialize(self) -> None:
        """Async initialization with thread-safe locking."""
        async with self._initialization_lock:
            if not self._initialized:
                await self._initialize()
                self._initialized = True

    async def _initialize(self) -> None:
        """Initialize instance components and configuration."""
        self.binance: Optional[BinanceAPI] = None
        self.config = await get_config()
        
        # Price cache: {symbol: (timestamp, value)}
        self._price_cache: Dict[str, Tuple[datetime, float]] = {}
        
        # Analysis configuration
        self._default_window = 100
        self._maxlag = 2
        self._cache_ttl = timedelta(seconds=10)
        self._top_altcoins = ["BNBUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT", "DOTUSDT"]
        
        logger.info("✅ CausalityAnalyzer initialized successfully")

    def set_binance_api(self, binance: BinanceAPI) -> None:
        """
        Set Binance API instance.
        
        Args:
            binance: BinanceAPI instance
        """
        self.binance = binance
        logger.info("✅ BinanceAPI instance set for CausalityAnalyzer")

    async def _get_price(self, symbol: str) -> float:
        """
        Get price with simple caching mechanism.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            
        Returns:
            Current price or 0.0 on error
        """
        if not self.binance:
            raise RuntimeError("BinanceAPI not set. Call set_binance_api() first.")
        
        now = datetime.utcnow()
        cached = self._price_cache.get(symbol)
        
        # Return cached value if not expired
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]
        
        try:
            price = await self.binance.get_price(symbol)
            if price is None:
                logger.warning(f"⚠️ Price is None for {symbol}")
                return 0.0
                
            price_float = float(price)
            self._price_cache[symbol] = (now, price_float)
            return price_float
            
        except Exception as e:
            logger.exception(f"❌ Price fetch error for {symbol}: {e}")
            return 0.0

    async def _get_btc_dominance(self) -> float:
        """
        Calculate BTC dominance proxy (BTC / (BTC + ETH + Top Alts)).
        
        Returns:
            BTC dominance ratio or 0.0 on error
        """
        try:
            btc_price = await self._get_price("BTCUSDT")
            eth_price = await self._get_price("ETHUSDT")
            
            if btc_price == 0.0:
                logger.warning("⚠️ BTC price is 0, dominance calculation skipped")
                return 0.0
            
            # Calculate sum of top altcoins
            alt_sum = 0.0
            for symbol in self._top_altcoins:
                alt_price = await self._get_price(symbol)
                alt_sum += alt_price
            
            total = btc_price + eth_price + alt_sum
            
            if total == 0:
                logger.warning("⚠️ Total market cap is 0, dominance calculation skipped")
                return 0.0
            
            dominance = btc_price / total
            return float(dominance)
            
        except Exception as e:
            logger.exception(f"❌ BTC dominance calculation error: {e}")
            return 0.0

    async def _get_correlation(self, symbol: str, window: Optional[int] = None) -> float:
        """
        Calculate BTC -> Altcoin correlation.
        
        Args:
            symbol: Altcoin symbol (e.g., "ETHUSDT")
            window: Correlation window size (optional)
            
        Returns:
            Correlation coefficient or 0.0 on error
        """
        if not self.binance:
            raise RuntimeError("BinanceAPI not set. Call set_binance_api() first.")
        
        window = window or self._default_window
        
        try:
            # Fetch klines data
            btc_klines = await self.binance.public.get_klines("BTCUSDT", interval="1h", limit=window)
            alt_klines = await self.binance.public.get_klines(symbol, interval="1h", limit=window)
            
            if not btc_klines or not alt_klines:
                logger.warning(f"⚠️ No klines data for correlation: {symbol}")
                return 0.0
            
            # Extract close prices
            btc_closes = np.array([float(k[4]) for k in btc_klines])
            alt_closes = np.array([float(k[4]) for k in alt_klines])
            
            # Data validation
            if len(btc_closes) != len(alt_closes):
                logger.warning(f"⚠️ Data length mismatch for correlation: {symbol}")
                min_len = min(len(btc_closes), len(alt_closes))
                btc_closes = btc_closes[:min_len]
                alt_closes = alt_closes[:min_len]
            
            if len(btc_closes) < 2:
                logger.warning(f"⚠️ Insufficient data for correlation: {symbol}")
                return 0.0
            
            # Check for constant data
            if np.std(btc_closes) == 0 or np.std(alt_closes) == 0:
                logger.debug(f"⚠️ Constant data detected for correlation: {symbol}")
                return 0.0
            
            # Calculate correlation
            correlation = np.corrcoef(btc_closes, alt_closes)[0, 1]
            
            if np.isnan(correlation):
                logger.warning(f"⚠️ NaN correlation result for: {symbol}")
                return 0.0
            
            return float(correlation)
            
        except Exception as e:
            logger.exception(f"❌ Correlation calculation error for {symbol}: {e}")
            return 0.0

    async def _get_granger_causality(self, symbol: str, maxlag: Optional[int] = None) -> float:
        """
        Perform Granger Causality test (BTC -> Altcoin).
        
        Args:
            symbol: Altcoin symbol (e.g., "ETHUSDT")
            maxlag: Maximum lag for the test (optional)
            
        Returns:
            Granger causality score or 0.0 on error
        """
        if not self.binance:
            raise RuntimeError("BinanceAPI not set. Call set_binance_api() first.")
        
        maxlag = maxlag or self._maxlag
        data_limit = max(200, maxlag * 10)  # Ensure sufficient data
        
        try:
            # Fetch klines data
            btc_klines = await self.binance.public.get_klines("BTCUSDT", interval="1h", limit=data_limit)
            alt_klines = await self.binance.public.get_klines(symbol, interval="1h", limit=data_limit)
            
            if not btc_klines or not alt_klines:
                logger.warning(f"⚠️ No klines data for Granger test: {symbol}")
                return 0.0
            
            # Extract close prices
            btc_closes = np.array([float(k[4]) for k in btc_klines])
            alt_closes = np.array([float(k[4]) for k in alt_klines])
            
            # Data validation
            if len(btc_closes) != len(alt_closes):
                logger.warning(f"⚠️ Data length mismatch for Granger test: {symbol}")
                min_len = min(len(btc_closes), len(alt_closes))
                btc_closes = btc_closes[:min_len]
                alt_closes = alt_closes[:min_len]
            
            # Check data requirements
            if len(alt_closes) <= maxlag or len(btc_closes) <= maxlag:
                logger.warning(f"⚠️ Insufficient data for Granger test: {symbol}")
                return 0.0
            
            # Check for constant data
            if np.std(alt_closes) == 0 or np.std(btc_closes) == 0:
                logger.debug(f"⚠️ Constant data detected for Granger test: {symbol}")
                return 0.0
            
            # Prepare data for Granger test
            data = np.column_stack([alt_closes, btc_closes])
            
            # Perform Granger causality test
            result = grangercausalitytests(data, maxlag=maxlag, verbose=False)
            
            # Extract p-values
            p_values = [result[i + 1][0]['ssr_ftest'][1] for i in range(maxlag)]
            
            # Handle NaN p-values
            valid_p_values = [p for p in p_values if not np.isnan(p)]
            
            if not valid_p_values:
                logger.warning(f"⚠️ All p-values are NaN for Granger test: {symbol}")
                return 0.0
            
            # Calculate score (1 - mean p-value)
            mean_p_value = np.mean(valid_p_values)
            score = 1 - mean_p_value
            
            return float(score)
            
        except Exception as e:
            logger.exception(f"❌ Granger causality calculation error for {symbol}: {e}")
            return 0.0

    async def get_causality_score(self, symbol: str) -> Dict[str, float]:
        """
        Get comprehensive leader-follower dynamics score.
        
        Args:
            symbol: Altcoin symbol (e.g., "ETHUSDT")
            
        Returns:
            Dictionary containing dominance, correlation, granger, and final score
            
        Raises:
            RuntimeError: If BinanceAPI not set or analyzer not initialized
        """
        if not self._initialized:
            await self.initialize()
        
        if not self.binance:
            raise RuntimeError("BinanceAPI not set. Call set_binance_api() first.")
        
        try:
            # Execute analyses in parallel
            dominance_task = self._get_btc_dominance()
            correlation_task = self._get_correlation(symbol)
            granger_task = self._get_granger_causality(symbol)
            
            dominance, correlation, granger = await asyncio.gather(
                dominance_task, correlation_task, granger_task,
                return_exceptions=True
            )
            
            # Handle exceptions from gather
            if isinstance(dominance, Exception):
                logger.error(f"❌ Dominance calculation failed: {dominance}")
                dominance = 0.0
            if isinstance(correlation, Exception):
                logger.error(f"❌ Correlation calculation failed: {correlation}")
                correlation = 0.0
            if isinstance(granger, Exception):
                logger.error(f"❌ Granger calculation failed: {granger}")
                granger = 0.0
            
            # Calculate final score with normalization
            components = [dominance, correlation, granger]
            valid_components = [c for c in components if c != 0.0]
            
            if not valid_components:
                final_score = 0.0
            else:
                average_score = np.mean(valid_components)
                final_score = np.tanh(average_score)  # Normalize to [-1, 1]
            
            result = {
                "dominance": float(dominance),
                "correlation": float(correlation),
                "granger": float(granger),
                "score": float(final_score),
            }
            
            logger.info(f"📊 Causality Score for {symbol}: {result}")
            return result
            
        except Exception as e:
            logger.exception(f"❌ Causality score calculation failed for {symbol}: {e}")
            return {
                "dominance": 0.0,
                "correlation": 0.0,
                "granger": 0.0,
                "score": 0.0,
            }

    async def batch_get_causality_scores(self, symbols: List[str]) -> Dict[str, Dict[str, float]]:
        """
        Get causality scores for multiple symbols in batch.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dictionary mapping symbols to their causality scores
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            tasks = {symbol: self.get_causality_score(symbol) for symbol in symbols}
            results = {}
            
            for symbol, task in tasks.items():
                try:
                    results[symbol] = await task
                except Exception as e:
                    logger.error(f"❌ Batch causality score failed for {symbol}: {e}")
                    results[symbol] = {
                        "dominance": 0.0,
                        "correlation": 0.0,
                        "granger": 0.0,
                        "score": 0.0,
                    }
            
            return results
            
        except Exception as e:
            logger.exception(f"❌ Batch causality scores calculation failed: {e}")
            return {symbol: {
                "dominance": 0.0,
                "correlation": 0.0,
                "granger": 0.0,
                "score": 0.0,
            } for symbol in symbols}

    async def cleanup(self) -> None:
        """Cleanup resources and clear cache."""
        self._price_cache.clear()
        logger.info("✅ CausalityAnalyzer cache cleared")

    async def get_analysis_parameters(self) -> Dict[str, any]:
        """
        Get current analysis parameters for monitoring.
        
        Returns:
            Dictionary with current configuration parameters
        """
        return {
            "default_window": self._default_window,
            "maxlag": self._maxlag,
            "cache_ttl_seconds": self._cache_ttl.total_seconds(),
            "top_altcoins": self._top_altcoins,
            "cache_size": len(self._price_cache),
            "initialized": self._initialized,
            "binance_set": self.binance is not None,
        }


# =============================================================================
# GLOBAL FACTORY FUNCTIONS AND CONTEXT MANAGER
# =============================================================================

_causality_analyzer_instance: Optional[CausalityAnalyzer] = None
_analyzer_lock = asyncio.Lock()

async def get_causality_analyzer() -> CausalityAnalyzer:
    """
    Get or create global CausalityAnalyzer instance.
    
    Returns:
        CausalityAnalyzer singleton instance
    """
    global _causality_analyzer_instance
    
    async with _analyzer_lock:
        if _causality_analyzer_instance is None:
            _causality_analyzer_instance = CausalityAnalyzer()
            await _causality_analyzer_instance.initialize()
            logger.info("✅ Global CausalityAnalyzer instance created")
        
        return _causality_analyzer_instance

async def close_causality_analyzer() -> None:
    """
    Close and cleanup global CausalityAnalyzer instance.
    """
    global _causality_analyzer_instance
    
    if _causality_analyzer_instance is not None:
        await _causality_analyzer_instance.cleanup()
        _causality_analyzer_instance = None
        logger.info("✅ Global CausalityAnalyzer instance closed")

# Context manager for temporary usage
class CausalityAnalyzerContext:
    """Context manager for CausalityAnalyzer with automatic cleanup."""
    
    def __init__(self, binance_api: Optional[BinanceAPI] = None):
        self.binance_api = binance_api
        self.analyzer: Optional[CausalityAnalyzer] = None
    
    async def __aenter__(self) -> CausalityAnalyzer:
        """Enter context and return analyzer instance."""
        self.analyzer = await get_causality_analyzer()
        
        if self.binance_api:
            self.analyzer.set_binance_api(self.binance_api)
        
        return self.analyzer
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context and cleanup."""
        if self.analyzer:
            await self.analyzer.cleanup()

# Convenience function for quick analysis
async def analyze_causality(symbol: str, binance_api: BinanceAPI) -> Dict[str, float]:
    """
    Quick convenience function for causality analysis.
    
    Args:
        symbol: Trading symbol to analyze
        binance_api: BinanceAPI instance
        
    Returns:
        Causality score dictionary
    """
    async with CausalityAnalyzerContext(binance_api) as analyzer:
        return await analyzer.get_causality_score(symbol)

# Aiogram 3.x Router integration example
def setup_causality_router(router: any, binance_api: BinanceAPI) -> any:
    """
    Setup Aiogram router with causality analysis handlers.
    
    Args:
        router: Aiogram router instance
        binance_api: BinanceAPI instance
        
    Returns:
        Configured router
    """
    from aiogram import F
    from aiogram.types import Message
    from aiogram.filters import Command
    
    @router.message(Command("causality"))
    async def causality_command(message: Message, symbol: str = "ETHUSDT"):
        """Causality analysis command handler."""
        try:
            analyzer = await get_causality_analyzer()
            analyzer.set_binance_api(binance_api)
            
            score = await analyzer.get_causality_score(symbol.upper())
            
            response = (
                f"📊 Causality Analysis for {symbol}:\n"
                f"• BTC Dominance: {score['dominance']:.4f}\n"
                f"• Correlation: {score['correlation']:.4f}\n"
                f"• Granger Causality: {score['granger']:.4f}\n"
                f"• Final Score: {score['score']:.4f}\n"
                f"Interpretation: {'Bullish' if score['score'] > 0 else 'Bearish' if score['score'] < 0 else 'Neutral'}"
            )
            
            await message.answer(response)
            
        except Exception as e:
            logger.exception(f"❌ Causality command failed: {e}")
            await message.answer("❌ Analysis failed. Please try again later.")
    
    return router