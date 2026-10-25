# -*- coding: utf-8 -*-
"""07 · SHAP 요인 분해  →  processed/shap_report.txt, figures/shap_*.png

실행: python modeling/07_run_shap.py [입찰번호]      (기본 REAL-10)      필요: pip install shap
"""
import sys
import numpy as np, pandas as pd
from b_common import *
from margin_model import MarginModel, margin_shapley
from scenario_engine import ScenarioEngine, Scenario
import explain as ex

FOCUS = sys.argv[1] if len(sys.argv) > 1 else "REAL-10"
features, model, table = load_win_assets(); check_contract(features, model, table)
raw = load_raw(); ids = train_ids(raw, features); mm = MarginModel.load(MODELS / "margin_model.pkl")
eng = ScenarioEngine(model, features.price_grid, table, raw, mm)
feats = win_feature_names(model, features)
train_tbl = table.drop_duplicates(COL["bid_id"]).set_index(COL["bid_id"], drop=False).loc[ids]
rep = Report(PROCESSED / "shap_report.txt")
rep("낙찰확률 모델 설명 (모델 불가지 SHAP, 확률 공간). * = anchor 이름표 가능성이 있는 이진 피처 → 해석 제외")
rep("※ 확률(0~100%)은 S자 곡선이라, 바뀌지 않은 피처의 기여도 시나리오에서 함께 움직일 수 있음 (상호작용). 가장 큰 막대 중심으로 읽기.")
rep(f"피처: {feats} · 학습 {len(train_tbl)}건 · 독립 anchor {raw.loc[ids,'anchor_id'].nunique()}개 → 값은 방향과 상대 크기로만 읽기")

X = ex.WinExplainer(eng, feats, train_tbl)

# 1) 글로벌
imp = X.global_importance()
rep("\n[1] 글로벌 중요도 (평균 |SHAP|, %p)"); rep((imp[::-1] * 100).round(2).rename(index=ex.nice).to_string())
ex.plot_global(imp, fname="shap_global.png", title=f"글로벌 요인 중요도 · 학습 {len(train_tbl)}건")

# 2) 이 입찰
sv, base_val = X.local(FOCUS)
p_now = eng.evaluate(FOCUS).summary["p_now"]
rep(f"\n[2] {FOCUS} 낙찰확률 {p_now:.1%} = 평균 {base_val:.1%} + 요인 합 {sv.sum()*100:+.1f}%p")
rep((sv.sort_values() * 100).round(2).rename(index=ex.nice).to_string())
ex.plot_local(sv, base_val, p_now, f"{FOCUS} 낙찰확률 요인", fname=f"shap_local_{FOCUS}.png")

# 3) 시나리오 차이 + 기대가치 분해
for sc in [Scenario("경쟁사 −5% + 후판 +10%", comp_pct=-0.05, steel_pct=0.10), Scenario("납기 6개월 지연", delay_months=6)]:
    cmp = eng.compare(FOCUS, sc); diff = X.scenario_diff(FOCUS, sc)
    rep(f"\n[3] 시나리오: {sc.label}")
    rep(f"기대가치 {cmp['base'].summary['ev_now']:.2f} → {cmp['scen'].summary['ev_now']:.2f} $mn "
        f"(변화 {cmp['d_ev']:+.2f} = 낙찰확률 효과 {cmp['d_ev_prob']:+.2f} + 건당 이익 효과 {cmp['d_ev_profit']:+.2f})")
    rep("낙찰확률 변화의 피처별 기여(%p): " + ", ".join(f"{ex.nice(k)} {v*100:+.1f}" for k, v in diff[diff.abs() > 1e-4].sort_values().items()))
    ex.plot_scenario_breakdown(cmp, diff, sc.label, fname=f"shap_scenario_{sc.label[:3]}_{FOCUS}.png".replace(" ", "_"))

# 4) 마진 요인 분해 (구조식이라 정확한 Shapley)
r = raw.loc[FOCUS]
for lab, g, ov in [("환율 −7% · 원가 +4% (D 변형과 같은 충격)", 0.93, 0.04), ("환율 −7%", 0.93, 0.0), ("원가 +8%", 1.0, 0.08)]:
    c = margin_shapley(quote=r.quote, bep=r.bep, g=g, overrun=ov)
    rep(f"\n[4] {FOCUS} 마진 변화 · {lab}: " + ", ".join(f"{k} {v*100:+.1f}%p" for k, v in c.items()))
    if "D 변형" in lab: ex.plot_margin_shapley(c, lab, fname=f"shap_margin_{FOCUS}.png")
rep.save()
