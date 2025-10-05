"""
binance_api/__init__.py
Binance API utilities package.

Bu paket:
- Public ve Private REST API endpointlerini
- WebSocket clientlarını
- API istek ve hata yönetimini
- Tip ve sabit tanımlarını
- Metri̇k ve circuit-breaker desteğini içerir.
MultiUserWebSocketManager --> BinanceWSManager yapıldı
"""

# -- Client'lar --
from .binance_client import BinanceClient               # Ana client
from .binance_request import BinanceHTTPClient     # HTTP istek yöneticisi eskisi  BinanceRequest

# -- Yardımcı bileşenler --
from .binance_circuit_breaker import CircuitBreaker     # Circuit breaker
from .binance_metrics import *                          # Prometheus metrikleri
from .binance_constants import *                        # Sabitler
from .binance_types import *                            # Pydantic modeller

# -- Hata Yönetimi -- BinanceException yerine BinanceError kullan.
from .binance_exceptions import (
    BinanceError,
    BinanceAPIError,
    BinanceAuthenticationError,
    BinanceWebSocketError,
)

# -- WebSocket --
#from .binance_websocket import BinanceWebSocketClient
from .binance_websocket import BinanceWSClient, BinanceWSManager
from .binance_ws_pydantic import *


# -- Public & Private endpoint modülleri  --
from . import binance_pb_spot
from . import binance_pb_futures
from . import binance_pb_system
from . import binance_pb_index

from . import binance_pr_asset
from . import binance_pr_base
from . import binance_pr_futures
from . import binance_pr_margin
from . import binance_pr_mining
from . import binance_pr_savings
from . import binance_pr_spot
from . import binance_pr_staking
from . import binance_pr_subaccount
from . import binance_pr_userstream




# -- Versiyon bilgisi --
__version__ = "1.0.0"

# -- Dışa açık API --
__all__ = [
    # Client'lar
    "BinanceClient",
    "BinanceHTTPClient",

    # Hatalar
    "BinanceError",
    "BinanceAPIError",
    "BinanceAuthenticationError",

    # Circuit Breaker
    "CircuitBreaker",

    # WebSocket Client
    "BinanceWSManager",

    # Public API modülleri
    "binance_pb_spot",
    "binance_pb_futures",
    "binance_pb_system",
    "binance_pb_index",

    # Private API modülleri
    "binance_pr_asset",
    "binance_pr_base",
    "binance_pr_futures",
    "binance_pr_margin",
    "binance_pr_mining",
    "binance_pr_savings",
    "binance_pr_spot",
    "binance_pr_staking",
    "binance_pr_subaccount",
    "binance_pr_userstream",
]
