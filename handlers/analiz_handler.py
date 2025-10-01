"""
handlers/analiz_handler.py - Geliştirilmiş Analiz Handler
"""

import logging
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from analysis.analysis_a import get_analysis_aggregator
from utils.binance.binance_a import BinanceAPI
from config import get_config

router = Router()
logger = logging.getLogger(__name__)

class AnalysisStates(StatesGroup):
    waiting_symbol = State()
    waiting_timeframe = State()

# Global instances
_analyzer = None
_binance_api = None

async def get_analyzer() -> Optional[any]:
    """Analyzer instance'ını getir"""
    global _analyzer, _binance_api
    
    if _analyzer is None:
        try:
            config = await get_config()
            
            # Binance API'yi sadece trading enabled ise başlat
            if config.ENABLE_TRADING:
                from utils.binance.binance_request import BinanceHTTPClient
                from utils.binance.binance_circuit_breaker import CircuitBreaker
                
                http_client = BinanceHTTPClient(
                    api_key=config.BINANCE_API_KEY,
                    secret_key=config.BINANCE_API_SECRET
                )
                cb = CircuitBreaker()
                _binance_api = BinanceAPI(http_client, cb)
            else:
                # Mock API for analysis only mode
                _binance_api = None
            
            _analyzer = get_analysis_aggregator(_binance_api)
            
        except Exception as e:
            logger.error(f"Analyzer başlatma hatası: {e}")
            return None
    
    return _analyzer

@router.message(Command("analysis", "analiz", "a"))
async def start_analysis(message: Message, state: FSMContext):
    """Analiz başlatma"""
    analyzer = await get_analyzer()
    if not analyzer:
        await message.answer("❌ Analiz modülü başlatılamadı. Lütfen config kontrol edin.")
        return
    
    await message.answer(
        "📊 **Analiz Modülü**\n\n"
        "Lütfen analiz yapmak istediğiniz sembolü girin:\n"
        "Örnek: `BTCUSDT`, `ETHUSDT`\n\n"
        "İptal için /cancel",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AnalysisStates.waiting_symbol)

@router.message(Command("t"))
async def quick_analysis(message: Message):
    """Hızlı analiz komutu"""
    try:
        args = message.text.strip().split()
        if len(args) < 2:
            await message.answer(
                "❌ Lütfen sembol belirtin. Örnek: `/t BTCUSDT`\n"
                "Çoklu sembol: `/t BTCUSDT,ETHUSDT`",
                parse_mode="Markdown"
            )
            return

        symbols = [s.strip().upper() for s in args[1].split(',')]
        analyzer = await get_analyzer()
        
        if not analyzer:
            await message.answer("❌ Analiz modülü hazır değil")
            return

        results = []
        for symbol in symbols[:3]:  # Maksimum 3 sembol
            await message.answer(f"🔍 `{symbol}` analiz ediliyor...", parse_mode="Markdown")
            
            try:
                result = await analyzer.run_analysis(symbol)
                results.append((symbol, result))
            except Exception as e:
                logger.error(f"Analiz hatası {symbol}: {e}")
                results.append((symbol, None))

        # Sonuçları formatla
        response = "📊 **ANALİZ SONUÇLARI**\n\n"
        
        for symbol, result in results:
            if not result:
                response += f"❌ `{symbol}`: Analiz başarısız\n\n"
                continue
                
            # Skor renk emojisi
            score_emoji = "🟢" if result.gnosis_signal > 0.3 else \
                         "🔴" if result.gnosis_signal < -0.3 else "🟡"
            
            response += (
                f"{score_emoji} **{symbol}**\n"
                f"• Skor: `{result.gnosis_signal:.3f}`\n"
                f"• Güven: `{result.confidence:.2f}`\n"
                f"• Rejim: `{result.market_regime}`\n"
                f"• Öneri: `{result.recommendation}`\n"
                f"• Pozisyon: `{result.position_size:.1%}`\n\n"
            )

        await message.answer(response, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Hızlı analiz hatası: {e}")
        await message.answer("❌ Analiz sırasında hata oluştu")

@router.message(Command("multianalysis", "ma"))
async def multi_analysis(message: Message):
    """Çoklu sembol analizi"""
    try:
        args = message.text.strip().split()
        if len(args) < 2:
            # Varsayılan semboller
            symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        else:
            symbols = [s.strip().upper() for s in args[1].split(',')]
        
        analyzer = await get_analyzer()
        if not analyzer:
            await message.answer("❌ Analiz modülü hazır değil")
            return
        
        await message.answer(f"🔍 {len(symbols)} sembol analiz ediliyor...")
        
        # Paralel analiz
        tasks = []
        for symbol in symbols[:5]:  # Maksimum 5 sembol
            tasks.append(analyzer.run_analysis(symbol))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Sırala (skora göre)
        sorted_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Analiz hatası {symbols[i]}: {result}")
                continue
            sorted_results.append((symbols[i], result))
        
        sorted_results.sort(key=lambda x: x[1].gnosis_signal, reverse=True)
        
        # Formatlı response
        response = "🏆 **SIRALI ANALİZ SONUÇLARI**\n\n"
        
        for symbol, result in sorted_results:
            trend_icon = "📈" if result.gnosis_signal > 0 else "📉"
            response += (
                f"{trend_icon} `{symbol:<10} | Skor: {result.gnosis_signal:7.3f} | "
                f"{result.recommendation:<12} | {result.position_size:5.1%}`\n"
            )
        
        await message.answer(f"```\n{response}\n```", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Çoklu analiz hatası: {e}")
        await message.answer("❌ Çoklu analiz hatası")

@router.message(StateFilter(AnalysisStates.waiting_symbol))
async def process_symbol(message: Message, state: FSMContext):
    """Sembol işleme"""
    symbol = message.text.upper().strip()
    
    # Sembol validasyonu
    if not all(c.isalnum() or c in ['/', '-', '_'] for c in symbol):
        await message.answer("❌ Geçersiz sembol formatı. Örnek: BTCUSDT")
        return
    
    await state.update_data(symbol=symbol)
    
    await message.answer(
        f"🔍 `{symbol}` için analiz başlatılıyor...\n"
        f"Bu işlem 15-30 saniye sürebilir.",
        parse_mode="Markdown"
    )
    
    try:
        analyzer = await get_analyzer()
        result = await analyzer.run_analysis(symbol)
        
        # Detaylı response
        response = (
            f"📊 **{symbol} DETAYLI ANALİZ**\n\n"
            f"🎯 **Genel Skor**: `{result.gnosis_signal:.3f}`\n"
            f"💪 **Güven Seviyesi**: `{result.confidence:.2f}`\n"
            f"🏛️ **Piyasa Rejimi**: `{result.market_regime}`\n\n"
            f"📈 **Modül Skorları**:\n"
        )
        
        for module, score in result.module_scores.items():
            module_icon = "🟢" if score > 0.3 else "🔴" if score < -0.3 else "🟡"
            response += f"{module_icon} {module}: `{score:.3f}`\n"
        
        response += f"\n✅ **Öneri**: `{result.recommendation}`\n"
        response += f"💰 **Pozisyon Büyüklüğü**: `{result.position_size:.1%}`\n\n"
        response += f"⏰ {result.timestamp}"
        
        await message.answer(response, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Analiz hatası: {e}")
        await message.answer("❌ Analiz sırasında hata oluştu")
    
    await state.clear()

@router.message(Command("cancel"))
async def cancel_analysis(message: Message, state: FSMContext):
    """Analizi iptal et"""
    await state.clear()
    await message.answer("❌ Analiz iptal edildi", reply_markup=ReplyKeyboardRemove())

# Error handler
@router.errors()
async def analysis_error_handler(event, **kwargs):
    """Analiz hata handler'ı"""
    logger.error(f"Analiz handler hatası: {event.exception}")
    # Hata mesajını kullanıcıya gönderme (güvenlik için)
    return "❌ İşlem sırasında bir hata oluştu"
