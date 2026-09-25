# -*- coding: utf-8 -*-
"""
IV引擎与扫描层：计算IV分位数、识别低票价品种、生成扫描报告数据

核心理论（来自《怎么找到翻十倍的期权》）：
  - "低票价"：当前IV处于历史低位（IV分位数 < 30%）
  - "大颠簸"：持有期RV显著高于建仓IV（IV-RV差值为负）
  - 翻倍潜力 = 低票价 × 大颠簸
"""
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .data_source import (
    scan_all_iv, fetch_product_detail, get_trade_date,
    CN2CODE, PRODUCT_GROUPS, SHFE_OPTION_PRODUCTS, CZCE_OPTION_PRODUCTS,
    GFEX_OPTION_PRODUCTS, DCE_SINA_PRODUCTS,
)

logger = logging.getLogger("scanner.engine")

# ═══════════════════════════════════════════════════════════════
# IV分位数计算
# ═══════════════════════════════════════════════════════════════

def calc_iv_percentile(current_iv: float, hist_ivs: list[float]) -> float:
    """计算当前IV在历史序列中的分位数（0-100）"""
    if not hist_ivs or np.isnan(current_iv):
        return np.nan
    arr = np.array(hist_ivs)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return np.nan
    return round(float(np.percentile(arr, 0) + (current_iv - np.percentile(arr, 0))
                       / (np.percentile(arr, 100) - np.percentile(arr, 0)) * 100), 1)
    # 简化：用百分位排名
    # return round(float((arr < current_iv).sum() / len(arr) * 100), 1)


def calc_iv_rank(current_iv: float, hist_ivs: list[float]) -> float:
    """IV Rank: 当前IV在过去N天中的排名百分位（0-100）"""
    if not hist_ivs or np.isnan(current_iv):
        return np.nan
    arr = np.array(hist_ivs)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return np.nan
    rank = float((arr < current_iv).sum() / len(arr) * 100)
    return round(rank, 1)


def fetch_hist_iv_series(product_name: str, exchange: str,
                         days: int = 120) -> list[float]:
    """
    获取品种历史IV序列（用于分位数计算）。
    从option_vol_shfe/option_hist_czce等接口逐日获取历史IV。
    注意：此函数较慢，仅用于离线计算。
    """
    import akshare as ak
    from .data_source import _safe_call, _product_base_name

    ivs = []
    end_date = datetime.now()
    # 粗略估算交易日（约days*1.4自然日覆盖days个交易日）
    start_date = end_date - timedelta(days=int(days * 1.5))

    try:
        if exchange == "SHFE":
            sym = f"{product_name}期权"
            # option_vol_shfe需要逐日查询，这里简化为取最近一天
            # 历史序列需要多次调用，暂返回空列表（后续可用缓存优化）
            pass
        elif exchange == "CZCE":
            sym = f"{product_name}期权"
            # 同上，CZCE也需逐日查询
            pass
        elif exchange == "GFEX":
            # GFEX同理
            pass
    except Exception as e:
        logger.warning("获取 %s 历史IV失败: %s", product_name, e)

    return ivs


# ═══════════════════════════════════════════════════════════════
# 扫描层：低票价品种筛选
# ═══════════════════════════════════════════════════════════════

# 低票价筛选阈值
LOW_IV_THRESHOLD = 25.0   # IV < 25% 视为低票价候选
IV_PERCENTILE_LOW = 30    # IV分位数 < 30% 视为历史低位

def scan_low_ticket_products(trade_date: str = None,
                              iv_threshold: float = LOW_IV_THRESHOLD) -> pd.DataFrame:
    """
    扫描全市场低票价品种（核心入口）。
    筛选条件：IV < iv_threshold 且有IV数据
    返回: DataFrame 按IV升序排列，含 product_name/exchange/iv/group/volume/open_interest
    """
    if trade_date is None:
        trade_date = get_trade_date(1)

    df = scan_all_iv(trade_date)
    if df.empty:
        return df

    # 过滤有IV数据的品种
    df_iv = df[df["iv"].notna()].copy()

    # 低票价筛选
    low_ticket = df_iv[df_iv["iv"] < iv_threshold].copy()
    low_ticket = low_ticket.sort_values("iv").reset_index(drop=True)

    logger.info("低票价品种（IV < %.0f%%）: %d / %d",
                iv_threshold, len(low_ticket), len(df_iv))

    return low_ticket


def generate_scan_report_data(trade_date: str = None) -> dict:
    """
    生成完整扫描报告数据（供Jinja2模板渲染）。
    返回: dict 含 trade_date, all_products, low_ticket, summary_stats
    """
    if trade_date is None:
        trade_date = get_trade_date(1)

    # 全市场扫描
    all_df = scan_all_iv(trade_date)
    if all_df.empty:
        return {"trade_date": trade_date, "all_products": [],
                "low_ticket": [], "summary": {}}

    # 有IV数据的品种
    df_iv = all_df[all_df["iv"].notna()].copy()

    # 低票价品种
    low_ticket = df_iv[df_iv["iv"] < LOW_IV_THRESHOLD].copy()
    low_ticket = low_ticket.sort_values("iv").reset_index(drop=True)

    # 高波动品种（潜在卖方机会）
    high_iv = df_iv[df_iv["iv"] > 50].copy()
    high_iv = high_iv.sort_values("iv", ascending=False).reset_index(drop=True)

    # 按板块分组统计
    group_stats = []
    for group_name, products in PRODUCT_GROUPS.items():
        mask = df_iv["product_name"].isin(products)
        group_df = df_iv[mask]
        if group_df.empty:
            continue
        group_stats.append({
            "group": group_name,
            "count": len(group_df),
            "avg_iv": round(float(group_df["iv"].mean()), 2),
            "min_iv": round(float(group_df["iv"].min()), 2),
            "max_iv": round(float(group_df["iv"].max()), 2),
            "min_product": group_df.loc[group_df["iv"].idxmin(), "product_name"],
            "max_product": group_df.loc[group_df["iv"].idxmax(), "product_name"],
        })

    # 汇总统计
    summary = {
        "total_products": len(all_df),
        "iv_available": len(df_iv),
        "iv_missing": len(all_df) - len(df_iv),
        "low_ticket_count": len(low_ticket),
        "high_iv_count": len(high_iv),
        "iv_median": round(float(df_iv["iv"].median()), 2),
        "iv_mean": round(float(df_iv["iv"].mean()), 2),
        "iv_min": round(float(df_iv["iv"].min()), 2),
        "iv_min_product": df_iv.loc[df_iv["iv"].idxmin(), "product_name"],
        "iv_max": round(float(df_iv["iv"].max()), 2),
        "iv_max_product": df_iv.loc[df_iv["iv"].idxmax(), "product_name"],
    }

    return {
        "trade_date": trade_date,
        "all_products": all_df.to_dict("records"),
        "low_ticket": low_ticket.to_dict("records"),
        "high_iv": high_iv.to_dict("records"),
        "group_stats": group_stats,
        "summary": summary,
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }