# analysis/orderflow.py
"""
Orderflow Analyzer - Anlık Likidite / Orderflow metrikleri

Bu modül:
- BinanceAPI (binance_a.py) üzerinden verileri çeker
- Order Book Imbalance (top N), Market Buy/Sell Volume ve Cumulative Delta hesaplar
- Her metriği [-1, +1] aralığına normalize eder ve birleşik bir pressure_score üretir
- aiogram 3.x Router pattern ile bir komut handler sağlar:
    /orderflow SYMBOL [--futures] [--levels=N]

Yapı:
- OrderflowAnalyzer: hesaplama fonksiyonları (singleton)
- create_router(binance_api): aiogram Router döndürür (aiogram 3.x uyumlu)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

# Tipleri doğrudan BinanceAPI'den almak isterseniz import edebilirsiniz.
# from .binance_a import BinanceAPI

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class OrderflowAnalyzer:
    """
    OrderflowAnalyzer - Singleton.
    Hesaplama yöntemleri: order book imbalance, market volume, cumulative delta.
    """

    _instance: Optional["OrderflowAnalyzer"] = None

    def __new__(cls, binance_api) -> "OrderflowAnalyzer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(binance_api)
            logger.info("OrderflowAnalyzer singleton oluşturuldu.")
        return cls._instance

    def _initialize(self, binance_api) -> None:
        """
        Args:
            binance_api: BinanceAPI örneği (binance_a.BinanceAPI)
        """
        self.binance = binance_api

        # Ağırlıklar: toplam 1.0
        self.weights = {
            "ob_imbalance": 0.5,
            "market_volume": 0.3,
            "cumulative_delta": 0.2,
        }

    # -------------------------
    # Yardımcı / Normalizasyon
    # -------------------------
    @staticmethod
    def _safe_div(a: float, b: float) -> float:
        """Bölme güvenliği (0 bölme önleme)."""
        return a / b if b != 0 else 0.0

    @staticmethod
    def _normalize_to_unit(x: float, clip: float = 1.0) -> float:
        """
        x değerini -clip .. +clip aralığından -1..+1'e ölçekler.
        clip pozitif ve >0 olmalı.
        """
        if clip <= 0:
            return 0.0
        v = max(min(x, clip), -clip)
        return v / clip

    # -------------------------
    # Metrik Hesaplayıcılar
    # -------------------------
    async def order_book_imbalance(self, symbol: str, top_n: int = 5, futures: bool = False) -> float:
        """
        Order Book Imbalance hesapla.
        Top N seviyeyi kullanır:
        imbalance = (sum_bid_size - sum_ask_size) / (sum_bid_size + sum_ask_size)
        Dönen değer -1..+1 arasıdır (normalize edilmiş).
        """
        try:
            if futures:
                ob = await self.binance.public.get_futures_order_book(symbol, limit=top_n)
            else:
                ob = await self.binance.public.get_order_book(symbol, limit=top_n)
            bids = ob.get("bids", [])  # list of [price, qty]
            asks = ob.get("asks", [])

            # Top N seviyeden toplam büyüklükleri al
            bid_sizes = 0.0
            ask_sizes = 0.0
            for i in range(min(top_n, len(bids))):
                # bids entries may be strings
                price_str, qty_str = bids[i][0], bids[i][1]
                # Hesaplamada yalnızca qty gerekli
                bid_sizes += float(qty_str)

            for i in range(min(top_n, len(asks))):
                price_str, qty_str = asks[i][0], asks[i][1]
                ask_sizes += float(qty_str)

            # imbalance hesaplama
            numer = bid_sizes - ask_sizes
            denom = bid_sizes + ask_sizes
            imbalance = self._safe_div(numer, denom)  # -1..+1 doğal range
            # Güvenlik: clip
            imbalance = max(min(imbalance, 1.0), -1.0)
            return imbalance
        except Exception as e:
            logger.warning(f"order_book_imbalance hata ({symbol}): {e}")
            return 0.0

    async def market_volume_from_trades(self, symbol: str, lookback_trades: int = 500, futures: bool = False) -> Tuple[float, float]:
        """
        Son trades'e bakıp market buy/sell volume hesaplar.
        Döner: (buy_volume, sell_volume)
        Not: Binance API implementasyonuna göre 'isBuyerMaker' veya 'is_buyer_maker' flag'leri farklı olabilir.
        Eğer trades endpoint mevcut değilse, boş dönülür.
        """
        buy_vol = 0.0
        sell_vol = 0.0
        try:
            # Öncelikle public.get_recent_trades veya public.get_agg_trades dene
            trades = []
            if hasattr(self.binance.public, "get_recent_trades"):
                trades = await self.binance.public.get_recent_trades(symbol, limit=lookback_trades)
            elif hasattr(self.binance.public, "get_agg_trades"):
                trades = await self.binance.public.get_agg_trades(symbol, limit=lookback_trades)
            else:
                # Eğer trades endpoint yoksa fallback: kline hacimlerini kullan (yaklaşık)
                klines = await self.binance.public.get_klines(symbol, interval="1m", limit=5)
                # klines: [open_time, open, high, low, close, volume, ...]
                for k in klines:
                    vol = float(k[5])
                    # Bu fallback çok kaba -> eşit böl
                    buy_vol += vol / 2.0
                    sell_vol += vol / 2.0
                return buy_vol, sell_vol

            # trades listesi varsa parse et
            for t in trades:
                # olası key isimleri: 'qty', 'quantity', 'q', 'amount'
                qty = None
                if isinstance(t, dict):
                    if "qty" in t:
                        qty = float(t["qty"])
                    elif "quantity" in t:
                        qty = float(t["quantity"])
                    elif "q" in t:
                        qty = float(t["q"])
                    elif "price" in t and "qty" in t:
                        qty = float(t.get("qty", 0))
                    else:
                        # try common fields
                        if "volume" in t:
                            qty = float(t["volume"])
                else:
                    # if tuple like [id, price, qty, ...] try index 2
                    try:
                        qty = float(t[2])
                    except Exception:
                        qty = 0.0

                if qty is None:
                    qty = 0.0

                # Taker side belirleme (Binance: isBuyerMaker True => taker is seller => sell trade)
                is_buyer_maker = None
                if isinstance(t, dict):
                    if "isBuyerMaker" in t:
                        is_buyer_maker = bool(t["isBuyerMaker"])
                    elif "is_buyer_maker" in t:
                        is_buyer_maker = bool(t["is_buyer_maker"])
                    elif "side" in t:
                        # bazı API'ler 'side': 'BUY' veya 'SELL' belirtebilir
                        side = t["side"].upper()
                        if side == "BUY":
                            is_buyer_maker = False
                        elif side == "SELL":
                            is_buyer_maker = True

                # Eğer is_buyer_maker True ise taker satıcı -> trade bir SELL (piyasa satışı)
                if is_buyer_maker is True:
                    sell_vol += qty
                elif is_buyer_maker is False:
                    buy_vol += qty
                else:
                    # Bilinmeyen -> kabaca price hareketine bak (fiyat artmış ise buy ağırlıklı)
                    # Bazı trade objelerinde 'm' veya 'is_buyer_maker' yoktur; bu durumda safe fallback:
                    if isinstance(t, dict) and ("price" in t and "prevPrice" in t):
                        p = float(t["price"])
                        pp = float(t["prevPrice"])
                        if p >= pp:
                            buy_vol += qty
                        else:
                            sell_vol += qty
                    else:
                        # eşit böl
                        buy_vol += qty / 2.0
                        sell_vol += qty / 2.0

            return buy_vol, sell_vol
        except Exception as e:
            logger.warning(f"market_volume_from_trades hata ({symbol}): {e}")
            return 0.0, 0.0

    async def cumulative_delta(self, symbol: str, lookback_trades: int = 500, futures: bool = False) -> float:
        """
        Cumulative delta: (sum_buy_volume - sum_sell_volume) / total_volume -> normalize edilmiş -1..+1
        """
        buy_vol, sell_vol = await self.market_volume_from_trades(symbol, lookback_trades, futures)
        total = buy_vol + sell_vol
        delta = buy_vol - sell_vol
        if total == 0:
            return 0.0
        raw = self._safe_div(delta, total)  # doğal -1..+1 aralığı
        raw = max(min(raw, 1.0), -1.0)
        return raw

    # -------------------------
    # Birleştirilmiş Skor
    # -------------------------
    async def compute_orderflow_score(
        self,
        symbol: str,
        *,
        futures: bool = False,
        top_n: int = 5,
        lookback_trades: int = 500,
    ) -> Dict[str, object]:
        """
        Tüm metrikleri hesaplayıp birleşik bir pressure score üretir.
        Dönen dict:
        {
            'symbol': str,
            'ob_imbalance': float,         # -1..+1
            'buy_volume': float,
            'sell_volume': float,
            'market_volume_imbalance': float, # -1..+1
            'cumulative_delta': float,     # -1..+1
            'pressure_score': float,       # -1..+1 (ağırlıklı birleşim)
            'details': {...}
        }
        """
        ob_task = asyncio.create_task(self.order_book_imbalance(symbol, top_n, futures))
        cd_task = asyncio.create_task(self.cumulative_delta(symbol, lookback_trades, futures))
        mv_task = asyncio.create_task(self.market_volume_from_trades(symbol, lookback_trades, futures))

        ob = await ob_task
        cumulative = await cd_task
        buy_vol, sell_vol = await mv_task

        # market volume imbalance normalize: (buy - sell) / (buy + sell)
        mv_imbalance = 0.0
        if (buy_vol + sell_vol) != 0:
            mv_imbalance = self._safe_div((buy_vol - sell_vol), (buy_vol + sell_vol))
            mv_imbalance = max(min(mv_imbalance, 1.0), -1.0)

        # Ağırlıklı kombinasyon
        w = self.weights
        pressure = (
            w["ob_imbalance"] * ob
            + w["market_volume"] * mv_imbalance
            + w["cumulative_delta"] * cumulative
        )

        # ensure in bounds
        pressure = max(min(pressure, 1.0), -1.0)

        return {
            "symbol": symbol.upper(),
            "ob_imbalance": float(ob),
            "buy_volume": float(buy_vol),
            "sell_volume": float(sell_vol),
            "market_volume_imbalance": float(mv_imbalance),
            "cumulative_delta": float(cumulative),
            "pressure_score": float(pressure),
            "weights": w,
        }


# -------------------------
# Aiogram Router (3.x) Helper
# -------------------------
def create_router(binance_api) -> Router:
    """
    Aiogram Router üretir. Kullanım:
        router = create_router(binance_api)
        dp.include_router(router)

    Komut formatı:
        /orderflow BTCUSDT
        /orderflow BTCUSDT --futures
        /orderflow BTCUSDT --levels=10 --trades=1000
    """
    router = Router()
    analyzer = OrderflowAnalyzer(binance_api)

    @router.message(Command("orderflow"))
    async def handle_orderflow_cmd(message: Message) -> None:
        """
        /orderflow handler
        """
        try:
            # Mesaj içeriğini parçala
            parts = (message.text or "").split()
            if len(parts) < 2:
                await message.reply("Kullanım: /orderflow SYMBOL [--futures] [--levels=N] [--trades=M]\nÖrnek: /orderflow BTCUSDT --levels=5 --trades=500")
                return

            symbol = parts[1]
            futures = False
            top_n = 5
            trades = 500

            for p in parts[2:]:
                p = p.strip()
                if p.startswith("--futures"):
                    futures = True
                elif p.startswith("--levels="):
                    try:
                        top_n = int(p.split("=", 1)[1])
                    except Exception:
                        top_n = 5
                elif p.startswith("--trades="):
                    try:
                        trades = int(p.split("=", 1)[1])
                    except Exception:
                        trades = 500

            # Hemen hesapla (senkron bloklamayacak)
            await message.reply(f"🔎 {symbol.upper()} için hesaplanıyor... (levels={top_n}, trades={trades}, futures={futures})")

            result = await analyzer.compute_orderflow_score(
                symbol,
                futures=futures,
                top_n=top_n,
                lookback_trades=trades,
            )

            # Basit, okunaklı metinle cevap
            score = result["pressure_score"]
            direction = "🔴 SATIŞ BASKISI" if score < -0.1 else ("🟢 ALIM BASKISI" if score > 0.1 else "⚪️ NÖTR")
            lines = [
                f"📌 Symbol: {result['symbol']}",
                f"📊 Pressure Score: {score:+.4f} ({direction})",
                f"🧾 Order Book Imbalance (top {top_n}): {result['ob_imbalance']:+.4f}",
                f"📈 Market Volume Imbalance: {result['market_volume_imbalance']:+.4f}",
                f"📉 Cumulative Delta: {result['cumulative_delta']:+.4f}",
                f"💵 Buy volume: {result['buy_volume']:.6f}",
                f"💸 Sell volume: {result['sell_volume']:.6f}",
            ]
            await message.reply("\n".join(lines))
        except Exception as e:
            logger.exception("orderflow handler hata")
            await message.reply(f"Hata: {e}")

    return router


# -------------------------
# Örnek kullanım (bot entegrasyonu)
# -------------------------
# Bu kısım gerçek çalıştırmada başka bir dosyada yapılmalı. Buraya sadece rehber amaçlı örnek bırakıyorum.
#
# from aiogram import Bot, Dispatcher
# from aiogram.fsm.storage.memory import MemoryStorage
# import asyncio
#
# async def setup_and_run():
#     bot = Bot(token="YOUR_TELEGRAM_BOT_TOKEN", parse_mode="HTML")
#     dp = Dispatcher(storage=MemoryStorage())
#
#     # BinanceAPI örneğini oluşturun (binance_a.BinanceAPI)
#     http_client = BinanceHTTPClient(api_key="...", secret_key="...")
#     cb = CircuitBreaker(...)
#     binance = BinanceAPI(http_client, cb)
#
#     router = create_router(binance)
#     dp.include_router(router)
#
#     await dp.start_polling(bot)
#
# asyncio.run(setup_and_run())
#
# -------------------------
# Notlar:
# - Binance public API'nizin isimlendirmesi farklı olabilir (get_recent_trades vs get_agg_trades).
#   Kod her iki alternatifi de deneyecek şekilde yazıldı; yoksa kline fallback yapılır.
# - 'isBuyerMaker' flag'inin anlamı farklı implementasyonlarda kafa karıştırabilir. Genelde:
#       isBuyerMaker == True  -> taker is seller => satış baskısı
#       isBuyerMaker == False -> taker is buyer  => alım baskısı
#   Yine de canlı test edip kendi API implementasyonunuza göre doğrulamanızı öneririm.
#
# - Performans: büyük trade lookback sayıları (ör. 5000) istenirse API limitlerine dikkat edin.
# - Bu modül, çatı bot projesine kolayca entegre edilebilir; analiz fonksiyonları bağımsızdır.
