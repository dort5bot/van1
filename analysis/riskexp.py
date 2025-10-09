# analysis/riskexp.py
"""
# analysis/riskexp.py
Risk & Exposure Management Module
==================================
Dinamik risk kontrolü ve pozisyon exposure yönetimi.
Value-at-Risk (VaR), Expected Shortfall (CVaR), ATR-based adaptive stop loss,
ve liquidation zone analizi ile kapsamlı risk skoru hesaplama.

Features:
- Multi-timeframe risk assessment
- Dynamic position sizing
- Liquidation proximity alerts
- Adaptive stop-loss mechanisms
- Portfolio exposure optimization
🎯 Core Features
Dynamic Risk Assessment: Real-time VaR, CVaR, ve drawdown analizi
Adaptive Position Sizing: Volatility-based pozisyon büyüklüğü optimizasyonu
Liquidation Zone Analysis: Yakın liquidation seviyeleri tespiti
Multi-Timeframe Analysis: Kısa ve uzun vadeli risk perspektifi
📊 Risk Management Depth
Value at Risk (VaR): Portfolio potential loss estimation
Conditional VaR (CVaR): Expected shortfall in extreme scenarios
ATR-based Stops: Volatility-adjusted stop loss seviyeleri
Liquidation Proximity: Yakın stop-out risk assessment
"""

import asyncio
import logging
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import hashlib

# Statistical imports
from scipy import stats
from scipy.optimize import minimize

# Binance API imports
from utils.binance_api.binance_a import BinanceAggregator, MultiUserBinanceAggregator

logger = logging.getLogger(__name__)

@dataclass
class RiskParameters:
    """Risk calculation parameters"""
    confidence_level: float = 0.95
    lookback_period: int = 100
    max_drawdown_window: int = 50
    liquidation_buffer: float = 0.05  # 5% buffer

@dataclass
class PriceVolatility:
    """Price and volatility data structure"""
    symbol: str
    timestamp: int
    prices: np.ndarray
    returns: np.ndarray
    volatility: float
    atr: float

@dataclass
class LiquidationData:
    """Liquidation zone analysis"""
    symbol: str
    liquidation_zones: List[Tuple[float, float]]  # (price, quantity)
    nearest_liquidation: float
    liquidation_risk_score: float
    estimated_liq_price: Optional[float] = None

@dataclass
class RiskMetrics:
    """Comprehensive risk metrics container"""
    symbol: str
    timestamp: int
    
    # Classical Metrics
    atr_stop_level: float
    liquidation_zones: List[Tuple[float, float]]
    max_drawdown: float
    current_drawdown: float
    
    # Professional Metrics
    value_at_risk: float
    conditional_var: float
    sharpe_ratio: float
    sortino_ratio: float
    adaptive_stop_loss: float
    
    # Exposure Analysis
    position_size_recommendation: float
    leverage_suggestion: float
    risk_adjusted_return: float
    
    # Composite Scores
    overall_risk_score: float
    market_risk_score: float
    liquidation_risk_score: float
    
    # Contextual Data
    volatility_regime: str
    risk_appetite: str

class RiskAnalyzer:
    """
    Risk & Exposure Management Analyzer
    Thread-safe + Real-time risk assessment + Multi-timeframe analysis
    """
    
    def __init__(self, 
                 risk_params: Optional[RiskParameters] = None,
                 max_history_days: int = 30):
        
        self.aggregator = MultiUserBinanceAggregator.get_instance()
        self.risk_params = risk_params or RiskParameters()
        
        # Configuration
        self.max_history_days = max_history_days
        
        # Data cache
        self.price_cache: Dict[str, deque] = {}
        self.risk_cache: Dict[str, RiskMetrics] = {}
        self.liquidation_cache: Dict[str, LiquidationData] = {}
        
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
        
        logger.info("RiskAnalyzer initialized successfully")
    
    async def start(self):
        """Start analyzer with periodic cleanup"""
        if self._is_running:
            return
            
        self._is_running = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("RiskAnalyzer started with periodic cleanup")
    
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
            self.risk_cache.clear()
            self.liquidation_cache.clear()
        
        logger.info("RiskAnalyzer stopped and cleaned up")
    
    # _get_symbol_lock methodunu düzelt:
    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create symbol-specific lock - SYNC VERSION"""
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]
        
    
    def _get_cache_key(self, symbol: str, timeframe: str = '1h') -> str:
        """Generate cache key for symbol and timeframe"""
        combined = f"{symbol}:{timeframe}:{self.risk_params.confidence_level}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    async def _periodic_cleanup(self):
        """Periodic cache cleanup task"""
        logger.info("Starting periodic risk cache cleanup")
        
        while self._is_running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                
                current_time = time.time()
                keys_to_remove = []
                
                # Remove old risk results (> 30 minutes)
                async with self._global_lock:
                    for key, metrics in self.risk_cache.items():
                        if current_time - getattr(metrics, '_created_at', current_time) > 1800:
                            keys_to_remove.append(key)
                    
                    for key in keys_to_remove:
                        del self.risk_cache[key]
                
                # Trim price cache
                for symbol in list(self.price_cache.keys()):
                    if len(self.price_cache[symbol]) > self.risk_params.lookback_period * 2:
                        self.price_cache[symbol] = deque(
                            list(self.price_cache[symbol])[-self.risk_params.lookback_period:],
                            maxlen=self.risk_params.lookback_period * 2
                        )
                
                logger.debug(f"Risk cleanup: removed {len(keys_to_remove)} cache entries")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk cleanup error: {e}")
    
    async def fetch_price_data(self, symbol: str, interval: str = '1h', limit: int = 500) -> PriceVolatility:
        """
        Fetch price data with volatility calculations
        """
        async with self._get_symbol_lock(symbol):
            try:
                # Check cache first
                cache_key = f"{symbol}:{interval}"
                if cache_key in self.price_cache and len(self.price_cache[cache_key]) > 0:
                    cached_data = self.price_cache[cache_key][-1]
                    if time.time() - cached_data.timestamp / 1000 < 3600:  # 1 hour freshness
                        return cached_data
                
                # Fetch klines data
                klines_data = await self.aggregator.public.spot.get_klines(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    user_id=None
                )
                
                if not klines_data or len(klines_data) < 20:
                    raise ValueError(f"Insufficient data for {symbol}")
                
                # Parse klines data
                timestamps = np.array([float(k[0]) for k in klines_data])
                highs = np.array([float(k[2]) for k in klines_data])
                lows = np.array([float(k[3]) for k in klines_data])
                closes = np.array([float(k[4]) for k in klines_data])
                
                # Calculate returns and volatility
                returns = np.diff(np.log(closes))
                
                if len(returns) < 10:
                    raise ValueError(f"Insufficient returns data for {symbol}")
                
                # Calculate ATR (Average True Range)
                atr = self._calculate_atr(highs, lows, closes, period=14)
                
                # Calculate volatility (annualized)
                volatility = np.std(returns) * np.sqrt(365 * 24)  # Assuming hourly data
                
                # Create price volatility object
                price_vol = PriceVolatility(
                    symbol=symbol,
                    timestamp=int(time.time() * 1000),
                    prices=closes,
                    returns=returns,
                    volatility=float(volatility),
                    atr=float(atr)
                )
                
                # Update cache
                if cache_key not in self.price_cache:
                    self.price_cache[cache_key] = deque(maxlen=10)
                self.price_cache[cache_key].append(price_vol)
                
                logger.debug(f"Fetched price data for {symbol}: volatility={volatility:.4f}, ATR={atr:.4f}")
                
                return price_vol
                
            except Exception as e:
                logger.error(f"Error fetching price data for {symbol}: {e}")
                raise
    
    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Calculate Average True Range"""
        try:
            true_ranges = []
            
            for i in range(1, len(highs)):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1])
                tr3 = abs(lows[i] - closes[i-1])
                true_range = max(tr1, tr2, tr3)
                true_ranges.append(true_range)
            
            if len(true_ranges) < period:
                return float(np.mean(true_ranges)) if true_ranges else 0.0
            
            atr = np.mean(true_ranges[-period:])
            return float(atr)
            
        except Exception as e:
            logger.error(f"Error calculating ATR: {e}")
            return 0.0
    
    async def fetch_liquidation_data(self, symbol: str) -> LiquidationData:
        """
        Fetch and analyze liquidation orders data
        """
        try:
            # Check cache
            if symbol in self.liquidation_cache:
                cached_data = self.liquidation_cache[symbol]
                if time.time() - cached_data.timestamp / 1000 < 600:  # 10 minutes freshness
                    return cached_data
            
            # Fetch liquidation orders
            liquidation_orders = await self.aggregator.public.futures.get_liquidation_orders(
                symbol=symbol,
                limit=50,
                user_id=None
            )
            
            # Fetch current price for reference
            current_price_data = await self.aggregator.public.futures.get_ticker_price(
                symbol=symbol,
                user_id=None
            )
            current_price = float(current_price_data['price']) if isinstance(current_price_data, dict) else float(current_price_data)
            
            # Analyze liquidation zones
            liquidation_zones = []
            nearest_liquidation = float('inf')
            
            for order in liquidation_orders:
                if isinstance(order, dict):
                    price = float(order.get('price', 0))
                    quantity = float(order.get('origQty', 0))
                    
                    if price > 0 and quantity > 0:
                        liquidation_zones.append((price, quantity))
                        
                        # Calculate distance from current price
                        distance = abs(price - current_price) / current_price
                        if distance < nearest_liquidation:
                            nearest_liquidation = distance
            
            # Calculate liquidation risk score
            liq_risk_score = min(1.0, nearest_liquidation / 0.1)  # Normalize to 0-1
            
            # Estimate liquidation price based on order book depth (simplified)
            estimated_liq_price = self._estimate_liquidation_price(liquidation_zones, current_price)
            
            liquidation_data = LiquidationData(
                symbol=symbol,
                liquidation_zones=liquidation_zones,
                nearest_liquidation=nearest_liquidation,
                liquidation_risk_score=liq_risk_score,
                estimated_liq_price=estimated_liq_price
            )
            
            # Update cache
            self.liquidation_cache[symbol] = liquidation_data
            
            return liquidation_data
            
        except Exception as e:
            logger.error(f"Error fetching liquidation data for {symbol}: {e}")
            # Return default liquidation data on error
            return LiquidationData(
                symbol=symbol,
                liquidation_zones=[],
                nearest_liquidation=float('inf'),
                liquidation_risk_score=0.0
            )
    
    def _estimate_liquidation_price(self, liquidation_zones: List[Tuple[float, float]], 
                                  current_price: float) -> Optional[float]:
        """Estimate potential liquidation price based on order concentration"""
        try:
            if not liquidation_zones:
                return None
            
            # Find price level with highest liquidation quantity
            zone_quantities = defaultdict(float)
            for price, quantity in liquidation_zones:
                # Group by price ranges (1% intervals)
                price_key = round(price, int(-np.log10(current_price)) + 2)
                zone_quantities[price_key] += quantity
            
            if not zone_quantities:
                return None
            
            # Find price with maximum liquidation quantity
            max_liq_price = max(zone_quantities.items(), key=lambda x: x[1])[0]
            
            return float(max_liq_price)
            
        except Exception as e:
            logger.error(f"Error estimating liquidation price: {e}")
            return None
    
    def calculate_atr_stop_level(self, price_vol: PriceVolatility, atr_multiplier: float = 2.0) -> float:
        """Calculate ATR-based stop loss level"""
        try:
            current_price = price_vol.prices[-1]
            atr_stop = current_price - (price_vol.atr * atr_multiplier)
            return max(0.0, atr_stop)
            
        except Exception as e:
            logger.error(f"Error calculating ATR stop level: {e}")
            return 0.0
    
    def calculate_max_drawdown(self, prices: np.ndarray, window: int = 50) -> Tuple[float, float]:
        """Calculate maximum and current drawdown"""
        try:
            if len(prices) < window:
                window = len(prices)
            
            recent_prices = prices[-window:]
            peak = np.maximum.accumulate(recent_prices)
            drawdowns = (peak - recent_prices) / peak
            
            max_drawdown = float(np.max(drawdowns))
            current_drawdown = float(drawdowns[-1])
            
            return max_drawdown, current_drawdown
            
        except Exception as e:
            logger.error(f"Error calculating drawdown: {e}")
            return 0.0, 0.0
    
    def calculate_value_at_risk(self, returns: np.ndarray, confidence_level: float = 0.95) -> Tuple[float, float]:
        """Calculate Value at Risk (VaR) and Conditional VaR (CVaR)"""
        try:
            if len(returns) < 10:
                return 0.0, 0.0
            
            # Parametric VaR (assuming normal distribution)
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            z_score = stats.norm.ppf(1 - confidence_level)
            var_parametric = mean_return + z_score * std_return
            
            # Historical VaR
            var_historical = np.percentile(returns, (1 - confidence_level) * 100)
            
            # Use conservative estimate
            var = min(var_parametric, var_historical)
            
            # Calculate Conditional VaR (Expected Shortfall)
            var_threshold = np.percentile(returns, (1 - confidence_level) * 100)
            cvar = np.mean(returns[returns <= var_threshold])
            
            return float(var), float(cvar)
            
        except Exception as e:
            logger.error(f"Error calculating VaR/CVaR: {e}")
            return 0.0, 0.0
    
    def calculate_sharpe_ratio(self, returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio (annualized)"""
        try:
            if len(returns) < 2 or np.std(returns) == 0:
                return 0.0
            
            excess_returns = returns - (risk_free_rate / 365 / 24)  # Assuming hourly data
            sharpe = np.mean(excess_returns) / np.std(returns) * np.sqrt(365 * 24)
            
            return float(sharpe)
            
        except Exception as e:
            logger.error(f"Error calculating Sharpe ratio: {e}")
            return 0.0
    
    def calculate_sortino_ratio(self, returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
        """Calculate Sortino ratio (annualized)"""
        try:
            if len(returns) < 2:
                return 0.0
            
            excess_returns = returns - (risk_free_rate / 365 / 24)
            downside_returns = returns[returns < 0]
            
            if len(downside_returns) == 0 or np.std(downside_returns) == 0:
                return 0.0
            
            sortino = np.mean(excess_returns) / np.std(downside_returns) * np.sqrt(365 * 24)
            
            return float(sortino)
            
        except Exception as e:
            logger.error(f"Error calculating Sortino ratio: {e}")
            return 0.0
    
    def calculate_adaptive_stop_loss(self, price_vol: PriceVolatility, 
                                  volatility_regime: str,
                                  current_drawdown: float) -> float:
        """Calculate adaptive stop loss based on market conditions"""
        try:
            current_price = price_vol.prices[-1]
            base_atr_multiplier = 2.0
            
            # Adjust multiplier based on volatility regime
            if volatility_regime == "high":
                atr_multiplier = base_atr_multiplier * 1.5
            elif volatility_regime == "low":
                atr_multiplier = base_atr_multiplier * 0.7
            else:
                atr_multiplier = base_atr_multiplier
            
            # Adjust for current drawdown
            if current_drawdown > 0.05:  # 5% drawdown
                atr_multiplier *= 0.8  # Tighter stop
            
            adaptive_stop = current_price - (price_vol.atr * atr_multiplier)
            
            return max(0.0, adaptive_stop)
            
        except Exception as e:
            logger.error(f"Error calculating adaptive stop loss: {e}")
            return self.calculate_atr_stop_level(price_vol)
    
    def calculate_position_size(self, volatility: float, 
                             account_size: float = 10000.0,
                             risk_per_trade: float = 0.02) -> float:
        """Calculate recommended position size based on volatility"""
        try:
            if volatility <= 0:
                return 0.0
            
            # Kelly Criterion inspired position sizing
            max_risk = account_size * risk_per_trade
            position_size = max_risk / (volatility * 2)  # Conservative sizing
            
            # Cap at 50% of account
            max_position = account_size * 0.5
            position_size = min(position_size, max_position)
            
            return float(position_size)
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0.0
    
    def calculate_leverage_suggestion(self, volatility: float, 
                                    risk_score: float,
                                    max_leverage: float = 10.0) -> float:
        """Calculate suggested leverage based on risk conditions"""
        try:
            base_leverage = 3.0  # Conservative base leverage
            
            # Adjust for volatility (inverse relationship)
            vol_adjustment = 1.0 / (1.0 + volatility)
            
            # Adjust for risk score (lower risk = higher leverage)
            risk_adjustment = 1.0 - risk_score
            
            suggested_leverage = base_leverage * vol_adjustment * risk_adjustment
            
            # Apply constraints
            suggested_leverage = max(1.0, min(suggested_leverage, max_leverage))
            
            return float(suggested_leverage)
            
        except Exception as e:
            logger.error(f"Error calculating leverage suggestion: {e}")
            return 1.0
    
    def determine_volatility_regime(self, volatility: float, 
                                  historical_vol: List[float]) -> str:
        """Determine current volatility regime"""
        try:
            if not historical_vol:
                return "medium"
            
            median_vol = np.median(historical_vol)
            
            if volatility > median_vol * 1.5:
                return "high"
            elif volatility < median_vol * 0.7:
                return "low"
            else:
                return "medium"
                
        except Exception as e:
            logger.error(f"Error determining volatility regime: {e}")
            return "medium"
    
    def calculate_overall_risk_score(self, metrics: RiskMetrics) -> float:
        """Calculate composite overall risk score (0-1)"""
        try:
            # Component weights
            weights = {
                'market_risk': 0.4,
                'liquidation_risk': 0.3,
                'drawdown_risk': 0.2,
                'volatility_risk': 0.1
            }
            
            # Normalize components to 0-1
            market_risk = min(1.0, abs(metrics.value_at_risk) * 10)  # Scale VaR
            liquidation_risk = metrics.liquidation_risk_score
            drawdown_risk = min(1.0, metrics.max_drawdown * 2)  # Scale drawdown
            volatility_risk = min(1.0, metrics.market_risk_score)
            
            # Weighted composite
            composite_score = (
                market_risk * weights['market_risk'] +
                liquidation_risk * weights['liquidation_risk'] +
                drawdown_risk * weights['drawdown_risk'] +
                volatility_risk * weights['volatility_risk']
            )
            
            return min(1.0, composite_score)
            
        except Exception as e:
            logger.error(f"Error calculating overall risk score: {e}")
            return 0.5
    
    async def analyze_risk_exposure(self, symbol: str, timeframe: str = '1h') -> RiskMetrics:
        """
        Comprehensive risk and exposure analysis
        """
        start_time = time.time()
        
        try:
            # Check cache
            cache_key = self._get_cache_key(symbol, timeframe)
            if cache_key in self.risk_cache:
                self._cache_hits += 1
                return self.risk_cache[cache_key]
            
            self._cache_misses += 1
            
            async with self._get_symbol_lock(symbol):
                # Fetch required data
                price_vol = await self.fetch_price_data(symbol, timeframe)
                liquidation_data = await self.fetch_liquidation_data(symbol)
                
                # Calculate classical metrics
                atr_stop_level = self.calculate_atr_stop_level(price_vol)
                max_drawdown, current_drawdown = self.calculate_max_drawdown(
                    price_vol.prices, self.risk_params.max_drawdown_window
                )
                
                # Calculate professional metrics
                var, cvar = self.calculate_value_at_risk(
                    price_vol.returns, self.risk_params.confidence_level
                )
                sharpe_ratio = self.calculate_sharpe_ratio(price_vol.returns)
                sortino_ratio = self.calculate_sortino_ratio(price_vol.returns)
                
                # Determine volatility regime
                volatility_regime = self.determine_volatility_regime(
                    price_vol.volatility, [price_vol.volatility]
                )
                
                # Calculate adaptive stop loss
                adaptive_stop_loss = self.calculate_adaptive_stop_loss(
                    price_vol, volatility_regime, current_drawdown
                )
                
                # Calculate exposure recommendations
                position_size = self.calculate_position_size(price_vol.volatility)
                
                # Preliminary risk score for leverage calculation
                preliminary_risk = min(1.0, abs(var) * 5 + current_drawdown)
                leverage_suggestion = self.calculate_leverage_suggestion(
                    price_vol.volatility, preliminary_risk
                )
                
                # Risk-adjusted return
                risk_adjusted_return = sharpe_ratio if not np.isnan(sharpe_ratio) else 0.0
                
                # Create initial metrics (will calculate final scores after)
                metrics = RiskMetrics(
                    symbol=symbol,
                    timestamp=int(time.time() * 1000),
                    atr_stop_level=atr_stop_level,
                    liquidation_zones=liquidation_data.liquidation_zones,
                    max_drawdown=max_drawdown,
                    current_drawdown=current_drawdown,
                    value_at_risk=var,
                    conditional_var=cvar,
                    sharpe_ratio=sharpe_ratio,
                    sortino_ratio=sortino_ratio,
                    adaptive_stop_loss=adaptive_stop_loss,
                    position_size_recommendation=position_size,
                    leverage_suggestion=leverage_suggestion,
                    risk_adjusted_return=risk_adjusted_return,
                    overall_risk_score=0.0,  # Will be calculated
                    market_risk_score=min(1.0, abs(var) * 8),  # Scaled VaR
                    liquidation_risk_score=liquidation_data.liquidation_risk_score,
                    volatility_regime=volatility_regime,
                    risk_appetite="conservative" if preliminary_risk > 0.7 else "moderate"
                )
                
                # Calculate final composite scores
                metrics.overall_risk_score = self.calculate_overall_risk_score(metrics)
                
                # Add cache metadata
                metrics._created_at = time.time()
                
                # Update cache
                async with self._global_lock:
                    self.risk_cache[cache_key] = metrics
                
                execution_time = time.time() - start_time
                self._execution_times.append(execution_time)
                
                logger.info(f"Risk analysis completed for {symbol}: "
                           f"Overall Risk: {metrics.overall_risk_score:.3f}, "
                           f"Time: {execution_time:.2f}s")
                
                return metrics
                
        except Exception as e:
            logger.error(f"Risk analysis failed for {symbol}: {e}")
            raise
    
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
            "risk_cache_size": len(self.risk_cache),
            "liquidation_cache_size": len(self.liquidation_cache),
            "active_symbol_locks": len(self._locks)
        }

# Global analyzer instance
_analyzer: Optional[RiskAnalyzer] = None

async def get_analyzer() -> RiskAnalyzer:
    """Get or create global analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = RiskAnalyzer()
        await _analyzer.start()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Main analysis function - Required by schema manager
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        priority: Analysis priority level (optional)
    
    Returns:
        Risk and exposure analysis results
    """
    start_time = time.time()
    
    try:
        # Input validation and sanitization
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol provided")
        
        symbol = symbol.strip().upper()
        
        # Get analyzer instance
        analyzer = await get_analyzer()
        
        # Run risk analysis
        metrics = await analyzer.analyze_risk_exposure(symbol)
        
        # Prepare response based on priority
        result = {
            'symbol': symbol,
            'overall_risk_score': round(metrics.overall_risk_score, 4),
            'timestamp': metrics.timestamp,
            'execution_time': round(time.time() - start_time, 4),
            'status': 'success',
            'risk_appetite': metrics.risk_appetite,
            'volatility_regime': metrics.volatility_regime
        }
        
        # Basic recommendations for all priority levels
        result.update({
            'recommendations': {
                'position_size': round(metrics.position_size_recommendation, 2),
                'suggested_leverage': round(metrics.leverage_suggestion, 2),
                'adaptive_stop_loss': round(metrics.adaptive_stop_loss, 4),
                'risk_adjusted_return': round(metrics.risk_adjusted_return, 4)
            }
        })
        
        # Add detailed metrics based on priority level
        if priority in ['*', '**', '***']:
            result['detailed_metrics'] = {
                'classical_metrics': {
                    'atr_stop_level': round(metrics.atr_stop_level, 4),
                    'max_drawdown': round(metrics.max_drawdown, 4),
                    'current_drawdown': round(metrics.current_drawdown, 4),
                    'liquidation_zones_count': len(metrics.liquidation_zones)
                },
                'professional_metrics': {
                    'value_at_risk': round(metrics.value_at_risk, 6),
                    'conditional_var': round(metrics.conditional_var, 6),
                    'sharpe_ratio': round(metrics.sharpe_ratio, 4),
                    'sortino_ratio': round(metrics.sortino_ratio, 4)
                },
                'risk_components': {
                    'market_risk_score': round(metrics.market_risk_score, 4),
                    'liquidation_risk_score': round(metrics.liquidation_risk_score, 4)
                }
            }
        
        # Add interpretation
        result['interpretation'] = _interpret_risk_score(metrics.overall_risk_score, metrics.risk_appetite)
        
        logger.info(f"Risk analysis completed for {symbol}: "
                   f"Score: {metrics.overall_risk_score:.4f}, "
                   f"Regime: {metrics.volatility_regime}, "
                   f"Time: {result['execution_time']:.2f}s")
        
        return result
        
    except Exception as e:
        logger.error(f"Risk analysis failed for {symbol}: {e}")
        
        return {
            'symbol': symbol,
            'overall_risk_score': 0.5,  # Neutral score on error
            'timestamp': int(time.time() * 1000),
            'execution_time': round(time.time() - start_time, 4),
            'status': 'error',
            'error': str(e),
            'interpretation': 'Analysis failed - neutral risk score assigned',
            'recommendations': {
                'position_size': 0,
                'suggested_leverage': 1,
                'adaptive_stop_loss': 0,
                'risk_adjusted_return': 0
            }
        }

def _interpret_risk_score(risk_score: float, risk_appetite: str) -> str:
    """Interpret risk score and provide actionable insights"""
    if risk_score >= 0.8:
        return "EXTREME RISK - Avoid trading, high probability of significant losses"
    elif risk_score >= 0.7:
        return "VERY HIGH RISK - Consider drastic position size reduction"
    elif risk_score >= 0.6:
        return "HIGH RISK - Reduce position size and use tight stops"
    elif risk_score >= 0.5:
        if risk_appetite == "conservative":
            return "MODERATE-HIGH RISK - Conservative traders should avoid"
        else:
            return "MODERATE RISK - Suitable for experienced traders with proper stops"
    elif risk_score >= 0.4:
        return "LOW-MODERATE RISK - Acceptable for most traders with risk management"
    elif risk_score >= 0.3:
        return "LOW RISK - Favorable conditions for trading"
    elif risk_score >= 0.2:
        return "VERY LOW RISK - Excellent risk-reward opportunities"
    else:
        return "MINIMAL RISK - Ideal trading conditions"

# Example usage
if __name__ == "__main__":
    async def test_analysis():
        """Test function for risk analysis"""
        result = await run("BTCUSDT", priority="*")
        print("Risk Analysis Result:")
        print(f"Symbol: {result['symbol']}")
        print(f"Overall Risk Score: {result['overall_risk_score']}")
        print(f"Interpretation: {result['interpretation']}")
        print(f"Volatility Regime: {result['volatility_regime']}")
        print(f"Risk Appetite: {result['risk_appetite']}")
        print(f"Execution Time: {result['execution_time']}s")
        
        print("\nRecommendations:")
        for key, value in result['recommendations'].items():
            print(f"  {key}: {value}")
    
    # Run test
    import asyncio
    asyncio.run(test_analysis())