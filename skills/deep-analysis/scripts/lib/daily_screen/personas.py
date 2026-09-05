"""Distinct F-school tape patterns plus cross-market Serenity evaluation."""
from __future__ import annotations

from dataclasses import dataclass

from .models import PersonaVerdict, StockSnapshot
from .events import filter_evidence, is_business_evidence


@dataclass(frozen=True)
class PersonaSpec:
    investor_id: str
    name: str
    style: str
    must_have: tuple[str, ...]
    positive_patterns: tuple[str, ...]
    veto_rules: tuple[str, ...]
    entry_condition: str
    invalidation: str
    horizon: str = "1-3d"


F_PERSONAS = (
    PersonaSpec("zhang_mz", "章盟主", "容量趋势", ("capacity", "trend_up"), ("leader", "theme_hot"), ("illiquid", "isolated"), "主线核心维持放量承接", "跌破上午均价且板块转弱"),
    PersonaSpec("sun_ge", "孙哥", "板块引导", ("theme_hot", "leader"), ("breadth", "active"), ("isolated",), "板块宽度继续扩散", "个股强而板块不响应"),
    PersonaSpec("zhao_lg", "赵老哥", "一二板定龙头", ("strong", "leader"), ("fresh_theme", "active"), ("extended", "laggard"), "前排换手确认且题材保持新鲜", "后排化或题材快速退潮"),
    PersonaSpec("fs_wyj", "佛山无影脚", "超跌反核", ("small_cap", "reversal"), ("active",), ("large_cap", "illiquid"), "反核后承接不破启动位", "冲高无承接或退出流动性下降"),
    PersonaSpec("yangjia", "炒股养家", "情绪周期", ("theme_hot",), ("breadth", "strong"), ("risk_off", "climax"), "赚钱效应继续向同题材扩散", "高位一致转分歧且亏钱效应扩散"),
    PersonaSpec("chen_xq", "陈小群", "龙头全周期", ("leader", "strong"), ("reversal", "hard_event"), ("laggard", "priced_in"), "总龙分歧转一致并带动板块", "后排跟风或消息兑现后失去承接"),
    PersonaSpec("hu_jl", "呼家楼", "板块平铺协同", ("breadth", "theme_hot"), ("capacity", "active"), ("isolated",), "多标的同步放量", "协同消失并退化为单票脉冲"),
    PersonaSpec("fang_xx", "方新侠", "大成交趋势", ("capacity", "trend_up"), ("near_high", "leader"), ("illiquid",), "大成交趋势保持在均价上方", "放量跌破趋势承接位"),
    PersonaSpec("zuoshou", "作手新一", "主线接力", ("theme_hot", "leader"), ("reversal", "active"), ("laggard", "competition"), "弱转强或回封确认", "竞争板抢位且自身地位下降"),
    PersonaSpec("xiao_ey", "小鳄鱼", "基本面盘面共振", ("trend_up", "fundamental_proxy"), ("theme_hot", "hard_event"), ("governance_risk",), "业务证据与盘面同时增强", "纯概念冲高或基本面证据被证伪"),
    PersonaSpec("jiao_yy", "交易猿", "容量龙头加速", ("capacity", "leader"), ("strong", "near_high"), ("small_cap", "failed_acceleration"), "渡劫后再次放量确认", "加速失败并跌破上午均价"),
    PersonaSpec("mao_lb", "毛老板", "AI 主线重仓", ("ai_chain", "capacity"), ("hard_event", "leader"), ("fake_ai",), "AI 硬催化和容量承接同时成立", "仅关键词无订单或产业证据"),
    PersonaSpec("xiao_xian", "消闲派", "超预期加速", ("hard_event", "strong"), ("leader", "near_high"), ("priced_in", "laggard"), "预期上修后强度可持续", "低于预期或补涨末端"),
    PersonaSpec("lasa", "拉萨天团", "散户拥挤反向", ("crowded",), ("active",), ("climax",), "只作为拥挤观察信号", "拥挤继续上升时禁止追涨"),
    PersonaSpec("chengdu", "成都帮", "底部点火", ("low_position", "active"), ("reversal", "hard_event"), ("extended",), "低位直线放量后回踩不破", "高位接力或消息无发酵"),
    PersonaSpec("sunan", "苏南帮", "低价小盘联动", ("small_cap", "breadth"), ("low_price", "active"), ("large_cap",), "区域/题材小票同步", "大市值或只有单票异动"),
    PersonaSpec("ningbo_st", "宁波桑田路", "连板接力", ("strong", "leader"), ("active", "theme_hot"), ("failed_acceleration",), "梯队高度和换手继续确认", "断板修复弱或板块高度下降"),
    PersonaSpec("liuyi_zl", "六一中路", "题材龙头接力", ("theme_hot", "leader"), ("hard_event", "active"), ("stale_theme", "laggard"), "主线回流且龙头确认", "旧题材无回流或后排套利"),
    PersonaSpec("liu_sh", "流沙河", "分歧低吸", ("trend_up", "not_extended"), ("reversal", "active"), ("breakdown", "climax"), "分歧低吸后出现承接", "一致缩量或破位无承接"),
    PersonaSpec("gu_bl", "古北路", "活跃容量", ("active", "capacity"), ("theme_hot", "leader"), ("sample_low",), "滚动活跃且板块启动", "样本不足或板块未启动"),
    PersonaSpec("bj_cj", "北京炒家", "首板", ("mid_cap", "strong"), ("active", "fresh_theme"), ("extended", "illiquid"), "上午放量首板代理条件成立", "午后被动跟风或流动性下降"),
    PersonaSpec("wang_zr", "瑞鹤仙", "强势题材", ("strong", "active"), ("theme_hot", "leader"), ("illiquid", "climax"), "强势题材保持辨识度", "次日追高拥挤或交易活跃度下降"),
    PersonaSpec("xin_dd", "鑫多多", "困境反转", ("low_position", "reversal"), ("hard_event", "small_cap"), ("extended", "priced_in"), "低位反转催化获盘口确认", "高位纯接力或预期已兑现"),
    PersonaSpec("ghzw", "股海贼王", "主线接力与格局票", ("theme_hot", "leader"), ("active", "capacity", "hard_event"), ("laggard", "failed_acceleration"), "涨停原因、板块地位与大盘环境同时成立", "非主线、承接差或高位竞争失败"),
)


_AI_TERMS = ("AI", "人工智能", "算力", "光模块", "CPO", "半导体", "芯片", "PCB", "铜箔", "机器人", "液冷", "电源", "数据中心")


def build_features(stock: StockSnapshot, theme: dict, evidence: list[dict] | None = None) -> dict[str, bool | None]:
    evidence, _ = filter_evidence(evidence or [], stock.observed_at)
    cap = stock.market_cap or 0
    has_hard_event = any(is_business_evidence(item) for item in evidence)
    ai_chain = any(term.lower() in f"{stock.name} {stock.industry}".lower() for term in _AI_TERMS)
    near_high = bool(stock.high and stock.price >= stock.high * 0.985)
    reversal = bool(stock.open_price and stock.prev_close and stock.open_price < stock.prev_close and stock.change_pct > 1)
    return {
        "illiquid": stock.amount < 2e8,
        "capacity": stock.amount >= 10e8,
        "active": (stock.turnover_rate or 0) >= 3 or (stock.volume_ratio or 0) >= 1.2,
        "trend_up": None,  # A trend requires historical bars.
        "strong": stock.change_pct >= 4,
        "extended": stock.change_pct >= (9.5 if stock.market == "A" else 12),
        "not_extended": stock.change_pct < 7,
        "near_high": near_high,
        "reversal": reversal,
        "leader": (theme.get("leader_rank") or 999) <= 2,
        "laggard": (theme.get("leader_rank") or 999) > 5,
        "theme_hot": (theme.get("theme_rank") or 999) <= 5 and (theme.get("breadth_pct") or 0) >= 55,
        "breadth": (theme.get("breadth_pct") or 0) >= 65,
        "isolated": (theme.get("breadth_pct") or 0) < 40,
        "fresh_theme": None,  # A single snapshot cannot establish theme age.
        "stale_theme": None,
        "small_cap": 0 < cap <= 100e8,
        "mid_cap": 20e8 <= cap <= 800e8,
        "large_cap": cap > 800e8,
        "low_price": stock.price <= 20,
        "low_position": None,  # Requires price history, not today's return.
        "crowded": (stock.turnover_rate or 0) >= 12 or stock.change_pct >= 9,
        "climax": stock.change_pct >= 9.5,
        "hard_event": has_hard_event,
        "priced_in": stock.change_pct >= 8 and has_hard_event,
        "ai_chain": ai_chain,
        "fake_ai": ai_chain and not has_hard_event,
        "fundamental_proxy": has_hard_event,
        "governance_risk": any(item.get("risk") == "governance" for item in evidence),
        "competition": (theme.get("breadth_pct") or 0) > 80 and (theme.get("leader_rank") or 999) > 2,
        "failed_acceleration": stock.change_pct < 2 and near_high is False,
        "breakdown": stock.change_pct < -2,
        "risk_off": None,
        "sample_low": not any(item.get("kind") == "lhb" for item in evidence),
    }


def evaluate_f_personas(stock: StockSnapshot, theme: dict, evidence: list[dict] | None = None) -> list[PersonaVerdict]:
    if stock.market != "A":
        return [PersonaVerdict(spec.investor_id, spec.name, spec.style, False, "skip", 0, [], [], "港股不适用 A 股涨停板、T+1 与龙虎榜人物生态。", "不适用", "不适用", spec.horizon) for spec in F_PERSONAS]
    features = build_features(stock, theme, evidence)
    verdicts = []
    for spec in F_PERSONAS:
        matched = [key for key in spec.must_have + spec.positive_patterns if features.get(key)]
        missing = [key for key in spec.must_have if not features.get(key)]
        vetoes = [key for key in spec.veto_rules if features.get(key)]
        unknown_vetoes = [key for key in spec.veto_rules if features.get(key) is None]
        must_ratio = (len(spec.must_have) - len(missing)) / max(1, len(spec.must_have))
        confidence = round(min(92, 38 + must_ratio * 34 + len(matched) * 5 - len(vetoes) * 16))
        if vetoes:
            signal = "bearish"
        elif not missing and not unknown_vetoes and len(matched) >= len(spec.must_have) + 1:
            signal = "bullish"
        else:
            signal = "neutral"
        reasoning = f"规则初筛（非 Agent 研判）· {spec.style}：命中 {', '.join(matched) if matched else '无'}"
        if missing:
            reasoning += f"；缺少 {', '.join(missing)}"
        if vetoes:
            reasoning += f"；否决 {', '.join(vetoes)}"
        if unknown_vetoes:
            reasoning += f"；风险待核验 {', '.join(unknown_vetoes)}"
        verdicts.append(PersonaVerdict(spec.investor_id, spec.name, spec.style, True, signal, max(0, confidence), matched, vetoes, reasoning, spec.entry_condition, spec.invalidation, spec.horizon))
    return verdicts


def evaluate_serenity(stock: StockSnapshot, theme: dict, evidence: list[dict] | None = None) -> PersonaVerdict:
    features = build_features(stock, theme, evidence)
    hard = features["hard_event"]
    ai = features["ai_chain"]
    if ai and hard:
        signal, confidence = "bullish", 78
        reasoning = "AI 供应链位置与 A/B 级业务证据同时命中，进入卡位候选。"
    elif ai:
        signal, confidence = "neutral", 56
        reasoning = "命中 AI 供应链关键词，但缺订单、认证、量产或财报贡献等硬证据，只能观察。"
    else:
        signal, confidence = "bearish", 35
        reasoning = "未识别到可验证的 AI 供应链瓶颈位置，不进入 Serenity 核心池。"
    return PersonaVerdict("serenity", "Serenity", "AI 供应链卡位", True, signal, confidence, ["ai_chain"] if ai else [], [] if hard else ["hard_evidence_missing"], reasoning, "等待客户验证、订单或供需紧张证据与价格承接共振", "出现可替代方案、供给转松或估值已完全反映", "1-4q")
