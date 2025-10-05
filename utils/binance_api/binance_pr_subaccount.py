# utils/binance_api/binance_pr_subaccount.py
"""
SubAccountClient: sub-account management endpoints.
Sub-account endpoints (/sapi/v1/sub-account/*).
Includes list, create, assets, transfer, futures, margin, status operations.
"""
from typing import Any, Dict, List, Optional
import logging
import re

from .binance_pr_base import BinancePrivateBase
#from .binance_exceptions import BinanceAPIError, BinanceRequestException, BinanceRateLimitException
from .binance_exceptions import BinanceAPIError, BinanceRequestError, BinanceRateLimitError # BinanceValidationError yoksa çıkar

logger = logging.getLogger(__name__)

EMAIL_REGEX = r"[^@]+@[^@]+\.[^@]+"

class SubAccountClient(BinancePrivateBase):
    """Sub-account operations."""

    async def get_list(self, email: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /sapi/v1/sub-account/list"""
        if email and not re.match(EMAIL_REGEX, email):
            raise ValueError(f"Invalid email format: {email}")
        params = {"email": email} if email else {}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/sub-account/list", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp.get("subAccounts", [])
        except Exception as e:
            logger.exception("Error getting sub-account list")
            raise BinanceAPIError(f"Error getting sub-account list: {e}")

    async def create(self, sub_account_string: str) -> Dict[str, Any]:
        """POST /sapi/v1/sub-account/virtualSubAccount"""
        if not sub_account_string or not isinstance(sub_account_string, str):
            raise ValueError("sub_account_string must be a non-empty string")
        params = {"subAccountString": sub_account_string}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/sub-account/virtualSubAccount", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp
        except Exception as e:
            logger.exception("Error creating sub-account")
            raise BinanceAPIError(f"Error creating sub-account: {e}")

    async def get_assets(self, email: str) -> Dict[str, Any]:
        """GET /sapi/v3/sub-account/assets"""
        if not re.match(EMAIL_REGEX, email):
            raise ValueError(f"Invalid email format: {email}")
        params = {"email": email}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v3/sub-account/assets", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp
        except Exception as e:
            logger.exception("Error getting sub-account assets")
            raise BinanceAPIError(f"Error getting sub-account assets: {e}")

    async def transfer(self, from_email: str, to_email: str, asset: str, amount: float) -> Dict[str, Any]:
        """POST /sapi/v1/sub-account/transfer"""
        for email in (from_email, to_email):
            if not re.match(EMAIL_REGEX, email):
                raise ValueError(f"Invalid email format: {email}")
        if not asset:
            raise ValueError("asset must be a non-empty string")
        if amount <= 0:
            raise ValueError("amount must be positive")
        params = {"fromEmail": from_email, "toEmail": to_email, "asset": asset, "amount": amount}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "POST", "/sapi/v1/sub-account/transfer", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp
        except Exception as e:
            logger.exception("Error transferring between sub-accounts")
            raise BinanceAPIError(f"Error transferring between sub-accounts: {e}")

    async def get_futures_account(self, email: str) -> Dict[str, Any]:
        """GET /sapi/v1/sub-account/futures/account"""
        if not re.match(EMAIL_REGEX, email):
            raise ValueError(f"Invalid email format: {email}")
        params = {"email": email}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/sub-account/futures/account", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp
        except Exception as e:
            logger.exception("Error getting sub-account futures account")
            raise BinanceAPIError(f"Error getting sub-account futures account: {e}")

    async def get_margin_account(self, email: str) -> Dict[str, Any]:
        """GET /sapi/v1/sub-account/margin/account"""
        if not re.match(EMAIL_REGEX, email):
            raise ValueError(f"Invalid email format: {email}")
        params = {"email": email}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/sub-account/margin/account", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp
        except Exception as e:
            logger.exception("Error getting sub-account margin account")
            raise BinanceAPIError(f"Error getting sub-account margin account: {e}")

    async def get_status(self, email: str) -> Dict[str, Any]:
        """GET /sapi/v1/sub-account/status"""
        if not re.match(EMAIL_REGEX, email):
            raise ValueError(f"Invalid email format: {email}")
        params = {"email": email}
        try:
            resp = await self.circuit_breaker.execute(
                self.http._request, "GET", "/sapi/v1/sub-account/status", params=params, signed=True
            )
            self._handle_api_error(resp)
            return resp
        except Exception as e:
            logger.exception("Error getting sub-account status")
            raise BinanceAPIError(f"Error getting sub-account status: {e}")

    def _handle_api_error(self, resp: Dict[str, Any]) -> None:
        """Parse Binance API errors and raise exceptions."""
        if not resp:
            raise BinanceRequestException("Empty response from Binance API")
        code = resp.get("code")
        msg = resp.get("msg")
        if code:
            if code in [418, 429]:
                raise BinanceRateLimitException(f"Rate limit hit: {code} - {msg}")
            raise BinanceRequestException(f"Binance API error {code}: {msg}")
