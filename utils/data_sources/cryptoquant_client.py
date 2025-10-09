
# -----------------------------------------------------------------------------
# File: utils/data_sources/cryptoquant_client.py
from __future__ import annotations
"""
CryptoQuantClient - wraps CryptoQuant API
Docs: https://developer.cryptoquant.com/docs
"""

from typing import Any, Optional
import os
import logging

from .base_client import BaseClient

_LOG = logging.getLogger(__name__)


class CryptoQuantClient(BaseClient):
    BASE = "https://api.cryptoquant.com/v1"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.getenv("CRYPTOQUANT_API_KEY")
        super().__init__(api_key=api_key, **kwargs)
        self._masked = self.mask_key(self.api_key) if self.api_key else None

    async def get_metric(self, coin: str, metric: str, params: Optional[dict] = None) -> Optional[Any]:
        """Fetch metric from CryptoQuant.

        `metric` should be a valid endpoint path like 'futures/open_interest' or 'exchange/reserve'.
        """
        coin = (coin or "").upper().strip()
        if not coin:
            raise ValueError("coin is required")
        if not metric or ".." in metric:
            raise ValueError("invalid metric")

        url = f"{self.BASE}/{metric}"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        qparams = dict(params or {})
        qparams.setdefault("symbol", coin)

        cache_key = f"cryptoquant:{coin}:{metric}:{sorted(qparams.items())}"
        _LOG.debug("Fetching CryptoQuant %s (api=%s)", metric, self._masked)
        return await self._request("GET", url, params=qparams, headers=headers, cache_key=cache_key)

