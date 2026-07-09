# Portfolio Monitor

自动从 Trading212 获取持仓，推送日报和周度操作复盘到 Telegram。

## 功能概览

| 报告 | 频率 | 文件 | 内容 |
|------|------|------|------|
| **Daily Portfolio Review** | 每个交易日 18:00 CEST | `monitor.py` | 当日涨跌、涨幅/跌幅前3、卖出建议、接近高位提醒 |
| **Weekly Portfolio Review** | 每周六 14:00 CEST | `scripts/weekly_review.py` | 操作复盘（买卖/加仓/减仓）、账户变化、评级、建议 |

## 周度操作复盘示例

```
📊 第28周 投资操作复盘
<i>2026-07-10 00:30 CEST</i>

📋 本周操作
  🟢 火箭实验室(RKLB) 开仓10股
  📈 英伟达(NVDA) +5股 → 15股
  📉 特斯拉(TSLA) -3股 → 5股

💰 账户变化
  总资产 ▼ €92,355 → €90,000 (-2.5%)
  现金 €55,480 → €53,000
  现金比例 59%

📌 当前前5持仓
  Sivers    21.0%  €4.2       1845股  PPL€-2,250
  标普500ETF   8.8%  €127.09    25股   PPL€+27
  迈威尔科技    6.3%  $216.6     11股   PPL$-284

🏆 本周评级: B
  ✅ 新增仓: 火箭实验室
  ⚠️ 前3持仓偏高，现金比例过大

🎯 下周建议
  考虑定投宽基ETF，23个标的偏多建议精简
```

## 文件结构

```
portfolio-monitor/
├── .github/workflows/
│   ├── monitor.yml            # Daily Portfolio Review — 工作日16:00 UTC
│   └── weekly_review.yml      # Weekly Portfolio Review — 周六12:00 UTC
├── scripts/
│   └── weekly_review.py       # 周度操作复盘脚本
├── snapshots/                  # 每周持仓快照（JSON, 保留52周后自动清理）
│   ├── 2026-W28.json
│   └── ...
├── monitor.py                  # 日报脚本：获取数据→分析→推送Telegram
├── trading212.py               # Trading212 API封装 + 自动ticker解析
├── README.md
└── .gitignore
```

## 工作流程

### 日报 (Daily Portfolio Review)
1. `trading212.py` 通过 API 获取 Trading212 全部持仓 + 现金余额
2. 自动解析每个标的的 Yahoo Finance 代码（US→直连，EU→试 `.DE`/`.PA`/`.F` 等）
3. 获取当日涨跌幅（从实际收盘价数组计算，不依赖 `chartPreviousClose`）、30日最高价
4. 盈利标的自动计算限价卖出建议
5. 推送 Telegram（HTML格式）

### 周度操作复盘 (Weekly Portfolio Review)
1. 获取 Trading212 全部持仓 + 现金余额
2. 保存当前快照至 `snapshots/{周}.json`
3. 加载上周快照，对比检测：新增/清仓/加仓/减仓
4. 规则引擎评估本周操作（现金管理、分散度、交易频率等）
5. 生成操作建议
6. 推送 Telegram
7. 自动清理 >52 周的旧快照

## GitHub Secrets 配置

| Secret | 说明 |
|--------|------|
| `TG_BOT_TOKEN` | Telegram Bot Token |
| `TG_CHAT_ID` | Telegram Chat ID |
| `TRADING212_API_KEY` | Trading212 API Key |
| `TRADING212_API_SECRET` | Trading212 API Secret |

## Ticker 覆盖

少数跨市场标的的欧股价格与美股不一致，手动覆盖到美股代码：

| 原始代码 | 覆盖到 | 说明 |
|---------|--------|------|
| 6RJ | RKLB | Rocket Lab |
| 9MW | MRVL | Marvell Technology |
| TSFA | TSM | TSMC ADR |

如需添加覆盖，编辑 `trading212.py` 中的 `_TICKER_OVERRIDE` 字典。

## 本地测试

```bash
# 日报
cd portfolio-monitor
TRADING212_API_KEY="xxx" TRADING212_API_SECRET="xxx" \
TG_BOT_TOKEN="xxx" TG_CHAT_ID="xxx" \
python monitor.py

# 周度操作复盘（需要先跑过一次日报生成快照）
TRADING212_API_KEY="xxx" TRADING212_API_SECRET="xxx" \
TG_BOT_TOKEN="xxx" TG_CHAT_ID="xxx" \
python scripts/weekly_review.py
```

## 快照管理

- 每周快照自动保存至 `snapshots/` 目录并提交到 GitHub
- 最多保留 **52 周**（1年），超出自动删除最旧快照
- 快照格式：JSON，每条约 1KB，一年总计约 50KB
