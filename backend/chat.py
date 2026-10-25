"""질문형 시나리오: 한국어 문장을 조건으로 바꾸고, 계산 결과를 문장으로 돌려준다.

외부 AI API 없이 규칙(정규식)으로 해석한다. 그래서 인터넷·키 없이도 동작하고, 같은 질문은 항상 같은 조건으로 읽힌다.
알아듣는 조건: 경쟁사 견적 · 후판가 · 환율(% 또는 원) · 납기 지연(개월) · 우리 견적가(%).
다른 표현을 더 알아듣게 하려면 아래 ANCHORS / NEG / POS 만 늘리면 된다.
나중에 Claude API 로 바꾸더라도, 이 모듈의 출력 형식(parse 결과 = 조건 딕셔너리)만 지키면 화면은 그대로다.
"""
from __future__ import annotations
import re
from typing import Optional

ZERO = {"comp_pct": 0.0, "steel_pct": 0.0, "fx_pct": 0.0, "fx_krw": None, "delay_months": 0, "quote_pct": 0.0}

# 조건 종류를 알려주는 말. 먼저 나온 것부터 문장을 조각내므로 "경쟁사 견적"은 comp 하나로 읽힌다.
ANCHORS = [
    ("comp", r"경쟁(?:사|업체|자)?|중국(?:\s*조선소)?|타사|다른\s*조선소"),
    ("steel", r"후판(?:\s*가격|가)?|철강(?:가)?|강재(?:가)?|원자재"),
    ("fx", r"환율|원\s*/\s*달러|달러\s*값"),
    ("delay", r"납기|인도\s*(?:시기|시점|일정)?|공기"),
    ("quote", r"(?:우리\s*|당사\s*)?(?:견적가?|제안가|입찰가|선가|가격)"),
]
_ANCHOR_RE = re.compile("|".join(f"(?P<{k}>{p})(?:\\s*(?:견적가?|가격|입찰가))?" if k == "comp" else f"(?P<{k}>{p})" for k, p in ANCHORS))

NEG = re.compile(r"싸|저렴|낮|내리|내려|인하|떨어|하락|줄|감소|깎|절감")
POS = re.compile(r"비싸|높|올리|올라|오르|인상|상승|증가|늘")
PCT = re.compile(r"([+\-]?)\s*(\d+(?:\.\d+)?)\s*%")
WON = re.compile(r"(\d+(?:\.\d+)?)\s*원")
MONTHS = re.compile(r"(\d+)\s*개월")
DELAY_UP = re.compile(r"지연|늦|연장|밀리|밀려|뒤로")
DELAY_DOWN = re.compile(r"단축|앞당|빨라|당기")
RESET = re.compile(r"초기화|처음으로|리셋|기본\s*조건으로|원래대로")

LABEL = {"comp_pct": "경쟁사 견적", "steel_pct": "후판가", "fx_pct": "환율", "quote_pct": "우리 견적가"}
LIMITS = {"comp_pct": (-0.5, 0.5), "steel_pct": (-0.5, 1.0), "fx_pct": (-0.5, 0.5), "quote_pct": (-0.3, 0.3)}
TOPIC_KEY = {"comp": "comp_pct", "steel": "steel_pct", "fx": "fx_pct", "quote": "quote_pct"}


def _sign(seg: str, num_end: int, explicit: str) -> int:
    """% 숫자의 부호: 명시한 +/-가 우선, 없으면 숫자 뒤(없으면 앞)에 나오는 올림/내림 표현으로 정한다."""
    if explicit:
        return -1 if explicit == "-" else 1
    for part in (seg[num_end:], seg[:num_end]):
        n, p = NEG.search(part), POS.search(part)
        if n and (not p or n.start() < p.start()):
            return -1
        if p:
            return 1
    return 0


def parse(text: str) -> dict:
    """문장 → {'updates': {...}, 'notes': [...], 'reset': bool}"""
    t = text.replace(",", "").replace("−", "-").replace("–", "-").strip()
    out = {"updates": {}, "notes": [], "reset": bool(RESET.search(t))}
    if out["reset"]:
        return out
    marks = [(m.lastgroup, m.start()) for m in _ANCHOR_RE.finditer(t)]
    for i, (kind, st) in enumerate(marks):
        seg = t[st: marks[i + 1][1] if i + 1 < len(marks) else len(t)]
        # 같은 조건이 두 번 나오면 뒤의 값이 이긴다 (updates 를 덮어씀)
        if kind == "delay":
            m = MONTHS.search(seg)
            if DELAY_DOWN.search(seg):
                out["notes"].append("납기 단축은 아직 계산하지 않아요. 납기 지연(개월)만 물어볼 수 있어요.")
            elif m and DELAY_UP.search(seg):
                n = int(m.group(1))
                if n <= 36:
                    out["updates"]["delay_months"] = n
                else:
                    out["notes"].append("납기 지연은 36개월까지만 계산해요.")
            continue
        if kind == "fx":
            w = WON.search(seg)
            if w and 800 <= float(w.group(1)) <= 2500:
                out["updates"]["fx_krw"] = float(w.group(1))
                out["updates"]["fx_pct"] = 0.0
                continue
        m = PCT.search(seg)
        if not m:
            continue
        sg = _sign(seg, m.end(), m.group(1))
        key = TOPIC_KEY[kind]
        if sg == 0:
            out["notes"].append(f"{LABEL[key]}가 올라가는지 내려가는지 알려 주세요. (예: {LABEL[key]} 5% 내리면)")
            continue
        v = sg * float(m.group(2)) / 100
        lo, hi = LIMITS[key]
        if not lo <= v <= hi:
            out["notes"].append(f"{LABEL[key]}는 {lo * 100:+.0f}% ~ {hi * 100:+.0f}% 범위만 계산해요.")
            continue
        out["updates"][key] = v
        if key == "fx_pct":
            out["updates"]["fx_krw"] = None
    # 모델에 없는 질문은 솔직하게 알린다
    if re.search(r"헤지", t):
        out["notes"].append("환헤지는 아직 모델에 들어 있지 않아 계산하지 못해요. 지금은 환율이 바뀌는 경우만 볼 수 있어요.")
    if re.search(r"실주|과거|비슷한|이력", t):
        out["notes"].append("지난 입찰 결과는 위쪽 '과거 이력' 메뉴에서 볼 수 있어요.")
    if re.search(r"신규\s*선주|선주|LNG|스크러버|사양|연료", t):
        out["notes"].append("선주·사양 같은 항목은 학습 데이터가 적어 시나리오 조건으로 쓰지 않아요.")
    return out


def describe(params: dict) -> list:
    """적용 중인 조건을 화면 칩 문구로."""
    chips = []
    sg = lambda v: f"{'+' if v > 0 else '-'}{abs(v) * 100:g}%"
    if params.get("comp_pct"): chips.append({"key": "comp_pct", "label": f"경쟁사 견적 {sg(params['comp_pct'])}"})
    if params.get("steel_pct"): chips.append({"key": "steel_pct", "label": f"후판가 {sg(params['steel_pct'])}"})
    if params.get("fx_krw"): chips.append({"key": "fx_krw", "label": f"환율 {params['fx_krw']:,.0f}원"})
    elif params.get("fx_pct"): chips.append({"key": "fx_pct", "label": f"환율 {sg(params['fx_pct'])}"})
    if params.get("delay_months"): chips.append({"key": "delay_months", "label": f"납기 +{params['delay_months']}개월"})
    if params.get("quote_pct"): chips.append({"key": "quote_pct", "label": f"우리 견적가 {sg(params['quote_pct'])}"})
    return chips


def _p(v: Optional[float], d: int = 0) -> str:
    return "–" if v is None else f"{v * 100:.{d}f}%"


def answer(be, bid_id: str, message: str, state: dict) -> dict:
    parsed = parse(message)
    if parsed["reset"]:
        params = dict(ZERO)
        return {"params": params, "active": [], "understood": [], "notes": [], "metrics": [],
                "lines": ["조건을 모두 기준으로 되돌렸어요. 다시 물어보세요."], "changed": True}
    prev = {**ZERO, **{k: v for k, v in state.items() if v is not None or k == "fx_krw"}}
    params = {**prev, **parsed["updates"]}
    understood = describe({**ZERO, **parsed["updates"]})
    notes = parsed["notes"]
    if not parsed["updates"]:
        lines = ["조건을 읽지 못했어요. 이렇게 물어보세요."] if not notes else []
        if not notes:
            lines += ["경쟁사 견적이 5% 낮아지면?", "환율이 1,300원까지 떨어지면?", "후판가가 10% 오르고 납기가 6개월 늦어지면?", "우리 견적가를 3% 낮추면?"]
        return {"params": prev, "active": describe(prev), "understood": [], "notes": notes, "metrics": [], "lines": lines, "changed": False}

    cmp_ = be.compare(bid_id, params)
    b, s, dec = cmp_["base"]["summary"], cmp_["scenario"]["summary"], cmp_["decomposition"]
    grp = lambda k: "fx" if k.startswith("fx") else k
    new_keys = {grp(u["key"]) for u in understood}
    kept = [c for c in describe(params) if grp(c["key"]) not in new_keys]
    head = " · ".join(u["label"] for u in understood)
    lines = [f"{head} 조건으로 다시 계산했어요." + (f" 앞서 적용한 {', '.join(c['label'] for c in kept)}도 함께 반영했어요." if kept else "")]
    dp = (s["p_now"] - b["p_now"]) * 100
    lines.append(f"낙찰확률은 {_p(b['p_now'])} → {_p(s['p_now'])}({dp:+.1f}%p), 기대가치는 ${b['ev_now']:.1f}M → ${s['ev_now']:.1f}M(척당)이에요.")
    dl = (s["loss_prob_now"] - b["loss_prob_now"]) * 100
    if abs(dl) >= 0.5:
        lines.append(f"환율·원가로 적자가 날 확률은 {_p(b['loss_prob_now'])} → {_p(s['loss_prob_now'])}예요.")
    if abs(dec["total"]) >= 0.05:
        main = "낙찰확률이 달라지는 영향" if abs(dec["prob_effect"]) >= abs(dec["profit_effect"]) else "건당 이익이 달라지는 영향"
        lines.append(f"기대가치 변화({dec['total']:+.1f}M)는 주로 {main}이에요.")
    if s["recommended"] is not None and b["recommended"] is not None and abs(s["recommended"] - b["recommended"]) >= 0.05:
        lines.append(f"권장 견적가는 ${b['recommended']:.1f}M → ${s['recommended']:.1f}M로 바뀌어요.")
    metrics = [{"label": "낙찰확률", "value": _p(s["p_now"])}, {"label": "예상 마진", "value": _p(s["margin_mean_now"], 1)},
               {"label": "적자확률", "value": _p(s["loss_prob_now"])}]
    return {"params": params, "active": describe(params), "understood": understood, "notes": notes, "metrics": metrics,
            "lines": lines, "changed": True, "source": cmp_["source"]}
