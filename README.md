# Portfolio Monitor

自动从 Trading212 获取持仓，每日收盘后推送日报到 Telegram。

## 日报内容

```
📊 收盘日报 — 2026-07-02

总净值 €95,100
持仓 €33,179 · 现金 €61,921
累计盈亏 €-5,247 | 今日 8涨 14跌

📈 涨幅前3
  4S0  €91.76 (+3.5%)
  6RJ  $100.46 (+2.5%)
  GOOGL $359.91 (+1.8%)

📉 跌幅前3
  2DG  €4.44 (-24.3%)
  AXTI $56.62 (-20.8%)
  AAOI $120.95 (-19.4%)

🔔 接近高位（关注）
  VUAA €126.31 (30日高 €127.40)
```

## 文件结构

```
portfolio-monitor/
├── .github/workflows/monitor.yml   # GitHub Actions: 每天16:00 UTC运行
├── monitor.py                        # 主脚本：获取数据→分析→推送Telegram
├── trading212.py                     # Trading212 API封装 + 自动ticker解析
└── README.md
```

## 工作流程

1. `trading212.py` 通过 API 获取 Trading212 全部持仓
2. 自动解析每个标的的 Yahoo Finance 代码（US→直连，EU→试`.DE`/`.PA`/`.F`等）
3. 获取今日涨跌幅、30日高价
4. 盈利标的自动计算限价卖出建议
5. 推送 Telegram 日报

## GitHub Secrets 配置

| Secret | 说明 |
|--------|------|
| `TG_BOT_TOKEN` | Telegram Bot Token（用做T bot的） |
| `TG_CHAT_ID` | Telegram Chat ID |
| `TRADING212_API_KEY` | Trading212 API Key |
| `TRADING212_API_SECRET` | Trading212 API Secret |

## Ticker覆盖

少数跨市场标的的欧股价格与美股不一致，手动覆盖到美股代码：

| 原始代码 | 覆盖到 | 说明 |
|---------|--------|------|
| 6RJ | RKLB | Rocket Lab |
| 9MW | MRVL | Marvell Technology |
| TSFA | TSM | TSMC ADR |

如需添加覆盖，编辑 `trading212.py` 中的 `_TICKER_OVERRIDE` 字典。

## 本地测试

```bash
cd portfolio-monitor
TRADING212_API_KEY="xxx" TRADING212_API_SECRET="xxx" \
TG_BOT_TOKEN="xxx" TG_CHAT_ID="xxx" \
python monitor.py
```
