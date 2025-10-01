# utils/binance/binance_request.py
"""
Enhanced Binance HTTP Client
Varsayılan olarak bot_api_key, bot_api_secret tut
get/post çağrılarında api_key/api_secret verilmemişse bot key’leri kullan

- Async aiohttp client with retry, rate limiting, metrics
- Public + Private endpoint support
- Dynamic weight handling per endpoint
- Detailed exception handling with specific error codes
Public ve Private endpoint destekli, imzalama ve API anahtarı ile kimlik doğrulama var.
Dinamik ağırlık (weight) takibi ve rate limiting uygulanmış. (Binance API her endpoint için farklı weight verir, bu kod bunu yönetiyor.)
Retry mantığı ve exponential backoff var. (İstek başarısız olursa tekrar deniyor)
Timeout ve detaylı hata yönetimi var. (Farklı Binance hata kodlarına özel istisnalar kullanıyor)
Aiohttp connector limit ayarları ile eşzamanlı bağlantı sınırlandırması yapılabiliyor.
Metrics (istatistik) toplama için ekstra modül var (MetricsManager) ki bu gerçek kullanımlarda faydalı.
WebSocket sınıfı
"""

import aiohttp
import asyncio
import time
import logging
import hashlib
import hmac
import urllib.parse
import json
import platform
from typing import Dict, Any, Optional, Union, Callable, Awaitable

from .binance_constants import BASE_URL, FUTURES_URL, DEFAULT_CONFIG, ENDPOINT_WEIGHT_MAP
from .binance_exceptions import (
    BinanceAPIError, BinanceRequestError, BinanceRateLimitError,
    BinanceAuthenticationError, BinanceTimeoutError,
    BinanceOrderRejectedError, BinanceInvalidSymbolError
)
from .binance_metrics import AdvancedMetrics as MetricsManager


logger = logging.getLogger(__name__)

#from .binance_request import BinanceRequest
#alias from .binance_request import BinanceHTTPClient as BinanceRequest
class BinanceHTTPClient:
    """
    Async HTTP client for Binance API with retry logic, dynamic rate limiting, 
    detailed error handling, and optional metrics tracking.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fapi_url: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        session: Optional[aiohttp.ClientSession] = None
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url or BASE_URL
        self.fapi_url = fapi_url or FUTURES_URL
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._session_provided_externally = session is not None
        self._session = session
        self._last_request_time = 0
        self._min_request_interval = 1.0 / self.config.get("requests_per_second", 10)
        self._weight_used = 0
        self._weight_reset_time = time.time() + 60
        self._weight_limit = 1200
        self.metrics = MetricsManager.get_instance()
        logger.info(
            f"✅ BinanceHTTPClient initialized - Base URL: {self.base_url}, FAPI URL: {self.fapi_url}, "
            f"Rate Limit: {self.config.get('requests_per_second')} req/s"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.config["timeout"],
                connect=self.config.get("connect_timeout", 5),
                sock_connect=self.config.get("sock_connect_timeout", 5),
                sock_read=self.config.get("sock_read_timeout", 10)
            )
            connector = aiohttp.TCPConnector(
                limit=self.config.get("connector_limit", 100),
                limit_per_host=self.config.get("connector_limit_per_host", 20),
                enable_cleanup_closed=True
            )
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
            logger.debug("Created new aiohttp ClientSession")
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed and not self._session_provided_externally:
            await self._session.close()
            self._session = None
            logger.info("✅ BinanceHTTPClient session closed")

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        if not self.secret_key:
            raise BinanceAuthenticationError("Secret key required for signed requests")
        query_string = urllib.parse.urlencode(params)
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _add_auth_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        if self.api_key:
            headers['X-MBX-APIKEY'] = self.api_key
        return headers

    async def _rate_limit(self, endpoint: Optional[str] = None) -> None:
        # Dynamic weight check
        endpoint_weight = ENDPOINT_WEIGHT_MAP.get(endpoint, 1) if endpoint else 1
        current_time = time.time()
        if time.time() > self._weight_reset_time:
            self._weight_used = 0
            self._weight_reset_time = current_time + 60
            await self.metrics.reset_rate_limit()
        if self._weight_used + endpoint_weight > self._weight_limit:
            sleep_time = max(0, self._weight_reset_time - current_time)
            logger.warning(f"Weight limit reached, sleeping for {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)
            self._weight_used = 0
            self._weight_reset_time = time.time() + 60

        # Minimum request interval
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        self._last_request_time = time.time()

    async def _handle_rate_limit(self, response_headers: Dict[str, str]) -> None:
        weight = response_headers.get('X-MBX-USED-WEIGHT', '0')
        weight_limit = response_headers.get('X-MBX-WEIGHT-LIMIT')
        try:
            self._weight_used += int(weight)
            if weight_limit:
                self._weight_limit = int(weight_limit)
            await self.metrics.record_rate_limit(int(weight))
        except ValueError:
            logger.warning(f"Failed parsing rate headers: {weight}, {weight_limit}")

    async def _handle_error(self, status_code: int, error_data: str, response_time: float) -> None:
        try:
            error_json = json.loads(error_data) if error_data else {}
            code = error_json.get('code', -1)
            msg = error_json.get('msg', 'Unknown error')
            await self.metrics.record_request(False, response_time, f"api_error_{code}")

            # Map specific Binance error codes to exceptions
            if status_code == 429:
                raise BinanceRateLimitError(msg, code, error_json)
            elif status_code == 401:
                raise BinanceAuthenticationError(msg, code, error_json)
            elif code in [-2010, -2011]:
                raise BinanceOrderRejectedError(msg, code, error_json)
            elif code == -1121:
                raise BinanceInvalidSymbolError(msg, code, error_json)
            elif status_code >= 400:
                raise BinanceAPIError(msg, code, error_json)
            else:
                raise BinanceRequestError(f"HTTP {status_code}: {msg}")
        except (ValueError, json.JSONDecodeError):
            await self.metrics.record_request(False, response_time, "invalid_response")
            raise BinanceRequestError(f"HTTP {status_code}: Invalid response: {error_data}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        futures: bool = False,
        retries: Optional[int] = None,
        timeout: Optional[float] = None
    ) -> Any:
        retries = retries if retries is not None else self.config["max_retries"]
        params = params or {}
        if not isinstance(params, dict):
            raise BinanceRequestError("Params must be a dict")

        base_url = self.fapi_url if futures else self.base_url
        url = f"{base_url}{endpoint}"
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': f'BinancePythonClient/1.0 (Python {platform.python_version()})'
        }
        if signed:
            params = params.copy()
            params['timestamp'] = int(time.time() * 1000)
            params.setdefault('recvWindow', self.config["recv_window"])
            params['signature'] = self._generate_signature(params)
        headers = self._add_auth_headers(headers)

        last_exception = None
        for attempt in range(retries + 1):
            try:
                await self._rate_limit(endpoint)
                session = await self._get_session()
                request_params = {
                    'method': method,
                    'url': url,
                    'headers': headers,
                    'params': params if method == 'GET' else None,
                    'timeout': timeout or self.config['timeout']
                }
                if method != 'GET':
                    if signed:
                        request_params['data'] = urllib.parse.urlencode(params)
                    else:
                        request_params['json'] = params

                start_time = time.time()
                async with session.request(**request_params) as response:
                    response_time = time.time() - start_time
                    await self._handle_rate_limit(response.headers)
                    if response.status == 200:
                        data = await response.json()
                        await self.metrics.record_request(True, response_time)
                        return data
                    error_text = await response.text()
                    await self._handle_error(response.status, error_text, response_time)

            except asyncio.TimeoutError:
                last_exception = BinanceTimeoutError(f"Request timeout after {timeout}s")
            except aiohttp.ClientError as e:
                last_exception = BinanceRequestError(f"HTTP client error: {e}")
            except Exception as e:
                last_exception = BinanceRequestError(f"Unexpected error: {e}")

            if attempt < retries:
                delay = self.config["retry_delay"] * (2 ** attempt)
                logger.warning(f"Retry {attempt+1}/{retries} for {method} {endpoint} after {delay:.2f}s")
                await asyncio.sleep(delay)
            else:
                raise last_exception

    # Public request helpers
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
                  signed: bool = False, futures: bool = False, timeout: Optional[float] = None) -> Any:
        return await self._request('GET', endpoint, params, signed, futures, timeout=timeout)

    async def post(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
                   signed: bool = False, futures: bool = False, timeout: Optional[float] = None) -> Any:
        return await self._request('POST', endpoint, params, signed, futures, timeout=timeout)

    async def put(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
                  signed: bool = False, futures: bool = False, timeout: Optional[float] = None) -> Any:
        return await self._request('PUT', endpoint, params, signed, futures, timeout=timeout)

    async def delete(self, endpoint: str, params: Optional[Dict[str, Any]] = None,
                     signed: bool = False, futures: bool = False, timeout: Optional[float] = None) -> Any:
        return await self._request('DELETE', endpoint, params, signed, futures, timeout=timeout)

    async def health_check(self) -> bool:
        try:
            await self.get('/api/v3/ping', timeout=5)
            return True
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def get_weight_usage(self) -> int:
        return self._weight_used

    def get_weight_remaining(self) -> int:
        return max(0, self._weight_limit - self._weight_used)

    def get_weight_limit(self) -> int:
        return self._weight_limit

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()



#

class BinanceWSClient:
    """
    Async Binance WebSocket client using aiohttp.
    Supports connect, disconnect, send, receive and auto-reconnect.

    Usage:
        async with BinanceWSClient() as ws:
            await ws.connect()
            await ws.subscribe(['btcusdt@ticker'])
            async for message in ws:
                print(message)
    """

    BASE_WS_URL = "wss://stream.binance.com:9443/ws"
    BASE_WS_FUTURES_URL = "wss://fstream.binance.com/ws"

    def __init__(
        self,
        futures: bool = False,
        api_key: Optional[str] = None,
        reconnect_interval: int = 5,
        on_message: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.futures = futures
        self.api_key = api_key  # Binance WS genellikle API key istemez, ama private streamler için gerekebilir
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._reconnect_interval = reconnect_interval
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._on_message = on_message
        self._subscribed_streams = set()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            logger.debug("Created new aiohttp ClientSession for WebSocket")
        return self._session

    async def connect(self):
        """
        Connect to Binance WebSocket endpoint.
        """
        url = self.BASE_WS_FUTURES_URL if self.futures else self.BASE_WS_URL

        # If you want to open combined streams (multiple streams in one WS connection),
        # URL is: wss://stream.binance.com:9443/stream?streams=stream1/stream2
        # Here we open a basic connection, subscribe later.

        session = await self._get_session()
        self._ws = await session.ws_connect(url)
        self._connected = True
        self._stop_event.clear()
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info(f"Connected to Binance WebSocket at {url}")

    async def disconnect(self):
        """
        Close WebSocket connection and session.
        """
        self._connected = False
        self._stop_event.set()
        if self._receive_task:
            await self._receive_task
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("WebSocket connection closed")
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("aiohttp session closed")

    async def _receive_loop(self):
        """
        Loop to receive messages and call the callback.
        Reconnects automatically if connection drops.
        """
        while not self._stop_event.is_set():
            try:
                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if self._on_message:
                            await self._on_message(data)
                        else:
                            logger.debug(f"WS Message received: {data}")
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.warning("WebSocket closed by server")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"WebSocket error: {msg.data}")
                        break
                # If we get here, WS closed or errored
                if not self._stop_event.is_set():
                    logger.warning("WebSocket connection lost, reconnecting...")
                    await self._reconnect()
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                if not self._stop_event.is_set():
                    await asyncio.sleep(self._reconnect_interval)
                    await self._reconnect()

    async def _reconnect(self):
        """
        Close existing connection and try reconnecting.
        """
        if self._ws and not self._ws.closed:
            await self._ws.close()
        await asyncio.sleep(self._reconnect_interval)
        await self.connect()
        # Resubscribe to streams if any
        if self._subscribed_streams:
            await self.subscribe(list(self._subscribed_streams))

    async def send(self, message: dict):
        """
        Send a JSON message to WebSocket.
        """
        if not self._connected or self._ws is None:
            raise ConnectionError("WebSocket is not connected")
        await self._ws.send_json(message)
        logger.debug(f"Sent WS message: {message}")

    async def subscribe(self, streams: list[str]):
        """
        Subscribe to one or more streams.
        Example streams: ['btcusdt@ticker', 'ethusdt@depth']

        Binance expects subscribe message:
        {
          "method": "SUBSCRIBE",
          "params": ["btcusdt@ticker", "ethusdt@depth"],
          "id": 1
        }
        """
        streams = [s.lower() for s in streams]
        self._subscribed_streams.update(streams)
        msg = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1
        }
        await self.send(msg)
        logger.info(f"Subscribed to streams: {streams}")

    async def unsubscribe(self, streams: list[str]):
        """
        Unsubscribe from streams.
        """
        streams = [s.lower() for s in streams]
        for s in streams:
            self._subscribed_streams.discard(s)
        msg = {
            "method": "UNSUBSCRIBE",
            "params": streams,
            "id": 1
        }
        await self.send(msg)
        logger.info(f"Unsubscribed from streams: {streams}")

    def __aiter__(self):
        """
        Async iterator over incoming messages (if no callback provided).
        """
        if self._on_message is not None:
            raise RuntimeError("Cannot use iterator and callback simultaneously")
        return self._message_generator()

    async def _message_generator(self):
        """
        Yalnızca __aiter__ için mesajları queue'ya koyup yield eder.
        """
        queue = asyncio.Queue()

        async def on_message(data):
            await queue.put(data)

        self._on_message = on_message

        while True:
            msg = await queue.get()
            yield msg

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

