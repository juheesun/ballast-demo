# -*- coding: utf-8 -*-
"""시나리오 엔진: 기대가치 곡선 · 반사실 비교 · 역방향 탐색.

A 의 결정을 그대로 따른다:
  · 기대가치 = 낙찰확률 × (견적가 − BEP)           (마진 모델은 기대가치 공식에 쓰지 않음)
  · 권장가   = 기대가치 ≥ 최고값 × 0.85 인 구간의 '하한'   (봉우리가 아님)
마진 모델(MarginModel)은 환율·원가 위험(손실 확률, 위험 반영 기대가치)을 '추가로' 얹는 데 쓴다.

반사실 시나리오 매핑 (※ 학습 결과가 아니라 팀이 정한 규칙):
  comp_pct     경쟁사 견적 변화(−0.05 = 5% 싸게) → 우리 견적비율을 ÷(1+comp_pct) 해서 낙찰모델에 입력
  steel_pct    후판가 변화 → BEP × (1 + steel_share × 변화)
  fx_pct/fx_krw 입찰 시점 환율 대신 쓸 환율 → BEP × (입찰환율 ÷ 새 환율)
  delay_months 납기 지연 → 리드타임 + n 개월 (환율 시뮬레이션 기간도 늘어남)
  overrides    임의 피처 덮어쓰기 (A 문서: 신규 선주·스크러버·LNG 는 anchor 이름표라 쓰면 경고)
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from b_common import COL, BINARY_LABEL_COLS, pct


@dataclass
class Scenario:
    label: str = "기본"
    comp_pct: float = 0.0
    steel_pct: float = 0.0
    fx_pct: float = 0.0
    fx_krw: float | None = None
    delay_months: int = 0
    overrides: dict = field(default_factory=dict)


@dataclass
class EvalResult:
    scenario: Scenario
    grid: pd.DataFrame          # ratio, quote, p, bep, ev, margin_*, loss_prob, ev_risk
    summary: dict


class ScenarioEngine:
    def __init__(self, win_model, price_grid_fn, table: pd.DataFrame, raw: pd.DataFrame, margin_model,
                 steel_share: float = 0.10, rec_threshold: float = 0.85, lo: float = 0.85, hi: float = 1.15, n: int = 121):
        self.model, self.price_grid, self.table, self.raw, self.mm = win_model, price_grid_fn, table, raw, margin_model
        self.steel_share, self.rec_threshold, self.lo, self.hi, self.n = steel_share, rec_threshold, lo, hi, n

    # ── 입찰 한 건 찾기 ──
    def row(self, bid_id: str) -> pd.Series:
        t = self.table[self.table[COL["bid_id"]] == bid_id]
        if t.empty:
            raise KeyError(f"{bid_id} 를 load_table() 결과에서 찾지 못했습니다.")
        return t.iloc[0]

    def _predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.model.predict_proba(df)).reshape(len(df), -1)[:, -1]

    # ── 핵심: 견적가를 쓸어가며 계산 ──
    def evaluate(self, bid_id: str, scenario: Scenario | None = None, lo=None, hi=None, n=None) -> EvalResult:
        sc = scenario or Scenario()
        row, raw = self.row(bid_id), self.raw.loc[bid_id]
        g = self.price_grid(row, lo or self.lo, hi or self.hi, n or self.n).reset_index(drop=True)
        ratio, quote = g[COL["ratio"]].to_numpy(float), g[COL["quote"]].to_numpy(float)
        bep0 = float(g[COL["bep"]].iloc[0])

        gm = g.copy()                                        # 낙찰확률 모델에 넣을 입력 (시나리오 반영)
        gm[COL["ratio"]] = ratio / (1.0 + sc.comp_pct)
        gm[COL["lead"]] = gm[COL["lead"]] + sc.delay_months
        for k, v in sc.overrides.items():
            if k in BINARY_LABEL_COLS:
                warnings.warn(f"'{k}' 는 anchor 이름표처럼 작동하는 피처입니다 (A 문서). 결과를 설명에 쓰지 마세요.")
            gm[k] = v
        p = self._predict(gm)

        fx0 = float(raw["expected_fx"])
        fx_s = sc.fx_krw if sc.fx_krw else fx0 * (1.0 + sc.fx_pct)
        bep_s = bep0 * (1.0 + self.steel_share * sc.steel_pct) * fx0 / fx_s         # 시나리오 손익분기 선가
        months = int(raw["lead_months"]) + sc.delay_months

        out = pd.DataFrame({"ratio": ratio, "quote": quote, "p": p, "bep": bep_s, "ev": p * (quote - bep_s)})
        risk = self.mm.summarize(quote, bep_s, months)
        out = pd.concat([out, risk], axis=1)
        out["ev_risk"] = out["p"] * out["profit_mean"]

        ev, i = out["ev"].to_numpy(), int(np.argmax(out["ev"].to_numpy()))
        if ev[i] > 0:
            ok = ev >= self.rec_threshold * ev[i]
            band_lo, band_hi = float(quote[ok].min()), float(quote[ok].max())
        else:
            band_lo = band_hi = None
        r_now = float(row[COL["ratio"]]); q_now = float(row[COL["quote"]])
        p_now = float(np.interp(r_now, ratio, p))
        risk_now = self.mm.summarize([q_now], bep_s, months).iloc[0]
        summary = dict(
            bid_id=bid_id, quote_now=q_now, ratio_now=r_now, bep=bep_s, bep_ratio=bep_s / (q_now / r_now), months=months,
            p_now=p_now, profit_now=q_now - bep_s, ev_now=p_now * (q_now - bep_s),
            loss_prob_now=float(risk_now["loss_prob"]), margin_mean_now=float(risk_now["margin_mean"]),
            best_quote=float(quote[i]), best_ratio=float(ratio[i]), best_ev=float(ev[i]),
            band_lo=band_lo, band_hi=band_hi,
            recommended=band_lo,                              # A 정책: 권장 구간 하한
            recommended_below_bep=(band_lo is not None and band_lo < bep_s))
        return EvalResult(sc, out, summary)

    # ── 기본 vs 시나리오 ──
    def compare(self, bid_id: str, scenario: Scenario) -> dict:
        b, s = self.evaluate(bid_id), self.evaluate(bid_id, scenario)
        sb, ss = b.summary, s.summary
        d_p = (ss["p_now"] - sb["p_now"]) * sb["profit_now"]          # 낙찰확률이 바뀐 효과
        d_profit = ss["p_now"] * (ss["profit_now"] - sb["profit_now"])  # 건당 이익이 바뀐 효과
        return dict(base=b, scen=s, d_ev=ss["ev_now"] - sb["ev_now"], d_ev_prob=d_p, d_ev_profit=d_profit)

    def summary_table(self, bid_id: str, scenarios: list) -> pd.DataFrame:
        rows = []
        for sc in scenarios:
            c = self.compare(bid_id, sc); b, s = c["base"].summary, c["scen"].summary
            rows.append({"조건": sc.label,
                         "낙찰확률": f"{b['p_now']:.1%} → {s['p_now']:.1%} ({(s['p_now']-b['p_now'])*100:+.1f}%p)",
                         "기대가치 $mn": f"{b['ev_now']:.2f} → {s['ev_now']:.2f} ({c['d_ev']:+.2f})",
                         "환율손실확률": f"{b['loss_prob_now']:.1%} → {s['loss_prob_now']:.1%}",
                         "손익분기 견적선": f"{pct(b['bep_ratio'])} → {pct(s['bep_ratio'])}",
                         "권장가(하한)": (f"${b['recommended']:.1f} → ${s['recommended']:.1f}mn" if s["recommended"] else "없음(기대가치≤0)")})
        return pd.DataFrame(rows).set_index("조건")

    # ───────────────────────── 역방향 탐색 ─────────────────────────
    def solve_quote(self, bid_id: str, scenario: Scenario | None = None, min_p=None, min_margin=None,
                    max_loss_prob=None, min_ev=None, margin_basis: str = "rule") -> dict:
        """조건을 모두 만족하는 견적가 구간. margin_basis: 'rule'(1−BEP/견적가) | 'risk'(환율·원가 충격 반영 기대 마진)."""
        r = self.evaluate(bid_id, scenario); g = r.grid
        mcol = "margin_rule" if margin_basis == "rule" else "margin_mean"
        cons = {}
        if min_p is not None: cons[f"낙찰확률 ≥ {min_p:.0%}"] = g["p"] >= min_p
        if min_margin is not None: cons[f"마진({margin_basis}) ≥ {min_margin:.0%}"] = g[mcol] >= min_margin
        if max_loss_prob is not None: cons[f"환율손실확률 ≤ {max_loss_prob:.0%}"] = g["loss_prob"] <= max_loss_prob
        if min_ev is not None: cons[f"기대가치 ≥ ${min_ev:.1f}mn"] = g["ev"] >= min_ev
        ok = np.ones(len(g), bool)
        for m in cons.values(): ok &= m.to_numpy()
        single = {k: (f"${g['quote'][m].min():.1f}~${g['quote'][m].max():.1f}mn" if m.any() else "해당 없음") for k, m in cons.items()}
        if not ok.any():
            return dict(feasible=False, single=single, result=r)
        gi = g[ok]; b = gi["ev"].idxmax()
        return dict(feasible=True, quote_lo=float(gi["quote"].min()), quote_hi=float(gi["quote"].max()),
                    ratio_lo=float(gi["ratio"].min()), ratio_hi=float(gi["ratio"].max()),
                    best_quote=float(g["quote"][b]), best_ev=float(g["ev"][b]), best_p=float(g["p"][b]),
                    best_margin=float(g[mcol][b]), single=single, result=r)

    def breakeven_fx(self, bid_id: str, quote: float | None = None, steel_pct: float = 0.0, overrun: float = 0.0) -> dict:
        """이 견적가에서 원화 매출 = 원가 가 되는 인도 시점 환율, 그리고 그 아래로 갈 확률."""
        raw = self.raw.loc[bid_id]; q = quote or float(raw["quote"])
        cost = float(raw["est_cost_krw_100m"]) * (1 + self.steel_share * steel_pct) * (1 + overrun)
        fx_be = cost * 100 / q
        g, _ = self.mm.shocks(int(raw["lead_months"]))
        return dict(fx_be=fx_be, fx_bid=float(raw["expected_fx"]), drop_pct=fx_be / float(raw["expected_fx"]) - 1,
                    prob_below=float((float(raw["expected_fx"]) * g < fx_be).mean()))

    def find_threshold(self, bid_id: str, param: str, lo: float, hi: float, metric: str, target: float,
                       base_scenario: Scenario | None = None, tol: float = 1e-4):
        """param(comp_pct | steel_pct | fx_pct | delay_months)을 lo~hi 에서 움직여 metric 이 target 이 되는 값을 이분법으로 찾는다.
        metric: p_now | ev_now | best_ev | loss_prob_now | recommended (권장가). 구간 안에서 target 을 못 가로지르면 None."""
        base_sc = base_scenario or Scenario()
        def f(v):
            kw = {**base_sc.__dict__, param: (int(round(v)) if param == "delay_months" else v)}
            s = self.evaluate(bid_id, Scenario(**kw)).summary
            val = s[metric]
            return (np.nan if val is None else val) - target
        flo, fhi = f(lo), f(hi)
        if np.isnan(flo) or np.isnan(fhi) or flo * fhi > 0:
            return None
        for _ in range(40):
            mid = (lo + hi) / 2; fm = f(mid)
            if np.isnan(fm) or abs(fm) < tol or abs(hi - lo) < 1e-6: break
            if flo * fm <= 0: hi = mid
            else: lo, flo = mid, fm
        return (lo + hi) / 2
