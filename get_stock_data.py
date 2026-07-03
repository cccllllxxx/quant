# -*- coding: utf-8 -*-
"""Fetch and save daily stock data for Kweichow Moutai (600519.SH)."""

TOKEN = "6fee336e108b9f275c1b8fc028d3404420d4fd02536949ef20b661aa"
# 请将上面这行内的 token 替换为你的 tushare token，确保没有额外字符。

import tushare as ts
import pandas as pd
import matplotlib.pyplot as plt


def main():
    """Fetch stock data, save CSV, and plot closing prices."""
    # Initialize tushare pro API with a placeholder token.
    pro = ts.pro_api(TOKEN)

    # Request daily data for Kweichow Moutai (600519.SH) over the specified date range.
    df = pro.daily(
        ts_code="600519.SH",
        start_date="20250701",
        end_date="20260701",
        fields="ts_code,trade_date,open,high,low,close,pre_close,change, pct_chg,vol,amount"
    )

    # Convert trade_date to datetime and sort by date in ascending order.
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values("trade_date", ascending=True).reset_index(drop=True)

    # Save the data to CSV with UTF-8 BOM encoding for better compatibility.
    csv_path = "maotai_stock.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Plot the closing prices.
    plt.figure(figsize=(12, 6))
    plt.plot(df["trade_date"], df["close"], marker="o", linestyle="-", color="tab:blue")
    plt.title("贵州茅台（600519.SH）每日收盘价")
    plt.xlabel("日期")
    plt.ylabel("收盘价")
    plt.grid(True)
    plt.tight_layout()

    # Save the plot to a PNG file.
    image_path = "maotai_close.png"
    plt.savefig(image_path, dpi=300)
    plt.close()

    # Notify completion.
    print("数据获取成功，CSV和图表已保存")


if __name__ == "__main__":
    main()
