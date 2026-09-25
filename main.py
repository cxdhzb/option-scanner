# -*- coding: utf-8 -*-
"""
商品期权IV扫描器 - 主入口
用法: python main.py [--output PATH] [--trade-date YYYYMMDD]
"""
import argparse
import logging
import sys
from pathlib import Path

# 将scanner包加入路径
sys.path.insert(0, str(Path(__file__).parent))

from scanner.data_source import get_trade_date
from scanner.iv_engine import generate_scan_report_data
from scanner.report import render_html_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def main():
    parser = argparse.ArgumentParser(description="商品期权IV扫描器")
    parser.add_argument("--output", "-o", type=str, default=None, help="HTML报告输出路径")
    parser.add_argument("--trade-date", "-d", type=str, default=None, help="交易日 YYYYMMDD，默认最近交易日")
    args = parser.parse_args()

    trade_date = args.trade_date or get_trade_date()
    logger.info("=" * 60)
    logger.info("商品期权IV扫描器 启动")
    logger.info("交易日: %s", trade_date)
    logger.info("=" * 60)

    # 1+2. 生成报告数据（内部调用scan_all_iv）
    logger.info("[1/2] 扫描全市场IV数据并生成报告数据...")
    report_data = generate_scan_report_data(trade_date=trade_date)
    n = report_data["summary"]["total_products"]
    logger.info("扫描完成: %d 品种", n)
    summary = report_data["summary"]
    logger.info(
        "汇总: %d品种, %d有IV, %d无IV, IV中位数%.1f%%",
        summary["total_products"],
        summary["iv_available"],
        summary["iv_missing"],
        summary["iv_median"],
    )

    # 2. 渲染HTML
    logger.info("[2/2] 渲染HTML报告...")
    output_path = render_html_report(report_data, output_path=args.output)
    logger.info("报告已生成: %s", output_path)
    logger.info("=" * 60)
    logger.info("完成！")
    return output_path


if __name__ == "__main__":
    main()