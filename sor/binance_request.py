# utils/binance/binance_request.py
import aiohttp
import asyncio
import time
import logging
import hashlib
import hmac
import urllib.parse
import json
import platform
from typing import Dict, Any, Optional, Union, Callable, Awaitable, List
from contextlib import asynccontextmanager

from .binance_constants import BASE_URL, FUTURES_URL, DEFAULT_CONFIG, ENDPOINT_WEIGHT_MAP
from .binance_exceptions import (
    BinanceAPIError, BinanceRequestError, BinanceRateLimitError,
    BinanceAuthenticationError, BinanceTimeoutError,
    BinanceOrderRejectedError, BinanceInvalidSymbolError
)
from .binance_metrics import AdvancedMetrics as MetricsManager

logger = logging.getLogger(__name__)

class BinanceHTTPClient:
    """
    Enhanced async HTTP client for Binance API with retry logic, dynamic rate limiting,
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
        self._concurrent_requests = 0
        self._max_concurrent_requests = self.config.get("max_concurrent_requests", 10)
        self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        self.metrics = MetricsManager.get_instance()
        
        logger.info(
            f"✅ BinanceHTTPClient initialized - Base URL: {self.base_url}, FAPI URL: {self.fapi_url}, "
            f"Rate Limit: {self.config.get('requests_per_second')} req/s, "
            f"Max Concurrent: {self._max_concurrent_requests}"
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
                enable_cleanup_closed=True,
                keepalive_timeout=30  # Keep-alive timeout eklendi
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout, 
                connector=connector,
                headers={
                    'User-Agent': f'BinancePythonClient/1.0 (Python {platform.python_version()})'
                }
            )
            logger.debug("Created new aiohttp ClientSession")
        return self._session

    async def close(self) -> None:
        """Close session and cleanup resources."""
        if self._session and not self._session.closed and not self._session_provided_externally:
            await self._session.close()
            self._session = None
            logger.info("✅ BinanceHTTPClient session closed")

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """Generate HMAC SHA256 signature for private endpoints."""
        if not self.secret_key:
            raise BinanceAuthenticationError("Secret key required for signed requests")
        
        # Parametreleri sırala ve encode et
        query_string = urllib.parse.urlencode(sorted(params.items()))
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _add_auth_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Add authentication headers to request."""
        if self.api_key:
            headers['X-MBX-APIKEY'] = self.api_key
        return headers

    async def _rate_limit(self, endpoint: Optional[str] = None) -> None:
        """Apply rate limiting based on endpoint weight and request interval."""
        # Endpoint weight kontrolü
        endpoint_weight = ENDPOINT_WEIGHT_MAP.get(endpoint, 1) if endpoint else 1
        current_time = time.time()
        
        # Weight reset kontrolü
        if current_time > self._weight_reset_time:
            self._weight_used = 0
            self._weight_reset_time = current_time + 60
            await self.metrics.reset_rate_limit()
        
        # Weight limit kontrolü
        if self._weight_used + endpoint_weight > self._weight_limit:
            sleep_time = max(0, self._weight_reset_time - current_time)
            logger.warning(f"⚠️ Weight limit reached, sleeping for {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)
            self._weight_used = 0
            self._weight_reset_time = time.time() + 60

        # Minimum request interval kontrolü
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        
        self._last_request_time = time.time()

    async def _handle_rate_limit(self, response_headers: Dict[str, str]) -> None:
        """Update rate limit metrics from response headers."""
        try:
            weight = int(response_headers.get('X-MBX-USED-WEIGHT', '0'))
            weight_limit = response_headers.get('X-MBX-WEIGHT-LIMIT')
            
            self._weight_used += weight
            
            if weight_limit:
                self._weight_limit = int(weight_limit)
            
            # Order count limits
            order_count_1s = response_headers.get('X-MBX-ORDER_COUNT-1S')
            order_count_1m = response_headers.get('X-MBX-ORDER_COUNT-1M')
            
            if order_count_1s:
                await self.metrics.record_order_limit('1s', int(order_count_1s))
            if order_count_1m:
                await self.metrics.record_order_limit('1m', int(order_count_1m))
                
            await self.metrics.record_rate_limit_increment(weight_1m_inc=weight)

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed parsing rate limit headers: {e}")

    async def _handle_error(self, status_code: int, error_data: str, response_time: float) -> None:
        """Handle API errors and map to specific exceptions."""
        try:
            error_json = json.loads(error_data) if error_data else {}
            code = error_json.get('code', -1)
            msg = error_json.get('msg', 'Unknown error')
            
            await self.metrics.record_request(False, response_time, f"api_error_{code}")

            # Binance error code mapping
            error_mappings = {
                429: BinanceRateLimitError,
                401: BinanceAuthenticationError,
                418: BinanceAPIError,  # IP banned
                419: BinanceAPIError,  # API banned
            }
            
            specific_codes = {
                -2010: BinanceOrderRejectedError,
                -2011: BinanceOrderRejectedError,
                -1121: BinanceInvalidSymbolError,
                -1013: BinanceInvalidSymbolError,
                -1021: BinanceAPIError,  # Timestamp error
                -1100: BinanceRequestError,  # Illegal characters
            }
            
            if status_code in error_mappings:
                raise error_mappings[status_code](msg, code, error_json)
            elif code in specific_codes:
                raise specific_codes[code](msg, code, error_json)
            elif status_code >= 400:
                raise BinanceAPIError(msg, code, error_json)
            else:
                raise BinanceRequestError(f"HTTP {status_code}: {msg}")
                
        except (ValueError, json.JSONDecodeError):
            await self.metrics.record_request(False, response_time, "invalid_response")
            raise BinanceRequestError(f"HTTP {status_code}: Invalid response: {error_data}")

    @asynccontextmanager
    async def _concurrent_request_limiter(self):
        """Limit concurrent requests using semaphore."""
        async with self._request_semaphore:
            self._concurrent_requests += 1
            try:
                yield
            finally:
                self._concurrent_requests -= 1

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
        """Internal request method with retry logic and error handling."""
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

        # Signature for private endpoints
        if signed:
            params = params.copy()
            params['timestamp'] = int(time.time() * 1000)
            params.setdefault('recvWindow', self.config["recv_window"])
            params['signature'] = self._generate_signature(params)
        
        headers = self._add_auth_headers(headers)

        last_exception = None
        for attempt in range(retries + 1):
            try:
                async with self._concurrent_request_limiter():
                    await self._rate_limit(endpoint)
                    session = await self._get_session()
                    
                    request_params = {
                        'method': method.upper(),
                        'url': url,
                        'headers': headers,
                    }

                    # GET vs POST parametreleri
                    if method.upper() == 'GET':
                        request_params['params'] = params
                    else:
                        if signed:
                            request_params['data'] = urllib.parse.urlencode(params)
                            headers['Content-Type'] = 'application/x-www-form-urlencoded'
                        else:
                            request_params['json'] = params

                    # Timeout ayarı
                    request_timeout = aiohttp.ClientTimeout(total=timeout or self.config['timeout'])
                    request_params['timeout'] = request_timeout

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
            except (BinanceAPIError, BinanceAuthenticationError, BinanceRateLimitError) as e:
                # Bu hataları tekrar deneme (bazı durumlar hariç)
                if isinstance(e, BinanceRateLimitError) and attempt < retries:
                    sleep_time = min(60, self.config["retry_delay"] * (2 ** attempt))
                    logger.warning(f"Rate limited, sleeping for {sleep_time}s")
                    await asyncio.sleep(sleep_time)
                    continue
                raise e
            except Exception as e:
                last_exception = BinanceRequestError(f"Unexpected error: {e}")

            # Retry logic
            if attempt < retries and last_exception:
                delay = self.config["retry_delay"] * (2 ** attempt)
                logger.warning(f"🔄 Retry {attempt+1}/{retries} for {method} {endpoint} after {delay:.2f}s")
                await asyncio.sleep(delay)
            elif last_exception:
                raise last_exception

    # Public request methods
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

    # Utility methods
    async def health_check(self) -> Dict[str, Any]:
        """Check API connectivity and return detailed health status."""
        try:
            start_time = time.time()
            await self.get('/api/v3/ping', timeout=5)
            response_time = time.time() - start_time
            
            return {
                'status': 'healthy',
                'response_time': response_time,
                'weight_used': self._weight_used,
                'weight_remaining': self.get_weight_remaining(),
                'concurrent_requests': self._concurrent_requests
            }
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return {
                'status': 'unhealthy',
                'error': str(e),
                'weight_used': self._weight_used,
                'concurrent_requests': self._concurrent_requests
            }

    def get_weight_usage(self) -> int:
        return self._weight_used

    def get_weight_remaining(self) -> int:
        return max(0, self._weight_limit - self._weight_used)

    def get_weight_limit(self) -> int:
        return self._weight_limit

    def get_concurrent_requests(self) -> int:
        return self._concurrent_requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()