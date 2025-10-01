"""
Binance API utilities package.
"""

from .binance_a import BinanceClient
from .binance_request import BinanceHTTPClient
from .binance_circuit_breaker import CircuitBreaker
from .binance_exceptions import BinanceAPIError, BinanceAuthenticationError

__version__ = "1.0.0"
__all__ = [
    "BinanceClient",
    "BinanceHTTPClient",
    "CircuitBreaker",
    "BinanceAPIError",
    "BinanceAuthenticationError",
]