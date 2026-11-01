"""MVP1 · 견적 리스크 화면의 환율·원가 위험 계산 (원가 통화 구분 · 대금 분할 · 환헤지 · 원화 금액 · 과거 검증).

modeling/ 의 MarginModel 은 '원가 전부 원화 · 대금은 인도 때 한 번에 · 헤지 없음'을 가정해 환율 위험을 크게 본다.
여기서는 같은 난수(같은 seed, 같은 뽑는 순서)로 환율 경로를 만들되, 세 가지를 더 반영한다.

  원가  = (1 + 원가초과) × 손익분기선가 × [ (1 − 달러원가비중) + 달러원가비중 × g(기자재 구매 시점) ]
  매출  = 견적가 × Σ 분할비율_k × [ 헤지비율 + (1 − 헤지비율) × g(받는 시점_k) ]
  마진  = 1 − 원가 ÷ 매출,   g(t) = t 개월 뒤 환율 ÷ 입찰 시점 환율

· 달러로 사는 원가(수입 엔진·기자재)는 환율이 내리면 같이 싸지므로 환율 위험은 원화 원가에만 걸린다.
· 헤지는 받을 달러의 일부를 입찰 시점 환율로 고정한다고 본다 (선물환 포인트·수수료는 0으로 가정).
· 원가 비중·달러 비중·분할 비율·헤지 비율은 전부 팀 가정이고, 화면에서 '가정' 배지로 바로 고칠 수 있다.
· 원가 비중·분할 비율·헤지 0%를 (원화 100%, 인도 100%)로 두면 MarginModel 결과와 정확히 같다.
· 낙찰확률·기대가치·권장가는 엔진(backend/engine.py) 값을 그대로 쓴다. 기대가치 공식에는 환율이 들어가지 않는다.
"""
from __future__ import annotations
import json
from typing import Optional
import numpy as np

from .engine import bc

SHIP_TYPE = "컨테이너선"          # dataset.json 의 입찰은 전부 컨테이너선(size_teu)
LARGE_TEU = 10000                 # 이 이상은 대형, 미만은 중소형(피더) 기본값을 쓴다

# 원가 구성 기본값 (※ 팀 가정. 선종·규모별). 후판·강재 10% 는 시나리오 엔진의 후판 비중(steel_share)과 맞춘 값.
COST_ITEMS = [("steel", "후판·강재"), ("labor", "인건비"), ("equip", "엔진·기자재"), ("etc", "기타")]
COST_SHARE = {"large": {"steel": 0.10, "labor": 0.30, "equip": 0.50, "etc": 0.10},
              "small": {"steel": 0.10, "labor": 0.35, "equip": 0.45, "etc": 0.10}}
COST_USD = {"steel": 0.0, "labor": 0.0, "equip": 0.6, "etc": 0.2}     # 항목 안에서 달러로 사는 비중
USD_COST_AT = 0.5                 # 달러 원가를 치르는 시점 (납기 대비, 0.5 = 중간 탑재 무렵)
# 대금 분할 기본값: 계약·착공·진수·인도에 20/20/20/40. at = 납기 대비 받는 시점
MILESTONES = [("contract", "계약", 0.0, 0.2), ("start", "착공", 0.25, 0.2), ("launch", "진수", 0.75, 0.2), ("delivery", "인도", 1.0, 0.4)]
LOSS_TARGET = 0.10                # '안전 시작 견적가' 기준: 적자확률이 이 값 이하가 되는 가장 낮은 견적가
BACKTEST_FROM = "2010-01"

_paths_cache: dict = {}
_ship_cache: dict = {}


def _r(v, nd=4):
    return None if v is None else round(float(v), nd)


def ship_info(bid_id: str) -> dict:
    """선종·규모·척수 (dataset.json). 엔진 원본표(load_raw)에는 없어서 따로 읽는다."""
    if not _ship_cache:
        for g in json.load(open(bc.DATASET, encoding="utf-8")):
            for r in [g["real"]] + g.get("scenarios", []):
                s = r["ship"]
                _ship_cache[r["bid_id"]] = {"type": SHIP_TYPE, "size_teu": s.get("size_teu"), "num_ships": int(s.get("num_ships") or 1)}
    return _ship_cache.get(bid_id, {"type": SHIP_TYPE, "size_teu": None, "num_ships": 1})


def defaults(bid_id: str) -> dict:
    teu = ship_info(bid_id)["size_teu"] or 0
    size = "large" if teu >= LARGE_TEU else "small"
    return {
        "basis": f"{SHIP_TYPE} {'대형(1만 TEU 이상)' if size == 'large' else '중소형(1만 TEU 미만)'} 기본값",
        "costs": [{"key": k, "label": lab, "share": COST_SHARE[size][k], "usd_share": COST_USD[k]} for k, lab in COST_ITEMS],
        "milestones": [{"key": k, "label": lab, "at": at, "weight": w} for k, lab, at, w in MILESTONES],
        "hedge": 0.0, "loss_target": LOSS_TARGET,
    }


def _merge(bid_id: str, a: Optional[dict]) -> tuple:
    """화면에서 보낸 가정을 기본값에 덮고, 합이 100%가 아니면 비율대로 나눈다."""
    d, a, notes = defaults(bid_id), a or {}, []
    labels = {c["key"]: c["label"] for c in d["costs"]} | {m["key"]: m["label"] for m in d["milestones"]}
    for k in ("costs", "milestones"):
        if a.get(k):
            d[k] = [{**x, "label": x.get("label") or labels.get(x["key"], x["key"])} for x in a[k]]
    for k in ("hedge", "loss_target"):
        if a.get(k) is not None:
            d[k] = float(a[k])
    for k, field, name in (("costs", "share", "원가 비중"), ("milestones", "weight", "대금 분할 비율")):
        tot = sum(x[field] for x in d[k])
        if tot <= 0:
            d[k] = defaults(bid_id)[k]
            notes.append(f"{name} 합계가 0이라 기본값으로 계산했어요.")
        elif abs(tot - 1) > 0.005:
            notes.append(f"{name} 합계가 {tot * 100:.0f}%라 비율대로 나눠 계산했어요.")
            for x in d[k]:
                x[field] = x[field] / tot
    return d, notes


def _paths(mm, months: int):
    """MarginModel.shocks() 와 같은 난수 순서. 달마다의 누적 환율 변화 g(t) (n, months+1) 와 원가 초과를 돌려준다."""
    months = max(int(months), 1)
    key = (id(mm), months)
    if key not in _paths_cache:
        rng = np.random.default_rng(mm.seed)
        r = rng.choice(mm.fx_returns, size=(mm.n_sims, months), replace=True)
        ov = rng.choice(mm.cost_overrun_values, size=mm.n_sims, p=mm.cost_overrun_probs)
        g = np.exp(np.concatenate([np.zeros((mm.n_sims, 1)), np.cumsum(r, axis=1)], axis=1))
        _paths_cache[key] = (g, ov)
    return _paths_cache[key]


def _factors(g, ov, months: int, a: dict, hedge: float):
    """시뮬레이션마다의 원가 배수 C 와 매출 배수 R (둘 다 '입찰 시점 환율·원가초과 0' 이면 1)."""
    usd = sum(c["share"] * c["usd_share"] for c in a["costs"])
    g_pay = g[:, int(round(USD_COST_AT * months))]
    C = (1.0 + ov) * ((1.0 - usd) + usd * g_pay)
    R = sum(m["weight"] * (hedge + (1.0 - hedge) * g[:, int(round(m["at"] * months))]) for m in a["milestones"])
    return C, R, usd


def _fx_breakeven(q: float, bep: float, usd: float, a: dict, hedge: float, fx0: float) -> Optional[float]:
    """환율이 입찰 직후 F 로 옮겨 가 계속 머문다면, 마진이 0 이 되는 F. (계약금은 이미 입찰 환율로 받는다)
    w0 + (1−w0)(h + (1−h)x) = (BEP/q)·((1−u) + u·x)  →  x = F / 입찰환율"""
    w0 = sum(m["weight"] for m in a["milestones"] if m["at"] <= 0)
    k = bep / q
    slope = (1 - w0) * (1 - hedge) - k * usd
    if slope <= 1e-9:
        return None                              # 환율이 아무리 내려도 적자가 나지 않음 (헤지·달러 원가로 다 막힘)
    x = (k * (1 - usd) - w0 - (1 - w0) * hedge) / slope
    return None if x <= 0 else x * fx0


def _backtest(mm, months: int) -> dict:
    """과거 환율로 시뮬레이션 범위 검증: 2010년 이후 '납기 길이' 구간을 한 달씩 밀며, 실제 환율 변화가 10~90% 범위에 든 비율."""
    fx = json.load(open(bc.FX_HISTORY, encoding="utf-8"))["monthly"]
    fx = sorted((r for r in fx if r["year_month"] >= BACKTEST_FROM), key=lambda r: r["year_month"])
    s = np.array([r["usd_krw"] for r in fx])
    g, _ = _paths(mm, months)
    lo, hi = np.percentile(g[:, -1], [10, 90])
    if len(s) <= months:
        return {"n": 0, "months": months}
    actual = s[months:] / s[:-months]
    return {"months": months, "n": int(len(actual)), "from": fx[0]["year_month"], "to": fx[-1]["year_month"],
            "lo": _r(lo), "hi": _r(hi), "inside": _r(((actual >= lo) & (actual <= hi)).mean()),
            "below": _r((actual < lo).mean()), "above": _r((actual > hi).mean()), "target": 0.8}


def evaluate(be, bid_id: str, assumptions: Optional[dict] = None) -> dict:
    a, notes = _merge(bid_id, assumptions)
    cur = be.curve(bid_id)                                       # 낙찰확률·기대가치·권장가 (엔진 값)
    s0, grid0 = cur["summary"], cur["grid"]
    raw = be.raw.loc[bid_id]
    fx0, bep, months = float(raw.expected_fx), float(s0["bep"]), int(round(s0["months"]))
    q_now, hedge, target = float(s0["quote_now"]), a["hedge"], a["loss_target"]
    g, ov = _paths(be.mm, months)
    C, R, usd = _factors(g, ov, months, a, hedge)
    ship = ship_info(bid_id)
    eok = fx0 / 100                                              # $M → 억 원 (입찰 시점 환율)

    quotes = np.array([r["quote"] for r in grid0])
    margin = 1.0 - (bep * C)[None, :] / (quotes[:, None] * R[None, :])          # (견적가, 시뮬레이션)
    loss = (margin < 0).mean(axis=1)
    p10, p50, p90 = np.percentile(margin, [10, 50, 90], axis=1)
    profit_usd = (quotes[:, None] * R[None, :] - bep * C[None, :]).mean(axis=1)   # 입찰 환율로 환산한 기대 이익 ($M)
    p = np.array([r["p"] for r in grid0])
    grid = [{"ratio": r["ratio"], "quote": r["quote"], "p": r["p"], "ev": r["ev"], "ev_risk": _r(p[i] * profit_usd[i], 3),
             "loss_prob": _r(loss[i]), "margin_mean": _r(margin[i].mean()), "margin_p10": _r(p10[i]),
             "margin_p50": _r(p50[i]), "margin_p90": _r(p90[i])} for i, r in enumerate(grid0)]

    def at_quote(q: float, h: float = hedge) -> np.ndarray:
        Ch, Rh, _ = _factors(g, ov, months, a, h)
        return 1.0 - bep * Ch / (q * Rh)

    m_now = at_quote(q_now)
    loss_now = float((m_now < 0).mean())
    # 안전 시작 견적가: 적자확률 ≤ 기준 이 되는 가장 낮은 견적가 (곡선 사이는 선형 보간)
    safe = None
    ok = np.nonzero(loss <= target)[0]
    if len(ok):
        j = int(ok[0])
        safe = float(quotes[0]) if j == 0 else float(np.interp(target, [loss[j], loss[j - 1]], [quotes[j], quotes[j - 1]]))
    interp = lambda q, k: float(np.interp(q, quotes, [r[k] for r in grid0]))

    # 판단 도구: 견적가를 올려서 기준을 맞출지, 헤지를 늘려서 맞출지
    raise_opt = hedge_opt = None
    if safe is not None and loss_now > target:
        raise_opt = {"quote": _r(safe, 2), "delta": _r(safe - q_now, 2), "delta_krw": _r((safe - q_now) * eok, 0),
                     "p": _r(interp(safe, "p")), "dp": _r(interp(safe, "p") - s0["p_now"]),
                     "ev": _r(interp(safe, "ev"), 3), "dev": _r(interp(safe, "ev") - s0["ev_now"], 3)}
    if loss_now > target:
        for h in np.arange(round(hedge * 100) + 1, 101) / 100:
            mh = at_quote(q_now, h)
            if (mh < 0).mean() <= target:
                hedge_opt = {"ratio": _r(h, 2), "loss_prob": _r((mh < 0).mean()), "margin_mean": _r(mh.mean()),
                             "margin_p10": _r(np.percentile(mh, 10)), "margin_p90": _r(np.percentile(mh, 90))}
                break
    # 비교용: 예전 가정(원가 전부 원화 · 인도 때 일시 수령 · 헤지 없음)
    simple = {"loss_prob": s0["loss_prob_now"], "fx_breakeven": _r(bep * fx0 / q_now, 1)}

    prof_ship = (q_now * R - bep * C) * eok                                 # 척당 이익 (억 원, 시뮬레이션별)
    cost_total = bep * eok
    summary = {k: s0[k] for k in ("quote_now", "ratio_now", "bep", "bep_ratio", "p_now", "ev_now", "best_quote",
                                  "band_lo", "band_hi", "recommended", "recommended_below_bep")}
    summary.update(months=months, fx_assumed=_r(fx0, 1), loss_prob_now=_r(loss_now), margin_mean_now=_r(m_now.mean()),
                   margin_p10_now=_r(np.percentile(m_now, 10)), margin_p90_now=_r(np.percentile(m_now, 90)),
                   ev_risk_now=_r(s0["p_now"] * float((q_now * R - bep * C).mean()), 3),
                   fx_breakeven=_r(_fx_breakeven(q_now, bep, usd, a, hedge, fx0), 1),
                   krw_cost_share=_r(1 - usd), safe_quote=_r(safe, 2),
                   safe_ratio=_r(safe / (q_now / s0["ratio_now"])) if safe is not None else None)
    money = {"fx": _r(fx0, 1), "num_ships": ship["num_ships"], "quote_krw": _r(q_now * eok, 0),
             "cost_total": _r(cost_total, 0),
             "cost_items": [{**c, "krw": _r(cost_total * c["share"], 0)} for c in a["costs"]],
             "profit_ship_mean": _r(prof_ship.mean(), 0), "profit_ship_p10": _r(np.percentile(prof_ship, 10), 0),
             "profit_ship_p90": _r(np.percentile(prof_ship, 90), 0),
             "profit_total_mean": _r(prof_ship.mean() * ship["num_ships"], 0),
             "safe_quote_krw": _r(safe * eok, 0) if safe is not None else None}
    return {"source": be.source, "bid_id": bid_id, "ship": ship, "assumptions": a, "notes": notes,
            "summary": summary, "grid": grid, "money": money, "simple": simple,
            "decision": {"target": target, "ok_now": loss_now <= target, "raise": raise_opt, "hedge": hedge_opt},
            "backtest": _backtest(be.mm, months)}
