"""
Portfolio sell targets — edit these as your plan changes.
Yahoo ticker: the symbol to fetch from Yahoo Finance.
If the ticker is USD-listed but your cost is in EUR, the
script will auto-convert using live EUR/USD rate.
"""

TARGETS = [
    # GLW — tiny position, just close it
    {
        "name": "GLW (Corning)",
        "ticker": "GLW",          # USD
        "avg_price": 218.41,
        "cost_currency": "EUR",
        "ticker_currency": "USD",
        "targets": [
            {"price": 190.00, "currency": "EUR", "action": "全部清仓 — 回本就出，回收€360加VUAA"},
        ],
        "stop_loss": None,
        "time_limit_days": 60,
        "time_limit_action": "清仓 — 2个月到限，不管盈亏都卖",
    },
    # LPK — German industrial
    {
        "name": "LPK (LPKF Laser)",
        "ticker": "LPK.HA",       # EUR (Hannover exchange)
        "avg_price": 19.79,
        "cost_currency": "EUR",
        "ticker_currency": "EUR",
        "targets": [
            {"price": 20.80, "currency": "EUR", "action": "卖一半(25股) €520 — 反弹5%"},
            {"price": 21.80, "currency": "EUR", "action": "全部清仓 — 反弹10%，小赚离场"},
        ],
        "stop_loss": {"price": 17.00, "currency": "EUR", "action": "清仓 — 跌超10%，止损"},
        "time_limit_days": 90,
        "time_limit_action": "清仓 — 3个月没到目标，不再等",
    },
    # AXTI — deep red, small
    {
        "name": "AXTI (AXT Inc)",
        "ticker": "AXTI",          # USD
        "avg_price": 87.23,
        "cost_currency": "USD",
        "ticker_currency": "USD",
        "targets": [
            {"price": 68.30, "currency": "USD", "action": "卖一半(6-7股) $400 — 反弹15%"},
            {"price": 77.00, "currency": "USD", "action": "全部清仓 — 反弹30%"},
        ],
        "stop_loss": {"price": 50.00, "currency": "USD", "action": "止损 — 新低，不能无限等"},
        "time_limit_days": 60,
        "time_limit_action": "清仓 — 2个月不到目标，割了回收资金",
    },
    # AAOI — AI optical play
    {
        "name": "AAOI (Applied Optoelectronics)",
        "ticker": "AAOI",          # USD
        "avg_price": 157.13,
        "cost_currency": "USD",
        "ticker_currency": "USD",
        "targets": [
            {"price": 136.00, "currency": "USD", "action": "卖一半(7-8股) $950 — 反弹10%"},
            {"price": 148.00, "currency": "USD", "action": "再卖剩下一半(3-4股) — 反弹20%"},
        ],
        "stop_loss": {"price": 100.00, "currency": "USD", "action": "全清 — 跌破$100，技术破位"},
        "time_limit_days": 120,
        "time_limit_action": "留€400底仓其余清 — AI光模块逻辑留小尾巴",
    },
    # XFAB — European foundry
    {
        "name": "XFAB (X-FAB)",
        "ticker": "XFAB.PA",       # EUR
        "avg_price": 10.67,
        "cost_currency": "EUR",
        "ticker_currency": "EUR",
        "targets": [
            {"price": 8.80, "currency": "EUR", "action": "卖一半(75股) €660 — 反弹20%"},
            {"price": 9.65, "currency": "EUR", "action": "全部清仓 — 反弹35%"},
        ],
        "stop_loss": {"price": 6.00, "currency": "EUR", "action": "止损 — 跌18%创新低"},
        "time_limit_days": 90,
        "time_limit_action": "清仓 — 3个月等不到汽车芯片催化",
    },
    # 2DG (Sivers) — biggest concern
    {
        "name": "2DG (Sivers Semiconductors)",
        "ticker": "2DG.F",         # EUR (Frankfurt)
        "avg_price": 5.50,
        "cost_currency": "EUR",
        "ticker_currency": "EUR",
        "targets": [
            {"price": 6.05, "currency": "EUR", "action": "减半仓(875股) €5,300回收 → 降至€3k风险"},
            {"price": 6.60, "currency": "EUR", "action": "再减到€2,000底仓(保留~300股)"},
        ],
        "stop_loss": {"price": 3.50, "currency": "EUR", "action": "全清 — 跌36%，不能再给8%仓位"},
        "time_limit_days": 90,
        "time_limit_action": "减至€3,000以下 — 强制降仓",
    },
    # 6RJ (Rocket Lab) — keep
    {
        "name": "6RJ (Rocket Lab / RKLB)",
        "ticker": "RKLB",          # USD
        "avg_price": 94.82,
        "cost_currency": "EUR",
        "ticker_currency": "USD",
        "targets": [
            {"price": 190.00, "currency": "EUR", "action": "卖一半(6-7股) — 翻倍止盈"},
        ],
        "stop_loss": {"price": 52.00, "currency": "EUR", "action": "全清 — 太空赛道但也得有底线"},
        "time_limit_days": None,
        "time_limit_action": None,
    },
]

# DCA monitoring
DCA_CONFIG = {
    "vuas_ticker": "VUAA.DE",
    "sxrv_ticker": "SXRV.DE",
    "ma_period": 200,
    "weekly_drop_threshold": -8.0,
    "annual_gain_threshold": 20.0,
}
