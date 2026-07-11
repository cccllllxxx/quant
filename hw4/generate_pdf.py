# -*- coding: utf-8 -*-
"""生成 TASK4 海龟交易策略作业 PDF。
格式要求：宋体、五号(10.5pt)、1.5倍行距、0段间距、两端对齐；
统计图带标号+标题+解读。
用法: python generate_pdf.py [姓名] [学号]
"""
import os
import sys
import json
from PIL import Image as PImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                Table, TableStyle, PageBreak)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BASE = r"C:\Users\clxx\Desktop\光华量化\HW4"
DATA = os.path.join(BASE, "data")

NAME = sys.argv[1] if len(sys.argv) > 1 else "陈柳萱"
SID  = sys.argv[2] if len(sys.argv) > 2 else "（学号）"

# ---------- 字体（宋体） ----------
font_path = r"C:\Windows\Fonts\simsun.ttc"
if not os.path.exists(font_path):
    font_path = r"C:\Windows\Fonts\simsun.ttf"
if font_path.lower().endswith(".ttc"):
    pdfmetrics.registerFont(TTFont("SimSun", font_path, subfontIndex=0))
else:
    pdfmetrics.registerFont(TTFont("SimSun", font_path))

# ---------- 样式 ----------
SIZE = 10.5                      # 五号
LEAD = SIZE * 1.5                # 1.5 倍行距

def style(size=SIZE, lead=None, align=TA_JUSTIFY, first=0, space=0, name=None):
    return ParagraphStyle(name or "s", fontName="SimSun", fontSize=size,
                          leading=lead or size * 1.5, alignment=align,
                          firstLineIndent=first, spaceBefore=space,
                          spaceAfter=space, wordWrap="CJK")

body   = style(first=21)                       # 正文：首行缩进2字、两端对齐、0段距
title  = style(16, align=TA_CENTER)
sub    = style(12, align=TA_CENTER)
h1     = style(13, align=TA_LEFT)              # 一级标题
h2     = style(11.5, align=TA_LEFT)
figcap = style(9.5, align=TA_CENTER)            # 图标题
small  = style(9.5, align=TA_JUSTIFY, first=0)
tblcell = style(8.5, align=TA_CENTER)

# ---------- 数据 ----------
with open(os.path.join(DATA, "backtest_metrics.json"), encoding="utf-8") as f:
    M = json.load(f)
with open(os.path.join(DATA, "experiment_summary.json"), encoding="utf-8") as f:
    E = json.load(f)
with open(os.path.join(DATA, "channel_scan.json"), encoding="utf-8") as f:
    CH = json.load(f)


def pct(x):
    return f"{x*100:.2f}%"


def f2(x):
    return f"{x:.2f}" if x is not None else "N/A"


def fmt_pl(x):
    if x is None:
        return "N/A"
    return f"{x:.2f}"


order = [("maotai", "贵州茅台", "600519.SH"),
         ("pingan", "平安银行", "000001.SZ"),
         ("sany", "三一重工", "600031.SH")]

# ---------- 文档内容 ----------
story = []


def P(t, st=body):
    story.append(Paragraph(t, st))


def gap(h=0.15 * cm):
    story.append(Spacer(1, h))


def add_fig(path, caption, desc, width=13.5 * cm, max_h=8.5 * cm):
    """插入图片并统一缩放。"""
    iw, ih = PImage.open(path).size
    h = width * ih / iw
    if h > max_h:
        h = max_h
        width = h * iw / ih
    story.append(Image(path, width=width, height=h))
    gap(0.1 * cm)
    P(caption, figcap)
    P(desc, body)
    gap(0.2 * cm)


# 封面
gap(3 * cm)
P("海龟交易策略回测分析", title)
P("——以贵州茅台、平安银行、三一重工为例（ATR 头寸规模法与金字塔加仓增强版）", sub)
gap(1.2 * cm)
P(f"姓　名：{NAME}", sub)
P(f"学　号：{SID}", sub)
P("课程：量化投资策略（TASK4）", sub)
P("提交日期：2026-07-11", sub)
story.append(PageBreak())

# 一、策略核心思想与关键优势
P("一、海龟交易策略的核心思想与关键优势", h1)
P("海龟交易法则（Turtle Trading Rules）由美国商品交易员理查德·丹尼斯（Richard Dennis）"
  "与威廉·埃克哈特（William Eckhardt）在 1983 年提出，其本质是一套系统化的趋势跟踪体系。"
  "该法则认为市场价格趋势一旦形成便具有延续性，交易者应通过机械化的规则捕捉中长期趋势，"
  "并严格控制亏损。海龟策略的核心思想可概括为：顺势而为、截断亏损、让利润奔跑。")
P("关键优势体现在以下五点：第一，规则完全客观，杜绝了主观情绪干扰，可在盘中无条件执行；"
  "第二，通过唐奇安通道（Donchian Channel）识别趋势，只在价格创新高/新低时入场，"
  "天然过滤了震荡行情中的大量噪音；第三，以平均真实波幅（ATR）为统一度量，仓位与止损均与"
  "市场波动挂钩，风险可控；第四，采用 2N 止损或离场通道下沿，确保单笔亏损有限，"
  "而盈利头寸可长期持有，形成正期望值；第五，本报告进一步引入海龟原版的 ATR 头寸规模法"
  "与金字塔加仓：单个单位占权益比例 = 1% × 价格 / N，按波动率动态配仓；"
  "价格每较上一单位入场价上行 0.5N 即追加 1 单位（最多 4 单位），止损随加仓整体上移，"
  "使趋势行情中的盈利头寸可逐步放大，而反转时仍能保护利润。")

# 二、关键概念解释
P("二、关键概念解释", h1)
P("（1）高低价格通道（Donchian Channel）：海龟策略使用两条通道线作为入场与离场依据。"
  "入场通道上轨为过去 N 个交易日的最高价（本报告采用 20 日或 55 日），下轨为过去 M 个交易日的"
  "最低价（对应 10 日或 20 日）。当收盘价向上突破上轨时产生买入信号，向下跌破下轨时产生"
  "卖出信号。为保证回测的防未来函数性质，通道值均采用前一日收盘后的滚动极值计算，"
  "即信号在 t 日收盘后产生、在 t+1 日开盘执行。")
P("（2）平均真实波幅（ATR, Average True Range）：ATR 是海龟体系衡量波动率的核心指标。"
  "真实波幅 TR = max(H-L, |H-PrevClose|, |L-PrevClose|)，ATR 为过去 N 日 TR 的简单平均。"
  "本报告采用经典 N=20 的 ATR。ATR 既用于计算止损距离，也用于刻画市场波动水平："
  "高 ATR 意味着价格摆动剧烈，需更宽的止损以避免随机噪音；低 ATR 则表明行情相对平稳。")
P("（3）止损条件：经典海龟法则采用 2N 止损，即建仓后一旦价格从入场价反向波动 2 倍 ATR，"
  "立即止损离场。此外，当收盘价跌破离场通道下轨（10 日或 20 日最低）时也会平仓。"
  "本报告默认使用 2N 止损，并在参数敏感性实验中对比 1N、2N、3N 三种倍数，"
  "以考察不同止损宽度对交易频率与收益的影响。")
P("（4）ATR 头寸规模法与金字塔加仓：海龟交易系统的资金管理核心，也是本报告相对基础版的"
  "增强点。单个单位占权益比例 f = 风险预算（1%） × 价格 / N（N 为入场时 ATR）；"
  "高波动股票自然降低仓位，低波动股票则提高仓位，使每单位承担的“1N 波动风险”"
  "恒等于约 1% 权益。当价格向有利方向每较上一单位入场价移动 0.5N 时追加 1 单位，"
  "最多 4 单位；每次加仓后止损价上移至最后一单位入场价 − k·N，对整体持仓统一止损。"
  "A股不可加杠杆，故总仓位以 100% 权益封顶。")

# 三、评价指标
P("三、量化评价指标定义", h1)
P("本报告沿用 TASK3 的指标口径，并新增海龟策略特有的统计量：")
P("（1）累计回报率：策略期末净值相对期初的收益率。")
P("（2）年化收益率：按每年 252 个交易日折算后的收益率，便于跨样本比较。")
P("（3）最大回撤（MDD）：净值从峰值回落至谷底的最大幅度，衡量极端风险。")
P("（4）夏普比率（Sharpe Ratio）：以无风险利率为 0，年化日收益率均值与年化标准差之比，"
  "衡量风险调整后收益。")
P("（5）胜率：盈利交易次数占全部平仓交易次数的比例。")
P("（6）盈亏比：平均盈利与平均亏损绝对值之比，反映盈利时的“赢大”能力。")
P("（7）止损退出占比：以 2N 止损条件离场的交易数占比，衡量策略依赖止损的程度。")
P("（8）买入持有基准（Buy & Hold）：期初买入并一直持有的收益，作为策略是否创造超额价值的参照。")

# 四、数据与方法
P("四、数据与方法", h1)
P("本报告继续使用贵州茅台（600519.SH）、平安银行（000001.SZ）、三一重工（600031.SH）三只"
  "A 股代表性标的。数据采用 Tushare 日线，并统一做前复权处理：以各 qfq 文件中的已调整 OHLC 为"
  "主序列，同时用原始价 × adj_factor / max(adj_factor) 做交叉验证，复权误差均小于 0.001 元"
  "（茅台 0.000887、平安 0.000000、三一 0.000057），可确认前复权正确。")
P("样本区间：贵州茅台约 844 个交易日（2023-01-03 至 2026-07-01），平安银行与三一重工各约"
  "1086 个交易日（2022-01-04 至 2026-07-01）。")
P("交易成本模型：单边佣金率 0.03%（万三）、单边滑点 0.05%（万五）、卖出印花税 0.05%、"
  "单笔最低佣金 5 元。策略仅做多，无杠杆，无空头交易，符合 A 股散户实盘环境。"
  "仓位管理采用海龟原版 ATR 头寸规模法（风险预算 1%）加金字塔加仓："
  "首次突破建立 1 单位，价格每较上一单位上行 0.5N 即追加 1 单位，最多 4 单位，"
  "总仓位不超过 100% 权益。默认参数为系统1（20 日入场 / 10 日出场）与系统2（55 日入场 / 20 日出场），"
  "止损倍数默认 2N。")
P("需要特别强调的是：所有信号均基于第 t 日收盘数据生成，实际成交在第 t+1 日开盘，"
  "以避免前视偏差（look-ahead bias）。")

# 五、回测结果
P("五、默认参数（系统1/系统2 × 2N 止损）回测结果", h1)
P("表 1 汇总了三只标的在默认参数下的核心指标，同时给出计入交易成本与不计成本两种口径，"
  "以及买入持有基准。", body)

# 表1
tbl1_head = ["标的", "系统", "入场/出场", "累计回报\n(含成本)", "累计回报\n(不含)",
             "年化", "最大回撤", "夏普", "胜率", "交易数", "止损退出", "买入持有"]
tbl1_data = [tbl1_head]
for key, nm, code in order:
    for sk in ["S1", "S2"]:
        sys = M["stocks"][key]["systems"][sk]
        mw, mwo = sys["with"], sys["without"]
        entry, exit_ = sys["entry"], sys["exit"]
        tbl1_data.append([
            nm, "系统1" if sk == "S1" else "系统2",
            f"{entry}/{exit_}",
            pct(mw["total_return"]), pct(mwo["total_return"]),
            pct(mw["annual_return"]), pct(mw["mdd"]), f2(mw["sharpe"]),
            pct(mw["win_rate"]), str(mw["n_trades"]),
            pct(mw["stop_exit_ratio"]), pct(sys["bh"])
        ])
t1 = Table(tbl1_data, colWidths=[1.6*cm, 1.2*cm, 1.6*cm, 1.8*cm, 1.8*cm,
                                   1.4*cm, 1.6*cm, 1.2*cm, 1.4*cm, 1.3*cm, 1.5*cm, 1.5*cm])
t1.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), "SimSun"), ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor('#888888')),
    ("BACKGROUND", (0, 0), (-1, 0), HexColor('#DDDDDD')),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor('#FFFFFF'), HexColor('#F3F6FB')]),
]))
story.append(t1)
gap(0.2 * cm)
P("表 1　默认参数（系统1/系统2 × 2N 止损）回测指标对比", figcap)

P("从表 1 可见，样本期内三只标的整体处于下行或震荡格局，买入持有基准均为负收益"
  "（茅台 -22.06%、平安 -24.26%、三一 -16.81%）。海龟策略在此环境下多数组合仍为负，"
  "但部分组合明显跑赢买入持有。其中，三一重工系统1（20/10）在引入 ATR 头寸规模法与金字塔加仓后"
  "录得 +2.70%，相对买入持有提升约 19.5 个百分点，验证了顺势加仓对捕捉阶段性反弹的贡献；"
  "平安银行系统2（55/20）录得 -10.37%，相对买入持有提升约 13.9 个百分点；"
  "贵州茅台系统1（20/10）录得 -19.37%，亦优于买入持有的 -22.06%。这说明海龟策略的核心价值"
  "并非在于创造绝对收益，而在于趋势不明时空仓观望、趋势确立时按波动率配仓并逐步加仓，"
  "从而规避大幅下跌并放大盈利。")

# 图 1-24
fig_num = 1
for key, nm, code in order:
    for sk in ["S1", "S2"]:
        sys_name = "系统1(20日突破/10日跌破)" if sk == "S1" else "系统2(55日突破/20日跌破)"
        sys_short = "S1" if sk == "S1" else "S2"
        sys_label = "系统1" if sk == "S1" else "系统2"
        sys = M["stocks"][key]["systems"][sk]
        mw = sys["with"]
        mwo = sys["without"]
        bh = sys["bh"]
        entry, exit_ = sys["entry"], sys["exit"]
        n_trades = mw["n_trades"]
        stop_ratio = mw["stop_exit_ratio"] * 100
        avg_hold = mw["avg_hold_days"]
        pl = mw["profit_loss_ratio"]

        # 价格+通道+信号
        cap_price = f"图{fig_num}　{nm}（{code}）{sys_label}：价格、高低通道与买卖信号（含金字塔加仓）"
        desc_price = (f"图中黑色线为收盘价（前复权），红色虚线为入场通道上轨（{entry}日最高），"
                      f"绿色虚线为离场通道下轨（{exit_}日最低）。红色大上三角为首次突破买入信号，"
                      f"橙色小上三角为金字塔加仓（0.5N 间距），绿色下三角为跌破卖出信号，"
                      f"橙色叉号为 2N 止损触发。右侧蓝色阶梯线展示持仓单位数（0~4 单位），"
                      f"直观显示加仓与清仓过程。本组合共完成 {n_trades} 笔完整交易，"
                      f"平均持仓约 {avg_hold:.1f} 日，{stop_ratio:.1f}% 以止损离场。"
                      f"含成本累计收益 {pct(mw['total_return'])}，最大回撤 {pct(mw['mdd'])}，"
                      f"夏普比率 {f2(mw['sharpe'])}。从图上可见，2023 至 2026 年三只标的多次出现"
                      f"假突破后快速回落，正是策略亏损的主要来源；"
                      f"而金字塔加仓在真正的趋势段中放大了盈利。")
        add_fig(os.path.join(DATA, f"{key}_{sk}_price_channels.png"), cap_price, desc_price)
        fig_num += 1

        # ATR
        cap_atr = f"图{fig_num}　{nm}（{code}）：20日平均真实波幅（ATR）"
        desc_atr = (f"该图展示 ATR(20) 的时序变化，反映标的波动率水平。ATR 越高，通道宽度与止损距离"
                    f"越大；ATR 越低，策略对价格噪音更敏感。{nm} 的 ATR 走势与价格剧烈波动阶段基本同步，"
                    f"在下跌趋势中往往伴随 ATR 放大，提示单笔交易风险上升。")
        add_fig(os.path.join(DATA, f"{key}_{sk}_atr.png"), cap_atr, desc_atr)
        fig_num += 1

        # 资金曲线
        cap_eq = f"图{fig_num}　{nm}（{code}）{sys_label}：资金曲线（含成本/不含成本 vs 买入持有）"
        desc_eq = (f"红色实线为策略含成本净值，橙色虚线为不含成本净值，蓝色点线为买入持有基准。"
                   f"含成本累计收益 {pct(mw['total_return'])}，不含成本 {pct(mwo['total_return'])}，"
                   f"买入持有 {pct(bh)}。成本侵蚀约 {pct(mwo['total_return'] - mw['total_return'])}。"
                   f"{('策略曲线显著高于买入持有，体现了趋势空仓的保护作用。' if mw['total_return'] > bh else '策略曲线与买入持有纠缠，受假突破拖累未能显著跑赢基准。')}")
        add_fig(os.path.join(DATA, f"{key}_{sk}_equity.png"), cap_eq, desc_eq)
        fig_num += 1

        # 回撤
        cap_dd = f"图{fig_num}　{nm}（{code}）{sys_label}：策略回撤曲线"
        desc_dd = (f"回撤曲线展示策略净值相对历史峰值的最大回落幅度。本组合最大回撤 {pct(mw['mdd'])}，"
                   f"发生在样本中后期。由于策略空仓机制，回撤曲线呈现阶梯式修复特征，"
                   f"避免了买入持有那种持续深跌且无法止损的局面。")
        add_fig(os.path.join(DATA, f"{key}_{sk}_drawdown.png"), cap_dd, desc_dd)
        fig_num += 1

story.append(PageBreak())

# 六、参数敏感性实验
P("六、参数敏感性实验", h1)
P("为系统考察核心参数对海龟策略的影响，本报告设计了两类实验："
  "（1）股票 × 系统 × 止损倍数 的 18 组全网格；"
  "（2）以三一重工为例，在止损 2N 条件下扫描不同入场/出场周期。", body)

P("表 2 汇总了 18 组全网格的含成本回测结果。", body)

tbl2_head = ["标的", "系统", "入场", "出场", "止损", "累计回报", "年化", "MDD", "Sharpe", "胜率", "交易数", "止损占比"]
tbl2_data = [tbl2_head]
for r in E["rows"]:
    tbl2_data.append([
        r["stock"], r["system"], str(r["entry"]), str(r["exit"]), str(r["stop"]),
        pct(r["total_with"]), pct(r["annual_with"]), pct(r["mdd_with"]),
        f2(r["sharpe_with"]), pct(r["win_rate"]), str(r["n_trades"]), pct(r["stop_exit_ratio"])
    ])
t2 = Table(tbl2_data, colWidths=[1.5*cm, 1.0*cm, 1.0*cm, 1.0*cm, 1.0*cm,
                                 1.7*cm, 1.4*cm, 1.4*cm, 1.3*cm, 1.3*cm, 1.2*cm, 1.5*cm])
t2.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), "SimSun"), ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor('#888888')),
    ("BACKGROUND", (0, 0), (-1, 0), HexColor('#DDDDDD')),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor('#FFFFFF'), HexColor('#F3F6FB')]),
]))
story.append(t2)
gap(0.2 * cm)
P("表 2　股票 × 系统 × 止损倍数 全网格敏感性实验（含成本）", figcap)

P("由表 2 可归纳出四点规律：")
P("（1）止损倍数的影响因系统与标的而异，不存在全局最优。对于系统1（20/10），贵州茅台随止损"
  "从 1N 放宽至 3N，累计回报由 -24.47% 改善至 -17.29%，止损占比由 87.5% 降至 45.5%，"
  "说明较宽止损在茅台的震荡市中减少了被噪音扫出场的次数；平安银行系统1呈现 2N（-30.08%）"
  "差于 1N（-22.16%）和 3N（-21.65%）的 U 型特征，中等宽度止损反而受损；"
  "三一重工系统1在 2N 时表现最优（+2.70%），1N（-17.01%）与 3N（-4.56%）均较差，"
  "说明 2N 对该标的能较好平衡保护利润与容忍波动。")
P("（2）系统2（55/20）通常更紧止损更优。贵州茅台系统2 1N 为 -14.60%，2N 为 -22.25%，"
  "3N 为 -28.61%；平安银行系统2 1N 为 -5.57%，亦优于 2N 的 -10.37%。长期系统本身入场次数少、"
  "持仓周期长，过宽止损会放大单次亏损的绝对额。")
P("（3）系统1 与系统2 的优劣取决于行情节奏。在 2N 止损下，三一重工系统1（+2.70%）远优于"
  "系统2（-10.13%），短期系统更能捕捉 2024–2025 年的阶段性反弹；贵州茅台系统2 1N（-14.60%）"
  "虽然亏损，但优于系统1 1N（-24.47%），在弱趋势中降低交易频率反而更稳健。")
P("（4）交易成本与交易频率正相关。系统1 交易次数显著多于系统2，含成本收益普遍低于不含成本；"
  "高换手在震荡市中放大了成本侵蚀，实务中应降低佣金或适当放宽条件。")

P("表 3 以三一重工为例，展示不同通道周期组合在止损 2N 下的表现。", body)

tbl3_head = ["入场周期", "出场周期", "累计回报", "最大回撤", "Sharpe", "胜率", "交易数", "止损占比"]
tbl3_data = [tbl3_head]
for r in CH["rows"]:
    tbl3_data.append([
        str(r["entry"]), str(r["exit"]), pct(r["total_with"]), pct(r["mdd_with"]),
        f2(r["sharpe_with"]), pct(r["win_rate"]), str(r["n_trades"]), pct(r["stop_exit_ratio"])
    ])
t3 = Table(tbl3_data, colWidths=[2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 1.5*cm, 1.5*cm, 1.5*cm, 1.5*cm])
t3.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), "SimSun"), ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor('#888888')),
    ("BACKGROUND", (0, 0), (-1, 0), HexColor('#DDDDDD')),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor('#FFFFFF'), HexColor('#F3F6FB')]),
]))
story.append(t3)
gap(0.2 * cm)
P("表 3　三一重工不同通道周期下的回测结果（止损 2N）", figcap)

P("表 3 显示，三一重工在 40/20 周期组合下表现最好（累计回报 +6.35%、MDD 15.16%、交易 9 次），"
  "20/10 次之（+2.70%、MDD 18.48%、交易 17 次），10/5 周期过短导致频繁换手（32 次）且"
  "累计回报 -18.27%；55/27 周期过长则反应迟缓，累计回报 -10.05%。这表明在本期行情中，"
  "入场周期在 20~40 日之间是相对合理的平衡点，既能捕捉中期趋势，又不会因过度敏感而反复止损。"
  "值得注意的是，40/20 的优异表现得益于 ATR 头寸规模法与金字塔加仓：较长的入场周期过滤了"
  "短期噪音，而金字塔加仓在趋势确立后逐步放大仓位，从而提升了整体收益。")

# 七、结论
P("七、结论与策略适用性", h1)
P("综合以上回测与参数实验，可得出以下结论：")
P("（1）海龟策略在 A 股 2022–2026 年震荡下行市中多数组合为负收益，但显著优于买入持有的"
  "深跌，体现了其“空仓避险”的核心价值。在引入 ATR 头寸规模法与金字塔加仓后，"
  "三一重工系统1（20/10）录得 +2.70% 的绝对收益，相对买入持有提升约 19.5 个百分点，"
  "最大回撤控制在 18.48% 以内；平安银行系统2（55/20）录得 -10.37%，相对买入持有提升约 13.9 个百分点。"
  "这说明顺势而为的金字塔加仓在阶段性趋势中能有效放大盈利。")
P("（2）止损倍数的最优值取决于系统与行情。系统1（20/10）在茅台和三一上均表现为 2N~3N 优于 1N，"
  "因为较宽止损容忍了短期噪音；系统2（55/20）则在茅台、平安上更紧止损（1N）更优，"
  "因为长期系统持仓周期长，过宽止损会放大单次亏损。实际交易中应结合 ATR 水平与系统周期动态调整。")
P("（3）通道周期选择需匹配行情节奏。本样本中，三一重工在 40/20 周期下表现最佳（+6.35%），"
  "20/10 次之（+2.70%），而 55/27 与 10/5 均明显落后。这表明入场周期在 20~40 日之间"
  "能较好平衡灵敏度与稳定性，过长周期会错失反弹末端，过短周期则会频繁止损。")
P("（4）交易成本对高换手策略侵蚀显著。系统1 交易频率高于系统2，含成本收益普遍低于不含成本；"
  "实务中应使用低佣金账户或适度放宽条件以减少交易次数。")
P("（5）ATR 头寸规模法与金字塔加仓是海龟策略区别于简单通道突破的关键增强。"
  "通过按波动率配仓并在趋势中逐步加仓，策略能够在保留趋势敞口的同时控制单笔风险；"
  "但加仓规则也要求行情具有足够持续性，否则快速反转会导致多次加仓均被套牢。")
P("（6）数据复权是回测可靠性的前提。本报告已验证三只标的 qfq 文件与复权因子重算价的误差"
  "均小于 0.001 元，可放心用于趋势跟踪。")
P("A 股使用心得：海龟策略适合在具有明显中长期趋势的市场中使用，如 2019–2020 年成长股牛市、"
  "2020–2021 年商品牛市或部分行业周期股的主升浪。在 A 股常见的“牛短熊长、急涨慢跌”环境中，"
  "单独使用海龟策略容易反复遭遇假突破；建议将其作为趋势过滤模块，与基本面选股、行业景气度判断"
  "或波动率调节仓位相结合。特别地，本报告引入的 ATR 头寸规模法与金字塔加仓规则，"
  "在 A 股趋势行情中可提升资金效率，但在震荡市中也可能因连续加仓而放大亏损，"
  "因此需严格配合止损纪律，并在市场环境不利时降低风险预算或暂停加仓。")

# ---------- 输出 ----------
out = os.path.join(BASE, f"{NAME}TASK4.pdf")
doc = SimpleDocTemplate(out, pagesize=A4,
                        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
                        title="海龟交易策略回测分析 TASK4", author=NAME)
doc.build(story)
print("已生成:", out, "大小:", os.path.getsize(out), "字节")
