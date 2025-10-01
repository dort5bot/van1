"""
Enhanced WebSocket client for Binance API.

Features:
- Spot, Futures, User Data streams
- Param validation for symbols, intervals, depth levels
- Async typing for callbacks
- Detailed error handling with HTTP code mapping
- ListenKey keepalive with retry
- Exponential backoff for reconnect
- Singleton pattern
"""

import asyncio
import json
import time
import logging
from typing import Dict, List, Any, Optional, Callable, Set, Union, Awaitable
from dataclasses import dataclass
from enum import Enum

import aiohttp
import websockets
from aiogram import Router, F
from aiogram.types import Message

from .binance_constants import BASE_URL, FUTURES_URL, WS_STREAMS
from .binance_exceptions import (
    BinanceWebSocketError,
    BinanceAuthenticationError,
    BinanceRateLimitError,
    BinanceAPIError,
)
from .binance_utils import generate_signature

logger = logging.getLogger(__name__)

# --------------------
# ENUMS & CONFIG
# --------------------
class StreamType(Enum):
    SPOT = "spot"
    FUTURES = "futures"
    USER_DATA = "user_data"

@dataclass
class WebSocketConfig:
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    testnet: bool = False
    base_url: str = "wss://stream.binance.com:9443"
    futures_url: str = "wss://fstream.binance.com"
    reconnect_delay: int = 1
    max_reconnect_delay: int = 60
    keepalive_interval: int = 1800  # 30 minutes
    listenkey_retry: int = 3
    rate_limit_delay: int = 1  # default delay for 429 retry

# --------------------
# BINANCE WEBSOCKET MANAGER
# --------------------
class BinanceWebSocketManager:
    _instance: Optional['BinanceWebSocketManager'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        testnet: bool = False,
        router: Optional[Router] = None
    ):
        if self._initialized:
            return

        self.config = WebSocketConfig(
            api_key=api_key,
            secret_key=secret_key,
            testnet=testnet,
            base_url="wss://testnet.binance.vision" if testnet else BASE_URL,
            futures_url="wss://stream.binancefuture.com" if testnet else FUTURES_URL
        )

        self.connections: Dict[str, Dict[str, Any]] = {}
        self.subscriptions: Dict[str, Set[str]] = {}
        self.callbacks: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}
        self.listen_keys: Dict[str, str] = {}

        self.router = router or Router()
        self._setup_handlers()

        self.running = False
        self._initialized = True

        logger.info("✅ BinanceWebSocketManager initialized with singleton pattern")

    # --------------------
    # AIROGRAM HANDLER
    # --------------------
    def _setup_handlers(self) -> None:
        @self.router.message(F.text == "/status")
        async def cmd_status(message: Message) -> None:
            status = self.get_status()
            await message.answer(f"WebSocket Status:\nActive connections: {status['active_connections']}")

    # --------------------
    # INITIALIZE / CLOSE
    # --------------------
    async def initialize(self) -> None:
        self.running = True
        logger.info("✅ BinanceWebSocketManager started")

    async def close_all(self) -> None:
        self.running = False
        tasks = []
        for conn in list(self.connections.values()):
            conn['running'] = False
            if conn.get('task'):
                conn['task'].cancel()
                tasks.append(conn['task'])
            if conn.get('keepalive_task'):
                conn['keepalive_task'].cancel()
                tasks.append(conn['keepalive_task'])
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.connections.clear()
        logger.info("✅ All WebSocket connections closed")

    # --------------------
    # CONNECTION & SUBSCRIPTION
    # --------------------
    async def connect(
        self,
        streams: List[str],
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        futures: bool = False
    ) -> str:
        if not streams:
            raise ValueError("Streams list cannot be empty")
        if not callable(callback):
            raise ValueError("Callback must be callable")

        try:
            url = self.config.futures_url if futures else self.config.base_url
            ws_url = f"{url}/stream?streams={'/'.join(streams)}"
            connection_id = f"{'futures_' if futures else 'spot_'}{int(time.time() * 1000)}"

            self.connections[connection_id] = {
                'url': ws_url,
                'streams': streams,
                'callback': callback,
                'futures': futures,
                'running': True,
                'task': None
            }

            self.connections[connection_id]['task'] = asyncio.create_task(
                self._run_connection(connection_id)
            )

            logger.info(f"✅ WebSocket connection {connection_id} started for {len(streams)} streams")
            return connection_id

        except Exception as e:
            logger.error("❌ Failed to create WebSocket connection", exc_info=True)
            raise BinanceWebSocketError(f"Connection failed: {e}") from e

    async def _run_connection(self, connection_id: str) -> None:
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]
        reconnect_delay = self.config.reconnect_delay

        while connection['running'] and self.running:
            try:
                async with websockets.connect(connection['url']) as ws:
                    logger.info(f"🔗 WebSocket {connection_id} connected")
                    reconnect_delay = self.config.reconnect_delay

                    while connection['running']:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            data = json.loads(message)
                            await connection['callback'](data)
                        except asyncio.TimeoutError:
                            await ws.ping()
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ JSON decode error: {e}", exc_info=True)
                        except Exception as e:
                            logger.error(f"❌ Callback error: {e}", exc_info=True)

            except websockets.ConnectionClosed:
                logger.warning(f"⚠️ WebSocket {connection_id} connection closed, reconnecting...")
            except Exception as e:
                logger.error(f"❌ WebSocket {connection_id} error: {e}", exc_info=True)

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, self.config.max_reconnect_delay)

    async def disconnect(self, connection_id: str) -> None:
        if connection_id not in self.connections:
            raise KeyError(f"Connection {connection_id} not found")

        conn = self.connections[connection_id]
        conn['running'] = False
        if conn.get('task'):
            conn['task'].cancel()
            try:
                await conn['task']
            except asyncio.CancelledError:
                pass
        if conn.get('keepalive_task'):
            conn['keepalive_task'].cancel()
            try:
                await conn['keepalive_task']
            except asyncio.CancelledError:
                pass
        del self.connections[connection_id]
        logger.info(f"✅ WebSocket {connection_id} disconnected")

    # --------------------
    # USER DATA STREAM
    # --------------------
    async def subscribe_user_data(
        self,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        futures: bool = False
    ) -> str:
        listen_key = await self._get_listen_key(futures)
        url = self.config.futures_url if futures else self.config.base_url
        ws_url = f"{url}/ws/{listen_key}"

        connection_id = f"user_data_{'futures_' if futures else 'spot_'}{int(time.time() * 1000)}"
        self.connections[connection_id] = {
            'url': ws_url,
            'streams': ['userData'],
            'callback': callback,
            'futures': futures,
            'running': True,
            'listen_key': listen_key,
            'task': None,
            'keepalive_task': None
        }

        # Start keepalive & connection tasks
        self.connections[connection_id]['keepalive_task'] = asyncio.create_task(
            self._keepalive_listen_key(listen_key, futures)
        )
        self.connections[connection_id]['task'] = asyncio.create_task(
            self._run_connection(connection_id)
        )

        logger.info(f"✅ User data WebSocket {connection_id} started")
        return connection_id

    async def _get_listen_key(self, futures: bool = False) -> str:
        endpoint = '/fapi/v1/listenKey' if futures else '/api/v3/userDataStream'
        url = (FUTURES_URL if futures else BASE_URL) + endpoint
        headers = {'X-MBX-APIKEY': self.config.api_key} if self.config.api_key else {}

        for attempt in range(self.config.listenkey_retry):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data['listenKey']
                        elif resp.status == 429:
                            logger.warning("⚠️ Rate limit hit, retrying...")
                            await asyncio.sleep(self.config.rate_limit_delay)
                        elif resp.status in (400, 401, 403, 500):
                            error_text = await resp.text()
                            raise BinanceAPIError(f"{resp.status} - {error_text}")
                        else:
                            error_text = await resp.text()
                            raise BinanceWebSocketError(f"{resp.status} - {error_text}")
            except Exception as e:
                logger.error(f"❌ Listen key retrieval failed: {e}", exc_info=True)
                await asyncio.sleep(2 ** attempt)
        raise BinanceWebSocketError("Failed to obtain listen key after retries")

    async def _keepalive_listen_key(self, listen_key: str, futures: bool = False) -> None:
        endpoint = '/fapi/v1/listenKey' if futures else '/api/v3/userDataStream'
        url = (FUTURES_URL if futures else BASE_URL) + endpoint
        headers = {'X-MBX-APIKEY': self.config.api_key} if self.config.api_key else {}

        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    params = {'listenKey': listen_key}
                    async with session.put(url, headers=headers, params=params) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.warning(f"⚠️ Listen key keepalive failed: {resp.status} - {text}")
                await asyncio.sleep(self.config.keepalive_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Listen key keepalive error: {e}", exc_info=True)
                await asyncio.sleep(60)

    # --------------------
    # COMMON STREAM SUBSCRIPTIONS
    # --------------------
    def _validate_symbol(self, symbol: str) -> None:
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid trading symbol")

    def _validate_interval(self, interval: str) -> None:
        if interval not in ["1s", "3s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]:
            raise ValueError(f"Invalid interval: {interval}")

    def _validate_depth(self, levels: int) -> None:
        if levels not in [5, 10, 20]:
            raise ValueError(f"Invalid depth levels: {levels}")

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Dict[str, Any]], Awaitable[None]], futures: bool = False, interval: str = '1s') -> str:
        self._validate_symbol(symbol)
        self._validate_interval(interval)
        stream = f"{symbol.lower()}@ticker_{interval}"
        return await self.connect([stream], callback, futures)

    async def subscribe_kline(self, symbol: str, interval: str, callback: Callable[[Dict[str, Any]], Awaitable[None]], futures: bool = False) -> str:
        self._validate_symbol(symbol)
        self._validate_interval(interval)
        stream = f"{symbol.lower()}@kline_{interval}"
        return await self.connect([stream], callback, futures)

    async def subscribe_depth(self, symbol: str, callback: Callable[[Dict[str, Any]], Awaitable[None]], futures: bool = False, levels: int = 20) -> str:
        self._validate_symbol(symbol)
        self._validate_depth(levels)
        stream = f"{symbol.lower()}@depth{levels}@100ms"
        return await self.connect([stream], callback, futures)

    async def subscribe_agg_trade(self, symbol: str, callback: Callable[[Dict[str, Any]], Awaitable[None]], futures: bool = False) -> str:
        self._validate_symbol(symbol)
        stream = f"{symbol.lower()}@aggTrade"
        return await self.connect([stream], callback, futures)

    # --------------------
    # STATUS & UTILS
    # --------------------
    def get_status(self) -> Dict[str, Any]:
        return {
            'active_connections': len(self.connections),
            'running': self.running,
            'subscriptions': {k: len(v) for k, v in self.subscriptions.items()}
        }

    def is_connected(self, connection_id: str) -> bool:
        return connection_id in self.connections and self.connections[connection_id]['running'] and self.running

    # --------------------
    # ASYNC CONTEXT MANAGER
    # --------------------
    async def __aenter__(self) -> 'BinanceWebSocketManager':
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close_all()

# --------------------
# GLOBAL INSTANCE
# --------------------
async def get_websocket_manager(
    api_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    testnet: bool = False,
    router: Optional[Router] = None
) -> BinanceWebSocketManager:
    if BinanceWebSocketManager._instance is None:
        BinanceWebSocketManager._instance = BinanceWebSocketManager(
            api_key=api_key,
            secret_key=secret_key,
            testnet=testnet,
            router=router
        )
    return BinanceWebSocketManager._instance
