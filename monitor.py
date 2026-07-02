#!/usr/bin/env python3
"""
Portfolio Monitor v2 — auto-fetch from Trading212, suggest limit sells for profitable positions.
Runs via GitHub Actions on schedule.

Strategy:
  - Fetch current portfolio from Trading212 live API
  - For each position in profit: calculate a limit sell price (near recent high)
  - Notify via Telegram with actionable suggestions
  - Only sell profitable positions (user's rule)
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

from trading212 import (
    fetch_portfolio, fetch_cash, enrich_positions,
    is_us_ticker, get_yahoo_ticker,
)


# ── Config overrides via env vars ─────────────────────────
# On GitHub Actions, set these as secrets
TRADING212_API_KEY = os.environ.get("TRADING212_API_KEY") or ""
TRADING212_API_SECRET = os.environ.get("TRADING212_API_SECRET") or ""


# ── Price helpers ────────────────────────────────────────

def fetch_price(yahoo_ticker: str) -> float | None:
    """Fetch current price from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception as e:
        print(f"  [WARN] {yahoo_ticker}: {e}")
        return None


def fetch_highs(yahoo_ticker: str, days: int = 30) -> dict:
    """Fetch recent price history and return highs.

    Returns: {
        'current': float,
        'high_20d': float,    # highest close in last 20 days
        'high_30d': float,    # highest close in last 30 days
        'close_5d_ago': float # price 5 days ago (for trend)
    }
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            quotes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in quotes if c is not None]
            if not closes:
                return None

            current = closes[-1]
            result = {
                "current": current,
                "high_20d": max(closes[-20:]) if len(closes) >= 20 else max(closes),
                "high_30d": max(closes),
                "close_5d_ago": closes[-6] if len(closes) >= 6 else closes[0],
                "is_near_high": current >= max(closes[-10:]) * 0.97 if len(closes) >= 10 else False,
            }
            return result
    except Exception as e:
        print(f"  [WARN] History {yahoo_ticker}: {e}")
        return None


def fetch_eurusd() -> float:
    """Get live EUR/USD rate."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return 1.08


# ── Sell strategy ──────────────────────────────────────

def suggest_limit_price(price_data: dict, avg_cost: float, currency: str, eurusd: float) -> dict | None:
    """Calculate the best limit sell price for a profitable position.

    Strategy (sell at high point):
    1. If stock is near its 20-day high → set limit at 20-day high
    2. If stock has pulled back >5% from high → set limit at high_20d * 0.98
    3. If stock is steadily rising → set limit at current * 1.03 (3% above)
    4. Always at least 2% above current price to leave room

    Returns {'limit_price': float, 'limit_currency': str, 'reason': str} or None
    """
    current = price_data["current"]
    high_20d = price_data["high_20d"]
    high_30d = price_data["high_30d"]
    close_5d = price_data["close_5d_ago"]
    profit_pct = (current - avg_cost) / avg_cost * 100

    # Convert avg_cost to the currency of the price data
    # (price data is in USD for US tickers, EUR for EU tickers)

    # How far from 20-day high?
    pct_from_high = (high_20d - current) / high_20d * 100

    if price_data["is_near_high"] and pct_from_high < 1:
        # Near the high — set limit at the 30-day high (reach for it)
        limit = round(high_30d, 2)
        reason = f"接近20日高({high_20d:.2f})，设限价于30日高"
    elif pct_from_high > 5:
        # Pulled back significantly — set limit near the high
        limit = round(high_20d * 0.98, 2)
        reason = f"从20日高回撤{pct_from_high:.1f}%，设限价于高位的98%"
    elif current > close_5d * 1.03:
        # Rising trend — set limit 3% above current
        limit = round(current * 1.03, 2)
        reason = "上升趋势中，设限价在现价+3%"
    else:
        # Sideways — set limit at 5% above current or 20d high - 2%, whichever lower
        limit = round(max(current * 1.02, high_20d * 0.97), 2)
        reason = f"横盘整理，设限价在高位附近"

    # Ensure limit is above current price
    if limit <= current:
        limit = round(current * 1.02, 2)
        reason = "限价必须高于现价，设为+2%"

    return {
        "limit_price": limit,
        "currency": currency,
        "current_price": round(current, 2),
        "profit_pct": round(profit_pct, 1),
        "avg_cost": round(avg_cost, 2),
        "reason": reason,
    }


# ── Telegram ─────────────────────────────────────────────

def send_telegram(message: str):
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        print("[SKIP] No TG secrets — printing:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        print("  [OK] Telegram sent")
    except Exception as e:
        print(f"  [ERROR] Telegram: {e}")


def escape_md(text: str) -> str:
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Main ────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    print(f"=== Portfolio Monitor v2 — {now.strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    # 1. Fetch portfolio
    print("── Fetching portfolio from Trading212 ──")
    positions = fetch_portfolio()
    if not positions:
        print("  No positions found or API error. Exiting.")
        return
    enrich_positions(positions)
    print(f"  Found {len(positions)} positions\n")

    # 2. Fetch cash
    cash_data = fetch_cash()
    free_cash = float(cash_data.get("free", 0)) if cash_data else 0
    total_cash = float(cash_data.get("total", 0)) if cash_data else 0

    # 3. Fetch FX
    eurusd = fetch_eurusd()
    print(f"  EUR/USD: {eurusd:.4f}\n")

    # 4. Check each position
    sell_signals = []
    portfolio_summary = []

    for pos in positions:
        cs = pos["clean_symbol"]
        yt = pos["yahoo_ticker"]
        qty = float(pos["quantity"])
        avg = float(pos["averagePrice"])
        curr = float(pos["currentPrice"])
        ppl = pos["total_ppl"]
        value = pos["current_value"]

        if not yt:
            print(f"  {cs}: no Yahoo ticker mapping, skipping")
            continue

        # Determine display currency
        is_usd = is_us_ticker(cs)
        display_cur = "$" if is_usd else "€"

        # Convert avg cost to USD if needed for comparison
        price_data = fetch_highs(yt)

        line = f"  {cs:>6} ({yt:<10})  {display_cur}{curr:<8}  avg {avg:<8}  PPL {display_cur}{ppl:<+8}"
        portfolio_summary.append(line)

        # Only care about profitable positions
        if ppl <= 0:
            line += f"  🔴亏损 跳过"
            print(line)
            continue

        # Skip tiny profits (not worth selling)
        profit_pct = (curr - avg) / avg * 100
        if ppl < 20 and profit_pct < 3:
            line += f"  ✅盈利({ppl:+.0f}) 但太小，跳过"
            print(line)
            continue

        line += f"  ✅盈利"
        print(line)

        if price_data is None:
            print(f"    ⚠️  No price history for {yt}")
            continue

        # Calculate suggested limit sell
        # Need to handle currency: price_data.current is in the ticker's currency
        # avg cost might be in a different currency
        # For simplicity, compare in the ticker's native currency
        # If avg is in EUR and ticker is USD, convert avg to USD
        if is_usd and "EUR" in str(pos.get("ticker", "")):
            # Cost was in EUR but we're looking at USD price
            avg_in_cur = avg * eurusd
            cur_label = f"${price_data['current']} (成本约${avg_in_cur:.2f})"
        else:
            avg_in_cur = avg
            cur_label = f"{display_cur}{avg:.2f}"

        if price_data["current"] > avg_in_cur:
            suggestion = suggest_limit_price(
                price_data, avg_in_cur,
                "$" if is_usd else "€",
                eurusd
            )
            if suggestion:
                sell_signals.append({
                    "name": f"{cs} ({yt})",
                    "qty": qty,
                    **suggestion,
                })
                print(f"    📈 建议限价卖: {suggestion['currency']}{suggestion['limit_price']} ({suggestion['reason']})")
        else:
            print(f"    ⚠️ Yahoo价({price_data['current']}) < 成本({avg_in_cur})，可能是汇率问题")

    # 5. Build report
    print(f"\n── Results ──")
    total_value = sum(p["current_value"] for p in positions)
    total_ppl = sum(p["total_ppl"] for p in positions)
    print(f"  持仓市值: €{total_value:,.2f}")
    print(f"  可用现金: €{free_cash:,.2f}")
    print(f"  累计盈亏: €{total_ppl:+,.2f}")

    if sell_signals:
        # Build Telegram message
        lines = [f"📊 *Portfolio Monitor — {today}*\n"]

        # Summary header
        lines.append(escape_md(
            f"持仓 €{total_value:,.0f} | 现金 €{free_cash:,.0f} | 盈亏 €{total_ppl:+,.0f}"
        ))
        lines.append("")
        lines.append(f"*🔔 {len(sell_signals)} 个盈利标的有卖出建议*")
        lines.append("")

        for s in sell_signals:
            lines.append(
                f"*{s['name']}*\n"
                f"💰 盈利 {escape_md(str(s['profit_pct']))}%  | 持仓 {s['qty']}股\n"
                f"📈 限价卖: *{s['currency']}{escape_md(str(s['limit_price']))}*\n"
                f"  现价 {s['currency']}{s['current_price']}  | 成本 {s['currency']}{s['avg_cost']}\n"
                f"  _{escape_md(s['reason'])}_\n"
            )

        lines.append("_建议在Trading212设置Limit Order_\n")

        msg = "\n".join(lines)
    else:
        msg_lines = [f"📊 *Portfolio Monitor — {today}*\n"]
        msg_lines.append(escape_md(
            f"持仓 €{total_value:,.0f} | 现金 €{free_cash:,.0f} | 盈亏 €{total_ppl:+,.0f}"
        ))
        msg_lines.append("\n✅ 当前没有盈利标的需要卖出建议。")
        msg = "\n".join(msg_lines)

    print(f"\n── Sending ──")
    send_telegram(msg)
    print("Done.")


if __name__ == "__main__":
    main()
