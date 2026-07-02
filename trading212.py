"""
Trading212 API helpers — fetch portfolio, auto-resolve Yahoo tickers.
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

# ── Known overrides for problematic tickers ──────────────
# Auto-resolver finds the European exchange listing, but some
# cross-listed stocks have odd price ratios on European exchanges.
# These override to the canonical US ticker for accurate data.
_TICKER_OVERRIDE = {
    "6RJ": "RKLB",    # Rocket Lab — correct exchange symbol is 6RJ0
    "9MW": "MRVL",    # Marvell
    "TSFA": "TSM",    # TSMC ADR
}
# Cache: resolved Yahoo ticker once found (in-memory, per-run)
_YAHOO_CACHE: dict[str, str | None] = {}

# European exchange suffixes to try, in priority order
_EU_SUFFIXES = [".DE", ".PA", ".F", ".HA", ".AS", ".L", ".MI", ".BR", ".ST", ".CO"]


def _test_yahoo_ticker(symbol: str) -> bool:
    """Quick check if a Yahoo ticker returns real data."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            result = data["chart"]["result"]
            if result and result[0]["meta"]["regularMarketPrice"]:
                return True
    except Exception:
        pass
    return False


def clean_ticker(raw: str) -> str:
    """Extract clean ticker symbol from Trading212 raw ticker.
    E.g. 'LPKd_EQ' -> 'LPK', 'AAOI_US_EQ' -> 'AAOI'
    """
    ticker = str(raw).split("_")[0]
    # Strip trailing lowercase letters (e.g. SOIp -> SOI, 2DGd -> 2DG)
    while ticker and ticker[-1].islower() and not ticker[-1].isdigit():
        ticker = ticker[:-1]
    return ticker.upper()


def resolve_yahoo_ticker(raw_ticker: str) -> tuple[str | None, str]:
    """Auto-resolve Trading212 ticker to Yahoo Finance symbol + currency.

    Returns: (yahoo_symbol, 'USD' | 'EUR')
    - For US stocks (_US_EQ): returns clean symbol directly
    - For European stocks: tries exchange suffixes until one works
    - Returns (None, '?') if no resolution found
    """
    clean_sym = clean_ticker(raw_ticker)

    # Check override first
    if clean_sym in _TICKER_OVERRIDE:
        override = _TICKER_OVERRIDE[clean_sym]
        result = (override, "USD")
        return result

    cache_key = f"{raw_ticker}|{clean_sym}"

    if cache_key in _YAHOO_CACHE:
        cached = _YAHOO_CACHE[cache_key]
        if cached is None:
            return (None, "?")
        return cached

    raw_upper = raw_ticker.upper()

    # --- US stocks ---
    if "_US_EQ" in raw_upper:
        # Try clean symbol directly as Yahoo ticker
        if _test_yahoo_ticker(clean_sym):
            result = (clean_sym, "USD")
            _YAHOO_CACHE[cache_key] = result
            return result
        # If clean symbol fails (unlikely for US stocks), try anyway
        # (some obscure tickers might not work, but most will)
        _YAHOO_CACHE[cache_key] = (clean_sym, "USD")
        return (clean_sym, "USD")

    # --- European stocks ---
    # Try suffixes in priority order
    for sfx in _EU_SUFFIXES:
        candidate = clean_sym + sfx
        if _test_yahoo_ticker(candidate):
            result = (candidate, "EUR")
            _YAHOO_CACHE[cache_key] = result
            return result

    # Fallback: try clean symbol as-is (some EU stocks work without suffix)
    if _test_yahoo_ticker(clean_sym):
        result = (clean_sym, "EUR")
        _YAHOO_CACHE[cache_key] = result
        return result

    _YAHOO_CACHE[cache_key] = None
    return (None, "?")


def resolve_currency(raw_ticker: str) -> str:
    """Determine if a position is priced in USD or EUR."""
    if "_US_EQ" in raw_ticker.upper():
        return "USD"
    return "EUR"


# ── Config ───────────────────────────────────────────────

def load_config() -> dict:
    """Load Trading212 API credentials. Env vars override config file."""
    if ENV_KEY and ENV_SECRET:
        return {
            "trading212_api_key": ENV_KEY,
            "trading212_api_secret": ENV_SECRET,
        }
    if not os.path.exists(CONFIG_PATH):
        alt = os.path.join(os.path.dirname(__file__), "..", "config.json")
        path = alt if os.path.exists(alt) else CONFIG_PATH
    else:
        path = CONFIG_PATH
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {"trading212_api_key": "", "trading212_api_secret": ""}


# ── API calls ────────────────────────────────────────────

def _auth_headers() -> dict:
    cfg = load_config()
    key = cfg.get("trading212_api_key", "").strip()
    secret = cfg.get("trading212_api_secret", "").strip()
    if not key:
        return {}
    encoded = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("utf-8")
    return {
        "Accept": "application/json",
        "Authorization": f"Basic {encoded}",
        "User-Agent": "PortfolioMonitor/1.0",
    }


def fetch_portfolio() -> list[dict]:
    """Fetch current portfolio from Trading212 live API."""
    headers = _auth_headers()
    if not headers:
        print("  [SKIP] No Trading212 API key configured")
        return []
    req = urllib.request.Request(
        "https://live.trading212.com/api/v0/equity/portfolio",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_cash() -> dict:
    """Fetch cash/account info from Trading212."""
    headers = _auth_headers()
    if not headers:
        return {}
    req = urllib.request.Request(
        "https://live.trading212.com/api/v0/equity/account/cash",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ── Enrichment ───────────────────────────────────────────

def enrich_positions(positions: list[dict]) -> list[dict]:
    """Add clean_symbol, yahoo_ticker, and currency to each position."""
    for p in positions:
        raw = p.get("ticker", "")
        p["clean_symbol"] = clean_ticker(raw)
        p["yahoo_ticker"], p["currency"] = resolve_yahoo_ticker(raw)
        # PPL from Trading212
        ppl = float(p.get("ppl") or 0)
        fx = float(p.get("fxPpl") or 0)
        p["total_ppl"] = round(ppl + fx, 2)
        p["current_value"] = round(
            float(p.get("quantity", 0)) * float(p.get("currentPrice", 0)), 2
        )
    return positions
