# utils/binance/binance_pr_asset.py
"""
AssetClient: deposit/withdraw/dust + asset endpoints.
Binance API standardına uygun geliştirilmiş versiyon.
"""
from typing import Any, Dict, List, Optional, Union
import logging

from .binance_pr_base import BinancePrivateBase
from .binance_exceptions import BinanceAPIError

logger = logging.getLogger(__name__)


class AssetClient(BinancePrivateBase):
    """Deposit, withdraw, dust conversion, asset info and related operations."""

    # ----------------------------- DUST -----------------------------

    async def get_dust_log(
        self, start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> Dict[str, Any]:
        """GET /sapi/v1/asset/dribblet - Get conversion history (dust log)."""
        try:
            params = {}
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/asset/dribblet", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting dust log")
            raise BinanceAPIError("GET /sapi/v1/asset/dribblet failed", e)

    async def convert_dust(self, assets: List[str]) -> Dict[str, Any]:
        """POST /sapi/v1/asset/dust - Convert micro assets to BNB."""
        try:
            params = {"asset": [a.upper() for a in assets]}
            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/asset/dust", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error converting dust")
            raise BinanceAPIError("POST /sapi/v1/asset/dust failed", e)

    # ----------------------------- ASSET INFO -----------------------------

    async def get_asset_dividend(
        self, asset: Optional[str] = None, start_time: Optional[int] = None, end_time: Optional[int] = None
    ) -> Dict[str, Any]:
        """GET /sapi/v1/asset/assetDividend - Query asset dividend record."""
        try:
            params = {}
            if asset:
                params["asset"] = asset.upper()
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/asset/assetDividend", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting asset dividend")
            raise BinanceAPIError("GET /sapi/v1/asset/assetDividend failed", e)

    async def get_asset_detail(self) -> Dict[str, Any]:
        """GET /sapi/v1/asset/assetDetail - Query asset detail (withdraw/deposit status, fee)."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/asset/assetDetail", signed=True
            )
        except Exception as e:
            logger.exception("Error getting asset detail")
            raise BinanceAPIError("GET /sapi/v1/asset/assetDetail failed", e)

    async def get_trade_fee(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /sapi/v1/asset/tradeFee - Get trading fee."""
        try:
            params = {}
            if symbol:
                params["symbol"] = symbol.upper()
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/asset/tradeFee", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting trade fee")
            raise BinanceAPIError("GET /sapi/v1/asset/tradeFee failed", e)

    # ----------------------------- DEPOSIT -----------------------------

    async def get_deposit_address(self, coin: str, network: Optional[str] = None) -> Dict[str, Any]:
        """GET /sapi/v1/capital/deposit/address - Get deposit address."""
        try:
            params = {"coin": coin.upper()}
            if network:
                params["network"] = network
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/capital/deposit/address", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting deposit address")
            raise BinanceAPIError(f"GET /sapi/v1/capital/deposit/address failed for {coin}", e)

    async def get_deposit_history(
        self,
        coin: Optional[str] = None,
        status: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """GET /sapi/v1/capital/deposit/hisrec - Get deposit history."""
        try:
            params = {}
            if coin:
                params["coin"] = coin.upper()
            if status is not None:
                params["status"] = status
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/capital/deposit/hisrec", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting deposit history")
            raise BinanceAPIError("GET /sapi/v1/capital/deposit/hisrec failed", e)

    async def get_all_coins_info(self) -> List[Dict[str, Any]]:
        """GET /sapi/v1/capital/config/getall - Get all coins info (network list, fee, enable status)."""
        try:
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/capital/config/getall", signed=True
            )
        except Exception as e:
            logger.exception("Error getting all coins info")
            raise BinanceAPIError("GET /sapi/v1/capital/config/getall failed", e)

    # ----------------------------- WITHDRAW -----------------------------

    async def get_withdraw_history(
        self,
        coin: Optional[str] = None,
        status: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """GET /sapi/v1/capital/withdraw/history - Get withdraw history."""
        try:
            params = {}
            if coin:
                params["coin"] = coin.upper()
            if status is not None:
                params["status"] = status
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/capital/withdraw/history", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting withdraw history")
            raise BinanceAPIError("GET /sapi/v1/capital/withdraw/history failed", e)

    async def get_withdraw_address_list(self, coin: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /sapi/v1/capital/withdraw/address/list - Get withdraw address whitelist (if enabled)."""
        try:
            params = {}
            if coin:
                params["coin"] = coin.upper()
            return await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/capital/withdraw/address/list", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error getting withdraw address list")
            raise BinanceAPIError("GET /sapi/v1/capital/withdraw/address/list failed", e)

    async def withdraw(
        self,
        coin: str,
        address: str,
        amount: Union[str, float],
        network: Optional[str] = None,
        address_tag: Optional[str] = None,
        wallet_type: Optional[int] = None,
        transaction_fee_flag: Optional[bool] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /sapi/v1/capital/withdraw/apply - Apply for withdraw.

        Required: coin, address, amount
        Optional: network, addressTag, walletType, transactionFeeFlag, name
        """
        try:
            params: Dict[str, Any] = {
                "coin": coin.upper(),
                "address": address,
                "amount": str(amount),  # API string bekliyor
            }
            if network:
                params["network"] = network
            if address_tag:
                params["addressTag"] = address_tag
            if wallet_type is not None:
                params["walletType"] = wallet_type
            if transaction_fee_flag is not None:
                params["transactionFeeFlag"] = str(transaction_fee_flag).lower()
            if name:
                params["name"] = name

            return await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/capital/withdraw/apply", params=params, signed=True
            )
        except Exception as e:
            logger.exception("Error withdrawing asset")
            raise BinanceAPIError(f"POST /sapi/v1/capital/withdraw/apply failed for {coin}", e)
