"""
analysis/derivs.py
Türev Piyasa Sentiment Modülü

Özellikler:
- BinanceAPI (utils/binance/binance_a.BinanceAPI) üzerinden veri çeker
- Funding Rate, Open Interest, Taker Buy/Sell Ratio, Long/Short Ratio hesaplar
- Metric'leri normalize eder ve 
* -1 (bearish) .. +1 (bullish) arası tek bir sentiment skoru üretir
- aiogram 3.x Router pattern ile /derivs_sentiment <SYMBOL> komutu sunar

Kullanım (örnek):
    from aiogram import Bot
    from aiogram.types import BotCommand
    from aiogram import Dispatcher
    from aiogram.types import Message
    from utils.binance.binance_a import BinanceAPI
    from utils.binance.binance_request import BinanceHTTPClient
    from utils.binance.binance_circuit_breaker import CircuitBreaker
    import derivs

    http_client = BinanceHTTPClient(api_key="...", secret_key="...")
    cb = CircuitBreaker(...)
    binance = BinanceAPI(http_client, cb)

    # aiogram bot ve dispatcher oluşturup derivs.router'u kaydedin
    dp.include_router(derivs.router)
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple, List

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

# import your BinanceAPI aggregator
from utils.binance.binance_a import BinanceAPI

logger = logging.getLogger(__name__)
router = Router(name="derivs_router")

# -------- Configuration & weights (ayarlanabilir) ----------
# Her metric için ağırlık (toplam 1'e normalize edilir)
METRIC_WEIGHTS = {
    "funding_rate": 0.30,
    "open_interest": 0.25,
    "taker_ratio": 0.25,
    "long_short_ratio": 0.20
}

# Zaman pencereleri (örnek)
FUNDING_LOOKBACK = 8  # son 8 funding period (8 * 8h tipikyse ~64 saat)
OI_LOOKBACK_SECONDS = 86400  # 24 saat (futures open interest için kullanılabilir)

# Normalizasyon sınırları (konservatif)
# Bu sınırlar aşılıyorsa clipping uygulanır — gerekirse canlı veriye göre güncelleyin.
NORMALIZATION_BOUNDS = {
    "funding_rate_pct": (-0.05, 0.05),  # -5% ile +5% funding (çok uç)
    "open_interest_change_pct": (-0.5, 0.5),  # -50%..+50% 24h değişim
    "taker_ratio": (0.0, 10.0),  # ratio (buy/sell) 0..10
    "long_short_ratio": (0.01, 100.0)  # long/short ratio aralığı (1..100 gibi)
}


# --------- Yardımcı fonksiyonlar ----------
def clip(value: float, bounds: Tuple[float, float]) -> float:
    lo, hi = bounds
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def normalize_to_minus1_plus1(value: float, lo: float, hi: float, invert: bool = False) -> float:
    """
    value'yi [lo,hi] aralığından -1..+1 aralığına çevirir.
    invert=True ise yüksek değer => bearish (negatif) kabul edilir.
    """
    if hi == lo:
        return 0.0
    v = (value - lo) / (hi - lo)  # 0..1
    v = clip(v, (0.0, 1.0))
    if invert:
        v = 1.0 - v
    return v * 2.0 - 1.0  # map 0..1 -> -1..+1


def weight_metrics(scores: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Her metric için ağırlıklı ortalama alır.
    scores: metric_name -> -1..+1
    weights: metric_name -> ağırlık (normalize edilmemiş olabilir)
    """
    # normalize weights
    total = sum(weights.values()) or 1.0
    normalized = {k: w / total for k, w in weights.items()}
    combined = 0.0
    for k, s in scores.items():
        w = normalized.get(k, 0.0)
        combined += s * w
    # clip output -1..+1
    return clip(combined, (-1.0, 1.0))


# ----------------------------
# Core data-gathering functions
# ----------------------------
async def fetch_funding_rate_avg(binance: BinanceAPI, symbol: str, limit: int = FUNDING_LOOKBACK) -> Optional[float]:
    """
    Son `limit` funding rate kayıtlarının ortalamasını getir (yüzde bazında, örn. 0.0001 -> 0.01%).
    Dönen değer funding rate'in ortalamasıdır (örneğin 0.0001).
    """
    try:
        # Beklenen method: get_funding_rate_history(symbol, limit)
        history = await binance.get_funding_rate_history(symbol, limit=limit)
        if not history:
            return None
        # history elemanlarının her biri dict, 'fundingRate' veya 'fundingRate' anahtarı olabilir
        rates = []
        for item in history:
            if item is None:
                continue
            # bazı API'ler 'fundingRate' string, some float
            fr = item.get("fundingRate") if isinstance(item, dict) else None
            if fr is None:
                # fallback: bazı implementasyonlar 'fundingRate' yerine 'rate' kullanır
                fr = item.get("rate") if isinstance(item, dict) else None
            if fr is None:
                continue
            try:
                rates.append(float(fr))
            except Exception:
                continue
        if not rates:
            return None
        avg = sum(rates) / len(rates)
        return avg
    except Exception as e:
        logger.exception("fetch_funding_rate_avg error: %s", e)
        return None


async def fetch_open_interest_change_pct(binance: BinanceAPI, symbol: str) -> Optional[float]:
    """
    Open interest'in 24 saatlik değişimini yüzde olarak döner (örnek: 0.12 => +12%).
    Eğer doğrudan API yoksa None döner.
    """
    try:
        # Beklenen: get_futures_open_interest, get_futures_open_interest_history veya benzeri
        current = await binance.get_open_interest(symbol)
        # current örnek: {'openInterest': '12345.0', 'time': 162...}
        ci = None
        if isinstance(current, dict):
            ci = current.get("openInterest") or current.get("openInterestValue") or current.get("oi")
        if ci is None:
            return None
        current_oi = float(ci)
        # fallback: bazı implementasyonlarda geçmiş veriyi almak gerekebilir; burada basit yaklaşım:
        # exchange'den 24 saat önceki open interest'i almaya çalış
        # Eğer BinanceAPI içinde history yoksa geriye None döner
        # Öneri: binance.public.get_futures_open_interest_history(symbol, period='24h', limit=2) olabilir
        history = []
        try:
            # many public API wrappers implement get_futures_open_interest_history
            history = await binance.public.get_futures_open_interest_history(symbol, period="24h", limit=2)
        except Exception:
            # fallback: deneyelim binance.public.get_futures_open_interest_history farklı isimde olabilir
            try:
                history = await binance.public.get_futures_open_interest(symbol, limit=2)
            except Exception:
                history = []
        prev_oi = None
        if isinstance(history, list) and len(history) >= 1:
            # pick the earlier entry if available
            # try many key names
            first = history[0]
            prev_val = first.get("openInterest") or first.get("oi") or first.get("value")
            if prev_val:
                prev_oi = float(prev_val)
        if prev_oi is None:
            # Eğer geçmiş veri alınamadıysa None döner (güvenli fallback)
            return None
        change_pct = (current_oi - prev_oi) / prev_oi if prev_oi != 0 else 0.0
        return change_pct
    except Exception as e:
        logger.exception("fetch_open_interest_change_pct error: %s", e)
        return None


async def fetch_taker_buy_sell_ratio(binance: BinanceAPI, symbol: str) -> Optional[float]:
    """
    Taker buy / taker sell ratio (24h).
    Eğer ratio = totalBuyVolume / totalSellVolume döner.
    Null dönerse endpoint yok demektir.
    """
    try:
        # Beklenen: public.get_futures_24hr_ticker(symbol) ya da benzeri
        tickers = await binance.get_24h_stats(symbol, futures=True)
        # tickers bazen dict veya list dönebilir. Eğer dict ise içinde takerBuyBaseVolume, takerSellBaseVolume olabilir
        if isinstance(tickers, dict):
            buy_vol = tickers.get("takerBuyBaseVol") or tickers.get("takerBuyBaseVolume") or tickers.get("takerBuyVolume")
            sell_vol = tickers.get("takerSellBaseVol") or tickers.get("takerSellBaseVolume") or tickers.get("takerSellVolume")
            if buy_vol is None or sell_vol is None:
                # bazı implementasyonlarda sadece quote vol olabilir
                buy_vol = tickers.get("takerBuyQuoteVol") or buy_vol
                sell_vol = tickers.get("takerSellQuoteVol") or sell_vol
            if buy_vol is None or sell_vol is None:
                return None
            buy = float(buy_vol)
            sell = float(sell_vol) if float(sell_vol) != 0 else 1e-9
            return buy / sell
        elif isinstance(tickers, list):
            # list ise ilgili dict'i bul
            for t in tickers:
                if t.get("symbol") == symbol.upper():
                    return await fetch_taker_buy_sell_ratio_from_ticker_dict(t)
        return None
    except Exception as e:
        logger.exception("fetch_taker_buy_sell_ratio error: %s", e)
        return None


async def fetch_taker_buy_sell_ratio_from_ticker_dict(ticker: Dict[str, Any]) -> Optional[float]:
    try:
        buy = ticker.get("takerBuyBaseVol") or ticker.get("takerBuyBaseVolume") or ticker.get("takerBuyVolume")
        sell = ticker.get("takerSellBaseVol") or ticker.get("takerSellBaseVolume") or ticker.get("takerSellVolume")
        if buy is None or sell is None:
            buy = ticker.get("takerBuyQuoteVol") or buy
            sell = ticker.get("takerSellQuoteVol") or sell
        if buy is None or sell is None:
            return None
        b = float(buy)
        s = float(sell) if float(sell) != 0 else 1e-9
        return b / s
    except Exception:
        return None


async def fetch_long_short_ratio(binance: BinanceAPI, symbol: str) -> Optional[float]:
    """
    Long/Short ratio (toplam long / toplam short). Binance'in public 'longShortRatio' endpoint'i varsa kullan.
    Eğer alınamazsa None döner.
    """
    try:
        # birçok wrapper'da get_futures_long_short_ratio(symbol, period='24h', limit=1) olabilir
        try:
            resp = await binance.public.get_futures_long_short_ratio(symbol, period="24h", limit=1)
        except Exception:
            # alternatif isim
            resp = await binance.public.get_futures_long_short_account_ratio(symbol, period="24h", limit=1)

        if not resp:
            return None
        # resp list veya dict olabilir
        if isinstance(resp, list) and resp:
            item = resp[0]
        elif isinstance(resp, dict):
            item = resp
        else:
            return None
        # item içindeki anahtarlar çeşitli olabilir: "longShortRatio", "buySellRatio", "longShort"
        val = item.get("longShortRatio") or item.get("longShort") or item.get("ratio") or item.get("buySellRatio")
        if val is None:
            # bazı API'ler longShortRatio'yi string '12.34' olarak döner
            # bazen ayrıca 'longAccount' ve 'shortAccount' alanları da olabilir
            la = item.get("longAccount") or item.get("long")
            sa = item.get("shortAccount") or item.get("short")
            if la is not None and sa is not None:
                la = float(la)
                sa = float(sa) if float(sa) != 0 else 1e-9
                return la / sa
            return None
        return float(val)
    except Exception as e:
        logger.exception("fetch_long_short_ratio error: %s", e)
        return None


# ----------------------------
# Metric -> score mapping
# ----------------------------
def score_from_funding_rate(avg_rate: float) -> float:
    """
    Funding rate: pozitif funding genelde longların kısa ödemesi (long baskısı),
    Negatif funding genelde short baskısı.
    Burada funding rate'i normalize edip -1..+1 döndürüyoruz.
    """
    # Convert bounds
    lo, hi = NORMALIZATION_BOUNDS["funding_rate_pct"]
    clipped = clip(avg_rate, (lo, hi))
    # Normalize: pozitif funding => bullish (+), negatif => bearish (-)
    return normalize_to_minus1_plus1(clipped, lo, hi, invert=False)


def score_from_oi_change(change_pct: float) -> float:
    """
    Open interest artışı genelde trend onaycı (bullish veya bearish olabilir, price yönüne bakılmalı).
    Burada basit heuristic: OI artışı (pozitif) => momentum arttı -> eğer fiyat da artıyorsa bullish,
    fakat biz sadece OI'yi kullanıyoruz; bu yüzden OI artışını nötr-pozitif işaretle ödüllendiriyoruz.
    (Daha sofistike model: price change ile çarp.)
    """
    lo, hi = NORMALIZATION_BOUNDS["open_interest_change_pct"]
    clipped = clip(change_pct, (lo, hi))
    # OI artışı => bullish, azalış => bearish
    return normalize_to_minus1_plus1(clipped, lo, hi, invert=False)


def score_from_taker_ratio(ratio: float) -> float:
    """
    Taker buy/sell ratio >1 ise alım baskısı (bullish), <1 ise satış baskısı (bearish).
    Normalize etmek için ratio'yu log ölçeğe alabiliriz.
    """
    lo, hi = NORMALIZATION_BOUNDS["taker_ratio"]
    clipped = clip(ratio, (lo + 1e-9, hi))
    # map [lo..hi] -> -1..+1, mid point 1 -> 0
    # shift domain to center at 1
    # transform: val' = ratio - 1 in [-1..(hi-1)]
    return normalize_to_minus1_plus1(clipped - 1.0, (lo - 1.0), (hi - 1.0), invert=False)


def score_from_long_short_ratio(ratio: float) -> float:
    """
    Long/Short ratio: >1 => long'lar daha fazla => bullish (muhtemelen)
    Ancak bazı durumlarda yüksek long/short = aşırı long (düzeltme riski). Basitçe normalize ediyoruz.
    """
    lo, hi = NORMALIZATION_BOUNDS["long_short_ratio"]
    clipped = clip(ratio, (lo, hi))
    # center at 1 -> 0
    return normalize_to_minus1_plus1(clipped - 1.0, (lo - 1.0), (hi - 1.0), invert=False)


# ----------------------------
# Top-level sentiment hesaplama
# ----------------------------
async def compute_derivatives_sentiment(binance: BinanceAPI, symbol: str) -> Dict[str, Any]:
    """
    Verilen sembol için türev piyasası sentiment'ini hesaplar.
    Dönen dict:
    {
        'symbol': symbol,
        'metrics': {
            'funding_rate_avg': value,
            'open_interest_change_pct': value,
            'taker_buy_sell_ratio': value,
            'long_short_ratio': value
        },
        'scores': {
            'funding_rate': -0..+1,
            'open_interest': -1..+1,
            'taker_ratio': -1..+1,
            'long_short_ratio': -1..+1
        },
        'combined_score': -1..+1
    }
    """
    symbol = symbol.upper()
    tasks = [
        fetch_funding_rate_avg(binance, symbol, limit=FUNDING_LOOKBACK),
        fetch_open_interest_change_pct(binance, symbol),
        fetch_taker_buy_sell_ratio(binance, symbol),
        fetch_long_short_ratio(binance, symbol)
    ]

    # Concurrently fetch
    funding_avg, oi_change, taker_ratio, long_short = await asyncio.gather(*tasks, return_exceptions=False)

    metrics = {
        "funding_rate_avg": funding_avg,
        "open_interest_change_pct": oi_change,
        "taker_buy_sell_ratio": taker_ratio,
        "long_short_ratio": long_short
    }

    # Compute individual scores; None -> neutral (0.0)
    scores = {}
    try:
        scores["funding_rate"] = score_from_funding_rate(funding_avg) if funding_avg is not None else 0.0
    except Exception:
        scores["funding_rate"] = 0.0
    try:
        scores["open_interest"] = score_from_oi_change(oi_change) if oi_change is not None else 0.0
    except Exception:
        scores["open_interest"] = 0.0
    try:
        scores["taker_ratio"] = score_from_taker_ratio(taker_ratio) if taker_ratio is not None else 0.0
    except Exception:
        scores["taker_ratio"] = 0.0
    try:
        scores["long_short_ratio"] = score_from_long_short_ratio(long_short) if long_short is not None else 0.0
    except Exception:
        scores["long_short_ratio"] = 0.0

    combined = weight_metrics(scores, METRIC_WEIGHTS)

    return {
        "symbol": symbol,
        "metrics": metrics,
        "scores": scores,
        "combined_score": combined
    }


# ----------------------------
# aiogram Router command
# ----------------------------
@router.message(Command(commands=["derivs_sentiment"]))
async def derivs_sentiment_command(message: Message) -> None:
    """
    Komut formatı:
    /derivs_sentiment BTCUSDT
    """
    text = message.text or ""
    parts = text.strip().split()
    if len(parts) < 2:
        await message.reply("Kullanım: /derivs_sentiment <SYMBOL>  (ör: /derivs_sentiment BTCUSDT)")
        return
    symbol = parts[1].upper()

    # Burada BinanceAPI singleton'ınızı elde edin. Kullanıcı koduna göre değişebilir.
    # Örnek: global ya da injection yoluyla sağlanabilir. Burada basit bir erişim varsayımı:
    try:
        # Eğer uygulamanızda BinanceAPI örneğini global veya context'te tutuyorsanız onu alın.
        # Aşağıdaki satırı kendi entegrasyonunuza göre uyarlayın:
        from utils.binance.binance_request import BinanceHTTPClient
        from utils.binance.binance_circuit_breaker import CircuitBreaker
        # Bu sadece örnek; gerçek uygulamada http client'ı başlatılmış tek örneği kullanın.
        http_client = BinanceHTTPClient()  # Eğer parametre gerekiyorsa uygulamanızın örneğini kullanın
        cb = CircuitBreaker()
        binance = BinanceAPI(http_client, cb)
    except Exception:
        # Eğer uygulamanızda hali hazırda yaratılmış bir BinanceAPI örneği varsa, onu kullanın.
        # Burada fallback: modul-level singleton'dan bağlanmayı deniyoruz:
        try:
            binance = BinanceAPI._instance  # type: ignore
            if not binance:
                raise RuntimeError("BinanceAPI instance not initialized")
        except Exception as e:
            logger.exception("BinanceAPI örneği alınamadı: %s", e)
            await message.reply("Hata: BinanceAPI örneği bulunamadı veya başlatılmamış. Uygulamayı kontrol edin.")
            return

    await message.reply(f"📡 {symbol} için türev sentiment hesaplanıyor... (veri çekiliyor)")

    try:
        result = await compute_derivatives_sentiment(binance, symbol)
    except Exception as e:
        logger.exception("compute_derivatives_sentiment hata: %s", e)
        await message.reply(f"Hata: Sentiment hesaplanamadı: {e}")
        return

    combined = result["combined_score"]
    metrics = result["metrics"]
    scores = result["scores"]

    # Biraz güzel formatlama (Türkçe)
    def fmt(x: Optional[float], prec: int = 6) -> str:
        return "N/A" if x is None else f"{x:.{prec}f}"

    sentiment_text = "BULLISH" if combined > 0.2 else ("BEARISH" if combined < -0.2 else "NEUTRAL / MIXED")
    emoji = "🟢" if combined > 0.2 else ("🔴" if combined < -0.2 else "🟡")

    text_lines = [
        f"{emoji} <b>{symbol} Türev Piyasa Sentiment</b>",
        f"Toplam Skor: <b>{combined:.4f}</b> ({sentiment_text})",
        "",
        "<b>Metrics</b>:",
        f"- Funding Rate (avg): {fmt(metrics['funding_rate_avg'], 8)}",
        f"- Open Interest 24h change: {fmt(metrics['open_interest_change_pct'], 6)}",
        f"- Taker Buy/Sell Ratio: {fmt(metrics['taker_buy_sell_ratio'], 6)}",
        f"- Long/Short Ratio: {fmt(metrics['long_short_ratio'], 6)}",
        "",
        "<b>Scores (normalized)</b>:",
        f"- Funding Rate score: {scores['funding_rate']:.4f}",
        f"- Open Interest score: {scores['open_interest']:.4f}",
        f"- Taker ratio score: {scores['taker_ratio']:.4f}",
        f"- Long/Short score: {scores['long_short_ratio']:.4f}",
        "",
        "Not: Bu model basit heuristikler içerir. Daha hassas sonuç için price action ile korelasyon, volüm ağırlıklı normalizasyon, ve daha uzun tarihsel verilerle calibrasyon önerilir."
    ]

    await message.reply("\n".join(text_lines), parse_mode="HTML")


# ----------------------------
# Eğer modül bağımsız çalıştırılırsa örnek kullanım
# ----------------------------
if __name__ == "__main__":
    # Sadece test/örnek amaçlıdır. Gerçek bot uygulamasında aiogram entegrasyonu kullanın.
    import asyncio
    from utils.binance.binance_request import BinanceHTTPClient
    from utils.binance.binance_circuit_breaker import CircuitBreaker

    async def _main():
        http_client = BinanceHTTPClient()  # init with config in real app
        cb = CircuitBreaker()
        binance = BinanceAPI(http_client, cb)
        res = await compute_derivatives_sentiment(binance, "BTCUSDT")
        print("Result:", res)

    asyncio.run(_main())
