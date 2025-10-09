# analysis/corrlead.py
"""
Correlation & Lead-Lag Analysis Module
=======================================
Coin'ler arası liderlik ve korelasyon analizi.
BTC→ETH→ALT liderlik akışı tespiti + Granger Causality + Dynamic Time Warping.
Multi-symbol, multi-timeframe correlation matrix ve lead-lag tespiti.

Features:
- Multi-asset correlation analysis
- Lead-lag relationship detection  
- Granger causality testing
- Dynamic Time Warping alignment
- Professional statistical metrics

🎯 Core Features
profesyonel trader'lar ve quant analistler için piyasa yapısı, 
liderlik ilişkileri ve korelasyon dinamiklerini derinlemesine analiz eder
stratejik karar destek sağlar.
Multi-Asset Correlation: BTC→ETH→ALT liderlik akışı analizi
Statistical Rigor: Pearson, Beta, Granger Causality, DTW, VAR
Lead-Lag Detection: Cross-correlation based timing relationships
Market Structure: Cluster analysis ve correlation regimes

📊 Analytical Depth
Granger Causality: Statistical causality testing
Dynamic Time Warping: Pattern alignment across time
Canonical Correlation: Multi-variate relationship analysis
VAR Modeling: Vector AutoRegression for system dynamics
"""

import asyncio
import logging
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import hashlib

# Statistical imports
from scipy.stats import pearsonr
from scipy import signal
from sklearn.cross_decomposition import CCA
import statsmodels.api as sm
from statsmodels.tsa.stattools import grangercausalitytests

# Binance API imports
from utils.binance_api.binance_a import BinanceAggregator, MultiUserBinanceAggregator

logger = logging.getLogger(__name__)

@dataclass
class PriceSeries:
    """Price series data structure"""
    symbol: str
    timestamps: np.ndarray
    prices: np.ndarray
    returns: np.ndarray
    source: str  # 'spot' or 'futures'

@dataclass
class CorrelationResult:
    """Correlation analysis result"""
    symbol_pair: Tuple[str, str]
    pearson_corr: float
    beta: float
    rolling_covariance: float
    lead_lag: int  # Positive: first leads second, Negative: second leads first
    confidence: float

@dataclass
class LeadLagMetrics:
    """Lead-lag analysis metrics container"""
    timestamp: int
    symbol_pairs: List[Tuple[str, str]]
    
    # Classical Metrics
    correlation_matrix: Dict[Tuple[str, str], float]
    beta_matrix: Dict[Tuple[str, str], float]
    covariance_matrix: Dict[Tuple[str, str], float]
    
    # Professional Metrics
    granger_causality: Dict[Tuple[str, str], Dict[str, Any]]
    dtw_distances: Dict[Tuple[str, str], float]
    canonical_correlations: Dict[Tuple[str, str], float]
    var_impulse_response: Dict[str, List[float]]
    
    # Lead-Lag Matrix
    lead_lag_matrix: Dict[Tuple[str, str], int]
    leadership_flow: List[Tuple[str, str, float]]  # (leader, follower, strength)
    
    # Composite Analysis
    market_structure: Dict[str, Any]
    cluster_analysis: Dict[str, List[str]]


class SecurityError(Exception):
    pass

class CorrelationAnalyzer:
    """
    Correlation & Lead-Lag Analyzer
    Thread-safe + Multi-symbol + Statistical rigor
    """
    
    def __init__(self, 
                 max_history_days: int = 30,
                 correlation_window: int = 100,
                 default_symbols: List[str] = None):
        
        self.aggregator = MultiUserBinanceAggregator.get_instance()
        
        # Configuration
        self.max_history_days = max_history_days
        self.correlation_window = correlation_window
        self.default_symbols = default_symbols or [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 
            'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT'
        ]
        
        # Data cache
        self.price_cache: Dict[str, deque] = {}
        self.correlation_cache: Dict[str, LeadLagMetrics] = {}
        self.gc_test_cache: Dict[str, Any] = {}  # Granger causality cache
        
        # Performance monitoring
        self._execution_times: deque = deque(maxlen=1000)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        
        # Thread safety
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        
        logger.info("CorrelationAnalyzer initialized successfully")
    
    async def start(self):
        """Start analyzer with periodic cleanup"""
        if self._is_running:
            return
            
        self._is_running = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("CorrelationAnalyzer started with periodic cleanup")
    
    async def stop(self):
        """Stop analyzer and cleanup resources"""
        self._is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Clear caches
        async with self._global_lock:
            self.price_cache.clear()
            self.correlation_cache.clear()
            self.gc_test_cache.clear()
        
        logger.info("CorrelationAnalyzer stopped and cleaned up")
    

    # _get_symbol_lock methodunu düzelt:
    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create symbol-specific lock - SYNC VERSION"""
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]
        

        
    
    
    def _get_cache_key(self, symbols: List[str], timeframe: str = '1h') -> str:
        """Generate cache key for symbol set and timeframe"""
        symbol_key = ":".join(sorted(symbols))
        timeframe_key = timeframe
        combined = f"{symbol_key}:{timeframe_key}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    async def _periodic_cleanup(self):
        """Periodic cache cleanup task"""
        logger.info("Starting periodic correlation cache cleanup")
        
        while self._is_running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                
                current_time = time.time()
                keys_to_remove = []
                
                # Remove old correlation results (> 1 hour)
                async with self._global_lock:
                    for key, metrics in self.correlation_cache.items():
                        if current_time - getattr(metrics, '_created_at', current_time) > 3600:
                            keys_to_remove.append(key)
                    
                    for key in keys_to_remove:
                        del self.correlation_cache[key]
                
                # Trim price cache
                for symbol in list(self.price_cache.keys()):
                    if len(self.price_cache[symbol]) > self.correlation_window * 2:
                        self.price_cache[symbol] = deque(
                            list(self.price_cache[symbol])[-self.correlation_window:],
                            maxlen=self.correlation_window * 2
                        )
                
                logger.debug(f"Correlation cleanup: removed {len(keys_to_remove)} cache entries")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Correlation cleanup error: {e}")
    
    async def fetch_price_data(self, symbol: str, interval: str = '1h', limit: int = 500) -> PriceSeries:
        """
        Fetch price data for symbol with caching and validation
        """
        async with self._get_symbol_lock(symbol):
            try:
                # Check cache first
                cache_key = f"{symbol}:{interval}"
                if cache_key in self.price_cache and len(self.price_cache[cache_key]) > 0:
                    cached_data = self.price_cache[cache_key][-1]
                    if time.time() - cached_data.timestamps[-1] / 1000 < 3600:  # 1 hour freshness
                        return cached_data
                
                # Fetch new data
                klines_data = await self.aggregator.public.spot.get_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    user_id=None
                )
                
                if not klines_data or len(klines_data) < 10:
                    raise ValueError(f"Insufficient data for {symbol}")
                
                # Parse klines data
                timestamps = np.array([float(k[0]) for k in klines_data])
                closes = np.array([float(k[4]) for k in klines_data])
                
                # Calculate returns
                returns = np.diff(np.log(closes))
                
                # Handle edge cases
                if len(returns) < 2:
                    raise ValueError(f"Insufficient returns data for {symbol}")
                
                # Create price series
                price_series = PriceSeries(
                    symbol=symbol,
                    timestamps=timestamps[1:],  # Align with returns
                    prices=closes[1:],
                    returns=returns,
                    source='spot'
                )
                
                # Update cache
                if cache_key not in self.price_cache:
                    self.price_cache[cache_key] = deque(maxlen=10)
                self.price_cache[cache_key].append(price_series)
                
                logger.debug(f"Fetched price data for {symbol}: {len(returns)} periods")
                
                return price_series
                
            except Exception as e:
                logger.error(f"Error fetching price data for {symbol}: {e}")
                raise
    
    def calculate_pearson_correlation(self, series1: PriceSeries, series2: PriceSeries) -> float:
        """Calculate Pearson correlation between two price series"""
        try:
            # Align series by length
            min_len = min(len(series1.returns), len(series2.returns))
            if min_len < 10:
                return 0.0
            
            returns1 = series1.returns[-min_len:]
            returns2 = series2.returns[-min_len:]
            
            correlation, _ = pearsonr(returns1, returns2)
            return float(correlation)
            
        except Exception as e:
            logger.error(f"Error calculating Pearson correlation: {e}")
            return 0.0
    
    def calculate_beta(self, series1: PriceSeries, series2: PriceSeries) -> float:
        """Calculate beta coefficient (sensitivity)"""
        try:
            min_len = min(len(series1.returns), len(series2.returns))
            if min_len < 10:
                return 0.0
            
            returns1 = series1.returns[-min_len:]
            returns2 = series2.returns[-min_len:]
            
            # Beta = cov(X,Y) / var(X)
            covariance = np.cov(returns1, returns2)[0, 1]
            variance = np.var(returns1)
            
            if variance == 0:
                return 0.0
            
            beta = covariance / variance
            return float(beta)
            
        except Exception as e:
            logger.error(f"Error calculating beta: {e}")
            return 0.0
    
    def calculate_rolling_covariance(self, series1: PriceSeries, series2: PriceSeries, window: int = 20) -> float:
        """Calculate rolling covariance"""
        try:
            min_len = min(len(series1.returns), len(series2.returns))
            if min_len < window:
                return 0.0
            
            returns1 = series1.returns[-min_len:]
            returns2 = series2.returns[-min_len:]
            
            # Simple rolling covariance
            covariances = []
            for i in range(len(returns1) - window + 1):
                slice1 = returns1[i:i+window]
                slice2 = returns2[i:i+window]
                cov = np.cov(slice1, slice2)[0, 1]
                covariances.append(cov)
            
            return float(np.mean(covariances)) if covariances else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating rolling covariance: {e}")
            return 0.0
    
    def calculate_granger_causality(self, series1: PriceSeries, series2: PriceSeries, maxlag: int = 5) -> Dict[str, Any]:
        """Perform Granger causality test"""
        try:
            min_len = min(len(series1.returns), len(series2.returns))
            if min_len < maxlag * 2:
                return {'causality': False, 'p_value': 1.0, 'f_statistic': 0.0}
            
            returns1 = series1.returns[-min_len:]
            returns2 = series2.returns[-min_len:]
            
            # Prepare data for Granger test
            data = np.column_stack([returns1, returns2])
            
            # Perform Granger causality test
            gc_result = grangercausalitytests(data, maxlag=maxlag, verbose=False)
            
            # Extract best lag results
            best_p_value = 1.0
            best_f_statistic = 0.0
            best_lag = 1
            
            for lag, results in gc_result.items():
                p_value = results[0]['ssr_ftest'][1]
                f_statistic = results[0]['ssr_ftest'][0]
                
                if p_value < best_p_value:
                    best_p_value = p_value
                    best_f_statistic = f_statistic
                    best_lag = lag
            
            causality = best_p_value < 0.05  # 95% confidence
            
            return {
                'causality': causality,
                'p_value': float(best_p_value),
                'f_statistic': float(best_f_statistic),
                'best_lag': best_lag,
                'direction': 'series1->series2' if causality else 'no_causality'
            }
            
        except Exception as e:
            logger.error(f"Error calculating Granger causality: {e}")
            return {'causality': False, 'p_value': 1.0, 'f_statistic': 0.0, 'error': str(e)}
    
    def calculate_dynamic_time_warping(self, series1: PriceSeries, series2: PriceSeries) -> float:
        """Calculate Dynamic Time Warping distance"""
        try:
            min_len = min(len(series1.prices), len(series2.prices))
            if min_len < 20:
                return float('inf')
            
            # Use normalized prices for DTW
            prices1 = series1.prices[-min_len:]
            prices2 = series2.prices[-min_len:]
            
            # Normalize prices
            norm1 = (prices1 - np.mean(prices1)) / np.std(prices1)
            norm2 = (prices2 - np.mean(prices2)) / np.std(prices2)
            
            # Simple DTW implementation (for demonstration)
            # In production, use optimized DTW library
            n, m = len(norm1), len(norm2)
            dtw_matrix = np.zeros((n+1, m+1))
            
            for i in range(1, n+1):
                for j in range(1, m+1):
                    cost = abs(norm1[i-1] - norm2[j-1])
                    dtw_matrix[i, j] = cost + min(dtw_matrix[i-1, j],    # insertion
                                                 dtw_matrix[i, j-1],    # deletion
                                                 dtw_matrix[i-1, j-1])  # match
            
            dtw_distance = dtw_matrix[n, m]
            return float(dtw_distance)
            
        except Exception as e:
            logger.error(f"Error calculating DTW: {e}")
            return float('inf')
    
    def calculate_canonical_correlation(self, series1: PriceSeries, series2: PriceSeries) -> float:
        """Calculate Canonical Correlation Analysis"""
        try:
            min_len = min(len(series1.returns), len(series2.returns))
            if min_len < 10:
                return 0.0
            
            # Create feature matrices (using rolling windows)
            window_size = 5
            if min_len < window_size * 2:
                return 0.0
            
            X, Y = [], []
            for i in range(min_len - window_size + 1):
                X.append(series1.returns[i:i+window_size])
                Y.append(series2.returns[i:i+window_size])
            
            X = np.array(X)
            Y = np.array(Y)
            
            # Perform CCA
            cca = CCA(n_components=1)
            cca.fit(X, Y)
            
            # Get canonical correlation
            X_c, Y_c = cca.transform(X, Y)
            corr = np.corrcoef(X_c.T, Y_c.T)[0, 1]
            
            return float(corr) if not np.isnan(corr) else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating canonical correlation: {e}")
            return 0.0
    
    def calculate_lead_lag_relationship(self, series1: PriceSeries, series2: PriceSeries, max_lag: int = 10) -> Tuple[int, float]:
        """Calculate lead-lag relationship using cross-correlation"""
        try:
            min_len = min(len(series1.returns), len(series2.returns))
            if min_len < max_lag * 2:
                return 0, 0.0
            
            returns1 = series1.returns[-min_len:]
            returns2 = series2.returns[-min_len:]
            
            # Calculate cross-correlation
            cross_corr = signal.correlate(returns1 - np.mean(returns1), 
                                        returns2 - np.mean(returns2),
                                        mode='full')
            
            lags = signal.correlation_lags(len(returns1), len(returns2), mode='full')
            
            # Find lag with maximum correlation
            max_idx = np.argmax(np.abs(cross_corr))
            best_lag = lags[max_idx]
            max_corr = cross_corr[max_idx]
            
            return int(best_lag), float(max_corr)
            
        except Exception as e:
            logger.error(f"Error calculating lead-lag: {e}")
            return 0, 0.0
    
    def perform_var_analysis(self, symbols: List[str], price_series: Dict[str, PriceSeries]) -> Dict[str, Any]:
        """Perform Vector AutoRegression analysis"""
        try:
            if len(symbols) < 2:
                return {}
            
            # Prepare data matrix
            min_length = min(len(price_series[sym].returns) for sym in symbols)
            if min_length < 20:
                return {}
            
            data = np.column_stack([price_series[sym].returns[-min_length:] for sym in symbols])
            
            # Fit VAR model
            var_model = sm.tsa.VAR(data)
            var_result = var_model.fit(maxlags=5, ic='aic')
            
            # Calculate impulse response
            irf = var_result.irf(periods=10)
            
            return {
                'model_order': var_result.k_ar,
                'aic': float(var_result.aic),
                'bic': float(var_result.bic),
                'impulse_response': irf.irfs.tolist(),
                'coeff_determination': var_result.rsquared
            }
            
        except Exception as e:
            logger.error(f"Error performing VAR analysis: {e}")
            return {}
    
    async def analyze_correlation_network(self, symbols: Optional[List[str]] = None, 
                                        timeframe: str = '1h') -> LeadLagMetrics:
        """
        Comprehensive correlation and lead-lag analysis
        """
        start_time = time.time()
        
        try:
            symbols = symbols or self.default_symbols
            symbols = [s.upper() for s in symbols]
            
            # Input validation
            if len(symbols) < 2:
                raise ValueError("At least 2 symbols required for correlation analysis")
            
            # Check cache
            cache_key = self._get_cache_key(symbols, timeframe)
            if cache_key in self.correlation_cache:
                self._cache_hits += 1
                return self.correlation_cache[cache_key]
            
            self._cache_misses += 1
            
            # Fetch price data for all symbols
            price_series = {}
            fetch_tasks = []
            
            for symbol in symbols:
                task = asyncio.create_task(self.fetch_price_data(symbol, timeframe))
                fetch_tasks.append((symbol, task))
            
            for symbol, task in fetch_tasks:
                try:
                    price_series[symbol] = await task
                except Exception as e:
                    logger.warning(f"Failed to fetch data for {symbol}: {e}")
                    continue
            
            if len(price_series) < 2:
                raise ValueError("Insufficient data for correlation analysis")
            
            # Initialize result matrices
            correlation_matrix = {}
            beta_matrix = {}
            covariance_matrix = {}
            granger_causality = {}
            dtw_distances = {}
            canonical_correlations = {}
            lead_lag_matrix = {}
            
            # Calculate pairwise metrics
            symbol_pairs = []
            for i, sym1 in enumerate(symbols):
                for j, sym2 in enumerate(symbols):
                    if i >= j or sym1 not in price_series or sym2 not in price_series:
                        continue
                    
                    pair = (sym1, sym2)
                    symbol_pairs.append(pair)
                    
                    # Classical metrics
                    correlation_matrix[pair] = self.calculate_pearson_correlation(
                        price_series[sym1], price_series[sym2]
                    )
                    beta_matrix[pair] = self.calculate_beta(
                        price_series[sym1], price_series[sym2]
                    )
                    covariance_matrix[pair] = self.calculate_rolling_covariance(
                        price_series[sym1], price_series[sym2]
                    )
                    
                    # Professional metrics
                    granger_causality[pair] = self.calculate_granger_causality(
                        price_series[sym1], price_series[sym2]
                    )
                    dtw_distances[pair] = self.calculate_dynamic_time_warping(
                        price_series[sym1], price_series[sym2]
                    )
                    canonical_correlations[pair] = self.calculate_canonical_correlation(
                        price_series[sym1], price_series[sym2]
                    )
                    
                    # Lead-lag analysis
                    lead_lag, confidence = self.calculate_lead_lag_relationship(
                        price_series[sym1], price_series[sym2]
                    )
                    lead_lag_matrix[pair] = lead_lag
            
            # VAR analysis
            var_results = self.perform_var_analysis(symbols, price_series)
            
            # Leadership flow analysis
            leadership_flow = self._calculate_leadership_flow(lead_lag_matrix, correlation_matrix)
            
            # Market structure analysis
            market_structure = self._analyze_market_structure(correlation_matrix, symbols)
            
            # Cluster analysis
            cluster_analysis = self._perform_cluster_analysis(correlation_matrix, symbols)
            
            # Create metrics container
            metrics = LeadLagMetrics(
                timestamp=int(time.time() * 1000),
                symbol_pairs=symbol_pairs,
                correlation_matrix=correlation_matrix,
                beta_matrix=beta_matrix,
                covariance_matrix=covariance_matrix,
                granger_causality=granger_causality,
                dtw_distances=dtw_distances,
                canonical_correlations=canonical_correlations,
                var_impulse_response=var_results.get('impulse_response', {}),
                lead_lag_matrix=lead_lag_matrix,
                leadership_flow=leadership_flow,
                market_structure=market_structure,
                cluster_analysis=cluster_analysis
            )
            
            # Add cache metadata
            metrics._created_at = time.time()
            
            # Update cache
            async with self._global_lock:
                self.correlation_cache[cache_key] = metrics
            
            execution_time = time.time() - start_time
            self._execution_times.append(execution_time)
            
            logger.info(f"Correlation analysis completed: {len(symbols)} symbols, "
                       f"{len(symbol_pairs)} pairs, time: {execution_time:.2f}s")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Correlation analysis failed: {e}")
            raise
    
    def _calculate_leadership_flow(self, lead_lag_matrix: Dict[Tuple[str, str], int],
                                 correlation_matrix: Dict[Tuple[str, str], float]) -> List[Tuple[str, str, float]]:
        """Calculate leadership flow from lead-lag matrix"""
        try:
            leadership_scores = defaultdict(float)
            
            for (sym1, sym2), lag in lead_lag_matrix.items():
                correlation = correlation_matrix.get((sym1, sym2), 0)
                confidence = abs(correlation)
                
                if lag > 0:  # sym1 leads sym2
                    leadership_scores[(sym1, sym2)] = confidence
                elif lag < 0:  # sym2 leads sym1
                    leadership_scores[(sym2, sym1)] = confidence
            
            # Sort by strength
            sorted_leadership = sorted(
                [(leader, follower, strength) for (leader, follower), strength in leadership_scores.items()],
                key=lambda x: x[2],
                reverse=True
            )
            
            return sorted_leadership[:10]  # Top 10 relationships
            
        except Exception as e:
            logger.error(f"Error calculating leadership flow: {e}")
            return []
    
    def _analyze_market_structure(self, correlation_matrix: Dict[Tuple[str, str], float],
                                symbols: List[str]) -> Dict[str, Any]:
        """Analyze overall market structure"""
        try:
            # Calculate average correlation
            correlations = list(correlation_matrix.values())
            avg_correlation = np.mean(correlations) if correlations else 0
            
            # Find most correlated pair
            # most_correlated = max(correlation_matrix.items(), key=lambda x: abs(x[1]), (('', ''), 0))
            most_correlated = max(
                correlation_matrix.items(),
                key=lambda x: abs(x[1]),
                default=(('', ''), 0)
            )

            
            # Calculate correlation distribution
            correlation_strength = {
                'very_strong': len([c for c in correlations if abs(c) > 0.8]),
                'strong': len([c for c in correlations if 0.6 < abs(c) <= 0.8]),
                'moderate': len([c for c in correlations if 0.4 < abs(c) <= 0.6]),
                'weak': len([c for c in correlations if abs(c) <= 0.4])
            }
            
            return {
                'average_correlation': float(avg_correlation),
                'most_correlated_pair': {
                    'pair': most_correlated[0],
                    'correlation': float(most_correlated[1])
                },
                'correlation_distribution': correlation_strength,
                'market_regime': 'highly_correlated' if avg_correlation > 0.6 else 'decoupled'
            }
            
        except Exception as e:
            logger.error(f"Error analyzing market structure: {e}")
            return {}
    
    def _perform_cluster_analysis(self, correlation_matrix: Dict[Tuple[str, str], float],
                                symbols: List[str]) -> Dict[str, List[str]]:
        """Perform simple cluster analysis based on correlations"""
        try:
            # Simple threshold-based clustering
            clusters = []
            assigned = set()
            
            for symbol in symbols:
                if symbol in assigned:
                    continue
                
                cluster = [symbol]
                assigned.add(symbol)
                
                # Find highly correlated symbols
                for other in symbols:
                    if other in assigned or other == symbol:
                        continue
                    
                    pair = (symbol, other) if symbol < other else (other, symbol)
                    correlation = correlation_matrix.get(pair, 0)
                    
                    if abs(correlation) > 0.7:  # Strong correlation threshold
                        cluster.append(other)
                        assigned.add(other)
                
                clusters.append(cluster)
            
            return {
                'clusters': clusters,
                'cluster_count': len(clusters),
                'largest_cluster': max(clusters, key=len) if clusters else []
            }
            
        except Exception as e:
            logger.error(f"Error performing cluster analysis: {e}")
            return {'clusters': [], 'cluster_count': 0, 'largest_cluster': []}
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        avg_time = np.mean(self._execution_times) if self._execution_times else 0
        cache_hit_rate = (self._cache_hits / (self._cache_hits + self._cache_misses) 
                         if (self._cache_hits + self._cache_misses) > 0 else 0)
        
        return {
            "average_execution_time": avg_time,
            "total_analyses": len(self._execution_times),
            "cache_hit_rate": cache_hit_rate,
            "price_cache_size": len(self.price_cache),
            "correlation_cache_size": len(self.correlation_cache),
            "active_symbol_locks": len(self._locks)
        }

# Global analyzer instance
_analyzer: Optional[CorrelationAnalyzer] = None

async def get_analyzer() -> CorrelationAnalyzer:
    """Get or create global analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = CorrelationAnalyzer()
        await _analyzer.start()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Main analysis function - Required by schema manager
    
    Args:
        symbol: Base symbol for analysis (e.g., "BTCUSDT")
        priority: Analysis priority level (optional)
    
    Returns:
        Correlation and lead-lag analysis results
    """
    start_time = time.time()
    
    try:
        # Input validation and sanitization
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol provided")
        
        symbol = symbol.strip().upper()
        
        # Get analyzer instance
        analyzer = await get_analyzer()
        
        # Determine symbols for analysis based on base symbol
        if symbol == 'BTCUSDT':
            analysis_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT']
        elif symbol == 'ETHUSDT':
            analysis_symbols = ['ETHUSDT', 'BTCUSDT', 'BNBUSDT', 'LINKUSDT', 'MATICUSDT']
        else:
            # Include major symbols + the requested symbol
            analysis_symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', symbol]
            analysis_symbols = list(dict.fromkeys(analysis_symbols))  # Remove duplicates
        
        # Run correlation analysis
        metrics = await analyzer.analyze_correlation_network(analysis_symbols)
        
        # Prepare response based on priority
        result = {
            'symbol': symbol,
            'analysis_symbols': analysis_symbols,
            'timestamp': metrics.timestamp,
            'execution_time': round(time.time() - start_time, 4),
            'status': 'success'
        }
        
        # Basic results for all priority levels
        result.update({
            'market_structure': metrics.market_structure,
            'cluster_analysis': metrics.cluster_analysis,
            'leadership_flow': [
                {'leader': leader, 'follower': follower, 'strength': round(strength, 4)}
                for leader, follower, strength in metrics.leadership_flow
            ]
        })
        
        # Add detailed metrics based on priority level
        if priority in ['*', '**', '***']:
            # Correlation matrix (simplified)
            corr_matrix = {}
            for (sym1, sym2), corr in metrics.correlation_matrix.items():
                if sym1 == symbol or sym2 == symbol:  # Focus on relationships with base symbol
                    corr_matrix[f"{sym1}-{sym2}"] = round(corr, 4)
            
            result['detailed_metrics'] = {
                'correlation_matrix': corr_matrix,
                'beta_exposure': {
                    f"{sym1}-{sym2}": round(beta, 4)
                    for (sym1, sym2), beta in metrics.beta_matrix.items()
                    if sym1 == symbol or sym2 == symbol
                },
                'granger_causality': {
                    f"{sym1}-{sym2}": {
                        'causality': gc['causality'],
                        'p_value': round(gc['p_value'], 4),
                        'direction': gc['direction']
                    }
                    for (sym1, sym2), gc in metrics.granger_causality.items()
                    if sym1 == symbol or sym2 == symbol
                }
            }
        
        # Add interpretation
        result['interpretation'] = _interpret_correlation_structure(metrics.market_structure)
        
        logger.info(f"Correlation analysis completed for {symbol}: "
                   f"Clusters: {metrics.cluster_analysis.get('cluster_count', 0)}, "
                   f"Time: {result['execution_time']:.2f}s")
        
        return result
        
    except Exception as e:
        logger.error(f"Correlation analysis failed for {symbol}: {e}")
        
        return {
            'symbol': symbol,
            'timestamp': int(time.time() * 1000),
            'execution_time': round(time.time() - start_time, 4),
            'status': 'error',
            'error': str(e),
            'interpretation': 'Analysis failed'
        }

def _interpret_correlation_structure(market_structure: Dict[str, Any]) -> str:
    """Interpret correlation structure"""
    avg_corr = market_structure.get('average_correlation', 0)
    regime = market_structure.get('market_regime', 'unknown')
    
    if regime == 'highly_correlated':
        return "Market is highly correlated - assets moving together"
    elif avg_corr > 0.3:
        return "Moderate correlation - some independent movement"
    else:
        return "Low correlation - assets trading independently"

# Example usage
if __name__ == "__main__":
    async def test_analysis():
        """Test function for correlation analysis"""
        result = await run("BTCUSDT", priority="*")
        print("Correlation Analysis Result:")
        print(f"Base Symbol: {result['symbol']}")
        print(f"Market Regime: {result['interpretation']}")
        print(f"Cluster Count: {result['cluster_analysis']['cluster_count']}")
        print(f"Execution Time: {result['execution_time']}s")
        
        if 'leadership_flow' in result:
            print("\nTop Leadership Relationships:")
            for flow in result['leadership_flow'][:3]:
                print(f"  {flow['leader']} → {flow['follower']} (strength: {flow['strength']})")
    
    # Run test
    import asyncio
    asyncio.run(test_analysis())