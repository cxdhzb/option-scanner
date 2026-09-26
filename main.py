# -*- coding: utf-8 -*-
"""
商品期权IV扫描器 - 三任务扫描系统主入口
任务一：全市场IV扫描与排序（含IV百分位）
任务二：十倍潜力合约筛选（蒙特卡洛模拟）
任务三：极高IV风险警示

用法: python main.py [--output PATH] [--trade-date YYYYMMDD] [--no-task2] [--no-task3]
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
    parser = argparse.ArgumentParser(description="商品期权IV扫描器（三任务系统）")
    parser.add_argument("--output", "-o", type=str, default=None, help="HTML报告输出路径")
    parser.add_argument("--trade-date", "-d", type=str, default=None, help="交易日 YYYYMMDD，默认最近交易日")
    parser.add_argument("--no-task2", action="store_true", help="禁用任务二（十倍合约筛选）")
    parser.add_argument("--no-task3", action="store_true", help="禁用任务三（极高IV警示）")
    parser.add_argument("--task1-only", action="store_true", help="仅运行任务一（全市场IV扫描）")
    args = parser.parse_args()

    trade_date = args.trade_date or get_trade_date()
    enable_task2 = not args.no_task2 and not args.task1_only
    enable_task3 = not args.no_task3 and not args.task1_only

    logger.info("=" * 60)
    logger.info("商品期权IV扫描器（三任务系统）启动")
    logger.info("交易日: %s", trade_date)
    logger.info("任务一: ✓  任务二: %s  任务三: %s",
                "✓" if enable_task2 else "✗", "✓" if enable_task3 else "✗")
    logger.info("=" * 60)

    # 生成报告数据（三任务整合）
    logger.info("[1/2] 扫描全市场数据并生成报告...")
    report_data = generate_scan_report_data(
        trade_date=trade_date,
        enable_task2=enable_task2,
        enable_task3=enable_task3,
    )
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
    if enable_task2:
        tc = report_data.get("ten_x_contracts", {}).get("summary", {})
        logger.info("十倍筛选: 筛选%d合约, 近月%d, 远月%d",
                     tc.get("total_screened", 0), tc.get("near_count", 0), tc.get("far_count", 0))
    if enable_task3:
        na = len(report_data.get("high_iv_alerts", []))
        logger.info("极高IV警示: %d 品种", na)

    # 渲染HTML
    logger.info("[2/2] 渲染HTML报告...")
    output_path = render_html_report(report_data, output_path=args.output)
    logger.info("报告已生成: %s", output_path)
    logger.info("=" * 60)
    logger.info("完成！")
    return output_path


if __name__ == "__main__":
    main()