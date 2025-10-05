# handlers/p_handler.py
"""
Price Scanner Handler - Binance API standartlarına uygun fiyat tarama ve sıralama
Komutlar: /p, /pg, /pl, /test_api
"""

import logging
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import asyncio

from utils.binance_api.binance_a import MultiUserBinanceAggregator

logger = logging.getLogger(__name__)

# Router tanımı
router = Router(name="price_handler")

# Config benzeri ayarlar
SCAN_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "PEPEUSDT", "FETUSDT",
    "ARPAUSDT", "SUSDT", "SANTOSUSDT", "PORTOUSDT", "OGUSDT",
    "DOGEUSDT", "SOLUSDT", "ALICEUSDT", "SHIBUSDT", "TRXUSDT",
    "TURBOUSDT", "SUNUSDT", "JTOUSDT", "BELUSDT", "FETUSDT"
]

DEFAULT_LIMIT = 20

class PriceScannerHandler:
    """Binance API standartlarına uygun fiyat tarama ve sıralama"""
    
    def __init__(self):
        self.agg = MultiUserBinanceAggregator.get_instance()
        self._ticker_cache = {}
        self._cache_lock = asyncio.Lock()
        self._last_update = None
    
    async def get_multiple_prices(self, symbols: List[str], user_id: Optional[int] = None) -> List[Dict[str, any]]:
        """Çoklu sembol fiyat verisi al - Binance API standart"""
        try:
            results = []
            for symbol in symbols:
                try:
                    # Binance API standart çağrısı
                    ticker_data = await self.agg.public.spot.ticker_24hr(symbol, user_id)
                    if ticker_data:
                        formatted_data = self._format_ticker_data(ticker_data)
                        results.append(formatted_data)
                except Exception as e:
                    logger.warning(f"Price fetch failed for {symbol}: {e}")
                    continue
            
            return results
        except Exception as e:
            logger.error(f"Multiple prices error: {e}")
            return []
    
    async def get_all_prices(self, user_id: Optional[int] = None) -> List[Dict[str, any]]:
        """Tüm SCAN_SYMBOLS fiyatlarını getir"""
        return await self.get_multiple_prices(SCAN_SYMBOLS, user_id)
    
    async def get_top_gainers(self, limit: int = DEFAULT_LIMIT, user_id: Optional[int] = None) -> List[Dict[str, any]]:
        """En çok yükselen coinleri getir - Binance API standart"""
        try:
            all_prices = await self.get_all_prices(user_id)
            gainers = [p for p in all_prices if p.get('price_change_percent', 0) > 0]
            sorted_gainers = sorted(gainers, key=lambda x: x.get('price_change_percent', 0), reverse=True)
            return sorted_gainers[:limit]
        except Exception as e:
            logger.error(f"Top gainers error: {e}")
            return []
    
    async def get_top_losers(self, limit: int = DEFAULT_LIMIT, user_id: Optional[int] = None) -> List[Dict[str, any]]:
        """En çok düşen coinleri getir - Binance API standart"""
        try:
            all_prices = await self.get_all_prices(user_id)
            losers = [p for p in all_prices if p.get('price_change_percent', 0) < 0]
            sorted_losers = sorted(losers, key=lambda x: x.get('price_change_percent', 0))
            return sorted_losers[:limit]
        except Exception as e:
            logger.error(f"Top losers error: {e}")
            return []
    
    async def test_api_connection(self, user_id: Optional[int] = None) -> Dict[str, any]:
        """Binance API bağlantı testi - Binance API standart"""
        try:
            # Binance API standart ping testi
            ping_ok = await self.agg.public.spot.ping(user_id)
            server_time = await self.agg.public.spot.server_time(user_id)
            
            return {
                'status': 'success' if ping_ok else 'failed',
                'ping': ping_ok,
                'server_time': server_time,
                'message': 'Binance API bağlantısı başarılı' if ping_ok else 'Binance API bağlantısı başarısız'
            }
        except Exception as e:
            logger.error(f"API test error: {e}")
            return {
                'status': 'error',
                'message': f'API test hatası: {str(e)}'
            }
    
    def _format_ticker_data(self, ticker_data: Dict[str, any]) -> Dict[str, any]:
        """Binance API response'unu formatla"""
        try:
            symbol = ticker_data.get('symbol', '')
            price_change_percent = float(ticker_data.get('priceChangePercent', 0))
            volume = float(ticker_data.get('volume', 0))
            last_price = float(ticker_data.get('lastPrice', 0))
            price_change = float(ticker_data.get('priceChange', 0))
            
            return {
                'symbol': symbol,
                'symbol_short': symbol.replace('USDT', ''),
                'price_change_percent': price_change_percent,
                'volume': volume,
                'volume_formatted': self._format_volume(volume),
                'last_price': last_price,
                'price_formatted': self._format_price(last_price),
                'price_change': price_change,
                'price_change_formatted': f"+{price_change:.4f}" if price_change > 0 else f"{price_change:.4f}"
            }
        except Exception as e:
            logger.error(f"Ticker format error: {e}")
            return {}
    
    def _format_volume(self, volume: float) -> str:
        """Hacim değerini formatla (M/K)"""
        if volume >= 1_000_000:
            return f"${volume/1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"${volume/1_000:.1f}K"
        else:
            return f"${volume:.0f}"
    
    def _format_price(self, price: float) -> str:
        """Fiyat değerini akıllı formatla"""
        if price >= 1000:
            return f"{price:,.0f}"
        elif price >= 1:
            return f"{price:,.2f}"
        elif price >= 0.01:
            return f"{price:.4f}"
        else:
            return f"{price:.8f}"

# Handler instance
price_scanner = PriceScannerHandler()

@router.message(Command("p"))
async def cmd_price_scan(message: Message):
    """Seçilen coinlerin veya default listesinin fiyatlarını göster"""
    try:
        args = message.text.split()[1:]
        user_id = message.from_user.id
        
        if args:
            # Kullanıcının girdiği semboller
            symbols = [s.upper() + "USDT" if not s.upper().endswith('USDT') else s.upper() for s in args]
            symbols = symbols[:15]  # Max 15 sembol
        else:
            # Default sembol listesi
            symbols = SCAN_SYMBOLS
        
        prices = await price_scanner.get_multiple_prices(symbols, user_id)
        
        if not prices:
            await message.answer("❌ Fiyat verisi alınamadı")
            return
        
        response = f"📊 **{len(prices)} Coin Fiyatları**\n\n"
        response += "⚡ Coin | Değişim | Hacim | Fiyat\n"
        response += "─" * 20 + "\n"
        
        for i, price in enumerate(prices[:20], 1):  # Max 20 sonuç
            symbol = price.get('symbol_short', 'N/A')
            change_percent = price.get('price_change_percent', 0)
            volume = price.get('volume_formatted', 'N/A')
            price_val = price.get('price_formatted', 'N/A')
            
            change_emoji = "🟢" if change_percent > 0 else "🔴"
            change_text = f"+{change_percent:.2f}%" if change_percent > 0 else f"{change_percent:.2f}%"
            
            response += f"{i}. {symbol}: {change_emoji} {change_text} | {volume} | {price_val}\n"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Price scan error: {e}")
        await message.answer("❌ Fiyat tarama sırasında hata oluştu")

@router.message(Command("pg"))
async def cmd_top_gainers(message: Message):
    """En çok yükselen coinleri listeler"""
    try:
        args = message.text.split()[1:]
        user_id = message.from_user.id
        
        limit = int(args[0]) if args and args[0].isdigit() else DEFAULT_LIMIT
        limit = min(limit, 50)  # Max 50
        
        gainers = await price_scanner.get_top_gainers(limit, user_id)
        
        if not gainers:
            await message.answer("❌ Yükselen coin verisi alınamadı")
            return
        
        response = f"📈 **En Çok Yükselen {len(gainers)} Coin**\n\n"
        response += "⚡ Coin | Değişim | Hacim | Fiyat\n"
        response += "─" * 20 + "\n"
        
        for i, coin in enumerate(gainers, 1):
            symbol = coin.get('symbol_short', 'N/A')
            change_percent = coin.get('price_change_percent', 0)
            volume = coin.get('volume_formatted', 'N/A')
            price_val = coin.get('price_formatted', 'N/A')
            
            response += f"{i}. {symbol}: 🟢 {change_percent:.2f}% | {volume} | {price_val}\n"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Top gainers error: {e}")
        await message.answer("❌ Yükselen coinler alınırken hata oluştu")

@router.message(Command("pl"))
async def cmd_top_losers(message: Message):
    """En çok düşen coinleri listeler"""
    try:
        args = message.text.split()[1:]
        user_id = message.from_user.id
        
        limit = int(args[0]) if args and args[0].isdigit() else DEFAULT_LIMIT
        limit = min(limit, 50)  # Max 50
        
        losers = await price_scanner.get_top_losers(limit, user_id)
        
        if not losers:
            await message.answer("❌ Düşen coin verisi alınamadı")
            return
        
        response = f"📉 **En Çok Düşen {len(losers)} Coin**\n\n"
        response += "⚡ Coin | Değişim | Hacim | Fiyat\n"
        response += "─" * 20 + "\n"
        
        for i, coin in enumerate(losers, 1):
            symbol = coin.get('symbol_short', 'N/A')
            change_percent = coin.get('price_change_percent', 0)
            volume = coin.get('volume_formatted', 'N/A')
            price_val = coin.get('price_formatted', 'N/A')
            
            response += f"{i}. {symbol}: 🔴 {change_percent:.2f}% | {volume} | {price_val}\n"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Top losers error: {e}")
        await message.answer("❌ Düşen coinler alınırken hata oluştu")

@router.message(Command("test_api"))
async def cmd_test_api(message: Message):
    """Binance API bağlantı testi yapar"""
    try:
        user_id = message.from_user.id
        test_result = await price_scanner.test_api_connection(user_id)
        
        status_emoji = "✅" if test_result['status'] == 'success' else "❌"
        
        response = f"{status_emoji} **Binance API Test Sonucu**\n\n"
        response += f"**Durum**: {test_result['status']}\n"
        response += f"**Ping**: {'Başarılı' if test_result.get('ping') else 'Başarısız'}\n"
        
        if test_result.get('server_time'):
            response += f"*Sunucu Zamanı*: {test_result['server_time']}\n"
        
        response += f"**Mesaj**: {test_result['message']}"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"API test error: {e}")
        await message.answer("❌ API testi sırasında hata oluştu")

@router.message(Command("scan_symbols"))
async def cmd_scan_symbols(message: Message):
    """Tarama yapılan sembol listesini göster"""
    try:
        response = "🔍 **Tarama Sembol Listesi**\n\n"
        response += f"Toplam **{len(SCAN_SYMBOLS)}** sembol:\n\n"
        
        # 4 kolon halinde göster
        symbols_per_column = len(SCAN_SYMBOLS) // 4 + 1
        columns = [SCAN_SYMBOLS[i:i + symbols_per_column] for i in range(0, len(SCAN_SYMBOLS), symbols_per_column)]
        
        for i in range(symbols_per_column):
            line = ""
            for col in columns:
                if i < len(col):
                    symbol_short = col[i].replace('USDT', '')
                    line += f"`{symbol_short:8}`"
            response += line + "\n"
        
        response += f"\nÖzel sembol için: `/p btc eth ada`"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Scan symbols error: {e}")
        await message.answer("❌ Sembol listesi gösterilirken hata oluştu")

# Cache temizleme
@router.message(Command("clear_price_cache"))
async def cmd_clear_price_cache(message: Message):
    """Fiyat cache'ini temizle"""
    try:
        price_scanner._ticker_cache.clear()
        await message.answer("🧹 Fiyat cache'i temizlendi")
    except Exception as e:
        logger.error(f"Clear cache error: {e}")
        await message.answer("❌ Cache temizlenirken hata oluştu")

logger.info("✅ Price Scanner Handler başarıyla yüklendi")

# Handler loader uyumluluğu
__all__ = ['router', 'PriceScannerHandler', 'SCAN_SYMBOLS']