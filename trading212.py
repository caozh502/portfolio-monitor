"""
Trading212 API helpers — fetch portfolio, map tickers.
"""
import base64
import json
import os
import urllib.request
import urllib.error

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# Env var overrides for GitHub Actions
ENV_KEY = os.environ.get("TRADING212_API_KEY") or ""
ENV_SECRET = os.environ.get("TRADING212_API_SECRET") or ""


# ── Ticker mapping: Trading212 raw -> Yahoo Finance ──────────
# Trading212 returns tickers like "LPKd_EQ", "AAOI_US_EQ"
# We map them to Yahoo Finance symbols for price history lookups
# European stocks need exchange suffixes (.DE, .PA, .HA, .F, etc.)
TICKER_MAP = {
    # European stocks (EUR-priced on Yahoo)
    "LPK": "LPK.HA",      # LPKF Laser — Hannover
    "SOI": "SOI.PA",      # Soitec — Paris
    "XFAB": "XFAB.PA",    # X-FAB — Paris
    "IFX": "IFX.DE",      # Infineon — Xetra
    "INL": "INL.DE",      # Intel — Xetra
    "2DG": "2DG.F",       # Sivers — Frankfurt
    "YDX": "YDX.DE",      # Nebius — Xetra
    "SPX": "SPX.DE",      # Space Exploration — Xetra
    "DRAM": "DRAM.DE",    # Defiance Memory ETF — Xetra
    "SXRV": "SXRV.DE",    # iShares NASDAQ 100 — Xetra
    "VUAA": "VUAA.DE",    # Vanguard S&P 500 — Xetra

    # US stocks (USD-priced on Yahoo)
    "6RJ": "RKLB",        # Rocket Lab
    "9MW": "MRVL",        # Marvell
    "GLW": "GLW",         # Corning
    "TSFA": "TSM",        # TSMC ADR
    "4S0": "NOW",         # ServiceNow
    "NOA3": "NOK",        # Nokia
    "ABEA": "GOOGL",      # Alphabet C
    "AXTI": "AXTI",       # AXT Inc
    "AAOI": "AAOI",       # Applied Optoelectronics
    "FLNC": "FLNC",       # Fluence Energy
    "GOOGL": "GOOGL",     # Alphabet A
    "RKLB": "RKLB",       # Rocket Lab
    "MU": "MU",           # Micron
    "MRVL": "MRVL",       # Marvell
    "NVDA": "NVDA",       # NVIDIA
    "QQQ": "QQQ",         # NASDAQ ETF
}

# Tickers that return USD prices from Yahoo Finance
USD_TICKERS = {
    "6RJ", "9MW", "GLW", "TSFA", "4S0", "NOA3", "ABEA",
    "AXTI", "AAOI", "FLNC", "GOOGL", "RKLB",
    "MU", "MRVL", "NVDA", "QQQ",
}


def load_config() -> dict:
    """Load Trading212 API credentials. Env vars override config file."""
    # Env vars first (for GH Actions)
    if ENV_KEY and ENV_SECRET:
        return {
            "trading212_api_key": ENV_KEY,
            "trading212_api_secret": ENV_SECRET,
        }

    # Fallback to local config.json
    if not os.path.exists(CONFIG_PATH):
        alt = os.path.join(os.path.dirname(__file__), "..", "config.json")
        if os.path.exists(alt):
            path = alt
        else:
            return {"trading212_api_key": "", "trading212_api_secret": ""}
    else:
        path = CONFIG_PATH

    with open(path) as f:
        return json.load(f)


def fetch_portfolio() -> list[dict]:
    """Fetch current portfolio from Trading212 live API."""
    cfg = load_config()
    key = cfg.get("trading212_api_key", "").strip()
    secret = cfg.get("trading212_api_secret", "").strip()

    if not key:
        print("  [SKIP] No Trading212 API key configured")
        return []

    encoded = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("utf-8")
    auth = f"Basic {encoded}"

    url = "https://live.trading212.com/api/v0/equity/portfolio"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": auth,
        "User-Agent": "PortfolioMonitor/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_cash() -> dict:
    """Fetch cash/account info from Trading212."""
    cfg = load_config()
    key = cfg.get("trading212_api_key", "").strip()
    secret = cfg.get("trading212_api_secret", "").strip()
    if not key:
        return {}

    encoded = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("utf-8")
    auth = f"Basic {encoded}"

    url = "https://live.trading212.com/api/v0/equity/account/cash"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": auth,
        "User-Agent": "PortfolioMonitor/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def clean_ticker(raw: str) -> str:
    """Extract clean ticker symbol from Trading212 raw ticker.
    E.g. 'LPKd_EQ' -> 'LPK', 'AAOI_US_EQ' -> 'AAOI'
    """
    ticker = str(raw).split("_")[0]
    # Strip trailing lowercase letters (e.g. SOIp -> SOI, 2DGd -> 2DG)
    while ticker and ticker[-1].islower() and not ticker[-1].isdigit():
        ticker = ticker[:-1]
    return ticker.upper()


def get_yahoo_ticker(clean_sym: str) -> str | None:
    """Map clean ticker to Yahoo Finance symbol."""
    return TICKER_MAP.get(clean_sym)


def is_us_ticker(clean_sym: str) -> bool:
    """Check if a ticker is USD-priced on Yahoo."""
    return clean_sym in USD_TICKERS


def enrich_positions(positions: list[dict]) -> list[dict]:
    """Add clean_symbol and yahoo_ticker to each position."""
    for p in positions:
        raw = p.get("ticker", "")
        cs = clean_ticker(raw)
        p["clean_symbol"] = cs
        p["yahoo_ticker"] = get_yahoo_ticker(cs)
        # PPL from Trading212
        ppl = float(p.get("ppl") or 0)
        fx = float(p.get("fxPpl") or 0)
        p["total_ppl"] = round(ppl + fx, 2)
        p["current_value"] = round(float(p.get("quantity", 0)) * float(p.get("currentPrice", 0)), 2)
    return positions
