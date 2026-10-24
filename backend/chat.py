"""질문형 시나리오: 한국어 문장을 조건으로 바꾸고, 계산 결과를 문장으로 돌려준다.

외부 AI API 없이 규칙(정규식)으로 해석한다. 그래서 인터넷·키 없이도 동작하고, 같은 질문은 항상 같은 조건으로 읽힌다.

알아듣는 조건
  경쟁사 견적(% · $M)       "경쟁사가 5% 싸게 들어오면", "중국이 덤핑하면", "경쟁사가 $5M 낮게 내면"
  후판가(%)                 "후판가 10% 오르면", "철판 값 상승", "강재가 떨어지면"
  환율(% · 원 · 원 변화)     "환율 1,300원이면", "환율 100원 떨어지면", "달러 강세", "원화 10% 절상"
  납기 지연(개월·달·년)       "납기 6개월 늦어지면", "인도가 석 달 밀리면", "1년 반 지연"
  우리 견적가(% · $M)        "견적가 3% 낮추면", "견적을 $5M 깎으면", "180M으로 내면", "우리가 경쟁사보다 2% 비싸면"
숫자 없이 방향만 말하면 % 조건은 5%, 납기는 3개월로 가정하고 notes 로 알린다.
여러 조건을 섞어도 되고("후판가랑 환율이 5%씩 오르면"), 조건 이름 없이 숫자만 말하면("그럼 10%면?") 지금 걸려 있는 조건 하나에 적용한다.
"환율 조건 빼줘"는 그 조건만 빼고, "초기화"는 전부 뺀다. "지금 낙찰확률은?"·"권장가 얼마야?"에는 현재 조건의 결과를 요약해 답한다.

다른 표현을 더 알아듣게 하려면 아래 ANCHORS / NEG / POS 만 늘리면 된다.
나중에 Claude API 로 바꾸더라도, answer() 의 출력 형식만 지키면 화면은 그대로다.
"""
from __future__ import annotations
import re
import traceback
from typing import Optional

ZERO = {"comp_pct": 0.0, "steel_pct": 0.0, "fx_pct": 0.0, "fx_krw": None, "delay_months": 0, "quote_pct": 0.0}

# ── 조건 종류를 알려주는 말. 문장을 이 말들 기준으로 조각낸다. market 은 계산 조건이 아니라 안내만 한다 ──
_PRICE_TAIL = r"(?:\s*(?:견적가?|가격|값|입찰가|제안가|오퍼|선가))?"
ANCHORS = [
    ("market", r"시장\s*(?:가격|가|선가|시세)|신조선가|선가\s*지수|클락슨"),
    ("comp", r"(?:경쟁(?:사|업체|자|\s*조선소|\s*상대)?|중국(?:\s*조선소)?|일본(?:\s*조선소)?|싱가포르|베트남|타사"
             r"|다른\s*(?:조선소|회사|업체)|상대(?:방|\s*조선소|\s*회사)|라이벌)" + _PRICE_TAIL),
    ("steel", r"(?:후판|철강|강재|강판|철판|원자재|자재비|재료비)(?:\s*(?:가격|값|시세|가))?"),
    ("fx", r"환율|원\s*/?\s*달러|(?<![\d만백천])(?<![\d만백천]\s)달러(?:\s*(?:값|가치|시세))?|원화(?:\s*(?:값|가치))?"),
    ("delay", r"납기|인도\s*(?:시기|시점|일정|일)?|공기|건조\s*기간|딜리버리"),
    ("quote", r"(?:우리|당사|저희)(?:\s*(?:쪽|측|회사))?" + _PRICE_TAIL + r"|견적가?|제안가|입찰가|오퍼|(?<!분기)(?<!분기\s)선가|가격"),
]
_ANCHOR_RE = re.compile("|".join(f"(?P<{k}>{p})" for k, p in ANCHORS))

NEG = re.compile(r"싸|저렴|낮|내리|내려|내린|인하|떨어|하락|줄|감소|깎|절감|약세|절하|빠지|빠져|급락|폭락|덤핑|할인|저가")
POS = re.compile(r"비싸|높|올리|올려|올라|오르|오른|인상|상승|증가|늘|강세|절상|뛰|급등|폭등")
PCT = re.compile(r"([+\-]?)\s*(\d+(?:\.\d+)?)\s*%")
WON = re.compile(r"(\d+(?:\.\d+)?)\s*원(?!화)")
BARE = re.compile(r"(?<![\d.$])(\d{3,4}(?:\.\d+)?)(?![\d.%]|\s*(?:개월|달|년|M|m|만|백만|달러))")
USD = re.compile(r"\$\s*(\d+(?:\.\d+)?)\s*(?:M|m|백만)?|(\d+(?:\.\d+)?)\s*(?:M|m|백만\s*달러|밀리언)(?![a-z])|(\d+(?:\.\d+)?)\s*만\s*달러")
MONTHS = re.compile(r"(\d+(?:\.\d+)?)\s*(개월|달(?!러)|년)")
DELAY_UP = re.compile(r"지연|늦|연장|밀리|밀려|밀린|뒤로|더\s*걸|미뤄|미루|연기")
DELAY_DOWN = re.compile(r"단축|앞당|빨라|당기|당겨|줄")
REMOVE = re.compile(r"빼|없애|제외|지워|무시|취소|해제")
RESET = re.compile(r"초기화|처음으로|처음부터|리셋|기본\s*조건|원래대로|되돌려|되돌리|기준\s*조건으로|기준으로\s*(?:돌|되|바)"
                   r"|(?:다|전부|모두|싹)\s*(?:빼|지워|없애|취소)")
CONNECT = re.compile(r"^\s*(?:가|이|은|는|도|을|를)?\s*(?:이?랑|와|과|하고|및|그리고|,|·|/)\s*(?:도)?\s*$")
INFO = re.compile(r"낙찰\s*확률|확률|권장|추천|제일|가장|최적|적정|얼마|마진|적자|손실|손익\s*분기|기대\s*가치|이익|지금|현재|요약|정리|결과|어때|어떻|상황|알려")
HELP = re.compile(r"안녕|하이|헬로|도움|도와|사용법|뭘\s*(?:할|물어|물을)|뭐\s*(?:할|물어|물을)|어떻게\s*(?:써|사용|물어|질문)|무슨\s*질문|기능|예시|설명|뭐야|누구|ㅎㅇ|hi|hello|^\?+$")
DECIDE = re.compile(r"따야|따도|해야\s*(?:돼|되|할)|할까|괜찮|들어가도|입찰해도|내도\s*(?:돼|되)|어떻게\s*해")
WORST = re.compile(r"최악|최선|베스트|워스트|비관|낙관")
THANKS = re.compile(r"고마|감사|땡큐|ㄳ|ㄱㅅ")

LABEL = {"comp_pct": "경쟁사 견적", "steel_pct": "후판가", "fx_pct": "환율", "quote_pct": "우리 견적가", "delay_months": "납기 지연"}
LIMITS = {"comp_pct": (-0.5, 0.5), "steel_pct": (-0.5, 1.0), "fx_pct": (-0.5, 0.5), "quote_pct": (-0.3, 0.3)}
TOPIC_KEY = {"comp": "comp_pct", "steel": "steel_pct", "fx": "fx_pct", "quote": "quote_pct", "delay": "delay_months"}
DEFAULT_PCT = 0.05     # 숫자 없이 "오르면/내리면"만 말했을 때 가정하는 폭
DEFAULT_DELAY = 3      # 개월 수 없이 "납기 늦어지면?"만 물었을 때 가정하는 지연
MAX_DELAY = 36
FX_RANGE = (800, 2500)

EXAMPLES = ["경쟁사 견적이 5% 낮아지면?", "환율이 1,300원까지 떨어지면?", "후판가가 10% 오르고 납기가 6개월 늦어지면?", "우리 견적가를 3% 낮추면?"]

# ── 문장 다듬기: 한글 숫자·단위를 숫자로 ──
_KNUM = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_KMONTH = {"한": 1, "두": 2, "세": 3, "석": 3, "네": 4, "넉": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}


def _kor_pct(m: re.Match) -> str:
    s = m.group(1)
    if "십" in s:
        a, _, b = s.partition("십")
        n = (_KNUM.get(a, 1) if a else 1) * 10 + (_KNUM.get(b, 0) if b else 0)
    else:
        n = _KNUM[s]
    return f"{n}%"


def _normalize(text: str) -> str:
    t = text.replace("−", "-").replace("–", "-").replace("％", "%").replace("＄", "$")
    t = re.sub(r"(\d),(\d)", r"\1\2", t)                                       # 1,300 → 1300
    t = re.sub(r"(\d)\s*(?:퍼센트|퍼센|퍼|프로)", r"\1%", t)                     # 5퍼 / 5프로 → 5%
    t = re.sub(r"(?<![가-힣])([일이삼사오육칠팔구]?십[일이삼사오육칠팔구]?|[일이삼사오육칠팔구])\s*(?:퍼센트|퍼|프로)", _kor_pct, t)
    t = re.sub(r"(\d+)\s*년\s*반", lambda m: f"{int(m.group(1)) * 12 + 6}개월", t)
    t = re.sub(r"반\s*년", "6개월", t)
    t = re.sub(r"(?<![가-힣])(한|두|세|석|네|넉|다섯|여섯|일곱|여덟|아홉|열)\s*달(?!러)", lambda m: f"{_KMONTH[m.group(1)]}개월", t)
    t = re.sub(r"(?<![가-힣])(일|한)\s*년", "1년", t)
    return t.strip()


def _ga(word: str) -> str:
    """받침에 맞춰 이/가: 환율이, 후판가가"""
    c = word[-1]
    return word + ("이" if "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 else "가")


def _sign(seg: str, num_end: int, explicit: str) -> int:
    """숫자의 부호: 명시한 +/-가 우선, 없으면 숫자 뒤(없으면 앞)에 나오는 올림/내림 표현으로 정한다."""
    if explicit:
        return -1 if explicit == "-" else 1
    for part in (seg[num_end:], seg[:num_end]):
        n, p = NEG.search(part), POS.search(part)
        if n and (not p or n.start() < p.start()):
            return -1
        if p:
            return 1
    return 0


def _fx_level(seg: str) -> Optional[float]:
    """환율 수준(원). '1400원에서 1300원으로' → 1300, '환율 1350이면' → 1350"""
    vals = [float(w.group(1)) for w in WON.finditer(seg)] + [float(b.group(1)) for b in BARE.finditer(seg)]
    vals = [v for v in vals if FX_RANGE[0] <= v <= FX_RANGE[1]]
    return vals[-1] if vals else None


def _usd(seg: str) -> Optional[float]:
    m = USD.search(seg)
    if not m:
        return None
    if m.group(3):
        return float(m.group(3)) / 100          # 500만 달러 → $5M
    return float(m.group(1) or m.group(2))


def _months(m: re.Match) -> int:
    return int(round(float(m.group(1)) * (12 if m.group(2) == "년" else 1)))


def parse(text: str, state: Optional[dict] = None) -> dict:
    """문장 → {'updates', 'special', 'removed', 'notes', 'assumed', 'labels', 'reset', 'intent'}
    special: 입찰 정보가 있어야 계산되는 값 (환율 원 변화, 견적가·경쟁사 $ 금액) → answer() 에서 조건으로 바꾼다."""
    t = _normalize(text)
    out = {"updates": {}, "special": {}, "removed": [], "notes": [], "assumed": [], "labels": {},
           "reset": bool(RESET.search(t)), "intent": None}
    if out["reset"]:
        return out
    marks = []
    for m in _ANCHOR_RE.finditer(t):
        kind = m.lastgroup
        if (kind == "quote" and marks and marks[-1][0] == "comp" and not re.match(r"우리|당사|저희", m.group())
                and re.fullmatch(r"\s*(?:가|이|은|는|도|의|측|쪽|들)?\s*", t[marks[-1][2]:m.start()])):
            marks[-1] = ("comp", marks[-1][1], m.end())          # "경쟁사가 견적을…" 의 견적은 경쟁사 견적
            continue
        if kind == "comp" and re.match(r"\s*(?:보다|대비|에\s*비해)", t[m.end():]):
            kind = "quote"                       # "우리가 경쟁사보다 3% 비싸면" → 우리 견적가
        marks.append((kind, m.start(), m.end()))
    pending: list = []                           # "후판가랑 환율이 5% 오르면" 처럼 값이 뒤에 몰린 조건들 (kind, 원화 여부)

    def put(kind: str, raw_sign: int, size: float, krw_side: bool, assumed: bool, seg: str = ""):
        key = TOPIC_KEY[kind]
        v = raw_sign * (-1 if krw_side else 1) * size
        lo, hi = LIMITS[key]
        if not lo <= v <= hi:
            out["notes"].append(f"{LABEL[key]}{'은' if (ord(LABEL[key][-1]) - 0xAC00) % 28 else '는'} {lo * 100:+.0f}% ~ {hi * 100:+.0f}% 범위만 계산해요.")
            return
        out["updates"][key] = v
        if key == "fx_pct":
            out["updates"]["fx_krw"] = None
            out["special"].pop("fx_delta", None)
            if krw_side:
                out["labels"]["fx_pct"] = f"원화 {'강세' if v < 0 else '약세'}"
            elif seg.startswith("달러"):
                out["labels"]["fx_pct"] = f"달러 {'강세' if v > 0 else '약세'}"
        if key == "quote_pct":
            out["special"].pop("quote_usd", None)
            out["special"].pop("quote_target", None)
        if key == "comp_pct":
            out["special"].pop("comp_usd", None)
        if assumed:
            out["assumed"].append(f"{LABEL[key]} {v * 100:+.0f}%")

    def flush(raw_sign: int, size: Optional[float], assumed: bool):
        for pk, pkrw in pending:
            if pk == "delay":
                if assumed:
                    out["updates"]["delay_months"] = DEFAULT_DELAY
                    out["assumed"].append(f"납기 {DEFAULT_DELAY}개월 지연")
            else:
                put(pk, raw_sign, size, pkrw, assumed)
        pending.clear()

    for i, (kind, st, en) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(t)
        seg, rest = t[st:end], t[en:end]
        if kind == "market":
            out["notes"].append("시장 선가(신조선가) 변화는 아직 조건으로 넣지 않았어요. 경쟁사 견적이나 우리 견적가로 바꿔 물어보세요.")
            continue
        key = TOPIC_KEY[kind]
        krw_side = kind == "fx" and seg.startswith("원화")
        if REMOVE.search(rest) and not PCT.search(seg) and not MONTHS.search(seg):
            out["removed"].append(key)
            continue
        # ── 납기 ──
        if kind == "delay":
            m = MONTHS.search(seg)
            if DELAY_DOWN.search(rest) and not DELAY_UP.search(rest):
                out["notes"].append("납기 단축은 아직 계산하지 않아요. 납기 지연(개월)만 물어볼 수 있어요.")
            elif m:
                n = _months(m)
                if 0 < n <= MAX_DELAY:
                    out["updates"]["delay_months"] = n
                elif n > MAX_DELAY:
                    out["notes"].append(f"납기 지연은 {MAX_DELAY}개월까지만 계산해요.")
            elif DELAY_UP.search(rest):
                out["updates"]["delay_months"] = DEFAULT_DELAY
                out["assumed"].append(f"납기 {DEFAULT_DELAY}개월 지연")
            elif CONNECT.match(rest):
                pending.append((kind, False))
            continue
        # ── 환율: 원 단위 ──
        if kind == "fx":
            lvl = _fx_level(seg)
            if lvl is not None:
                out["updates"]["fx_krw"], out["updates"]["fx_pct"] = lvl, 0.0
                out["special"].pop("fx_delta", None)
                continue
            d = WON.search(seg)
            if d and float(d.group(1)) < FX_RANGE[0]:            # "환율이 100원 떨어지면" → 지금 환율에서 ±100원
                sg = _sign(seg, d.end(), "") * (-1 if krw_side else 1)
                if sg:
                    out["special"]["fx_delta"] = sg * float(d.group(1))
                    out["updates"].pop("fx_pct", None); out["updates"].pop("fx_krw", None)
                    continue
        # ── 후판가는 % 로만 ──
        if kind == "steel" and re.search(r"\d\s*(?:만\s*)?원|톤당", seg) and not PCT.search(seg):
            out["notes"].append("후판가는 % 변화로 물어봐 주세요. (예: 후판가 10% 오르면)")
            continue
        # ── 우리 견적가 · 경쟁사 견적: $ 금액 ──
        if kind in ("quote", "comp") and not PCT.search(seg):
            usd = _usd(seg)
            if usd is not None:
                sg = _sign(seg, 0, "")
                if kind == "quote" and usd >= 30:                  # $30M 이상이면 변화량이 아니라 목표 견적가로 본다 (예: 180M으로)
                    out["special"]["quote_target"] = usd
                    out["updates"].pop("quote_pct", None)
                    continue
                if sg:
                    out["special"][f"{kind}_usd"] = sg * usd
                    out["updates"].pop(key, None)
                    continue
        # ── % 조건 ──
        m = PCT.search(seg)
        if m:
            raw = _sign(seg, m.end(), m.group(1))
            if raw == 0:
                out["notes"].append(f"{_ga(LABEL[key])} 올라가는지 내려가는지 알려 주세요. (예: {LABEL[key]} 5% 내리면)")
                pending.clear()
                continue
            size = float(m.group(2)) / 100
            put(kind, raw, size, krw_side, False, seg)
            flush(raw, size, False)
            continue
        raw = _sign(rest, 0, "")
        if raw:
            put(kind, raw, DEFAULT_PCT, krw_side, True, seg)
            flush(raw, DEFAULT_PCT, True)
        elif CONNECT.match(rest):
            pending.append((kind, krw_side))

    # ── 조건 이름 없이 숫자만: "그럼 10%면?", "6개월이면?", "1,250원이면?" ──
    ask_which = False
    if not marks:
        st = state or {}
        active = [k for k in ("comp_pct", "steel_pct", "quote_pct") if st.get(k)]
        if st.get("fx_pct") or st.get("fx_krw"):
            active.append("fx_pct")
        m, mm, lvl = PCT.search(t), MONTHS.search(t), _fx_level(t)
        usd = _usd(t)
        if usd is not None and usd >= 30 and not m:                # "180M으로 내면?" → 목표 견적가
            out["special"]["quote_target"] = usd
        elif usd is not None and not m and _sign(t, 0, ""):         # "$3M 낮추면?" → 우리 견적가 ±$3M
            out["special"]["quote_usd"] = _sign(t, 0, "") * usd
        elif mm:
            n = _months(mm)
            if 0 < n <= MAX_DELAY:
                out["updates"]["delay_months"] = n
            else:
                out["notes"].append(f"납기 지연은 {MAX_DELAY}개월까지만 계산해요.")
        elif lvl is not None and re.search(r"원|환율", t) or (lvl is not None and "fx_pct" in active):
            out["updates"]["fx_krw"], out["updates"]["fx_pct"] = lvl, 0.0
        elif m and len(active) == 1:
            key = active[0]
            kind = {v: k for k, v in TOPIC_KEY.items()}[key]
            raw = _sign(t, m.end(), m.group(1)) or (1 if (st.get(key) or 0) > 0 else -1 if st.get(key) else 0)
            if raw:
                put(kind, raw, float(m.group(2)) / 100, False, False)
            else:
                out["notes"].append(f"{_ga(LABEL[key])} 올라가는지 내려가는지 알려 주세요. (예: {LABEL[key]} 10% 내리면)")
        elif m:
            ask_which = True

    # ── 모델에 없는 질문은 솔직하게 알린다 ──
    if re.search(r"헤지|헷지", t):
        out["notes"].append("환헤지는 아직 모델에 들어 있지 않아 계산하지 못해요. 지금은 환율이 바뀌는 경우만 볼 수 있어요.")
    if re.search(r"실주|과거|비슷한|유사|이력|지난\s*입찰", t):
        out["notes"].append("지난 입찰 결과는 위쪽 '과거 이력' 메뉴에서 볼 수 있어요.")
    if re.search(r"선주|LNG|lng|스크러버|사양|연료|척수|선박\s*크기|TEU|teu", t):
        out["notes"].append("선주·사양·척수 같은 항목은 학습 데이터가 적어 시나리오 조건으로 쓰지 않아요.")
    if re.search(r"엔화|유로|위안", t):
        out["notes"].append("환율은 원/달러만 계산해요. 계약 통화가 달러라서예요.")
    if re.search(r"인건비|임금|노무비|전체\s*원가|건조\s*비|(?<!손익)원가", t) and "steel_pct" not in out["updates"]:
        out["notes"].append("원가는 지금 후판가 변화로만 볼 수 있어요. (예: 후판가 10% 오르면)")

    if ask_which and not out["notes"]:                         # 다른 안내(환헤지 등)가 이미 있으면 그쪽이 답
        out["notes"].append("어떤 조건에 적용할지 같이 말해 주세요. (예: 환율 10% 떨어지면, 후판가 10% 오르면)")

    if not out["updates"] and not out["special"] and not out["removed"]:
        if DECIDE.search(t):
            out["intent"] = "decide"
        elif WORST.search(t):
            out["intent"] = "worst"
        elif HELP.search(t):
            out["intent"] = "help"
        elif THANKS.search(t):
            out["intent"] = "thanks"
        elif INFO.search(t):
            out["intent"] = "info"
    return out


def describe(params: dict) -> list:
    """적용 중인 조건을 화면 칩 문구로."""
    chips = []
    sg = lambda v: f"{'+' if v > 0 else '-'}{round(abs(v) * 100, 1):g}%"
    if params.get("comp_pct"): chips.append({"key": "comp_pct", "label": f"경쟁사 견적 {sg(params['comp_pct'])}"})
    if params.get("steel_pct"): chips.append({"key": "steel_pct", "label": f"후판가 {sg(params['steel_pct'])}"})
    if params.get("fx_krw"): chips.append({"key": "fx_krw", "label": f"환율 {params['fx_krw']:,.0f}원"})
    elif params.get("fx_pct"): chips.append({"key": "fx_pct", "label": f"환율 {sg(params['fx_pct'])}"})
    if params.get("delay_months"): chips.append({"key": "delay_months", "label": f"납기 +{params['delay_months']}개월"})
    if params.get("quote_pct"): chips.append({"key": "quote_pct", "label": f"우리 견적가 {sg(params['quote_pct'])}"})
    return chips


def _p(v: Optional[float], d: int = 0) -> str:
    return "–" if v is None else f"{v * 100:.{d}f}%"


def _m(v: Optional[float]) -> str:
    return "–" if v is None else f"{'-' if v < 0 else ''}${abs(v):.1f}M"


def _metrics(s: dict) -> list:
    return [{"label": "낙찰확률", "value": _p(s["p_now"])}, {"label": "예상 마진", "value": _p(s["margin_mean_now"], 1)},
            {"label": "적자확률", "value": _p(s["loss_prob_now"])}]


def _reply(params: dict, prev: dict, lines: list, notes=(), metrics=(), understood=(), changed=False, source=None) -> dict:
    p = params if changed else prev
    return {"params": p, "active": describe(p), "understood": list(understood), "notes": list(notes), "metrics": list(metrics),
            "lines": lines, "changed": changed, **({"source": source} if source else {})}


def _resolve_special(be, bid_id: str, prev: dict, parsed: dict, notes: list) -> dict:
    """입찰 정보가 있어야 계산되는 값(환율 원 변화, $ 금액)을 조건으로 바꾼다."""
    up, sp = dict(parsed["updates"]), parsed["special"]
    if not sp:
        return up
    raw = be.raw.loc[bid_id]
    if "fx_delta" in sp:
        now = prev.get("fx_krw") or float(raw.expected_fx) * (1 + (prev.get("fx_pct") or 0))
        new = round(now + sp["fx_delta"], 1)
        if FX_RANGE[0] <= new <= FX_RANGE[1]:
            up["fx_krw"], up["fx_pct"] = new, 0.0
            parsed["labels"]["fx_krw"] = f"환율 {now:,.0f}원 → {new:,.0f}원"
        else:
            notes.append(f"환율은 {FX_RANGE[0]:,}~{FX_RANGE[1]:,}원 사이만 계산해요.")
    q0 = float(raw.quote)
    if "quote_usd" in sp or "quote_target" in sp:
        v = (sp["quote_target"] / q0 - 1) if "quote_target" in sp else (prev.get("quote_pct") or 0) + sp["quote_usd"] / q0
        lo, hi = LIMITS["quote_pct"]
        if lo <= v <= hi:
            up["quote_pct"] = round(v, 4)
            parsed["labels"]["quote_pct"] = f"우리 견적가 {_m(q0 * (1 + v))}"
        else:
            notes.append(f"우리 견적가는 제안가({_m(q0)}) 대비 {lo * 100:+.0f}% ~ {hi * 100:+.0f}% 범위만 계산해요.")
    if "comp_usd" in sp:
        v = sp["comp_usd"] / float(raw.market_price)              # 경쟁사 견적은 시장 기준가 근처라고 보고 % 로 바꾼다
        lo, hi = LIMITS["comp_pct"]
        if lo <= v <= hi:
            up["comp_pct"] = round(v, 4)
            parsed["labels"]["comp_pct"] = f"경쟁사 견적 {'+' if v > 0 else '-'}${abs(sp['comp_usd']):g}M"
        else:
            notes.append(f"경쟁사 견적은 {lo * 100:+.0f}% ~ {hi * 100:+.0f}% 범위만 계산해요.")
    return up


def _summary_lines(be, bid_id: str, params: dict) -> tuple:
    cmp_ = be.compare(bid_id, params)
    b, s = cmp_["base"]["summary"], cmp_["scenario"]["summary"]
    active = describe(params)
    head = f"지금 조건({', '.join(c['label'] for c in active)})" if active else "지금은 기준 조건"
    lines = [f"{head}에서 제안가 {_m(s['quote_now'])} 기준으로 낙찰확률 {_p(s['p_now'])}, 예상 마진 {_p(s['margin_mean_now'], 1)}, "
             f"적자 확률 {_p(s['loss_prob_now'])}예요.",
             f"기대가치는 척당 {_m(s['ev_now'])}, 손익분기 선가는 {_m(s['bep'])}예요."]
    if s["recommended"] is not None:
        band = f" (권장 구간 {_m(s['band_lo'])} ~ {_m(s['band_hi'])})" if s.get("band_hi") is not None else ""
        lines.append(f"권장 견적가는 {_m(s['recommended'])}{band}예요.")
    else:
        lines.append("이 조건에서는 기대가치가 0 이하라 권장 견적가가 없어요.")
    if active:
        lines.append(f"기준 조건이었다면 낙찰확률 {_p(b['p_now'])}, 예상 마진 {_p(b['margin_mean_now'], 1)}, 권장 견적가 {_m(b['recommended'])}였어요.")
    return lines, _metrics(s), cmp_["source"]


def _verdict(be, bid_id: str, params: dict) -> str:
    """'이 입찰 따야 돼?' → 결정은 담당자가 하고, 숫자로 본 판단 근거만 한 줄로."""
    s = be.compare(bid_id, params)["scenario"]["summary"]
    q, lo, hi = s["quote_now"], s.get("band_lo"), s.get("band_hi")
    if q < s["bep"]:
        v = f"지금 제안가 {_m(q)}는 손익분기 선가 {_m(s['bep'])}보다 낮아서, 따내면 손해예요. 견적을 올리거나 들어가지 않는 쪽을 검토하세요."
    elif lo is None:
        v = "이 조건에서는 어느 견적가에서도 기대가치가 0 이하예요. 들어가더라도 남는 게 없을 가능성이 커요."
    elif q < lo - 0.05:
        v = f"지금 제안가는 권장 구간({_m(lo)} ~ {_m(hi)})보다 싸요. 견적을 올려도 기대가치가 비슷하거나 더 커요."
    elif q > hi + 0.05:
        v = f"지금 제안가는 권장 구간({_m(lo)} ~ {_m(hi)})보다 비싸요. 낮추면 낙찰 가능성을 높일 수 있어요."
    else:
        v = f"지금 제안가는 권장 구간({_m(lo)} ~ {_m(hi)}) 안이라 숫자로는 들어갈 만해요."
    return v + " (최종 결정은 숫자에 안 잡히는 요인까지 보고 담당자가 판단해 주세요.)"


def answer(be, bid_id: str, message: str, state: dict) -> dict:
    prev = {**ZERO, **{k: v for k, v in (state or {}).items() if v is not None or k == "fx_krw"}}
    try:
        return _answer(be, bid_id, message, prev)
    except KeyError:
        return _reply(prev, prev, ["이 입찰은 지금 계산할 수 없어요. 낙찰확률 모델 데이터에 없는 입찰이에요. 다른 입찰을 골라 주세요."])
    except Exception:                                          # 해석 규칙의 빈틈 때문에 화면이 멈추지 않도록
        traceback.print_exc()
        return _reply(prev, prev, ["질문을 처리하다 문제가 생겼어요. 조금 다르게 물어봐 주세요."] + EXAMPLES[:2])


def _answer(be, bid_id: str, message: str, prev: dict) -> dict:
    parsed = parse(message, prev)
    if parsed["reset"]:
        return _reply(dict(ZERO), prev, ["조건을 모두 기준으로 되돌렸어요. 다시 물어보세요."], changed=True)
    notes = list(dict.fromkeys(parsed["notes"]))
    if parsed["assumed"]:
        notes.insert(0, f"숫자가 없어서 이렇게 가정했어요: {', '.join(dict.fromkeys(parsed['assumed']))}. 다른 폭이 궁금하면 숫자를 같이 말해 주세요.")

    updates = _resolve_special(be, bid_id, prev, parsed, notes)
    params = {**prev, **updates}
    removed = list(dict.fromkeys(parsed["removed"]))
    removed_names = [LABEL[k] for k in removed if prev.get(k) or (k == "fx_pct" and prev.get("fx_krw"))]
    for k in removed:
        params[k] = 0
        if k == "fx_pct":
            params["fx_krw"] = None

    if not updates and not removed_names:
        if parsed["intent"] == "help":
            return _reply(params, prev, ["경쟁사 견적·후판가·환율·납기·우리 견적가가 바뀌면 결과가 어떻게 달라지는지 계산해 드려요. "
                                         "여러 조건을 한 문장에 섞어도 되고, 숫자 없이 물어보면 5%(납기는 3개월)로 가정해요. 이렇게 물어보세요."] + EXAMPLES
                          + ["'지금 낙찰확률은?'처럼 물으면 현재 결과를 요약하고, '환율 조건 빼줘'·'초기화'로 조건을 뺄 수 있어요."], notes)
        if parsed["intent"] == "worst":
            return _reply(params, prev, ["최악·최선은 사람마다 기준이 달라서 조건을 직접 정해 물어봐 주세요.",
                                         "예: 경쟁사가 10% 싸게 들어오고 환율이 1,300원이면?", "예: 후판가가 20% 오르고 납기가 6개월 늦어지면?"], notes)
        if parsed["intent"] == "decide":
            lines, metrics, src = _summary_lines(be, bid_id, prev)
            return _reply(params, prev, lines + [_verdict(be, bid_id, prev)], notes, metrics, source=src)
        if parsed["intent"] == "thanks":
            return _reply(params, prev, ["천만에요. 다른 조건도 궁금하면 물어보세요."], notes)
        if parsed["intent"] == "info" or removed:
            lines, metrics, src = _summary_lines(be, bid_id, prev)
            if removed:
                lines.insert(0, "빼라고 한 조건은 지금 걸려 있지 않아요.")
            return _reply(params, prev, lines, notes, metrics, source=src)
        lines = [] if notes else ["조건을 읽지 못했어요. 이렇게 물어보세요."] + EXAMPLES
        return _reply(params, prev, lines, notes)

    cmp_ = be.compare(bid_id, params)
    b, s, dec = cmp_["base"]["summary"], cmp_["scenario"]["summary"], cmp_["decomposition"]
    understood = describe({**ZERO, **updates})
    said = parsed["labels"]
    grp = lambda k: "fx" if k.startswith("fx") else k

    def name(u: dict) -> str:
        k = u["key"]
        if k in ("fx_krw", "quote_pct", "comp_pct") and k in said:
            return said[k]
        if k == "fx_pct" and "fx_pct" in said:
            return f"{said['fx_pct']}({u['label']})"
        return u["label"]

    new_keys = {grp(u["key"]) for u in understood} | {grp(k) for k in removed}
    kept = [c for c in describe(params) if grp(c["key"]) not in new_keys]
    lines = []
    if removed_names:
        lines.append(f"{', '.join(removed_names)} 조건을 뺐어요.")
    if understood:
        lines.append(f"{' · '.join(name(u) for u in understood)} 조건으로 다시 계산했어요."
                     + (f" 앞서 적용한 {', '.join(c['label'] for c in kept)}도 함께 반영했어요." if kept else ""))
    elif kept:
        lines.append(f"남은 조건({', '.join(c['label'] for c in kept)})으로 다시 계산했어요.")
    else:
        lines.append("이제 기준 조건과 같아요.")
    dp = (s["p_now"] - b["p_now"]) * 100
    if abs(dp) < 0.5:   # 환율·후판가만 바뀌면 낙찰확률은 그대로라 "63% → 63%(+0.0%p)" 대신 그대로라고 말한다
        lines.append(f"낙찰확률은 {_p(s['p_now'])}로 그대로예요. 기대가치는 {_m(b['ev_now'])} → {_m(s['ev_now'])}(척당)이에요.")
    else:
        lines.append(f"낙찰확률은 {_p(b['p_now'])} → {_p(s['p_now'])}({dp:+.1f}%p), 기대가치는 {_m(b['ev_now'])} → {_m(s['ev_now'])}(척당)이에요.")
    dl = (s["loss_prob_now"] - b["loss_prob_now"]) * 100
    if abs(dl) >= 0.5:
        lines.append(f"환율·원가로 적자가 날 확률은 {_p(b['loss_prob_now'])} → {_p(s['loss_prob_now'])}예요.")
    if abs(dec["total"]) >= 0.05:
        main = "낙찰확률이 달라지는 영향" if abs(dec["prob_effect"]) >= abs(dec["profit_effect"]) else "건당 이익이 달라지는 영향"
        lines.append(f"기대가치 변화({dec['total']:+.1f}M)는 주로 {main}이에요.")
    if abs(s["bep"] - b["bep"]) >= 0.05:   # 권장가가 왜 움직였는지: 원가(손익분기 선가)가 바뀐 경우
        lines.append(f"손익분기 선가가 {_m(b['bep'])} → {_m(s['bep'])}로 {'올라가요' if s['bep'] > b['bep'] else '내려가요'}.")
    if s["recommended"] is None and b["recommended"] is not None:
        lines.append("이 조건에서는 기대가치가 0 이하라 권장 견적가가 없어요.")
    elif s["recommended"] is not None and b["recommended"] is not None and abs(s["recommended"] - b["recommended"]) >= 0.05:
        lines.append(f"권장 견적가는 {_m(b['recommended'])} → {_m(s['recommended'])}로 바뀌어요.")
    if s["quote_now"] < s["bep"]:
        lines.append(f"주의: 이 조건에서 제안가 {_m(s['quote_now'])}는 손익분기 선가 {_m(s['bep'])}보다 낮아요. 따내면 손해예요.")
    return _reply(params, prev, lines, notes, _metrics(s), understood, changed=True, source=cmp_["source"])