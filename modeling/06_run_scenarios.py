# -*- coding: utf-8 -*-
"""06 · 기대가치 곡선 · 반사실 시나리오 · 역방향 탐색  →  processed/scenario_report.txt, figures/*.png

실행: python modeling/06_run_scenarios.py [입찰번호]      (기본 REAL-10)
"""
import sys
import pandas as pd
from b_common import *
from margin_model import MarginModel
from scenario_engine import ScenarioEngine, Scenario
from plots import plot_ev, plot_fx_risk

FOCUS = sys.argv[1] if len(sys.argv) > 1 else "REAL-10"
features, model, table = load_win_assets(); check_contract(features, model, table)
raw = load_raw(); mm = MarginModel.load(MODELS / "margin_model.pkl")
eng = ScenarioEngine(model, features.price_grid, table, raw, mm)      # 권장 구간 85%, 견적 −15%~+15%
rep = Report(PROCESSED / "scenario_report.txt")
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 20)

# 시나리오 목록 (※ 매핑은 팀이 정한 규칙. 신규 선주·스크러버·LNG 토글은 A 문서에 따라 넣지 않음)
SCEN = [Scenario("경쟁사 견적 −5%", comp_pct=-0.05),
        Scenario("후판가 +10%", steel_pct=0.10),
        Scenario("환율 −7%", fx_pct=-0.07),
        Scenario("납기 6개월 지연", delay_months=6),
        Scenario("경쟁사 −5% + 후판 +10%", comp_pct=-0.05, steel_pct=0.10)]

# ── 1. 전체 실제 건: 권장가 정책 ──
rep("=" * 78); rep("1. 실제 건별 권장가 (정책: 기대가치 ≥ 최고의 85% 구간의 하한)")
rows = []
for bid in raw.index[(raw.variant == "REAL")]:
    s = eng.evaluate(bid).summary
    rows.append({"입찰": bid, "제안가": f"${s['quote_now']:.1f}", "낙찰확률": f"{s['p_now']:.0%}", "손익분기": pct(s["bep_ratio"]),
                 "봉우리": f"${s['best_quote']:.1f}", "권장 구간": (f"${s['band_lo']:.1f}~{s['band_hi']:.1f}" if s["band_lo"] else "없음"),
                 "권장가": (f"${s['recommended']:.1f}" if s["recommended"] else "-"), "환율손실확률(제안가)": f"{s['loss_prob_now']:.0%}"})
rep(pd.DataFrame(rows).set_index("입찰").to_string())

# ── 2. 초점 입찰: 기본 지표와 반사실 ──
b = eng.evaluate(FOCUS); s = b.summary
rep("\n" + "=" * 78); rep(f"2. [{FOCUS}] 기본 조건")
rep(f"제안가 ${s['quote_now']:.1f}mn ({pct(s['ratio_now'])}) · 손익분기 선가 ${s['bep']:.1f}mn ({pct(s['bep_ratio'])})")
rep(f"낙찰확률 {s['p_now']:.1%} · 기대가치 ${s['ev_now']:.2f}mn/척 · 환율·원가 손실 확률 {s['loss_prob_now']:.1%} · 기대 마진 {s['margin_mean_now']:.1%}")
rep(f"기대가치 봉우리 ${s['best_quote']:.1f}mn · 권장 구간 ${s['band_lo']:.1f}~{s['band_hi']:.1f}mn · 권장가 ${s['recommended']:.1f}mn")
rep("\n반사실 시나리오 (제안가 기준 기본 → 바뀐 조건)")
rep(eng.summary_table(FOCUS, SCEN).to_string())

plot_ev(b, title=f"{FOCUS} · 견적가별 기대가치", fname=f"{FOCUS}_ev_base.png")
plot_fx_risk(b, title=f"{FOCUS} · 환율·원가 위험", fname=f"{FOCUS}_fx_risk.png")
combo = SCEN[-1]; plot_ev(eng.evaluate(FOCUS, combo), b, title=f"{FOCUS} · 반사실: {combo.label}", fname=f"{FOCUS}_ev_scenario.png")

# ── 3. 역방향 탐색 ──
rep("\n" + "=" * 78); rep(f"3. [{FOCUS}] 역방향 탐색")
def show(title, q):
    if q["feasible"]:
        rep(f"· {title}: 견적가 ${q['quote_lo']:.1f}~${q['quote_hi']:.1f}mn ({pct(q['ratio_lo'])}~{pct(q['ratio_hi'])}) · 구간 내 최고 기대가치 ${q['best_ev']:.2f}mn @ ${q['best_quote']:.1f}mn (낙찰 {q['best_p']:.0%})")
    else:
        rep(f"· {title}: ✗ 동시에 만족하는 견적가가 없음. 조건별 단독 구간 → " + " / ".join(f"{k}: {v}" for k, v in q["single"].items()))
show("낙찰확률 ≥ 40% 이면서 마진 ≥ 5%", eng.solve_quote(FOCUS, min_p=0.40, min_margin=0.05))
show("낙찰확률 ≥ 40% 이면서 환율손실확률 ≤ 20%", eng.solve_quote(FOCUS, min_p=0.40, max_loss_prob=0.20))
show("낙찰확률 ≥ 60%", eng.solve_quote(FOCUS, min_p=0.60))
show("같은 조건(낙찰 ≥40%, 마진 ≥5%), 경쟁사 −5%일 때", eng.solve_quote(FOCUS, SCEN[0], min_p=0.40, min_margin=0.05))
show("무리한 조건(낙찰 ≥ 80% 이면서 마진 ≥ 15%)", eng.solve_quote(FOCUS, min_p=0.80, min_margin=0.15))

be = eng.breakeven_fx(FOCUS)
rep(f"· 제안가의 손익분기 환율 {be['fx_be']:,.0f}원 (입찰 시점 {be['fx_bid']:,.0f}원 대비 {be['drop_pct']*100:+.1f}%) · 인도 시점에 그 아래로 갈 확률 {be['prob_below']:.1%}")
be2 = eng.breakeven_fx(FOCUS, steel_pct=0.10, overrun=0.04)
rep(f"  후판 +10% & 원가 초과 4% 이면: {be2['fx_be']:,.0f}원 ({be2['drop_pct']*100:+.1f}%) · 확률 {be2['prob_below']:.1%}")

def thr(txt, **kw):
    v = eng.find_threshold(FOCUS, **kw)
    rep(f"· {txt}: " + ("구간 안에서 해당 없음" if v is None else v if isinstance(v, str) else f"{v:+.3f}" if abs(v) < 5 else f"{v:.1f}"))
thr("경쟁사 견적이 이만큼 변하면 제안가의 낙찰확률이 20% 아래 (comp_pct)", param="comp_pct", lo=0.0, hi=-0.30, metric="p_now", target=0.20)
thr("경쟁사 견적이 이만큼 변하면 최고 기대가치가 절반 (comp_pct)", param="comp_pct", lo=0.0, hi=-0.30, metric="best_ev", target=s["best_ev"] * 0.5)
thr("후판가가 이만큼 오르면 최고 기대가치가 절반 (steel_pct)", param="steel_pct", lo=0.0, hi=3.0, metric="best_ev", target=s["best_ev"] * 0.5)
thr("환율이 이만큼 떨어지면 제안가의 기대가치가 0 이하 (fx_pct)", param="fx_pct", lo=0.0, hi=-0.30, metric="ev_now", target=0.0)
thr("납기가 이만큼(개월) 늦어지면 제안가의 낙찰확률이 20% 아래", param="delay_months", lo=0, hi=24, metric="p_now", target=0.20)
rep.save()
