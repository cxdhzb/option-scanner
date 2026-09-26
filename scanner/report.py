# -*- coding: utf-8 -*-
"""
报告层：基于 Jinja2 渲染暗色Ember主题 HTML 报告
"""
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger("scanner.report")

# 暗色Ember主题色板（来自用户提供的模拟代码）
COLORS = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "ink": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#ff6a00",
    "danger": "#b3212c",
    "warning": "#ffd166",
    "success": "#3fb950",
    "border": "#30363d",
    "gradient": ["#161b22", "#5b1520", "#b3212c", "#ff6a00", "#ffd166"],
}

REPORT_DIR = Path(__file__).parent.parent / "reports"
TEMPLATE_DIR = Path(__file__).parent / "templates"


def _iv_color(iv: float | None) -> str:
    """IV值 → 颜色（低=绿/中=橙/高=红）"""
    if iv is None:
        return COLORS["muted"]
    if iv < 15:
        return COLORS["success"]
    if iv < 25:
        return "#3fb950"
    if iv < 35:
        return COLORS["accent"]
    if iv < 50:
        return COLORS["warning"]
    return COLORS["danger"]


def _iv_bar_width(iv: float | None, max_iv: float = 80.0) -> float:
    """IV值 → 进度条宽度百分比"""
    if iv is None:
        return 0
    return min(iv / max_iv * 100, 100)


def _clean_nan(obj):
    """递归清理数据中的nan值，转为None（Jinja2不支持is nan测试）"""
    import math
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


def render_html_report(data: dict, output_path: str | Path = None) -> str:
    """
    渲染HTML报告。
    data: generate_scan_report_data() 的返回值
    output_path: 输出文件路径，默认 reports/index.html
    """
    if output_path is None:
        output_path = REPORT_DIR / "index.html"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 清理nan值，Jinja2不支持is nan测试
    data = _clean_nan(data)

    # 确保模板目录存在，始终使用最新模板
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    template_file = TEMPLATE_DIR / "report.html"
    _create_default_template(template_file)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["iv_color"] = _iv_color
    env.filters["iv_bar"] = _iv_bar_width

    template = env.get_template("report.html")
    html = template.render(
        **data,
        colors=COLORS,
        low_iv_threshold=25.0,
    )

    output_path.write_text(html, encoding="utf-8")
    logger.info("报告已生成: %s", output_path)
    return str(output_path)


def _create_default_template(path: Path):
    """创建默认Jinja2模板（暗色Ember主题）"""
    path.write_text(TEMPLATE_HTML, encoding="utf-8")


TEMPLATE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>商品期权IV扫描报告 - {{ trade_date }}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: {{ colors.bg }}; color: {{ colors.ink }}; font-family: -apple-system, 'Segoe UI', sans-serif; line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }
h1 { font-size: 1.8em; margin-bottom: 8px; color: {{ colors.accent }}; }
h2 { font-size: 1.3em; margin: 24px 0 12px; color: {{ colors.ink }}; border-bottom: 1px solid {{ colors.border }}; padding-bottom: 6px; }
.subtitle { color: {{ colors.muted }}; font-size: 0.9em; margin-bottom: 20px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-card { background: {{ colors.panel }}; border: 1px solid {{ colors.border }}; border-radius: 8px; padding: 16px; }
.stat-card .label { color: {{ colors.muted }}; font-size: 0.85em; }
.stat-card .value { font-size: 1.6em; font-weight: 700; color: {{ colors.accent }}; }
.stat-card .sub { color: {{ colors.muted }}; font-size: 0.8em; }
table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
th { background: {{ colors.panel }}; color: {{ colors.muted }}; font-size: 0.85em; text-transform: uppercase; padding: 10px 12px; text-align: left; border-bottom: 2px solid {{ colors.border }}; }
td { padding: 8px 12px; border-bottom: 1px solid {{ colors.border }}; font-size: 0.9em; }
tr:hover { background: {{ colors.panel }}; }
.iv-cell { font-weight: 700; font-size: 1.05em; }
.iv-bar { height: 4px; border-radius: 2px; margin-top: 2px; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 600; }
.tag-low { background: rgba(63,185,80,0.15); color: {{ colors.success }}; }
.tag-high { background: rgba(179,33,44,0.15); color: {{ colors.danger }}; }
.tag-mid { background: rgba(255,106,0,0.15); color: {{ colors.accent }}; }
.group-section { margin-bottom: 16px; }
.group-header { color: {{ colors.muted }}; font-size: 0.9em; margin-bottom: 6px; }
footer { text-align: center; color: {{ colors.muted }}; font-size: 0.8em; margin-top: 40px; padding: 20px; border-top: 1px solid {{ colors.border }}; }
.warning-box { background: rgba(179,33,44,0.1); border: 1px solid {{ colors.danger }}; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; color: {{ colors.warning }}; font-size: 0.85em; }
h3 { font-size: 1.1em; margin: 16px 0 8px; color: {{ colors.ink }}; }
.risk-extreme { background: rgba(179,33,44,0.2); border-left: 3px solid {{ colors.danger }}; }
.risk-high { background: rgba(255,106,0,0.1); border-left: 3px solid {{ colors.accent }}; }
</style>
</head>
<body>
<div class="container">
<h1>商品期权IV扫描报告</h1>
<p class="subtitle">交易日: {{ trade_date }} | 扫描时间: {{ scan_time }} | 数据仅供研究参考，不构成投资建议</p>

<div class="warning-box">
⚠️ 本报告数据来自公开交易所接口，仅供学术研究参考，不构成任何投资建议。期权交易具有高风险，请谨慎决策。
</div>

<h2>市场概览</h2>
<div class="stats-grid">
<div class="stat-card">
  <div class="label">扫描品种</div>
  <div class="value">{{ summary.total_products }}</div>
  <div class="sub">有IV: {{ summary.iv_available }} | 无IV: {{ summary.iv_missing }}</div>
</div>
<div class="stat-card">
  <div class="label">IV中位数</div>
  <div class="value">{{ summary.iv_median }}%</div>
  <div class="sub">均值: {{ summary.iv_mean }}%</div>
</div>
<div class="stat-card">
  <div class="label">最低IV</div>
  <div class="value" style="color: {{ colors.success }}">{{ summary.iv_min }}%</div>
  <div class="sub">{{ summary.iv_min_product }}</div>
</div>
<div class="stat-card">
  <div class="label">最高IV</div>
  <div class="value" style="color: {{ colors.danger }}">{{ summary.iv_max }}%</div>
  <div class="sub">{{ summary.iv_max_product }}</div>
</div>
<div class="stat-card">
  <div class="label">低票价品种</div>
  <div class="value" style="color: {{ colors.success }}">{{ summary.low_ticket_count }}</div>
  <div class="sub">IV < {{ low_iv_threshold }}%</div>
</div>
<div class="stat-card">
  <div class="label">高波动品种</div>
  <div class="value" style="color: {{ colors.danger }}">{{ summary.high_iv_count }}</div>
  <div class="sub">IV > 50%</div>
</div>
{% if ten_x_contracts and ten_x_contracts.summary %}
<div class="stat-card">
  <div class="label">十倍候选合约</div>
  <div class="value" style="color: {{ colors.accent }}">{{ ten_x_contracts.summary.near_count + ten_x_contracts.summary.far_count }}</div>
  <div class="sub">近月{{ ten_x_contracts.summary.near_count }} / 远月{{ ten_x_contracts.summary.far_count }}</div>
</div>
{% endif %}
{% if high_iv_alerts %}
<div class="stat-card">
  <div class="label">极高IV警示</div>
  <div class="value" style="color: {{ colors.danger }}">{{ high_iv_alerts | length }}</div>
  <div class="sub">{% set extreme_count = high_iv_alerts | selectattr('risk_level', 'equalto', '极高') | list | length %}极高{{ extreme_count }} / 高{{ high_iv_alerts | length - extreme_count }}</div>
</div>
{% endif %}
</div>

<h2>低票价品种（IV < {{ low_iv_threshold }}%）</h2>
<p style="color: {{ colors.muted }}; font-size: 0.85em; margin-bottom: 8px;">
💡 低IV = "低票价"：期权权利金便宜，买方建仓成本低，若后续RV飙升则收益可观
</p>
<table>
<thead><tr><th>#</th><th>品种</th><th>交易所</th><th>板块</th><th>IV(%)</th><th>IV百分位</th><th>IV来源</th><th>成交量</th><th>持仓量</th></tr></thead>
<tbody>
{% for p in low_ticket %}
<tr>
  <td>{{ loop.index }}</td>
  <td><strong>{{ p.product_name }}</strong></td>
  <td>{{ p.exchange }}</td>
  <td>{{ p.group }}</td>
  <td class="iv-cell" style="color: {{ p.iv | iv_color }}">{{ p.iv | round(2) }}%</td>
  <td>{% if p.iv_percentile is not none %}<span style="color: {% if p.iv_percentile < 30 %}{{ colors.success }}{% elif p.iv_percentile > 70 %}{{ colors.danger }}{% else %}{{ colors.warning }}{% endif %}">{{ p.iv_percentile }}%</span>{% else %}-{% endif %}</td>
  <td><span style="font-size:0.8em;color:{{ colors.muted }}">{{ p.iv_source }}</span></td>
  <td>{{ "{:,}".format(p.volume) if p.volume else "-" }}</td>
  <td>{{ "{:,}".format(p.open_interest) if p.open_interest else "-" }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<h2>全品种IV排名</h2>
<table>
<thead><tr><th>#</th><th>品种</th><th>交易所</th><th>板块</th><th>IV(%)</th><th>IV百分位</th><th>IV柱状图</th><th>成交量</th><th>持仓量</th></tr></thead>
<tbody>
{% for p in all_products %}
{% if p.iv is not none %}
<tr>
  <td>{{ loop.index }}</td>
  <td><strong>{{ p.product_name }}</strong></td>
  <td>{{ p.exchange }}</td>
  <td>{{ p.group }}</td>
  <td class="iv-cell" style="color: {{ p.iv | iv_color }}">{{ p.iv | round(2) }}%</td>
  <td>{% if p.iv_percentile is not none %}<span style="color: {% if p.iv_percentile < 30 %}{{ colors.success }}{% elif p.iv_percentile > 70 %}{{ colors.danger }}{% else %}{{ colors.warning }}{% endif %}">{{ p.iv_percentile }}%</span>{% else %}-{% endif %}</td>
  <td>
    <div class="iv-bar" style="width: {{ p.iv | iv_bar }}%; background: {{ p.iv | iv_color }}"></div>
  </td>
  <td>{{ "{:,}".format(p.volume) if p.volume else "-" }}</td>
  <td>{{ "{:,}".format(p.open_interest) if p.open_interest else "-" }}</td>
</tr>
{% endif %}
{% endfor %}
</tbody>
</table>

<h2>板块统计</h2>
<table>
<thead><tr><th>板块</th><th>品种数</th><th>平均IV</th><th>最低IV</th><th>最高IV</th><th>最低品种</th><th>最高品种</th></tr></thead>
<tbody>
{% for g in group_stats %}
<tr>
  <td><strong>{{ g.group }}</strong></td>
  <td>{{ g.count }}</td>
  <td>{{ g.avg_iv }}%</td>
  <td style="color:{{ colors.success }}">{{ g.min_iv }}%</td>
  <td style="color:{{ colors.danger }}">{{ g.max_iv }}%</td>
  <td>{{ g.min_product }}</td>
  <td>{{ g.max_product }}</td>
</tr>
{% endfor %}
</tbody>
</table>

{% if ten_x_contracts and (ten_x_contracts.near_term or ten_x_contracts.far_term) %}
<h2>🎯 十倍潜力合约筛选</h2>
<p style="color: {{ colors.muted }}; font-size: 0.85em; margin-bottom: 8px;">
💡 筛选逻辑：近月虚值5%~10%(Delta 0.20~0.35) / 远月虚值12%~18%(Delta 0.25~0.40) | 蒙特卡洛模拟(正态+Levy α=1.8) | 十倍概率 ≥ 2%
</p>
<div class="stats-grid" style="margin-bottom: 16px;">
<div class="stat-card">
  <div class="label">筛选合约总数</div>
  <div class="value">{{ ten_x_contracts.summary.total_screened }}</div>
</div>
<div class="stat-card">
  <div class="label">近月候选</div>
  <div class="value" style="color: {{ colors.accent }}">{{ ten_x_contracts.summary.near_count }}</div>
</div>
<div class="stat-card">
  <div class="label">远月候选</div>
  <div class="value" style="color: {{ colors.warning }}">{{ ten_x_contracts.summary.far_count }}</div>
</div>
<div class="stat-card">
  <div class="label">低票价加分</div>
  <div class="value" style="color: {{ colors.success }}">{{ ten_x_contracts.summary.low_ticket_count }}</div>
</div>
</div>

{% if ten_x_contracts.near_term %}
<h3 style="color: {{ colors.accent }}; margin-top: 16px;">近月合约（≤{{ 35 }}天到期，Gamma爆发力强）</h3>
<table>
<thead><tr><th>#</th><th>合约</th><th>品种</th><th>行权价</th><th>虚值%</th><th>天数</th><th>IV(%)</th><th>Delta</th><th>权利金</th><th>十倍概率(正态)</th><th>十倍概率(Levy)</th><th>低票价</th></tr></thead>
<tbody>
{% for c in ten_x_contracts.near_term %}
<tr>
  <td>{{ loop.index }}</td>
  <td style="font-size:0.85em;"><strong>{{ c.contract_code }}</strong></td>
  <td>{{ c.product_name }}</td>
  <td>{{ c.strike }}</td>
  <td>{{ c.moneyness }}%</td>
  <td>{{ c.days_to_expiry }}d</td>
  <td class="iv-cell" style="color: {{ c.iv | iv_color }}">{{ c.iv }}%</td>
  <td>{% if c.delta is not none %}{{ c.delta }}{% else %}-{% endif %}</td>
  <td>{% if c.premium is not none %}{{ c.premium }}{% else %}{{ c.premium_mc_levy }}{% endif %}</td>
  <td>{{ (c.prob_10x_normal * 100) | round(1) }}%</td>
  <td style="color: {{ colors.accent }}; font-weight:700;">{{ (c.prob_10x_levy * 100) | round(1) }}%</td>
  <td>{% if c.is_low_ticket %}<span class="tag tag-low">✓</span>{% else %}-{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}

{% if ten_x_contracts.far_term %}
<h3 style="color: {{ colors.warning }}; margin-top: 16px;">远月合约（>35天到期，时间损耗慢）</h3>
<table>
<thead><tr><th>#</th><th>合约</th><th>品种</th><th>行权价</th><th>虚值%</th><th>天数</th><th>IV(%)</th><th>Delta</th><th>权利金</th><th>十倍概率(正态)</th><th>十倍概率(Levy)</th><th>低票价</th></tr></thead>
<tbody>
{% for c in ten_x_contracts.far_term %}
<tr>
  <td>{{ loop.index }}</td>
  <td style="font-size:0.85em;"><strong>{{ c.contract_code }}</strong></td>
  <td>{{ c.product_name }}</td>
  <td>{{ c.strike }}</td>
  <td>{{ c.moneyness }}%</td>
  <td>{{ c.days_to_expiry }}d</td>
  <td class="iv-cell" style="color: {{ c.iv | iv_color }}">{{ c.iv }}%</td>
  <td>{% if c.delta is not none %}{{ c.delta }}{% else %}-{% endif %}</td>
  <td>{% if c.premium is not none %}{{ c.premium }}{% else %}{{ c.premium_mc_levy }}{% endif %}</td>
  <td>{{ (c.prob_10x_normal * 100) | round(1) }}%</td>
  <td style="color: {{ colors.accent }}; font-weight:700;">{{ (c.prob_10x_levy * 100) | round(1) }}%</td>
  <td>{% if c.is_low_ticket %}<span class="tag tag-low">✓</span>{% else %}-{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}
{% endif %}

{% if high_iv_alerts %}
<h2>⚠️ 极高IV风险警示</h2>
<p style="color: {{ colors.muted }}; font-size: 0.85em; margin-bottom: 8px;">
⚠️ IV百分位≥80%或IV>50%或IV溢价>1.5倍中位数，标记顶部反转信号，卖方机会但需警惕IV崩塌
</p>
<table>
<thead><tr><th>#</th><th>品种</th><th>交易所</th><th>板块</th><th>IV(%)</th><th>IV百分位</th><th>IV溢价</th><th>风险等级</th><th>反转信号</th><th>触发条件</th></tr></thead>
<tbody>
{% for a in high_iv_alerts %}
<tr>
  <td>{{ loop.index }}</td>
  <td><strong>{{ a.product_name }}</strong></td>
  <td>{{ a.exchange }}</td>
  <td>{{ a.group }}</td>
  <td class="iv-cell" style="color: {{ colors.danger }}">{{ a.iv }}%</td>
  <td>{% if a.iv_percentile is not none %}{{ a.iv_percentile }}%{% else %}-{% endif %}</td>
  <td>{% if a.iv_premium_ratio is not none %}{{ a.iv_premium_ratio }}x{% else %}-{% endif %}</td>
  <td><span class="tag {% if a.risk_level == '极高' %}tag-high{% else %}tag-mid{% endif %}">{{ a.risk_level }}</span></td>
  <td>{% if a.reversal_signal %}<span style="color:{{ colors.danger }};font-weight:700;">⚠ 反转</span>{% else %}-{% endif %}</td>
  <td style="font-size:0.8em;">
    {% if a.high_percentile %}<span class="tag tag-high">百分位≥80%</span> {% endif %}
    {% if a.high_premium %}<span class="tag tag-mid">溢价>1.5x</span> {% endif %}
    {% if a.very_high_iv %}<span class="tag tag-high">IV>50%</span>{% endif %}
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}

<h2>数据来源说明</h2>
<div style="color: {{ colors.muted }}; font-size: 0.85em; line-height: 1.8;">
<p>• <strong>SHFE（上期所）</strong>：option_vol_shfe 接口，合约系列级IV（小数口径×100归一）</p>
<p>• <strong>CZCE（郑商所）</strong>：option_hist_czce 接口，合约级IV+DELTA（百分数口径），|DELTA-0.5|最小者作平值IV</p>
<p>• <strong>GFEX（广期所）</strong>：option_vol_gfex 接口，合约系列级IV（百分数口径）</p>
<p>• <strong>DCE（大商所）</strong>：官网被WAF拦截，降级用新浪合约表（仅行情，无IV数据）</p>
<p>• IV口径已统一为百分数（%），成交量最大合约系列作主力参考</p>
</div>

<footer>
商品期权IV扫描器 | 数据来源: AKShare/各交易所公开接口 | {{ scan_time }}
</footer>
</div>
</body>
</html>"""