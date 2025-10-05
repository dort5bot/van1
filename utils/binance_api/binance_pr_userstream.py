# utils/binance_api/binance_pr_userstream.py
"""
UserStreamClient: user data stream endpoints (listenKey).
Supports Spot (/api/v3/userDataStream), Futures (/fapi/v1/listenKey), and Margin (/sapi/v1/userDataStream)
"""
from typing import Any, Dict, TypedDict
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class ListenKeyResponse(TypedDict):
    listenKey: str


class UserStreamClient(BinancePrivateBase):
    """Create, keepalive, and close listen keys for Spot, Futures, and Margin accounts."""

    async def create_listen_key(self, futures: bool = False, margin: bool = False) -> ListenKeyResponse:
        """
        POST user data stream.
        - Spot: /api/v3/userDataStream
        - Futures: /fapi/v1/listenKey
        - Margin: /sapi/v1/userDataStream
        """
        if futures and margin:
            raise ValueError("Cannot set both futures and margin to True")
        try:
            if futures:
                endpoint = "/fapi/v1/listenKey"
            elif margin:
                endpoint = "/sapi/v1/userDataStream"
            else:
                endpoint = "/api/v3/userDataStream"

            resp = await self.circuit_breaker.execute(
                self.http._request,
                "POST",
                endpoint,
                signed=True,
                futures=futures,
                margin=margin,
            )

            if "listenKey" not in resp:
                raise BinanceAPIError(f"No listenKey returned from Binance: {resp}")

            return ListenKeyResponse(listenKey=resp["listenKey"])
        except Exception as e:
            logger.exception("Error creating listen key")
            raise BinanceAPIError(f"Error creating listen key: {e}")

    async def keepalive_listen_key(self, listen_key: str, futures: bool = False, margin: bool = False) -> Dict[str, Any]:
        """
        PUT user data stream to keep alive.
        """
        if not listen_key or not isinstance(listen_key, str):
            raise ValueError("listen_key must be a non-empty string")
        if futures and margin:
            raise ValueError("Cannot set both futures and margin to True")
        try:
            if futures:
                endpoint = "/fapi/v1/listenKey"
            elif margin:
                endpoint = "/sapi/v1/userDataStream"
            else:
                endpoint = "/api/v3/userDataStream"

            params = {"listenKey": listen_key}

            return await self.circuit_breaker.execute(
                self.http._request,
                "PUT",
                endpoint,
                params=params,
                signed=True,
                futures=futures,
                margin=margin,
            )
        except Exception as e:
            logger.exception("Error keeping listen key alive")
            raise BinanceAPIError(f"Error keeping listen key alive: {e}")

    async def close_listen_key(self, listen_key: str, futures: bool = False, margin: bool = False) -> Dict[str, Any]:
        """
        DELETE user data stream.
        """
        if not listen_key or not isinstance(listen_key, str):
            raise ValueError("listen_key must be a non-empty string")
        if futures and margin:
            raise ValueError("Cannot set both futures and margin to True")
        try:
            if futures:
                endpoint = "/fapi/v1/listenKey"
            elif margin:
                endpoint = "/sapi/v1/userDataStream"
            else:
                endpoint = "/api/v3/userDataStream"

            params = {"listenKey": listen_key}

            return await self.circuit_breaker.execute(
                self.http._request,
                "DELETE",
                endpoint,
                params=params,
                signed=True,
                futures=futures,
                margin=margin,
            )
        except Exception as e:
            logger.exception("Error closing listen key")
            raise BinanceAPIError(f"Error closing listen key: {e}")
