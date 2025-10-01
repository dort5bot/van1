# utils/binance/binance_websocket.py
"""
v6-multi (2+ kullanıcı)
WebSocket API ile tam uyumlu
REST API (trade, order, account, futures işlemleri)-Yok
Çok kullanıcılı WebSocket manager
- Her kullanıcı kendi API key'ini kullanır
- Public işlemler için bot API key'i kullanılır
- Kullanıcı bazlı connection yönetimi
"""

import asyncio
import json
import time
import logging

import hmac
import uuid
import aiohttp
import websockets

from typing import Dict, List, Any, Optional, Callable, Set, Union, Awaitable, Tuple
from dataclasses import dataclass
from enum import Enum
import hashlib

from .binance_constants import BASE_URL, FUTURES_URL
from .binance_exceptions import BinanceWebSocketError, BinanceAPIError
from ..apikey_manager import APIKeyManager

logger = logging.getLogger(__name__)

class StreamType(Enum):
    SPOT = "spot"
    FUTURES = "futures"
    USER_DATA = "user_data"

@dataclass
class UserWebSocketConfig:
    user_id: int
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    futures: bool = False
    testnet: bool = False

@dataclass
class RESTApiConfig:
    """REST API konfigürasyon sınıfı"""
    api_key: str
    secret_key: str
    futures: bool = False
    testnet: bool = False

class BinanceRESTAPI:
    """
    Çok kullanıcılı Binance REST API sınıfı
    HMAC SHA256 imzalı request'ler
    Rate limit ve hata yönetimi
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limits: Dict[str, Dict[str, Any]] = {}
        
    async def initialize(self):
        """HTTP session başlat"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close(self):
        """HTTP session kapat"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def _get_base_url(self, config: RESTApiConfig) -> str:
        """Base URL belirle"""
        if config.testnet:
            return "https://testnet.binancefuture.com" if config.futures else "https://testnet.binance.vision"
        else:
            return "https://fapi.binance.com" if config.futures else "https://api.binance.com"
    
    def _sign_payload(self, payload: Dict[str, Any], secret_key: str) -> str:
        """HMAC SHA256 ile payload imzala"""
        query_string = '&'.join([f"{key}={value}" for key, value in payload.items()])
        return hmac.new(
            secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _create_secure_payload(self, params: Dict[str, Any], config: RESTApiConfig) -> Dict[str, Any]:
        """Güvenli payload oluştur (timestamp ve signature ekle)"""
        payload = params.copy()
        payload['timestamp'] = int(time.time() * 1000)
        payload['recvWindow'] = 5000
        
        # Signature oluştur
        signature = self._sign_payload(payload, config.secret_key)
        payload['signature'] = signature
        
        return payload
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        config: RESTApiConfig,
        params: Optional[Dict[str, Any]] = None,
        retries: int = 3
    ) -> Dict[str, Any]:
        """
        HTTP request gönder
        
        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint
            config: Kullanıcı konfigürasyonu
            params: Request parametreleri
            retries: Maksimum yeniden deneme sayısı
        
        Returns:
            API response
            
        Raises:
            BinanceAPIError: API hatası durumunda
        """
        await self.initialize()
        
        if params is None:
            params = {}
        
        base_url = self._get_base_url(config)
        url = f"{base_url}{endpoint}"
        
        headers = {
            'X-MBX-APIKEY': config.api_key,
            'Content-Type': 'application/json'
        }
        
        last_exception = None
        
        for attempt in range(retries):
            try:
                # Rate limit kontrolü
                await self._check_rate_limit(endpoint)
                
                # Secure payload oluştur (private endpoint'ler için)
                is_private = endpoint not in [
                    '/api/v3/ping', '/api/v3/time', '/api/v3/exchangeInfo',
                    '/fapi/v1/ping', '/fapi/v1/time', '/fapi/v1/exchangeInfo'
                ]
                
                request_params = params
                if is_private and config.secret_key:
                    request_params = self._create_secure_payload(params, config)
                
                async with self.session.request(method, url, headers=headers, params=request_params) as response:
                    # Rate limit headers'ını güncelle
                    await self._update_rate_limits(response, endpoint)
                    
                    response_data = await response.json()
                    
                    if response.status == 200:
                        return response_data
                    else:
                        error_code = response_data.get('code', response.status)
                        error_msg = response_data.get('msg', 'Unknown error')
                        
                        # Retry gerektiren hatalar
                        if response.status in [429, 418]:  # Rate limit, IP ban
                            wait_time = 2 ** attempt  # Exponential backoff
                            logger.warning(f"⚠️ Rate limit hit, waiting {wait_time}s (attempt {attempt + 1}/{retries})")
                            await asyncio.sleep(wait_time)
                            continue
                            
                        # Retry gerektirmeyen hatalar
                        raise BinanceAPIError(f"API Error {error_code}: {error_msg}")
                        
            except asyncio.TimeoutError:
                last_exception = BinanceAPIError(f"Request timeout (attempt {attempt + 1}/{retries})")
                logger.warning(f"⏰ Request timeout, retrying... ({attempt + 1}/{retries})")
                await asyncio.sleep(1)
                
            except aiohttp.ClientError as e:
                last_exception = BinanceAPIError(f"Network error: {e}")
                logger.warning(f"🌐 Network error, retrying... ({attempt + 1}/{retries})")
                await asyncio.sleep(1)
        
        # Tüm retry'ler başarısız oldu
        raise last_exception or BinanceAPIError("Max retries exceeded")
    
    async def _check_rate_limit(self, endpoint: str):
        """Rate limit kontrolü"""
        if endpoint in self.rate_limits:
            limits = self.rate_limits[endpoint]
            current_time = time.time()
            
            # Weight limit kontrolü
            if 'used_weight_1m' in limits:
                used_weight = limits['used_weight_1m']
                weight_limit = limits.get('weight_limit_1m', 1200)  # Varsayılan limit
                
                if used_weight > weight_limit * 0.9:  # %90 threshold
                    wait_time = 60 - (current_time - limits.get('weight_reset_time', 0))
                    if wait_time > 0:
                        logger.warning(f"⚠️ Weight limit approaching, waiting {wait_time:.1f}s")
                        await asyncio.sleep(wait_time)
    
    async def _update_rate_limits(self, response: aiohttp.ClientResponse, endpoint: str):
        """Rate limit headers'ını güncelle"""
        headers = response.headers
        
        if 'X-MBX-USED-WEIGHT-1M' in headers:
            self.rate_limits[endpoint] = {
                'used_weight_1m': int(headers['X-MBX-USED-WEIGHT-1M']),
                'weight_limit_1m': int(headers.get('X-MBX-WEIGHT-LIMIT-1M', 1200)),
                'weight_reset_time': time.time()
            }
    
    # ORDER METHODS
    async def create_order(
        self,
        user_id: int,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        time_in_force: Optional[str] = None,
        futures: bool = False,
        testnet: bool = False
    ) -> Dict[str, Any]:
        """
        Yeni order oluştur
        
        Args:
            user_id: Kullanıcı ID
            symbol: İşlem çifti (BTCUSDT, ETHUSDT, vb.)
            side: BUY veya SELL
            order_type: LIMIT, MARKET, STOP_LOSS, vb.
            quantity: Miktar
            price: Fiyat (LIMIT order'lar için)
            time_in_force: GTC, IOC, FOK
            futures: Futures işlemleri için
            testnet: Testnet kullanımı için
        """
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v1/order' if futures else '/api/v3/order'
        
        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': quantity
        }
        
        if price is not None:
            params['price'] = price
        
        if time_in_force is not None:
            params['timeInForce'] = time_in_force.upper()
        
        return await self._make_request('POST', endpoint, config, params)
    
    async def cancel_order(
        self,
        user_id: int,
        symbol: str,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
        futures: bool = False,
        testnet: bool = False
    ) -> Dict[str, Any]:
        """Order iptal et"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v1/order' if futures else '/api/v3/order'
        
        params = {'symbol': symbol.upper()}
        
        if order_id is not None:
            params['orderId'] = order_id
        elif orig_client_order_id is not None:
            params['origClientOrderId'] = orig_client_order_id
        else:
            raise ValueError("Either order_id or orig_client_order_id must be provided")
        
        return await self._make_request('DELETE', endpoint, config, params)
    
    async def get_order(
        self,
        user_id: int,
        symbol: str,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
        futures: bool = False,
        testnet: bool = False
    ) -> Dict[str, Any]:
        """Order bilgisini getir"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v1/order' if futures else '/api/v3/order'
        
        params = {'symbol': symbol.upper()}
        
        if order_id is not None:
            params['orderId'] = order_id
        elif orig_client_order_id is not None:
            params['origClientOrderId'] = orig_client_order_id
        else:
            raise ValueError("Either order_id or orig_client_order_id must be provided")
        
        return await self._make_request('GET', endpoint, config, params)
    
    async def get_open_orders(
        self,
        user_id: int,
        symbol: Optional[str] = None,
        futures: bool = False,
        testnet: bool = False
    ) -> List[Dict[str, Any]]:
        """Açık order'ları getir"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v1/openOrders' if futures else '/api/v3/openOrders'
        
        params = {}
        if symbol is not None:
            params['symbol'] = symbol.upper()
        
        return await self._make_request('GET', endpoint, config, params)
    
    async def get_all_orders(
        self,
        user_id: int,
        symbol: str,
        limit: int = 500,
        futures: bool = False,
        testnet: bool = False
    ) -> List[Dict[str, Any]]:
        """Tüm order'ları getir"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v1/allOrders' if futures else '/api/v3/allOrders'
        
        params = {
            'symbol': symbol.upper(),
            'limit': limit
        }
        
        return await self._make_request('GET', endpoint, config, params)
    
    # ACCOUNT METHODS
    async def get_account_info(
        self,
        user_id: int,
        futures: bool = False,
        testnet: bool = False
    ) -> Dict[str, Any]:
        """Hesap bilgilerini getir"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v2/account' if futures else '/api/v3/account'
        
        return await self._make_request('GET', endpoint, config)
    
    async def get_balance(
        self,
        user_id: int,
        asset: Optional[str] = None,
        futures: bool = False,
        testnet: bool = False
    ) -> List[Dict[str, Any]]:
        """Bakiye bilgilerini getir"""
        account_info = await self.get_account_info(user_id, futures, testnet)
        
        if futures:
            balances = account_info.get('assets', [])
        else:
            balances = account_info.get('balances', [])
        
        if asset is not None:
            asset_upper = asset.upper()
            balances = [bal for bal in balances if bal['asset'] == asset_upper]
        
        return balances
    
    # TRADE METHODS
    async def get_account_trades(
        self,
        user_id: int,
        symbol: str,
        limit: int = 500,
        futures: bool = False,
        testnet: bool = False
    ) -> List[Dict[str, Any]]:
        """Hesap trade'lerini getir"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if not api_creds:
            raise BinanceAuthenticationError(f"API key not found for user {user_id}")
        
        api_key, secret_key = api_creds
        config = RESTApiConfig(api_key, secret_key, futures, testnet)
        
        endpoint = '/fapi/v1/userTrades' if futures else '/api/v3/myTrades'
        
        params = {
            'symbol': symbol.upper(),
            'limit': limit
        }
        
        return await self._make_request('GET', endpoint, config, params)
    
    # MARKET DATA METHODS
    async def get_exchange_info(
        self,
        symbol: Optional[str] = None,
        futures: bool = False,
        testnet: bool = False
    ) -> Dict[str, Any]:
        """Exchange bilgilerini getir (public)"""
        # Public endpoint için bot API key'ini kullan
        config = RESTApiConfig(self.bot_api_key or '', self.bot_secret_key or '', futures, testnet)
        
        endpoint = '/fapi/v1/exchangeInfo' if futures else '/api/v3/exchangeInfo'
        
        params = {}
        if symbol is not None:
            params['symbol'] = symbol.upper()
        
        return await self._make_request('GET', endpoint, config, params)
    
    async def get_symbol_info(
        self,
        symbol: str,
        futures: bool = False,
        testnet: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Sembol bilgilerini getir"""
        exchange_info = await self.get_exchange_info(futures=futures, testnet=testnet)
        symbols = exchange_info.get('symbols', [])
        
        for sym in symbols:
            if sym['symbol'] == symbol.upper():
                return sym
        
        return None


# MultiUserWebSocketManager sınıfına REST API entegrasyonu
class MultiUserWebSocketManager:
    _instance: Optional['MultiUserWebSocketManager'] = None
    
    def __new__(cls, *args, **kwargs):
       if cls._instance is None:
           cls._instance = super().__new__(cls)
       return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
            
        self.api_key_manager = APIKeyManager.get_instance()
        
        # ===WebSocket değişkenleri=====
        # Connection storage: {connection_id: {user_data}}
        self.user_connections: Dict[str, Dict[str, Any]] = {}
        # User bazlı connection tracking: {user_id: [connection_ids]}
        self.user_connection_map: Dict[int, Set[str]] = {}
        # Bot API key'i (public işlemler için)
        self.bot_api_key: Optional[str] = None
        self.bot_secret_key: Optional[str] = None
        
        # ===REST API instance===
        self.rest_api = BinanceRESTAPI()
        
        self.running = False
        self._initialized = True
        
        logger.info("✅ MultiUserWebSocketManager initialized")

    async def initialize(self, bot_api_key: Optional[str] = None, bot_secret_key: Optional[str] = None) -> None:
        """Bot API key'lerini ayarla ve manager'ı başlat"""
        self.bot_api_key = bot_api_key
        self.bot_secret_key = bot_secret_key
        
        # REST API'yi başlat
        await self.rest_api.initialize()
        
        # REST API'ye bot key'lerini ve API key manager'ını set et
        self.rest_api.api_key_manager = self.api_key_manager
        self.rest_api.bot_api_key = bot_api_key
        self.rest_api.bot_secret_key = bot_secret_key
        
        self.running = True
        logger.info("✅ MultiUserWebSocketManager started with REST API")

    def _generate_connection_id(self, user_id: int, stream_type: str) -> str:
        """Benzersiz connection ID oluştur"""
        timestamp = int(time.time() * 1000)
        unique_str = f"{user_id}_{stream_type}_{timestamp}"
        return hashlib.md5(unique_str.encode()).hexdigest()[:12]

    async def _get_user_config(self, user_id: int, futures: bool = False) -> UserWebSocketConfig:
        """Kullanıcının API key'lerini getir"""
        api_creds = await self.api_key_manager.get_apikey(user_id)
        if api_creds:
            api_key, secret_key = api_creds
            return UserWebSocketConfig(
                user_id=user_id,
                api_key=api_key,
                secret_key=secret_key,
                futures=futures
            )
        else:
            # Kullanıcı API key'i yoksa bot key'ini kullan (sadece public streams)
            return UserWebSocketConfig(
                user_id=user_id,
                api_key=self.bot_api_key,
                secret_key=self.bot_secret_key,
                futures=futures
            )

    async def connect_public_stream(
        self,
        user_id: int,
        streams: List[str],
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        futures: bool = False
    ) -> str:
        """Public stream bağlantısı (bot API key'i kullanır)"""
        return await self._connect_stream(
            user_id=user_id,
            streams=streams,
            callback=callback,
            futures=futures,
            is_public=True
        )

    async def connect_user_stream(
        self,
        user_id: int,
        streams: List[str],
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        futures: bool = False
    ) -> str:
        """Kullanıcı özel stream bağlantısı (kullanıcı API key'i kullanır)"""
        return await self._connect_stream(
            user_id=user_id,
            streams=streams,
            callback=callback,
            futures=futures,
            is_public=False
        )

    async def _connect_stream(
        self,
        user_id: int,
        streams: List[str],
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        futures: bool = False,
        is_public: bool = False
    ) -> str:
        """Stream bağlantısı oluştur"""
        if not streams:
            raise ValueError("Streams list cannot be empty")
        if not callable(callback):
            raise ValueError("Callback must be callable")

        try:
            # Kullanıcı config'ini al
            user_config = await self._get_user_config(user_id, futures)
            
            # URL oluştur
            base_url = "wss://fstream.binance.com" if futures else "wss://stream.binance.com:9443"
            if user_config.testnet:
                base_url = "wss://stream.binancefuture.com" if futures else "wss://testnet.binance.vision"
                
            ws_url = f"{base_url}/stream?streams={'/'.join(streams)}"
            
            # Connection ID oluştur
            stream_type = "public" if is_public else "private"
            connection_id = self._generate_connection_id(user_id, stream_type)

            # Connection kaydı oluştur
            self.user_connections[connection_id] = {
                'user_id': user_id,
                'url': ws_url,
                'streams': streams,
                'callback': callback,
                'futures': futures,
                'is_public': is_public,
                'user_config': user_config,
                'running': True,
                'task': None
            }

            # User connection mapping güncelle
            if user_id not in self.user_connection_map:
                self.user_connection_map[user_id] = set()
            self.user_connection_map[user_id].add(connection_id)

            # Connection task'ını başlat
            self.user_connections[connection_id]['task'] = asyncio.create_task(
                self._run_connection(connection_id)
            )

            logger.info(f"✅ {stream_type.capitalize()} WebSocket {connection_id} started for user {user_id}")
            return connection_id

        except Exception as e:
            logger.error(f"❌ Failed to create WebSocket connection for user {user_id}", exc_info=True)
            raise BinanceWebSocketError(f"Connection failed: {e}") from e

    async def _run_connection(self, connection_id: str) -> None:
        """WebSocket connection'ı çalıştır"""
        if connection_id not in self.user_connections:
            return

        connection = self.user_connections[connection_id]
        reconnect_delay = 1
        max_reconnect_delay = 60

        while connection['running'] and self.running:
            try:
                async with websockets.connect(connection['url']) as ws:
                    logger.info(f"🔗 WebSocket {connection_id} connected for user {connection['user_id']}")
                    reconnect_delay = 1

                    while connection['running']:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            data = json.loads(message)
                            
                            # Kullanıcı bilgisini callback'e ekle
                            enhanced_data = {
                                **data,
                                'user_id': connection['user_id'],
                                'connection_id': connection_id,
                                'is_public': connection['is_public']
                            }
                            
                            await connection['callback'](enhanced_data)
                            
                        except asyncio.TimeoutError:
                            await ws.ping()
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ JSON decode error for connection {connection_id}: {e}")
                        except Exception as e:
                            logger.error(f"❌ Callback error for connection {connection_id}: {e}")

            except websockets.ConnectionClosed:
                logger.warning(f"⚠️ WebSocket {connection_id} connection closed, reconnecting...")
            except Exception as e:
                logger.error(f"❌ WebSocket {connection_id} error: {e}")

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

    async def subscribe_user_data(
        self,
        user_id: int,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
        futures: bool = False
    ) -> str:
        """Kullanıcı data stream'ine abone ol"""
        user_config = await self._get_user_config(user_id, futures)
        
        if not user_config.api_key:
            raise BinanceAuthenticationError("User API key not found")

        # ListenKey al
        listen_key = await self._get_listen_key(user_config)
        
        # URL oluştur
        base_url = "wss://fstream.binance.com" if futures else "wss://stream.binance.com:9443"
        if user_config.testnet:
            base_url = "wss://stream.binancefuture.com" if futures else "wss://testnet.binance.vision"
            
        ws_url = f"{base_url}/ws/{listen_key}"

        connection_id = self._generate_connection_id(user_id, "user_data")

        self.user_connections[connection_id] = {
            'user_id': user_id,
            'url': ws_url,
            'streams': ['userData'],
            'callback': callback,
            'futures': futures,
            'is_public': False,
            'user_config': user_config,
            'running': True,
            'listen_key': listen_key,
            'task': None,
            'keepalive_task': None
        }

        # User connection mapping
        if user_id not in self.user_connection_map:
            self.user_connection_map[user_id] = set()
        self.user_connection_map[user_id].add(connection_id)

        # Task'ları başlat
        self.user_connections[connection_id]['keepalive_task'] = asyncio.create_task(
            self._keepalive_listen_key(connection_id)
        )
        self.user_connections[connection_id]['task'] = asyncio.create_task(
            self._run_connection(connection_id)
        )

        logger.info(f"✅ User data WebSocket {connection_id} started for user {user_id}")
        return connection_id

    async def _get_listen_key(self, user_config: UserWebSocketConfig) -> str:
        """ListenKey al"""
        endpoint = '/fapi/v1/listenKey' if user_config.futures else '/api/v3/userDataStream'
        url = ("https://fapi.binance.com" if user_config.futures else "https://api.binance.com") + endpoint
        headers = {'X-MBX-APIKEY': user_config.api_key} if user_config.api_key else {}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['listenKey']
                else:
                    error_text = await resp.text()
                    raise BinanceAPIError(f"{resp.status} - {error_text}")

    async def _keepalive_listen_key(self, connection_id: str) -> None:
        """ListenKey'i canlı tut"""
        if connection_id not in self.user_connections:
            return

        connection = self.user_connections[connection_id]
        user_config = connection['user_config']
        
        endpoint = '/fapi/v1/listenKey' if user_config.futures else '/api/v3/userDataStream'
        url = ("https://fapi.binance.com" if user_config.futures else "https://api.binance.com") + endpoint
        headers = {'X-MBX-APIKEY': user_config.api_key}

        while connection['running'] and self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    params = {'listenKey': connection['listen_key']}
                    async with session.put(url, headers=headers, params=params) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.warning(f"⚠️ Listen key keepalive failed for {connection_id}: {resp.status} - {text}")
                
                await asyncio.sleep(1800)  # 30 dakika
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Listen key keepalive error for {connection_id}: {e}")
                await asyncio.sleep(60)

    async def disconnect_user_connections(self, user_id: int) -> None:
        """Kullanıcının tüm bağlantılarını kapat"""
        if user_id not in self.user_connection_map:
            return

        connection_ids = list(self.user_connection_map[user_id])
        for connection_id in connection_ids:
            await self.disconnect(connection_id)

        logger.info(f"✅ All connections closed for user {user_id}")

    async def disconnect(self, connection_id: str) -> None:
        """Belirli bir bağlantıyı kapat"""
        if connection_id not in self.user_connections:
            return

        conn = self.user_connections[connection_id]
        conn['running'] = False
        
        # Task'ları iptal et
        tasks = []
        if conn.get('task'):
            conn['task'].cancel()
            tasks.append(conn['task'])
        if conn.get('keepalive_task'):
            conn['keepalive_task'].cancel()
            tasks.append(conn['keepalive_task'])
            
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Kayıtları temizle
        user_id = conn['user_id']
        if user_id in self.user_connection_map:
            self.user_connection_map[user_id].discard(connection_id)
            if not self.user_connection_map[user_id]:
                del self.user_connection_map[user_id]
                
        del self.user_connections[connection_id]
        logger.info(f"✅ WebSocket {connection_id} disconnected")



    async def close_all(self) -> None:
        """Tüm bağlantıları kapat (REST API dahil)"""
        self.running = False
        
        # WebSocket bağlantılarını kapat
        tasks = []
        for connection_id in list(self.user_connections.keys()):
            conn = self.user_connections[connection_id]
            conn['running'] = False
            if conn.get('task'):
                tasks.append(conn['task'])
            if conn.get('keepalive_task'):
                tasks.append(conn['keepalive_task'])
                
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
        self.user_connections.clear()
        self.user_connection_map.clear()
        
        # REST API session'ını kapat
        await self.rest_api.close()
        
        logger.info("✅ All WebSocket connections and REST API closed")



    def get_user_status(self, user_id: int) -> Dict[str, Any]:
        """Kullanıcının connection durumunu getir"""
        connections = self.user_connection_map.get(user_id, set())
        return {
            'user_id': user_id,
            'active_connections': len(connections),
            'connections': list(connections),
            'running': self.running
        }

    def get_global_status(self) -> Dict[str, Any]:
        """Global durumu getir"""
        return {
            'total_users': len(self.user_connection_map),
            'total_connections': len(self.user_connections),
            'running': self.running
        }

# REST API metodları - delegation
    async def create_order(self, user_id: int, symbol: str, side: str, order_type: str, 
                          quantity: float, **kwargs) -> Dict[str, Any]:
        """Order oluştur (REST API delegasyonu)"""
        return await self.rest_api.create_order(user_id, symbol, side, order_type, quantity, **kwargs)
    
    async def cancel_order(self, user_id: int, symbol: str, **kwargs) -> Dict[str, Any]:
        """Order iptal et (REST API delegasyonu)"""
        return await self.rest_api.cancel_order(user_id, symbol, **kwargs)
    
    async def get_account_info(self, user_id: int, **kwargs) -> Dict[str, Any]:
        """Hesap bilgilerini getir (REST API delegasyonu)"""
        return await self.rest_api.get_account_info(user_id, **kwargs)
    
    # Diğer REST API metodları için benzer delegasyonlar...




# Global instance
async def get_multi_websocket_manager(
    bot_api_key: Optional[str] = None,
    bot_secret_key: Optional[str] = None
) -> MultiUserWebSocketManager:
    manager = MultiUserWebSocketManager()
    await manager.initialize(bot_api_key, bot_secret_key)
    return manager