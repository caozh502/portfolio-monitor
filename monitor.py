#!/usr/bin/env python3
"""
Portfolio Monitor — daily close report.
Fetches portfolio from Trading212, analyses positions, sends Telegram briefing.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

from trading212 import fetch_portfolio, fetch_cash, enrich_positions


# ── Price helpers ────────────────────────────────────────

def fetch_today_data(yahoo_ticker: str) -> dict | None:
    """Fetch today's price and day change for a ticker.

    Returns: {'price': float, 'change_pct': float} or None
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range=3d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            quotes = result["indicators"]["quote"][0]
            closes = [c for c in quotes.get("close", []) if c is not None]

            current = float(meta["regularMarketPrice"])
            prev_close = float(meta.get("chartPreviousClose", closes[-2] if len(closes) >= 2 else current))
            change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0

            # 30-day high
            high_30d = max(closes) if closes else current
            is_near_high = current >= high_30d * 0.97 if high_30d else False

            return {
                "price": current,
                "change_pct": round(change_pct, 2),
                "prev_close": prev_close,
                "high_30d": high_30d,
                "is_near_high": is_near_high,
            }
    except Exception as e:
        print(f"  [WARN] {yahoo_ticker}: {e}")
        return None


def fetch_eurusd() -> float:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return 1.08


# ── Sell logic ───────────────────────────────────────────

def suggest_limit(today: dict, avg_cost: float, currency: str) -> dict | None:
    """Suggest a limit sell price for a profitable position."""
    price = today["price"]
    profit_pct = (price - avg_cost) / avg_cost * 100

    if today["is_near_high"]:
        limit = round(today["high_30d"], 2)
        reason = f"接近30日高，设限价于{today['high_30d']:.2f}"
    elif today["change_pct"] > 0:
        limit = round(price * 1.03, 2)
        reason = f"今日上涨+{today['change_pct']:.1f}%，限价+3%"
    else:
        limit = round(price * 1.02, 2)
        reason = f"今日下跌{today['change_pct']:.1f}%，限价+2%等反弹"

    return {
        "limit_price": limit,
        "currency": currency,
        "current_price": round(price, 2),
        "profit_pct": round(profit_pct, 1),
        "avg_cost": round(avg_cost, 2),
        "reason": reason,
    }


# ── Telegram ─────────────────────────────────────────────

def send_telegram(message: str):
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        print("[SKIP] No TG secrets")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": message,
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        print("  [OK] Telegram sent")
    except Exception as e:
        print(f"  [ERROR] Telegram: {e}")


# ── Main ────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    print(f"=== Portfolio Monitor — {today} {now.strftime('%H:%M')} UTC ===\n")

    # 1. Fetch
    positions = fetch_portfolio()
    if not positions:
        print("  No positions. Exiting.")
        return
    enrich_positions(positions)

    cash_data = fetch_cash()
    free_cash = float(cash_data.get("free", 0)) if cash_data else 0
    eurusd = fetch_eurusd()
    print(f"  {len(positions)} positions, EUR/USD={eurusd:.4f}\n")

    # 2. Analyse each position
    enriched = []
    total_pos_value = 0
    total_ppl = 0

    for pos in positions:
        cs = pos["clean_symbol"]
        yt = pos["yahoo_ticker"]
        qty = float(pos["quantity"])
        avg = float(pos["averagePrice"])
        curr_t212 = float(pos["currentPrice"])
        ppl = pos["total_ppl"]
        val = pos["current_value"]
        cur = pos.get("currency", "EUR")
        display = "$" if cur == "USD" else "€"
        total_pos_value += val
        total_ppl += ppl

        entry = {
            "cs": cs, "yt": yt, "qty": qty, "avg": avg,
            "price_t212": curr_t212, "ppl": ppl, "value": val,
            "cur": cur, "display": display,
            "today": None, "sell_signal": None,
        }

        if not yt:
            print(f"  {cs}: no Yahoo ticker")
            enriched.append(entry)
            continue

        today_data = fetch_today_data(yt)
        entry["today"] = today_data

        if today_data:
            # Use Yahoo price for more accurate day-change data
            entry["price_live"] = today_data["price"]
            line = (f"  {cs:>6} {display}{today_data['price']:<8} "
                    f"日涨跌{today_data['change_pct']:>+6.1f}%  "
                    f"PPL{display}{ppl:<+8}")
            print(line)

            # Sell signal — only profitable positions with meaningful profit
            if ppl > 20 or (ppl > 0 and (curr_t212 - avg) / avg * 100 > 5):
                signal = suggest_limit(today_data, avg, display)
                if signal:
                    signal["name"] = f"{cs} ({yt})"
                    signal["qty"] = qty
                    entry["sell_signal"] = signal
                    print(f"    → 建议限价卖: {display}{signal['limit_price']} ({signal['reason']})")
        else:
            print(f"  {cs}: no live data")

        enriched.append(entry)

    # 3. Sort for report
    total_val = total_pos_value + free_cash
    # Movers: positions with today data
    with_today = [e for e in enriched if e["today"] is not None]
    gainers = sorted(with_today, key=lambda e: e["today"]["change_pct"], reverse=True)[:5]
    losers = sorted(with_today, key=lambda e: e["today"]["change_pct"])[:5]
    sell_signals = [e["sell_signal"] for e in enriched if e["sell_signal"] is not None]

    # 4. Count positions by movement type
    up = sum(1 for e in with_today if e["today"]["change_pct"] > 0)
    dn = sum(1 for e in with_today if e["today"]["change_pct"] < 0)

    # 5. Build daily report
    lines = [f"📊 收盘日报 — {today}\n"]

    # Summary
    lines.append(f"总净值 €{total_val:,.0f}")
    lines.append(f"持仓 €{total_pos_value:,.0f}  ·  现金 €{free_cash:,.0f}")
    lines.append(f"累计盈亏 €{total_ppl:+,.0f}   |   今日 {up}涨 {dn}跌")
    lines.append("")

    # Top movers
    if gainers and gainers[0]["today"]["change_pct"] > 0:
        lines.append("📈 涨幅前3")
        for e in gainers[:3]:
            d = e["today"]
            lines.append(f"  {e['cs']}  {e['display']}{d['price']:.2f}  ({d['change_pct']:+.1f}%)")
        lines.append("")

    if losers and losers[0]["today"]["change_pct"] < 0:
        lines.append("📉 跌幅前3")
        for e in losers[:3]:
            d = e["today"]
            lines.append(f"  {e['cs']}  {e['display']}{d['price']:.2f}  ({d['change_pct']:+.1f}%)")
        lines.append("")

    # Sell signals
    if sell_signals:
        lines.append(f"💡 卖出建议 ({len(sell_signals)}个)")
        for s in sell_signals[:5]:
            pct_str = f"{s['profit_pct']:+.1f}%"
            lines.append(f"  {s['name']}  盈利{pct_str}")
            lines.append(f"    限价: {s['currency']}{s['limit_price']}  |  现价 {s['currency']}{s['current_price']}")
        lines.append("")

    # Positions near 30-day high (potential sell candidates for future)
    near_high = [e for e in with_today if e["today"] and e["today"]["is_near_high"] and e["ppl"] > 0]
    if near_high:
        lines.append(f"🔔 接近高位（关注）")
        for e in near_high[:3]:
            d = e["today"]
            lines.append(f"  {e['cs']}  {e['display']}{d['price']:.2f} (30日高 {e['display']}{d['high_30d']:.2f})")
        lines.append("")

    msg = "\n".join(lines)

    print(f"\n── Sending ──")
    send_telegram(msg)
    print("Done.")


if __name__ == "__main__":
    main()
