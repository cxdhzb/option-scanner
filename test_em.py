# -*- coding: utf-8 -*-
"""测试：获取合约月份列表 + option_comm_symbol"""
import akshare as ak
import inspect

# 1. option_commodity_contract_sina（不带table）—— 可能返回合约列表
print("=== option_commodity_contract_sina signature ===")
try:
    print(inspect.signature(ak.option_commodity_contract_sina))
    src = inspect.getsource(ak.option_commodity_contract_sina)
    print(src[:800])
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:200])

# 2. option_comm_symbol —— 可能返回品种代码映射
print("\n=== option_comm_symbol ===")
try:
    df = ak.option_comm_symbol()
    print(type(df))
    if hasattr(df, 'columns'):
        print(df.columns.tolist())
        print(df.head(10).to_string())
        print("rows:", len(df))
    else:
        print(df)
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:200])

# 3. option_commodity_hist_sina —— 之前失败，再试一次看签名
print("\n=== option_commodity_hist_sina signature ===")
try:
    print(inspect.signature(ak.option_commodity_hist_sina))
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:200])

# 4. 测试 option_commodity_contract_sina 调用
print("\n=== option_commodity_contract_sina(豆粕期权) ===")
try:
    df4 = ak.option_commodity_contract_sina(symbol="豆粕期权")
    print(df4.columns.tolist())
    print(df4.head(10).to_string())
    print("rows:", len(df4))
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:300])