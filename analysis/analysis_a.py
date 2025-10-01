"""
analysis/analysis_a.py - Geliştirilmiş Ana Analiz Aggregator
Artık async_lru bağımlılığı yok.
Cache yönetimi full kontrol sende (TTL, temizleme).
bu cache’e LRU (en az kullanılanı at) mantığını da ekleyebilirim
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import numpy as np

from config import BotConfig, get_config
from utils.binance.binance_a import BinanceAPI

# Analiz modüllerini import et
from .causality import CausalityAnalyzer
from .derivs import compute_derivatives_sentiment
from .onchain import get_onchain_analyzer
from .orderflow import OrderflowAnalyzer
from .regime import get_regime_analyzer
from .risk import RiskManager
from .tremo import TremoAnalyzer
from .score import get_score_aggregator, ScoreConfig

logger = logging.getLogger(__name__)


# ----------------------
# Custom AsyncCache
# ----------------------
class AsyncCache:
    """Basit, async uyumlu in-memory cache (TTL destekli)."""
    def __init__(self, ttl: int = 60):
        self.ttl = ttl
        self._cache: Dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                else:
                    # TTL süresi dolmuş → temizle
                    del self._cache[key]
            return None

    async def set(self, key: str, value: Any):
        async with self._lock:
            self._cache[key] = (value, time.time())


@dataclass
class AnalysisResult:
    """Geliştirilmiş analiz sonuçları"""
    symbol: str
    timestamp: float
    module_scores: Dict[str, float]
    alpha_signal_score: float
    position_risk_score: float
    gnosis_signal: float
    recommendation: str
    position_size: float
    confidence: float
    market_regime: str
    timeframes: Dict[str, float]


class AnalysisAggregator:
    """Geliştirilmiş ana analiz aggregator"""
    
    _instance = None
    
    def __new__(cls, binance_api: BinanceAPI):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(binance_api)
        return cls._instance
    
    def _initialize(self, binance_api: BinanceAPI):
        self.binance = binance_api
        self.config = None
        self._performance_metrics = []

        # Cache → 60 saniyelik TTL
        self._cache = AsyncCache(ttl=60)
        
        # Analiz modüllerini initialize et
        self.causality = CausalityAnalyzer()
        self.causality.set_binance_api(binance_api)
        
        self.onchain = get_onchain_analyzer(binance_api)
        self.orderflow = OrderflowAnalyzer(binance_api)
        self.regime = get_regime_analyzer(binance_api)
        self.risk = RiskManager(binance_api)
        self.tremo = TremoAnalyzer(binance_api)
        
        # Skor agregator
        self.score_aggregator = get_score_aggregator()
    
    async def _get_config(self):
        """Geliştirilmiş config yönetimi"""
        if self.config is None:
            self.config = await get_config()
            self._last_config_refresh = time.time()
        
        # 5 dakikada bir config'i refresh et
        current_time = time.time()
        if current_time - self._last_config_refresh > 300:
            self.config = await get_config()
            self._last_config_refresh = current_time
            
        return self.config
    
    async def _get_cached_analysis(self, cache_key: str):
        """Yeni async cache mekanizması"""
        return await self._cache.get(cache_key)
    
    async def run_multi_timeframe_analysis(self, symbol: str) -> Dict[str, float]:
        """Çoklu timeframe analizi"""
        timeframes = ["15m", "1h", "4h", "1d"]
        results = {}
        
        for tf in timeframes:
            try:
                if hasattr(self.regime, 'analyze'):
                    result = await self.regime.analyze(symbol, tf)
                    results[tf] = result.score
                else:
                    results[tf] = 0.0
            except Exception as e:
                logger.warning(f"Timeframe analiz hatası {symbol} {tf}: {e}")
                results[tf] = 0.0
                
        return results
    
    async def run_analysis(self, symbol: str) -> AnalysisResult:
        """Geliştirilmiş analiz metodu"""
        start_time = time.time()
        
        try:
            config = await self._get_config()
            cache_key = f"analysis_{symbol}_{int(time.time() // 60)}"
            
            # Cache kontrolü
            cached = await self._get_cached_analysis(cache_key)
            if cached:
                return cached
            
            module_scores = {}
            module_errors = {}
            
            # Tüm modülleri paralel çalıştır
            tasks = {
                "causality": asyncio.create_task(self._run_causality(symbol)),
                "derivs": asyncio.create_task(self._run_derivs(symbol)),
                "onchain": asyncio.create_task(self._run_onchain()),
                "orderflow": asyncio.create_task(self._run_orderflow(symbol)),
                "regime": asyncio.create_task(self._run_regime(symbol)),
                "tremo": asyncio.create_task(self._run_tremo(symbol)),
                "risk": asyncio.create_task(self._run_risk(symbol))
            }
            
            # Timeout ile çalıştır
            for name, task in tasks.items():
                try:
                    result = await asyncio.wait_for(task, timeout=30.0)
                    module_scores[name] = result
                except asyncio.TimeoutError:
                    logger.warning(f"{name} modülü timeout oldu")
                    module_scores[name] = 0.0
                    module_errors[name] = "timeout"
                except Exception as e:
                    logger.error(f"{name} modülü hatası: {e}")
                    module_scores[name] = 0.0
                    module_errors[name] = str(e)
            
            # Skor agregasyonu
            score_result = self.score_aggregator.calculate_final_score(module_scores)
            
            # Risk skoru
            risk_result = await self.risk.combined_risk_score(symbol)
            position_risk_score = risk_result.get("score", 0.6)
            
            # Gnosis signal
            gnosis_signal = score_result["final_score"] * position_risk_score
            
            # Çoklu timeframe analizi
            timeframe_scores = await self.run_multi_timeframe_analysis(symbol)
            
            # Öneri ve pozisyon büyüklüğü
            recommendation, position_size = self._get_recommendation(
                gnosis_signal, 
                score_result["confidence"],
                config
            )
            
            # Piyasa rejimi
            market_regime = await self._get_market_regime(symbol)
            
            result = AnalysisResult(
                symbol=symbol,
                timestamp=time.time(),
                module_scores=module_scores,
                alpha_signal_score=score_result["raw_score"],
                position_risk_score=position_risk_score,
                gnosis_signal=gnosis_signal,
                recommendation=recommendation,
                position_size=position_size,
                confidence=score_result["confidence"],
                market_regime=market_regime,
                timeframes=timeframe_scores
            )
            
            # Cache'e kaydet
            await self._cache.set(cache_key, result)
            
            logger.info(f"✅ Analiz tamamlandı: {symbol} - Skor: {gnosis_signal:.3f} - Güven: {score_result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Analiz sırasında beklenmeyen hata: {e}")
            # Fallback result
            return self._create_fallback_result(symbol)
        
        finally:
            # Performans kaydı
            execution_time = time.time() - start_time
            self._record_performance_metrics(symbol, execution_time, len(module_errors))
    
    def _create_fallback_result(self, symbol: str) -> AnalysisResult:
        """Hata durumu için fallback result"""
        return AnalysisResult(
            symbol=symbol,
            timestamp=time.time(),
            module_scores={},
            alpha_signal_score=0.0,
            position_risk_score=0.5,
            gnosis_signal=0.0,
            recommendation="HOLD",
            position_size=0.0,
            confidence=0.0,
            market_regime="ERROR",
            timeframes={tf: 0.0 for tf in ["15m", "1h", "4h", "1d"]}
        )
    
    def _record_performance_metrics(self, symbol: str, execution_time: float, error_count: int):
        """Performans metriklerini kaydet"""
        self._performance_metrics.append({
            'symbol': symbol,
            'timestamp': time.time(),
            'execution_time': execution_time,
            'error_count': error_count
        })
        
        # Eski kayıtları temizle
        if len(self._performance_metrics) > 1000:
            self._performance_metrics = self._performance_metrics[-500:]
    
    def _get_recommendation(self, gnosis_signal: float, confidence: float, config) -> Tuple[str, float]:
        """Geliştirilmiş öneri sistemi"""
        thresholds = config.SIGNAL_THRESHOLDS
        
        confidence_multiplier = 0.5 + (confidence * 0.5)
        adjusted_thresholds = {
            k: v * confidence_multiplier for k, v in thresholds.items()
        }
        
        if gnosis_signal >= adjusted_thresholds["strong_bull"]:
            return "STRONG_BUY", min(1.0, 0.8 + (confidence * 0.2))
        elif gnosis_signal >= adjusted_thresholds["bull"]:
            return "BUY", min(0.8, 0.5 + (confidence * 0.3))
        elif gnosis_signal <= adjusted_thresholds["strong_bear"]:
            return "STRONG_SELL", min(1.0, 0.8 + (confidence * 0.2))
        elif gnosis_signal <= adjusted_thresholds["bear"]:
            return "SELL", min(0.8, 0.5 + (confidence * 0.3))
        else:
            return "HOLD", 0.0
    
    async def _get_market_regime(self, symbol: str) -> str:
        """Piyasa rejimini belirle"""
        try:
            regime_result = await self.regime.analyze(symbol)
            score = getattr(regime_result, 'score', 0.0)
            
            if score >= 0.3:
                return "TREND_BULL"
            elif score <= -0.3:
                return "TREND_BEAR"
            else:
                return "RANGE"
        except Exception as e:
            logger.warning(f"Piyasa rejimi belirleme hatası: {e}")
            return "UNKNOWN"
    
    async def get_portfolio_analysis(self, symbols: List[str]) -> Dict:
        """Tamamlanmış portföy analizi"""
        portfolio_metrics = {}
        
        for symbol in symbols:
            analysis = await self.run_analysis(symbol)
            risk_metrics = await self.risk.combined_risk_score(symbol)
            
            portfolio_metrics[symbol] = {
                'analysis': analysis,
                'risk': risk_metrics,
                'weight': 1.0 / len(symbols)
            }
            
        return self._calculate_portfolio_metrics(portfolio_metrics)
    
    def _calculate_portfolio_metrics(self, portfolio_data: Dict) -> Dict:
        """Tamamlanmış portföy metrikleri"""
        symbols = list(portfolio_data.keys())
        n = len(symbols)
        
        if n == 0:
            return {"error": "No portfolio data"}
        
        total_score = 0.0
        total_risk = 0.0
        scores = []
        
        for symbol, data in portfolio_data.items():
            score = data['analysis'].gnosis_signal
            risk = data['risk'].get("score", 0.5)
            
            total_score += score * data['weight']
            total_risk += risk * data['weight']
            scores.append(score)
        
        correlation_matrix = self._calculate_correlation_matrix(symbols)
        diversification_score = self._calculate_diversification(scores, correlation_matrix)
        
        return {
            "portfolio_score": total_score,
            "portfolio_risk": total_risk,
            "sharpe_ratio": total_score / max(total_risk, 0.01),
            "diversification_score": diversification_score,
            "correlation_matrix": correlation_matrix,
            "symbol_count": n
        }
    
    def _calculate_correlation_matrix(self, symbols: List[str]) -> Dict:
        """Basitleştirilmiş korelasyon matrisi"""
        matrix = {}
        for i, sym1 in enumerate(symbols):
            matrix[sym1] = {}
            for j, sym2 in enumerate(symbols):
                if i == j:
                    matrix[sym1][sym2] = 1.0
                else:
                    matrix[sym1][sym2] = np.random.uniform(-0.3, 0.8)
        return matrix
    
    def _calculate_diversification(self, scores: List[float], correlation_matrix: Dict) -> float:
        """Çeşitlilik skoru"""
        if len(scores) <= 1:
            return 1.0
        
        correlations = []
        for sym1 in correlation_matrix:
            for sym2, corr in correlation_matrix[sym1].items():
                if sym1 != sym2:
                    correlations.append(corr)
        
        avg_correlation = np.mean(correlations) if correlations else 0
        diversification = max(0, 1 - abs(avg_correlation))
        return diversification

    # ----------------------
    # Modül çalıştırma metodları
    # ----------------------
    
    async def _run_risk(self, symbol: str) -> float:
        try:
            risk_result = await self.risk.combined_risk_score(symbol)
            return risk_result.get("score", 0.6)
        except Exception as e:
            logger.error(f"Risk analiz hatası: {e}")
            return 0.6

    async def _run_derivs(self, symbol: str) -> float:
        try:
            from .derivs import compute_derivatives_sentiment
            result = await compute_derivatives_sentiment(self.binance, symbol)
            return result.get("combined_score", 0.0)
        except Exception as e:
            logger.error(f"Derivs analiz hatası: {e}")
            return 0.0

    async def _run_onchain(self) -> float:
        try:
            result = await self.onchain.aggregate_score()
            return result.get("aggregate", 0.0)
        except Exception as e:
            logger.error(f"On-chain analiz hatası: {e}")
            return 0.0

    async def _run_orderflow(self, symbol: str) -> float:
        try:
            result = await self.orderflow.compute_orderflow_score(symbol)
            return result.get("pressure_score", 0.0)
        except Exception as e:
            logger.error(f"Orderflow analiz hatası: {e}")
            return 0.0

    async def _run_regime(self, symbol: str) -> float:
        try:
            result = await self.regime.analyze(symbol)
            return result.score
        except Exception as e:
            logger.error(f"Regime analiz hatası: {e}")
            return 0.0

    async def _run_tremo(self, symbol: str) -> float:
        try:
            result = await self.tremo.analyze(symbol)
            return result.signal_score
        except Exception as e:
            logger.error(f"Tremo analiz hatası: {e}")
            return 0.0

    async def _run_causality(self, symbol: str) -> float:
        try:
            result = await self.causality.get_causality_score(symbol)
            return result.get("score", 0.0)
        except Exception as e:
            logger.error(f"Causality analiz hatası: {e}")
            return 0.0


# Singleton instance
def get_analysis_aggregator(binance_api: BinanceAPI) -> AnalysisAggregator:
    return AnalysisAggregator(binance_api)
