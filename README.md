# 量化交易基础任务 · HW1

个人作业展示页：彭博终端风格、纯 HTML/CSS/JS 单文件实现，数据通过 Tushare 获取并内联。

## 目录结构

```
HW1/
├── index.html          # 网页入口（双击即开，零依赖）
├── maotai_close.png    # 贵州茅台 600519 收盘价曲线图
├── maotai_stock.csv    # 贵州茅台 近一年日线数据（243 个交易日）
├── get_stock_data.py   # 通过 Tushare 拉取数据的脚本
└── README.md
```

## 数据范围

- **标的**：贵州茅台（600519.SH）
- **周期**：2025-07-01 ~ 2026-07-01（243 个交易日）
- **来源**：[Tushare](https://tushare.pro)

## 本地打开

直接双击 `index.html`，或在终端里：

```bash
# 方式一：直接打开
start index.html        # Windows
open index.html         # macOS

# 方式二：起一个本地服务器（推荐）
python -m http.server 8090
# 然后浏览器访问 http://localhost:8090
```

## 复现数据

```bash
# 安装依赖
pip install tushare pandas matplotlib

# 替换 get_stock_data.py 里的 token 后运行
python get_stock_data.py
```

## 板块概览

1. **量化交易的优势** — 传统 vs 量化 五维对比
2. **基本概念** — K线 / 基本面 / 技术面
3. **数据实践** — 茅台近一年日线 + 收盘价曲线 + CSV 下载

## 配色

A 股惯例：**红涨绿跌**。

| 颜色 | 含义 |
|------|------|
| 红 `#ff4d6d` | 上涨 |
| 绿 `#25e899` | 下跌 |
| 青 `#00e5ff` | 中性 / 强调 |
| 琥珀 `#ffb300` | 高亮 / 注释 |

> 仅供学习研究使用，不构成任何投资建议。
