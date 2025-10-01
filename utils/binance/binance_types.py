# utils/binance/binance_types.py
"""
Binance API type definitions with validation and enhanced error handling.
Includes:
- Literal types for OrderSide, OrderType, TimeInForce, Interval, PositionSide, MarginType
- TypedDict for Spot, Futures, WebSocket, ExchangeInfo
- Enhanced request types with validation helpers
- Detailed ErrorResponse mapping and exception helpers
"""

from typing import TypedDict, List, Union, Optional, Dict, Any, Literal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ------------------------------
# Literal Types
# ------------------------------
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_LIMIT", 
                   "TAKE_PROFIT", "TAKE_PROFIT_LIMIT", "LIMIT_MAKER"]
TimeInForce = Literal["GTC", "IOC", "FOK"]
Interval = Literal["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
OrderStatus = Literal["NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "PENDING_CANCEL", "REJECTED", "EXPIRED"]
PositionSide = Literal["BOTH", "LONG", "SHORT"]
MarginType = Literal["ISOLATED", "CROSSED"]

# ------------------------------
# Base Types
# ------------------------------
Symbol = str
Asset = str

# ------------------------------
# TypedDict Definitions
# ------------------------------
class Kline(TypedDict):
    open_time: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    close_time: int
    quote_asset_volume: str
    number_of_trades: int
    taker_buy_base_asset_volume: str
    taker_buy_quote_asset_volume: str
    ignore: str

class OrderBookEntry(TypedDict):
    price: str
    quantity: str

class OrderBook(TypedDict):
    lastUpdateId: int
    bids: List[List[str]]
    asks: List[List[str]]

class Ticker(TypedDict):
    symbol: str
    priceChange: str
    priceChangePercent: str
    weightedAvgPrice: str
    prevClosePrice: str
    lastPrice: str
    lastQty: str
    bidPrice: str
    askPrice: str
    openPrice: str
    highPrice: str
    lowPrice: str
    volume: str
    quoteVolume: str
    openTime: int
    closeTime: int
    firstId: int
    lastId: int
    count: int

class Balance(TypedDict):
    asset: str
    free: str
    locked: str

class AccountInfo(TypedDict):
    makerCommission: int
    takerCommission: int
    buyerCommission: int
    sellerCommission: int
    canTrade: bool
    canWithdraw: bool
    canDeposit: bool
    updateTime: int
    accountType: str
    balances: List[Balance]
    permissions: List[str]

class Order(TypedDict):
    symbol: str
    orderId: int
    orderListId: int
    clientOrderId: str
    price: str
    origQty: str
    executedQty: str
    cummulativeQuoteQty: str
    status: OrderStatus
    timeInForce: TimeInForce
    type: OrderType
    side: OrderSide
    stopPrice: str
    icebergQty: str
    time: int
    updateTime: int
    isWorking: bool
    origQuoteOrderQty: str

class OrderResponse(Order):
    transactTime: int

class Trade(TypedDict):
    id: int
    price: str
    qty: str
    quoteQty: str
    time: int
    isBuyerMaker: bool
    isBestMatch: bool

# ------------------------------
# Futures Types
# ------------------------------
class Position(TypedDict):
    symbol: str
    positionAmt: str
    entryPrice: str
    markPrice: str
    unRealizedProfit: str
    liquidationPrice: str
    leverage: str
    maxNotionalValue: str
    marginType: MarginType
    isolatedMargin: str
    isAutoAddMargin: str
    positionSide: PositionSide
    notional: str
    isolatedWallet: str
    updateTime: int

class FuturesBalance(TypedDict):
    accountAlias: str
    asset: str
    balance: str
    crossWalletBalance: str
    crossUnPnl: str
    availableBalance: str
    maxWithdrawAmount: str

class FuturesAccount(TypedDict):
    assets: List[FuturesBalance]
    positions: List[Position]
    canDeposit: bool
    canTrade: bool
    canWithdraw: bool
    feeTier: int
    updateTime: int
    totalInitialMargin: str
    totalMaintMargin: str
    totalWalletBalance: str
    totalUnrealizedProfit: str
    totalMarginBalance: str
    totalPositionInitialMargin: str
    totalOpenOrderInitialMargin: str
    totalCrossWalletBalance: str
    totalCrossUnPnl: str
    availableBalance: str
    maxWithdrawAmount: str

# ------------------------------
# WebSocket Types
# ------------------------------
class WSMessage(TypedDict):
    stream: str
    data: Dict[str, Any]

class WSKlineData(TypedDict):
    t: int
    T: int
    s: str
    i: str
    o: str
    c: str
    h: str
    l: str
    v: str
    n: int
    x: bool
    q: str
    V: str
    Q: str
    B: str

# ------------------------------
# Response & Error Types
# ------------------------------
class BinanceResponse(TypedDict):
    success: bool
    data: Optional[Union[Dict[str, Any], List[Any]]]
    error: Optional[str]
    error_code: Optional[int]
    timestamp: int

class ErrorResponse(TypedDict):
    code: int
    msg: str

# ------------------------------
# Health Status
# ------------------------------
class HealthStatus(TypedDict):
    status: Literal["HEALTHY", "DEGRADED", "CRITICAL"]
    issues: Optional[List[str]]
    warnings: Optional[List[str]]
    metrics: Optional[Dict[str, Any]]
    timestamp: float

# ------------------------------
# Request Types
# ------------------------------
class OrderRequest(TypedDict, total=False):
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: Optional[str]
    quoteOrderQty: Optional[str]
    price: Optional[str]
    timeInForce: Optional[TimeInForce]
    newClientOrderId: Optional[str]
    stopPrice: Optional[str]
    icebergQty: Optional[str]
    newOrderRespType: Optional[str]
    recvWindow: Optional[int]

class FuturesOrderRequest(OrderRequest):
    positionSide: Optional[PositionSide]
    reduceOnly: Optional[bool]
    activationPrice: Optional[str]
    callbackRate: Optional[str]
    closePosition: Optional[bool]
    workingType: Optional[str]
    priceRate: Optional[str]
    priceProtect: Optional[bool]

# ------------------------------
# Exchange Info Types
# ------------------------------
class RateLimit(TypedDict):
    rateLimitType: str
    interval: str
    intervalNum: int
    limit: int
    weight_used: int
    weight_limit: int
    last_reset_time: float
    requests_per_second: float

class SymbolFilter(TypedDict):
    filterType: str
    minPrice: Optional[str]
    maxPrice: Optional[str]
    tickSize: Optional[str]
    minQty: Optional[str]
    maxQty: Optional[str]
    stepSize: Optional[str]
    minNotional: Optional[str]
    limit: Optional[int]
    maxNumOrders: Optional[int]
    maxNumAlgoOrders: Optional[int]

class SymbolInfo(TypedDict):
    symbol: str
    status: str
    baseAsset: str
    baseAssetPrecision: int
    quoteAsset: str
    quotePrecision: int
    quoteAssetPrecision: int
    baseCommissionPrecision: int
    quoteCommissionPrecision: int
    orderTypes: List[OrderType]
    icebergAllowed: bool
    ocoAllowed: bool
    quoteOrderQtyMarketAllowed: bool
    allowTrailingStop: bool
    cancelReplaceAllowed: bool
    isSpotTradingAllowed: bool
    isMarginTradingAllowed: bool
    filters: List[SymbolFilter]
    permissions: List[str]
    defaultSelfTradePreventionMode: str
    allowedSelfTradePreventionModes: List[str]

class ExchangeInfo(TypedDict):
    timezone: str
    serverTime: int
    rateLimits: List[RateLimit]
    exchangeFilters: List[Any]
    symbols: List[SymbolInfo]

# ------------------------------
# Validation Helpers
# ------------------------------
def validate_order_request(req: OrderRequest, symbol_info: SymbolInfo):
    """
    Validate order request against SymbolInfo filters.
    Raises ValueError on invalid input.
    """
    for f in symbol_info["filters"]:
        if f["filterType"] == "LOT_SIZE" and "minQty" in f and req.get("quantity"):
            if float(req["quantity"]) < float(f["minQty"]):
                raise ValueError(f"Quantity {req['quantity']} below minQty {f['minQty']}")
            if float(req["quantity"]) > float(f["maxQty"]):
                raise ValueError(f"Quantity {req['quantity']} above maxQty {f['maxQty']}")
        if f["filterType"] == "PRICE_FILTER" and req.get("price"):
            if float(req["price"]) < float(f["minPrice"]):
                raise ValueError(f"Price {req['price']} below minPrice {f['minPrice']}")
            if float(req["price"]) > float(f["maxPrice"]):
                raise ValueError(f"Price {req['price']} above maxPrice {f['maxPrice']}")

# ------------------------------
# Error Mapping Helper
# ------------------------------
BINANCE_ERROR_MAP = {
    -1000: "Unknown error",
    -1001: "Disconnected from server",
    -1013: "Invalid quantity/price",
    -2010: "Order would trigger liquidation",
    -2011: "Order canceled",
    -2013: "Order not found",
    -2014: "Insufficient balance",
    # Add more codes as needed
}

class BinanceAPIError(Exception):
    """Detailed Binance API exception with code and message."""
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"[Binance API Error {code}] {msg}")

def raise_if_error(response: Union[ErrorResponse, BinanceResponse]):
    """Raise BinanceAPIError if response contains an error."""
    if isinstance(response, dict):
        code = response.get("code") or response.get("error_code")
        msg = response.get("msg") or response.get("error")
        if code is not None:
            raise BinanceAPIError(code=code, msg=msg or BINANCE_ERROR_MAP.get(code, "Unknown error"))

