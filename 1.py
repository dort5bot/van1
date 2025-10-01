








public ve private ayrı alt yapılar olarak tanımlanmalı, ve onların altına spot, futures, margin gibi yapılar mantıklı şekilde oturtulmalı.
Bu ağaç yapısı:
Kod okunabilirliğini artırır
Bakımı ve testleri kolaylaştırır
Hataların sınırlarını belirler
Genişletilebilirliği arttırır (örneğin staking, mining kolay eklenebilir)






















# bot/config.py

class BinanceAPI:
    BASE_URL = "https://api.binance.com"
    FUTURE_URL = "https://fapi.binance.com"
    TIMEOUT = 10

    class Public:
        class Spot:
            TICKER = "/api/v3/ticker/price"
            ORDERBOOK = "/api/v3/depth"

        class Future:
            TICKER = "/fapi/v1/ticker/price"
            FUNDING_RATE = "/fapi/v1/fundingRate"


# diğer genel ayarların varsa onlar da aynı dosyada olur:
BOT_NAME = "MyTelegramBot"
DEBUG = True
