# -*- coding: utf-8 -*-
"""快速验证：全市场IV扫描（仅测试1品种/交易所）"""
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

from scanner.data_source import (
    scan_shfe, scan_czce, scan_gfex, scan_dce, get_trade_date
)

td = get_trade_date(1)
print(f"最近交易日: {td}")

# SHFE: 只测铜期权
print("\n=== SHFE 铜期权 ===")
from scanner.data_source import fetch_shfe_iv, fetch_shfe_quotes
iv = fetch_shfe_iv("铜期权", td)
print(f"IV数据: {len(iv)}行, 列={iv.columns.tolist()}")
if not iv.empty:
    print(iv.head(3).to_string())

# CZCE: 只测白糖期权
print("\n=== CZCE 白糖期权 ===")
from scanner.data_source import fetch_czce_quotes
q = fetch_czce_quotes("白糖期权", td)
print(f"行情数据: {len(q)}行, 列={q.columns.tolist()}")
if not q.empty and "隐含波动率" in q.columns:
    print(q[["合约代码", "DELTA", "隐含波动率"]].head(3).to_string())

# GFEX: 工业硅
print("\n=== GFEX 工业硅 ===")
from scanner.data_source import fetch_gfex_iv
giv = fetch_gfex_iv("工业硅", td)
print(f"IV数据: {len(giv)}行, 列={giv.columns.tolist()}")
if not giv.empty:
    print(giv.head(3).to_string())

# DCE: 豆粕期权（降级路径）
print("\n=== DCE 豆粕期权（新浪降级）===")
from scanner.data_source import fetch_dce_contracts, fetch_dce_chain
contracts = fetch_dce_contracts("豆粕期权")
print(f"合约列表: {contracts}")
if contracts:
    chain = fetch_dce_chain("豆粕期权", contracts[0])
    print(f"期权链: {len(chain)}行, 列={chain.columns.tolist()}")

print("\n=== 完整扫描测试 ===")
from scanner.data_source import scan_all_iv
df = scan_all_iv(td)
if not df.empty:
    print(df[["product_name", "exchange", "iv", "iv_source", "volume", "open_interest"]].to_string())
else:
    print("扫描无结果")