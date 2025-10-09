
# -----------------------------------------------------------------------------
# File: handlers/example_handlers.py
from __future__ import annotations
"""
Aiogram 3.x compatible example handlers using Router pattern.
Assumes aiogram is installed and bot object exists in your project.
This file demonstrates how to integrate DataProvider into handlers.
"""

from aiogram import Router
from aiogram.types import Message
import logging

from utils.data_sources.data_provider import DataProvider

router = Router()
_LOG = logging.getLogger(__name__)
provider = DataProvider()


@router.message(commands=["etf"])  # /etf BTC
async def cmd_etf(message: Message) -> None:
    try:
        parts = message.text.strip().split()
        coin = parts[1].upper() if len(parts) > 1 else "BTC"
        data = await provider.get_etf_flows(coin)
        if not data:
            await message.reply("ETF verisi alınamadı.")
            return
        # format short reply (limit long messages for telegram)
        text = f"📊 {coin} Spot ETF Akışları (kısa)\n"
        for row in data[:8]:
            issuer = row.get("Issuer") or row.get("Issuer/Name") or list(row.values())[0]
            daily = row.get("Daily Flow") or row.get("Daily") or "-"
            text += f"{issuer}: {daily}\n"
        await message.reply(text)
    except Exception as e:
        _LOG.exception("/etf handler error: %s", e)
        await message.reply("Beklenmedik bir hata oluştu.")


@router.message(commands=["funding"])  # /funding BTC
async def cmd_funding(message: Message) -> None:
    parts = message.text.strip().split()
    coin = parts[1].upper() if len(parts) > 1 else "BTC"
    data = await provider.get_funding_rates(coin)
    if not data:
        await message.reply("Funding verisi alınamadı.")
        return
    # minimal formatting
    await message.reply(f"Funding verisi (örnek): {str(data)[:400]}")
