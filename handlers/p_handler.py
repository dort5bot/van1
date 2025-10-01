"""
p_handler.py
------------
Binance API üzerinden coin verilerini sorgulayan handler.
Komutlar:
- /p [symbols...] → Seçilen coinlerin veya config SCAN_SYMBOLS listesinin fiyatlarını gösterir
- /pg [limit]     → En çok yükselen coinleri listeler
- /pl [limit]     → En çok düşen coinleri listeler
- /test_api       → Binance API bağlantı testi yapar
Rapor formatı (coin adı, değişim %, hacim, fiyat )
"""

import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from typing import List, Optional

from utils.binance.binance_a import get_binance_api
from config import get_config

logger = logging.getLogger(__name__)

router = Router()

# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
async def fetch_with_retry(func, *args, retries: int = 3, **kwargs):
    """Binance API çağrısını retry ile sarmalar."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            logger.warning(f"⚠️ API çağrısı başarısız (attempt {attempt}/{retries}): {e}")
    logger.error(f"❌ API çağrısı {retries} denemeden sonra başarısız: {last_exc}")
    raise last_exc


def format_number(num: float, precision: int = 2) -> str:
    """Sayısal değerleri okunabilir hale getirir."""
    if num >= 1_000_000_000:
        return f"${num/1_000_000_000:.2f}B"
    elif num >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    elif num >= 1_000:
        return f"${num/1_000:.2f}K"
    else:
        return f"${num:.{precision}f}"


def format_report(title: str, tickers: List[dict]) -> str:
    """Ticker listesini rapor formatına çevirir."""
    lines = [f"📈 {title}", "⚡Coin | Değişim | Hacim | Fiyat"]
    for i, t in enumerate(tickers, 1):
        sym = t.get("symbol", "N/A")
        change = float(t.get("priceChangePercent", 0))
        vol = float(t.get("quoteVolume", 0))
        price = float(t.get("lastPrice", 0))
        lines.append(
            f"{i}. {sym}: {change:+.2f}% | {format_number(vol)} | {price:.4f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------
# /p komutu
# ---------------------------------------------------------------------
@router.message(Command("p"))
async def cmd_p(message: Message) -> None:
    """
    /p [symbols...] → SCAN_SYMBOLS veya belirtilen coinleri listeler.
    """
    try:
        args = message.text.split()[1:]
        api = await get_binance_api()

        if args:
            # Kullanıcının yazdığı coinler
            symbols = [s.upper() if s.upper().endswith("USDT") else f"{s.upper()}USDT" for s in args]
            tickers = await fetch_with_retry(api.get_custom_symbols_data, symbols)
            title = "Seçili Coinler"
        else:
            # Config SCAN_SYMBOLS
            config = await get_config()
            symbols = config.SCAN_SYMBOLS
            tickers = await fetch_with_retry(api.get_custom_symbols_data, symbols)
            # Hacme göre sırala
            tickers.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
            title = "SCAN_SYMBOLS (Hacme Göre)"

        if not tickers:
            await message.answer("❌ Veri bulunamadı")
            return

        report = format_report(title, tickers)
        await message.answer(report)

    except Exception as e:
        logger.error(f"❌ /p komutunda hata: {e}")
        await message.answer("❌ Veri alınamadı, lütfen tekrar deneyin.")


# ---------------------------------------------------------------------
# /pg komutu (top gainers)
# ---------------------------------------------------------------------
@router.message(Command("pg"))
async def cmd_pg(message: Message) -> None:
    """
    /pg [limit] → En çok yükselen coinleri listeler.
    """
    try:
        args = message.text.split()[1:]
        limit = int(args[0]) if args else 20
        api = await get_binance_api()

        tickers = await fetch_with_retry(api.get_top_gainers_with_volume, limit)
        if not tickers:
            await message.answer("❌ Yükselen coin bulunamadı")
            return

        report = format_report(f"En Çok Yükselen İlk {limit}", tickers)
        await message.answer(report)

    except Exception as e:
        logger.error(f"❌ /pg komutunda hata: {e}")
        await message.answer("❌ Veri alınamadı.")


# ---------------------------------------------------------------------
# /pl komutu (top losers)
# ---------------------------------------------------------------------
@router.message(Command("pl"))
async def cmd_pl(message: Message) -> None:
    """
    /pl [limit] → En çok düşen coinleri listeler.
    """
    try:
        args = message.text.split()[1:]
        limit = int(args[0]) if args else 20
        api = await get_binance_api()

        tickers = await fetch_with_retry(api.get_top_losers_with_volume, limit)
        if not tickers:
            await message.answer("❌ Düşen coin bulunamadı")
            return

        report = format_report(f"En Çok Düşen İlk {limit}", tickers)
        await message.answer(report)

    except Exception as e:
        logger.error(f"❌ /pl komutunda hata: {e}")
        await message.answer("❌ Veri alınamadı.")


# ---------------------------------------------------------------------
# /test_api komutu
# ---------------------------------------------------------------------
@router.message(Command("test_api"))
async def cmd_test_api(message: Message) -> None:
    """
    /test_api → Binance API bağlantı testi yapar.
    """
    try:
        api = await get_binance_api()
        ping = await fetch_with_retry(api.ping)
        server_time = await fetch_with_retry(api.get_server_time)
        await message.answer(f"✅ Binance API çalışıyor.\nPing: {ping}\nServer Time: {server_time}")
    except Exception as e:
        logger.error(f"❌ /test_api komutunda hata: {e}")
        await message.answer(f"❌ Binance API bağlantısı başarısız: {e}")
