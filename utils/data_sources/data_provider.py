# -----------------------------------------------------------------------------
# File: utils/data_sources/data_provider.py
# akıllı kaynak seçimi destekler, otomatik olarak tarar
# 

from __future__ import annotations
"""
DataProvider: unified interface for downstream handlers
Provides get_metric(source, coin, metric) and convenience methods


import:
from utils.data_sources.data_provider import data_provider
btc_etf_data = await data_provider.get_metric("BTC", "etf_net_flow")


"""

from typing import Any, Optional
import logging

from .glassnode_client import GlassnodeClient
from .cryptoquant_client import CryptoQuantClient
from .farside_scraper import FarsideScraper

_LOG = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Otomatik yönlendirme tablosu (hangi metric hangi kaynaklarda bulunur)
_METRIC_SOURCE_MAP = {
    # ETF akışları yalnızca Farside'da
    "etf_flows": ["farside"],
    "etf_net_flow": ["farside"],
    # Borsa net akışları (öncelik: Glassnode → CryptoQuant)
    "exchange/netflow": ["glassnode", "cryptoquant"],
    "exchange_netflow": ["glassnode", "cryptoquant"],
    # Funding oranları yalnızca CryptoQuant'ta
    "funding_rate": ["cryptoquant"],
    "futures/funding_rate": ["cryptoquant"],
}


class DataProvider:
    """Singleton-like provider that holds client instances.
    Supports both manual and auto source routing.

    Usage:
        provider = DataProvider()

        # 1️⃣ Klasik yöntem
        data = await provider.get_metric('glassnode', 'BTC', 'exchange/netflow')

        # 2️⃣ Otomatik kaynak seçimi (yeni)
        data = await provider.get_metric('BTC', 'etf_flows')
    """

    _instance: Optional["DataProvider"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._glassnode: Optional[GlassnodeClient] = None
        self._cryptoquant: Optional[CryptoQuantClient] = None
        self._farside: Optional[FarsideScraper] = None

    # -------------------------------------------------------------------------
    # Client properties
    @property
    def glassnode(self) -> GlassnodeClient:
        if self._glassnode is None:
            self._glassnode = GlassnodeClient()
        return self._glassnode

    @property
    def cryptoquant(self) -> CryptoQuantClient:
        if self._cryptoquant is None:
            self._cryptoquant = CryptoQuantClient()
        return self._cryptoquant

    @property
    def farside(self) -> FarsideScraper:
        if self._farside is None:
            self._farside = FarsideScraper()
        return self._farside

    # -------------------------------------------------------------------------
    # Unified metric access
    async def get_metric(self, *args, **kwargs) -> Optional[Any]:
        """
        Flexible unified access method.

        ✅ Eski biçim (source + coin + metric)
            await get_metric("glassnode", "BTC", "exchange/netflow")

        ✅ Yeni biçim (coin + metric) - otomatik kaynak seçimi
            await get_metric("BTC", "etf_flows")
        """
        try:
            # --- Parametre sayısına göre çağrı biçimini ayırt et ---
            if len(args) == 3:
                # eski biçim (source, coin, metric)
                source, coin, metric = args
                return await self._get_metric_by_source(source, coin, metric, **kwargs)

            elif len(args) == 2:
                # yeni biçim (coin, metric)
                coin, metric = args
                metric_key = metric.lower().strip()
                possible_sources = _METRIC_SOURCE_MAP.get(metric_key, [])

                if not possible_sources:
                    _LOG.warning("No known data source for metric '%s'", metric_key)
                    return None

                # kaynakları sırayla dene (örneğin glassnode -> cryptoquant fallback)
                for src in possible_sources:
                    data = await self._get_metric_by_source(src, coin, metric, **kwargs)
                    if data is not None:
                        return data

                _LOG.warning("All sources failed for metric '%s'", metric_key)
                return None

            else:
                raise ValueError("Invalid arguments: use (source, coin, metric) or (coin, metric)")

        except Exception as e:
            _LOG.exception("DataProvider.get_metric failed: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Internal helper (tek kaynak için çağrı)
    async def _get_metric_by_source(self, source: str, coin: str, metric: str, **kwargs) -> Optional[Any]:
        source = (source or "").lower().strip()
        if source == "glassnode":
            return await self.glassnode.get_metric(coin, metric, kwargs.get("timeframe"))
        if source == "cryptoquant":
            return await self.cryptoquant.get_metric(coin, metric, params=kwargs.get("params"))
        if source == "farside":
            return await self.farside.get_metric(coin, metric)
        raise ValueError(f"Unknown data source: {source}")

    # -------------------------------------------------------------------------
    # Convenience wrappers
    async def get_exchange_netflow(self, coin: str) -> Optional[Any]:
        data = await self.get_metric("glassnode", coin, "exchange/netflow")
        if data is not None:
            return data
        return await self.get_metric("cryptoquant", coin, "exchange/netflow")

    async def get_funding_rates(self, coin: str) -> Optional[Any]:
        return await self.get_metric("cryptoquant", coin, "futures/funding_rate")

    async def get_etf_flows(self, coin: str) -> Optional[Any]:
        return await self.get_metric("farside", coin, "etf_flows")
