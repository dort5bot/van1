

# -----------------------------------------------------------------------------
# File: README.md
"""
Usage notes:
- Set environment variables GLASSNODE_API_KEY and CRYPTOQUANT_API_KEY for richer data.
- Install dependencies: aiohttp, bs4, aiogram
- Integrate handlers by including router in your aiogram Dispatcher.
- The BaseClient has an internal cleanup task which starts when first client is created.

Security & Notes:
- API keys are validated and masked in logs.
- Cache TTL defaults to 300s but can be overridden via client constructors.



Bu altyapıda
glassnode_client.py, 
cryptoquant_client.py 
farside_scraper.py sadece 10–20 satırlık miras kodlar olur.
data_provider.py ise bu üç client’i Singleton olarak kullanır.


Bu yapıda tüm veri kaynaklarına erişim merkezi olarak data_provider.py dosyasından yapılır.
Yapının mantığı şu şekilde işler:

glassnode_client.py, cryptoquant_client.py, farside_scraper.py her biri kendi veri kaynağını yönetir (API veya scraping).
base_client.py bu client’ların ortak altyapısını (session, cache, error handling, async lock vs.) sağlar.
data_provider.py ise bu client’ları tek bir erişim noktası (Facade / Singleton) altında birleştirir.

Dolayısıyla bot içinden sadece şu şekilde çağırmak yeterlidir:

from utils.data_sources.data_provider import data_provider
data = await data_provider.get_metric("BTC", "etf_net_flow")


veya doğrudan spesifik kaynak:

await data_provider.glassnode.get_metric("BTC", "active_addresses")
await data_provider.cryptoquant.get_metric("ETH", "exchange_reserve")
await data_provider.farside.get_etf_flows("BTC")


Bu sayede:
Tek session pool ve cache kullanılır
API key ve rate limit tek yerden yönetilir
Multi-user destekli Telegram botlar için güvenli, thread-safe yapı korunur

"""
