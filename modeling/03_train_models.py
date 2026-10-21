"""
낙찰확률 모델 학습 · 비교 (로지스틱 회귀 vs LightGBM)

평가: Leave-One-Anchor-Out(8-fold)이 메인, 시간 분할이 보조.
      확률을 기대가치 계산에 쓰므로 정확도보다 Brier·log loss(확률이 맞는가)를 우선으로 봄.

사용법:  python modeling/03_train_models.py
결과:    modeling/models/win_logit.pkl, win_lgbm.pkl   (전체 학습 데이터로 다시 학습한 최종 모델)
         modeling/processed/oof_predictions.csv          (폴드 밖 예측, 캘리브레이션 평가용)
         modeling/processed/model_report.txt
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from features import leave_one_anchor_out, load_table, price_grid, time_split  # noqa: E402
from win_model import WinModel  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)
DATA = HERE.parent / "data" / "dataset.json"
PROC = HERE / "processed"
MODELS = HERE / "models"
PROC.mkdir(exist_ok=True)
lines = []


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def metrics(y, p):
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return {"Brier": brier_score_loss(y, p), "LogLoss": log_loss(y, p, labels=[0, 1]),
            "AUC": roc_auc_score(y, p) if len(set(y)) > 1 else np.nan,
            "정확도": ((p >= 0.5) == y).mean()}


# ------------------------------------------------------------ 베이스라인
def baseline_base_rate(tr, te):
    return np.full(len(te), tr.won.mean())


def baseline_threshold(tr, te):
    """price_ratio ≤ t 면 낙찰. t는 train에서 정확도 최대로."""
    x, y = tr.price_ratio.values.astype(float), tr.won.astype(bool).values
    best_t = max(np.unique(x), key=lambda t: ((x <= t) == y).mean())
    return np.where(te.price_ratio.values <= best_t, 0.95, 0.05)  # 0/1 대신 0.95/0.05


# ------------------------------------------------------------ 데이터
df = load_table(DATA)
y = df.won.astype(bool).values
out(f"학습 데이터 {len(df)}건, anchor {df.anchor_id.nunique()}개, 낙찰률 {y.mean():.0%}")

CONFIGS = [WinModel(k, fs, w) for k in ("logit", "lgbm")
           for fs in ("core", "ship", "full") for w in (False, True)]

# ------------------------------------------------------------ LOAO
oof = pd.DataFrame({"bid_id": df.bid_id, "anchor_id": df.anchor_id,
                    "variant": df.variant, "price_ratio": df.price_ratio, "won": y})
folds = list(leave_one_anchor_out(df))
for name, fn in [("기준: 낙찰률 상수", baseline_base_rate), ("기준: 가격비 임계값", baseline_threshold)]:
    oof[name] = np.nan
    for _, tr, te in folds:
        oof.loc[te, name] = fn(df.loc[tr], df.loc[te])
for cfg in CONFIGS:
    oof[cfg.name] = np.nan
    for _, tr, te in folds:
        m = WinModel(cfg.kind, cfg.feature_set, cfg.use_weight).fit(df.loc[tr])
        oof.loc[te, cfg.name] = m.predict_proba(df.loc[te])

model_cols = [c for c in oof.columns if c.startswith(("기준", "logit", "lgbm"))]
res = pd.DataFrame({c: metrics(y, oof[c].values) for c in model_cols}).T
res["anchor별 정확도 최저"] = [
    min(((oof.loc[te, c] >= 0.5) == y[te]).mean() for _, _, te in folds) for c in model_cols]
res = res.sort_values("Brier")
out("\n" + "=" * 70 + "\nLeave-One-Anchor-Out (폴드 밖 예측 72건 기준, Brier·LogLoss는 낮을수록 좋음)\n" + "=" * 70)
out(res.round(3).to_string())
oof.to_csv(PROC / "oof_predictions.csv", index=False, encoding="utf-8-sig")

best = {k: res[[i.startswith(k) for i in res.index]].index[0] for k in ("logit", "lgbm")}
out(f"\n종류별 최고 설정: {best}")

# ------------------------------------------------------------ 시간 분할 (보조)
tr_idx, te_idx = time_split(df)
out("\n" + "=" * 70 + f"\n시간 분할 (train {len(tr_idx)}건 → test {len(te_idx)}건, anchor 2개라 참고만)\n" + "=" * 70)
rows = {}
for name, fn in [("기준: 낙찰률 상수", baseline_base_rate), ("기준: 가격비 임계값", baseline_threshold)]:
    rows[name] = metrics(y[te_idx], fn(df.loc[tr_idx], df.loc[te_idx]))
for cfg in CONFIGS:
    if cfg.name in best.values():
        m = WinModel(cfg.kind, cfg.feature_set, cfg.use_weight).fit(df.loc[tr_idx])
        rows[cfg.name] = metrics(y[te_idx], m.predict_proba(df.loc[te_idx]))
out(pd.DataFrame(rows).T.round(3).to_string())

# ------------------------------------------------------------ 최종 모델 (전체 데이터)
finals = {}
for kind, fname in (("logit", "win_logit.pkl"), ("lgbm", "win_lgbm.pkl")):
    cfg = next(c for c in CONFIGS if c.name == best[kind])
    m = WinModel(cfg.kind, cfg.feature_set, cfg.use_weight).fit(df)
    m.save(MODELS / fname)
    finals[kind] = m
    out(f"\n저장: models/{fname}  ({m.name})  " + m.pre_.describe().split("\n")[0])

out("\n" + "=" * 70 + "\n로지스틱 계수 해석\n" + "=" * 70)
coef = finals["logit"].coefficients()
out(coef.round(3).to_string())
if "price_ratio" in coef.index:
    b = coef.loc["price_ratio", "원단위 계수"]
    out(f"→ 견적가를 시장가 대비 1%p 올리면 낙찰 오즈가 {np.exp(b * 0.01):.2f}배 "
        f"({(np.exp(b * 0.01) - 1):+.0%})")
if "lead_months" in coef.index:
    b = coef.loc["lead_months", "원단위 계수"]
    out(f"→ 납기를 1개월 늦게 제시하면 낙찰 오즈가 {np.exp(b):.2f}배 ({(np.exp(b) - 1):+.0%})")

# ------------------------------------------------------------ 견적가-낙찰확률 곡선 점검
out("\n" + "=" * 70 + "\n견적가 곡선 점검 (anchor별 실제 건, price_ratio 0.85~1.15)\n" + "=" * 70)
reals = df[df.variant == "REAL"]
tab = []
for _, r in reals.iterrows():
    g = price_grid(r)
    row = {"anchor": r.anchor_id, "실제 비율": round(float(r.price_ratio), 3)}
    for kind, m in finals.items():
        p = m.predict_proba(g)
        row[f"{kind} 단조감소"] = bool(np.all(np.diff(p) <= 1e-9))
        row[f"{kind} P(실제가)"] = round(float(m.predict_proba(r.to_frame().T)[0]), 2)
        cross = g.price_ratio.values[np.argmax(p < 0.5)] if (p < 0.5).any() else np.nan
        row[f"{kind} 50%선"] = round(float(cross), 3) if p[0] >= 0.5 else "처음부터<50%"
    tab.append(row)
out(pd.DataFrame(tab).to_string(index=False))

(PROC / "model_report.txt").write_text("\n".join(lines), encoding="utf-8")
print(f"\n보고서: {PROC / 'model_report.txt'}")
