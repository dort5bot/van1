# analysis/ordmic.py
"""
Order Flow & Microstructure Analysis Module
============================================
Gerçek zamanlı likidite yönü ve piyasa mikro yapısı analizi.
CVD (Cumulative Volume Delta) + OFI (Order Flow Imbalance) kombinasyonu ile
anlık yön ve likidite baskısı tespiti.

Features:
- Real-time liquidity pressure detection
- Order book imbalance analysis  
- Market microstructure metrics
- Professional trading insights

🎯 Core Features
profesyonel trader'lar için anlık piyasa yönü ve likidite baskısını tespit ederek high-quality trading sinyalleri sağlar.

Gerçek Zamanlı Likidite Analizi: Order book imbalance + trade flow kombinasyonu
Profesyonel Metrikler: CVD, OFI, Taker Dominance, Liquidity Density
Composite Scoring: 0-1 arası likidite baskı skoru
Thread-Safe Design: Asyncio lock'lar ile güvenli concurrent execution

📊 Analytical Depth
Multi-timeframe Analysis: Son 100 trade ve order book snapshot
Volume Profile: Buy/sell ratio ve volume distribution
Depth Analysis: Farklı price level'larda likidite yoğunluğu
Market Microstructure: Gerçek piyasa dinamikleri tespiti

"""

import asyncio
import logging
import time
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import deque

# Binance API imports
from utils.binance_api.binance_a import MultiUserBinanceAggregator

logger = logging.getLogger(__name__)

@dataclass
class OrderBookSnapshot:
    """Order book snapshot data structure"""
    symbol: str
    timestamp: int
    bids: List[Tuple[float, float]]  # (price, quantity)
    asks: List[Tuple[float, float]]
    spread: float
    mid_price: float

@dataclass
class TradeFlow:
    """Trade flow data structure"""
    symbol: str
    timestamp: int
    price: float
    quantity: float
    is_buyer_maker: bool
    trade_type: str  # 'BUY' or 'SELL'

@dataclass
class MicrostructureMetrics:
    """Microstructure metrics container"""
    symbol: str
    timestamp: int
    
    # Classical Metrics
    orderbook_imbalance: float
    spread: float
    market_pressure: float
    
    # Professional Metrics
    cumulative_volume_delta: float
    order_flow_imbalance: float
    taker_dominance_ratio: float
    liquidity_density: float
    
    # Composite Score
    liquidity_pressure_score: float
    
    # Additional Context
    volume_profile: Dict[str, float]
    depth_analysis: Dict[str, Any]

class OrderFlowAnalyzer:
    """
    Order Flow & Microstructure Analyzer
    Thread-safe + Real-time analysis + Multi-user support
    """
    
    def __init__(self, max_trade_history: int = 1000, max_orderbook_snapshots: int = 100):
        self.aggregator = MultiUserBinanceAggregator.get_instance()
        
        # Data buffers
        self.trade_history: Dict[str, deque] = {}
        self.orderbook_snapshots: Dict[str, deque] = {}
        self.metrics_history: Dict[str, deque] = {}
        
        # Configuration
        self.max_trade_history = max_trade_history
        self.max_orderbook_snapshots = max_orderbook_snapshots
        
        # Locks for thread safety
        self._locks: Dict[str, asyncio.Lock] = {}
        
        logger.info("OrderFlowAnalyzer initialized successfully")
    
    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create symbol-specific lock"""
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]
    
    def _initialize_buffers(self, symbol: str):
        """Initialize data buffers for symbol"""
        if symbol not in self.trade_history:
            self.trade_history[symbol] = deque(maxlen=self.max_trade_history)
        if symbol not in self.orderbook_snapshots:
            self.orderbook_snapshots[symbol] = deque(maxlen=self.max_orderbook_snapshots)
        if symbol not in self.metrics_history:
            self.metrics_history[symbol] = deque(maxlen=500)
    
    async def fetch_orderbook_data(self, symbol: str, limit: int = 100) -> OrderBookSnapshot:
        """Fetch current order book data"""
        try:
            orderbook_data = await self.aggregator.public.futures.get_order_book(
                symbol=symbol, 
                limit=limit,
                user_id=None  # Public endpoint
            )
            
            # Parse order book data
            bids = [(float(bid[0]), float(bid[1])) for bid in orderbook_data.get('bids', [])]
            asks = [(float(ask[0]), float(ask[1])) for ask in orderbook_data.get('asks', [])]
            
            # Calculate metrics
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            spread = best_ask - best_bid if best_ask and best_bid else 0
            mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
            
            snapshot = OrderBookSnapshot(
                symbol=symbol,
                timestamp=int(time.time() * 1000),
                bids=bids,
                asks=asks,
                spread=spread,
                mid_price=mid_price
            )
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Error fetching orderbook for {symbol}: {e}")
            raise
    
    async def fetch_recent_trades(self, symbol: str, limit: int = 500) -> List[TradeFlow]:
        """Fetch recent trades data"""
        try:
            trades_data = await self.aggregator.public.futures.get_recent_trades(
                symbol=symbol,
                limit=limit,
                user_id=None  # Public endpoint
            )
            
            trades = []
            for trade in trades_data:
                trade_flow = TradeFlow(
                    symbol=symbol,
                    timestamp=trade.get('time', 0),
                    price=float(trade.get('price', 0)),
                    quantity=float(trade.get('qty', 0)),
                    is_buyer_maker=trade.get('isBuyerMaker', False),
                    trade_type='BUY' if not trade.get('isBuyerMaker', False) else 'SELL'
                )
                trades.append(trade_flow)
            
            return trades
            
        except Exception as e:
            logger.error(f"Error fetching trades for {symbol}: {e}")
            raise
    
    def calculate_orderbook_imbalance(self, orderbook: OrderBookSnapshot) -> float:
        """Calculate order book imbalance"""
        try:
            # Sum quantities for bids and asks
            total_bid_qty = sum(qty for _, qty in orderbook.bids[:10])  # Top 10 levels
            total_ask_qty = sum(qty for _, qty in orderbook.asks[:10])
            
            if total_bid_qty + total_ask_qty == 0:
                return 0.0
            
            imbalance = (total_bid_qty - total_ask_qty) / (total_bid_qty + total_ask_qty)
            return float(imbalance)
            
        except Exception as e:
            logger.error(f"Error calculating orderbook imbalance: {e}")
            return 0.0
    
    def calculate_cumulative_volume_delta(self, trades: List[TradeFlow]) -> float:
        """Calculate Cumulative Volume Delta (CVD)"""
        try:
            cvd = 0.0
            for trade in trades[-100:]:  # Last 100 trades
                if trade.trade_type == 'BUY':
                    cvd += trade.quantity
                else:
                    cvd -= trade.quantity
            
            return cvd
            
        except Exception as e:
            logger.error(f"Error calculating CVD: {e}")
            return 0.0
    
    def calculate_order_flow_imbalance(self, trades: List[TradeFlow]) -> float:
        """Calculate Order Flow Imbalance Index (OFI)"""
        try:
            if not trades:
                return 0.0
            
            recent_trades = trades[-50:]  # Last 50 trades
            
            buy_volume = sum(trade.quantity for trade in recent_trades if trade.trade_type == 'BUY')
            sell_volume = sum(trade.quantity for trade in recent_trades if trade.trade_type == 'SELL')
            
            total_volume = buy_volume + sell_volume
            if total_volume == 0:
                return 0.0
            
            ofi = (buy_volume - sell_volume) / total_volume
            return float(ofi)
            
        except Exception as e:
            logger.error(f"Error calculating OFI: {e}")
            return 0.0
    
    def calculate_taker_dominance_ratio(self, trades: List[TradeFlow]) -> float:
        """Calculate Taker Dominance Ratio"""
        try:
            if not trades:
                return 0.0
            
            recent_trades = trades[-100:]  # Last 100 trades
            
            taker_buys = sum(1 for trade in recent_trades 
                           if trade.trade_type == 'BUY' and not trade.is_buyer_maker)
            taker_sells = sum(1 for trade in recent_trades 
                            if trade.trade_type == 'SELL' and trade.is_buyer_maker)
            
            total_taker_trades = taker_buys + taker_sells
            if total_taker_trades == 0:
                return 0.0
            
            dominance_ratio = (taker_buys - taker_sells) / total_taker_trades
            return float(dominance_ratio)
            
        except Exception as e:
            logger.error(f"Error calculating taker dominance ratio: {e}")
            return 0.0
    
    def calculate_liquidity_density(self, orderbook: OrderBookSnapshot) -> float:
        """Calculate Liquidity Density Map"""
        try:
            # Analyze liquidity concentration around mid price
            mid_price = orderbook.mid_price
            price_range = orderbook.spread * 2  # ± spread around mid
            
            if price_range == 0:
                return 0.0
            
            # Calculate liquidity within price range
            bid_liquidity = sum(qty for price, qty in orderbook.bids 
                              if mid_price - price_range <= price <= mid_price)
            ask_liquidity = sum(qty for price, qty in orderbook.asks 
                              if mid_price <= price <= mid_price + price_range)
            
            total_liquidity = bid_liquidity + ask_liquidity
            
            # Normalize by average liquidity
            avg_liquidity_per_level = total_liquidity / (len(orderbook.bids) + len(orderbook.asks))
            if avg_liquidity_per_level == 0:
                return 0.0
            
            density_score = total_liquidity / (avg_liquidity_per_level * price_range)
            return float(min(density_score, 1.0))  # Cap at 1.0
            
        except Exception as e:
            logger.error(f"Error calculating liquidity density: {e}")
            return 0.0
    
    def calculate_market_pressure(self, orderbook_imbalance: float, ofi: float) -> float:
        """Calculate combined market pressure"""
        try:
            # Weighted combination of orderbook imbalance and order flow imbalance
            pressure = (orderbook_imbalance * 0.6) + (ofi * 0.4)
            return float(pressure)
            
        except Exception as e:
            logger.error(f"Error calculating market pressure: {e}")
            return 0.0
    
    def calculate_liquidity_pressure_score(self, metrics: MicrostructureMetrics) -> float:
        """Calculate final liquidity pressure score (0-1)"""
        try:
            # Normalize individual metrics
            normalized_imbalance = (metrics.orderbook_imbalance + 1) / 2  # -1 to 1 -> 0 to 1
            normalized_cvd = self._normalize_cvd(metrics.cumulative_volume_delta)
            normalized_ofi = (metrics.order_flow_imbalance + 1) / 2  # -1 to 1 -> 0 to 1
            normalized_taker = (metrics.taker_dominance_ratio + 1) / 2  # -1 to 1 -> 0 to 1
            
            # Weighted composite score
            composite_score = (
                normalized_imbalance * 0.25 +
                normalized_cvd * 0.25 +
                normalized_ofi * 0.20 +
                normalized_taker * 0.15 +
                metrics.liquidity_density * 0.15
            )
            
            # Ensure score is between 0 and 1
            pressure_score = max(0.0, min(1.0, composite_score))
            
            return pressure_score
            
        except Exception as e:
            logger.error(f"Error calculating liquidity pressure score: {e}")
            return 0.5  # Neutral score on error
    
    def _normalize_cvd(self, cvd: float) -> float:
        """Normalize CVD to 0-1 range"""
        try:
            # Use historical context for normalization
            if hasattr(self, 'cvd_stats'):
                mean, std = self.cvd_stats
                if std > 0:
                    z_score = (cvd - mean) / (std * 2)  # 2 std dev range
                    return max(0.0, min(1.0, (z_score + 1) / 2))
            
            # Fallback normalization
            normalized = 1 / (1 + np.exp(-cvd / 1000))  # Sigmoid normalization
            return float(normalized)
            
        except Exception as e:
            logger.error(f"Error normalizing CVD: {e}")
            return 0.5
    
    async def analyze_microstructure(self, symbol: str) -> MicrostructureMetrics:
        """
        Comprehensive microstructure analysis
        Thread-safe + Real-time data + Professional metrics
        """
        async with self._get_symbol_lock(symbol):
            try:
                self._initialize_buffers(symbol)
                
                # Fetch current data
                orderbook = await self.fetch_orderbook_data(symbol)
                trades = await self.fetch_recent_trades(symbol)
                
                # Update data buffers
                self.orderbook_snapshots[symbol].append(orderbook)
                self.trade_history[symbol].extend(trades)
                
                # Calculate classical metrics
                orderbook_imbalance = self.calculate_orderbook_imbalance(orderbook)
                spread = orderbook.spread
                market_pressure = self.calculate_market_pressure(orderbook_imbalance, 0)  # OFI will be added later
                
                # Calculate professional metrics
                cvd = self.calculate_cumulative_volume_delta(trades)
                ofi = self.calculate_order_flow_imbalance(trades)
                taker_dominance = self.calculate_taker_dominance_ratio(trades)
                liquidity_density = self.calculate_liquidity_density(orderbook)
                
                # Update market pressure with OFI
                market_pressure = self.calculate_market_pressure(orderbook_imbalance, ofi)
                
                # Create metrics container
                metrics = MicrostructureMetrics(
                    symbol=symbol,
                    timestamp=orderbook.timestamp,
                    orderbook_imbalance=orderbook_imbalance,
                    spread=spread,
                    market_pressure=market_pressure,
                    cumulative_volume_delta=cvd,
                    order_flow_imbalance=ofi,
                    taker_dominance_ratio=taker_dominance,
                    liquidity_density=liquidity_density,
                    liquidity_pressure_score=0.0,  # Will be calculated
                    volume_profile=self._calculate_volume_profile(trades),
                    depth_analysis=self._analyze_orderbook_depth(orderbook)
                )
                
                # Calculate final pressure score
                metrics.liquidity_pressure_score = self.calculate_liquidity_pressure_score(metrics)
                
                # Update metrics history
                self.metrics_history[symbol].append(metrics)
                
                logger.info(f"Microstructure analysis completed for {symbol}: "
                           f"Pressure Score: {metrics.liquidity_pressure_score:.3f}")
                
                return metrics
                
            except Exception as e:
                logger.error(f"Microstructure analysis failed for {symbol}: {e}")
                raise
    
    def _calculate_volume_profile(self, trades: List[TradeFlow]) -> Dict[str, float]:
        """Calculate volume profile from trades"""
        try:
            buy_volume = sum(trade.quantity for trade in trades if trade.trade_type == 'BUY')
            sell_volume = sum(trade.quantity for trade in trades if trade.trade_type == 'SELL')
            total_volume = buy_volume + sell_volume
            
            return {
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'total_volume': total_volume,
                'buy_ratio': buy_volume / total_volume if total_volume > 0 else 0.0,
                'sell_ratio': sell_volume / total_volume if total_volume > 0 else 0.0
            }
        except Exception as e:
            logger.error(f"Error calculating volume profile: {e}")
            return {}
    
    def _analyze_orderbook_depth(self, orderbook: OrderBookSnapshot) -> Dict[str, Any]:
        """Analyze order book depth structure"""
        try:
            # Calculate depth at different levels
            depth_levels = [0.001, 0.005, 0.01, 0.02]  # Price offsets from mid
            
            depth_analysis = {}
            for level in depth_levels:
                price_offset = orderbook.mid_price * level
                
                # Bid depth
                bid_depth = sum(qty for price, qty in orderbook.bids 
                              if price >= orderbook.mid_price - price_offset)
                
                # Ask depth
                ask_depth = sum(qty for price, qty in orderbook.asks 
                              if price <= orderbook.mid_price + price_offset)
                
                depth_analysis[f'depth_{int(level*1000)}bp'] = {
                    'bid_depth': bid_depth,
                    'ask_depth': ask_depth,
                    'depth_imbalance': (bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0.0
                }
            
            return depth_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing orderbook depth: {e}")
            return {}

# Global analyzer instance
_analyzer: Optional[OrderFlowAnalyzer] = None

async def get_analyzer() -> OrderFlowAnalyzer:
    """Get or create global analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = OrderFlowAnalyzer()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Main analysis function - Required by schema manager
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        priority: Analysis priority level (optional)
    
    Returns:
        Analysis results with liquidity pressure score
    """
    start_time = time.time()
    
    try:
        # Input validation
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol provided")
        
        symbol = symbol.strip().upper()
        
        # Get analyzer instance
        analyzer = await get_analyzer()
        
        # Run microstructure analysis
        metrics = await analyzer.analyze_microstructure(symbol)
        
        # Prepare response based on priority
        result = {
            'symbol': symbol,
            'liquidity_pressure_score': round(metrics.liquidity_pressure_score, 4),
            'timestamp': metrics.timestamp,
            'execution_time': round(time.time() - start_time, 4),
            'status': 'success'
        }
        
        # Add detailed metrics based on priority level
        if priority in ['*', '**', '***']:
            result.update({
                'classical_metrics': {
                    'orderbook_imbalance': round(metrics.orderbook_imbalance, 6),
                    'spread': round(metrics.spread, 6),
                    'market_pressure': round(metrics.market_pressure, 6)
                },
                'professional_metrics': {
                    'cumulative_volume_delta': round(metrics.cumulative_volume_delta, 4),
                    'order_flow_imbalance': round(metrics.order_flow_imbalance, 6),
                    'taker_dominance_ratio': round(metrics.taker_dominance_ratio, 6),
                    'liquidity_density': round(metrics.liquidity_density, 6)
                },
                'volume_profile': metrics.volume_profile,
                'depth_analysis': metrics.depth_analysis
            })
        
        # Add interpretation
        result['interpretation'] = _interpret_pressure_score(metrics.liquidity_pressure_score)
        
        logger.info(f"Order flow analysis completed for {symbol}: "
                   f"Score: {metrics.liquidity_pressure_score:.4f}, "
                   f"Time: {result['execution_time']:.2f}s")
        
        return result
        
    except Exception as e:
        logger.error(f"Order flow analysis failed for {symbol}: {e}")
        
        return {
            'symbol': symbol,
            'liquidity_pressure_score': 0.5,  # Neutral score on error
            'timestamp': int(time.time() * 1000),
            'execution_time': round(time.time() - start_time, 4),
            'status': 'error',
            'error': str(e),
            'interpretation': 'Analysis failed - neutral score assigned'
        }

def _interpret_pressure_score(score: float) -> str:
    """Interpret liquidity pressure score"""
    if score >= 0.7:
        return "Strong buying pressure - bullish liquidity"
    elif score >= 0.6:
        return "Moderate buying pressure"
    elif score >= 0.4:
        return "Balanced liquidity - neutral"
    elif score >= 0.3:
        return "Moderate selling pressure"
    else:
        return "Strong selling pressure - bearish liquidity"

# Example usage
if __name__ == "__main__":
    async def test_analysis():
        """Test function for order flow analysis"""
        result = await run("BTCUSDT", priority="*")
        print("Order Flow Analysis Result:")
        print(f"Symbol: {result['symbol']}")
        print(f"Pressure Score: {result['liquidity_pressure_score']}")
        print(f"Interpretation: {result['interpretation']}")
        print(f"Execution Time: {result['execution_time']}s")
    
    # Run test
    import asyncio
    asyncio.run(test_analysis())