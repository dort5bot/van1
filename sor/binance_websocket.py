# utils/binance/binance_websocket.py
"""
v8
Enhanced Binance WebSocket Client
- Combined stream support  
- Exponential backoff reconnection
- Ping/pong mechanism
- Better error handling and callbacks
- Message queue for async iteration
- Backward compatible with existing code
"""

import aiohttp
import asyncio
import time
import json
import logging
from typing import Dict, Any, Optional, List, Callable, Awaitable, AsyncGenerator, Union
from urllib.parse import urlencode

from .binance_exceptions import BinanceWebSocketError

logger = logging.getLogger(__name__)

class BinanceWSClient:
    """
    Async Binance WebSocket client using aiohttp.
    Supports connect, disconnect, send, receive and auto-reconnect.

    Usage:
        # Eski kullanım (backward compatible)
        async with BinanceWSClient() as ws:
            await ws.connect()
            await ws.subscribe(['btcusdt@ticker'])
            async for message in ws:
                print(message)

        # Yeni kullanım (callback'lerle)
        async def handle_message(msg):
            print(msg)
            
        ws = BinanceWSClient(on_message=handle_message)
        await ws.connect()
        await ws.subscribe(['btcusdt@ticker'])
    """

    BASE_WS_URL = "wss://stream.binance.com:9443/ws"
    BASE_WS_FUTURES_URL = "wss://fstream.binance.com/ws"
    COMBINED_STREAM_URL = "wss://stream.binance.com:9443/stream"
    COMBINED_FUTURES_STREAM_URL = "wss://fstream.binance.com/stream"

    def __init__(
        self,
        futures: bool = False,
        api_key: Optional[str] = None,
        reconnect_interval: int = 5,
        max_reconnect_attempts: int = 10,
        ping_interval: int = 30,
        on_message: Optional[Callable[[dict], Awaitable[None]]] = None,
        on_error: Optional[Callable[[Exception], Awaitable[None]]] = None,
        on_connect: Optional[Callable[[], Awaitable[None]]] = None,
        on_disconnect: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        # Eski parametreler korundu
        self.futures = futures
        self.api_key = api_key
        
        # Yeni parametreler
        self._reconnect_interval = reconnect_interval
        self._max_reconnect_attempts = max_reconnect_attempts
        self._ping_interval = ping_interval
        
        # Callbacks (yeni)
        self._on_message = on_message
        self._on_error = on_error
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        
        # Internal state (eski + yeni)
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._reconnect_attempts = 0
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._subscribed_streams = set()
        self._message_queue = asyncio.Queue()
        self._last_message_time = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
            logger.debug("Created new aiohttp ClientSession for WebSocket")
        return self._session

    async def connect(self):
        """
        Connect to Binance WebSocket endpoint.
        Eski method signature korundu, içeriği geliştirildi.
        """
        try:
            # Yeni: Combined stream URL desteği
            base_url = self.BASE_WS_FUTURES_URL if self.futures else self.BASE_WS_URL
            url = base_url
            
            if self._subscribed_streams:
                streams_param = '/'.join(self._subscribed_streams)
                combined_url = self.COMBINED_FUTURES_STREAM_URL if self.futures else self.COMBINED_STREAM_URL
                url = f"{combined_url}?streams={streams_param}"

            session = await self._get_session()
            
            # Yeni: heartbeat ve autoping eklendi
            self._ws = await session.ws_connect(
                url,
                heartbeat=self._ping_interval,
                autoping=True
            )
            
            self._connected = True
            self._reconnect_attempts = 0  # Yeni: reconnect sayacı sıfırlandı
            self._stop_event.clear()
            
            # Yeni: Ping loop eklendi
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())
            
            logger.info(f"✅ Connected to Binance WebSocket at {url}")
            
            # Yeni: on_connect callback
            if self._on_connect:
                await self._on_connect()
                
            return True
            
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            # Yeni: on_error callback
            if self._on_error:
                await self._on_error(e)
            return False

    async def disconnect(self):
        """
        Close WebSocket connection and session.
        Eski method signature korundu, içeriği geliştirildi.
        """
        self._connected = False
        self._stop_event.set()
        
        # Yeni: Ping task'ı durdur
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

        # Receive task'ı durdur
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # WebSocket'i kapat
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("WebSocket connection closed")

        # Session'ı kapat
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("aiohttp session closed")
            
        # Yeni: on_disconnect callback
        if self._on_disconnect:
            await self._on_disconnect()

    async def _ping_loop(self):
        """Yeni: Send periodic ping messages to keep connection alive."""
        while self._connected and not self._stop_event.is_set():
            try:
                await asyncio.sleep(self._ping_interval)
                if self._ws and not self._ws.closed:
                    await self._ws.ping()
                    logger.debug("Sent WebSocket ping")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ping error: {e}")
                break

    async def _receive_loop(self):
        """
        Loop to receive messages and call the callback.
        Reconnects automatically if connection drops.
        Eski fonksiyon geliştirildi.
        """
        while not self._stop_event.is_set():
            try:
                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        self._last_message_time = time.time()  # Yeni: son mesaj zamanı
                        
                        # Yeni: callback veya queue'ya ekle
                        if self._on_message:
                            await self._on_message(data)
                        else:
                            await self._message_queue.put(data)
                            
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.warning("WebSocket closed by server")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"WebSocket error: {msg.data}")
                        break
                    elif msg.type == aiohttp.WSMsgType.PONG:
                        logger.debug("Received WebSocket pong")  # Yeni: pong log
                        
                # Eski reconnect mantığı geliştirildi
                if not self._stop_event.is_set():
                    await self._reconnect()
                    
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                # Yeni: on_error callback
                if self._on_error:
                    await self._on_error(e)
                    
                if not self._stop_event.is_set():
                    await self._reconnect()

    async def _reconnect(self):
        """
        Yeni: Exponential backoff ile akıllı yeniden bağlanma
        Eski basit reconnect yerine gelişmiş versiyon
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Max reconnection attempts reached")
            if self._on_error:
                await self._on_error(ConnectionError("Max reconnection attempts reached"))
            return

        self._reconnect_attempts += 1
        # Yeni: Exponential backoff
        delay = min(self._reconnect_interval * (2 ** (self._reconnect_attempts - 1)), 300)
        
        logger.warning(f"🔄 Reconnecting in {delay}s (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
        await asyncio.sleep(delay)
        
        try:
            await self.connect()
            # Yeni: Önceki stream'leri yeniden subscribe et
            if self._subscribed_streams:
                await self.subscribe(list(self._subscribed_streams))
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")

    async def send(self, message: dict):
        """
        Send a JSON message to WebSocket.
        Eski method signature korundu, hata yönetimi geliştirildi.
        """
        if not self._connected or self._ws is None:
            raise ConnectionError("WebSocket is not connected")
        
        try:
            await self._ws.send_json(message)
            logger.debug(f"Sent WS message: {message}")
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
            # Yeni: on_error callback
            if self._on_error:
                await self._on_error(e)
            raise

    async def subscribe(self, streams: list[str]):
        """
        Subscribe to one or more streams.
        Eski method signature korundu, combined stream desteği eklendi.
        """
        streams = [s.lower() for s in streams]
        self._subscribed_streams.update(streams)
        
        msg = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": int(time.time() * 1000)  # Yeni: unique ID
        }
        
        await self.send(msg)
        logger.info(f"✅ Subscribed to streams: {streams}")

    async def unsubscribe(self, streams: list[str]):
        """
        Unsubscribe from streams.
        Eski method signature korundu.
        """
        streams = [s.lower() for s in streams]
        for s in streams:
            self._subscribed_streams.discard(s)
            
        msg = {
            "method": "UNSUBSCRIBE",
            "params": streams,
            "id": int(time.time() * 1000)  # Yeni: unique ID
        }
        
        await self.send(msg)
        logger.info(f"Unsubscribed from streams: {streams}")

    # Yeni methodlar - Backward compatibility bozmuyor
    async def list_subscriptions(self) -> List[str]:
        """Yeni: Get list of currently subscribed streams."""
        return list(self._subscribed_streams)

    def is_connected(self) -> bool:
        """Yeni: Check if WebSocket is connected."""
        return self._connected and self._ws and not self._ws.closed

    def get_last_message_time(self) -> float:
        """Yeni: Get timestamp of last received message."""
        return self._last_message_time

    def get_reconnect_attempts(self) -> int:
        """Yeni: Get current reconnect attempt count."""
        return self._reconnect_attempts

    # Eski async iterator desteği korundu
    def __aiter__(self):
        """
        Async iterator over incoming messages (if no callback provided).
        Eski method aynen korundu.
        """
        if self._on_message is not None:
            raise RuntimeError("Cannot use iterator and callback simultaneously")
        return self._message_generator()

    async def _message_generator(self):
        """
        Yalnızca __aiter__ için mesajları queue'ya koyup yield eder.
        Eski method geliştirildi - queue kullanılıyor.
        """
        while self._connected or not self._message_queue.empty():
            try:
                # Yeni: timeout ile daha güvenli
                message = await asyncio.wait_for(
                    self._message_queue.get(), 
                    timeout=1.0
                )
                yield message
                self._message_queue.task_done()
            except asyncio.TimeoutError:
                if not self._connected:
                    break
                continue

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


# Yeni: WSManager eklendi - Backward compatibility bozmuyor
class BinanceWSManager:
    """Manager for multiple WebSocket connections."""
    
    def __init__(self):
        self._connections: List[BinanceWSClient] = []
    
    async def create_connection(
        self,
        streams: List[str],
        futures: bool = False,
        on_message: Optional[Callable[[dict], Awaitable[None]]] = None,
        **kwargs
    ) -> BinanceWSClient:
        """Create and setup a WebSocket connection."""
        ws = BinanceWSClient(futures=futures, on_message=on_message, **kwargs)
        await ws.connect()
        if streams:
            await ws.subscribe(streams)
        self._connections.append(ws)
        return ws
    
    async def close_all(self):
        """Close all WebSocket connections."""
        for ws in self._connections:
            if ws.is_connected():
                await ws.disconnect()
        self._connections.clear()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()