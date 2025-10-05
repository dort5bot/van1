# utils/binance_api/binance_pr_mining.py
"""
MiningClient: Binance mining endpoints (sapi/v1/mining/*).
"""

from typing import Any, Dict, Optional
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class MiningClient(BinancePrivateBase):
    """Mining operations."""

    async def get_algo_list(self) -> Dict[str, Any]:
        """
        GET /sapi/v1/mining/pub/algoList
        Returns supported mining algorithms.
        """
        try:
            return await self.circuit_breaker.execute(
                self.http._request,
                "GET",
                "/sapi/v1/mining/pub/algoList",
                signed=False,
            )
        except BinanceAPIError:
            raise
        except Exception as e:
            logger.exception("Error fetching algo list")
            raise BinanceAPIError(f"Unexpected error in get_algo_list: {e}")

    async def get_coin_list(self) -> Dict[str, Any]:
        """
        GET /sapi/v1/mining/pub/coinList
        Returns supported mining coins.
        """
        try:
            return await self.circuit_breaker.execute(
                self.http._request,
                "GET",
                "/sapi/v1/mining/pub/coinList",
                signed=False,
            )
        except BinanceAPIError:
            raise
        except Exception as e:
            logger.exception("Error fetching coin list")
            raise BinanceAPIError(f"Unexpected error in get_coin_list: {e}")

    async def get_user_status(
        self, algo: str, user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        GET /sapi/v1/mining/statistics/user/status
        Returns mining account status for given algo.
        Required:
            - algo: mining algorithm
        Optional:
            - userName: sub-account name
        """
        if not algo:
            raise ValueError("Parameter 'algo' is required")

        params: Dict[str, Any] = {"algo": algo}
        if user_name:
            params["userName"] = user_name

        try:
            return await self.circuit_breaker.execute(
                self.http._request,
                "GET",
                "/sapi/v1/mining/statistics/user/status",
                params=params,
                signed=True,
            )
        except BinanceAPIError:
            raise
        except Exception as e:
            logger.exception("Error fetching user status (params=%s)", params)
            raise BinanceAPIError(f"Unexpected error in get_user_status: {e}")

    async def get_earnings_list(
        self,
        algo: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        GET /sapi/v1/mining/payment/list
        Returns payment records.
        """
        if not algo:
            raise ValueError("Parameter 'algo' is required")

        params: Dict[str, Any] = {"algo": algo}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if page_index:
            params["pageIndex"] = page_index
        if page_size:
            params["pageSize"] = page_size

        try:
            return await self.circuit_breaker.execute(
                self.http._request,
                "GET",
                "/sapi/v1/mining/payment/list",
                params=params,
                signed=True,
            )
        except BinanceAPIError:
            raise
        except Exception as e:
            logger.exception("Error getting mining earnings list (params=%s)", params)
            raise BinanceAPIError(f"Unexpected error in get_earnings_list: {e}")

    async def get_worker_list(
        self,
        algo: str,
        user_name: Optional[str] = None,
        page_index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        GET /sapi/v1/mining/worker/list
        Returns workers list for given algo.
        """
        if not algo:
            raise ValueError("Parameter 'algo' is required")

        params: Dict[str, Any] = {"algo": algo}
        if user_name:
            params["userName"] = user_name
        if page_index:
            params["pageIndex"] = page_index
        if page_size:
            params["pageSize"] = page_size

        try:
            return await self.circuit_breaker.execute(
                self.http._request,
                "GET",
                "/sapi/v1/mining/worker/list",
                params=params,
                signed=True,
            )
        except BinanceAPIError:
            raise
        except Exception as e:
            logger.exception("Error getting worker list (params=%s)", params)
            raise BinanceAPIError(f"Unexpected error in get_worker_list: {e}")
