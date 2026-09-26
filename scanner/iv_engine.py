# -*- coding: utf-8 -*-
"""
IV引擎与扫描层：三任务扫描系统
  任务一：全市场IV扫描与排序（含IV百分位）
  任务二：十倍潜力合约筛选（蒙特卡洛模拟）
  任务三：极高IV风险警示

核心理论（来自《怎么找到翻十倍的期权》）：
  - "低票价"：当前IV处于历史低位（IV百分位 < 30%）
  - "大颠簸"：持有期RV显著高于建仓IV（IV-RV差值为负）
  - 翻倍潜力 = 低票价 × 大颠簸
  - 十倍概率：票价(IV)与颠簸(RV)的落差决定赔率
  - Levy稳定分布(alpha=1.8)比正态厚尾，十倍概率从2.7%→6.6%
"""
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.stats import levy_stable

from .data_source import (
    scan_all_iv, fetch_product_detail, get_trade_date,
    fetch_all_contract_chains, calc_iv_percentile_from_history,
    load_iv_history, update_iv_history,
    CN2CODE, PRODUCT_GROUPS, SHFE_OPTION_PRODUCTS, CZCE_OPTION_PRODUCTS,
    GFEX_OPTION_PRODUCTS, DCE_SINA_PRODUCTS, NEAR_TERM_CUTOFF,
)

logger = logging.getLogger("scanner.engine")

# ═══════════════════════════════════════════════════════════════
# IV百分位计算（历史缓存方式，见data_source.py）
# ═══════════════════════════════════════════════════════════════

def calc_iv_percentile(current_iv: float, hist_ivs: list[float]) -> float:
    """计算当前IV在历史序列中的百分位排名（0-100）

    百分位 = 历史中低于当前IV的天数 / 总天数 × 100
    """
    if not hist_ivs or current_iv is None or np.isnan(current_iv):
        return np.nan
    arr = np.array(hist_ivs)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return np.nan
    rank = float((arr < current_iv).sum() / len(arr) * 100)
    return round(rank, 1)


def calc_iv_rank(current_iv: float, hist_ivs: list[float]) -> float:
    """IV Rank: (当前IV - 最低IV) / (最高IV - 最低IV) × 100"""
    if not hist_ivs or current_iv is None or np.isnan(current_iv):
        return np.nan
    arr = np.array(hist_ivs)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return np.nan
    iv_min, iv_max = arr.min(), arr.max()
    if iv_max == iv_min:
        return 50.0
    rank = float((current_iv - iv_min) / (iv_max - iv_min) * 100)
    return round(rank, 1)


# ═══════════════════════════════════════════════════════════════
# 蒙特卡洛模拟：十倍概率计算
# ═══════════════════════════════════════════════════════════════

# 默认参数
MC_SIMULATIONS = 20000    # 模拟路径数
RISK_FREE_RATE = 0.025    # 无风险利率


def mc_10x_normal(S: float, K: float, T: float, sigma: float,
                  r: float = RISK_FREE_RATE, N: int = MC_SIMULATIONS) -> tuple:
    """正态分布蒙特卡洛：计算看涨期权十倍概率

    S: 标的当前价, K: 行权价, T: 到期时间(年), sigma: IV(小数)
    返回: (理论权利金, 十倍概率)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return (0.0, 0.0)
    Z = np.random.standard_normal(N)
    ST = S * np.exp((r - 0.5 * sigma ** 2) * T + sigma * np.sqrt(T) * Z)
    payoff = np.maximum(ST - K, 0)
    premium = float(payoff.mean() * np.exp(-r * T))
    if premium <= 0:
        return (0.0, 0.0)
    prob = float((payoff >= 10 * premium).mean())
    return (round(premium, 4), round(prob, 4))


def mc_10x_levy(S: float, K: float, T: float, sigma: float,
                r: float = RISK_FREE_RATE, N: int = MC_SIMULATIONS,
                alpha: float = 1.8) -> tuple:
    """Levy稳定分布蒙特卡洛：计算看涨期权十倍概率

    alpha=1.8: 比正态(2.0)厚尾，更符合商品价格分布
    返回: (理论权利金, 十倍概率)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return (0.0, 0.0)
    try:
        Z = levy_stable.rvs(alpha, 0, scale=1, size=N)
        # 标准化：使方差匹配sigma^2*T
        # levy_stable的方差：对alpha<2，variance = 2*gamma^2 / (2-alpha)
        # 这里scale=1即gamma=1，所以variance = 2/(2-alpha)
        levy_var = 2.0 / (2.0 - alpha)  # alpha=1.8时 variance=10.0
        if levy_var <= 0 or np.isinf(levy_var):
            return mc_10x_normal(S, K, T, sigma, r, N)
        c = sigma * np.sqrt(T) / np.sqrt(levy_var)
        # 截断极端值避免数值溢出
        Z = np.clip(Z, -50, 50)
        ST = S * np.exp((r - 0.5 * sigma ** 2) * T + c * Z)
        ST = np.maximum(ST, 0)
        payoff = np.maximum(ST - K, 0)
        premium = float(payoff.mean() * np.exp(-r * T))
        if premium <= 0:
            return (0.0, 0.0)
        prob = float((payoff >= 10 * premium).mean())
        return (round(premium, 4), round(prob, 4))
    except Exception as e:
        logger.warning("Levy模拟失败，回退正态: %s", e)
        return mc_10x_normal(S, K, T, sigma, r, N)


# ═══════════════════════════════════════════════════════════════
# 任务二：十倍潜力合约筛选
# ═══════════════════════════════════════════════════════════════

# 行权价甜区参数
NEAR_OTM_MIN = 0.05   # 近月虚值5%
NEAR_OTM_MAX = 0.10   # 近月虚值10%
FAR_OTM_MIN = 0.12    # 远月虚值12%
FAR_OTM_MAX = 0.18    # 远月虚值18%

# Delta目标范围
NEAR_DELTA_MIN = 0.20  # 近月Delta 0.20~0.35
NEAR_DELTA_MAX = 0.35
FAR_DELTA_MIN = 0.25   # 远月Delta 0.25~0.40
FAR_DELTA_MAX = 0.40

# 筛选阈值
MIN_PREMIUM = 5.0      # 最低权利金（元）
MAX_BID_ASK_SPREAD = 50.0  # 最大买卖价差（元）
TEN_X_PROB_THRESHOLD = 0.02  # 十倍概率最低阈值(2%)


def _estimate_underlying_price(contracts: list[dict]) -> float | None:
    """从合约链估算标的当前价格（取ATM合约行权价中值）"""
    if not contracts:
        return None
    # 优先用Delta最接近0.5的Call合约
    calls = [c for c in contracts if c.get("option_type") == "call" and c.get("delta") is not None]
    if calls:
        calls_sorted = sorted(calls, key=lambda c: abs(c["delta"] - 0.5))
        return calls_sorted[0].get("strike")
    # 回退：取所有Call行权价中值
    call_strikes = [c["strike"] for c in contracts if c.get("option_type") == "call" and c.get("strike", 0) > 0]
    if call_strikes:
        return float(np.median(call_strikes))
    return None


def screen_10x_contracts(trade_date: str = None, iv_df: pd.DataFrame = None) -> dict:
    """十倍潜力合约筛选（任务二核心入口）

    筛选逻辑：
    1. 获取全市场合约级数据
    2. 按近月/远月分类
    3. 筛选虚值甜区（近月5%~10%, 远月12%~18%）
    4. 筛选Delta范围（近月0.20~0.35, 远月0.25~0.40）
    5. 蒙特卡洛模拟计算十倍概率
    6. 按十倍概率评分排序

    参数:
        trade_date: 交易日
        iv_df: 已有的IV数据DataFrame（避免重复扫描）
    返回: dict 含 near_term, far_term, summary
    """
    if trade_date is None:
        trade_date = get_trade_date(1)

    logger.info("=" * 40)
    logger.info("任务二：十倍潜力合约筛选")
    logger.info("=" * 40)

    # 获取合约级数据
    all_contracts = fetch_all_contract_chains(trade_date)
    if not all_contracts:
        logger.warning("无合约级数据，跳过十倍筛选")
        return {"near_term": [], "far_term": [], "summary": {"total_screened": 0, "near_count": 0, "far_count": 0}}

    # 按品种分组
    product_groups = {}
    for c in all_contracts:
        key = c["product_name"]
        if key not in product_groups:
            product_groups[key] = []
        product_groups[key].append(c)

    # 获取全市场IV数据（用于低票价筛选），优先使用传入的数据
    if iv_df is None:
        iv_df = scan_all_iv(trade_date, calc_percentile=True)
    low_iv_products = set()
    if not iv_df.empty:
        low_iv_mask = iv_df["iv"].notna() & (iv_df["iv"] < LOW_IV_THRESHOLD)
        low_iv_products = set(iv_df[low_iv_mask]["product_name"].tolist())

    near_term_results = []
    far_term_results = []

    for product_name, contracts in product_groups.items():
        # 估算标的当前价格
        S = _estimate_underlying_price(contracts)
        if S is None or S <= 0:
            continue

        # 获取该品种的IV（用于蒙特卡洛）
        product_iv = None
        if not iv_df.empty:
            mask = iv_df["product_name"] == product_name
            if mask.any():
                product_iv = float(iv_df.loc[mask, "iv"].iloc[0])

        for c in contracts:
            # 只看看涨期权
            if c.get("option_type") != "call":
                continue
            # 必须有IV
            if c.get("iv") is None or c["iv"] <= 0:
                continue
            # 必须有行权价
            if c.get("strike", 0) <= 0:
                continue
            # 过滤已到期
            if c.get("days_to_expiry", -1) <= 0:
                continue

            K = c["strike"]
            sigma = c["iv"] / 100.0  # IV百分数转小数
            T = c["days_to_expiry"] / 365.0  # 天转年
            term = c.get("term", "远月")
            moneyness = (K - S) / S  # 虚值程度

            # 按近远月筛选虚值甜区
            if term == "近月":
                if not (NEAR_OTM_MIN <= moneyness <= NEAR_OTM_MAX):
                    continue
                # Delta筛选（如果有）
                if c.get("delta") is not None:
                    if not (NEAR_DELTA_MIN <= c["delta"] <= NEAR_DELTA_MAX):
                        continue
            else:  # 远月
                if not (FAR_OTM_MIN <= moneyness <= FAR_OTM_MAX):
                    continue
                if c.get("delta") is not None:
                    if not (FAR_DELTA_MIN <= c["delta"] <= FAR_DELTA_MAX):
                        continue

            # 权利金筛选
            if c.get("premium") is not None and c["premium"] < MIN_PREMIUM:
                continue

            # 买卖价差筛选
            if c.get("bid_ask_spread") is not None and c["bid_ask_spread"] > MAX_BID_ASK_SPREAD:
                continue

            # 蒙特卡洛模拟
            try:
                premium_normal, prob_normal = mc_10x_normal(S, K, T, sigma)
                premium_levy, prob_levy = mc_10x_levy(S, K, T, sigma)
            except Exception as e:
                logger.warning("蒙特卡洛模拟失败 %s: %s", c["contract_code"], e)
                continue

            # 十倍概率阈值筛选
            if prob_levy < TEN_X_PROB_THRESHOLD:
                continue

            # 低票价加分
            is_low_ticket = product_name in low_iv_products

            result = {
                "contract_code": c["contract_code"],
                "product_name": product_name,
                "product_code": c.get("product_code", ""),
                "exchange": c["exchange"],
                "option_type": "call",
                "strike": K,
                "underlying_price": round(S, 2),
                "moneyness": round(moneyness * 100, 1),
                "days_to_expiry": c["days_to_expiry"],
                "term": term,
                "iv": c["iv"],
                "delta": c.get("delta"),
                "premium": c.get("premium"),
                "premium_mc_normal": premium_normal,
                "premium_mc_levy": premium_levy,
                "prob_10x_normal": prob_normal,
                "prob_10x_levy": prob_levy,
                "is_low_ticket": is_low_ticket,
                "volume": c.get("volume", 0),
                "open_interest": c.get("open_interest", 0),
                "trade_date": trade_date,
            }

            if term == "近月":
                near_term_results.append(result)
            else:
                far_term_results.append(result)

    # 按十倍概率排序
    near_term_results.sort(key=lambda x: x["prob_10x_levy"], reverse=True)
    far_term_results.sort(key=lambda x: x["prob_10x_levy"], reverse=True)

    # 限制数量
    near_term_results = near_term_results[:30]
    far_term_results = far_term_results[:30]

    summary = {
        "total_screened": len(all_contracts),
        "near_count": len(near_term_results),
        "far_count": len(far_term_results),
        "low_ticket_count": sum(1 for r in near_term_results + far_term_results if r["is_low_ticket"]),
    }

    logger.info("十倍筛选完成: 筛选%d合约, 近月%d, 远月%d",
                summary["total_screened"], summary["near_count"], summary["far_count"])

    return {"near_term": near_term_results, "far_term": far_term_results, "summary": summary}


# ═══════════════════════════════════════════════════════════════
# 任务三：极高IV风险警示
# ═══════════════════════════════════════════════════════════════

# 极高IV阈值
IV_PERCENTILE_EXTREME = 80   # IV百分位 ≥ 80% 视为极高
IV_PREMIUM_THRESHOLD = 1.5   # IV溢价 > 1.5倍中位数视为异常


def scan_high_iv_alerts(trade_date: str = None, iv_df: pd.DataFrame = None) -> list[dict]:
    """极高IV风险警示（任务三核心入口）

    筛选条件：
    1. IV百分位 ≥ 80%（历史高位）
    2. IV溢价 > 中位数的1.5倍
    3. 标记顶部反转信号

    参数:
        trade_date: 交易日
        iv_df: 已有的IV数据DataFrame（避免重复扫描）
    返回: list[dict] 按IV百分位降序
    """
    if trade_date is None:
        trade_date = get_trade_date(1)

    logger.info("=" * 40)
    logger.info("任务三：极高IV风险警示")
    logger.info("=" * 40)

    # 获取全市场IV数据（含百分位），优先使用传入的数据
    df = iv_df if iv_df is not None else scan_all_iv(trade_date, calc_percentile=True)
    if df is None or (hasattr(df, 'empty') and df.empty):
        return []

    df_iv = df[df["iv"].notna()].copy()

    # 计算IV中位数和溢价
    iv_median = float(df_iv["iv"].median())
    df_iv["iv_premium_ratio"] = round(df_iv["iv"] / iv_median, 2) if iv_median > 0 else np.nan

    # 筛选极高IV品种
    alerts = []
    for _, row in df_iv.iterrows():
        iv_pct = row.get("iv_percentile")
        iv_premium = row.get("iv_premium_ratio")

        # 条件1：IV百分位 ≥ 80%
        high_percentile = iv_pct is not None and not np.isnan(iv_pct) and iv_pct >= IV_PERCENTILE_EXTREME
        # 条件2：IV溢价 > 1.5倍中位数
        high_premium = iv_premium is not None and not np.isnan(iv_premium) and iv_premium >= IV_PREMIUM_THRESHOLD
        # 条件3：绝对IV > 50%
        very_high_iv = row["iv"] > 50

        # 至少满足一个条件才警示
        if not (high_percentile or high_premium or very_high_iv):
            continue

        # 顶部反转信号：IV极高+持仓量下降（如有数据）
        reversal_signal = False
        if high_percentile and very_high_iv:
            reversal_signal = True

        # 风险等级
        risk_level = "高"
        if high_percentile and high_premium and very_high_iv:
            risk_level = "极高"
        elif high_percentile and very_high_iv:
            risk_level = "极高"
        elif high_percentile or very_high_iv:
            risk_level = "高"

        alerts.append({
            "product_name": row["product_name"],
            "product_code": row.get("product_code", ""),
            "exchange": row["exchange"],
            "group": row.get("group", ""),
            "iv": row["iv"],
            "iv_percentile": iv_pct if iv_pct is not None and not np.isnan(iv_pct) else None,
            "iv_premium_ratio": iv_premium if iv_premium is not None and not np.isnan(iv_premium) else None,
            "iv_median": round(iv_median, 2),
            "volume": row.get("volume", 0),
            "open_interest": row.get("open_interest", 0),
            "high_percentile": high_percentile,
            "high_premium": high_premium,
            "very_high_iv": very_high_iv,
            "reversal_signal": reversal_signal,
            "risk_level": risk_level,
            "trade_date": trade_date,
        })

    # 按风险等级和IV百分位排序
    risk_order = {"极高": 0, "高": 1}
    alerts.sort(key=lambda x: (risk_order.get(x["risk_level"], 9),
                               -(x.get("iv_percentile") or 0)))

    logger.info("极高IV警示: %d 品种", len(alerts))
    return alerts


# ═══════════════════════════════════════════════════════════════
# 扫描层：低票价品种筛选
# ═══════════════════════════════════════════════════════════════

# 低票价筛选阈值
LOW_IV_THRESHOLD = 25.0   # IV < 25% 视为低票价候选
IV_PERCENTILE_LOW = 30    # IV百分位 < 30% 视为历史低位

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


def generate_scan_report_data(trade_date: str = None, enable_task2: bool = True,
                                enable_task3: bool = True) -> dict:
    """
    生成完整扫描报告数据（三任务整合，供Jinja2模板渲染）。

    任务一：全市场IV扫描与排序（含IV百分位）
    任务二：十倍潜力合约筛选（蒙特卡洛模拟）
    任务三：极高IV风险警示

    返回: dict 含 trade_date, all_products, low_ticket, high_iv_alerts,
                ten_x_contracts, group_stats, summary, scan_time
    """
    if trade_date is None:
        trade_date = get_trade_date(1)

    # ═══ 任务一：全市场IV扫描与排序 ═══
    logger.info("=" * 40)
    logger.info("任务一：全市场IV扫描与排序")
    logger.info("=" * 40)

    all_df = scan_all_iv(trade_date, calc_percentile=True)
    if all_df.empty:
        return {"trade_date": trade_date, "all_products": [],
                "low_ticket": [], "high_iv_alerts": [],
                "ten_x_contracts": {"near_term": [], "far_term": [], "summary": {}},
                "group_stats": [], "summary": {},
                "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # 有IV数据的品种
    df_iv = all_df[all_df["iv"].notna()].copy()

    # 低票价品种（IV < 阈值 且 IV百分位 < 30%）
    low_ticket = df_iv[df_iv["iv"] < LOW_IV_THRESHOLD].copy()
    low_ticket = low_ticket.sort_values("iv").reset_index(drop=True)

    # 高波动品种（潜在卖方机会/风险警示）
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
    iv_median = round(float(df_iv["iv"].median()), 2)
    summary = {
        "total_products": len(all_df),
        "iv_available": len(df_iv),
        "iv_missing": len(all_df) - len(df_iv),
        "low_ticket_count": len(low_ticket),
        "high_iv_count": len(high_iv),
        "iv_median": iv_median,
        "iv_mean": round(float(df_iv["iv"].mean()), 2),
        "iv_min": round(float(df_iv["iv"].min()), 2),
        "iv_min_product": df_iv.loc[df_iv["iv"].idxmin(), "product_name"],
        "iv_max": round(float(df_iv["iv"].max()), 2),
        "iv_max_product": df_iv.loc[df_iv["iv"].idxmax(), "product_name"],
    }

    # ═══ 任务二：十倍潜力合约筛选 ═══
    ten_x_contracts = {"near_term": [], "far_term": [], "summary": {}}
    if enable_task2:
        try:
            ten_x_contracts = screen_10x_contracts(trade_date, iv_df=all_df)
        except Exception as e:
            logger.error("任务二执行失败: %s", e, exc_info=True)

    # ═══ 任务三：极高IV风险警示 ═══
    high_iv_alerts = []
    if enable_task3:
        try:
            high_iv_alerts = scan_high_iv_alerts(trade_date, iv_df=all_df)
        except Exception as e:
            logger.error("任务三执行失败: %s", e, exc_info=True)

    return {
        "trade_date": trade_date,
        "all_products": all_df.to_dict("records"),
        "low_ticket": low_ticket.to_dict("records"),
        "high_iv": high_iv.to_dict("records"),
        "ten_x_contracts": ten_x_contracts,
        "high_iv_alerts": high_iv_alerts,
        "group_stats": group_stats,
        "summary": summary,
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }