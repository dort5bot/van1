
# -----------------------------------------------------------------------------
# File: utils/data_sources/glassnode_client.py
from __future__ import annotations
"""
GlassnodeClient - wraps Glassnode public metrics API
https://docs.glassnode.com
"""

from typing import Any, Optional
import os
import logging

from .base_client import BaseClient

_LOG = logging.getLogger(__name__)


class GlassnodeClient(BaseClient):
    BASE = "https://api.glassnode.com/v1/metrics"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.getenv("GLASSNODE_API_KEY")
        super().__init__(api_key=api_key, **kwargs)
        self._api_key_masked = self.mask_key(self.api_key) if self.api_key else None

    async def get_metric(self, coin: str, metric: str, timeframe: Optional[str] = None) -> Optional[Any]:
        """Return JSON data for a given metric. Example metric: 'exchange/netflow'

        Args:
            coin: 'BTC'|'ETH' etc.
            metric: glassnode metric path relative to /v1/metrics
            timeframe: optional timeframe param for some endpoints
        """
        coin = (coin or "").upper().strip()
        if not coin:
            raise ValueError("coin is required")
        if not metric or ".." in metric:
            raise ValueError("invalid metric")

        url = f"{self.BASE}/{metric}"
        params = {"a": coin}
        if timeframe:
            params["t"] = timeframe
        if self.api_key:
            params["api_key"] = self.api_key

        cache_key = f"glassnode:{coin}:{metric}:{timeframe}"
        _LOG.debug("Fetching Glassnode %s (api_key=%s)", metric, self._api_key_masked)
        return await self._request("GET", url, params=params, cache_key=cache_key)

