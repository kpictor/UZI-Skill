"""Dense responsive HTML decision terminal for daily screening."""
from __future__ import annotations

import shutil
from pathlib import Path

from lib.report.security import escape_payload, safe_asset_id, safe_url


ACTION_LABELS = {
    "buyable": "数据条件通过，待成交确认",
    "wait_pullback": "等分歧/回踩",
    "wait_reseal": "等回封确认",
    "watch_only": "只看不追",
    "unbuyable": "当前不可成交",
    "avoid": "回避",
}


def _money(value: float, market: str) -> str:
    symbol = "HK$" if market == "H" else "¥"
    return f"{symbol}{value / 1e8:.1f}亿"


def render_report(report: dict, output: Path, avatars_dir: Path) -> Path:
    report = escape_payload(report)
    rows = []
    for rank, pick in enumerate(report.get("picks", []), 1):
        stock = pick["snapshot"]
        verdicts = pick.get("persona_verdicts") or []
        bulls = [item for item in verdicts if item.get("signal") == "bullish"]
        avatars = "".join(
            f'<span class="avatar" title="{item["name"]} · {item["style"]}"><img src="avatars/{safe_asset_id(item["investor_id"])}.svg" alt=""></span>'
            for item in bulls[:6]
        )
        serenity = pick.get("serenity") or {}
        if serenity.get("signal") == "bullish":
            avatars += '<span class="avatar serenity" title="Serenity · AI 卡位"><img src="avatars/serenity.svg" alt=""></span>'
        persona_rows = "".join(
            f'<tr><td><img src="avatars/{safe_asset_id(item["investor_id"])}.svg" alt="">{item["name"]}</td><td>{item["style"]}</td><td><span class="signal {item["signal"]}">{item["signal"]}</span></td><td>{item["confidence"]}</td><td>{item["reasoning_summary"]}</td></tr>'
            for item in verdicts if item.get("eligible")
        )
        evidence = "".join(f'<li><b>{item.get("grade", "—")}</b> <a href="{safe_url(item.get("url"))}" target="_blank" rel="noopener noreferrer">{item.get("title", "—")}</a> <span>{item.get("source", "")} · {item.get("published_at", "—")}</span></li>' for item in pick.get("evidence", []))
        extra = stock.get("extra") or {}
        intraday = extra.get("intraday") or {}
        quote = intraday.get("quote") or {}
        source_details = f'''<h3>数据对齐</h3><p>行业：{(extra.get("industry_source") or {}).get("source", "—")}<br>
盘口：{quote.get("source", "—")} · 报价时间 {quote.get("quote_at", "—")}<br>
买一 / 卖一：{quote.get("bid", "—")} / {quote.get("ask", "—")} · VWAP {quote.get("vwap", "—")}<br>
分钟线：{intraday.get("minute_source", "—")} · {len(intraday.get("bars") or [])} 条<br>
源诊断：{', '.join(intraday.get("source_errors") or []) or '无已记录错误'}</p>'''
        risks = "".join(f"<li>{item}</li>" for item in pick.get("risk_flags", []) + pick.get("data_gaps", [])) or "<li>无额外已识别风险；不代表风险已排除</li>"
        rows.append(f'''<article class="pick-row">
  <div class="rank">{rank:02d}</div>
  <div class="identity"><strong>{stock["name"]}</strong><span>{stock["code"]} · {stock["market"]}股</span></div>
  <div class="quote"><strong>{stock["change_pct"]:+.2f}%</strong><span>{_money(stock["amount"], stock["market"])}</span></div>
  <div class="theme"><strong>{stock["industry"]}</strong><span>主题 #{pick.get("theme_rank") or "—"} · 个股 #{pick.get("leader_rank") or "—"}</span></div>
  <div class="action"><span class="action-pill {pick["action"]}">{ACTION_LABELS.get(pick["action"], pick["action"])}</span><small>规则分 {pick["research_confidence"]:.1f}</small></div>
  <div class="supporters">{avatars or '<span class="none">暂无强看多角色</span>'}</div>
  <div class="thesis"><span>{pick["why_now"]}</span><small>失效：{pick["invalidation"]}</small></div>
  <details><summary>证据与完整评委矩阵</summary><div class="detail-grid"><section><h3>进入条件</h3><p>{pick["entry_condition"]}</p>{source_details}<h3>证据</h3><ul>{evidence or '<li>当前仅有行情横截面证据</li>'}</ul><h3>风险</h3><ul>{risks}</ul></section><section class="matrix"><table><thead><tr><th>评委</th><th>战法</th><th>信号</th><th>置信</th><th>依据</th></tr></thead><tbody>{persona_rows}</tbody></table></section></div></details>
</article>''')
    empty = '<div class="empty"><strong>当前数据不足以形成入榜候选</strong><span>未补足证据或未达到规则阈值，不凑数。</span></div>'
    actions = report.get("action_summary") or {}
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>UZI 每日观察榜</title><style>
:root{{--bg:#0b0f14;--panel:#121821;--line:#283241;--text:#edf2f7;--muted:#8b98a8;--green:#2dd4bf;--red:#fb7185;--gold:#fbbf24;--blue:#60a5fa}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Inter,"PingFang SC",sans-serif;letter-spacing:0}}main{{max-width:1500px;margin:auto;padding:22px}}header{{display:grid;grid-template-columns:1fr auto;gap:18px;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:16px}}h1{{font-size:28px;margin:0 0 5px}}.sub,.meta{{color:var(--muted)}}.summary{{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}}.summary span,.action-pill{{border:1px solid var(--line);padding:5px 9px;border-radius:4px;background:#18202b}}.screen-head,.pick-row{{display:grid;grid-template-columns:48px minmax(145px,1.1fr) 100px minmax(150px,1.2fr) 180px 170px minmax(260px,2fr);gap:12px;align-items:center}}.screen-head{{color:var(--muted);font-size:11px;padding:8px 12px}}.pick-row{{background:var(--panel);border-top:1px solid var(--line);padding:12px}}.rank{{font:700 18px ui-monospace;color:var(--gold)}}.identity,.quote,.theme,.action,.thesis{{display:flex;flex-direction:column;min-width:0}}.identity span,.quote span,.theme span,.action small,.thesis small{{color:var(--muted);font-size:11px}}.quote strong{{color:var(--red)}}.action-pill{{font-size:11px;width:max-content;max-width:100%}}.buyable{{border-color:#0f766e;color:var(--green)}}.wait_pullback,.wait_reseal{{border-color:#a16207;color:var(--gold)}}.unbuyable,.avoid{{border-color:#be123c;color:var(--red)}}.supporters{{display:flex;min-height:32px;align-items:center}}.avatar{{width:30px;height:30px;margin-left:-5px;border:2px solid var(--panel);background:#fff;border-radius:50%;overflow:hidden}}.avatar:first-child{{margin-left:0}}.avatar img{{width:100%;height:100%;object-fit:cover}}.avatar.serenity{{border-color:var(--blue)}}.none{{font-size:11px;color:var(--muted)}}details{{grid-column:1/-1;border-top:1px solid var(--line);padding-top:8px}}summary{{cursor:pointer;color:var(--blue);font-size:12px}}.detail-grid{{display:grid;grid-template-columns:300px 1fr;gap:20px;padding:14px 0}}h3{{font-size:12px;color:var(--muted);margin:10px 0 4px}}ul{{padding-left:18px}}li span{{color:var(--muted);font-size:10px}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{padding:7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}td img{{width:22px;height:22px;vertical-align:middle;margin-right:6px;background:#fff;border-radius:50%}}.signal.bullish{{color:var(--green)}}.signal.bearish{{color:var(--red)}}.signal.neutral{{color:var(--gold)}}.empty{{padding:60px;text-align:center;background:var(--panel);display:flex;flex-direction:column}}.empty span{{color:var(--muted)}}footer{{color:var(--muted);font-size:11px;padding:18px 0}}
header>div,section,details{{min-width:0}}.meta,.identity,.theme,.thesis,section p,li{{overflow-wrap:anywhere}}a{{color:var(--blue)}}
@media(max-width:1200px){{main{{padding:12px}}header{{grid-template-columns:1fr}}.summary{{justify-content:flex-start}}.screen-head{{display:none}}.pick-row{{grid-template-columns:34px minmax(0,1fr) 90px;gap:8px}}.theme,.action,.supporters,.thesis{{grid-column:2/-1}}.detail-grid{{grid-template-columns:minmax(0,1fr)}}.matrix{{overflow-x:auto}}h1{{font-size:23px}}}}
</style></head><body><main><header><div><h1>UZI 每日观察榜</h1><div class="sub">A+港股 · 游资 F 组 + Serenity · 最多 {report.get("filters", {}).get("top_n", 10)} 只，不凑数</div><div class="meta">生成 {report.get("generated_at", "")} · 快照观测 {report.get("as_of_by_market", {})}</div></div><div class="summary"><span>条件通过 {actions.get("buyable",0)}</span><span>等回踩 {actions.get("wait_pullback",0)}</span><span>等确认 {actions.get("wait_reseal",0)}</span><span>只观察 {actions.get("watch_only",0)}</span><span>不可成交 {actions.get("unbuyable",0)}</span></div></header><div class="screen-head"><span>#</span><span>股票</span><span>盘面</span><span>主线地位</span><span>行动</span><span>规则匹配角色</span><span>为什么现在 / 失效</span></div>{''.join(rows) or empty}<footer>研究辅助，不构成买卖建议。当前为规则初筛，尚非 Agent 角色研判；规则分未经概率校准，不是胜率。缺消息、行业或分时成交验证时仅供观察。</footer></main></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(output)
    target_avatars = output.parent / "avatars"
    if not target_avatars.exists() and avatars_dir.exists():
        shutil.copytree(avatars_dir, target_avatars)
    return output
