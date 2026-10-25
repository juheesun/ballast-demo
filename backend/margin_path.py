"""MVP2 · 계약부터 인도까지 마진 범위가 어떻게 벌어지는지 (시나리오 화면의 '마진 범위' 그래프).

modeling/ 의 MarginModel 과 똑같은 난수(같은 seed, 같은 뽑는 순서)로 환율 경로를 만들고,
달마다 '그 시점 환율로 정산한다면'의 마진 분포(10·50·90%, 평균, 적자 확률)를 계산한다.
마지막 달(인도 시점) 값은 카드의 '예상 마진'·'적자 확률'과 정확히 같다.

  마진(t) = 1 − (1 + 원가초과 × t/개월수) × 손익분기선가 ÷ (견적가 × 환율변화(t))

· 원가 초과는 건조가 진행되면서 조금씩 드러난다고 보고 t/개월수 만큼만 반영한다 (인도 시점에 전부).
· 공정 이름(강재절단·탑재·진수)은 납기를 4등분한 화면용 표시이고 계산에는 쓰지 않는다.
· modeling/ 은 고치지 않는다. 엔진(backend/engine.py)이 만든 요약값(견적가·손익분기·개월수)만 받아 쓴다.
"""
from __future__ import annotations
import json
from typing import Optional
import numpy as np

MILESTONES = [(0.0, "계약"), (0.25, "강재절단"), (0.5, "탑재"), (0.75, "진수"), (1.0, "인도")]
_paths_cache: dict = {}
_result_cache: dict = {}


def _paths(mm, months: int):
    """MarginModel.shocks() 와 같은 난수 순서로 뽑되, 합계 대신 달마다의 누적 경로를 남긴다."""
    months = max(int(months), 1)
    key = (id(mm), months)
    if key not in _paths_cache:
        rng = np.random.default_rng(mm.seed)
        r = rng.choice(mm.fx_returns, size=(mm.n_sims, months), replace=True)
        ov = rng.choice(mm.cost_overrun_values, size=mm.n_sims, p=mm.cost_overrun_probs)
        g = np.exp(np.concatenate([np.zeros((mm.n_sims, 1)), np.cumsum(r, axis=1)], axis=1))   # (n, months+1), t=0 은 1
        _paths_cache[key] = (g, ov)
    return _paths_cache[key]


def _series(mm, quote: float, bep: float, months: int) -> list:
    months = max(int(months), 1)
    g, ov = _paths(mm, months)
    frac = np.arange(months + 1) / months
    margin = 1.0 - (1.0 + ov[:, None] * frac[None, :]) * bep / (quote * g)                  # (n, months+1)
    p10, p50, p90 = np.percentile(margin, [10, 50, 90], axis=0)
    mean, loss = margin.mean(axis=0), (margin < 0).mean(axis=0)
    r = lambda v: round(float(v), 4)
    return [{"month": t, "p10": r(p10[t]), "p50": r(p50[t]), "p90": r(p90[t]), "mean": r(mean[t]), "loss_prob": r(loss[t])}
            for t in range(months + 1)]


def _one(be, bid_id: str, params: Optional[dict]) -> dict:
    s = be.curve(bid_id, params)["summary"]
    months = int(round(s["months"]))
    return {"quote": s["quote_now"], "bep": s["bep"], "months": months, "points": _series(be.mm, s["quote_now"], s["bep"], months)}


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
