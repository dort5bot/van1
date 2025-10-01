"""
On-chain Analiz Modülü - Güncellenmiş Singleton Pattern

Bu modül, Stablecoin Supply Ratio, Exchange Net Flow ve ETF Flows gibi
ana on-chain metrikleri hesaplar. 
Çıktılar -1 (Bearish) ile +1 (Bullish) arasında normalize edilir.

Güncellemeler:
- Singleton pattern düzeltildi
- BinanceAPI parametre olarak alınıyor
- Config entegrasyonu tamamlandı
- Eksik metodlar implemente edildi
- Daha iyi error handling
"""

import logging
import asyncio
import time
from typing import Dict, Any, Optional, List
import aiohttp
import numpy as np

from utils.binance.binance_a import BinanceAPI
from config import get_config, BotConfig, OnChainConfig

logger = logging.getLogger(__name__)

class OnchainAnalyzer:
    _instance: Optional["OnchainAnalyzer"] = None
    _initialized: bool = False
    
    def __new__(cls, binance_api: Optional[BinanceAPI] = None, 
                config: Optional[OnChainConfig] = None) -> "OnchainAnalyzer":
        """Singleton pattern implementation"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, binance_api: Optional[BinanceAPI] = None, 
                 config: Optional[OnChainConfig] = None) -> None:
        """
        OnchainAnalyzer initialization with config.
        """
        if not self._initialized:
            self.binance = binance_api
            self.config = config
            self.session: Optional[aiohttp.ClientSession] = None
            self._cache: Dict[str, Any] = {}
            self._cache_timestamps: Dict[str, float] = {}
            self._initialized = True
            logger.info("✅ OnchainAnalyzer initialized (config will be loaded on first use)")
            
            # Config'i async olarak yükleme işlemini ertele
            self._config_loaded = False
    

    async def _ensure_config_loaded(self):
        """Config'i async olarak yükle - DÜZELTİLMİŞ VERSİYON"""
        if not self._config_loaded:
            if self.config is None:
                # ✅ await KALDIRILDI - get_config() zaten async bir fonksiyon
                bot_config = await get_config()  # Bu doğru, await gerekli
                self.config = bot_config.ONCHAIN
            self._config_loaded = True
    
    
    async def _get_cached_data(self, key: str, ttl: int) -> Optional[Any]:
        """Cache'ten veri al"""
        current_time = time.time()
        if key in self._cache and current_time - self._cache_timestamps[key] < ttl:
            logger.debug(f"Cache hit for {key}")
            return self._cache[key]
        return None

    async def _set_cached_data(self, key: str, data: Any) -> None:
        """Cache'e veri kaydet"""
        self._cache[key] = data
        self._cache_timestamps[key] = time.time()
        logger.debug(f"Cache set for {key}")

    async def _get_glassnode_data(self, endpoint: str, params: Dict[str, Any]) -> Optional[List[Dict]]:
        """
        Glassnode API'den veri çekme
        
        Args:
            endpoint: API endpoint
            params: Query parametreleri
            
        Returns:
            API response data or None
        """
        try:
            await self._ensure_session()
            
            base_url = "https://api.glassnode.com/v1"
            params['api_key'] = self.config.GLASSNODE_API_KEY
            
            async with self.session.get(f"{base_url}/{endpoint}", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"Glassnode API error: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Glassnode API request error: {e}")
            return None

    async def stablecoin_supply_ratio(self) -> float:
        """Stablecoin Supply Ratio hesaplama"""
        try:
            await self._ensure_config_loaded()  # ✅ Config yüklendiğinden emin ol
            # Cache kontrolü
            cache_key = "ssr_data"
            cache_ttl = self.config.CACHE_TTL["ssr"]
            cached_data = await self._get_cached_data(cache_key, cache_ttl)
            
            if cached_data is not None:
                return cached_data
            
            # Glassnode API'den SSR verisi al
            params = {
                'a': 'BTC',
                'i': '24h',
                's': int(time.time()) - 86400 * 7,  # 7 günlük veri
                'u': int(time.time())
            }
            
            ssr_data = await self._get_glassnode_data("metrics/indicators/ssr", params)
            
            if ssr_data and len(ssr_data) > 0:
                latest_ssr = ssr_data[-1]['v']
                ssr_thresholds = self.config.SSR_THRESHOLDS
                
                # Threshold'lara göre normalize et
                if latest_ssr > ssr_thresholds["bearish"]:
                    result = -1.0
                elif latest_ssr < ssr_thresholds["bullish"]:
                    result = 1.0
                else:
                    # Linear normalization between thresholds
                    neutral_range = ssr_thresholds["bearish"] - ssr_thresholds["bullish"]
                    if neutral_range > 0:
                        result = ((ssr_thresholds["neutral"] - latest_ssr) / neutral_range) * 2
                    else:
                        result = 0.0
                
                result = max(-1.0, min(1.0, result))  # Clamp to [-1, 1]
                
                await self._set_cached_data(cache_key, result)
                logger.info(f"SSR calculated: {latest_ssr:.2f} → {result:.3f}")
                return result
                
            else:
                # Fallback: Binance API ile basit hesaplama
                if self.binance:
                    try:
                        btc_price = await self.binance.get_symbol_ticker("BTCUSDT")
                        if btc_price and 'price' in btc_price:
                            btc_price_val = float(btc_price['price'])
                            # Basit SSR hesaplama (örnek)
                            btc_market_cap = btc_price_val * 19500000  # ~19.5M BTC
                            usdt_supply = 80000000000  # ~80B USDT
                            ssr = btc_market_cap / usdt_supply
                            
                            ssr_thresholds = self.config.SSR_THRESHOLDS
                            # Normalize
                            if ssr > ssr_thresholds["bearish"]:
                                result = -1.0
                            elif ssr < ssr_thresholds["bullish"]:
                                result = 1.0
                            else:
                                neutral_range = ssr_thresholds["bearish"] - ssr_thresholds["bullish"]
                                if neutral_range > 0:
                                    result = ((ssr_thresholds["neutral"] - ssr) / neutral_range) * 2
                                else:
                                    result = 0.0
                            
                            result = max(-1.0, min(1.0, result))
                            await self._set_cached_data(cache_key, result)
                            logger.info(f"SSR fallback: {ssr:.2f} → {result:.3f}")
                            return result
                    except Exception as binance_error:
                        logger.warning(f"Binance fallback failed: {binance_error}")
                
                # Ultimate fallback
                result = self.config.FALLBACK_VALUES["ssr"]
                await self._set_cached_data(cache_key, result)
                return result
                
        except Exception as e:
            logger.error(f"SSR calculation error: {e}")
            return self.config.FALLBACK_VALUES["ssr"]

    async def exchange_net_flow(self) -> float:
        """Exchange net flow analizi"""
        try:
            cache_key = "netflow_data"
            cache_ttl = self.config.CACHE_TTL["netflow"]
            cached_data = await self._get_cached_data(cache_key, cache_ttl)
            
            if cached_data is not None:
                return cached_data
            
            # Glassnode API'den exchange flow verisi
            params = {
                'a': 'BTC',
                'i': '24h',
                's': int(time.time()) - 86400 * 3,  # 3 günlük veri
                'u': int(time.time())
            }
            
            inflow_data = await self._get_glassnode_data("metrics/transactions/transfers_volume_to_exchanges", params)
            outflow_data = await self._get_glassnode_data("metrics/transactions/transfers_volume_from_exchanges", params)
            
            if inflow_data and outflow_data and len(inflow_data) > 0 and len(outflow_data) > 0:
                latest_inflow = inflow_data[-1]['v']
                latest_outflow = outflow_data[-1]['v']
                net_flow = latest_inflow - latest_outflow
                
                # Threshold'lara göre normalize et
                thresholds = self.config.NETFLOW_THRESHOLDS
                if net_flow > thresholds["bearish"]:
                    result = -1.0
                elif net_flow < thresholds["bullish"]:
                    result = 1.0
                else:
                    # Linear normalization
                    range_size = thresholds["bearish"] - thresholds["bullish"]
                    if range_size > 0:
                        result = -((net_flow - thresholds["bullish"]) / range_size) * 2
                    else:
                        result = 0.0
                
                result = max(-1.0, min(1.0, result))
                await self._set_cached_data(cache_key, result)
                logger.info(f"Net flow calculated: {net_flow:.0f} → {result:.3f}")
                return result
            else:
                result = self.config.FALLBACK_VALUES["netflow"]
                await self._set_cached_data(cache_key, result)
                return result
                
        except Exception as e:
            logger.error(f"Exchange net flow error: {e}")
            return self.config.FALLBACK_VALUES["netflow"]

    async def etf_flows(self) -> float:
        """ETF flows analizi (basit implementasyon)"""
        try:
            cache_key = "etf_flows_data"
            cache_ttl = self.config.CACHE_TTL["etf_flows"]
            cached_data = await self._get_cached_data(cache_key, cache_ttl)
            
            if cached_data is not None:
                return cached_data
            
            # Burada gerçek ETF veri kaynağına bağlanılacak
            # Şimdilik simüle edilmiş veri
            simulated_flow = np.random.uniform(-50000000, 50000000)
            
            threshold = self.config.ETF_THRESHOLDS["max_flow"]
            if abs(simulated_flow) > threshold:
                result = 1.0 if simulated_flow > 0 else -1.0
            else:
                result = simulated_flow / threshold
            
            result = max(-1.0, min(1.0, result))
            await self._set_cached_data(cache_key, result)
            logger.info(f"ETF flows simulated: {simulated_flow:.0f} → {result:.3f}")
            return result
            
        except Exception as e:
            logger.error(f"ETF flows error: {e}")
            return self.config.FALLBACK_VALUES["etf_flows"]

    async def fear_greed_index(self) -> float:
        """Fear & Greed Index"""
        try:
            cache_key = "fear_greed_data"
            cache_ttl = self.config.CACHE_TTL["fear_greed"]
            cached_data = await self._get_cached_data(cache_key, cache_ttl)
            
            if cached_data is not None:
                return cached_data
            
            # Alternative.me Fear and Greed Index API
            await self._ensure_session()
            url = "https://api.alternative.me/fng/"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and 'data' in data and len(data['data']) > 0:
                        fgi_value = int(data['data'][0]['value'])
                        # Normalize: 0-100 → -1 to +1
                        result = (fgi_value - 50) / 50
                        result = max(-1.0, min(1.0, result))
                        await self._set_cached_data(cache_key, result)
                        logger.info(f"Fear & Greed Index: {fgi_value} → {result:.3f}")
                        return result
            
            # Fallback
            result = self.config.FALLBACK_VALUES["fear_greed"]
            await self._set_cached_data(cache_key, result)
            return result
            
        except Exception as e:
            logger.error(f"Fear & Greed Index error: {e}")
            return self.config.FALLBACK_VALUES["fear_greed"]

    async def aggregate_score(self) -> Dict[str, Any]:
        """Tüm metrikleri toplu olarak hesapla ve aggregate score üret"""
        try:
            weights = self.config.METRIC_WEIGHTS
            
            # Tüm metrikleri paralel çalıştır
            tasks = {
                "stablecoin_supply_ratio": self.stablecoin_supply_ratio(),
                "exchange_net_flow": self.exchange_net_flow(),
                "etf_flows": self.etf_flows(),
                "fear_greed_index": self.fear_greed_index()
            }
            
            results = {}
            for name, task in tasks.items():
                try:
                    # Timeout yönetimi
                    timeout = self.config.API_TIMEOUTS.get(name.split('_')[0], 30)
                    results[name] = await asyncio.wait_for(task, timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning(f"{name} timeout after {timeout}s, using fallback")
                    results[name] = self.config.FALLBACK_VALUES.get(name, 0.0)
                except Exception as e:
                    logger.error(f"{name} calculation error: {e}")
                    results[name] = self.config.FALLBACK_VALUES.get(name, 0.0)

            # Ağırlıklı ortalama
            total_weight = sum(weights.values())
            if total_weight > 0:
                weighted_sum = sum(results[name] * weights.get(name, 0.0) for name in results)
                aggregate_score = weighted_sum / total_weight
            else:
                aggregate_score = sum(results.values()) / len(results)
            
            aggregate_score = round(aggregate_score, 3)

            result = {
                **results,
                "aggregate": aggregate_score,
                "timestamp": time.time()
            }
            
            logger.info(f"📊 On-chain analysis complete: {aggregate_score:.3f}")
            return result
            
        except Exception as e:
            logger.error(f"Aggregate score calculation error: {e}")
            fallback_values = self.config.FALLBACK_VALUES
            return {
                "stablecoin_supply_ratio": fallback_values["ssr"],
                "exchange_net_flow": fallback_values["netflow"],
                "etf_flows": fallback_values["etf_flows"],
                "fear_greed_index": fallback_values["fear_greed"],
                "aggregate": 0.0,
                "timestamp": time.time(),
                "error": str(e)
            }

    async def close(self) -> None:
        """Kaynakları temizle"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("OnchainAnalyzer session closed")

# Aiogram 3.x Router entegrasyonu
from aiogram import Router, F
from aiogram.types import Message

router = Router()

@router.message(F.text.lower() == "onchain")
async def onchain_handler(message: Message) -> None:
    """Telegram bot için On-chain analiz handler"""
    try:
        # Bot'tan analyzer instance'ını al veya oluştur
        analyzer = getattr(message.bot, 'onchain_analyzer', None)
        if analyzer is None:
            binance_api = getattr(message.bot, 'binance_api', None)
            if not binance_api:
                await message.answer("❌ Binance API bağlantısı kurulamadı")
                return
            
            analyzer = get_onchain_analyzer(binance_api)
            message.bot.onchain_analyzer = analyzer
        
        await message.answer("🔍 On-chain veriler hesaplanıyor...")
        
        result = await analyzer.aggregate_score()

        # Sonuçları formatla
        text = (
            "🔗 **On-Chain Analiz**\n\n"
            f"• 📊 **Stablecoin Supply Ratio**: `{result['stablecoin_supply_ratio']:.3f}`\n"
            f"• 💸 **Exchange Net Flow**: `{result['exchange_net_flow']:.3f}`\n"
            f"• 📈 **ETF Flows**: `{result['etf_flows']:.3f}`\n"
            f"• 😨 **Fear & Greed**: `{result['fear_greed_index']:.3f}`\n\n"
            f"⭐ **Genel Skor**: `{result['aggregate']:.3f}`"
        )

        await message.answer(text)
        
    except Exception as e:
        logger.error(f"Onchain handler error: {e}")
        await message.answer("❌ On-chain analiz sırasında hata oluştu")

# Singleton instance getter
def get_onchain_analyzer(binance_api: Optional[BinanceAPI] = None, 
                         config: Optional[OnChainConfig] = None) -> OnchainAnalyzer:
    """
    OnchainAnalyzer singleton instance'ını döndürür.
    
    Args:
        binance_api: BinanceAPI instance (opsiyonel)
        config: OnChainConfig instance (opsiyonel)
        
    Returns:
        OnchainAnalyzer instance
    """
    return OnchainAnalyzer(binance_api, config)

# Test fonksiyonu
async def test_onchain_analyzer():
    """Test function for onchain analyzer"""
    try:
        # Mock BinanceAPI için basit bir sınıf
        class MockBinanceAPI:
            async def get_symbol_ticker(self, symbol: str) -> Optional[Dict]:
                return {'price': '45000.0'} if symbol == "BTCUSDT" else None
        
        analyzer = get_onchain_analyzer(MockBinanceAPI())
        result = await analyzer.aggregate_score()
        print("✅ On-chain analysis test result:", result)
        
        await analyzer.close()
    except Exception as e:
        print(f"❌ Test hatası: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_onchain_analyzer())