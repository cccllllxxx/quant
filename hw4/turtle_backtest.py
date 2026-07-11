# -*- coding: utf-8 -*-
"""
HW4 海龟交易策略（Turtle Trading）回测与可视化看板生成脚本
==========================================================
任务要求：
  1) 加载已存储的股价数据（前复权，验证复权正确性）
  2) 计算高低价格通道（系统1: 20日入场/10日出场；系统2: 55日入场/20日出场）
  3) 计算 ATR（平均真实波幅，经典 N=20）
  4) 计算买入/卖出交易信号（通道突破 + ATR 止损状态机）
  5) 绘制可视化图形（价格、高低通道、买卖信号、止损标记、ATR、资金曲线、回撤）
  6) 模拟交易回测，计算量化指标；参数敏感性（股票×系统×止损倍数）实验

输出：
  - data/*.png            matplotlib 静态图表（供 PDF 使用）
  - data/backtest_metrics.json    默认参数(S1/S2 × 2N)下的指标
  - data/experiment_summary.json  参数敏感性全网格 + 通道周期扫描
  - 海龟策略看板.html      交互式看板（核心交付物）

约定：
  - 无风险利率 rf=0；年化因子 252 交易日
  - 成交于信号次日开盘（position 整体后移 1 日），严格防未来函数
  - 佣金默认万三(0.0003)，滑点默认万五(0.0005)，卖出印花税 0.05%(0.0005)，单笔最低佣金 5 元
  - A股配色：涨红(#ff4d6d) 跌绿(#25e899)；买入信号红▲、卖出信号绿▼、止损×橙
  - 仅做多（A股散户无法便捷做空），满仓 ratio=1（与 HW3 指标口径可比）
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
            r'C:/Windows/Fonts/NotoSansSC-VF.ttf',
            r'C:/Windows/Fonts/simsun.ttc']:
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
COLOR_UPPER = '#ff4d6d'   # 入场通道上轨 红
COLOR_LOWER = '#25e899'   # 离场通道下轨 绿
COLOR_STOP = '#ffa940'    # 止损标记 橙
COLOR_ATR = '#7c5cff'     # ATR 紫

ANNUAL_FACTOR = 252       # 每年交易日数
RF = 0.0                  # 无风险利率

# 股票配置：(raw_csv, code, name, note, qfq_csv)
STOCK_CONFIG = {
    "maotai": ("maotai_daily.csv", "600519.SH", "贵州茅台",
               "Tushare日线, 2023-01~2026-07, 约844个交易日",
               "maotai_daily_qfq.csv"),
    "pingan": ("pingan_daily.csv", "000001.SZ", "平安银行",
               "Tushare日线, 2022-01~2026-07, 约1086个交易日",
               "pingan_daily_qfq.csv"),
    "sany":   ("sany_daily.csv", "600031.SH", "三一重工",
               "Tushare日线, 2022-01~2026-07, 约1086个交易日",
               "sany_daily_qfq.csv"),
}

# 海龟两套系统（用户要求两者都做并对比）
SYSTEMS = {
    "S1": {"entry": 20, "exit": 10, "name": "系统1(短期)"},   # 20日突破买入 / 10日破低卖出
    "S2": {"entry": 55, "exit": 20, "name": "系统2(长期)"},   # 55日突破买入 / 20日破低卖出
}
ATR_WINDOW = 20            # 经典 N = 20 日 ATR
STOP_MULTS = [1, 2, 3]     # 止损倍数对比 1N/2N/3N
DEFAULT_STOP_MULT = 2      # 默认止损倍数（作图与默认指标）

# ---- 完整海龟版新增规则参数（ATR头寸规模法 + 金字塔加仓）----
RISK_PCT = 0.01            # 单笔单位风险预算 = 账户权益的 1%（海龟经典）
ADD_STEP = 0.5             # 金字塔加仓间距：价格每上行 0.5N 加 1 单位
MAX_UNITS = 4              # 单一标的最多持有 4 个单位（海龟经典上限）
POS_CAP = 1.0             # 无杠杆现金上限：总仓位不超过 100% 权益（A股散户约束）
PYRAMID = True             # 是否启用金字塔加仓

# 交易成本（HW4 新增卖出印花税，更贴近 A 股实盘）
COMMISSION = 0.0003        # 佣金（单边万三）
SLIPPAGE = 0.0005          # 滑点（万五）
MIN_COMMISSION = 5.0       # 单笔最低佣金（元，不免五）
STAMP_TAX = 0.0005         # 卖出印花税（0.05%）


# ============================================================
# 1) 加载已存储的股价数据（前复权 + 复权正确性校验）
# ============================================================
def load_stock_pair(raw_file, qfq_file, code, name, note):
    """
    加载原始价 + 前复权价。
    前复权文件(qfq)已含调整后的 OHLC 与 adj_factor；本函数同时：
      - 以 qfq 文件的 OHLC 作为“前复权价”主序列（最精确）；
      - 用原始价 × adj_factor / max(adj_factor) 重算一遍作为交叉验证，
        计算重算 close 与 qfq 文件 close 的最大绝对差 max_diff（应极小）。
    返回 (df, max_diff)，df 含 *_raw 与 *_qfq 两套 OHLC 及 adj_factor。
    """
    raw = pd.read_csv(raw_file, encoding='utf-8-sig')
    qfq = pd.read_csv(qfq_file, encoding='utf-8-sig')

    # 以 qfq 文件为基准（含已调整 OHLC + adj_factor）
    df = qfq.rename(columns={
        'open': 'open_qfq', 'high': 'high_qfq',
        'low': 'low_qfq', 'close': 'close_qfq'})

    # 合并原始未调整 OHLC（按 trade_date 对齐）
    raw2 = raw[['trade_date', 'open', 'high', 'low', 'close']].rename(
        columns={'open': 'open_raw', 'high': 'high_raw',
                 'low': 'low_raw', 'close': 'close_raw'})
    df = df.merge(raw2, on='trade_date', how='left')

    # 交叉验证：用原始价重算前复权
    fmax = df['adj_factor'].max()
    df['close_recomp'] = df['close_raw'] * df['adj_factor'] / fmax
    max_diff = float((df['close_recomp'] - df['close_qfq']).abs().max())

    # 日期解析与排序
    dt = pd.to_datetime(df['trade_date'], format='%Y%m%d', errors='coerce')
    if dt.isna().any():
        dt = dt.fillna(pd.to_datetime(df['trade_date'], errors='coerce'))
    df['trade_date'] = dt
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['code'] = code
    df['name'] = name
    df['note'] = note
    df['_fmax'] = fmax
    return df, max_diff


# ============================================================
# 2) 高低价格通道（对应需求 b）
# ============================================================
def compute_channels(df, entry_w, exit_w, use_qfq=True):
    """
    唐奇安通道（Donchian Channel）：
      - 入场通道上轨 = 前 entry_w 日最高价（滚动 max，shift(1) 防未来函数）
      - 离场通道下轨 = 前 exit_w 日最低价（滚动 min，shift(1) 防未来函数）
    """
    h = 'high_qfq' if use_qfq else 'high_raw'
    l = 'low_qfq' if use_qfq else 'low_raw'
    upper = df[h].rolling(entry_w).max().shift(1)   # 入场通道上轨
    lower = df[l].rolling(exit_w).min().shift(1)    # 离场通道下轨
    return upper, lower


# ============================================================
# 3) ATR（对应需求 c）—— 经典算法
# ============================================================
def compute_atr(df, window=20, use_qfq=True):
    """
    平均真实波幅 ATR（即海龟的“N”）：
      TR = max(H-L, |H-prevC|, |L-prevC|)
      ATR = mean(TR, window)   （经典简单平均；可换 Wilder 平滑）
    """
    h = 'high_qfq' if use_qfq else 'high_raw'
    l = 'low_qfq' if use_qfq else 'low_raw'
    c = 'close_qfq' if use_qfq else 'close_raw'
    prev_c = df[c].shift(1)
    tr = pd.concat([
        (df[h] - df[l]).abs(),
        (df[h] - prev_c).abs(),
        (df[l] - prev_c).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window).mean()        # 简单平均（经典海龟）
    return atr


# ============================================================
# 4) 买卖信号（对应需求 d）—— 状态机 + 严格防未来函数
# ============================================================
def compute_signals(df, upper, lower, atr, stop_mult=2, use_qfq=True,
                    risk_pct=RISK_PCT, add_step=ADD_STEP,
                    max_units=MAX_UNITS, pyramid=PYRAMID, pos_cap=POS_CAP):
    """
    完整海龟信号状态机（仅做多）—— 含 ATR 头寸规模法 + 金字塔加仓 + 止损随加仓上移。

    (1) 首次建仓：空仓且 close 向上突破入场通道上轨 → 买入第 1 个单位。
    (2) ATR 头寸规模法：单个单位占权益比例 f = risk_pct × price / N。
        含义——价格每反向波动 1 个 N，该单位市值波动 = 股数×N = (risk_pct×权益/N)×N = risk_pct×权益，
        即每单位承担约 risk_pct(=1%) 权益的“市场波动风险”，实现按波动率标准化的仓位管理。
        A股不可加杠杆，故总仓位以 pos_cap(=1.0，满仓) 封顶。
    (3) 金字塔加仓：持仓后价格每较“上一单位入场价”上行 add_step·N(=0.5N) 即加 1 单位，
        最多 max_units(=4) 个单位；每次加仓后止损价上移到“最后一单位入场价 − k·N”，
        对整体持仓统一止损（锁定利润、控制回撤）。
    (4) 离场：当日 low ≤ 止损价 → 止损离场；或 close 跌破离场通道下轨 → 跌破离场（全部清仓）。

    执行价统一为次日开盘（pos_exec = pos.shift(1)），杜绝前视偏差。
    返回 buy, add, sell, stop_hit, pos, pos_exec, units_arr
      - buy       首次突破建仓日
      - add       金字塔加仓日
      - sell      离场日（含止损）
      - stop_hit  因止损离场日
      - pos       目标仓位（占权益比例，0..pos_cap，可小数）
      - pos_exec  次日开盘成交后的实际持仓比例
      - units_arr 每日持仓单位数（0..max_units，整数）
    """
    c = 'close_qfq' if use_qfq else 'close_raw'
    h = 'high_qfq' if use_qfq else 'high_raw'
    low = 'low_qfq' if use_qfq else 'low_raw'
    close = df[c].values.astype(float)
    high_arr = df[h].values.astype(float)
    low_arr = df[low].values.astype(float)
    atr_arr = atr.values.astype(float)
    n = len(df)

    buy = np.zeros(n, dtype=bool)
    add = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    stop_hit = np.zeros(n, dtype=bool)
    pos = np.zeros(n)
    units_arr = np.zeros(n, dtype=int)

    units = 0
    frac_sum = 0.0          # 已建单位对应的目标仓位比例之和
    last_entry_px = 0.0     # 最近一次建/加仓成交价（用于加仓间距与移动止损）
    entry_N = 0.0           # 首次建仓时的 N（用于加仓间距与止损带宽）
    stop_px = 0.0

    for i in range(1, n):
        if units == 0:
            # ---- 首次突破建仓 ----
            if (pd.notna(upper.iloc[i]) and close[i] > upper.iloc[i]
                    and atr_arr[i] > 0):
                buy[i] = True
                units = 1
                entry_N = atr_arr[i]
                last_entry_px = close[i]
                unit_frac = risk_pct * close[i] / entry_N
                frac_sum = min(pos_cap, unit_frac)
                stop_px = last_entry_px - stop_mult * entry_N
        else:
            # ---- 先判离场（止损优先，用当日最低价）----
            exited = False
            if pd.notna(low_arr[i]) and low_arr[i] <= stop_px:
                stop_hit[i] = True
                sell[i] = True
                exited = True
            elif pd.notna(lower.iloc[i]) and close[i] < lower.iloc[i]:
                sell[i] = True
                exited = True

            if exited:
                units = 0
                frac_sum = 0.0
                last_entry_px = 0.0
                entry_N = 0.0
                stop_px = 0.0
            elif pyramid and entry_N > 0:
                # ---- 金字塔加仓：价格每上行 0.5N 加 1 单位 ----
                while (units < max_units and frac_sum < pos_cap and
                       high_arr[i] >= last_entry_px + add_step * entry_N):
                    units += 1
                    last_entry_px = last_entry_px + add_step * entry_N
                    unit_frac = risk_pct * close[i] / entry_N
                    frac_sum = min(pos_cap, frac_sum + unit_frac)
                    stop_px = last_entry_px - stop_mult * entry_N  # 止损随最后一单位上移
                    add[i] = True
        pos[i] = frac_sum
        units_arr[i] = units

    pos_exec = pd.Series(pos).shift(1).fillna(0.0)   # 次日开盘成交
    return buy, add, sell, stop_hit, pos, pos_exec, units_arr


# ============================================================
# 5) 回测引擎（含成本 / 不含成本 双版本，HW4 新增卖出印花税）
# ============================================================
def run_backtest(close_arr, position_exec, cost_on=True, commission=COMMISSION,
                 slippage=SLIPPAGE, ratio=1.0, min_commission=MIN_COMMISSION,
                 stamp_tax=STAMP_TAX, init_capital=100000.0):
    """
    模拟交易回测（与 HW3 同口径，新增卖出印花税）。
    - 每日策略收益 = 执行仓位 × 当日收益率
    - 调仓日扣佣金+滑点+（卖出时）印花税；佣金设单笔最低佣金
    返回 equity_with, equity_no, net_with, net_no
    """
    close = np.asarray(close_arr, dtype=float)
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
                if pos[i] < pos[i - 1]:       # 减仓 = 卖出 → 计印花税
                    cost += turnover * stamp_tax
        nw = strat - cost
        nn = strat
        ew *= (1.0 + nw)
        en *= (1.0 + nn)
        net_with[i] = nw
        net_no[i] = nn
        equity_with[i] = ew
        equity_no[i] = en

    return equity_with, equity_no, net_with, net_no


def buy_and_hold(close_arr):
    """买入持有基准（无成本）净值曲线。"""
    close = np.asarray(close_arr, dtype=float)
    n = len(close)
    eq = np.zeros(n)
    e = 1.0
    for i in range(n):
        r = 0.0 if i == 0 else (close[i] / close[i - 1] - 1.0)
        e *= (1.0 + r)
        eq[i] = e
    return eq


# ============================================================
# 6) 量化指标（基础 + 海龟扩展）
# ============================================================
def turtle_metrics(equity, net_ret, position_exec, stop_hit, atr_arr,
                   ratio=1.0, rf=RF, af=ANNUAL_FACTOR):
    """计算单条净值曲线对应的全部指标（含海龟扩展）。"""
    eq = np.asarray(equity, dtype=float)
    ret = np.asarray(net_ret, dtype=float)
    n = len(eq)
    stop_hit = np.asarray(stop_hit, dtype=bool)

    total = eq[-1] / eq[0] - 1.0
    years = n / af
    ann = (eq[-1] / eq[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    mdd = float(-dd.min())

    rfd = rf / af
    ex = ret - rfd
    std = ex.std(ddof=1) if n > 1 else 0.0
    sharpe = float(ex.mean() / std * np.sqrt(af)) if std > 0 else 0.0

    # 交易回合（round-trip）：完整海龟版仓位是连续比例（0..pos_cap），不再非 0 即 1。
    # 一笔“交易”定义为：仓位从 0 增到 >0（首次建仓）到回落到 0（清仓）的完整回合，
    # 中间的金字塔加仓不另计为一笔，归属同一回合。
    pos = position_exec.values * ratio
    eps = 1e-9
    trades = []
    stop_exits = 0
    hold_days_list = []
    entry_atr_list = []
    i = 1
    while i < n:
        if pos[i] > eps and pos[i - 1] <= eps:
            e_idx = i
            x = None
            j = i + 1
            while j < n:
                if pos[j] <= eps and pos[j - 1] > eps:
                    x = j
                    break
                j += 1
            if x is None:
                x = n - 1
            tret = eq[x] / eq[e_idx - 1] - 1.0
            is_stop = bool(stop_hit[x - 1]) if (x - 1) >= 0 else False
            if is_stop:
                stop_exits += 1
            trades.append(tret)
            hold_days_list.append(x - e_idx)
            if (e_idx - 1) < len(atr_arr):
                entry_atr_list.append(float(atr_arr[e_idx - 1]))
            i = x + 1
        else:
            i += 1

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean([abs(t) for t in losses])) if losses else 0.0
    if avg_loss > 1e-6:
        pl = avg_win / avg_loss
    elif avg_win > 1e-6:
        pl = None
    else:
        pl = 0.0

    # 最大连续亏损次数
    max_consec_loss = 0
    run = 0
    for t in trades:
        if t <= 0:
            run += 1
            max_consec_loss = max(max_consec_loss, run)
        else:
            run = 0

    return {
        'total_return': float(total),
        'annual_return': float(ann),
        'mdd': float(mdd),
        'sharpe': float(sharpe),
        'win_rate': float(win_rate),
        'profit_loss_ratio': (None if pl is None else float(pl)),
        'n_trades': len(trades),
        'n_stop_exits': int(stop_exits),
        'stop_exit_ratio': (float(stop_exits) / len(trades)) if trades else 0.0,
        'avg_hold_days': (float(np.mean(hold_days_list)) if hold_days_list else 0.0),
        'max_consec_loss': int(max_consec_loss),
        'avg_entry_atr': (float(np.mean(entry_atr_list)) if entry_atr_list else 0.0),
    }


# ============================================================
# 7) 可视化（matplotlib 静态 PNG，供 PDF 备份）
# ============================================================
def plot_channels_signals(df, upper, lower, buy, add, sell, stop_hit, sys_name,
                          entry_w, exit_w, stop_mult, units_arr, path):
    dates = df['trade_date']
    close = df['close_qfq']
    fig, ax = plt.subplots(figsize=(13, 6.4))
    ax.plot(dates, close, label='收盘价(前复权)', color=COLOR_CLOSE, lw=1.1)
    ax.plot(dates, upper, label=f'入场通道上轨({entry_w}日高)', color=COLOR_UPPER,
            lw=1.2, ls='--')
    ax.plot(dates, lower, label=f'离场通道下轨({exit_w}日低)', color=COLOR_LOWER,
            lw=1.2, ls='--')

    ax.scatter(dates[buy], close[buy], marker='^', color=COLOR_UP, s=95,
               zorder=5, label='买入(首次建仓)')
    ax.scatter(dates[add], close[add], marker='^', color=COLOR_STOP, s=50,
               zorder=5, label='加仓(金字塔,0.5N)')
    ax.scatter(dates[sell & ~stop_hit], close[sell & ~stop_hit], marker='v',
               color=COLOR_DOWN, s=95, zorder=5, label='卖出(跌破)')
    ax.scatter(dates[stop_hit], close[stop_hit], marker='x', color=COLOR_STOP, s=80,
               zorder=5, label=f'止损(k={stop_mult}N)')

    # 持仓单位数（右轴，直观展示金字塔加仓过程）
    ax2 = ax.twinx()
    ax2.step(dates, units_arr, where='post', color='#3b5bdb', lw=1.1, alpha=0.55)
    ax2.set_ylabel('持仓单位数', color='#3b5bdb')
    ax2.set_ylim(-0.5, MAX_UNITS + 0.5)
    ax2.set_yticks(range(0, MAX_UNITS + 1))
    ax2.tick_params(axis='y', labelcolor='#3b5bdb')
    ax2.grid(False)

    ax.set_title(f"{df['name'].iloc[0]}  海龟{sys_name}  价格+高低通道+信号 (止损{stop_mult}N, ATR头寸+金字塔)",
                 fontsize=13)
    ax.set_ylabel('价格(前复权)')
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


def plot_atr(dates, atr, name, sys_name, path):
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(dates, atr, label='ATR (N)', color=COLOR_ATR, lw=1.4)
    ax.set_title(f"{name}  海龟{sys_name}  ATR(20日平均真实波幅)", fontsize=13)
    ax.set_ylabel('ATR')
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


def plot_equity(dates, eq_with, eq_no, bh, name, sys_name, path):
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(dates, eq_with, label='策略(含成本)', color=COLOR_UP, lw=1.4)
    ax.plot(dates, eq_no, label='策略(不含成本)', color=COLOR_STOP, lw=1.4, ls='--')
    ax.plot(dates, bh, label='买入持有', color='#4d8bff', lw=1.4, ls=':')
    ax.set_title(f"{name}  海龟{sys_name}  资金曲线", fontsize=13)
    ax.set_ylabel('净值(起始=1.0)')
    ax.axhline(1.0, color='gray', lw=0.8)
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


def plot_drawdown(dates, equity, name, sys_name, path):
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.fill_between(dates, dd * 100, 0, color=COLOR_DOWN, alpha=0.35)
    ax.plot(dates, dd * 100, color=COLOR_DOWN, lw=1.0)
    ax.set_title(f"{name}  海龟{sys_name}  回撤曲线", fontsize=13)
    ax.set_ylabel('回撤(%)')
    ax.grid(True, alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)


# ============================================================
# HTML 看板生成（内联数据 + Chart.js，参数可交互）
# ============================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>海龟交易策略回测看板</title>
<script src="chart.umd.min.js"></script>
  <style>
  :root{
    --up:#ff4d6d; --down:#25e899; --band:#7c5cff; --stop:#ffa940;
    --bg:#f5f6f8; --surface:#ffffff; --ink:#171a21; --ink-2:#3a4150;
    --muted:#6c7480; --line:#e7e9ee; --accent:#3b5bdb; --accent-ink:#2c44b8;
    --accent-soft:rgba(59,91,219,.09); --shadow-sm:0 1px 2px rgba(16,24,40,.04);
    --shadow-md:0 8px 28px rgba(16,24,40,.08); --radius:16px; --radius-sm:11px;
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
  @media (max-width:760px){ .metrics{grid-template-columns:repeat(2,1fr);}
    .controls-grid{grid-template-columns:1fr 1fr;} }
  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;}}
  @media print{ body{background:#fff;background-image:none;} .card{box-shadow:none;break-inside:avoid;animation:none;}
    .print-btn,.controls-grid{display:none!important;} .metrics{margin-bottom:8px;} }
</style>
</head>
<body>
<header>
  <h1>海龟交易策略（Turtle Trading）回测看板 <span class="section-tag">HW4</span></h1>
  <p>唐奇安通道突破 · ATR 波动止损 · 系统1(20/10) / 系统2(55/20) · 止损倍数 1N/2N/3N 对比 · 可交互调参 · 前复权</p>
</header>

<div class="wrap">

  <!-- 概念讲解 -->
  <div class="card">
    <h2>一、核心概念讲解</h2>
    <h3>1. 海龟法则（Turtle Trading Rules）</h3>
    <p>1983 年传奇交易员 Richard Dennis 与 William Eckhardt 的著名实验：他们培训一批“海龟”学员，
       教授一套完整的<strong>趋势跟踪 + 严格风控 + 头寸管理</strong>机械交易系统，证明交易能否盈利更多取决于
       可复制的纪律与系统，而非天赋。本看板复刻其经典通道突破系统。</p>
    <h3>2. 高低价格通道（Donchian Channel）</h3>
    <ul>
      <li><strong>入场通道上轨</strong> = 前 N 日最高价（如 20 日）。当收盘价<strong>向上突破</strong>上轨 → 买入信号。</li>
      <li><strong>离场通道下轨</strong> = 前 M 日最低价（如 10 日）。当收盘价<strong>向下跌破</strong>下轨 → 卖出信号。</li>
      <li>系统1（短期）：N=20 入场 / M=10 出场；系统2（长期）：N=55 入场 / M=20 出场。</li>
    </ul>
    <h3>3. 平均真实波幅 ATR（Average True Range）</h3>
    <p>真实波幅 TR = max(H−L, |H−前收|, |L−前收|)；ATR 即 TR 的 N 日均值（海龟称“N”），度量市场波动率。
       ATR 越大波动越剧烈，止损距离随之放大，实现<strong>波动率标准化</strong>的风险控制。</p>
    <h3>4. 止损条件（k·N 止损）</h3>
    <p>入场后设置止损价 = 入场价 − k×N（N 为入场时 ATR）。价格触及即离场。k 越小止损越紧（交易少、单笔亏小但假突破多），
       k 越大止损越宽（扛得住噪声但偶发大亏）。本看板对比 <strong>1N / 2N / 3N</strong>。</p>
    <h3>5. 头寸规模法（ATR Sizing）与金字塔加仓（Pyramiding）</h3>
    <p>海龟最具辨识度的资金管理创新，也是本作业相对前两版的增强点：
       <strong>① ATR 头寸规模法</strong>——单个单位占权益比例 f = 风险预算(1%) × 价格 ÷ N。
       价格每反向波动 1 个 N，该单位市值波动恰等于约 1% 权益，从而<strong>按波动率标准化风险</strong>（波动大的股票少买、波动小的多买）。
       <strong>② 金字塔加仓</strong>——持仓后价格每较上一单位入场价上行 0.5N 就加 1 个单位，最多 4 个单位；
       每次加仓后止损价上移至“最后一单位入场价 − k·N”，对整体持仓统一止损，既放大顺势利润又锁定回撤。
       A股不可加杠杆，故总仓位以 100% 权益封顶。</p>
    <div class="note">防未来函数：信号在<strong>当日收盘</strong>判定，实际<strong>次日开盘</strong>成交（仓位整体后移 1 日）。
       止损“触发”用当日最低价是否跌破止损价判定。看板仅做多（A股散户无法便捷做空），并启用 ATR 头寸规模法 + 金字塔加仓（最多 4 单位，总仓 ≤100%）。</div>
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
      <div class="ctrl">海龟系统
        <div class="ctrl-row">
          <button class="btn active" onclick="setSystem('S1')" id="sysS1">系统1 (20/10)</button>
          <button class="btn" onclick="setSystem('S2')" id="sysS2">系统2 (55/20)</button>
        </div>
      </div>
      <div class="ctrl">止损倍数 k·N
        <div class="ctrl-row">
          <button class="btn" onclick="setStop(1)" id="stop1">1N</button>
          <button class="btn active" onclick="setStop(2)" id="stop2">2N</button>
          <button class="btn" onclick="setStop(3)" id="stop3">3N</button>
        </div>
      </div>
      <div class="ctrl">起始日期<input id="startDate" type="date"></div>
      <div class="ctrl">结束日期<input id="endDate" type="date"></div>
      <div class="ctrl">ATR 窗口
        <input id="atrWin" type="range" min="5" max="60" value="20" style="width:100%">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#9aa1ad;"><span>5</span><span id="atrVal">20</span><span>60</span></div>
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
      <div class="ctrl">卖出印花税<input id="stamp" type="number" value="0.0005" step="0.0001" style="width:100%"></div>
      <div class="ctrl">最低佣金(元/笔)<input id="minComm" type="number" value="5" step="1" min="0" style="width:100%"></div>
      <label class="toggle-wrap ctrl"><span style="font-size:13px;">使用前复权价</span>
        <div class="toggle"><input type="checkbox" id="useQfq" checked><span class="slider"></span></div>
      </label>
      <div class="ctrl">初始资金（元）<input id="initCapital" type="number" value="100000" step="10000" style="width:100%"></div>
      <div class="ctrl" style="justify-content:flex-end;">
        <button class="btn btn-reset" onclick="resetParams()" style="width:100%;">重置默认参数</button>
      </div>
    </div>
  </div>

  <!-- 图表1：价格+通道+信号 -->
  <div class="card">
    <h2>三、价格 + 高低通道 + 买卖信号</h2>
    <div class="charts"><canvas id="chartPrice"></canvas></div>
  </div>

  <!-- 图表2：ATR -->
  <div class="card">
    <h2>四、ATR（平均真实波幅）</h2>
    <div class="charts"><canvas id="chartATR"></canvas></div>
  </div>

  <!-- 图表3：净值对比 -->
  <div class="card">
    <h2>五、策略净值 vs 买入持有基准</h2>
    <div class="charts"><canvas id="chartEquity"></canvas></div>
  </div>

  <!-- 图表4：回撤 -->
  <div class="card">
    <h2>六、回撤曲线</h2>
    <div class="charts"><canvas id="chartDD"></canvas></div>
  </div>

  <!-- 实验对比 -->
  <div class="card">
    <h2>七、参数敏感性实验对比（股票 × 系统 × 止损倍数）</h2>
    <p class="note">佣金万三、滑点万五、卖出印花税万五、最低佣金5元、ATR窗口20、满仓。共 18 组：
       观察止损倍数（1N/2N/3N）、系统（S1 短期 / S2 长期）、股票三者对收益与风险的影响。</p>
    <div id="expTable" style="overflow-x:auto;"></div>
  </div>

  <!-- 应用心得 -->
  <div class="card">
    <h2>八、应用心得与 A 股适用场景</h2>
    <ul>
      <li><strong>趋势依赖强</strong>：海龟是纯趋势跟踪系统，单边市（如长期上行/下行）能吃主升浪；震荡市频繁假突破，反复止损磨损成本。</li>
      <li><strong>系统2 更平滑、更滞后</strong>：55/20 长周期过滤噪声、信号少而稳；20/10 短周期灵敏但假信号多。需结合标的性质与持有周期选择。</li>
      <li><strong>止损倍数权衡</strong>：1N 止损紧、交易少、单笔亏小但容易被噪声扫损；3N 止损宽、扛得住波动但偶发单笔大亏。2N 为经典折中。</li>
      <li><strong>成本不可忽视</strong>：HW4 较 HW3 新增<strong>卖出印花税 0.05%</strong>，频繁进出下佣金+滑点+印花税显著吞噬利润，实盘必须计入。</li>
      <li><strong>复权不可省</strong>：除权除息缺口会制造虚假突破，本看板全部使用前复权价，并经“原始价×复权因子”交叉校验确认无误。</li>
      <li><strong>A 股特化注意</strong>：仅做多、T+1、涨跌停限制，原版空头与金字塔加仓在本土散户场景受限；牛短熊长环境下趋势策略整体承压，宜配合长期趋势过滤。</li>
    </ul>
  </div>

</div>
<button class="print-btn" onclick="window.print()">打印 / 导出 PDF</button>

<script>
const STOCKS_RAW = __STOCKS_RAW__;
const STOCKS_QFQ = __STOCKS_QFQ__;
const EXPERIMENT = __EXP__;

let chartPrice, chartATR, chartEquity, chartDD;
let curSystem = 'S1';
let curStop = 2;

function setSystem(s){ curSystem = s;
  document.getElementById('sysS1').classList.toggle('active', s==='S1');
  document.getElementById('sysS2').classList.toggle('active', s==='S2');
  render(); }
function setStop(k){ curStop = k;
  [1,2,3].forEach(function(v){ document.getElementById('stop'+v).classList.toggle('active', v===k); });
  render(); }
function setPresetComm(val){ document.getElementById('commission').value = val; syncCommPreset(); render(); }
function syncCommPreset(){ const v = parseFloat(document.getElementById('commission').value);
  document.querySelectorAll('[onclick^="setPresetComm"]').forEach(function(b){
    const bval = parseFloat(b.getAttribute('onclick').match(/[\d.]+/)[0]);
    b.classList.toggle('active', Math.abs(bval - v) < 1e-9); }); }
document.getElementById('commission').addEventListener('input', function(){ syncCommPreset(); render(); });

document.getElementById('atrWin').addEventListener('input', function(){
  document.getElementById('atrVal').textContent = this.value; render(); });

function resetParams(){
  document.getElementById('stock').value = 'pingan';
  curSystem = 'S1'; curStop = 2;
  document.getElementById('sysS1').classList.add('active'); document.getElementById('sysS2').classList.remove('active');
  [1,2,3].forEach(function(v){ document.getElementById('stop'+v).classList.toggle('active', v===2); });
  document.getElementById('atrWin').value = 20; document.getElementById('atrVal').textContent = '20';
  document.getElementById('cost').checked = true;
  document.getElementById('commission').value = '0.0003'; syncCommPreset();
  document.getElementById('slippage').value = '0.0005';
  document.getElementById('stamp').value = '0.0005';
  document.getElementById('minComm').value = '5';
  document.getElementById('useQfq').checked = true;
  document.getElementById('initCapital').value = '100000';
  const key = document.getElementById('stock').value;
  const s = getStockData(key, true);
  if(s && s.dates.length > 0){ document.getElementById('startDate').value = s.dates[0];
    document.getElementById('endDate').value = s.dates[s.dates.length-1]; }
  render();
}

function getStockData(key, useQfq){ if(useQfq && STOCKS_QFQ[key]) return STOCKS_QFQ[key]; return STOCKS_RAW[key] || null; }

function sliceData(stock, startDate, endDate){
  if(!stock || !stock.dates.length) return null;
  let si = 0, ei = stock.dates.length - 1;
  if(startDate){ si = stock.dates.indexOf(startDate); if(si === -1) si = 0; }
  if(endDate){ ei = stock.dates.indexOf(endDate); if(ei === -1) ei = stock.dates.length - 1; }
  if(si >= ei) { si = 0; ei = stock.dates.length - 1; }
  const out = {name: stock.name, code: stock.code, note: stock.note};
  out.dates = stock.dates.slice(si, ei+1);
  out.close = stock.close.slice(si, ei+1);
  out.high = stock.high.slice(si, ei+1);
  out.low = stock.low.slice(si, ei+1);
  return out;
}

function rollingMax(arr, p){ const out = new Array(arr.length).fill(null);
  let m = -Infinity; const q = [];
  for(let i=0;i<arr.length;i++){ q.push(arr[i]);
    if(q.length > p) q.shift();
    out[i] = (i >= p-1) ? Math.max.apply(null, q) : null; }
  return out; }
function rollingMin(arr, p){ const out = new Array(arr.length).fill(null);
  let q = [];
  for(let i=0;i<arr.length;i++){ q.push(arr[i]);
    if(q.length > p) q.shift();
    out[i] = (i >= p-1) ? Math.min.apply(null, q) : null; }
  return out; }
function rollingMean(arr, p){ const out = new Array(arr.length).fill(null); let sum=0;
  for(let i=0;i<arr.length;i++){ sum += arr[i]; if(i>=p) sum -= arr[i-p];
    if(i>=p-1) out[i] = sum/p; } return out; }
function shiftRight(arr){ const out = new Array(arr.length).fill(null);
  for(let i=1;i<arr.length;i++) out[i] = arr[i-1]; return out; }

function computeTR(high, low, close){ const n = close.length; const tr = new Array(n);
  for(let i=0;i<n;i++){ if(i===0){ tr[i] = high[i]-low[i]; continue; }
    tr[i] = Math.max(high[i]-low[i], Math.abs(high[i]-close[i-1]), Math.abs(low[i]-close[i-1])); }
  return tr; }
function computeATR(high, low, close, win){ const tr = computeTR(high, low, close);
  return rollingMean(tr, win); }

function turtleSignals(close, high, low, upper, lower, atr, stopMult){
  const n = close.length;
  // 与 Python 端一致：ATR 头寸规模法 + 金字塔加仓（海龟完整版）
  const RISK_PCT=0.01, ADD_STEP=0.5, MAX_UNITS=4, POS_CAP=1.0, PYRAMID=true;
  const buy = new Array(n).fill(false), add = new Array(n).fill(false);
  const sell = new Array(n).fill(false), stopHit = new Array(n).fill(false);
  const pos = new Array(n).fill(0), units = new Array(n).fill(0);
  let curUnits = 0, fracSum = 0, lastEntryPx = 0, entryN = 0, stopPx = 0;
  for(let i=1;i<n;i++){
    if(curUnits === 0){
      if(upper[i] != null && close[i] > upper[i] && (atr[i]!=null?atr[i]:0) > 0){
        buy[i] = true; curUnits = 1; entryN = (atr[i]!=null?atr[i]:0);
        lastEntryPx = close[i];
        const uf = RISK_PCT*close[i]/entryN; fracSum = Math.min(POS_CAP, uf);
        stopPx = lastEntryPx - stopMult*entryN;
      }
    } else {
      let exited = false;
      if(low[i] != null && low[i] <= stopPx){ stopHit[i]=true; sell[i]=true; exited=true; }
      else if(lower[i] != null && close[i] < lower[i]){ sell[i]=true; exited=true; }
      if(exited){ curUnits=0; fracSum=0; lastEntryPx=0; entryN=0; stopPx=0; }
      else if(PYRAMID && entryN>0){
        while(curUnits < MAX_UNITS && fracSum < POS_CAP &&
              high[i] >= lastEntryPx + ADD_STEP*entryN){
          curUnits += 1; lastEntryPx = lastEntryPx + ADD_STEP*entryN;
          const uf = RISK_PCT*close[i]/entryN; fracSum = Math.min(POS_CAP, fracSum+uf);
          stopPx = lastEntryPx - stopMult*entryN; add[i]=true;
        }
      }
    }
    pos[i] = fracSum; units[i] = curUnits;
  }
  const posExec = new Array(n).fill(0);
  for(let i=1;i<n;i++) posExec[i] = pos[i-1];
  return {buy, add, sell, stopHit, pos, posExec, units};
}

function backtest(close, posExec, costOn, comm, slip, ratio, minComm, stamp, initCap){
  minComm = (minComm===undefined)?5 : minComm; initCap = (initCap===undefined)?100000 : initCap;
  stamp = (stamp===undefined)?0 : stamp; ratio = (ratio===undefined)?1 : ratio;
  const n = close.length; const dailyRet = new Array(n).fill(0);
  for(let i=1;i<n;i++) dailyRet[i]=close[i]/close[i-1]-1;
  const eqW=new Array(n), eqN=new Array(n), netW=new Array(n), netN=new Array(n);
  let ew=1, en=1;
  for(let i=0;i<n;i++){ const p = posExec[i]*ratio; const sr = (i===0)?0 : p*dailyRet[i];
    let cost=0;
    if(i>0 && costOn){ const turnover = Math.abs(posExec[i]*ratio - posExec[i-1]*ratio);
      if(turnover>0){ const portVal = ew*initCap; const tradeVal = turnover*portVal;
        const commAmt = Math.max(tradeVal*comm, minComm); cost = commAmt/portVal + slip*turnover;
        if(posExec[i]*ratio < posExec[i-1]*ratio) cost += turnover*stamp; } }
    const nw = sr - cost, nn = sr; ew*=(1+nw); en*=(1+nn);
    eqW[i]=ew; eqN[i]=en; netW[i]=nw; netN[i]=nn; }
  return {eqW, eqN, netW, netN};
}
function bhEquity(close){ const n=close.length; const eq=new Array(n); let e=1;
  for(let i=0;i<n;i++){ const r=(i===0)?0:close[i]/close[i-1]-1; e*=(1+r); eq[i]=e; } return eq; }

function metrics(equity, netRet, posExec, stopHit, ratio, af){
  const n=equity.length; const total=equity[n-1]/equity[0]-1; const years=n/af;
  const ann=Math.pow(equity[n-1]/equity[0], 1/years)-1;
  let peak=equity[0]; const dd=new Array(n); let mdd=0;
  for(let i=0;i<n;i++){ if(equity[i]>peak)peak=equity[i]; dd[i]=equity[i]/peak-1; if(-dd[i]>mdd)mdd=-dd[i]; }
  let mean=0; for(let i=0;i<n;i++) mean+=netRet[i]; mean/=n;
  let v=0; for(let i=0;i<n;i++){const d=netRet[i]-mean; v+=d*d;} v/=(n-1);
  const std=Math.sqrt(v); const sharpe= std>0? mean/std*Math.sqrt(af):0;
  const pos=posExec.map(function(v){return v*ratio;});
  const EPS=1e-9; const trades=[]; let stopExits=0; const holds=[];
  let i=1;
  while(i<n){
    if(pos[i]>EPS && pos[i-1]<=EPS){
      const e=i; let x=null; let j=i+1;
      while(j<n){ if(pos[j]<=EPS && pos[j-1]>EPS){ x=j; break; } j++; }
      if(x===null)x=n-1; const t=equity[x]/equity[e-1]-1; trades.push(t); holds.push(x-e);
      if(stopHit[x]) stopExits++;
      i = x+1;
    } else { i++; }
  }
  let wins=0; for(const t of trades) if(t>0)wins++;
  const winRate= trades.length? wins/trades.length:0;
  let aw=0,wl=0,wc=0,lc=0; for(const t of trades){ if(t>0){aw+=t;wc++;} else {wl+=Math.abs(t);lc++;} }
  const avgWin=wc?aw/wc:0, avgLoss=lc?wl/lc:0;
  const pl= avgLoss>0? avgWin/avgLoss : (avgWin>0? Infinity:0);
  const maxConsec= (function(){let mx=0,run=0; for(const t of trades){ if(t<=0){run++;mx=Math.max(mx,run);} else run=0;} return mx;})();
  return {total, ann, mdd, sharpe, winRate, pl, nTrades:trades.length,
    stopExits, stopRatio: trades.length? stopExits/trades.length:0,
    avgHold: holds.length? holds.reduce(function(a,b){return a+b;},0)/holds.length:0, dd, maxConsec};
}

function fmtPct(x){ return (x*100).toFixed(2)+'%'; }
function fmtNum(x){ return x==null||x===Infinity? '—' : x.toFixed(2); }
function cls(x){ return x>=0? 'pos':'neg'; }

function render(){
  const key = document.getElementById('stock').value;
  const useQfq = document.getElementById('useQfq').checked;
  const sFull = getStockData(key, useQfq);
  if(!sFull){ document.getElementById('metrics').innerHTML='<p>无数据</p>'; return; }

  const sysParams = curSystem==='S1' ? {entry:20, exit:10} : {entry:55, exit:20};
  const atrWin = parseInt(document.getElementById('atrWin').value)||20;
  const costOn = document.getElementById('cost').checked;
  const comm = parseFloat(document.getElementById('commission').value)||0;
  const slip = parseFloat(document.getElementById('slippage').value)||0;
  const stamp = parseFloat(document.getElementById('stamp').value)||0;
  const minComm = parseFloat(document.getElementById('minComm').value);
  const minCommV = isNaN(minComm) ? 5 : minComm;
  const capital = parseFloat(document.getElementById('initCapital').value)||100000;
  const ratio = 1.0;
  const startDate = document.getElementById('startDate').value;
  const endDate = document.getElementById('endDate').value;

  if(!startDate && sFull.dates.length > 0){
    document.getElementById('startDate').value = sFull.dates[0];
    document.getElementById('endDate').value = sFull.dates[sFull.dates.length-1];
  }
  const s = sliceData(sFull, startDate || sFull.dates[0], endDate || sFull.dates[sFull.dates.length-1]);

  document.getElementById('stocknote').textContent =
    s.name + (useQfq?' [前复权]':'') + ' (' + s.code + ') ｜ 共 ' + s.dates.length + ' 个交易日' +
    (startDate ? ' ｜ ' + startDate + ' ~ ' + endDate : '') +
    ' ｜ ' + curSystem + '(' + sysParams.entry + '/' + sysParams.exit + ') ｜ 止损' + curStop + 'N ｜ ATR窗口' + atrWin;

  const upper = shiftRight(rollingMax(s.high, sysParams.entry));
  const lower = shiftRight(rollingMin(s.low, sysParams.exit));
  const atr = computeATR(s.high, s.low, s.close, atrWin);
  const sig = turtleSignals(s.close, s.high, s.low, upper, lower, atr, curStop);
  const bt = backtest(s.close, sig.posExec, costOn, comm, slip, ratio, minCommV, stamp, capital);
  const bh = bhEquity(s.close);

  const mW = metrics(bt.eqW, bt.netW, sig.posExec, sig.stopHit, ratio, 252);
  const mN = metrics(bt.eqN, bt.netN, sig.posExec, sig.stopHit, ratio, 252);
  const bhTotal = bh[bh.length-1]/bh[0]-1;
  const excess = mW.total - bhTotal;

  // 图表1：价格 + 通道 + 信号
  const upperShift = upper.map(function(v){return v==null?null:v;});
  const lowerShift = lower.map(function(v){return v==null?null:v;});
  const buyData = s.close.map(function(v,i){ return sig.buy[i]? v : null; });
  const addData = s.close.map(function(v,i){ return sig.add[i]? v : null; });
  const sellData = s.close.map(function(v,i){ return (sig.sell[i]&&!sig.stopHit[i])? v : null; });
  const stopData = s.close.map(function(v,i){ return sig.stopHit[i]? v : null; });
  const pdata = { labels: s.dates, datasets: [
    {label:'收盘价(前复权)', data:s.close, borderColor:'#2b2b2b', borderWidth:1.1, pointRadius:0, yAxisID:'yPrice'},
    {label:'入场通道上轨('+sysParams.entry+'日高)', data:upperShift, borderColor:'#ff4d6d', borderWidth:1.2, borderDash:[6,4], pointRadius:0, yAxisID:'yPrice'},
    {label:'离场通道下轨('+sysParams.exit+'日低)', data:lowerShift, borderColor:'#25e899', borderWidth:1.2, borderDash:[6,4], pointRadius:0, yAxisID:'yPrice'},
    {label:'买入(首次建仓)', data:buyData, showLine:false, pointStyle:'triangle', pointRadius:7, pointBackgroundColor:'#ff4d6d', borderColor:'#ff4d6d'},
    {label:'加仓(金字塔,0.5N)', data:addData, showLine:false, pointStyle:'triangle', pointRadius:5, pointBackgroundColor:'#ffa940', borderColor:'#ffa940'},
    {label:'卖出(跌破)', data:sellData, showLine:false, pointStyle:'triangle', pointRotation:180, pointRadius:7, pointBackgroundColor:'#25e899', borderColor:'#25e899'},
    {label:'止损(k='+curStop+'N)', data:stopData, showLine:false, pointStyle:'x', pointRadius:7, pointBackgroundColor:'#ffa940', borderColor:'#ffa940'},
    {label:'持仓单位数', data:sig.units, borderColor:'#3b5bdb', borderWidth:1.1, pointRadius:0, yAxisID:'yUnits', borderDash:[2,2]},
  ]};
  if(chartPrice) chartPrice.destroy();
  chartPrice = new Chart(document.getElementById('chartPrice'), {type:'line', data:pdata,
    options:{responsive:true, interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{maxTicksLimit:15}},
        yPrice:{position:'left', title:{display:true, text:'价格(前复权)'}},
        yUnits:{position:'right', min:0, max:4, title:{display:true, text:'单位数'},
          grid:{drawOnChartArea:false}, ticks:{stepSize:1}}},
      plugins:{legend:{position:'top'}}}});

  // 图表2：ATR
  const adata = { labels: s.dates, datasets: [
    {label:'ATR (N, '+atrWin+'日)', data:atr, borderColor:'#7c5cff', borderWidth:1.4, pointRadius:0},
  ]};
  if(chartATR) chartATR.destroy();
  chartATR = new Chart(document.getElementById('chartATR'), {type:'line', data:adata,
    options:{responsive:true, scales:{x:{ticks:{maxTicksLimit:15}}}, plugins:{legend:{position:'top'}}}});

  // 图表3：净值
  const edata = { labels: s.dates, datasets: [
    {label:'策略净值(含成本)', data:bt.eqW, borderColor:'#ff4d6d', borderWidth:1.4, pointRadius:0},
    {label:'策略净值(不含成本)', data:bt.eqN, borderColor:'#ffa940', borderWidth:1.4, borderDash:[6,4], pointRadius:0},
    {label:'买入持有基准', data:bh, borderColor:'#4d8bff', borderWidth:1.4, borderDash:[2,3], pointRadius:0},
  ]};
  if(chartEquity) chartEquity.destroy();
  chartEquity = new Chart(document.getElementById('chartEquity'), {type:'line', data:edata,
    options:{responsive:true, interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{maxTicksLimit:15}}}, plugins:{legend:{position:'top'}}}});

  // 图表4：回撤
  const ddPct = mW.dd.map(function(v){ return v*100; });
  const ddata = {labels:s.dates, datasets:[
    {label:'Drawdown %', data:ddPct, borderColor:'#25e899', backgroundColor:'rgba(37,232,153,.25)',
     fill:true, pointRadius:0, borderWidth:1}]};
  if(chartDD) chartDD.destroy();
  chartDD = new Chart(document.getElementById('chartDD'), {type:'line', data:ddata,
    options:{responsive:true, scales:{x:{ticks:{maxTicksLimit:15}}}, plugins:{legend:{display:false}}}});

  // 指标卡
  const cards = [
    ['年化收益率', fmtPct(mW.ann), '基准 '+fmtPct(Math.pow(1+bhTotal,252/s.dates.length)-1)],
    ['夏普比率', fmtNum(mW.sharpe), costOn ? '含成本' : '不计成本'],
    ['最大回撤', fmtPct(mW.mdd), mW.mdd<=0?'':' '+((s.dates[mW.dd.indexOf(-mW.mdd)]||'')+' 起')],
    ['胜率', fmtPct(mW.winRate), mW.nTrades+'笔 · 盈亏比 '+fmtNum(mW.pl)],
    ['累计收益(含成本)', fmtPct(mW.total), '≈ ¥'+Math.round(capital*mW.total).toLocaleString()],
    ['累计收益(无成本)', fmtPct(mN.total), '≈ ¥'+Math.round(capital*mN.total).toLocaleString()],
    ['超额收益(策略-B&H)', fmtPct(excess), excess>=0?'跑赢基准':'跑输基准'],
    ['买入持有收益', fmtPct(bhTotal), '≈ ¥'+Math.round(capital*bhTotal).toLocaleString()],
    ['止损离场占比', fmtPct(mW.stopRatio), mW.stopExits+'/'+mW.nTrades+' 笔'],
    ['平均持仓(交易日)', fmtNum(mW.avgHold), '最长连亏 '+mW.maxConsec+' 笔'],
  ];
  document.getElementById('metrics').innerHTML = cards.map(function(c){
    return '<div class="metric"><div class="k">'+c[0]+'</div><div class="v '+cls(parseFloat(c[1]))+'">'+c[1]+
    '</div><div class="sub">'+c[2]+'</div></div>'; }).join('');

  buildExpTable();
}

function buildExpTable(){
  const exp = EXPERIMENT;
  let html = '<table><thead><tr><th>股票</th><th>系统</th><th>止损</th><th>总收益(含)</th>'+
    '<th>最大回撤</th><th>夏普</th><th>胜率</th><th>盈亏比</th><th>交易次数</th><th>止损占比</th><th>平均持仓</th></tr></thead><tbody>';
  for(const row of exp.rows){
    html += '<tr><td>'+row.stock+'</td><td>'+row.system+'</td><td>'+row.stop+'N</td>'+
      '<td class="'+cls(row.total_with)+'">'+fmtPct(row.total_with)+'</td>'+
      '<td class="neg">'+fmtPct(row.mdd_with)+'</td>'+
      '<td>'+fmtNum(row.sharpe_with)+'</td>'+
      '<td>'+fmtPct(row.win_rate)+'</td>'+
      '<td>'+fmtNum(row.pl)+'</td>'+
      '<td>'+row.n_trades+'</td>'+
      '<td>'+fmtPct(row.stop_exit_ratio)+'</td>'+
      '<td>'+fmtNum(row.avg_hold_days)+'</td></tr>';
  }
  html += '</tbody></table>';
  document.getElementById('expTable').innerHTML = html;
}

['stock','cost','slippage','stamp','initCapital','minComm','startDate','endDate','useQfq'].forEach(function(id){
  const el = document.getElementById(id); el.addEventListener('input', render); el.addEventListener('change', render); });

syncCommPreset();
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
    out = os.path.join(BASE_DIR, '海龟策略看板.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    return out


# ============================================================
# 主流程
# ============================================================
def main():
    print('=' * 60)
    print('HW4 海龟交易策略（Turtle Trading）回测')
    print('=' * 60)

    # 加载全部股票（原始 + 前复权）
    stocks = {}        # key -> df（含 *_raw / *_qfq / adj_factor）
    qfq_diff = {}      # key -> max_diff 校验值
    for key, (fname, code, name, note, qfq_fname) in STOCK_CONFIG.items():
        df, max_diff = load_stock_pair(
            os.path.join(DATA_DIR, fname), os.path.join(DATA_DIR, qfq_fname),
            code, name, note)
        stocks[key] = df
        qfq_diff[key] = max_diff
        print(f'  {name}({code}): {len(df)} 条, '
              f'{df["trade_date"].min().date()} ~ {df["trade_date"].max().date()} '
              f'| 复权校验 max_diff={max_diff:.6f} (adj_factor max={float(df["_fmax"].iloc[0]):.4f})')

    # ---- 默认参数图表 + 指标（系统1/系统2 × 默认止损 2N）----
    print(f'\n计算默认参数图表与指标 (止损{DEFAULT_STOP_MULT}N, ATR={ATR_WINDOW})...')
    metrics_all = {'stocks': {}, 'qfq_diff': qfq_diff,
                   'default_stop': DEFAULT_STOP_MULT, 'atr_window': ATR_WINDOW}
    for key, df in stocks.items():
        metrics_all['stocks'][key] = {'name': df['name'].iloc[0],
                                      'code': df['code'].iloc[0],
                                      'systems': {}}
        for sys_key, sys in SYSTEMS.items():
            ew, ex = sys['entry'], sys['exit']
            upper, lower = compute_channels(df, ew, ex, use_qfq=True)
            atr = compute_atr(df, ATR_WINDOW, use_qfq=True)
            (buy, add, sell, stop_hit, pos, pos_exec, units_arr) = compute_signals(
                df, upper, lower, atr, stop_mult=DEFAULT_STOP_MULT, use_qfq=True)
            eq_w, eq_n, net_w, net_n = run_backtest(df['close_qfq'], pos_exec, cost_on=True)
            bh = buy_and_hold(df['close_qfq'])
            m_w = turtle_metrics(eq_w, net_w, pos_exec, stop_hit, atr.values)
            m_n = turtle_metrics(eq_n, net_n, pos_exec, stop_hit, atr.values)
            bh_total = bh[-1] / bh[0] - 1
            metrics_all['stocks'][key]['systems'][sys_key] = {
                'with': m_w, 'without': m_n, 'bh': bh_total,
                'entry': ew, 'exit': ex}

            # 作图（4 张/系统）
            plot_channels_signals(df, upper, lower, buy, add, sell, stop_hit,
                                  sys['name'], ew, ex, DEFAULT_STOP_MULT, units_arr,
                                  os.path.join(DATA_DIR, f'{key}_{sys_key}_price_channels.png'))
            plot_atr(df['trade_date'], atr, df['name'].iloc[0], sys['name'],
                     os.path.join(DATA_DIR, f'{key}_{sys_key}_atr.png'))
            plot_equity(df['trade_date'], eq_w, eq_n, bh, df['name'].iloc[0], sys['name'],
                        os.path.join(DATA_DIR, f'{key}_{sys_key}_equity.png'))
            plot_drawdown(df['trade_date'], eq_w, df['name'].iloc[0], sys['name'],
                          os.path.join(DATA_DIR, f'{key}_{sys_key}_drawdown.png'))

            print(f'  [{df["name"].iloc[0]} {sys_key}] 总收益(含)={m_w["total_return"]*100:7.2f}%  '
                  f'MDD={m_w["mdd"]*100:6.2f}%  Sharpe={m_w["sharpe"]:6.2f}  '
                  f'胜率={m_w["win_rate"]*100:5.1f}%  交易={m_w["n_trades"]:3d}次  '
                  f'止损占比={m_w["stop_exit_ratio"]*100:5.1f}%')

    with open(os.path.join(DATA_DIR, 'backtest_metrics.json'), 'w', encoding='utf-8') as f:
        json.dump(metrics_all, f, ensure_ascii=False, indent=2)

    # ---- 参数敏感性全网格：股票 × 系统 × 止损倍数 = 18 组 ----
    print('\n扫描 股票 × 系统 × 止损倍数 组合 (18 组)...')
    exp_rows = []
    for key, df in stocks.items():
        for sys_key, sys in SYSTEMS.items():
            ew, ex = sys['entry'], sys['exit']
            upper, lower = compute_channels(df, ew, ex, use_qfq=True)
            atr = compute_atr(df, ATR_WINDOW, use_qfq=True)
            for k in STOP_MULTS:
                _, _, _, stop_hit, _, pos_exec, _ = compute_signals(
                    df, upper, lower, atr, stop_mult=k, use_qfq=True)
                eq_w, eq_n, net_w, net_n = run_backtest(df['close_qfq'], pos_exec, cost_on=True)
                m_w = turtle_metrics(eq_w, net_w, pos_exec, stop_hit, atr.values)
                m_n = turtle_metrics(eq_n, net_n, pos_exec, stop_hit, atr.values)
                exp_rows.append({
                    'stock': df['name'].iloc[0], 'code': df['code'].iloc[0],
                    'system': sys_key, 'entry': ew, 'exit': ex, 'stop': k,
                    'total_with': m_w['total_return'], 'total_without': m_n['total_return'],
                    'annual_with': m_w['annual_return'], 'mdd_with': m_w['mdd'],
                    'sharpe_with': m_w['sharpe'], 'win_rate': m_w['win_rate'],
                    'pl': m_w['profit_loss_ratio'], 'n_trades': m_w['n_trades'],
                    'stop_exit_ratio': m_w['stop_exit_ratio'],
                    'avg_hold_days': m_w['avg_hold_days'],
                    'max_consec_loss': m_w['max_consec_loss'],
                })
    experiment = {
        'params': {'atr_window': ATR_WINDOW, 'commission': COMMISSION,
                   'slippage': SLIPPAGE, 'stamp_tax': STAMP_TAX,
                   'min_commission': MIN_COMMISSION, 'systems': SYSTEMS,
                   'stop_mults': STOP_MULTS},
        'rows': exp_rows}
    with open(os.path.join(DATA_DIR, 'experiment_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(experiment, f, ensure_ascii=False, indent=2)

    # ---- 通道周期扫描（以三一重工为例，止损 2N，ATR=20）----
    print('\n通道周期扫描 (三一重工, 止损2N)...')
    scan_rows = []
    scan_stock = stocks['sany']
    scan_atr = compute_atr(scan_stock, ATR_WINDOW, use_qfq=True)
    for ew in [10, 20, 40, 55]:
        ex = max(5, ew // 2)
        upper, lower = compute_channels(scan_stock, ew, ex, use_qfq=True)
        _, _, _, stop_hit, _, pos_exec, _ = compute_signals(
            scan_stock, upper, lower, scan_atr, stop_mult=2, use_qfq=True)
        eq_w, _, net_w, _ = run_backtest(scan_stock['close_qfq'], pos_exec, cost_on=True)
        m_w = turtle_metrics(eq_w, net_w, pos_exec, stop_hit, scan_atr.values)
        scan_rows.append({'entry': ew, 'exit': ex, 'total_with': m_w['total_return'],
                          'mdd_with': m_w['mdd'], 'sharpe_with': m_w['sharpe'],
                          'win_rate': m_w['win_rate'], 'n_trades': m_w['n_trades'],
                          'stop_exit_ratio': m_w['stop_exit_ratio']})
    with open(os.path.join(DATA_DIR, 'channel_scan.json'), 'w', encoding='utf-8') as f:
        json.dump({'stock': '三一重工', 'stop': 2, 'atr_window': ATR_WINDOW,
                   'rows': scan_rows}, f, ensure_ascii=False, indent=2)

    # ---- 看板数据（嵌入原始序列 + 前复权序列：close/high/low）----
    def _payload_from_df(df, qfq):
        return {
            'name': df['name'].iloc[0], 'code': df['code'].iloc[0],
            'note': df['note'].iloc[0],
            'dates': df['trade_date'].dt.strftime('%Y-%m-%d').tolist(),
            'close': [round(float(v), 4) for v in df['close_raw' if not qfq else 'close_qfq']],
            'high': [round(float(v), 4) for v in df['high_raw' if not qfq else 'high_qfq']],
            'low': [round(float(v), 4) for v in df['low_raw' if not qfq else 'low_qfq']],
        }

    stocks_raw_payload = {}
    stocks_qfq_payload = {}
    for key in STOCK_CONFIG:
        stocks_raw_payload[key] = _payload_from_df(stocks[key], qfq=False)
        stocks_qfq_payload[key] = _payload_from_df(stocks[key], qfq=True)

    out_html = build_html(stocks_raw_payload, stocks_qfq_payload, experiment)
    print(f'\n看板已生成: {out_html}')
    print(f'图表与 JSON 已写入: {DATA_DIR}')
    print('\n' + '=' * 60)
    print('完成！用浏览器打开「海龟策略看板.html」即可交互查看，')
    print('点击右下角按钮可打印 / 导出 PDF。')
    print('=' * 60)


if __name__ == '__main__':
    main()
