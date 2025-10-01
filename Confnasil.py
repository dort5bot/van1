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

        class Setting:
            DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            MAX_LIMIT = 1000

    class Private:
        class Spot:
            ACCOUNT = "/api/v3/account"
            ORDER = "/api/v3/order"

        class Future:
            ACCOUNT = "/fapi/v2/account"
            ORDER = "/fapi/v1/order"


# diğer genel ayarların varsa onlar da aynı dosyada olur:
BOT_NAME = "MyTelegramBot"
DEBUG = True
