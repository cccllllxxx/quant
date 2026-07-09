# -*- coding: utf-8 -*-
"""
HW3 双均线策略回测与可视化看板生成脚本  v2（增强版）
=====================================
v2 增强内容：
  ✅ 使用 Tushare 拉取的更长历史数据（3~4.5年 vs 原始 0.5~1年）
  ✅ 支持前复权价格（平安银行已含复权因子，消除除权缺口对信号的影响）
  ✅ 看板新增：日期范围选择器 / 复权开关 / 重置按钮 / 超额收益突出显示
  ✅ 概念讲解区增加「复权」专门说明
  ✅ 对标老师示例看板功能

任务要求：
  1) 加载已存储的股价数据
  2) 设定短/长均线周期，计算均线
  3) 计算买入/卖出交易信号（金叉/死叉）
  4) 绘制可视化图形（价格、长短均线、买卖信号）
  5) 模拟交易回测，计算量化指标（MDD / Sharpe / 累计回报 等）
  6) 尝试不同股票、均线周期，总结双均线策略适用场景

输出：
  - data/*.png           matplotlib 绘制的静态图表
  - data/backtest_metrics.json   默认参数(5,15)下的指标
  - data/experiment_summary.json 不同股票×周期的实验对比
  - 双均线策略看板.html   交互式看板（核心交付物）

约定：
  - 无风险利率 rf=0；年化因子 252 交易日
  - 成交于信号次日开盘（position 整体后移 1 日），严格防未来函数
  - 佣金默认万三(0.0003)，支持万一(0.0001)；滑点默认 0.0005，均可调
  - A股配色：涨红(#ff4d6d) 跌绿(#25e899)；买入信号红▲、卖出信号绿▼
"""

import os
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 注册中文字体，避免 PNG 标题出现方块字
for _fp in [r'C:/Windows/Fonts/simhei.ttf',
            r'C:/Windows/Fonts/msyh.ttc',
            r'C:/Windows/Fonts/NotoSansSC-VF.ttf']:
    if os.path.exists(_fp):
        try:
            fm.fontManager.addfont(_fp)
            _fn = fm.FontProperties(fname=_fp).get_name()
            plt.rcParams['font.sans-serif'] = [_fn]
            break
        except Exception:
            pass
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 路径与配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# A股配色
COLOR_UP = '#ff4d6d'      # 涨 / 买入 红
COLOR_DOWN = '#25e899'    # 跌 / 卖出 绿
COLOR_CLOSE = '#2b2b2b'
COLOR_MA_S = '#ffa940'    # 短均线 橙
COLOR_MA_L = '#4d8bff'    # 长均线 蓝

ANNUAL_FACTOR = 252       # 每年交易日数
RF = 0.0                  # 无风险利率

# 股票配置：(csv文件名, 代码, 显示名, 数据说明, 前复权文件名或None)
STOCK_CONFIG = {
    "maotai": ("maotai_daily.csv", "600519.SH", "贵州茅台",
               "Tushare日线, 2023-01~2026-07, 约844个交易日",
               "maotai_daily_qfq.csv"),  # 前复权(由OHLC重建, 已验证)
    "pingan": ("pingan_daily.csv", "000001.SZ", "平安银行",
               "Tushare日线, 2022-01~2026-07, 约1086个交易日",
               "pingan_daily_qfq.csv"),  # 前复权(由OHLC重建, 已验证)
    "sany":   ("sany_daily.csv", "600031.SH", "三一重工",
               "Tushare日线, 2022-01~2026-07, 约1086个交易日",
               "sany_daily_qfq.csv"),  # 前复权(由OHLC重建, 已验证)
}

# 实验扫描的均线周期组合
PERIOD_SWEEP = [(5, 15), (5, 20), (10, 30), (20, 60)]

# 默认参数（对标老师示例用 SMA(6,28)，但我们保留 (5,15) 作为默认作业值）
DEFAULT_SHORT = 5
DEFAULT_LONG = 15


# ============================================================
# 1) 加载已存储的股价数据（支持原始/前复权）
# ============================================================
def load_stock(filename, code, name, note, qfq_filename=None, use_qfq=False):
    """
    加载 CSV 股价数据。
    use_qfq=True 时尝试加载前复权版本；若不存在则回退到原始数据并给出警告。
    """
    filepath = os.path.join(DATA_DIR, filename)
    df = pd.read_csv(filepath, encoding='utf-8-sig')

    # 若请求前复权且有对应文件
    if use_qfq and qfq_filename:
        qfq_path = os.path.join(DATA_DIR, qfq_filename)
        if os.path.exists(qfq_path):
            df = pd.read_csv(qfq_path, encoding='utf-8-sig')
            note = note + " [前复权]"
        else:
            note = note + " [警告: 无前复权文件，使用原始价]"

    # 兼容两种日期格式：紧凑 YYYYMMDD 与 ISO 2025-07-01
    dt = pd.to_datetime(df['trade_date'], format='%Y%m%d', errors='coerce')
    if dt.isna().any():
        dt = dt.fillna(pd.to_datetime(df['trade_date'], errors='coerce'))
    df['trade_date'] = dt
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['code'] = code
    df['name'] = name
    df['note'] = note
    df['daily_ret'] = df['close'].pct_change().fillna(0.0)

    # 记录是否为前复权模式
    df['_use_qfq'] = use_qfq
    return df


# ============================================================
# 2) 计算均线 + 3) 交易信号（金叉/死叉，防未来函数）
# ============================================================
def compute_ma_and_signals(df, short, long):
    """
    计算短/长均线，并生成金叉(买入)/死叉(卖出)信号。
    严格防未来函数：信号在当日收盘判定，仓位在次日开盘生效。
    """
    close = df['close']
    ma_s = close.rolling(short).mean()
    ma_l = close.rolling(long).mean()

    diff = ma_s - ma_l
    prev = diff.shift(1)

    n = len(df)
    golden = np.zeros(n, dtype=bool)
    death = np.zeros(n, dtype=bool)
    position = np.zeros(n)
    cur = 0.0
    for i in range(1, n):
        # 仅在长短均线均已有效、且确实发生"仓位切换"时标记信号，避免已空仓时的冗余死叉
        if pd.notna(ma_s.iloc[i]) and pd.notna(ma_l.iloc[i]) and pd.notna(prev.iloc[i]):
            d = diff.iloc[i]
            dp = prev.iloc[i]
            if dp <= 0 and d > 0 and cur == 0:       # 金叉：空仓->买入
                golden[i] = True
                cur = 1.0
            elif dp >= 0 and d < 0 and cur == 1:      # 死叉：持仓->卖出
                death[i] = True
                cur = 0.0
        position[i] = cur
    position = pd.Series(position, index=df.index)
    position_exec = position.shift(1).fillna(0.0)  # 次日开盘成交 -> 执行仓位

    return ma_s, ma_l, golden, death, position, position_exec


# ============================================================
# 4) 回测引擎（含成本 / 不含成本 双版本，成本可配置）
# ============================================================
def run_backtest(df, position_exec, cost_on=True, commission=0.0003,
                 slippage=0.0005, ratio=1.0, min_commission=5.0,
                 init_capital=100000.0):
    """
    模拟交易回测。
    - 每日策略收益 = 执行仓位 × 当日收益率
    - 调仓日(仓位变动)扣除 佣金+滑点；佣金按"成交金额×费率"计算，并设单笔最低佣金
      (min_commission=0 即"免五"，纯按比例收取)
    - 同时返回 含成本 / 不含成本 两条净值曲线，以及各自的日净收益
    """
    close = df['close'].values.astype(float)
    n = len(close)
    pos = position_exec.values * ratio

    net_with = np.zeros(n)
    net_no = np.zeros(n)
    equity_with = np.zeros(n)
    equity_no = np.zeros(n)

    ew = 1.0
    en = 1.0
    for i in range(n):
        daily = 0.0 if i == 0 else (close[i] / close[i - 1] - 1.0)
        p = pos[i]
        strat = p * daily
        cost = 0.0
        if cost_on and i > 0:
            turnover = abs(pos[i] - pos[i - 1])
            if turnover > 0:
                port_val = ew * init_capital
                trade_val = turnover * port_val
                comm_amt = max(trade_val * commission, min_commission)
                cost = comm_amt / port_val + slippage * turnover
        nw = strat - cost
        nn = strat
        ew *= (1.0 + nw)
        en *= (1.0 + nn)
        net_with[i] = nw
        net_no[i] = nn
        equity_with[i] = ew
        equity_no[i] = en

    return equity_with, equity_no, net_with, net_no


def buy_and_hold(df):
    """买入持有基准（无成本）净值曲线。"""
    close = df['close'].values.astype(float)
    n = len(close)
    eq = np.zeros(n)
    e = 1.0
    for i in range(n):
        r = 0.0 if i == 0 else (close[i] / close[i - 1] - 1.0)
        e *= (1.0 + r)
        eq[i] = e
    return eq


# ============================================================
# 5) 量化指标（对应要求图：总收益/年化/超额/MDD/胜率/盈亏比/Sharpe + 累计回报）
# ============================================================
def compute_metrics(equity, net_ret, position_exec, ratio=1.0, rf=RF, af=ANNUAL_FACTOR):
    """计算单条净值曲线对应的全部指标。"""
    eq = np.asarray(equity, dtype=float)
    ret = np.asarray(net_ret, dtype=float)
    n = len(eq)

    total = eq[-1] / eq[0] - 1.0                       # 总收益率 / 累计回报(末值)
    years = n / af
    ann = (eq[-1] / eq[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    # 最大回撤 MDD
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    mdd = float(-dd.min())

    # 夏普比率 Sharpe
    rfd = rf / af
    ex = ret - rfd
    std = ex.std(ddof=1) if n > 1 else 0.0
    sharpe = float(ex.mean() / std * np.sqrt(af)) if std > 0 else 0.0

    # 交易回合（round-trip）统计：胜率 / 盈亏比
    pos = position_exec.values * ratio
    entries = [i for i in range(1, n) if pos[i] == ratio and pos[i - 1] == 0]
    trades = []
    for e_idx in entries:
        x = None
        for k in range(e_idx + 1, n):
            if pos[k] == 0 and pos[k - 1] == ratio:
                x = k
                break
        if x is None:
            x = n - 1  # 末日仍持仓，按市值计
        trades.append(eq[x] / eq[e_idx - 1] - 1.0)

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean([abs(t) for t in losses])) if losses else 0.0
    if avg_loss > 1e-6:
        pl = avg_win / avg_loss
    elif avg_win > 1e-6:
        pl = None  # 亏损近乎为 0，盈亏比无定义 -> 标记为 N/A
    else:
        pl = 0.0

    return {
        'total_return': float(total),
        'annual_return': float(ann),
        'mdd': float(mdd),
        'sharpe': float(sharpe),
        'win_rate': float(win_rate),
        'profit_loss_ratio': (None if pl is None else float(pl)),
        'n_trades': len(trades),
    }


# ============================================================
# 6) 可视化（matplotlib 静态图，作为 PDF 导出备份）
# ============================================================
def plot_price_ma_signals(df, ma_s, ma_l, golden, death, short, long, path):
    dates = df['trade_date']
    close = df['close']
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(dates, close, label='Close', color=COLOR_CLOSE, lw=1.2)
    ax.plot(dates, ma_s, label=f'MA{short}', color=COLOR_MA_S, lw=1.4)
    ax.plot(dates, ma_l, label=f'MA{long}', color=COLOR_MA_L, lw=1.4)

    buy_dates = dates[golden]
    buy_px = close[golden]
    sell_dates = dates[death]
    sell_px = close[death]
    ax.scatter(buy_dates, buy_px, marker='^', color=COLOR_UP, s=90,
               zorder=5, label='Buy (Golden Cross)')
    ax.scatter(sell_dates, sell_px, marker='v', color=COLOR_DOWN, s=90,
               zorder=5, label='Sell (Death Cross)')

    title_suffix = " [前复权]" if df['_use_qfq'].iloc[0] else ""
    ax.set_title(f"{df['name'].iloc[0]}  Dual MA ({short},{long})  Signals{title_suffix}", fontsize=13)
    ax.set_ylabel('Price')
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


def plot_equity(dates, eq_with, eq_no, bh, name, path):
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(dates, eq_with, label='Strategy (with cost)', color=COLOR_UP, lw=1.4)
    ax.plot(dates, eq_no, label='Strategy (no cost)', color=COLOR_MA_S, lw=1.4, ls='--')
    ax.plot(dates, bh, label='Buy & Hold', color=COLOR_MA_L, lw=1.4, ls=':')
    ax.set_title(f"{name}  Equity Curve", fontsize=13)
    ax.set_ylabel('Net Value (start=1.0)')
    ax.axhline(1.0, color='gray', lw=0.8)
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


def plot_drawdown(dates, equity, name, path):
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.fill_between(dates, dd * 100, 0, color=COLOR_DOWN, alpha=0.35)
    ax.plot(dates, dd * 100, color=COLOR_DOWN, lw=1.0)
    ax.set_title(f"{name}  Drawdown", fontsize=13)
    ax.set_ylabel('Drawdown (%)')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


# ============================================================
# HTML 看板生成（内联数据 + Chart.js，参数可交互） v2增强版
# ============================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>双均线策略回测看板</title>
<script src="chart.umd.min.js"></script>
  <style>
  :root{
    --up:#ff4d6d; --down:#25e899; --maS:#ffa940; --maL:#4d8bff;
    --bg:#f5f6f8;
    --surface:#ffffff;
    --ink:#171a21;
    --ink-2:#3a4150;
    --muted:#6c7480;
    --line:#e7e9ee;
    --accent:#3b5bdb;
    --accent-ink:#2c44b8;
    --accent-soft:rgba(59,91,219,.09);
    --shadow-sm:0 1px 2px rgba(16,24,40,.04);
    --shadow-md:0 8px 28px rgba(16,24,40,.08);
    --radius:16px;
    --radius-sm:11px;
    --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,"Liberation Mono",monospace;
    --sans:"SF Pro Display",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,sans-serif;
  }
  *{box-sizing:border-box;}
  html{-webkit-text-size-adjust:100%;}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
       font-size:14.5px;line-height:1.6;-webkit-font-smoothing:antialiased;
       background-image:radial-gradient(900px 380px at 8% -6%,rgba(59,91,219,.05),transparent 60%);}
  input,select,textarea{accent-color:var(--accent);font-family:var(--sans);}
  header{position:relative;background:#14171f;color:#fff;padding:24px 36px 20px;overflow:hidden;
         border-bottom:1px solid rgba(255,255,255,.06);}
  header::after{content:'';position:absolute;right:-100px;top:-150px;width:380px;height:380px;
       background:radial-gradient(circle,rgba(59,91,219,.28),transparent 70%);filter:blur(8px);}
  header h1{margin:0;font-size:23px;font-weight:700;letter-spacing:-.01em;position:relative;}
  header p{margin:7px 0 0;opacity:.72;font-size:13.5px;position:relative;max-width:820px;}
  .wrap{max-width:1360px;margin:0 auto;padding:20px 22px 56px;}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
        padding:20px 22px;margin:14px 0;box-shadow:var(--shadow-sm);}
  .card h2{margin:0 0 14px;font-size:17px;font-weight:680;letter-spacing:-.01em;
       display:flex;align-items:center;gap:9px;}
  .card h2::before{content:'';width:4px;height:17px;border-radius:3px;background:var(--accent);}
  .card h3{font-size:14px;color:var(--ink-2);margin:14px 0 5px;font-weight:640;}
  .card p,.card li{color:var(--ink-2);}
  .card ul{margin:0;padding-left:20px;}
  .note{font-size:13px;color:var(--muted);background:var(--accent-soft);
        border-left:3px solid var(--accent);padding:9px 13px;border-radius:8px;margin:10px 0;}
  /* 参数区：指标条 + 紧凑控件网格 */
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px;}
  .metric{background:#fbfcfd;border:1px solid var(--line);border-radius:12px;padding:11px 13px;
       transition:transform .18s,box-shadow .18s,border-color .18s;}
  .metric:hover{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:#dde1e8;}
  .metric .k{font-size:11.5px;color:var(--muted);font-weight:560;}
  .metric .v{font-size:20px;font-weight:700;margin-top:5px;font-family:var(--mono);letter-spacing:-.02em;}
  .metric .sub{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.4;}
  .controls-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(188px,1fr));
       gap:13px 18px;align-items:end;}
  .ctrl{display:flex;flex-direction:column;gap:5px;font-size:13px;color:var(--ink-2);font-weight:560;}
  .ctrl-row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;}
  .ctrl input,.ctrl select{padding:8px 10px;border:1px solid var(--line);border-radius:9px;
       font-size:13.5px;color:var(--ink);min-width:0;width:100%;background:#fff;transition:.15s;}
  .ctrl input:focus,.ctrl select:focus{outline:none;border-color:var(--accent);
       box-shadow:0 0 0 3px var(--accent-soft);}
  .btn{border:1px solid var(--line);background:#fff;border-radius:9px;padding:8px 15px;
       cursor:pointer;font-size:13px;font-weight:560;color:var(--ink-2);transition:.15s;}
  .btn:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft);}
  .btn:active{transform:translateY(1px);}
  .btn.active{background:var(--accent);color:#fff;border-color:var(--accent);}
  .btn.active:hover{background:var(--accent-ink);}
  .btn-reset{background:var(--accent-soft);color:var(--accent-ink);font-weight:650;border-color:transparent;}
  .btn-reset:hover{background:var(--accent);color:#fff;}
  .toggle-wrap{display:flex;align-items:center;gap:9px;cursor:pointer;height:38px;}
  .toggle{position:relative;width:44px;height:24px;flex-shrink:0;}
  .toggle input{opacity:0;width:0;height:0;}
  .toggle .slider{position:absolute;inset:0;background:#cdd2da;border-radius:24px;transition:.2s;}
  .toggle .slider::before{content:'';position:absolute;height:18px;width:18px;left:3px;bottom:3px;
      background:#fff;border-radius:50%;transition:.2s;box-shadow:0 1px 2px rgba(0,0,0,.2);}
  .toggle input:checked+.slider{background:var(--accent);}
  .toggle input:checked+.slider::before{transform:translateX(20px);}
  .charts canvas{max-height:400px;}
  table{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px;
       border:1px solid var(--line);border-radius:10px;overflow:hidden;}
  th,td{padding:8px 11px;text-align:center;border-bottom:1px solid var(--line);}
  th{background:#f3f5f9;color:var(--ink-2);font-weight:620;}
  tbody tr:last-child td{border-bottom:none;}
  tbody tr:hover{background:#fafbfc;}
  .pos{color:var(--up);} .neg{color:var(--down);}
  pre{background:#0f172a;color:#e2e8f0;padding:14px 16px;border-radius:10px;overflow:auto;
      font-size:12.5px;line-height:1.6;font-family:var(--mono);}
  .print-btn{position:fixed;right:22px;bottom:22px;background:var(--accent);color:#fff;border:none;
        border-radius:28px;padding:12px 20px;font-size:13.5px;font-weight:600;cursor:pointer;
        box-shadow:0 8px 22px rgba(59,91,219,.32);z-index:99;transition:.15s;}
  .print-btn:hover{background:var(--accent-ink);transform:translateY(-1px);}
  .section-tag{display:inline-block;background:var(--accent);color:#fff;font-size:11px;font-weight:600;
      padding:3px 9px;border-radius:999px;margin-left:9px;vertical-align:middle;}
  @keyframes rise{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:none;}}
  .card{animation:rise .5s cubic-bezier(.22,.61,.36,1) both;}
  .wrap>.card:nth-child(1){animation-delay:.03s;}
  .wrap>.card:nth-child(2){animation-delay:.08s;}
  .wrap>.card:nth-child(3){animation-delay:.13s;}
  .wrap>.card:nth-child(4){animation-delay:.18s;}
  .wrap>.card:nth-child(5){animation-delay:.23s;}
  .wrap>.card:nth-child(6){animation-delay:.28s;}
  .wrap>.card:nth-child(7){animation-delay:.33s;}
  @media (max-width:760px){
    .metrics{grid-template-columns:repeat(2,1fr);}
    .controls-grid{grid-template-columns:1fr 1fr;}
  }
  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;}}
  @media print{
    body{background:#fff;background-image:none;}
    .card{box-shadow:none;break-inside:avoid;animation:none;}
    .print-btn,.controls-grid{display:none!important;}
    .metrics{margin-bottom:8px;}
  }
</style>
</head>
<body>
<header>
  <h1>双均线策略（Dual Moving Average）回测看板 <span class="section-tag">v2 增强</span></h1>
  <p>金叉买入 · 死叉卖出 · 含/不含交易成本对比 · 可交互调参 · 前复权支持 · 适用于量化作业 HW3</p>
</header>

<div class="wrap">

  <!-- 概念讲解 -->
  <div class="card">
    <h2>一、核心概念讲解</h2>
    <h3>1. 双均线策略</h3>
    <p>同时计算一条<strong>短期均线</strong>（如 MA5）和一条<strong>长期均线</strong>（如 MA15）。
       短期均线对价格更敏感、长期均线更平滑。两者相对位置反映趋势强弱：短线上穿长线视为趋势转强，
       短线下穿长线视为趋势转弱。</p>
    <h3>2. 金叉（Golden Cross）与死叉（Death Cross）</h3>
    <ul>
      <li><span class="pos">金叉</span>：短期均线由下向上穿越长期均线（diff 由负转正）→ 看多信号，<strong>买入</strong>。</li>
      <li><span class="neg">死叉</span>：短期均线由上向下穿越长期均线（diff 由正转负）→ 看空信号，<strong>卖出</strong>。</li>
    </ul>
    <div class="note">防未来函数：信号在<strong>当日收盘</strong>判定，实际<strong>次日开盘</strong>成交（仓位整体后移 1 日），避免用到当日收盘之后的信息。</div>

    <h3>3. 为什么需要复权（Price Adjustment）？</h3>
    <p>A股存在<strong>除权除息</strong>（分红、送股、配股等），会导致股价出现非自然的"跳空缺口"。
       例如某股票每股分红 1 元，除息日开盘价会直接下跌约 1 元——这不是真实的市场波动，
       但会让均线系统产生<strong>假的金叉/死叉信号</strong>。</p>
    <ul>
      <li><strong>前复权（Forward-Adjusted）</strong>：将历史价格按最新复权因子调整，保持最新价格不变、
          消除历史缺口。适合回测和趋势分析（本看板推荐使用）。</li>
      <li><strong>后复权（Backward-Adjusted）</strong>：保持最早价格不变、后续价格上调。适合计算长期累计收益。</li>
      <li><strong>不复权</strong>：原始挂牌价。适合查看实际成交价格。</li>
    </ul>
    <div class="note">本看板的"复权"开关可实时切换原始价与前复权价进行对比观察。</div>

    <h3>4. 量化效果基础指标</h3>
    <ul>
      <li><strong>累计回报 Cumulative Return</strong>：策略净值随时间的累计增长（净值曲线），末值即总收益。</li>
      <li><strong>最大回撤 MDD（Max Drawdown）</strong>：净值从历史高点到后续最低点的最大跌幅，衡量最坏亏损幅度与回撤风险。</li>
      <li><strong>夏普比率 Sharpe Ratio</strong>：单位总风险（波动率）带来的超额收益 = 日均超额收益 / 日收益标准差 × √252，越高越好。</li>
      <li>另含：总收益率、年化收益、超额收益（相对买入持有基准）、胜率、盈亏比（详见看板指标区）。</li>
    </ul>
  </div>

  <!-- 交互控件 -->
  <div class="card">
    <h2>二、参数交互</h2>
    <div class="metrics" id="metrics"></div>
    <div class="note" id="stocknote"></div>
    <div class="controls-grid">
      <div class="ctrl">标的选择
        <select id="stock">
          <option value="maotai">贵州茅台 600519.SH</option>
          <option value="pingan" selected>平安银行 000001.SZ</option>
          <option value="sany">三一重工 600031.SH</option>
        </select>
      </div>
      <div class="ctrl">起始日期<input id="startDate" type="date"></div>
      <div class="ctrl">结束日期<input id="endDate" type="date"></div>
      <div class="ctrl">短线周期 SMA
        <input id="short" type="range" min="2" max="60" value="5" style="width:100%">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#9aa1ad;"><span>2</span><span id="shortVal">5</span><span>60</span></div>
      </div>
      <div class="ctrl">长线周期 SMA
        <input id="long" type="range" min="3" max="120" value="15" style="width:100%">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#9aa1ad;"><span>3</span><span id="longVal">15</span><span>120</span></div>
      </div>
      <label class="toggle-wrap ctrl"><span style="font-size:13px;">计入交易成本</span>
        <div class="toggle"><input type="checkbox" id="cost" checked><span class="slider"></span></div>
      </label>
      <div class="ctrl">佣金率(单边)<input id="commission" type="number" value="0.0003" step="0.0001" min="0" style="width:100%">
        <div class="ctrl-row" style="margin-top:2px;">
          <button class="btn" onclick="setPresetComm(0.0001)">万一</button>
          <button class="btn active" onclick="setPresetComm(0.0003)">万三</button>
        </div>
      </div>
      <div class="ctrl">滑点<input id="slippage" type="number" value="0.0005" step="0.0001" style="width:100%"></div>
      <div class="ctrl">最低佣金(元/笔)<input id="minComm" type="number" value="5" step="1" min="0" style="width:100%"></div>
      <label class="toggle-wrap ctrl"><span style="font-size:13px;">使用前复权价</span>
        <div class="toggle"><input type="checkbox" id="useQfq"><span class="slider"></span></div>
      </label>
      <div class="ctrl">初始资金（元）<input id="initCapital" type="number" value="100000" step="10000" style="width:100%"></div>
      <div class="ctrl" style="justify-content:flex-end;">
        <button class="btn btn-reset" onclick="resetParams()" style="width:100%;">重置默认参数</button>
      </div>
    </div>
  </div>

  <!-- 图表1：价格+均线+信号 -->
  <div class="card">
    <h2>三、价格 + 均线 + 买卖信号</h2>
    <div class="charts"><canvas id="chartPrice"></canvas></div>
  </div>

  <!-- 图表2：净值对比 -->
  <div class="card">
    <h2>四、策略净值 vs 买入持有基准</h2>
    <div class="charts"><canvas id="chartEquity"></canvas></div>
  </div>

  <!-- 图表3：回撤 -->
  <div class="card">
    <h2>五、回撤曲线</h2>
    <div class="charts"><canvas id="chartDD"></canvas></div>
  </div>

  <!-- 实验对比 -->
  <div class="card">
    <h2>六、不同股票 x 均线周期 实验对比</h2>
    <p class="note">佣金率与滑点均可自由设置（默认万三 0.0003、滑点 0.0005，全仓）；含成本版指标。可点击"万一/万三"快捷填入，或手动输入任意费率；"最低佣金(元/笔)"默认 5 元（不免五），设为 0 即"免五"，纯按比例收取。观察收益/回撤随成本变化。</p>
    <div id="expTable" style="overflow-x:auto;"></div>
  </div>

  <!-- 应用心得 -->
  <div class="card">
    <h2>七、应用心得与适用场景总结</h2>
    <ul>
      <li><strong>趋势市有效、震荡市失效</strong>：双均线是趋势跟踪策略，在单边上涨/下跌行情中能吃到主升浪；在横盘震荡中会频繁出现"假金叉/假死叉"，反复来回止损，磨损成本很高。</li>
      <li><strong>周期越长越平滑、越滞后</strong>：长均线(如 MA60)过滤噪声但信号滞后，容易错过头部/底部；短均线(如 MA5)灵敏但假信号多。需结合标的性质权衡。</li>
      <li><strong>交易成本不可忽视</strong>：对比"含成本"与"不含成本"两版净值可见，频繁交易下佣金+滑点会显著吞噬利润；实盘必须计入成本评价。注意券商"单笔最低佣金 5 元"(不免五)对小额交易影响很大——本看板"最低佣金"设为 0 即为"免五"，可对比观察小资金频繁调仓时被最低佣金拖累的程度。</li>
      <li><strong>复权的重要性</strong>：使用未复权的原始价格进行回测，除权除息日的价格跳空会产生大量假信号。建议始终使用前复权价格进行技术分析和回测。</li>
      <li><strong>改进方向</strong>：加入成交量/波动率过滤假信号、用 ATR 做止损、或结合更长周期均线确认大趋势（如双均线 + 长期趋势过滤）。</li>
    </ul>
  </div>

</div>
<button class="print-btn" onclick="window.print()">打印 / 导出 PDF</button>

<script>
const STOCKS_RAW = __STOCKS_RAW__;
const STOCKS_QFQ = __STOCKS_QFQ__;
const EXPERIMENT = __EXP__;

let chartPrice, chartEquity, chartDD;

// 预设按钮：仅把佣金率填入输入框（仍可手动改成任意值）
function setPresetComm(val){
  document.getElementById('commission').value = val;
  syncCommPreset();
  render();
}
// 手动输入佣金率时，高亮匹配的预设（若都不匹配则取消高亮）
function syncCommPreset(){
  const v = parseFloat(document.getElementById('commission').value);
  const map = {'0.0001':'万一', '0.0003':'万三'};
  document.querySelectorAll('[onclick^="setPresetComm"]').forEach(function(b){
    const bval = parseFloat(b.getAttribute('onclick').match(/[\d.]+/)[0]);
    b.classList.toggle('active', Math.abs(bval - v) < 1e-9);
  });
}
document.getElementById('commission').addEventListener('input', function(){
  syncCommPreset();
  render();
});

// 同步滑块数值显示
document.getElementById('short').addEventListener('input', function(){
  document.getElementById('shortVal').textContent = this.value;
  render();
});
document.getElementById('long').addEventListener('input', function(){
  document.getElementById('longVal').textContent = this.value;
  render();
});

function resetParams(){
  document.getElementById('stock').value = 'pingan';
  document.getElementById('short').value = 5;
  document.getElementById('long').value = 15;
  document.getElementById('shortVal').textContent = '5';
  document.getElementById('longVal').textContent = '15';
  document.getElementById('cost').checked = true;
  document.getElementById('commission').value = '0.0003';
  syncCommPreset();
  document.getElementById('slippage').value = '0.0005';
  document.getElementById('minComm').value = '5';
  document.getElementById('useQfq').checked = false;
  document.getElementById('initCapital').value = '100000';
  // 重置日期范围为全量
  const key = document.getElementById('stock').value;
  const useQ = document.getElementById('useQfq').checked;
  const s = getStockData(key, useQ);
  if(s && s.dates.length > 0){
    document.getElementById('startDate').value = s.dates[0];
    document.getElementById('endDate').value = s.dates[s.dates.length-1];
  }
  render();
}

function getStockData(key, useQfq){
  if(useQfq && STOCKS_QFQ[key]) return STOCKS_QFQ[key];
  return STOCKS_RAW[key] || null;
}

function sliceData(stock, startDate, endDate){
  if(!stock || !stock.dates.length) return null;
  let si = 0, ei = stock.dates.length - 1;
  if(startDate){ si = stock.dates.indexOf(startDate); if(si === -1) si = 0; }
  if(endDate){ ei = stock.dates.indexOf(endDate); if(ei === -1) ei = stock.dates.length - 1; }
  if(si >= ei) { si = 0; ei = stock.dates.length - 1; }
  const out = {name: stock.name, code: stock.code, note: stock.note};
  out.dates = stock.dates.slice(si, ei+1);
  out.close = stock.close.slice(si, ei+1);
  out.open = stock.open ? stock.open.slice(si, ei+1) : [];
  return out;
}

function rollingMean(arr, p){
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for(let i=0;i<arr.length;i++){
    sum += arr[i];
    if(i>=p) sum -= arr[i-p];
    if(i>=p-1) out[i] = sum/p;
  }
  return out;
}

function computeSignals(close, maS, maL){
  const n = close.length;
  const golden = new Array(n).fill(false);
  const death = new Array(n).fill(false);
  const pos = new Array(n).fill(0);
  let cur = 0;
  for(let i=0;i<n;i++){
    if(i>=1 && maS[i]!=null && maL[i]!=null && maS[i-1]!=null && maL[i-1]!=null){
      const d = maS[i]-maL[i], dp = maS[i-1]-maL[i-1];
      if(dp<=0 && d>0 && cur===0){ golden[i]=true; cur=1; }
      else if(dp>=0 && d<0 && cur===1){ death[i]=true; cur=0; }
    }
    pos[i]=cur;
  }
  const posExec = new Array(n).fill(0);
  for(let i=1;i<n;i++) posExec[i]=pos[i-1];
  return {golden, death, pos, posExec};
}

function backtest(close, posExec, costOn, comm, slip, ratio, minComm, initCap){
  minComm = (minComm===undefined)?5 : minComm;
  initCap = (initCap===undefined)?100000 : initCap;
  const n = close.length;
  const dailyRet = new Array(n).fill(0);
  for(let i=1;i<n;i++) dailyRet[i]=close[i]/close[i-1]-1;
  const eqW=new Array(n), eqN=new Array(n), netW=new Array(n), netN=new Array(n);
  let ew=1, en=1;
  for(let i=0;i<n;i++){
    const p = posExec[i]*ratio;
    const sr = (i===0)?0 : p*dailyRet[i];
    let cost=0;
    if(i>0 && costOn){
      const turnover = Math.abs(posExec[i]*ratio - posExec[i-1]*ratio);
      if(turnover>0){
        const portVal = ew * initCap;          // 上一交易日组合市值(元)
        const tradeVal = turnover * portVal;    // 本笔成交金额(元)
        const commAmt = Math.max(tradeVal*comm, minComm);  // 单笔最低佣金(0=免五)
        cost = commAmt/portVal + slip*turnover; // 折算为占净值比例
      }
    }
    const nw = sr - cost, nn = sr;
    ew*=(1+nw); en*=(1+nn);
    eqW[i]=ew; eqN[i]=en; netW[i]=nw; netN[i]=nn;
  }
  return {eqW, eqN, netW, netN};
}

function bhEquity(close){
  const n=close.length; const eq=new Array(n); let e=1;
  for(let i=0;i<n;i++){ const r=(i===0)?0:close[i]/close[i-1]-1; e*=(1+r); eq[i]=e; }
  return eq;
}

function metrics(equity, netRet, posExec, ratio, af){
  const n=equity.length;
  const total=equity[n-1]/equity[0]-1;
  const years=n/af;
  const ann=Math.pow(equity[n-1]/equity[0], 1/years)-1;
  let peak=equity[0]; const dd=new Array(n); let mdd=0;
  for(let i=0;i<n;i++){ if(equity[i]>peak)peak=equity[i]; dd[i]=equity[i]/peak-1; if(-dd[i]>mdd)mdd=-dd[i]; }
  let mean=0; for(let i=0;i<n;i++) mean+=netRet[i]; mean/=n;
  let v=0; for(let i=0;i<n;i++){const d=netRet[i]-mean; v+=d*d;} v/=(n-1);
  const std=Math.sqrt(v); const sharpe= std>0? mean/std*Math.sqrt(af):0;
  const pos=posExec.map(v=>v*ratio);
  const entries=[]; for(let i=1;i<n;i++) if(pos[i]===ratio && pos[i-1]===0) entries.push(i);
  const trades=[];
  for(const e of entries){ let x=null; for(let k=e+1;k<n;k++){ if(pos[k]===0 && pos[k-1]===ratio){x=k;break;} } if(x===null)x=n-1; trades.push(equity[x]/equity[e-1]-1); }
  let wins=0; for(const t of trades) if(t>0)wins++;
  const winRate= trades.length? wins/trades.length:0;
  let aw=0,wl=0,wc=0,lc=0; for(const t of trades){ if(t>0){aw+=t;wc++;} else {wl+=Math.abs(t);lc++;} }
  const avgWin=wc?aw/wc:0, avgLoss=lc?wl/lc:0;
  const pl= avgLoss>0? avgWin/avgLoss : (avgWin>0? Infinity:0);
  return {total, ann, mdd, sharpe, winRate, pl, nTrades:trades.length, dd};
}

function fmtPct(x){ return (x*100).toFixed(2)+'%'; }
function fmtNum(x){ return x==null||x===Infinity? '—' : x.toFixed(2); }
function cls(x){ return x>=0? 'pos':'neg'; }

function render(){
  const key = document.getElementById('stock').value;
  const useQfq = document.getElementById('useQfq').checked;
  const sFull = getStockData(key, useQfq);
  if(!sFull){ document.getElementById('metrics').innerHTML='<p>无数据</p>'; return; }

  const short = parseInt(document.getElementById('short').value)||5;
  const long = parseInt(document.getElementById('long').value)||15;
  const costOn = document.getElementById('cost').checked;
  const comm = parseFloat(document.getElementById('commission').value)||0;
  const slip = parseFloat(document.getElementById('slippage').value)||0;
  const minComm = parseFloat(document.getElementById('minComm').value);  // NaN->5(不免五)
  const minCommV = isNaN(minComm) ? 5 : minComm;
  const capital = parseFloat(document.getElementById('initCapital').value)||100000;
  const ratio = 1.0;
  const startDate = document.getElementById('startDate').value;
  const endDate = document.getElementById('endDate').value;

  // 初始化日期范围（首次加载时）
  if(!startDate && sFull.dates.length > 0){
    document.getElementById('startDate').value = sFull.dates[0];
    document.getElementById('endDate').value = sFull.dates[sFull.dates.length-1];
  }

  const s = sliceData(sFull, startDate || sFull.dates[0], endDate || sFull.dates[sFull.dates.length-1]);

  // 更新复权提示
  const qfqTag = useQfq ? ' [前复权]' : '';
  const qfqWarn = (useQfq && !STOCKS_QFQ[key]) ? ' （该股票暂无复权数据，仍用原始价）' : '';
  document.getElementById('stocknote').textContent =
    s.name + qfqTag + ' (' + s.code + ') ｜ 共 ' + s.dates.length + ' 个交易日' +
    (startDate ? ' ｜ ' + startDate + ' ~ ' + endDate : '') +
    ' ｜ SMA('+short+','+long+')' + qfqWarn;

  const maS = rollingMean(s.close, short);
  const maL = rollingMean(s.close, long);
  const sig = computeSignals(s.close, maS, maL);
  const bt = backtest(s.close, sig.posExec, costOn, comm, slip, ratio, minCommV, capital);
  const bh = bhEquity(s.close);

  const mW = metrics(bt.eqW, bt.netW, sig.posExec, ratio, 252);
  const mN = metrics(bt.eqN, bt.netN, sig.posExec, ratio, 252);
  const bhTotal = bh[bh.length-1]/bh[0]-1;
  const excess = mW.total - bhTotal;

  // ---- 图表1：价格 + 均线 + 信号 ----
  const buyData = s.close.map((v,i)=> sig.golden[i]? v : null);
  const sellData = s.close.map((v,i)=> sig.death[i]? v : null);
  const pdata = {
    labels: s.dates,
    datasets: [
      {label:'Close', data:s.close, borderColor:'#2b2b2b', borderWidth:1.2, pointRadius:0},
      {label:'MA'+short, data:maS, borderColor:'#ffa940', borderWidth:1.4, pointRadius:0},
      {label:'MA'+long, data:maL, borderColor:'#4d8bff', borderWidth:1.4, pointRadius:0},
      {label:'Buy', data:buyData, showLine:false, pointStyle:'triangle',
       pointRadius:7, pointBackgroundColor:'#ff4d6d', borderColor:'#ff4d6d'},
      {label:'Sell', data:sellData, showLine:false, pointStyle:'triangle', pointRotation:180,
       pointRadius:7, pointBackgroundColor:'#25e899', borderColor:'#25e899'},
    ]
  };
  if(chartPrice) chartPrice.destroy();
  chartPrice = new Chart(document.getElementById('chartPrice'), {type:'line', data:pdata,
    options:{responsive:true, interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{maxTicksLimit:15}}}, plugins:{legend:{position:'top'}}}});

  // ---- 图表2：净值 ----
  const edata = {
    labels: s.dates,
    datasets: [
      {label:'策略净值(含成本)', data:bt.eqW, borderColor:'#ff4d6d', borderWidth:1.4, pointRadius:0},
      {label:'策略净值(不含成本)', data:bt.eqN, borderColor:'#ffa940', borderWidth:1.4, borderDash:[6,4], pointRadius:0},
      {label:'买入持有基准', data:bh, borderColor:'#4d8bff', borderWidth:1.4, borderDash:[2,3], pointRadius:0},
    ]
  };
  if(chartEquity) chartEquity.destroy();
  chartEquity = new Chart(document.getElementById('chartEquity'), {type:'line', data:edata,
    options:{responsive:true, interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{maxTicksLimit:15}}}, plugins:{legend:{position:'top'}}}});

  // ---- 图表3：回撤 ----
  const ddPct = mW.dd.map(v=> v*100);
  const ddata = {labels:s.dates, datasets:[
    {label:'Drawdown %', data:ddPct, borderColor:'#25e899', backgroundColor:'rgba(37,232,153,.25)',
     fill:true, pointRadius:0, borderWidth:1}]};
  if(chartDD) chartDD.destroy();
  chartDD = new Chart(document.getElementById('chartDD'), {type:'line', data:ddata,
    options:{responsive:true, scales:{x:{ticks:{maxTicksLimit:15}}}, plugins:{legend:{display:false}}}});

  // ---- 指标卡 ----
  const cards = [
    ['年化收益率', fmtPct(mW.ann), '基准 '+fmtPct(Math.pow(1+bhTotal,252/s.dates.length)-1)],
    ['夏普比率', fmtNum(mW.sharpe), costOn ? '含成本' : '不计成本'],
    ['最大回撤', fmtPct(mW.mdd), mW.mdd<=0?'':' '+((s.dates[mW.dd.indexOf(-mW.mdd)]||'')+' 起')],
    ['胜率', fmtPct(mW.winRate), mW.nTrades+'笔交易 · 盈亏比 '+fmtNum(mW.pl)],
    ['累计收益(含成本)', fmtPct(mW.total), '≈ ¥'+Math.round(capital*mW.total).toLocaleString()],
    ['累计收益(无成本)', fmtPct(mN.total), '≈ ¥'+Math.round(capital*mN.total).toLocaleString()],
    ['超额收益(策略-B&H)', fmtPct(excess), excess>=0?'跑赢基准':'跑输基准'],
    ['买入持有收益', fmtPct(bhTotal), '≈ ¥'+Math.round(capital*bhTotal).toLocaleString()],
  ];
  document.getElementById('metrics').innerHTML = cards.map(c=>
    '<div class="metric"><div class="k">'+c[0]+'</div><div class="v '+cls(parseFloat(c[1]))+'">'+c[1]+
    '</div><div class="sub">'+c[2]+'</div></div>').join('');

  // ---- 实验对比表 ----
  buildExpTable();
}

function buildExpTable(){
  const exp = EXPERIMENT;
  let html = '<table><thead><tr><th>股票</th><th>周期(短,长)</th><th>总收益(含成本)</th>'+
    '<th>总收益(无成本)</th><th>最大回撤</th><th>夏普</th><th>胜率</th><th>盈亏比</th><th>交易次数</th></tr></thead><tbody>';
  for(const row of exp.rows){
    html += '<tr><td>'+row.stock+'</td><td>('+row.short+','+row.long+')</td>'+
      '<td class="'+cls(row.total_with)+'">'+fmtPct(row.total_with)+'</td>'+
      '<td class="'+cls(row.total_without)+'">'+fmtPct(row.total_without)+'</td>'+
      '<td class="neg">'+fmtPct(row.mdd_with)+'</td>'+
      '<td>'+fmtNum(row.sharpe_with)+'</td>'+
      '<td>'+fmtPct(row.win_rate)+'</td>'+
      '<td>'+fmtNum(row.pl)+'</td>'+
      '<td>'+row.n_trades+'</td></tr>';
  }
  html += '</tbody></table>';
  document.getElementById('expTable').innerHTML = html;
}

// 绑定控件
['stock','cost','slippage','initCapital','minComm','startDate','endDate','useQfq'].forEach(id=>{
  const el = document.getElementById(id);
  el.addEventListener('input', render);
  el.addEventListener('change', render);
});
// 注意：short/long 已通过 input 事件绑定（滑块）

syncCommPreset();  // 初始高亮与输入框匹配的预设
render();
</script>
</body>
</html>
"""


def build_html(stocks_raw_payload, stocks_qfq_payload, experiment_payload):
    """把股票原始数据、前复权数据与实验摘要嵌入模板，生成看板。"""
    html = HTML_TEMPLATE
    html = html.replace('__STOCKS_RAW__', json.dumps(stocks_raw_payload, ensure_ascii=False))
    html = html.replace('__STOCKS_QFQ__', json.dumps(stocks_qfq_payload, ensure_ascii=False))
    html = html.replace('__EXP__', json.dumps(experiment_payload, ensure_ascii=False))
    out = os.path.join(BASE_DIR, '双均线策略看板.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    return out


# ============================================================
# 主流程
# ============================================================
def main():
    print('=' * 60)
    print('HW3 双均线策略回测 v2（增强：复权+长数据+日期范围）')
    print('=' * 60)

    # 加载全部股票（同时加载原始版和前复权版）
    stocks_raw = {}   # key -> DataFrame (原始价)
    stocks_qfq = {}   # key -> DataFrame (前复权价, 若有)
    for key, (fname, code, name, note, qfq_fname) in STOCK_CONFIG.items():
        df_raw = load_stock(fname, code, name, note, qfq_fname, use_qfq=False)
        stocks_raw[key] = df_raw
        print(f'  [原始] {name}({code}): {len(df_raw)} 条, '
              f'{df_raw["trade_date"].min().date()} ~ {df_raw["trade_date"].max().date()}')

        if qfq_fname:
            df_qfq = load_stock(fname, code, name, note, qfq_fname, use_qfq=True)
            stocks_qfq[key] = df_qfq
            print(f'  [前复权] {name}({code}): {len(df_qfq)} 条')
        else:
            print(f'  [前复权] {name}: 暂无复权数据（adj_factor 接口频率限制）')

    # ---- 默认参数 (5,15) 的图表与指标（使用原始数据以兼容原逻辑）----
    SHORT, LONG = DEFAULT_SHORT, DEFAULT_LONG
    print(f'\n计算默认参数 ({SHORT},{LONG}) 的图表与指标...')
    metrics_all = {}
    for key, df in stocks_raw.items():
        ma_s, ma_l, golden, death, position, pos_exec = compute_ma_and_signals(df, SHORT, LONG)
        eq_w, eq_n, net_w, net_n = run_backtest(df, pos_exec, cost_on=True,
                                                 commission=0.0003, slippage=0.0005)
        bh = buy_and_hold(df)
        m_w = compute_metrics(eq_w, net_w, pos_exec)
        m_n = compute_metrics(eq_n, net_n, pos_exec)
        bh_total = bh[-1] / bh[0] - 1
        metrics_all[key] = {'with': m_w, 'without': m_n, 'bh': bh_total}

        dates = df['trade_date']
        plot_price_ma_signals(df, ma_s, ma_l, golden, death, SHORT, LONG,
                              os.path.join(DATA_DIR, f'{key}_price_signals.png'))
        plot_equity(dates, eq_w, eq_n, bh, df['name'].iloc[0],
                    os.path.join(DATA_DIR, f'{key}_equity.png'))
        plot_drawdown(dates, eq_w, df['name'].iloc[0],
                      os.path.join(DATA_DIR, f'{key}_drawdown.png'))

        print(f'  {df["name"].iloc[0]}: 总收益(含成本)={m_w["total_return"]*100:.2f}%  '
              f'MDD={m_w["mdd"]*100:.2f}%  Sharpe={m_w["sharpe"]:.2f}  '
              f'胜率={m_w["win_rate"]*100:.1f}%  交易={m_w["n_trades"]}次')

    # 默认参数指标 JSON
    with open(os.path.join(DATA_DIR, 'backtest_metrics.json'), 'w', encoding='utf-8') as f:
        json.dump(metrics_all, f, ensure_ascii=False, indent=2)

    # ---- 实验扫描：股票 × 均线周期（使用原始数据）----
    print('\n扫描 股票 × 均线周期 组合...')
    exp_rows = []
    for key, df in stocks_raw.items():
        for (sh, lo) in PERIOD_SWEEP:
            _, _, _, _, position, pos_exec = compute_ma_and_signals(df, sh, lo)
            eq_w, eq_n, net_w, net_n = run_backtest(df, pos_exec, cost_on=True,
                                                     commission=0.0003, slippage=0.0005)
            m_w = compute_metrics(eq_w, net_w, pos_exec)
            m_n = compute_metrics(eq_n, net_n, pos_exec)
            exp_rows.append({
                'stock': df['name'].iloc[0], 'code': df['code'].iloc[0],
                'short': sh, 'long': lo,
                'total_with': m_w['total_return'], 'total_without': m_n['total_return'],
                'mdd_with': m_w['mdd'], 'mdd_without': m_n['mdd'],
                'sharpe_with': m_w['sharpe'], 'sharpe_without': m_n['sharpe'],
                'win_rate': m_w['win_rate'], 'pl': m_w['profit_loss_ratio'],
                'n_trades': m_w['n_trades'],
            })
    experiment = {'params': [{'short': sh, 'long': lo} for (sh, lo) in PERIOD_SWEEP],
                  'commission': 0.0003, 'slippage': 0.0005, 'rows': exp_rows}
    with open(os.path.join(DATA_DIR, 'experiment_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(experiment, f, ensure_ascii=False, indent=2)

    # ---- 看板数据（嵌入原始序列 + 前复权序列）----
    def _payload_from_df(df):
        return {
            'name': df['name'].iloc[0],
            'code': df['code'].iloc[0],
            'note': df['note'].iloc[0],
            'dates': df['trade_date'].dt.strftime('%Y-%m-%d').tolist(),
            'close': [round(float(v), 4) for v in df['close']],
            'open': [round(float(v), 4) for v in df['open']],
        }

    stocks_raw_payload = {}
    stocks_qfq_payload = {}
    for key in STOCK_CONFIG:
        stocks_raw_payload[key] = _payload_from_df(stocks_raw[key])
        if key in stocks_qfq:
            stocks_qfq_payload[key] = _payload_from_df(stocks_qfq[key])

    out_html = build_html(stocks_raw_payload, stocks_qfq_payload, experiment)
    print(f'\n看板已生成: {out_html}')
    print(f'图表与 JSON 已写入: {DATA_DIR}')
    print('\n' + '=' * 60)
    print('完成！用浏览器打开「双均线策略看板.html」即可交互查看，')
    print('点击右下角按钮可打印 / 导出 PDF。')
    print('v2 新增：前复权支持(平安)、日期范围选择、重置按钮、更长数据')
    print('=' * 60)


if __name__ == '__main__':
    main()
