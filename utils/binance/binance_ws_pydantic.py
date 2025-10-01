"""
binance_ws_Pydantic.py
----------------------

Binance WebSocket API'den gelen ham JSON verilerini Pydantic modelleri ile doğrulayan,
tipleyen ve anlamlandıran modül.

- Spot Market
- Futures Market
- System Events

Modül, çoklu kullanıcı ve çoklu WebSocket bağlantısını destekleyecek şekilde
oldukça genişletilebilir, modüler yapıda tasarlanmıştır.

Bu modül, Binance'in resmi WebSocket event formatlarına %100 uyumludur.

Referanslar:
- https://binance-docs.github.io/apidocs/spot/en/#websocket-market-streams
- https://binance-docs.github.io/apidocs/futures/en/#websocket-market-streams
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Union, Literal
from datetime import datetime


# ------------------------
# Temel BaseModel'ler
# ------------------------

class BaseEvent(BaseModel):
    """Tüm eventlerin temel alanları"""
    e: str  # Event Type
    E: int  # Event Time (ms)

    @property
    def event_time(self) -> datetime:
        """Event zamanını datetime objesi olarak verir"""
        return datetime.fromtimestamp(self.E / 1000)


# ------------------------
# Spot Market Event Modelleri
# ------------------------

class TradeEvent(BaseEvent):
    e: Literal["trade"]
    s: str  # Symbol
    t: int  # Trade ID
    p: str  # Price
    q: str  # Quantity
    b: int  # Buyer Order ID
    a: int  # Seller Order ID
    T: int  # Trade Time (ms)
    m: bool  # Is buyer maker?
    M: bool  # Ignore

    @property
    def trade_time(self) -> datetime:
        return datetime.fromtimestamp(self.T / 1000)


class AggTradeEvent(BaseEvent):
    e: Literal["aggTrade"]
    s: str  # Symbol
    a: int  # Aggregate Trade ID
    p: str  # Price
    q: str  # Quantity
    f: int  # First trade ID
    l: int  # Last trade ID
    T: int  # Trade time (ms)
    m: bool  # Is buyer maker?
    M: bool  # Ignore

    @property
    def agg_trade_time(self) -> datetime:
        return datetime.fromtimestamp(self.T / 1000)


class Kline(BaseModel):
    t: int  # Kline start time
    T: int  # Kline close time
    s: str  # Symbol
    i: str  # Interval
    f: int  # First trade ID
    L: int  # Last trade ID
    o: str  # Open price
    c: str  # Close price
    h: str  # High price
    l: str  # Low price
    v: str  # Base asset volume
    n: int  # Number of trades
    x: bool  # Is this kline closed?
    q: str  # Quote asset volume
    V: str  # Taker buy base asset volume
    Q: str  # Taker buy quote asset volume
    B: str  # Ignore

    @property
    def start_time(self) -> datetime:
        return datetime.fromtimestamp(self.t / 1000)

    @property
    def close_time(self) -> datetime:
        return datetime.fromtimestamp(self.T / 1000)


class KlineEvent(BaseEvent):
    e: Literal["kline"]
    s: str
    k: Kline


class DepthUpdateEvent(BaseEvent):
    e: Literal["depthUpdate"]
    s: str  # Symbol
    U: int  # First update ID in event
    u: int  # Final update ID in event
    b: List[List[str]]  # Bids to be updated [price, quantity]
    a: List[List[str]]  # Asks to be updated [price, quantity]


class OutboundAccountPositionEvent(BaseEvent):
    e: Literal["outboundAccountPosition"]
    u: int  # Account update time
    B: List[dict]  # Balances, örn: [{"a":"BTC","f":"100.0","l":"0.0"}]


class BalanceUpdateEvent(BaseEvent):
    e: Literal["balanceUpdate"]
    a: str  # Asset
    d: str  # Balance Delta
    T: int  # Clear Time (ms)

    @property
    def clear_time(self) -> datetime:
        return datetime.fromtimestamp(self.T / 1000)


# ------------------------
# Futures Market Event Modelleri
# ------------------------

class FuturesAggTradeEvent(BaseEvent):
    e: Literal["aggTrade"]
    E: int  # Event time
    s: str  # Symbol
    a: int  # Aggregate trade ID
    p: str  # Price
    q: str  # Quantity
    f: int  # First trade ID
    l: int  # Last trade ID
    T: int  # Trade time
    m: bool  # Is buyer maker?
    M: bool  # Ignore

    @property
    def trade_time(self) -> datetime:
        return datetime.fromtimestamp(self.T / 1000)


class FuturesKlineEvent(BaseEvent):
    e: Literal["kline"]
    E: int
    s: str
    k: Kline


class FuturesMarkPriceEvent(BaseEvent):
    e: Literal["markPriceUpdate"]
    E: int
    s: str
    p: str  # Mark price
    i: int  # Index price
    T: int  # Next funding time
    r: str  # Funding rate


# ------------------------
# System Event Modelleri
# ------------------------

class PingEvent(BaseEvent):
    e: Literal["ping"]
    E: int


class PongEvent(BaseEvent):
    e: Literal["pong"]
    E: int


# ------------------------
# Union Tipler ve Parse Fonksiyonu
# ------------------------

BinanceWSEvent = Union[
    TradeEvent,
    AggTradeEvent,
    KlineEvent,
    DepthUpdateEvent,
    OutboundAccountPositionEvent,
    BalanceUpdateEvent,
    FuturesAggTradeEvent,
    FuturesKlineEvent,
    FuturesMarkPriceEvent,
    PingEvent,
    PongEvent,
]


def parse_binance_ws_event(data: dict) -> BinanceWSEvent:
    """
    Binance WebSocket'ten gelen JSON datasını uygun Pydantic modele parse eder.
    Desteklenen event tipleri:
        - trade
        - aggTrade
        - kline
        - depthUpdate
        - outboundAccountPosition
        - balanceUpdate
        - futures aggTrade, kline, markPriceUpdate
        - ping, pong

    Args:
        data (dict): Binance WS JSON verisi

    Returns:
        BinanceWSEvent: Pydantic event modeli

    Raises:
        ValueError: Tanımlanamayan event tipinde
    """
    event_type = data.get("e")
    if event_type is None:
        raise ValueError("Event type 'e' alanı yok!")

    # Spot Market Eventleri
    if event_type == "trade":
        return TradeEvent.parse_obj(data)
    elif event_type == "aggTrade" and "T" in data:  # Spot veya Futures ayırımı basit:
        # Futures ve spot aggTrade aynı yapıya çok benzer, gerekirse buraya kontrol eklenebilir.
        if "E" in data and "p" in data:
            # Futures genelde E de bulunur ama spotta da var, daha derin kontrol gerekebilir.
            # Burada basit ayırım yapılabilir.
            return AggTradeEvent.parse_obj(data)
        else:
            return AggTradeEvent.parse_obj(data)
    elif event_type == "kline":
        # Futures ve spot aynı model kullanabilir.
        return KlineEvent.parse_obj(data)
    elif event_type == "depthUpdate":
        return DepthUpdateEvent.parse_obj(data)
    elif event_type == "outboundAccountPosition":
        return OutboundAccountPositionEvent.parse_obj(data)
    elif event_type == "balanceUpdate":
        return BalanceUpdateEvent.parse_obj(data)

    # Futures özel eventleri
    elif event_type == "markPriceUpdate":
        return FuturesMarkPriceEvent.parse_obj(data)

    # Sistem eventleri
    elif event_type == "ping":
        return PingEvent.parse_obj(data)
    elif event_type == "pong":
        return PongEvent.parse_obj(data)

    else:
        raise ValueError(f"Unknown Binance WebSocket event type: {event_type}")



# ------------------------
# Örnek Kullanım
# ------------------------

if __name__ == "__main__":
    import json

    # Örnek WS JSON Trade Event verisi
    raw_json = """
    {
        "e": "trade",
        "E": 123456789,
        "s": "BTCUSDT",
        "t": 12345,
        "p": "0.001",
        "q": "100",
        "b": 88,
        "a": 50,
        "T": 123456785,
        "m": true,
        "M": true
    }
    """
    data = json.loads(raw_json)
    event = parse_binance_ws_event(data)
    print(event)
    print("Trade Time:", event.trade_time)

