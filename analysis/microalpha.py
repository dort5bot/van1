# analysis/microalpha.py
"""
Market Micro Alpha (Tick-Level Alpha Factor) Analysis Module
=============================================================
Gerçek zamanlı mikro-yapı yönü ve hacimsel alpha faktörü üretimi.
WebSocket tick verileri + REST API kombinasyonu ile high-frequency alpha tespiti.

Features:
- Real-time WebSocket data processing
- Tick-level order flow analysis
- Microstructure alpha generation
- Low-latency signal processing
- Professional market making metrics

🎯 Core Features
Real-Time WebSocket Processing: Live tick data processing with automatic reconnection
High-Frequency Alpha Generation: Microsecond-level signal detection
Multi-Timeframe Aggregation: 1s, 5s, 30s aggregation windows
Professional Market Microstructure: CVD, OFI, Microprice, Kyle's Lambda

📊 Analytical Depth
Cumulative Volume Delta (CVD): Real-time volume imbalance
Order Flow Imbalance (OFI): Trade direction analysis
Microprice Deviation: Advanced price discovery metrics
Market Impact Modeling: Kyle's Lambda estimation
Latency Adjustment: Time-weighted flow analysis
High-Frequency Z-Score: Statistical anomaly detection


"""

import asyncio
import logging
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Deque
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import hashlib
import json
import websockets
from datetime import datetime, timedelta

# Binance API imports
from utils.binance_api.binance_a import MultiUserBinanceAggregator

logger = logging.getLogger(__name__)

@dataclass
class TickData:
    """Individual tick data structure"""
    symbol: str
    timestamp: int
    price: float
    quantity: float
    is_buyer_maker: bool
    trade_id: Optional[int] = None

@dataclass
class OrderBookSnapshot:
    """Order book snapshot for microprice calculation"""
    symbol: str
    timestamp: int
    bids: List[Tuple[float, float]]  # (price, quantity)
    asks: List[Tuple[float, float]]
    spread: float
    mid_price: float

@dataclass
class MicrostructureMetrics:
    """Microstructure alpha metrics container"""
    symbol: str
    timestamp: int
    
    # Classical Metrics
    tick_volume: int
    spread: float
    bid_ask_imbalance: float
    trade_direction_ratio: float
    
    # Professional Metrics
    cumulative_volume_delta: float
    order_flow_imbalance: float
    microprice_deviation: float
    market_impact_kyle: float
    latency_adjusted_flow: float
    high_frequency_zscore: float
    
    # Alpha Factors
    micro_alpha_score: float
    trend_direction: int  # 1: bullish, -1: bearish, 0: neutral
    confidence: float
    
    # Aggregation Context
    aggregation_period: str  # 1s, 5s, etc.
    data_points: int

class WebSocketManager:
    """
    WebSocket connection manager for real-time tick data
    Thread-safe + Connection pooling + Automatic reconnection
    """
    
    def __init__(self):
        self.connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.data_buffers: Dict[str, Deque[TickData]] = defaultdict(lambda: deque(maxlen=10000))
        self.orderbook_buffers: Dict[str, Deque[OrderBookSnapshot]] = defaultdict(lambda: deque(maxlen=1000))
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_lock = asyncio.Lock()
        self._is_running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        
        logger.info("WebSocketManager initialized")
    
    async def start(self):
        """Start WebSocket manager"""
        self._is_running = True
        logger.info("WebSocketManager started")
    
    async def stop(self):
        """Stop all WebSocket connections"""
        self._is_running = False
        async with self._global_lock:
            for symbol, ws in self.connections.items():
                try:
                    await ws.close()
                except Exception as e:
                    logger.warning(f"Error closing WebSocket for {symbol}: {e}")
            self.connections.clear()
        logger.info("WebSocketManager stopped")
    
    async def connect_symbol(self, symbol: str):
        """Connect to WebSocket for specific symbol"""
        async with self._get_symbol_lock(symbol):
            if symbol in self.connections:
                return  # Already connected
            
            try:
                # Binance Futures WebSocket endpoints
                trade_stream = f"wss://fstream.binance.com/ws/{symbol.lower()}@trade"
                depth_stream = f"wss://fstream.binance.com/ws/{symbol.lower()}@depth@100ms"
                
                # Connect to trade stream
                trade_ws = await websockets.connect(trade_stream, ping_interval=20, ping_timeout=10)
                self.connections[f"{symbol}_trade"] = trade_ws
                
                # Connect to depth stream
                depth_ws = await websockets.connect(depth_stream, ping_interval=20, ping_timeout=10)
                self.connections[f"{symbol}_depth"] = depth_ws
                
                # Start message handlers
                asyncio.create_task(self._handle_trade_messages(symbol, trade_ws))
                asyncio.create_task(self._handle_depth_messages(symbol, depth_ws))
                
                logger.info(f"WebSocket connected for {symbol}")
                
            except Exception as e:
                logger.error(f"WebSocket connection failed for {symbol}: {e}")
                await self._reconnect_symbol(symbol)
    
    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get symbol-specific lock"""
        return self._locks[symbol]
    
    async def _reconnect_symbol(self, symbol: str):
        """Automatic reconnection with exponential backoff"""
        delay = self._reconnect_delay
        
        while self._is_running and delay <= self._max_reconnect_delay:
            try:
                logger.info(f"Attempting to reconnect {symbol} in {delay}s...")
                await asyncio.sleep(delay)
                await self.connect_symbol(symbol)
                return
            except Exception as e:
                logger.warning(f"Reconnection failed for {symbol}: {e}")
                delay = min(delay * 2, self._max_reconnect_delay)
        
        logger.error(f"Max reconnection attempts reached for {symbol}")
    
    async def _handle_trade_messages(self, symbol: str, websocket):
        """Handle trade WebSocket messages"""
        try:
            async for message in websocket:
                if not self._is_running:
                    break
                
                try:
                    data = json.loads(message)
                    
                    tick = TickData(
                        symbol=symbol,
                        timestamp=data.get('T', int(time.time() * 1000)),
                        price=float(data['p']),
                        quantity=float(data['q']),
                        is_buyer_maker=data['m'],
                        trade_id=data.get('t')
                    )
                    
                    async with self._get_symbol_lock(symbol):
                        self.data_buffers[symbol].append(tick)
                    
                except Exception as e:
                    logger.error(f"Error processing trade message for {symbol}: {e}")
                    
        except Exception as e:
            logger.error(f"Trade WebSocket error for {symbol}: {e}")
            if self._is_running:
                await self._reconnect_symbol(symbol)
    
    async def _handle_depth_messages(self, symbol: str, websocket):
        """Handle depth WebSocket messages"""
        try:
            async for message in websocket:
                if not self._is_running:
                    break
                
                try:
                    data = json.loads(message)
                    
                    # Parse order book data
                    bids = [(float(price), float(qty)) for price, qty in data.get('b', [])]
                    asks = [(float(price), float(qty)) for price, qty in data.get('a', [])]
                    
                    if bids and asks:
                        best_bid = bids[0][0]
                        best_ask = asks[0][0]
                        spread = best_ask - best_bid
                        mid_price = (best_bid + best_ask) / 2
                        
                        snapshot = OrderBookSnapshot(
                            symbol=symbol,
                            timestamp=data.get('E', int(time.time() * 1000)),
                            bids=bids,
                            asks=asks,
                            spread=spread,
                            mid_price=mid_price
                        )
                        
                        async with self._get_symbol_lock(symbol):
                            self.orderbook_buffers[symbol].append(snapshot)
                    
                except Exception as e:
                    logger.error(f"Error processing depth message for {symbol}: {e}")
                    
        except Exception as e:
            logger.error(f"Depth WebSocket error for {symbol}: {e}")
            if self._is_running:
                await self._reconnect_symbol(symbol)
    
    def get_recent_ticks(self, symbol: str, lookback_ms: int = 5000) -> List[TickData]:
        """Get recent ticks within lookback period"""
        async with self._get_symbol_lock(symbol):
            current_time = int(time.time() * 1000)
            recent_ticks = [
                tick for tick in self.data_buffers[symbol]
                if current_time - tick.timestamp <= lookback_ms
            ]
            return recent_ticks
    
    def get_latest_orderbook(self, symbol: str) -> Optional[OrderBookSnapshot]:
        """Get latest order book snapshot"""
        async with self._get_symbol_lock(symbol):
            if self.orderbook_buffers[symbol]:
                return self.orderbook_buffers[symbol][-1]
            return None

class MicroAlphaAnalyzer:
    """
    Market Micro Alpha Analyzer
    High-frequency + Real-time + WebSocket driven analysis
    """
    
    def __init__(self, 
                 aggregation_periods: List[str] = None,
                 max_buffer_size: int = 10000):
        
        self.aggregator = MultiUserBinanceAggregator.get_instance()
        self.ws_manager = WebSocketManager()
        
        # Configuration
        self.aggregation_periods = aggregation_periods or ['1s', '5s', '30s']
        self.max_buffer_size = max_buffer_size
        
        # Analysis buffers
        self.alpha_cache: Dict[str, Dict[str, MicrostructureMetrics]] = defaultdict(dict)
        self.historical_alpha: Dict[str, Deque[MicrostructureMetrics]] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        
        # Performance monitoring
        self._execution_times: Deque[float] = deque(maxlen=1000)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        
        # Thread safety
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_lock = asyncio.Lock()
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        
        logger.info("MicroAlphaAnalyzer initialized successfully")
    
    async def start(self):
        """Start analyzer with WebSocket connections"""
        if self._is_running:
            return
            
        self._is_running = True
        await self.ws_manager.start()
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("MicroAlphaAnalyzer started with WebSocket connections")
    
    async def stop(self):
        """Stop analyzer and cleanup resources"""
        self._is_running = False
        await self.ws_manager.stop()
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Clear caches
        async with self._global_lock:
            self.alpha_cache.clear()
            self.historical_alpha.clear()
        
        logger.info("MicroAlphaAnalyzer stopped and cleaned up")
    
    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get symbol-specific lock"""
        return self._locks[symbol]
    
    def _get_cache_key(self, symbol: str, aggregation: str) -> str:
        """Generate cache key for symbol and aggregation period"""
        combined = f"{symbol}:{aggregation}:{int(time.time()) // 10}"  # 10-second chunks
        return hashlib.md5(combined.encode()).hexdigest()
    
    async def _periodic_cleanup(self):
        """Periodic cache cleanup task"""
        logger.info("Starting periodic microalpha cache cleanup")
        
        while self._is_running:
            try:
                await asyncio.sleep(60)  # 1 minute
                
                current_time = time.time()
                keys_to_remove = defaultdict(list)
                
                # Remove old alpha results (> 2 minutes)
                async with self._global_lock:
                    for symbol, aggregation_cache in self.alpha_cache.items():
                        for aggregation, metrics in aggregation_cache.items():
                            if current_time - getattr(metrics, '_created_at', current_time) > 120:
                                keys_to_remove[symbol].append(aggregation)
                    
                    for symbol, aggregations in keys_to_remove.items():
                        for aggregation in aggregations:
                            del self.alpha_cache[symbol][aggregation]
                
                logger.debug(f"Microalpha cleanup: removed {sum(len(v) for v in keys_to_remove.values())} cache entries")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Microalpha cleanup error: {e}")
    
    async def ensure_websocket_connection(self, symbol: str):
        """Ensure WebSocket connection for symbol"""
        try:
            await self.ws_manager.connect_symbol(symbol)
            # Small delay to ensure initial data collection
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"WebSocket connection failed for {symbol}: {e}")
            raise
    
    def calculate_tick_volume(self, ticks: List[TickData]) -> int:
        """Calculate total tick volume"""
        return len(ticks)
    
    def calculate_spread(self, orderbook: OrderBookSnapshot) -> float:
        """Calculate current spread"""
        return orderbook.spread
    
    def calculate_bid_ask_imbalance(self, orderbook: OrderBookSnapshot, depth_levels: int = 5) -> float:
        """Calculate bid-ask imbalance"""
        try:
            total_bid_qty = sum(qty for _, qty in orderbook.bids[:depth_levels])
            total_ask_qty = sum(qty for _, qty in orderbook.asks[:depth_levels])
            
            if total_bid_qty + total_ask_qty == 0:
                return 0.0
            
            imbalance = (total_bid_qty - total_ask_qty) / (total_bid_qty + total_ask_qty)
            return float(imbalance)
            
        except Exception as e:
            logger.error(f"Error calculating bid-ask imbalance: {e}")
            return 0.0
    
    def calculate_trade_direction_ratio(self, ticks: List[TickData]) -> float:
        """Calculate trade direction ratio"""
        try:
            if not ticks:
                return 0.0
            
            buy_ticks = sum(1 for tick in ticks if not tick.is_buyer_maker)
            sell_ticks = sum(1 for tick in ticks if tick.is_buyer_maker)
            
            total_ticks = buy_ticks + sell_ticks
            if total_ticks == 0:
                return 0.0
            
            direction_ratio = (buy_ticks - sell_ticks) / total_ticks
            return float(direction_ratio)
            
        except Exception as e:
            logger.error(f"Error calculating trade direction ratio: {e}")
            return 0.0
    
    def calculate_cumulative_volume_delta(self, ticks: List[TickData]) -> float:
        """Calculate Cumulative Volume Delta (CVD)"""
        try:
            cvd = 0.0
            for tick in ticks:
                if not tick.is_buyer_maker:  # Buyer-initiated (aggressive buy)
                    cvd += tick.quantity
                else:  # Seller-initiated (aggressive sell)
                    cvd -= tick.quantity
            
            return cvd
            
        except Exception as e:
            logger.error(f"Error calculating CVD: {e}")
            return 0.0
    
    def calculate_order_flow_imbalance(self, ticks: List[TickData]) -> float:
        """Calculate Order Flow Imbalance Index (OFI)"""
        try:
            if not ticks:
                return 0.0
            
            buy_volume = sum(tick.quantity for tick in ticks if not tick.is_buyer_maker)
            sell_volume = sum(tick.quantity for tick in ticks if tick.is_buyer_maker)
            
            total_volume = buy_volume + sell_volume
            if total_volume == 0:
                return 0.0
            
            ofi = (buy_volume - sell_volume) / total_volume
            return float(ofi)
            
        except Exception as e:
            logger.error(f"Error calculating OFI: {e}")
            return 0.0
    
    def calculate_microprice_deviation(self, orderbook: OrderBookSnapshot) -> float:
        """Calculate microprice deviation from mid-price"""
        try:
            # Microprice = (bid_price * ask_quantity + ask_price * bid_quantity) / (bid_quantity + ask_quantity)
            if not orderbook.bids or not orderbook.asks:
                return 0.0
            
            best_bid_price, best_bid_qty = orderbook.bids[0]
            best_ask_price, best_ask_qty = orderbook.asks[0]
            
            total_qty = best_bid_qty + best_ask_qty
            if total_qty == 0:
                return 0.0
            
            microprice = (best_bid_price * best_ask_qty + best_ask_price * best_bid_qty) / total_qty
            deviation = (microprice - orderbook.mid_price) / orderbook.mid_price
            
            return float(deviation)
            
        except Exception as e:
            logger.error(f"Error calculating microprice deviation: {e}")
            return 0.0
    
    def calculate_market_impact_kyle(self, ticks: List[TickData], orderbook: OrderBookSnapshot) -> float:
        """Calculate Kyle's lambda (market impact model)"""
        try:
            if not ticks or not orderbook.bids or not orderbook.asks:
                return 0.0
            
            # Simplified Kyle's lambda estimation
            recent_volume = sum(tick.quantity for tick in ticks[-10:])  # Last 10 trades
            spread = orderbook.spread
            mid_price = orderbook.mid_price
            
            if mid_price == 0 or spread == 0:
                return 0.0
            
            # Kyle's lambda ≈ spread / (price * volume)
            kyle_lambda = spread / (mid_price * recent_volume) if recent_volume > 0 else 0.0
            
            return float(kyle_lambda)
            
        except Exception as e:
            logger.error(f"Error calculating Kyle's lambda: {e}")
            return 0.0
    
    def calculate_latency_adjusted_flow(self, ticks: List[TickData]) -> float:
        """Calculate latency-adjusted flow ratio"""
        try:
            if len(ticks) < 2:
                return 0.0
            
            # Calculate time-weighted flow
            current_time = int(time.time() * 1000)
            weighted_flow = 0.0
            total_weight = 0.0
            
            for tick in ticks[-50:]:  # Last 50 ticks
                time_diff = current_time - tick.timestamp
                if time_diff <= 0:
                    continue
                
                # Exponential time decay
                weight = 1.0 / (1.0 + time_diff / 1000.0)  # 1-second half-life
                
                flow_contribution = tick.quantity * (1 if not tick.is_buyer_maker else -1)
                weighted_flow += flow_contribution * weight
                total_weight += weight
            
            if total_weight == 0:
                return 0.0
            
            normalized_flow = weighted_flow / total_weight
            return float(normalized_flow)
            
        except Exception as e:
            logger.error(f"Error calculating latency-adjusted flow: {e}")
            return 0.0
    
    def calculate_high_frequency_zscore(self, metrics: MicrostructureMetrics, 
                                      historical_data: List[MicrostructureMetrics]) -> float:
        """Calculate high-frequency Z-score for anomaly detection"""
        try:
            if len(historical_data) < 10:
                return 0.0
            
            # Use CVD for Z-score calculation
            recent_cvds = [m.cumulative_volume_delta for m in historical_data[-20:]]
            
            if len(recent_cvds) < 5:
                return 0.0
            
            mean_cvd = np.mean(recent_cvds)
            std_cvd = np.std(recent_cvds)
            
            if std_cvd == 0:
                return 0.0
            
            z_score = (metrics.cumulative_volume_delta - mean_cvd) / std_cvd
            return float(z_score)
            
        except Exception as e:
            logger.error(f"Error calculating HF Z-score: {e}")
            return 0.0
    
    def calculate_micro_alpha_score(self, metrics: MicrostructureMetrics) -> float:
        """Calculate composite micro alpha score (0-1)"""
        try:
            # Normalize individual components
            components = {
                'cvd': self._normalize_component(metrics.cumulative_volume_delta, -1000, 1000),
                'ofi': (metrics.order_flow_imbalance + 1) / 2,  # -1 to 1 -> 0 to 1
                'microprice': (metrics.microprice_deviation + 0.01) / 0.02,  # Normalize around zero
                'flow': self._normalize_component(metrics.latency_adjusted_flow, -100, 100),
                'zscore': self._normalize_component(metrics.high_frequency_zscore, -3, 3)
            }
            
            # Apply weights based on reliability
            weights = {
                'cvd': 0.25,
                'ofi': 0.20,
                'microprice': 0.25,
                'flow': 0.15,
                'zscore': 0.15
            }
            
            # Calculate weighted score
            alpha_score = 0.0
            total_weight = 0.0
            
            for component, value in components.items():
                if 0 <= value <= 1:  # Valid normalized value
                    alpha_score += value * weights[component]
                    total_weight += weights[component]
            
            if total_weight == 0:
                return 0.5  # Neutral score
            
            final_score = alpha_score / total_weight
            return min(1.0, max(0.0, final_score))
            
        except Exception as e:
            logger.error(f"Error calculating micro alpha score: {e}")
            return 0.5
    
    def _normalize_component(self, value: float, min_val: float, max_val: float) -> float:
        """Normalize component value to 0-1 range"""
        try:
            normalized = (value - min_val) / (max_val - min_val)
            return max(0.0, min(1.0, normalized))
        except:
            return 0.5
    
    def determine_trend_direction(self, metrics: MicrostructureMetrics) -> int:
        """Determine trend direction from microstructure signals"""
        try:
            bullish_signals = 0
            bearish_signals = 0
            
            # CVD signal
            if metrics.cumulative_volume_delta > 100:
                bullish_signals += 1
            elif metrics.cumulative_volume_delta < -100:
                bearish_signals += 1
            
            # OFI signal
            if metrics.order_flow_imbalance > 0.1:
                bullish_signals += 1
            elif metrics.order_flow_imbalance < -0.1:
                bearish_signals += 1
            
            # Microprice signal
            if metrics.microprice_deviation > 0.001:
                bullish_signals += 1
            elif metrics.microprice_deviation < -0.001:
                bearish_signals += 1
            
            # Determine overall direction
            if bullish_signals > bearish_signals + 1:
                return 1  # Bullish
            elif bearish_signals > bullish_signals + 1:
                return -1  # Bearish
            else:
                return 0  # Neutral
                
        except Exception as e:
            logger.error(f"Error determining trend direction: {e}")
            return 0
    
    async def analyze_microstructure(self, symbol: str, aggregation: str = '5s') -> MicrostructureMetrics:
        """
        Comprehensive microstructure analysis for alpha generation
        """
        start_time = time.time()
        
        try:
            # Ensure WebSocket connection
            await self.ensure_websocket_connection(symbol)
            
            # Check cache
            cache_key = self._get_cache_key(symbol, aggregation)
            if (symbol in self.alpha_cache and 
                aggregation in self.alpha_cache[symbol]):
                self._cache_hits += 1
                return self.alpha_cache[symbol][aggregation]
            
            self._cache_misses += 1
            
            async with self._get_symbol_lock(symbol):
                # Get recent data based on aggregation period
                lookback_ms = self._get_lookback_ms(aggregation)
                recent_ticks = self.ws_manager.get_recent_ticks(symbol, lookback_ms)
                latest_orderbook = self.ws_manager.get_latest_orderbook(symbol)
                
                if not recent_ticks or not latest_orderbook:
                    raise ValueError(f"Insufficient real-time data for {symbol}")
                
                # Calculate classical metrics
                tick_volume = self.calculate_tick_volume(recent_ticks)
                spread = self.calculate_spread(latest_orderbook)
                bid_ask_imbalance = self.calculate_bid_ask_imbalance(latest_orderbook)
                trade_direction_ratio = self.calculate_trade_direction_ratio(recent_ticks)
                
                # Calculate professional metrics
                cvd = self.calculate_cumulative_volume_delta(recent_ticks)
                ofi = self.calculate_order_flow_imbalance(recent_ticks)
                microprice_dev = self.calculate_microprice_deviation(latest_orderbook)
                kyle_lambda = self.calculate_market_impact_kyle(recent_ticks, latest_orderbook)
                latency_flow = self.calculate_latency_adjusted_flow(recent_ticks)
                
                # Get historical data for Z-score
                historical_data = list(self.historical_alpha[symbol])
                
                # Create initial metrics (Z-score will be calculated after)
                metrics = MicrostructureMetrics(
                    symbol=symbol,
                    timestamp=int(time.time() * 1000),
                    tick_volume=tick_volume,
                    spread=spread,
                    bid_ask_imbalance=bid_ask_imbalance,
                    trade_direction_ratio=trade_direction_ratio,
                    cumulative_volume_delta=cvd,
                    order_flow_imbalance=ofi,
                    microprice_deviation=microprice_dev,
                    market_impact_kyle=kyle_lambda,
                    latency_adjusted_flow=latency_flow,
                    high_frequency_zscore=0.0,  # Will be calculated
                    micro_alpha_score=0.0,  # Will be calculated
                    trend_direction=0,  # Will be calculated
                    confidence=0.0,  # Will be calculated
                    aggregation_period=aggregation,
                    data_points=len(recent_ticks)
                )
                
                # Calculate Z-score
                metrics.high_frequency_zscore = self.calculate_high_frequency_zscore(
                    metrics, historical_data
                )
                
                # Calculate final alpha score and trend
                metrics.micro_alpha_score = self.calculate_micro_alpha_score(metrics)
                metrics.trend_direction = self.determine_trend_direction(metrics)
                
                # Calculate confidence based on data quality
                metrics.confidence = min(1.0, len(recent_ticks) / 50.0)  # Normalize to 0-1
                
                # Add cache metadata
                metrics._created_at = time.time()
                
                # Update caches
                async with self._global_lock:
                    if symbol not in self.alpha_cache:
                        self.alpha_cache[symbol] = {}
                    self.alpha_cache[symbol][aggregation] = metrics
                    self.historical_alpha[symbol].append(metrics)
                
                execution_time = time.time() - start_time
                self._execution_times.append(execution_time)
                
                logger.info(f"Microstructure analysis completed for {symbol}: "
                           f"Alpha Score: {metrics.micro_alpha_score:.4f}, "
                           f"Trend: {metrics.trend_direction}, "
                           f"Ticks: {len(recent_ticks)}, "
                           f"Time: {execution_time:.3f}s")
                
                return metrics
                
        except Exception as e:
            logger.error(f"Microstructure analysis failed for {symbol}: {e}")
            raise
    
    def _get_lookback_ms(self, aggregation: str) -> int:
        """Convert aggregation period to milliseconds lookback"""
        if aggregation == '1s':
            return 1000
        elif aggregation == '5s':
            return 5000
        elif aggregation == '30s':
            return 30000
        elif aggregation == '1m':
            return 60000
        else:
            return 5000  # Default 5 seconds
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        avg_time = np.mean(self._execution_times) if self._execution_times else 0
        cache_hit_rate = (self._cache_hits / (self._cache_hits + self._cache_misses) 
                         if (self._cache_hits + self._cache_misses) > 0 else 0)
        
        return {
            "average_execution_time": avg_time,
            "total_analyses": len(self._execution_times),
            "cache_hit_rate": cache_hit_rate,
            "alpha_cache_size": len(self.alpha_cache),
            "historical_data_points": sum(len(q) for q in self.historical_alpha.values()),
            "active_symbol_locks": len(self._locks),
            "websocket_connections": len(self.ws_manager.connections)
        }

# Global analyzer instance
_analyzer: Optional[MicroAlphaAnalyzer] = None

async def get_analyzer() -> MicroAlphaAnalyzer:
    """Get or create global analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = MicroAlphaAnalyzer()
        await _analyzer.start()
    return _analyzer

async def run(symbol: str, priority: Optional[str] = None) -> Dict[str, Any]:
    """
    Main analysis function - Required by schema manager
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        priority: Analysis priority level (optional)
    
    Returns:
        Microstructure alpha analysis results
    """
    start_time = time.time()
    
    try:
        # Input validation and sanitization
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol provided")
        
        symbol = symbol.strip().upper()
        
        # Get analyzer instance
        analyzer = await get_analyzer()
        
        # Determine aggregation based on priority
        if priority == '***':  # Highest priority - fastest aggregation
            aggregation = '1s'
        elif priority == '**':  # Medium priority
            aggregation = '5s'
        else:  # Default and * priority
            aggregation = '5s'
        
        # Run microstructure analysis
        metrics = await analyzer.analyze_microstructure(symbol, aggregation)
        
        # Prepare response based on priority
        result = {
            'symbol': symbol,
            'micro_alpha_score': round(metrics.micro_alpha_score, 4),
            'timestamp': metrics.timestamp,
            'execution_time': round(time.time() - start_time, 4),
            'status': 'success',
            'trend_direction': metrics.trend_direction,
            'confidence': round(metrics.confidence, 4),
            'aggregation_period': metrics.aggregation_period,
            'data_points': metrics.data_points
        }
        
        # Basic signals for all priority levels
        trend_map = {1: "BULLISH", -1: "BEARISH", 0: "NEUTRAL"}
        result['trend_interpretation'] = trend_map[metrics.trend_direction]
        
        # Add detailed metrics based on priority level
        if priority in ['*', '**', '***']:
            result['detailed_metrics'] = {
                'classical_metrics': {
                    'tick_volume': metrics.tick_volume,
                    'spread': round(metrics.spread, 6),
                    'bid_ask_imbalance': round(metrics.bid_ask_imbalance, 4),
                    'trade_direction_ratio': round(metrics.trade_direction_ratio, 4)
                },
                'professional_metrics': {
                    'cumulative_volume_delta': round(metrics.cumulative_volume_delta, 2),
                    'order_flow_imbalance': round(metrics.order_flow_imbalance, 4),
                    'microprice_deviation': round(metrics.microprice_deviation, 6),
                    'market_impact_kyle': round(metrics.market_impact_kyle, 8),
                    'latency_adjusted_flow': round(metrics.latency_adjusted_flow, 2),
                    'high_frequency_zscore': round(metrics.high_frequency_zscore, 4)
                }
            }
        
        # Add trading signals
        result['trading_signals'] = _generate_trading_signals(metrics)
        
        logger.info(f"Microalpha analysis completed for {symbol}: "
                   f"Score: {metrics.micro_alpha_score:.4f}, "
                   f"Trend: {result['trend_interpretation']}, "
                   f"Time: {result['execution_time']:.3f}s")
        
        return result
        
    except Exception as e:
        logger.error(f"Microalpha analysis failed for {symbol}: {e}")
        
        return {
            'symbol': symbol,
            'micro_alpha_score': 0.5,  # Neutral score on error
            'timestamp': int(time.time() * 1000),
            'execution_time': round(time.time() - start_time, 4),
            'status': 'error',
            'error': str(e),
            'trend_interpretation': 'UNKNOWN',
            'confidence': 0.0,
            'aggregation_period': 'N/A',
            'data_points': 0,
            'trading_signals': {'action': 'HOLD', 'reason': 'Analysis failed'}
        }

def _generate_trading_signals(metrics: MicrostructureMetrics) -> Dict[str, Any]:
    """Generate actionable trading signals from microstructure metrics"""
    alpha_score = metrics.micro_alpha_score
    trend = metrics.trend_direction
    confidence = metrics.confidence
    
    if confidence < 0.3:
        return {'action': 'HOLD', 'reason': 'Low confidence in signals'}
    
    if alpha_score >= 0.7 and trend == 1:
        return {
            'action': 'BUY',
            'reason': 'Strong bullish microstructure',
            'confidence': 'HIGH',
            'suggested_size': 'Normal' if alpha_score < 0.8 else 'Large'
        }
    elif alpha_score >= 0.6 and trend == 1:
        return {
            'action': 'BUY',
            'reason': 'Moderate bullish microstructure', 
            'confidence': 'MEDIUM',
            'suggested_size': 'Small'
        }
    elif alpha_score <= 0.3 and trend == -1:
        return {
            'action': 'SELL',
            'reason': 'Strong bearish microstructure',
            'confidence': 'HIGH',
            'suggested_size': 'Normal' if alpha_score > 0.2 else 'Large'
        }
    elif alpha_score <= 0.4 and trend == -1:
        return {
            'action': 'SELL',
            'reason': 'Moderate bearish microstructure',
            'confidence': 'MEDIUM', 
            'suggested_size': 'Small'
        }
    else:
        return {'action': 'HOLD', 'reason': 'Neutral microstructure conditions'}

# Example usage
if __name__ == "__main__":
    async def test_analysis():
        """Test function for microalpha analysis"""
        result = await run("BTCUSDT", priority="*")
        print("MicroAlpha Analysis Result:")
        print(f"Symbol: {result['symbol']}")
        print(f"Micro Alpha Score: {result['micro_alpha_score']}")
        print(f"Trend: {result['trend_interpretation']}")
        print(f"Confidence: {result['confidence']}")
        print(f"Aggregation: {result['aggregation_period']}")
        print(f"Data Points: {result['data_points']}")
        print(f"Execution Time: {result['execution_time']}s")
        
        if 'trading_signals' in result:
            print(f"\nTrading Signal: {result['trading_signals']['action']}")
            print(f"Reason: {result['trading_signals']['reason']}")
    
    # Run test
    import asyncio
    asyncio.run(test_analysis())