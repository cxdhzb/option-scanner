# -*- coding: utf-8 -*-
"""
数据层：基于 AKShare 获取国内商品期权全市场行情与IV数据
覆盖交易所：上期所(SHFE)、郑商所(CZCE)、广期所(GFEX)、大商所(DCE-降级)

实测验证结论（2026-09-26）：
  SHFE: option_hist_shfe(行情,无IV) + option_vol_shfe(合约系列IV,小数口径)
  CZCE: option_hist_czce(合约级IV+DELTA,百分数口径) ← 最优数据源
  GFEX: option_vol_gfex(合约系列IV,百分数口径)
  DCE:  option_hist_dce 失败(官网WAF 412) → 降级用新浪合约表(行情无IV)
  EM:   全部连接断开
  Sina: option_commodity_contract_sina(合约列表) + option_commodity_contract_table_sina(期权链行情)
"""
import re
import time
import logging
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import numpy as np

logger = logging.getLogger("scanner.data")

# ═══════════════════════════════════════════════════════════════
# 常量：品种映射与交易所配置
# ═══════════════════════════════════════════════════════════════

CN2CODE = {
    "豆粕": "M", "玉米": "C", "白糖": "SR", "棉花": "CF", "菜籽粕": "RM",
    "棕榈油": "P", "生猪": "LH", "苹果": "AP", "红枣": "CJ", "花生": "PK",
    "豆一": "A", "豆二": "B", "PTA": "TA", "甲醇": "MA", "LPG": "PG",
    "橡胶": "RU", "塑料": "L", "PVC": "V", "PP": "PP", "乙二醇": "EG",
    "苯乙烯": "EB", "短纤": "PF", "纯碱": "SA", "玻璃": "FG", "原油": "SC",
    "燃料油": "FU", "沥青": "BU", "尿素": "UR", "对二甲苯": "PX", "烧碱": "SH",
    "铁矿石": "I", "螺纹钢": "RB", "热卷": "HC", "锰硅": "SM", "硅铁": "SF",
    "铜": "CU", "铝": "AL", "锌": "ZN", "镍": "NI", "锡": "SN",
    "氧化铝": "AO", "多晶硅": "PS", "黄金": "AU", "白银": "AG",
    "工业硅": "SI", "碳酸锂": "LC", "原木": "LG", "鸡蛋": "JD",
    "玉米淀粉": "CS", "瓶片": "BP", "不锈钢": "SS", "纸浆": "SP",
    "合成橡胶": "BR",
}

PRODUCT_GROUPS = {
    "农产品": ["豆粕", "玉米", "白糖", "棉花", "菜籽粕", "棕榈油", "生猪",
              "苹果", "红枣", "花生", "豆一", "豆二", "鸡蛋", "玉米淀粉"],
    "能化": ["PTA", "甲醇", "LPG", "橡胶", "塑料", "PVC", "PP", "乙二醇",
             "苯乙烯", "短纤", "纯碱", "玻璃", "原油", "燃料油", "沥青",
             "尿素", "对二甲苯", "烧碱", "纸浆", "合成橡胶"],
    "黑色": ["铁矿石", "螺纹钢", "热卷", "锰硅", "硅铁"],
    "有色": ["铜", "铝", "锌", "镍", "锡", "氧化铝", "多晶硅"],
    "贵金属": ["黄金", "白银"],
    "新能源": ["工业硅", "碳酸锂"],
}

SHFE_OPTION_PRODUCTS = [
    "铜期权", "黄金期权", "白银期权", "铝期权", "锌期权", "铅期权",
    "镍期权", "锡期权", "氧化铝期权", "螺纹钢期权", "热卷期权",
    "不锈钢期权", "橡胶期权", "燃料油期权", "原油期权",
    "沥青期权", "纸浆期权", "合成橡胶期权",
]

CZCE_OPTION_PRODUCTS = [
    "白糖期权", "棉花期权", "PTA期权", "甲醇期权", "菜籽粕期权",
    "菜籽油期权", "动力煤期权", "花生期权", "纯碱期权", "玻璃期权",
    "短纤期权", "锰硅期权", "硅铁期权", "尿素期权", "对二甲苯期权",
    "烧碱期权", "瓶片期权", "红枣期权", "苹果期权",
]

GFEX_OPTION_PRODUCTS = ["工业硅", "碳酸锂"]  # 不带"期权"后缀

DCE_SINA_PRODUCTS = [
    "豆粕期权", "玉米期权", "铁矿石期权", "液化石油气期权",
]

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _safe_call(func, retries: int = 3, wait: int = 3, **kwargs):
    """带重试的安全接口调用"""
    last_err = None
    for i in range(retries):
        try:
            result = func(**kwargs)
            if result is None or (hasattr(result, "empty") and result.empty):
                return pd.DataFrame() if isinstance(result, pd.DataFrame) else result
            return result
        except Exception as e:
            last_err = e
            logger.warning("接口 %s 第%d次失败: %s，%d秒后重试",
                           getattr(func, "__name__", str(func)), i + 1, e, wait)
            time.sleep(wait)
    logger.error("接口 %s 最终失败: %s",
                 getattr(func, "__name__", str(func)), last_err)
    return pd.DataFrame()


def extract_product_code(contract: str) -> str:
    """从合约代码提取品种代码，如 m2509-C-3200 -> M"""
    if not contract:
        return ""
    s = re.sub(r"[^A-Za-z]", "", str(contract)[:6])
    return s.upper() if s else ""


def _product_base_name(option_name: str) -> str:
    """去掉'期权'后缀：'铜期权' -> '铜'"""
    return option_name.replace("期权", "").strip()


def _classify_group(product_name: str) -> str:
    """品种名 → 板块分组"""
    base = _product_base_name(product_name)
    for group, names in PRODUCT_GROUPS.items():
        if base in names:
            return group
    return "其他"


def get_trade_date(offset_days: int = 1) -> str:
    """获取最近交易日（默认昨交易日，格式 YYYYMMDD）"""
    tool_df = _safe_call(ak.tool_trade_date_hist_sina)
    if not tool_df.empty and "trade_date" in tool_df.columns:
        dates = pd.to_datetime(tool_df["trade_date"]).dt.strftime("%Y%m%d").tolist()
        today = datetime.now().strftime("%Y%m%d")
        passed = [d for d in dates if d <= today]
        if passed:
            idx = max(0, len(passed) - offset_days)
            return passed[idx]
    d = datetime.now() - timedelta(days=offset_days)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


# ═══════════════════════════════════════════════════════════════
# 交易所适配器：SHFE（上期所）
# ═══════════════════════════════════════════════════════════════

def fetch_shfe_quotes(symbol: str, trade_date: str) -> pd.DataFrame:
    """上期所期权行情（无IV）。symbol如'铜期权'; trade_date如'20260924'"""
    df = _safe_call(ak.option_hist_shfe, symbol=symbol, trade_date=trade_date)
    if df.empty:
        return df
    if "合约代码" in df.columns:
        df = df[df["合约代码"].notna()].copy()
    return df


def fetch_shfe_iv(symbol: str, trade_date: str) -> pd.DataFrame:
    """上期所期权IV（合约系列级，小数→百分数）。过滤'小计'行"""
    df = _safe_call(ak.option_vol_shfe, symbol=symbol, trade_date=trade_date)
    if df.empty:
        return df
    series_col = next((c for c in ["合约系列", "合约代码", "系列"] if c in df.columns), None)
    if series_col:
        df = df[df[series_col].astype(str).str.match(r"^[a-zA-Z]+\d+", na=False)].copy()
    iv_col = next((c for c in ["隐含波动率", "隐波", "iv"] if c in df.columns), None)
    if iv_col:
        df["iv_pct"] = pd.to_numeric(df[iv_col], errors="coerce") * 100
    return df


def scan_shfe(trade_date: str) -> list[dict]:
    """扫描上期所全部期权品种IV"""
    results = []
    for prod_name in SHFE_OPTION_PRODUCTS:
        try:
            iv_df = fetch_shfe_iv(prod_name, trade_date)
            if iv_df.empty:
                logger.warning("SHFE %s 无IV数据", prod_name)
                continue
            vol_col = "成交量" if "成交量" in iv_df.columns else None
            if vol_col:
                iv_df[vol_col] = pd.to_numeric(iv_df[vol_col], errors="coerce")
                main_row = iv_df.loc[iv_df[vol_col].idxmax()]
            else:
                main_row = iv_df.iloc[0]
            base = _product_base_name(prod_name)
            results.append({
                "product_name": base, "product_code": CN2CODE.get(base, ""),
                "exchange": "SHFE", "group": _classify_group(prod_name),
                "iv": round(float(main_row.get("iv_pct", 0)), 2),
                "iv_source": "option_vol_shfe", "delta": None,
                "volume": int(pd.to_numeric(main_row.get("成交量", 0), errors="coerce")),
                "open_interest": int(pd.to_numeric(main_row.get("持仓量", 0), errors="coerce")),
                "trade_date": trade_date,
            })
        except Exception as e:
            logger.error("SHFE %s 扫描异常: %s", prod_name, e)
    return results


# ═══════════════════════════════════════════════════════════════
# 交易所适配器：CZCE（郑商所）—— 最优数据源（合约级IV+DELTA）
# ═══════════════════════════════════════════════════════════════

def fetch_czce_quotes(symbol: str, trade_date: str) -> pd.DataFrame:
    """郑商所期权行情（含合约级IV+DELTA，百分数口径）"""
    df = _safe_call(ak.option_hist_czce, symbol=symbol, trade_date=trade_date)
    if df.empty:
        return df
    if "合约代码" in df.columns:
        df = df[df["合约代码"].notna()].copy()
    return df


def scan_czce(trade_date: str) -> list[dict]:
    """扫描郑商所全部期权品种IV，用|DELTA-0.5|筛选平值合约"""
    results = []
    for prod_name in CZCE_OPTION_PRODUCTS:
        try:
            df = fetch_czce_quotes(prod_name, trade_date)
            if df.empty:
                logger.warning("CZCE %s 无数据", prod_name)
                continue
            delta_col = "DELTA" if "DELTA" in df.columns else None
            iv_col = "隐含波动率" if "隐含波动率" in df.columns else None
            if delta_col and iv_col:
                df[delta_col] = pd.to_numeric(df[delta_col], errors="coerce")
                df[iv_col] = pd.to_numeric(df[iv_col], errors="coerce")
                call_mask = df["合约代码"].astype(str).str.contains(r"C\d", na=False)
                calls = df[call_mask].copy() if call_mask.any() else df.copy()
                calls["delta_dist"] = (calls[delta_col] - 0.5).abs()
                atm = calls.loc[calls["delta_dist"].idxmin()]
                iv_val, delta_val = float(atm[iv_col]), float(atm[delta_col])
            elif iv_col:
                df[iv_col] = pd.to_numeric(df[iv_col], errors="coerce")
                vol_col = "成交量(手)" if "成交量(手)" in df.columns else "成交量"
                df[vol_col] = pd.to_numeric(df[vol_col], errors="coerce")
                atm = df.loc[df[vol_col].idxmax()]
                iv_val, delta_val = float(atm[iv_col]), None
            else:
                logger.warning("CZCE %s 无IV列", prod_name)
                continue
            base = _product_base_name(prod_name)
            vol_col = "成交量(手)" if "成交量(手)" in df.columns else "成交量"
            oi_col = "持仓量" if "持仓量" in df.columns else "持仓量"
            results.append({
                "product_name": base, "product_code": CN2CODE.get(base, ""),
                "exchange": "CZCE", "group": _classify_group(prod_name),
                "iv": round(iv_val, 2), "iv_source": "option_hist_czce",
                "delta": round(delta_val, 4) if delta_val is not None else None,
                "volume": int(pd.to_numeric(df[vol_col], errors="coerce").sum()),
                "open_interest": int(pd.to_numeric(df[oi_col], errors="coerce").sum()),
                "trade_date": trade_date,
            })
        except Exception as e:
            logger.error("CZCE %s 扫描异常: %s", prod_name, e)
    return results


# ═══════════════════════════════════════════════════════════════
# 交易所适配器：GFEX（广期所）
# ═══════════════════════════════════════════════════════════════

def fetch_gfex_iv(symbol: str, trade_date: str) -> pd.DataFrame:
    """广期所期权IV（合约系列级，百分数口径直接用）"""
    df = _safe_call(ak.option_vol_gfex, symbol=symbol, trade_date=trade_date)
    if df.empty:
        return df
    iv_col = next((c for c in ["隐含波动率", "隐波", "iv"] if c in df.columns), None)
    if iv_col:
        df = df.rename(columns={iv_col: "iv_pct"})
        df["iv_pct"] = pd.to_numeric(df["iv_pct"], errors="coerce")
    return df


def scan_gfex(trade_date: str) -> list[dict]:
    """扫描广期所全部期权品种IV"""
    results = []
    for prod_name in GFEX_OPTION_PRODUCTS:
        try:
            iv_df = fetch_gfex_iv(prod_name, trade_date)
            if iv_df.empty:
                logger.warning("GFEX %s 无IV数据", prod_name)
                continue
            vol_col = "成交量" if "成交量" in iv_df.columns else None
            if vol_col:
                iv_df[vol_col] = pd.to_numeric(iv_df[vol_col], errors="coerce")
                main_row = iv_df.loc[iv_df[vol_col].idxmax()]
            else:
                main_row = iv_df.iloc[0]
            results.append({
                "product_name": prod_name, "product_code": CN2CODE.get(prod_name, ""),
                "exchange": "GFEX", "group": _classify_group(prod_name),
                "iv": round(float(main_row.get("iv_pct", 0)), 2),
                "iv_source": "option_vol_gfex", "delta": None,
                "volume": int(pd.to_numeric(main_row.get("成交量", 0), errors="coerce")),
                "open_interest": int(pd.to_numeric(main_row.get("持仓量", 0), errors="coerce")),
                "trade_date": trade_date,
            })
        except Exception as e:
            logger.error("GFEX %s 扫描异常: %s", prod_name, e)
    return results


# ═══════════════════════════════════════════════════════════════
# 交易所适配器：DCE（大商所）—— 降级路径（新浪合约表，无IV）
# ═══════════════════════════════════════════════════════════════

def fetch_dce_contracts(symbol: str) -> list[str]:
    """获取大商所品种可用合约月份列表（新浪路径）"""
    df = _safe_call(ak.option_commodity_contract_sina, symbol=symbol)
    if df.empty:
        return []
    if "合约" in df.columns:
        return df["合约"].astype(str).tolist()
    return []


def fetch_dce_chain(symbol: str, contract: str) -> pd.DataFrame:
    """获取大商所品种某合约月份的期权链行情（新浪路径，无IV）"""
    df = _safe_call(ak.option_commodity_contract_table_sina,
                    symbol=symbol, contract=contract)
    return df


def scan_dce(trade_date: str) -> list[dict]:
    """扫描大商所品种（降级路径：新浪合约表，无IV，标记为数据缺失）"""
    results = []
    for prod_name in DCE_SINA_PRODUCTS:
        try:
            contracts = fetch_dce_contracts(prod_name)
            if not contracts:
                logger.warning("DCE %s 无合约数据", prod_name)
                continue
            main_contract = contracts[0]
            chain_df = fetch_dce_chain(prod_name, main_contract)
            if chain_df.empty:
                logger.warning("DCE %s %s 期权链为空", prod_name, main_contract)
                continue
            base = _product_base_name(prod_name)
            total_oi = 0
            for col in chain_df.columns:
                if "持仓量" in col:
                    total_oi += int(pd.to_numeric(chain_df[col], errors="coerce").sum())
            results.append({
                "product_name": base, "product_code": CN2CODE.get(base, ""),
                "exchange": "DCE", "group": _classify_group(prod_name),
                "iv": None, "iv_source": "sina_fallback(无IV)", "delta": None,
                "volume": 0, "open_interest": total_oi,
                "trade_date": trade_date, "contracts": contracts,
            })
        except Exception as e:
            logger.error("DCE %s 扫描异常: %s", prod_name, e)
    return results


# ═══════════════════════════════════════════════════════════════
# 统一扫描入口
# ═══════════════════════════════════════════════════════════════

def scan_all_iv(trade_date: str = None) -> pd.DataFrame:
    """
    全市场商品期权IV扫描（统一入口）。
    trade_date: 'YYYYMMDD'，默认最近交易日
    返回: DataFrame 含 product_name/product_code/exchange/group/iv/iv_source/delta/volume/open_interest/trade_date
    """
    if trade_date is None:
        trade_date = get_trade_date(1)
    logger.info("开始全市场IV扫描，交易日: %s", trade_date)

    all_results = []
    logger.info("扫描 SHFE (%d 品种)...", len(SHFE_OPTION_PRODUCTS))
    all_results.extend(scan_shfe(trade_date))
    logger.info("扫描 CZCE (%d 品种)...", len(CZCE_OPTION_PRODUCTS))
    all_results.extend(scan_czce(trade_date))
    logger.info("扫描 GFEX (%d 品种)...", len(GFEX_OPTION_PRODUCTS))
    all_results.extend(scan_gfex(trade_date))
    logger.info("扫描 DCE (%d 品种，降级路径)...", len(DCE_SINA_PRODUCTS))
    all_results.extend(scan_dce(trade_date))

    df = pd.DataFrame(all_results)
    if not df.empty:
        df = df.sort_values("iv", na_position="last").reset_index(drop=True)
        logger.info("扫描完成: %d 品种，%d 有IV，%d 无IV",
                     len(df), df["iv"].notna().sum(), df["iv"].isna().sum())
    else:
        logger.warning("全市场扫描无结果")
    return df


def fetch_product_detail(product_name: str, exchange: str,
                         trade_date: str = None) -> dict:
    """获取单个品种的详细数据（含期权链）"""
    if trade_date is None:
        trade_date = get_trade_date(1)

    if exchange == "SHFE":
        sym = f"{product_name}期权" if not product_name.endswith("期权") else product_name
        return {"iv_df": fetch_shfe_iv(sym, trade_date),
                "quotes_df": fetch_shfe_quotes(sym, trade_date),
                "trade_date": trade_date}
    elif exchange == "CZCE":
        sym = f"{product_name}期权" if not product_name.endswith("期权") else product_name
        qdf = fetch_czce_quotes(sym, trade_date)
        return {"iv_df": qdf, "quotes_df": qdf, "trade_date": trade_date}
    elif exchange == "GFEX":
        return {"iv_df": fetch_gfex_iv(product_name, trade_date),
                "quotes_df": pd.DataFrame(), "trade_date": trade_date}
    elif exchange == "DCE":
        sym = f"{product_name}期权" if not product_name.endswith("期权") else product_name
        contracts = fetch_dce_contracts(sym)
        qdf = fetch_dce_chain(sym, contracts[0]) if contracts else pd.DataFrame()
        return {"iv_df": pd.DataFrame(), "quotes_df": qdf, "trade_date": trade_date}
    return {"iv_df": pd.DataFrame(), "quotes_df": pd.DataFrame(), "trade_date": trade_date}