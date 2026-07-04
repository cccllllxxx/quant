# -*- coding: utf-8 -*-
"""
HW2 指标计算脚本
计算 RSI、MACD、布林带、OBV 及参数敏感性数据
输出 JSON 供网站使用
"""

import json
import os
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ============================================================
# 指标计算函数
# ============================================================

def calc_rsi(close, period=14):
    """RSI 相对强弱指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(close, fast=12, slow=26, signal=9):
    """MACD 指标"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2  # A股惯例: 柱状图 = 2*(DIF-DEA)
    return dif, dea, hist


def calc_bollinger(close, period=20, num_std=2):
    """布林带"""
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid
    return mid, upper, lower, bandwidth


def calc_obv(close, vol):
    """OBV 能量潮"""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * vol).cumsum()
    return obv


def calc_atr(high, low, close, period=14):
    """ATR 平均真实波幅 (扩展)"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr


# ============================================================
# 数据处理
# ============================================================

def load_stock(filepath, name):
    """加载股票数据"""
    df = pd.read_csv(filepath, encoding='utf-8-sig')
    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['name'] = name
    return df


def compute_all_indicators(df):
    """计算全部指标"""
    close = df['close']
    vol = df['vol']
    high = df['high']
    low = df['low']

    # 基础指标
    df['RSI_14'] = calc_rsi(close, 14)
    df['DIF'], df['DEA'], df['MACD_HIST'] = calc_macd(close)
    df['BOLL_MID'], df['BOLL_UPPER'], df['BOLL_LOWER'], df['BOLL_BW'] = calc_bollinger(close)
    df['OBV'] = calc_obv(close, vol)
    df['ATR_14'] = calc_atr(high, low, close)
    df['MA5'] = close.rolling(5).mean()
    df['MA20'] = close.rolling(20).mean()

    # 参数敏感性: RSI
    df['RSI_7'] = calc_rsi(close, 7)
    df['RSI_21'] = calc_rsi(close, 21)

    # 参数敏感性: 布林带
    df['BOLL_MID_15'], df['BOLL_UPPER_15'], df['BOLL_LOWER_15'], _ = calc_bollinger(close, 20, 1.5)
    df['BOLL_MID_25'], df['BOLL_UPPER_25'], df['BOLL_LOWER_25'], _ = calc_bollinger(close, 20, 2.5)

    return df


def df_to_chart_data(df, columns, date_col='trade_date'):
    """将 DataFrame 转为图表友好的 JSON 格式"""
    result = {}
    dates = df[date_col].dt.strftime('%Y-%m-%d').tolist()
    result['dates'] = dates
    for col in columns:
        if col in df.columns:
            result[col] = [None if pd.isna(v) else round(float(v), 4) for v in df[col]]
    return result


def compute_stats(df, name):
    """计算描述性统计量"""
    stats_cols = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    stats = df[stats_cols].describe()
    # 缺失值检查
    missing = df[stats_cols].isnull().sum().to_dict()
    missing_total = int(sum(missing.values()))

    result = {
        'name': name,
        'ts_code': df['ts_code'].iloc[0],
        'date_range': {
            'start': df['trade_date'].min().strftime('%Y-%m-%d'),
            'end': df['trade_date'].max().strftime('%Y-%m-%d')
        },
        'total_records': len(df),
        'missing_values': {k: int(v) for k, v in missing.items()},
        'missing_total': missing_total,
        'statistics': {}
    }

    col_names_cn = {
        'open': '开盘价', 'high': '最高价', 'low': '最低价',
        'close': '收盘价', 'vol': '成交量(手)', 'amount': '成交额(千元)',
        'pct_chg': '涨跌幅(%)'
    }

    for col in stats_cols:
        s = stats[col]
        result['statistics'][col] = {
            'name_cn': col_names_cn.get(col, col),
            'count': int(s['count']),
            'mean': round(float(s['mean']), 4),
            'std': round(float(s['std']), 4),
            'min': round(float(s['min']), 4),
            '25%': round(float(s['25%']), 4),
            '50%': round(float(s['50%']), 4),
            '75%': round(float(s['75%']), 4),
            'max': round(float(s['max']), 4),
        }

    return result


def export_indicators_json(df, name):
    """导出指标数据为 JSON"""
    columns = [
        'close', 'vol', 'pct_chg',
        'MA5', 'MA20',
        'RSI_14', 'RSI_7', 'RSI_21',
        'DIF', 'DEA', 'MACD_HIST',
        'BOLL_MID', 'BOLL_UPPER', 'BOLL_LOWER', 'BOLL_BW',
        'BOLL_UPPER_15', 'BOLL_LOWER_15',
        'BOLL_UPPER_25', 'BOLL_LOWER_25',
        'OBV', 'ATR_14'
    ]
    chart_data = df_to_chart_data(df, columns)

    # 找一些关键信号点用于交互
    signals = find_signal_points(df)

    output = {
        'name': name,
        'ts_code': df['ts_code'].iloc[0],
        'chart_data': chart_data,
        'signals': signals
    }

    filepath = os.path.join(DATA_DIR, f'{name}_indicators.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"  -> {filepath}")
    return output


def find_signal_points(df):
    """找出一些关键信号点供交互使用"""
    signals = []
    n = len(df)

    for i in range(1, n):
        date_str = df['trade_date'].iloc[i].strftime('%Y-%m-%d')
        idx = i

        # RSI 超买超卖
        rsi = df['RSI_14'].iloc[i]
        if pd.notna(rsi):
            if rsi > 70:
                signals.append({'date': date_str, 'idx': idx, 'type': 'rsi_overbought', 'value': round(float(rsi), 2)})
            elif rsi < 30:
                signals.append({'date': date_str, 'idx': idx, 'type': 'rsi_oversold', 'value': round(float(rsi), 2)})

        # MACD 金叉死叉
        if i > 0 and pd.notna(df['DIF'].iloc[i]) and pd.notna(df['DEA'].iloc[i]):
            dif_now = df['DIF'].iloc[i]
            dea_now = df['DEA'].iloc[i]
            dif_prev = df['DIF'].iloc[i-1]
            dea_prev = df['DEA'].iloc[i-1]
            if pd.notna(dif_prev) and pd.notna(dea_prev):
                if dif_prev <= dea_prev and dif_now > dea_now:
                    signals.append({'date': date_str, 'idx': idx, 'type': 'macd_golden_cross', 'value': round(float(dif_now), 4)})
                elif dif_prev >= dea_prev and dif_now < dea_now:
                    signals.append({'date': date_str, 'idx': idx, 'type': 'macd_death_cross', 'value': round(float(dif_now), 4)})

        # 布林带突破
        close = df['close'].iloc[i]
        upper = df['BOLL_UPPER'].iloc[i]
        lower = df['BOLL_LOWER'].iloc[i]
        if pd.notna(upper) and close > upper:
            signals.append({'date': date_str, 'idx': idx, 'type': 'boll_breakout_up', 'value': round(float(close), 2)})
        elif pd.notna(lower) and close < lower:
            signals.append({'date': date_str, 'idx': idx, 'type': 'boll_breakout_down', 'value': round(float(close), 2)})

    # 限量返回（避免太多）
    return signals[:50]


def export_param_sensitivity(df, name):
    """导出参数敏感性对比数据"""
    # RSI 参数对比
    rsi_compare = df_to_chart_data(df, ['RSI_7', 'RSI_14', 'RSI_21'])

    # 布林带参数对比
    boll_compare = df_to_chart_data(df, [
        'close',
        'BOLL_UPPER_15', 'BOLL_LOWER_15',
        'BOLL_UPPER', 'BOLL_LOWER',
        'BOLL_UPPER_25', 'BOLL_LOWER_25'
    ])

    output = {
        'name': name,
        'rsi_compare': rsi_compare,
        'boll_compare': boll_compare
    }

    filepath = os.path.join(DATA_DIR, f'{name}_param_sensitivity.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"  -> {filepath}")
    return output


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 50)
    print("HW2 指标计算脚本")
    print("=" * 50)

    # 加载数据
    pingan = load_stock(
        os.path.join(BASE_DIR, '平安集团行情数据.csv'),
        'pingan'
    )
    sany = load_stock(
        os.path.join(BASE_DIR, '三一重工行情数据.csv'),
        'sany'
    )

    print(f"\n平安银行: {len(pingan)} 条记录, {pingan['trade_date'].min().date()} ~ {pingan['trade_date'].max().date()}")
    print(f"三一重工: {len(sany)} 条记录, {sany['trade_date'].min().date()} ~ {sany['trade_date'].max().date()}")

    # 计算指标
    print("\n计算技术指标...")
    pingan = compute_all_indicators(pingan)
    sany = compute_all_indicators(sany)

    # 描述性统计
    print("\n生成描述性统计量...")
    pingan_stats = compute_stats(pingan, '平安银行')
    sany_stats = compute_stats(sany, '三一重工')

    with open(os.path.join(DATA_DIR, 'pingan_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(pingan_stats, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, 'sany_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(sany_stats, f, ensure_ascii=False, indent=2)
    print(f"  -> {DATA_DIR}/pingan_stats.json")
    print(f"  -> {DATA_DIR}/sany_stats.json")

    # 指标数据
    print("\n导出指标数据 JSON...")
    export_indicators_json(pingan, 'pingan')
    export_indicators_json(sany, 'sany')

    # 参数敏感性
    print("\n导出参数敏感性数据 JSON...")
    export_param_sensitivity(pingan, 'pingan')
    export_param_sensitivity(sany, 'sany')

    # 合并统计概览
    overview = {
        'stocks': [
            {'name': '平安银行', 'ts_code': '000001.SZ', 'records': len(pingan),
             'start': pingan['trade_date'].min().strftime('%Y-%m-%d'),
             'end': pingan['trade_date'].max().strftime('%Y-%m-%d')},
            {'name': '三一重工', 'ts_code': '600031.SH', 'records': len(sany),
             'start': sany['trade_date'].min().strftime('%Y-%m-%d'),
             'end': sany['trade_date'].max().strftime('%Y-%m-%d')},
        ]
    }
    with open(os.path.join(DATA_DIR, 'overview.json'), 'w', encoding='utf-8') as f:
        json.dump(overview, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print("全部完成！JSON 文件已输出到 data/ 目录")
    print("=" * 50)


if __name__ == '__main__':
    main()
