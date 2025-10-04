# utils/binance/binance_a.py
# V105  - multi-user

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Union
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .binance_request import BinanceHTTPClient



# Public imports
from . import binance_pb_spot, binance_pb_futures, binance_pb_system, binance_pb_index

# Private imports
from .binance_pr_spot import SpotClient
from .binance_pr_futures import FuturesClient
from .binance_pr_margin import MarginClient
from .binance_pr_asset import AssetClient
from .binance_pr_savings import SavingsClient
from .binance_pr_staking import StakingClient
from .binance_pr_mining import MiningClient
from .binance_pr_subaccount import SubAccountClient
from .binance_pr_userstream import UserStreamClient
from .binance_pr_base import BinancePrivateBase
from .binance_pr_convert import ConvertClient
from .binance_pr_crypto_loans import CryptoLoansClient  
from .binance_pr_pay import PayClient

#diger importlar
from .binance_pr_giftcard import GiftCardClient


# Common imports - zorunlu
# kullanılmıyor> from utils.binance_api.binance_client import BinanceClientManager
# kullanılmıyor> from utils.binance_api.binance_metrics import MetricsCollector
from .binance_request import BinanceHTTPClient
from .binance_circuit_breaker import CircuitBreaker

from ..apikey_manager import APIKeyManager


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)



# ===============================
# MULTI-USER AGGREGATOR SETTINGS
# ===============================
class MultiUserAggregatorSettings:
    """
    Multi-user configuration for Binance API aggregator.
    Her kullanıcı için ayrı HTTP client ve circuit breaker yönetimi.
    """
    _instance: Optional["MultiUserAggregatorSettings"] = None

    def __init__(self):
        self.apikey_db = APIKeyManager.get_instance()
        self._user_clients: Dict[int, BinanceHTTPClient] = {}
        self._user_circuit_breakers: Dict[int, CircuitBreaker] = {}
        self._user_locks: Dict[int, asyncio.Lock] = {}
        logger.debug("MultiUserAggregatorSettings initialized")

    @classmethod
    def get_instance(cls) -> "MultiUserAggregatorSettings":
        """Return singleton instance."""
        if cls._instance is None:
            cls._instance = MultiUserAggregatorSettings()
        return cls._instance

    def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        """Get or create user-specific lock."""
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    async def get_user_client(self, user_id: int) -> BinanceHTTPClient:
        """
        Get or create user-specific HTTP client.
        Thread-safe with user-specific locks.
        """
        async with self._get_user_lock(user_id):
            if user_id in self._user_clients:
                return self._user_clients[user_id]
            
            # Create new client for user
            creds = await self.apikey_db.get_apikey(user_id)
            if not creds:
                raise ValueError(f"No API key found for user {user_id}")
            
            api_key, api_secret = creds
            client = BinanceHTTPClient(
                api_key=api_key, 
                secret_key=api_secret,
                user_id=user_id
            )
            
            self._user_clients[user_id] = client
            logger.info(f"Created HTTP client for user {user_id}")
            return client

    async def get_user_circuit_breaker(self, user_id: int) -> CircuitBreaker:
        """Get or create user-specific circuit breaker."""
        async with self._get_user_lock(user_id):
            if user_id in self._user_circuit_breakers:
                return self._user_circuit_breakers[user_id]
            
            breaker = CircuitBreaker(name=f"user_{user_id}")
            self._user_circuit_breakers[user_id] = breaker
            return breaker

    async def cleanup_user_resources(self, user_id: int):
        """Cleanup user-specific resources."""
        async with self._get_user_lock(user_id):
            if user_id in self._user_clients:
                await self._user_clients[user_id].close()
                del self._user_clients[user_id]
            
            if user_id in self._user_circuit_breakers:
                del self._user_circuit_breakers[user_id]
            
            if user_id in self._user_locks:
                del self._user_locks[user_id]
            
            logger.info(f"Cleaned up resources for user {user_id}")

    async def get_all_active_users(self) -> List[int]:
        """Get list of all active users with clients."""
        return list(self._user_clients.keys())



# ===============================
# ENHANCED PUBLIC API - MULTI-USER READY
# ===============================

class MultiUserPublicApi:
    """
    Multi-user compatible Public API.
    Public endpoints don't require user authentication but can track user context.
    """

    def __init__(self):
        self.spot = self.MultiUserPublicSpot()
        self.futures = self.MultiUserPublicFutures()
        self.system = self.MultiUserPublicSystem()
        self.index = self.MultiUserPublicIndex()
        logger.debug("MultiUserPublicApi initialized")

    class MultiUserPublicSpot:
        """Multi-user Public Spot API."""

        def __init__(self):
            self._public_client = binance_pb_spot.BinancePBSpot.get_instance()
            logger.debug("MultiUserPublicSpot instance created")

        async def ping(self, user_id: Optional[int] = None) -> bool:
            """Test connectivity with optional user context."""
            logger.debug(f"Ping request from user {user_id}")
            return await self._public_client.ping()

        async def server_time(self, user_id: Optional[int] = None) -> int:
            """Get server time with user context."""
            logger.debug(f"Server time request from user {user_id}")
            return await self._public_client.server_time()

        async def exchange_info(self, symbol: Optional[str] = None, user_id: Optional[int] = None) -> Any:
            """Get exchange info with user context."""
            logger.debug(f"Exchange info request from user {user_id} for symbol {symbol}")
            return await self._public_client.exchange_info(symbol)

        # public method'lar aynı şekilde user_id parametresi alacak
        async def order_book(self, symbol: str, limit: int = 100, user_id: Optional[int] = None) -> Any:
            logger.debug(f"Order book request from user {user_id} for {symbol}")
            return await self._public_client.order_book(symbol, limit)

        async def get_klines(self, symbol: str, interval: str, limit: int = 500,
                           start_time: Optional[int] = None, end_time: Optional[int] = None,
                           user_id: Optional[int] = None) -> Any:
            logger.debug(f"Klines request from user {user_id} for {symbol} {interval}")
            return await self._public_client.klines(
                symbol=symbol, interval=interval, limit=limit,
                start_time=start_time, end_time=end_time
            )


  
  
        
        # ek-ds     
        async def avg_price(self, symbol: str, user_id: Optional[int] = None) -> Dict[str, Any]:
            """Get average price for symbol with user context."""
            logger.debug(f"Avg price request from user {user_id} for {symbol}")
            return await self._public_client.avg_price(symbol)

        async def get_ui_klines(self, symbol: str, interval: str, limit: int = 500,
                              start_time: Optional[int] = None, end_time: Optional[int] = None,
                              user_id: Optional[int] = None) -> Any:
            """Get UI klines with user context."""
            logger.debug(f"UI klines request from user {user_id} for {symbol} {interval}")
            return await self._public_client.ui_klines(
                symbol=symbol, interval=interval, limit=limit,
                start_time=start_time, end_time=end_time
            )

        async def get_recent_trades(self, symbol: str, limit: int = 500, 
                                  user_id: Optional[int] = None) -> Any:
            """Get recent trades with user context."""
            logger.debug(f"Recent trades request from user {user_id} for {symbol}")
            return await self._public_client.trades(symbol, limit)

        async def get_historical_trades(self, symbol: str, limit: int = 500, 
                                      from_id: Optional[int] = None,
                                      user_id: Optional[int] = None) -> Any:
            """Get historical trades with user context."""
            logger.debug(f"Historical trades request from user {user_id} for {symbol}")
            return await self._public_client.historical_trades(symbol, limit, from_id)
            
            
        
    class MultiUserPublicFutures:
        """Multi-user Public Futures API."""

        def __init__(self):
            self._public_client = binance_pb_futures.BinancePBFutures.get_instance()
            logger.debug("MultiUserPublicFutures instance created")

        async def get_futures_klines(self, symbol: str, interval: str, limit: int = 500, 
                                   user_id: Optional[int] = None) -> Any:
            logger.debug(f"Futures klines request from user {user_id} for {symbol}")
            return await self._public_client.klines(symbol=symbol, interval=interval, limit=limit)

        # ek
        # 
        async def get_continuous_klines(self, pair: str, contract_type: str, interval: str, 
                                      limit: int = 500, start_time: Optional[int] = None,
                                      end_time: Optional[int] = None, 
                                      user_id: Optional[int] = None) -> Any:
            """Get continuous klines with user context."""
            logger.debug(f"Continuous klines request from user {user_id} for {pair}")
            return await self._public_client.continuous_klines(
                pair=pair, contract_type=contract_type, interval=interval,
                limit=limit, start_time=start_time, end_time=end_time
            )

        async def get_index_price_klines(self, pair: str, interval: str, limit: int = 500,
                                       start_time: Optional[int] = None, 
                                       end_time: Optional[int] = None,
                                       user_id: Optional[int] = None) -> Any:
            """Get index price klines with user context."""
            logger.debug(f"Index price klines request from user {user_id} for {pair}")
            return await self._public_client.index_price_klines(
                pair=pair, interval=interval, limit=limit,
                start_time=start_time, end_time=end_time
            )

        async def get_mark_price_klines(self, symbol: str, interval: str, limit: int = 500,
                                      start_time: Optional[int] = None,
                                      end_time: Optional[int] = None,
                                      user_id: Optional[int] = None) -> Any:
            """Get mark price klines with user context."""
            logger.debug(f"Mark price klines request from user {user_id} for {symbol}")
            return await self._public_client.mark_price_klines(
                symbol=symbol, interval=interval, limit=limit,
                start_time=start_time, end_time=end_time
            )

        async def get_funding_rate(self, symbol: Optional[str] = None, 
                                 start_time: Optional[int] = None,
                                 end_time: Optional[int] = None, limit: int = 100,
                                 user_id: Optional[int] = None) -> Any:
            """Get funding rate with user context."""
            logger.debug(f"Funding rate request from user {user_id} for {symbol}")
            return await self._public_client.funding_rate(
                symbol=symbol, start_time=start_time, end_time=end_time, limit=limit
            )

        async def get_ticker_24hr(self, symbol: Optional[str] = None, 
                                user_id: Optional[int] = None) -> Any:
            """Get 24hr ticker with user context."""
            logger.debug(f"24hr ticker request from user {user_id} for {symbol}")
            return await self._public_client.ticker_24hr(symbol)

        async def get_ticker_price(self, symbol: Optional[str] = None, 
                                 user_id: Optional[int] = None) -> Any:
            """Get ticker price with user context."""
            logger.debug(f"Ticker price request from user {user_id} for {symbol}")
            return await self._public_client.ticker_price(symbol)
            
        
    
    class MultiUserPublicIndex:
        """Multi-user Public Index API."""

        def __init__(self):
            self._public_client = binance_pb_index.BinancePBIndex.get_instance()
            logger.debug("MultiUserPublicIndex instance created")

        async def get_index_price(self, symbol: str, user_id: Optional[int] = None) -> Dict[str, Any]:
            logger.debug(f"Index price request from user {user_id} for {symbol}")
            return await self._public_client.mark_price(symbol)

        # ek
        
        async def get_funding_rate_history(self, symbol: Optional[str] = None,
                                         start_time: Optional[int] = None,
                                         end_time: Optional[int] = None, limit: int = 100,
                                         user_id: Optional[int] = None) -> Any:
            """Get funding rate history with user context."""
            logger.debug(f"Funding rate history request from user {user_id} for {symbol}")
            return await self._public_client.funding_rate_history(
                symbol=symbol, start_time=start_time, end_time=end_time, limit=limit
            )

        async def get_index_info(self, symbol: Optional[str] = None, 
                               user_id: Optional[int] = None) -> Any:
            """Get index information with user context."""
            logger.debug(f"Index info request from user {user_id} for {symbol}")
            return await self._public_client.index_info(symbol)

        async def get_asset_index(self, symbol: Optional[str] = None, 
                                user_id: Optional[int] = None) -> Any:
            """Get asset index with user context."""
            logger.debug(f"Asset index request from user {user_id} for {symbol}")
            return await self._public_client.asset_index(symbol)
            
        
     
    class MultiUserPublicSystem:
        """Multi-user Public System API."""

        async def ping(self, user_id: Optional[int] = None) -> bool:
            logger.debug(f"System ping from user {user_id}")
            return await binance_pb_system.ping()

        async def get_exchange_info(self, user_id: Optional[int] = None) -> Dict[str, Any]:
            logger.debug(f"System exchange info from user {user_id}")
            return await binance_pb_system.get_exchange_info()
        
        # ek
    
        async def ping_spot(self, user_id: Optional[int] = None) -> bool:
            """Ping spot endpoint with user context."""
            logger.debug(f"System spot ping from user {user_id}")
            return await binance_pb_system.ping_spot()

        async def ping_futures(self, user_id: Optional[int] = None) -> bool:
            """Ping futures endpoint with user context."""
            logger.debug(f"System futures ping from user {user_id}")
            return await binance_pb_system.ping_futures()

        async def get_server_time_spot(self, user_id: Optional[int] = None) -> int:
            """Get spot server time with user context."""
            logger.debug(f"System spot server time from user {user_id}")
            return await binance_pb_system.server_time_spot()

        async def get_server_time_futures(self, user_id: Optional[int] = None) -> int:
            """Get futures server time with user context."""
            logger.debug(f"System futures server time from user {user_id}")
            return await binance_pb_system.server_time_futures()

        async def get_exchange_info_spot(self, symbol: Optional[str] = None, 
                                       user_id: Optional[int] = None) -> Any:
            """Get spot exchange info with user context."""
            logger.debug(f"System spot exchange info from user {user_id} for {symbol}")
            return await binance_pb_system.exchange_info_spot(symbol)

        async def get_exchange_info_futures(self, symbol: Optional[str] = None, 
                                          user_id: Optional[int] = None) -> Any:
            """Get futures exchange info with user context."""
            logger.debug(f"System futures exchange info from user {user_id} for {symbol}")
            return await binance_pb_system.exchange_info_futures(symbol)
            
        
        
# ===============================
# ENHANCED PRIVATE API - MULTI-USER
# ===============================
class MultiUserPrivateApi:
    """
    Multi-user Private API with enhanced user management.
    """

    def __init__(self):
        self.settings = MultiUserAggregatorSettings.get_instance()
        logger.debug("MultiUserPrivateApi initialized")

        self.spot = self.MultiUserPrivateSpot(self) 
        self.futures = self.MultiUserPrivateFutures(self) 
        self.margin = self.MultiUserPrivateMargin(self)
        self.asset = self.MultiUserPrivateAsset(self) 
        self.savings = self.MultiUserPrivateSavings(self)
        self.staking = self.MultiUserPrivateStaking(self)
        self.mining = self.MultiUserPrivateMining(self)
        self.subaccount = self.MultiUserPrivateSubAccount(self)
        self.userstream = self.MultiUserPrivateUserStream(self)
        self.convert = self.MultiUserPrivateConvert(self)
        self.crypto_loans = self.MultiUserPrivateCryptoLoans(self)
        self.pay = self.MultiUserPrivatePay(self)
        self.giftcard = self.MultiUserPrivateGiftCard(self)
       


    async def _get_user_base_client(self, user_id: int) -> BinancePrivateBase:
        """Get user-specific base client."""
        http_client = await self.settings.get_user_client(user_id)
        circuit_breaker = await self.settings.get_user_circuit_breaker(user_id)
        return BinancePrivateBase(http_client, circuit_breaker)

    class MultiUserPrivateSpot:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateSpot instance created")

        async def client(self, user_id: int) -> SpotClient:
            """Get user-specific Spot client."""
            base = await self.parent._get_user_base_client(user_id)
            return SpotClient(base.http, base.circuit_breaker)

        async def get_account_info(self, user_id: int) -> Dict[str, Any]:
            """Get user account info."""
            client = await self.client(user_id)
            return await client.get_account_info()

        async def get_account_status(self, user_id: int) -> Dict[str, Any]:
            """GET /sapi/v1/account/status - Get account status."""
            logger.debug(f"Account status request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_account_status()



        async def place_order(self, user_id: int, **kwargs) -> Dict[str, Any]:
            """Place order for specific user."""
            client = await self.client(user_id)
            return await client.place_order(**kwargs)

        async def get_open_orders(self, user_id: int, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
            """Get user's open orders."""
            client = await self.client(user_id)
            return await client.get_open_orders(symbol)

        async def get_order_history(self, user_id: int, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
            """Get user's order history."""
            client = await self.client(user_id)
            return await client.get_order_history(symbol, limit)



        async def get_dustable_assets(self, user_id: int) -> Dict[str, Any]:
            """GET /sapi/v1/asset/dust-btc - Get dustable assets."""
            logger.debug(f"Dustable assets request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_dustable_assets()

        async def get_asset_dividend_record(self, user_id: int, asset: Optional[str] = None,
                                          start_time: Optional[int] = None,
                                          end_time: Optional[int] = None,
                                          limit: int = 20) -> Dict[str, Any]:
            """GET /sapi/v1/asset/assetDividend - Get asset dividend record."""
            logger.debug(f"Asset dividend record request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_asset_dividend_record(asset, start_time, end_time, limit)
            
        
    class MultiUserPrivateFutures:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateFutures instance created")

        async def client(self, user_id: int) -> FuturesClient:
            """Get user-specific Futures client."""
            base = await self.parent._get_user_base_client(user_id)
            return FuturesClient(base.http, base.circuit_breaker)

        async def get_account_info(self, user_id: int) -> Dict[str, Any]:
            """Get user futures account info."""
            client = await self.client(user_id)
            return await client.get_account_info()


        async def get_futures_account_transaction_history(self, user_id: int, asset: str,
                                                start_time: Optional[int] = None,
                                                end_time: Optional[int] = None,
                                                current: int = 1, size: int = 10) -> Dict[str, Any]:
            """GET /sapi/v1/futures/transfer - Get futures account transaction history."""
            logger.debug(f"Futures account transaction history request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_futures_account_transaction_history(asset, start_time, end_time, current, size)

        async def place_order(self, user_id: int, **kwargs) -> Dict[str, Any]:
            """Place futures order for specific user."""
            client = await self.client(user_id)
            return await client.place_order(**kwargs)

        async def get_position(self, user_id: int, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
            """Get user's positions."""
            client = await self.client(user_id)
            return await client.get_position(symbol)


        async def get_futures_balance(self, user_id: int) -> List[Dict[str, Any]]:
            """GET /fapi/v2/balance - Get futures account balance."""
            logger.debug(f"Futures balance request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_futures_balance()
            
        
    class MultiUserPrivateMargin:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent

        async def client(self, user_id: int) -> MarginClient:
            base = await self.parent._get_user_base_client(user_id)
            return MarginClient(base.http, base.circuit_breaker)

        async def get_margin_account(self, user_id: int) -> Dict[str, Any]:
            client = await self.client(user_id)
            return await client.get_margin_account()

        async def get_margin_interest_rate_history(self, user_id: int, asset: str,
                                                 vip_level: Optional[int] = None,
                                                 start_time: Optional[int] = None,
                                                 end_time: Optional[int] = None) -> Dict[str, Any]:
            """GET /sapi/v1/margin/interestRateHistory - Get margin interest rate history."""
            logger.debug(f"Margin interest rate history request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_margin_interest_rate_history(asset, vip_level, start_time, end_time)

        async def get_margin_order_count(self, user_id: int, is_isolated: Optional[bool] = None) -> Dict[str, Any]:
            """GET /sapi/v1/margin/rateLimit/order - Get margin order count."""
            logger.debug(f"Margin order count request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_margin_order_count(is_isolated)
            

    class MultiUserPrivateAsset:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent

        async def client(self, user_id: int) -> AssetClient:
            base = await self.parent._get_user_base_client(user_id)
            return AssetClient(base.http, base.circuit_breaker)

        async def get_asset_balance(self, user_id: int, asset: str) -> Dict[str, Any]:
            client = await self.client(user_id)
            return await client.get_asset_balance(asset)

        async def get_asset_ledger(self, user_id: int, asset: Optional[str] = None,
                                  start_time: Optional[int] = None,
                                  end_time: Optional[int] = None,
                                  limit: int = 500) -> List[Dict[str, Any]]:
            """GET /sapi/v1/asset/ledger - Get asset ledger."""
            logger.debug(f"Asset ledger request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_asset_ledger(asset, start_time, end_time, limit)

        async def get_auto_conversion_status(self, user_id: int, asset: Optional[str] = None) -> Dict[str, Any]:
            """GET /sapi/v1/asset/auto-conversion - Get auto-conversion status."""
            logger.debug(f"Auto-conversion status request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_auto_conversion_status(asset)
    
    
    # -------EK PRIVATE API SINIFLARI ------------

    class MultiUserPrivateSavings:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateSavings instance created")

        async def client(self, user_id: int) -> SavingsClient:
            """Get user-specific Savings client."""
            base = await self.parent._get_user_base_client(user_id)
            return SavingsClient(base.http, base.circuit_breaker)

        async def get_savings_product_list(self, user_id: int, product_type: str = "REGULAR", 
                                         asset: Optional[str] = None, 
                                         current: int = 1, size: int = 50) -> Dict[str, Any]:
            """GET /sapi/v1/lending/daily/product/list - Get savings product list."""
            logger.debug(f"Savings product list request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_savings_product_list(product_type, asset, current, size)

        async def purchase_savings_product(self, user_id: int, product_id: str, 
                                         amount: float) -> Dict[str, Any]:
            """POST /sapi/v1/lending/daily/purchase - Purchase savings product."""
            logger.debug(f"Savings purchase request from user {user_id} for product {product_id}")
            client = await self.client(user_id)
            return await client.purchase_savings_product(product_id, amount)

        async def get_savings_balance(self, user_id: int, asset: Optional[str] = None) -> Dict[str, Any]:
            """GET /sapi/v1/lending/daily/token/position - Get savings balance."""
            logger.debug(f"Savings balance request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_savings_balance(asset)

    class MultiUserPrivateStaking:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateStaking instance created")

        async def client(self, user_id: int) -> StakingClient:
            """Get user-specific Staking client."""
            base = await self.parent._get_user_base_client(user_id)
            return StakingClient(base.http, base.circuit_breaker)

        async def get_staking_product_list(self, user_id: int, product: str = "STAKING") -> Dict[str, Any]:
            """GET /sapi/v1/staking/productList - Get staking product list."""
            logger.debug(f"Staking product list request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_staking_product_list(product)

        async def stake_asset(self, user_id: int, product: str, product_id: str, 
                            amount: float) -> Dict[str, Any]:
            """POST /sapi/v1/staking/purchase - Stake asset."""
            logger.debug(f"Staking request from user {user_id} for product {product_id}")
            client = await self.client(user_id)
            return await client.stake_asset(product, product_id, amount)

        async def get_staking_position(self, user_id: int, product: str, 
                                     product_id: Optional[str] = None) -> Dict[str, Any]:
            """GET /sapi/v1/staking/position - Get staking position."""
            logger.debug(f"Staking position request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_staking_position(product, product_id)

    class MultiUserPrivateMining:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateMining instance created")

        async def client(self, user_id: int) -> MiningClient:
            """Get user-specific Mining client."""
            base = await self.parent._get_user_base_client(user_id)
            return MiningClient(base.http, base.circuit_breaker)

        async def get_mining_earnings_list(self, user_id: int, algo: str, 
                                         start_date: str, end_date: str,
                                         page_index: int = 1, page_size: int = 100) -> Dict[str, Any]:
            """GET /sapi/v1/mining/payment/list - Get mining earnings list."""
            logger.debug(f"Mining earnings list request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_mining_earnings_list(algo, start_date, end_date, page_index, page_size)

        async def get_mining_statistics(self, user_id: int, algo: str) -> Dict[str, Any]:
            """GET /sapi/v1/mining/statistics/user/status - Get mining statistics."""
            logger.debug(f"Mining statistics request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_mining_statistics(algo)

    class MultiUserPrivateSubAccount:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateSubAccount instance created")

        async def client(self, user_id: int) -> SubAccountClient:
            """Get user-specific SubAccount client."""
            base = await self.parent._get_user_base_client(user_id)
            return SubAccountClient(base.http, base.circuit_breaker)

        async def get_subaccount_list(self, user_id: int, page: int = 1, 
                                    limit: int = 10) -> Dict[str, Any]:
            """GET /sapi/v1/sub-account/list - Get sub-account list."""
            logger.debug(f"Sub-account list request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_subaccount_list(page, limit)

        async def get_subaccount_assets(self, user_id: int, email: str) -> Dict[str, Any]:
            """GET /sapi/v3/sub-account/assets - Get sub-account assets."""
            logger.debug(f"Sub-account assets request from user {user_id} for {email}")
            client = await self.client(user_id)
            return await client.get_subaccount_assets(email)

        async def create_virtual_subaccount(self, user_id: int, sub_account_string: str) -> Dict[str, Any]:
            """POST /sapi/v1/sub-account/virtualSubAccount - Create virtual sub-account."""
            logger.debug(f"Create virtual sub-account request from user {user_id}")
            client = await self.client(user_id)
            return await client.create_virtual_subaccount(sub_account_string)

    class MultiUserPrivateUserStream:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateUserStream instance created")

        async def client(self, user_id: int) -> UserStreamClient:
            """Get user-specific UserStream client."""
            base = await self.parent._get_user_base_client(user_id)
            return UserStreamClient(base.http, base.circuit_breaker)

        async def start_user_data_stream(self, user_id: int) -> Dict[str, Any]:
            """POST /api/v3/userDataStream - Start user data stream."""
            logger.debug(f"Start user data stream request from user {user_id}")
            client = await self.client(user_id)
            return await client.start_user_data_stream()

        async def keepalive_user_data_stream(self, user_id: int, listen_key: str) -> Dict[str, Any]:
            """PUT /api/v3/userDataStream - Keepalive user data stream."""
            logger.debug(f"Keepalive user data stream request from user {user_id}")
            client = await self.client(user_id)
            return await client.keepalive_user_data_stream(listen_key)

        async def close_user_data_stream(self, user_id: int, listen_key: str) -> Dict[str, Any]:
            """DELETE /api/v3/userDataStream - Close user data stream."""
            logger.debug(f"Close user data stream request from user {user_id}")
            client = await self.client(user_id)
            return await client.close_user_data_stream(listen_key)

    class MultiUserPrivateConvert:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateConvert instance created")

        async def client(self, user_id: int) -> ConvertClient:
            """Get user-specific Convert client."""
            base = await self.parent._get_user_base_client(user_id)
            return ConvertClient(base.http, base.circuit_breaker)

        async def get_convert_trade_history(self, user_id: int, start_time: Optional[int] = None,
                                          end_time: Optional[int] = None, limit: int = 100) -> Dict[str, Any]:
            """GET /sapi/v1/convert/tradeFlow - Get convert trade history."""
            logger.debug(f"Convert trade history request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_convert_trade_history(start_time, end_time, limit)

        async def create_convert_trade(self, user_id: int, from_asset: str, to_asset: str,
                                     amount: float) -> Dict[str, Any]:
            """POST /sapi/v1/convert/trade - Create convert trade."""
            logger.debug(f"Create convert trade request from user {user_id}")
            client = await self.client(user_id)
            return await client.create_convert_trade(from_asset, to_asset, amount)

    class MultiUserPrivateCryptoLoans:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateCryptoLoans instance created")

        async def client(self, user_id: int) -> CryptoLoansClient:
            """Get user-specific CryptoLoans client."""
            base = await self.parent._get_user_base_client(user_id)
            return CryptoLoansClient(base.http, base.circuit_breaker)

        async def get_loan_income_history(self, user_id: int, asset: Optional[str] = None,
                                        type_: Optional[str] = None,
                                        start_time: Optional[int] = None,
                                        end_time: Optional[int] = None,
                                        limit: int = 100) -> Dict[str, Any]:
            """GET /sapi/v1/loan/income - Get loan income history."""
            logger.debug(f"Loan income history request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_loan_income_history(asset, type_, start_time, end_time, limit)

        async def get_loan_ongoing_orders(self, user_id: int, order_id: Optional[int] = None,
                                        collateral_account_id: Optional[int] = None) -> Dict[str, Any]:
            """GET /sapi/v1/loan/ongoing/orders - Get loan ongoing orders."""
            logger.debug(f"Loan ongoing orders request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_loan_ongoing_orders(order_id, collateral_account_id)

    class MultiUserPrivatePay:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivatePay instance created")

        async def client(self, user_id: int) -> PayClient:
            """Get user-specific Pay client."""
            base = await self.parent._get_user_base_client(user_id)
            return PayClient(base.http, base.circuit_breaker)

        async def get_pay_trade_history(self, user_id: int, start_time: Optional[int] = None,
                                      end_time: Optional[int] = None,
                                      limit: int = 100) -> Dict[str, Any]:
            """GET /sapi/v1/pay/transactions - Get pay trade history."""
            logger.debug(f"Pay trade history request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_pay_trade_history(start_time, end_time, limit)

        async def create_pay_trade(self, user_id: int, receiver_email: str,
                                 amount: float, currency: str) -> Dict[str, Any]:
            """POST /sapi/v1/pay/transfer - Create pay trade."""
            logger.debug(f"Create pay trade request from user {user_id}")
            client = await self.client(user_id)
            return await client.create_pay_trade(receiver_email, amount, currency)

    class MultiUserPrivateGiftCard:
        def __init__(self, parent: "MultiUserPrivateApi"):
            self.parent = parent
            logger.debug("MultiUserPrivateGiftCard instance created")

        async def client(self, user_id: int) -> GiftCardClient:
            """Get user-specific GiftCard client."""
            base = await self.parent._get_user_base_client(user_id)
            return GiftCardClient(base.http, base.circuit_breaker)

        async def create_gift_card(self, user_id: int, token: str, amount: float) -> Dict[str, Any]:
            """POST /sapi/v1/giftcard/create - Create gift card."""
            logger.debug(f"Create gift card request from user {user_id}")
            client = await self.client(user_id)
            return await client.create_gift_card(token, amount)

        async def get_gift_card_verification(self, user_id: int, reference_no: str) -> Dict[str, Any]:
            """GET /sapi/v1/giftcard/verify - Get gift card verification."""
            logger.debug(f"Gift card verification request from user {user_id}")
            client = await self.client(user_id)
            return await client.get_gift_card_verification(reference_no)
            
            
    

# ===============================
# MAIN MULTI-USER AGGREGATOR
# ===============================
class MultiUserBinanceAggregator:
    """
    Unified Multi-User Binance Aggregator for Public + Private APIs.
    Supports multiple users with isolated sessions and circuit breakers.
    """

    _instance: Optional["MultiUserBinanceAggregator"] = None

    def __init__(self):
        self.public = MultiUserPublicApi()
        self.private = MultiUserPrivateApi()
        self.settings = MultiUserAggregatorSettings.get_instance()
        self._version = "3.0.0-multi"
        self._init_time = datetime.now()
        
        logger.info(f"✅ MultiUserBinanceAggregator v{self._version} initialized")

    @classmethod
    def get_instance(cls) -> "MultiUserBinanceAggregator":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = MultiUserBinanceAggregator()
        return cls._instance

    # User Management Methods
    async def validate_user_credentials(self, user_id: int) -> bool:
        """Validate user's Binance credentials."""
        try:
            api_manager = APIKeyManager.get_instance()
            return await api_manager.validate_binance_credentials(user_id)
        except Exception as e:
            logger.error(f"Credential validation failed for user {user_id}: {e}")
            return False



    async def get_user_status(self, user_id: int) -> Dict[str, Any]:
        try:
            creds_valid = await self.validate_user_credentials(user_id)
            client = await self.settings.get_user_client(user_id)
            health = await client.health_check()
            circuit_breaker = await self.settings.get_user_circuit_breaker(user_id)
            
            return {
                'user_id': user_id,
                'credentials_valid': creds_valid,
                'api_health': health,
                'circuit_breaker_state': circuit_breaker.get_state(),
                'active_since': self._init_time.isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to get status for user {user_id}: {e}")
            return {
                'user_id': user_id,
                'credentials_valid': False,
                'error': str(e)
            }


    async def get_all_users_status(self) -> Dict[int, Dict[str, Any]]:
        """Get status for all active users."""
        active_users = await self.settings.get_all_active_users()
        status_dict = {}
        
        for user_id in active_users:
            status_dict[user_id] = await self.get_user_status(user_id)
            
        return status_dict

    async def cleanup_user(self, user_id: int):
        """Cleanup resources for a specific user."""
        await self.settings.cleanup_user_resources(user_id)
        logger.info(f"Cleaned up aggregator resources for user {user_id}")

    # Enhanced Health Check
    async def health_check(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Comprehensive health check.
        If user_id provided, includes user-specific checks.
        """
        health_report = {
            'status': 'healthy',
            'version': self._version,
            'timestamp': datetime.now().isoformat(),
            'uptime_seconds': (datetime.now() - self._init_time).total_seconds(),  # DAHA İYİ
            'architecture': 'multi-user',
            'services': {},
            'users': {}
        }
        
        try:
            # Public API health check
            ping_ok = await self.public.spot.ping(user_id)
            health_report['services']['public_spot'] = {
                'status': 'healthy' if ping_ok else 'unhealthy',
                'ping': ping_ok
            }
            
            if not ping_ok:
                health_report['status'] = 'degraded'
                
        except Exception as e:
            health_report['services']['public_spot'] = {'status': 'error', 'error': str(e)}
            health_report['status'] = 'degraded'

        # User-specific health checks
        if user_id:
            try:
                user_status = await self.get_user_status(user_id)
                health_report['users'][user_id] = user_status
                
                if not user_status.get('credentials_valid', False):
                    health_report['status'] = 'degraded'
                    
            except Exception as e:
                health_report['users'][user_id] = {'status': 'error', 'error': str(e)}
                health_report['status'] = 'degraded'

        return health_report

    # Statistics and Monitoring
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics."""
        return {
            'version': self._version,
            'initialized': self._init_time.isoformat(),
            'uptime_seconds': (datetime.now() - self._init_time).total_seconds(),
            'multi_user': True,
            'active_users_count': len(self.settings._user_clients)
        }

    async def close(self):
        """Cleanup all resources."""
        active_users = await self.settings.get_all_active_users()
        for user_id in active_users:
            await self.cleanup_user(user_id)
        logger.info("MultiUserBinanceAggregator closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()



# ===============================
# BACKWARD COMPATIBILITY WRAPPER
# ===============================
class BinanceAggregator:
    """
    Backward compatibility wrapper for existing code.
    Delegates to MultiUserBinanceAggregator with default user context.
    """
    
    _instance: Optional["BinanceAggregator"] = None

    def __init__(self, http_client: Optional[BinanceHTTPClient] = None):
        self._multi_user_aggregator = MultiUserBinanceAggregator.get_instance()
        self._http_client = http_client
        logger.info("Legacy BinanceAggregator initialized (delegates to MultiUser)")

    @classmethod
    def get_instance(cls, http_client: Optional[BinanceHTTPClient] = None) -> "BinanceAggregator":
        if cls._instance is None:
            cls._instance = BinanceAggregator(http_client)
        return cls._instance

    @property
    def public(self):
        return self._multi_user_aggregator.public

    @property
    def private(self):
        return self._multi_user_aggregator.private

    async def health_check(self) -> Dict[str, Any]:
        return await self._multi_user_aggregator.health_check()

    def get_stats(self) -> Dict[str, Any]:
        return self._multi_user_aggregator.get_stats()

# ===============================
# USAGE EXAMPLES - TEST ve DEBUG
# ===============================

async def demo_multi_user_usage():
    """Demo of multi-user aggregator usage."""
    aggregator = MultiUserBinanceAggregator.get_instance()
    
    # User 1 operations
    user1_id = 12345
    try:
        # Public calls with user context
        server_time = await aggregator.public.spot.server_time(user1_id)
        print(f"User {user1_id} - Server time: {server_time}")
        
        # Private calls require valid credentials
        account_info = await aggregator.private.spot.get_account_info(user1_id)
        print(f"User {user1_id} - Account info retrieved")
        
    except Exception as e:
        print(f"User {user1_id} operation failed: {e}")
        
    
    # User 2 operations
    user2_id = 67890
    try:
        klines = await aggregator.public.spot.get_klines(
            "BTCUSDT", "1h", limit=10, user_id=user2_id
        )
        print(f"User {user2_id} - Klines retrieved")
        
    except Exception as e:
        print(f"User {user2_id} operation failed: {e}")
    
    # System health check
    health = await aggregator.health_check()
    print("System health:", health)
    
    # All users status
    all_status = await aggregator.get_all_users_status()
    print("All users status:", all_status)

if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_multi_user_usage())
    
    
    



"""
Tüm endpoint'ler orijinal Binance API isimlerini korur
Multi-user desteği sağlanır (user_id parametresi)
Kapsamlı logging
Mevcut kod yapısı
Type hints ve docstring'ler tutarlı


"""