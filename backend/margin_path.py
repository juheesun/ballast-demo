"""MVP2 · 계약부터 인도까지 마진 범위가 어떻게 벌어지는지 (시나리오 화면의 '마진 범위' 그래프) + 환헤지 계산.

환율·원가 위험은 견적리스크 화면과 같은 계산(backend/quote_risk.py: 원가 통화 구분·대금 분할 기본 가정)을 쓴다.
같은 난수(같은 seed, 같은 뽑는 순서)로 환율 경로를 만들고, 달마다 '아직 안 받은 대금과 아직 안 산 달러 원가를
그 시점 환율로 정산한다면'의 마진 분포(10·50·90%, 평균, 적자확률)를 계산한다.
마지막 달(인도 시점) 값은 카드의 '예상 마진'·'적자확률'과 정확히 같다.

  매출(t) = Σ 분할비율_k × 환율변화(min(받는 시점_k, t))
  원가(t) = (1 + 원가초과 × t/개월수) × [ 원화 원가 + 달러 원가 × 환율변화(min(구매 시점, t)) ]
  마진(t) = 1 − 원가(t) × 손익분기선가 ÷ (견적가 × 매출(t))

· 원가 초과는 건조가 진행되면서 조금씩 드러난다고 보고 t/개월수 만큼만 반영한다 (인도 시점에 전부).
· 공정 이름(강재절단·탑재·진수)은 납기를 4등분한 화면용 표시다.
· modeling/ 은 고치지 않는다. 엔진(backend/engine.py)이 만든 요약값(견적가·손익분기·개월수)만 받아 쓴다.
"""
from __future__ import annotations
import json
from typing import Optional
import numpy as np

from .quote_risk import USD_COST_AT, breakeven_fx, defaults, factors, fx_basis, sim_paths

MILESTONES = [(0.0, "계약"), (0.25, "강재절단"), (0.5, "탑재"), (0.75, "진수"), (1.0, "인도")]
_result_cache: dict = {}


def _series(mm, quote: float, bep: float, months: int, a: dict, g0: float = 1.0) -> list:
    months = max(int(months), 1)
    g, ov = sim_paths(mm, months)
    t = np.arange(months + 1)
    usd = sum(c["share"] * c["usd_share"] for c in a["costs"])
    upto = lambda at: g[:, np.minimum(int(round(at * months)), t)]                         # (n, months+1)
    R = g0 * sum(m["weight"] * upto(m["at"]) for m in a["milestones"])                     # g0 = 반사실 환율 출발점 (quote_risk.fx_basis)
    C = (1.0 + ov[:, None] * (t / months)[None, :]) * ((1.0 - usd) + usd * g0 * upto(USD_COST_AT))
    margin = 1.0 - C * bep / (quote * R)
    p10, p50, p90 = np.percentile(margin, [10, 50, 90], axis=0)
    mean, loss = margin.mean(axis=0), (margin < 0).mean(axis=0)
    r = lambda v: round(float(v), 4)
    return [{"month": int(k), "p10": r(p10[k]), "p50": r(p50[k]), "p90": r(p90[k]), "mean": r(mean[k]), "loss_prob": r(loss[k])}
            for k in t]


def _one(be, bid_id: str, params: Optional[dict]) -> dict:
    s = be.curve(bid_id, params)["summary"]
    months, a = int(round(s["months"])), defaults(bid_id)
    bep, g0, _ = fx_basis(be, bid_id, s, a)
    return {"quote": s["quote_now"], "bep": s["bep"], "months": months, "points": _series(be.mm, s["quote_now"], bep, months, a, g0)}


def margin_path(be, bid_id: str, params: Optional[dict] = None) -> dict:
    key = (bid_id, json.dumps(params or {}, sort_keys=True, default=str))
    if key not in _result_cache:
        base, scen = _one(be, bid_id, None), _one(be, bid_id, params)
        m = scen["months"]
        _result_cache[key] = {
            "source": be.source, "bid_id": bid_id, "base": base, "scenario": scen,
            "milestones": [{"month": int(round(f * m)), "label": lab} for f, lab in MILESTONES],
        }
    return _result_cache[key]


def hedge(be, bid_id: str, params: Optional[dict] = None, ratio: float = 0.0) -> dict:
    """환헤지 계산: 받을 달러의 ratio 만큼을 지금 조건의 환율로 고정하면 인도 시점 마진·적자확률이 어떻게 바뀌나.
    계산은 견적리스크와 같은 quote_risk.factors (헤지 비용 = 선물환 포인트는 0으로 가정). 헤지 0% 이면 카드 값과 같다.
    버틸 수 있는 환율이 None 이면 환율이 아무리 내려도 적자가 나지 않는다는 뜻 (헤지·달러 원가로 다 막힘)."""
    s = be.curve(bid_id, params)["summary"]
    months, q, fx = int(round(s["months"])), s["quote_now"], s["fx_assumed"]
    a = defaults(bid_id)
    bep, g0, fx_bid = fx_basis(be, bid_id, s, a)
    g, ov = sim_paths(be.mm, months)
    r = lambda v: round(float(v), 4)

    def one(h: float) -> dict:
        C, R, usd = factors(g, ov, months, a, h, g0)
        m = 1.0 - bep * C / (q * R)
        fb = breakeven_fx(q, bep, usd, a, h, fx_bid, g0)
        return {"ratio": r(h), "loss_prob": r((m < 0).mean()), "margin_mean": r(m.mean()),
                "margin_p10": r(np.percentile(m, 10)), "margin_p90": r(np.percentile(m, 90)),
                "fx_breakeven": None if fb is None else round(fb, 1)}
    return {"source": be.source, "bid_id": bid_id, "fx_assumed": fx, "none": one(0.0), "hedged": one(float(ratio))}
