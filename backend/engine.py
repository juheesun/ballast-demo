"""백엔드 엔진 어댑터.

modeling/ 의 B 코드(ScenarioEngine)를 그대로 불러 쓴다. modeling/ 은 수정하지 않는다.
A 의 모델(features.py, win_model.py, win_logit.pkl)이 없거나 환경변수 BALLAST_MOCK=1 이면
'예시 모드'로 동작한다: 낙찰확률만 단순 로지스틱으로 대신하고, 나머지(손익분기, 환율·원가 시뮬레이션)는 진짜 계산이다.
→ 프론트엔드 개발이 A 모델 완성을 기다리지 않아도 된다. 응답의 source 값이 "mock" 이면 화면에 '예시 데이터'로 표시한다.
"""
from __future__ import annotations
from typing import Optional
import json, math, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MODELING = ROOT / "modeling"
if str(MODELING) not in sys.path:
    sys.path.insert(0, str(MODELING))

import b_common as bc                                    # noqa: E402  (modeling/ 에 있음)
from margin_model import MarginModel                     # noqa: E402
from scenario_engine import ScenarioEngine, Scenario    # noqa: E402

# 시나리오 버튼 정의. 화면의 버튼은 이 목록으로 그려진다 (프론트는 목록만 받음).
# 매핑 규칙은 팀이 정한 가정이다 (modeling/scenario_engine.py 상단 설명 참고).
PRESETS = [
    {"id": "comp_m5",  "group": "경쟁",   "label": "경쟁사 견적 -5%",   "params": {"comp_pct": -0.05}},
    {"id": "comp_m10", "group": "경쟁",   "label": "경쟁사 견적 -10%",  "params": {"comp_pct": -0.10}},
    {"id": "fx_m5",    "group": "환율",   "label": "환율 -5%",          "params": {"fx_pct": -0.05}},
    {"id": "fx_m10",   "group": "환율",   "label": "환율 -10%",         "params": {"fx_pct": -0.10}},
    {"id": "steel_p10", "group": "비용",  "label": "후판가 +10%",       "params": {"steel_pct": 0.10}},
    {"id": "delay_3",  "group": "납기",   "label": "납기 3개월 지연",   "params": {"delay_months": 3}},
    {"id": "delay_6",  "group": "납기",   "label": "납기 6개월 지연",   "params": {"delay_months": 6}},
    {"id": "combo",    "group": "복합",   "label": "경쟁사 -5% + 후판 +10%", "params": {"comp_pct": -0.05, "steel_pct": 0.10}},
]


def _num(x, nd=4):
    if x is None:
        return None
    x = float(x)
    return None if (math.isnan(x) or math.isinf(x)) else round(x, nd)


class _MockWinModel:
    """예시용 낙찰확률. A 문서의 해석(견적 1%p↑ → 오즈 -28%, 납기 1개월↑ → 오즈 -19%)만 반영한 로지스틱."""
    SLOPE_PER_PCT = math.log(0.72)
    SLOPE_PER_MONTH = math.log(0.81)

    def __init__(self, p0: float = 0.60):
        self.z0 = math.log(p0 / (1 - p0))

    def predict_proba(self, df: pd.DataFrame):
        d_ratio = (df["price_ratio"] - df["_ratio_ref"]) * 100
        d_lead = df["lead_months"] - df["_lead_ref"]
        z = self.z0 + self.SLOPE_PER_PCT * d_ratio + self.SLOPE_PER_MONTH * d_lead
        return 1 / (1 + np.exp(-z))


class Backend:
    def __init__(self):
        self.raw = bc.load_raw()
        mm_path = bc.MODELS / "margin_model.pkl"
        self.mm = MarginModel.load(mm_path) if mm_path.exists() else MarginModel(fx_returns=bc.load_fx_returns())
        self.source, self.reason, self.eng = "model", None, None
        if os.environ.get("BALLAST_MOCK") != "1":
            try:
                features, model, table = bc.load_win_assets()
                bc.check_contract(features, model, table)
                self.eng = ScenarioEngine(model, features.price_grid, table, self.raw, self.mm)
            except (Exception, SystemExit) as e:        # A 파일 없음 / 컬럼 불일치 → 예시 모드
                self.reason = str(e)[:300]
        else:
            self.reason = "BALLAST_MOCK=1"
        if self.eng is None:
            self.source = "mock"
            self.eng = self._mock_engine()
        self._cache: dict = {}

    # ── 예시 모드용 엔진: 같은 ScenarioEngine 에 가짜 낙찰모델·표를 끼운다 ──
    def _mock_engine(self) -> ScenarioEngine:
        real = self.raw[self.raw.variant == "REAL"]
        table = pd.DataFrame({
            "bid_id": real.bid_id.values, "variant": "REAL",
            "price_ratio": (real.quote / real.market_price).values, "lead_months": real.lead_months.values,
            "quote_usd_mn": real.quote.values, "market_price_usd_mn": real.market_price.values, "bep_usd_mn": real.bep.values})
        table["_ratio_ref"], table["_lead_ref"] = table["price_ratio"], table["lead_months"]

        def price_grid(row, lo=0.85, hi=1.15, n=61):
            ratios = np.linspace(lo, hi, n)
            g = pd.DataFrame([row.to_dict()] * n)
            g["price_ratio"] = ratios
            g["quote_usd_mn"] = ratios * row["market_price_usd_mn"]
            return g
        return ScenarioEngine(_MockWinModel(), price_grid, table, self.raw, self.mm)

    # ── 입찰 목록 ──
    def bids(self) -> list:
        out = []
        for r in self.raw[self.raw.variant == "REAL"].sort_index().itertuples():
            out.append(dict(id=r.bid_id, label=f"{r.bid_id} · {r.shipyard}", shipyard=r.shipyard,
                            quote_now=_num(r.quote, 2), market_price=_num(r.market_price, 2),
                            ratio_now=_num(r.quote / r.market_price), lead_months=int(r.lead_months),
                            expected_fx=_num(r.expected_fx, 1), bep=_num(r.bep, 2)))
        return out

    # ── 곡선 응답 ──
    def _payload(self, bid_id: str, sc: Scenario, res) -> dict:
        raw, s, g = self.raw.loc[bid_id], res.summary, res.grid
        fx0 = float(raw.expected_fx)
        fx_s = sc.fx_krw or fx0 * (1 + sc.fx_pct)
        cols = {"ratio": 4, "quote": 3, "p": 4, "ev": 3, "ev_risk": 3, "loss_prob": 4,
                "margin_rule": 4, "margin_mean": 4, "margin_p10": 4, "margin_p50": 4, "margin_p90": 4}
        grid = [{k: _num(v, nd) for (k, nd), v in zip(cols.items(), row)} for row in g[list(cols)].itertuples(index=False)]
        keys = ["quote_now", "ratio_now", "bep", "bep_ratio", "months", "p_now", "profit_now", "ev_now", "loss_prob_now",
                "margin_mean_now", "best_quote", "best_ratio", "best_ev", "band_lo", "band_hi", "recommended", "recommended_below_bep"]
        summary = {k: (bool(s[k]) if k == "recommended_below_bep" else _num(s[k])) for k in keys}
        summary["fx_assumed"] = _num(fx_s, 1)
        summary["fx_breakeven"] = _num(s["bep"] * fx_s / s["quote_now"], 1)       # 이 제안가에서 매출 = 원가 가 되는 환율
        return {"source": self.source, "bid_id": bid_id, "scenario": sc.__dict__ | {"overrides": {}},
                "summary": summary, "grid": grid}

    @staticmethod
    def _scenario(params: Optional[dict]) -> Scenario:
        p = params or {}
        return Scenario(label=p.get("label", "조건"), comp_pct=float(p.get("comp_pct", 0)), steel_pct=float(p.get("steel_pct", 0)),
                        fx_pct=float(p.get("fx_pct", 0)), fx_krw=p.get("fx_krw"), delay_months=int(p.get("delay_months", 0)))

    def curve(self, bid_id: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        quote_pct = float(params.pop("quote_pct", 0) or 0)       # 우리 견적가를 바꿔 보는 질문 ("견적가를 3% 낮추면?")
        sc = self._scenario(params)
        key = ("curve", bid_id, json.dumps(sc.__dict__, sort_keys=True, default=str), round(quote_pct, 4))
        if key not in self._cache:
            # 제안가가 기본 범위(시장가 -15%~+15%) 밖이어도 그래프에 보이도록 입찰마다 범위를 넓힌다
            r = self.raw.loc[bid_id]
            ratio = float(r.quote / r.market_price)
            lo, hi = min(0.85, ratio - 0.03), max(1.15, ratio + 0.03)
            payload = self._payload(bid_id, sc, self.eng.evaluate(bid_id, sc, lo=lo, hi=hi))
            if quote_pct:
                payload = self._move_quote(payload, quote_pct)
            self._cache[key] = payload
        return self._cache[key]

    @staticmethod
    def _move_quote(payload: dict, quote_pct: float) -> dict:
        """곡선은 그대로 두고 '제안가' 위치만 옮겨, 그 견적가에서의 낙찰확률·기대가치 등을 곡선에서 읽는다."""
        s, g = dict(payload["summary"]), payload["grid"]
        ratio_new = s["ratio_now"] * (1 + quote_pct)
        xs = [r["ratio"] for r in g]
        at = lambda k: float(np.interp(ratio_new, xs, [r[k] for r in g]))
        market = s["quote_now"] / s["ratio_now"]
        s.update(ratio_now=_num(ratio_new), quote_now=_num(ratio_new * market, 3), p_now=_num(at("p")), ev_now=_num(at("ev"), 3),
                 loss_prob_now=_num(at("loss_prob")), margin_mean_now=_num(at("margin_mean")),
                 profit_now=_num(ratio_new * market - s["bep"], 3))
        s["fx_breakeven"] = _num(s["bep"] * s["fx_assumed"] / s["quote_now"], 1)
        return {**payload, "summary": s}

    def compare(self, bid_id: str, params: Optional[dict]) -> dict:
        sc = self._scenario({k: v for k, v in (params or {}).items() if k != "quote_pct"})
        base, scen = self.curve(bid_id), self.curve(bid_id, params)
        b, s = base["summary"], scen["summary"]
        diff = lambda k: None if b[k] is None or s[k] is None else _num(s[k] - b[k])
        return {"source": self.source, "bid_id": bid_id, "base": base, "scenario": scen,
                "delta": {k: diff(k) for k in ("p_now", "ev_now", "loss_prob_now", "margin_mean_now", "recommended", "bep", "best_quote")},
                "decomposition": self._decompose(b, s)}

    @staticmethod
    def _decompose(b: dict, s: dict) -> dict:
        """기대가치 = 낙찰확률 × 건당 이익 → 변화 = (확률 변화 × 기존 이익) + (새 확률 × 이익 변화). 정확히 합쳐진다."""
        prob = (s["p_now"] - b["p_now"]) * b["profit_now"]
        prof = s["p_now"] * (s["profit_now"] - b["profit_now"])
        return {"total": _num(s["ev_now"] - b["ev_now"]), "prob_effect": _num(prob), "profit_effect": _num(prof)}

    def scenario_table(self, bid_id: str) -> list:
        base = self.curve(bid_id)["summary"]
        rows = [{"id": "base", "label": "기준", "group": "", "params": {}, "p_now": base["p_now"], "ev_now": base["ev_now"],
                 "loss_prob_now": base["loss_prob_now"], "recommended": base["recommended"], "d_ev": 0.0}]
        for pr in PRESETS:
            s = self.curve(bid_id, pr["params"])["summary"]
            rows.append({"id": pr["id"], "label": pr["label"], "group": pr["group"], "params": pr["params"],
                         "p_now": s["p_now"], "ev_now": s["ev_now"], "loss_prob_now": s["loss_prob_now"],
                         "recommended": s["recommended"], "d_ev": _num(s["ev_now"] - base["ev_now"])})
        return rows

    def fx_latest(self) -> dict:
        m = json.load(open(bc.MARKET_MONTHLY, encoding="utf-8"))
        last, prev = m[-1], m[-2]
        carried = any("usd_krw" in a for a in last.get("assumed_fields", []))
        return {"year_month": last["year_month"], "usd_krw": _num(last["usd_krw"], 1),
                "change": _num(last["usd_krw"] - prev["usd_krw"], 1), "carried_over": carried}


    # ── 과거 이력 (data/dataset.json) ──
    def history(self) -> dict:
        data = json.load(open(bc.DATASET, encoding="utf-8"))
        rows = []
        for g in data:
            for r in [g["real"]] + g.get("scenarios", []):
                o, p, sh = r["outcome"], r["price"], r["ship"]
                sc = r.get("scenario") or {}
                rows.append({"id": r["bid_id"], "anchor": r["anchor_id"], "origin": r["origin"], "variant": sc.get("variant", "REAL"),
                             "date": sh["bid_date"], "shipyard": sh["shipyard"], "owner": sh["owner"], "ships": sh["num_ships"],
                             "delivery": sh["delivery_month"], "quote": _num(p["quote_usd_mn"], 1), "market": _num(p["market_price_usd_mn"], 1),
                             "ratio": _num(p["price_ratio"]), "won": bool(o["won"]),
                             "loss_reason": None if o["won"] else o["loss_reason"], "margin": _num(o.get("actual_margin")),
                             "note": sc.get("reason", ""), "source": r.get("source", "")})
        return {"source": "dataset.json", "rows": rows}
