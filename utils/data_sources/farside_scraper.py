
# -----------------------------------------------------------------------------
# File: utils/data_sources/farside_scraper.py
from __future__ import annotations
"""
FarsideScraper - scrapes ETF flow tables from farside.co.uk
- resilient to minor HTML changes
- returns list[dict] rows
"""

from typing import Any, List, Optional
import aiohttp
from bs4 import BeautifulSoup
import logging

from .base_client import BaseClient

_LOG = logging.getLogger(__name__)


FARSIDE_URLS = {
    "BTC": "https://farside.co.uk/bitcoin-etf-flow-table/",
    "ETH": "https://farside.co.uk/ethereum-etf-flow-table/",
}


class FarsideScraper(BaseClient):
    async def get_metric(self, coin: str, metric: str = "etf_flows") -> Optional[List[dict]]:
        coin = (coin or "").upper().strip()
        if coin not in FARSIDE_URLS:
            raise ValueError("Unsupported coin for Farside scraper")
        url = FARSIDE_URLS[coin]
        cache_key = f"farside:{coin}:{metric}"
        _LOG.debug("Fetching Farside %s for %s", metric, coin)

        # Reuse BaseClient request but parse text
        text = await self._request("GET", url, cache_key=cache_key, parse_json=False)
        if not text:
            return None

        try:
            soup = BeautifulSoup(text, "html.parser")
            # find candidate tables with header containing 'Issuer' or 'Daily flow'
            tables = soup.find_all("table")
            best = None
            for t in tables:
                headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
                if not headers:
                    continue
                if any("issuer" in h for h in headers) or any("daily" in h for h in headers):
                    best = t
                    break
            if best is None:
                _LOG.warning("No suitable table found on farside page")
                return None

            headers = [th.get_text(strip=True) for th in best.find_all("th")]
            rows = []
            for tr in best.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if not cells:
                    continue
                # align headers and cells (some rows might have fewer cells)
                row = {headers[i]: cells[i] if i < len(cells) else None for i in range(len(headers))}
                rows.append(row)
            return rows
        except Exception as e:
            _LOG.exception("Error parsing farside page: %s", e)
            return None

