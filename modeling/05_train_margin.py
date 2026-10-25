# -*- coding: utf-8 -*-
"""05 · 마진 모델 + 선택 편향 점검  →  models/margin_model.pkl, processed/margin_report.txt

실행: python modeling/05_train_margin.py   (A 의 03_train_models.py 로 win_logit.pkl 이 만들어진 뒤)
"""
import numpy as np, pandas as pd
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from b_common import *
from margin_model import MarginModel

features, model, table = load_win_assets()
check_contract(features, model, table)
raw = load_raw(); ids = train_ids(raw, features)
rep = Report(PROCESSED / "margin_report.txt")
tr = raw.loc[ids].copy()
tr["rule_margin"] = 1 - tr["bep"] / tr["quote"]
tr["ratio"] = tr["quote"] / tr["market_price"]

# ── 1. 마진 공식 검증 ──
rep("=" * 70); rep("1. 마진 구조식 검증: 실제 마진 = 1 − 추정원가×(1+원가초과) ÷ (견적가×인도환율÷100)")
w_all = raw[raw.won == 1]
chk = 1 - w_all.est_cost_krw_100m * (1 + w_all.cost_overrun) / (w_all.quote * w_all.delivery_fx / 100)
rep(f"낙찰 {len(w_all)}건, 공식과 데이터의 최대 차이 = {(w_all.actual_margin - chk).abs().max():.4f}  → 마진은 '환율 변화'와 '원가 초과' 두 값으로 완전히 결정됨")
rep("입찰 시점에 모르는 값은 이 둘뿐이라, 회귀로 배우지 않고 분포에서 뽑아 기대 마진·손실 확률을 계산한다.")

# ── 2. 낙찰 건 구성 (선택 편향이 어디서 오는지) ──
rep("\n" + "=" * 70); rep("2. 학습 행 중 낙찰 건의 구성")
won = tr[tr.won == 1]
comp = won.groupby("variant").agg(건수=("won", "size"), 평균_마진=("actual_margin", "mean"), 평균_원가초과=("cost_overrun", "mean"),
                                   평균_환율변화=("delivery_fx", lambda s: np.nan)).drop(columns="평균_환율변화")
fxchg = (won.delivery_fx / won.expected_fx - 1).groupby(won.variant).mean()
comp["평균_환율변화"] = fxchg
rep(comp.round(3).to_string())
rep(f"→ 낙찰 {len(won)}건 중 환율·원가 충격 변형(D·J·K)이 {won.variant.isin(list('DJK')).sum()}건. 학습 낙찰 건은 '충격이 많이 섞인 표본'이다.")

# ── 3. 낙찰확률(IPW 가중치용) ──
tbl = table.drop_duplicates(COL["bid_id"]).set_index(COL["bid_id"], drop=False).loc[ids]
if WIN_OOF_PATH.exists():
    p = pd.read_csv(WIN_OOF_PATH).set_index("bid_id")["p_oof"].reindex(ids).values; src = "A 의 LOAO 예측(win_oof.csv)"
else:
    p = np.asarray(model.predict_proba(tbl)).reshape(len(tbl), -1)[:, -1]; src = "학습 데이터 위 예측 (win_oof.csv 가 없어 in-sample 사용 → 약간 낙관적)"
tr["p_win"] = p
IPW_CLIP = (0.10, 1.0)
tr["ipw"] = 1 / np.clip(tr["p_win"], *IPW_CLIP)
tr.loc[tr.won == 1, "ipw"] /= tr.loc[tr.won == 1, "ipw"].mean()

# ── 4. 마진 충격 추정치 비교 ──
rep("\n" + "=" * 70); rep(f"4. 낙찰 건 '충격(실제 마진 − 규칙 마진)' 평균 추정 · 낙찰확률 출처: {src}")
won = tr[tr.won == 1]; shock = won.actual_margin - won.rule_margin
mm = MarginModel(fx_returns=load_fx_returns())
mc_shift = np.mean([mm.summarize([r.quote], r.bep, int(r.lead_months)).iloc[0]["margin_mean"] - r.rule_margin for r in tr.itertuples()])
est = pd.Series({"낙찰 건만의 단순 평균 (선택 편향 있음)": shock.mean(),
                 "낙찰 건 IPW 가중 평균": np.average(shock, weights=won["ipw"]),
                 "구조식 + 환율·원가 시뮬레이션 (전체 학습 행 평균)": mc_shift})
rep(est.round(4).to_string())
rep("→ 낙찰 건 평균은 충격 변형이 많아 크게 음수로 나온다. IPW 로 보정해도 큰 변화가 없으면(위 첫 두 줄) 편향의 원인이\n"
    "   '누가 낙찰됐나'보다 '낙찰 건에 충격 변형이 많이 섞인 구성'이라는 뜻이다. 그래서 낙찰 건 회귀 대신 시뮬레이션을 쓴다.")

# ── 5. 참고: 낙찰 건 회귀가 규칙을 이기는가 (anchor 하나씩 빼기, A 의 LOAO 와 같은 방식) ──
rep("\n" + "=" * 70); rep("5. 참고 · LOAO (anchor 하나씩 빼고 낙찰 건으로 학습 → 빠진 anchor 의 낙찰/실주 건 예측)")
X_cols = ["rule_margin", "ratio", "lead_months"]
pred = {k: np.zeros(len(tr)) for k in ("규칙(구조식, 충격 없음)", "단순 Ridge", "IPW Ridge")}
for tr_i, te_i in LeaveOneGroupOut().split(tr, groups=tr["anchor_id"]):
    a, b = tr.iloc[tr_i], tr.iloc[te_i]; aw = a[a.won == 1]
    pred["규칙(구조식, 충격 없음)"][te_i] = b["rule_margin"].values
    m1 = make_pipeline(StandardScaler(), Ridge(alpha=3.0)).fit(aw[X_cols], aw["actual_margin"])
    pred["단순 Ridge"][te_i] = m1.predict(b[X_cols])
    m2 = make_pipeline(StandardScaler(), Ridge(alpha=3.0)).fit(aw[X_cols], aw["actual_margin"], ridge__sample_weight=aw["ipw"].values)
    pred["IPW Ridge"][te_i] = m2.predict(b[X_cols])
W, L = (tr.won == 1).values, (tr.won == 0).values
y = tr["actual_margin"].values
rows = [{"모델": k, "낙찰 건 MAE": np.abs(v - y)[W].mean(), "실주 건 평균오차": (v - y)[L].mean()} for k, v in pred.items()]
rep(pd.DataFrame(rows).set_index("모델").round(4).to_string())
rep("※ 실주 건의 '땄다면' 마진은 규칙값으로 만들어져 있어 규칙 행의 실주 오차는 0 이 당연하다 (기준선).\n"
    "  Ridge 의 음수 오차 = 낙찰 건으로만 배워서 마진을 낮게 보는 선택 편향. 낙찰 건 MAE 가 좋아 보여도 충격 변형 패턴을 외운 것일 수 있다.")

# ── 6. 환율 변동성과 저장 ──
rep("\n" + "=" * 70); rep("6. 환율 시뮬레이션 설정")
sig = mm.fx_returns.std()
rep(f"월별 로그수익률 {len(mm.fx_returns)}개, 월 변동성 σ = {sig:.2%} (24개월 ≈ {sig*np.sqrt(24):.1%}, 36개월 ≈ {sig*np.sqrt(36):.1%}). 추세 제거(demean).")
rep(f"원가 초과 분포(팀 가정): {dict(zip(mm.cost_overrun_values, mm.cost_overrun_probs))}  ← 데이터엔 0/4%/8% 세 수준만 있어 확률은 가정")
ex = tr[tr.variant == "REAL"].iloc[0]
s = mm.summarize([ex.quote], ex.bep, int(ex.lead_months)).iloc[0]
rep(f"예) {ex.bid_id}: 규칙 마진 {s.margin_rule:.1%} · 기대 마진 {s.margin_mean:.1%} · 10~90% [{s.margin_p10:.1%}, {s.margin_p90:.1%}] · 손실 확률 {s.loss_prob:.1%}")
mm.save(MODELS / "margin_model.pkl"); rep(f"→ 저장: {MODELS / 'margin_model.pkl'}")
rep.save()
