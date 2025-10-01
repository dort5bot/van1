# utils/binance/binance_request.py
"""
Enhanced Binance HTTP Client
- Async aiohttp client with retry, rate limiting, metrics
- Public + Private endpoint support
- Dynamic weight handling per endpoint
- Detailed exception handling with specific error codes
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
from typing import Dict, Any, Optional, Union

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
