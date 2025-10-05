# binance_api_map.py

BINANCE_API_MAP = {
    "spot_public": [
        {"method": "ping", "endpoint": "/api/v3/ping", "required": False, "category": "general"},
        {"method": "get_server_time", "endpoint": "/api/v3/time", "required": False, "category": "general"},
        {"method": "get_price", "endpoint": "/api/v3/ticker/price", "required": True, "category": "trend"},
        {"method": "get_24hr_ticker", "endpoint": "/api/v3/ticker/24hr", "required": True, "category": "trend"},
        {"method": "get_exchange_info", "endpoint": "/api/v3/exchangeInfo", "required": False, "category": "info"},
        {"method": "get_klines", "endpoint": "/api/v3/klines", "required": True, "category": "trend"},
        {"method": "get_depth", "endpoint": "/api/v3/depth", "required": True, "category": "order_flow"},
        {"method": "get_book_ticker", "endpoint": "/api/v3/ticker/bookTicker", "required": False, "category": "order_flow"},
        {"method": "get_recent_trades", "endpoint": "/api/v3/trades", "required": False, "category": "order_flow"},
    ],
    "spot_private": [
        {"method": "get_account_info", "endpoint": "/api/v3/account", "required": True, "category": "position"},
        {"method": "get_open_orders", "endpoint": "/api/v3/openOrders", "required": True, "category": "order_flow"},
        {"method": "get_order_status", "endpoint": "/api/v3/order", "required": False, "category": "order_flow"},
        {"method": "place_order", "endpoint": "/api/v3/order", "required": True, "category": "order_flow"},
        {"method": "cancel_order", "endpoint": "/api/v3/order", "required": False, "category": "order_flow"},
        {"method": "get_my_trades", "endpoint": "/api/v3/myTrades", "required": False, "category": "position"},
        {"method": "get_account_snapshot", "endpoint": "/sapi/v1/accountSnapshot", "required": False, "category": "position"},
        {"method": "get_sub_account_list", "endpoint": "/sapi/v3/sub-account/list", "required": False, "category": "info"},
        {"method": "get_asset_dividend", "endpoint": "/sapi/v1/asset/assetDividend", "required": False, "category": "income"},
        {"method": "get_margin_transfer_history", "endpoint": "/sapi/v1/margin/transfer", "required": False, "category": "fund_flow"},
    ],
    "futures_private": [
        # önceki metodları buraya ekle, örneğin:
        {"method": "get_futures_account", "endpoint": "/fapi/v2/account", "required": True, "category": "position"},
        {"method": "get_futures_balance", "endpoint": "/fapi/v2/balance", "required": True, "category": "position"},
        {"method": "get_open_positions", "endpoint": "/fapi/v2/positionRisk", "required": True, "category": "position"},
        {"method": "place_futures_order", "endpoint": "/fapi/v1/order", "required": True, "category": "order_flow"},
        {"method": "cancel_futures_order", "endpoint": "/fapi/v1/order", "required": False, "category": "order_flow"},
        {"method": "get_futures_trades", "endpoint": "/fapi/v1/userTrades", "required": False, "category": "position"},
        {"method": "get_income_history", "endpoint": "/fapi/v1/income", "required": False, "category": "income"},
        {"method": "change_leverage", "endpoint": "/fapi/v1/leverage", "required": False, "category": "position"},
        # vs.
    ],
    "margin_private": [
        {"method": "get_margin_account", "endpoint": "/sapi/v1/margin/account", "required": True, "category": "position"},
        {"method": "get_margin_balance", "endpoint": "/sapi/v1/margin/allAssets", "required": False, "category": "position"},
        {"method": "get_margin_orders", "endpoint": "/sapi/v1/margin/openOrders", "required": True, "category": "order_flow"},
        {"method": "place_margin_order", "endpoint": "/sapi/v1/margin/order", "required": True, "category": "order_flow"},
        {"method": "get_margin_loan", "endpoint": "/sapi/v1/margin/loan", "required": True, "category": "fund_flow"},
        {"method": "repay_margin_loan", "endpoint": "/sapi/v1/margin/repay", "required": False, "category": "fund_flow"},
        {"method": "get_margin_trades", "endpoint": "/sapi/v1/margin/myTrades", "required": False, "category": "position"},
    ],
}
