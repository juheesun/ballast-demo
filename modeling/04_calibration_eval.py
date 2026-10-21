"""
캘리브레이션 중심 평가

기대가치 = 낙찰확률 × (견적가 − BEP) 이므로, 모델이 "70%"라고 하면 실제로 10번 중 7번 이겨야 합니다.
정확도가 높아도 확률이 틀리면 권장 견적가가 엉뚱한 곳에 찍힙니다. 그래서 세 단계로 봅니다.

  1. 확률이 맞는가    : 신뢰도 표, ECE, Brier 분해, 캘리브레이션 기울기 (+ anchor 단위 부트스트랩 신뢰구간)
  2. 보정하면 나아지나 : 중첩 LOAO 안에서 Platt 보정 (test anchor는 보정에도 안 쓰임)
  3. 돈이 되는가      : 각 anchor를 빼고 학습한 모델로 기대가치 곡선을 그려 권장가를 정하고,
                        합성 규칙(실제 계약가까지는 낙찰)으로 실제 이익과 놓친 이익(regret)을 계산

사용법:  python modeling/04_calibration_eval.py   (03_train_models.py 먼저 실행)
결과:    modeling/processed/calibration_report.txt, decision_eval.csv
         modeling/figures/reliability.png, ev_curves.png
"""
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from features import leave_one_anchor_out, load_table, price_grid  # noqa: E402
from win_model import WinModel  # noqa: E402

warnings.filterwarnings("ignore")
DATA = HERE.parent / "data" / "dataset.json"
PROC, FIG = HERE / "processed", HERE / "figures"
FIG.mkdir(exist_ok=True)
RNG = np.random.default_rng(0)
lines = []

MODELS = {"로지스틱": ("logit", "ship"), "LightGBM": ("lgbm", "ship")}
COLORS = {"로지스틱": "#2a78d6", "LightGBM": "#eb6834"}   # 범주 1·2번 슬롯
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BINS = np.linspace(0, 1, 6)                                # 5구간 (표본 72건이라 굵게)


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def head(t):
    out("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


# ================================================================ 지표
def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def reliability_table(y, p):
    idx = np.clip(np.digitize(p, BINS[1:-1]), 0, len(BINS) - 2)
    rows = []
    for b in range(len(BINS) - 1):
        m = idx == b
        rows.append({"구간": f"{BINS[b]:.1f}–{BINS[b+1]:.1f}", "건수": int(m.sum()),
                     "평균 예측": p[m].mean() if m.any() else np.nan,
                     "실제 낙찰률": y[m].mean() if m.any() else np.nan})
    return pd.DataFrame(rows)


def calib_metrics(y, p):
    t = reliability_table(y, p).dropna()
    w = t["건수"] / len(y)
    gap = t["평균 예측"] - t["실제 낙찰률"]
    ece = float((w * gap.abs()).sum())
    # Murphy 분해: Brier ≈ 신뢰도(작을수록 좋음) − 분해능(클수록 좋음) + 불확실성(데이터 고정)
    rel = float((w * gap ** 2).sum())
    res = float((w * (t["실제 낙찰률"] - y.mean()) ** 2).sum())
    # 캘리브레이션 기울기/절편: y ~ a + b·logit(p).  b<1 이면 과신, b>1 이면 소심
    lr = LogisticRegression(penalty=None).fit(logit(p).reshape(-1, 1), y)
    return {"Brier": float(np.mean((p - y) ** 2)), "ECE": ece, "신뢰도항": rel, "분해능항": res,
            "기울기": float(lr.coef_[0][0]), "절편": float(lr.intercept_[0]),
            "평균예측-실제": float(p.mean() - y.mean())}


def cluster_bootstrap(df, col, n=2000):
    """anchor 단위로 다시 뽑기. 독립 단위가 8개라 행 단위로 뽑으면 신뢰구간이 가짜로 좁아짐."""
    anchors = df.anchor_id.unique()
    groups = {a: df[df.anchor_id == a] for a in anchors}
    br, ec = [], []
    for _ in range(n):
        s = pd.concat([groups[a] for a in RNG.choice(anchors, len(anchors))])
        y, p = s.won.values.astype(float), s[col].values
        br.append(np.mean((p - y) ** 2))
        ec.append(calib_metrics(y, p)["ECE"] if len(set(y)) > 1 else np.nan)
    q = lambda v: np.nanpercentile(v, [5, 95])  # noqa: E731
    return q(br), q(ec)


# ================================================================ 예측 만들기
df = load_table(DATA)
y = df.won.astype(bool).values.astype(float)
folds = list(leave_one_anchor_out(df))


def loao_predict(data, kind, fs, platt=False):
    """data 안에서 LOAO 폴드 밖 예측. platt=True면 각 폴드의 train 안에서 다시 LOAO를 돌려
    Platt 보정 계수를 정한 뒤 test에 적용 (test anchor는 보정에도 쓰이지 않음)."""
    p = pd.Series(np.nan, index=data.index)
    for _, tr, te in leave_one_anchor_out(data):
        m = WinModel(kind, fs).fit(data.loc[tr])
        raw = m.predict_proba(data.loc[te])
        if platt:
            inner = loao_predict(data.loc[tr], kind, fs, platt=False)
            cal = LogisticRegression(penalty=None).fit(
                logit(inner.values).reshape(-1, 1), data.loc[tr, "won"].astype(bool))
            raw = cal.predict_proba(logit(raw).reshape(-1, 1))[:, 1]
        p.loc[te] = raw
    return p


preds = pd.DataFrame({"anchor_id": df.anchor_id, "variant": df.variant, "won": y})
for name, (k, fs) in MODELS.items():
    preds[name] = loao_predict(df, k, fs)
    preds[name + "+Platt"] = loao_predict(df, k, fs, platt=True)

# ================================================================ 1. 확률이 맞는가
head("1. 확률이 맞는가 (LOAO 폴드 밖 예측 72건)")
out("ECE: 예측 확률과 실제 낙찰률의 평균 차이 (0에 가까울수록 좋음)")
out("기울기: 1이면 정상, 1보다 작으면 과신(확률을 0·1 쪽으로 너무 밀어냄)")
rows = {}
for c in [c for c in preds.columns if c in MODELS or c.endswith("Platt")]:
    rows[c] = calib_metrics(y, preds[c].values)
    bci, eci = cluster_bootstrap(preds, c)
    rows[c]["Brier 90%CI"] = f"{bci[0]:.3f}–{bci[1]:.3f}"
    rows[c]["ECE 90%CI"] = f"{eci[0]:.3f}–{eci[1]:.3f}"
summary = pd.DataFrame(rows).T
out(summary.to_string(float_format=lambda v: f"{v:.3f}"))

for name in MODELS:
    out(f"\n[{name}] 신뢰도 표")
    out(reliability_table(y, preds[name].values).round(3).to_string(index=False))

# ================================================================ 2. 결정 평가
head("3. 돈이 되는가: 기대가치 곡선으로 고른 견적가의 실제 이익 (척당 $mn)")
out("가정(합성 규칙): 실제 계약가 이하로 내면 낙찰, 넘으면 실주. 최적 = 실제 계약가로 입찰.")
out("놓친 이익 = 최적 이익 − 권장가로 냈을 때 이익.  BEP보다 싼 실제 계약(REAL-03)은 최적이 '입찰 포기'(0).")

GRID_LO, GRID_HI, GRID_N = 0.80, 1.20, 161


def true_profit(quote, real_quote, bep):
    return (quote - bep) if quote <= real_quote + 1e-9 else 0.0


strategies = {}
reals = df[df.variant == "REAL"]
records, curves = [], {}
for a, tr, te in folds:
    r = reals[reals.anchor_id == a].iloc[0]
    real_q, bep, mkt = float(r.quote_usd_mn), float(r.bep_usd_mn), float(r.market_price_usd_mn)
    opt = max(real_q - bep, 0.0)
    g = price_grid(r, GRID_LO, GRID_HI, GRID_N)
    q = g.quote_usd_mn.values.astype(float)
    rec_row = {"anchor": a, "실제 비율": round(real_q / mkt, 3), "최적 이익": round(opt, 2)}
    for name, (k, fs) in MODELS.items():
        m = WinModel(k, fs).fit(df.loc[tr])
        p = m.predict_proba(g)
        ev = p * (q - bep)
        i = int(np.argmax(ev))
        band = q[ev >= 0.85 * ev.max()] if ev.max() > 0 else np.array([np.nan])
        gain = true_profit(q[i], real_q, bep) if ev.max() > 0 else 0.0  # 기대가치<0이면 입찰 포기
        rec_row[f"{name} 권장비율"] = round(q[i] / mkt, 3)
        rec_row[f"{name} 이익"] = round(gain, 2)
        rec_row[f"{name} 실제가∈권장구간"] = bool(np.nanmin(band) <= real_q <= np.nanmax(band))
        # 대안 정책: 봉우리 대신 권장 구간의 하한으로 입찰 (실주 절벽에서 안전거리 확보)
        low = float(np.nanmin(band)) if ev.max() > 0 else np.nan
        rec_row[f"{name} 구간하한 이익"] = round(true_profit(low, real_q, bep), 2) if ev.max() > 0 else 0.0
        curves[(a, name)] = (q / mkt, ev, p)
    # 기준 전략 1: 시장가 그대로
    rec_row["시장가 입찰 이익"] = round(true_profit(mkt, real_q, bep), 2)
    # 기준 전략 2: BEP + 목표마진 5%  (견적 = BEP / (1-0.05))
    rec_row["목표마진5% 이익"] = round(true_profit(bep / 0.95, real_q, bep), 2)
    curves[(a, "_meta")] = (real_q / mkt, bep / mkt)
    records.append(rec_row)

dec = pd.DataFrame(records)
out(dec.to_string(index=False))
dec.to_csv(PROC / "decision_eval.csv", index=False, encoding="utf-8-sig")
tot_opt = dec["최적 이익"].sum()
out(f"\n8건 합계 (척당 $mn) — 가능한 최대 이익 {tot_opt:.1f}")
for col in ["로지스틱 이익", "로지스틱 구간하한 이익", "LightGBM 이익", "LightGBM 구간하한 이익",
            "시장가 입찰 이익", "목표마진5% 이익"]:
    v = dec[col].sum()
    won_n = int((dec[col] > 0).sum())
    out(f"  {col:<18} {v:6.1f}  (최대의 {v / tot_opt:5.1%}, 놓친 이익 {tot_opt - v:5.1f}, "
        f"낙찰 {won_n}/7)")
for name in MODELS:
    out(f"  {name}: 실제 계약가가 권장 구간(기대가치 최고의 85% 이상) 안에 든 건 "
        f"{dec[f'{name} 실제가∈권장구간'].sum()}/8")

# 1·3 사이: 보정 표를 결정 평가 앞에 두면 읽기 순서가 맞지 않아, 2번은 여기서 요약
head("2. Platt 보정 효과 요약")
for name in MODELS:
    b, a_ = summary.loc[name], summary.loc[name + "+Platt"]
    out(f"{name}: Brier {b['Brier']:.3f} → {a_['Brier']:.3f}, ECE {b['ECE']:.3f} → {a_['ECE']:.3f}, "
        f"기울기 {b['기울기']:.2f} → {a_['기울기']:.2f}")

# ================================================================ 그림
from matplotlib import font_manager  # noqa: E402

_installed = {f.name for f in font_manager.fontManager.ttflist}
KFONT = next((f for f in ["Malgun Gothic", "AppleGothic", "Apple SD Gothic Neo", "NanumGothic",
                          "Noto Sans CJK KR", "Noto Sans CJK JP"] if f in _installed), "DejaVu Sans")
plt.rcParams.update({"font.family": KFONT, "axes.unicode_minus": False,
                     "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})

# (1) 신뢰도 그림
fig, ax = plt.subplots(figsize=(6.2, 5.6), dpi=160)
ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls=(0, (4, 3)), zorder=1)
ax.text(0.97, 0.90, "완벽한 보정", color=INK2, fontsize=9, ha="right", rotation=42)
for name in MODELS:
    t = reliability_table(y, preds[name].values).dropna()
    ax.plot(t["평균 예측"], t["실제 낙찰률"], color=COLORS[name], lw=2, zorder=2)
    ax.scatter(t["평균 예측"], t["실제 낙찰률"], s=t["건수"] * 9 + 30, color=COLORS[name],
               edgecolor=SURF, linewidth=2, zorder=3,
               label=f"{name}  (ECE {summary.loc[name, 'ECE']:.3f})")
ax.set_xlim(-0.02, 1.02)
ax.set_ylim(-0.02, 1.02)
ax.set_xlabel("모델이 예측한 낙찰확률")
ax.set_ylabel("실제 낙찰률")
ax.set_title("예측 확률 vs 실제 낙찰률 (점 크기 = 건수)", loc="left", fontsize=12, color=INK)
ax.grid(color=GRID, lw=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK)
fig.tight_layout()
fig.savefig(FIG / "reliability.png")
plt.close(fig)

# (2) anchor별 기대가치 곡선 (작은 그림 8개, 같은 축)
fig, axes = plt.subplots(2, 4, figsize=(13, 6.2), dpi=150, sharex=True)
ymax = max(curves[(a, n)][1].max() for a, *_ in folds for n in MODELS)
ymin = min(curves[(a, n)][1].min() for a, *_ in folds for n in MODELS)
for ax, (a, *_) in zip(axes.flat, folds):
    real_r, bep_r = curves[(a, "_meta")]
    ax.axvspan(GRID_LO, bep_r, color="#f1efe9", zorder=0)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.axvline(real_r, color=INK, lw=1.2, ls=(0, (3, 2)), zorder=1)
    for name in MODELS:
        x, ev, _ = curves[(a, name)]
        i = int(np.argmax(ev))
        ax.plot(x, ev, color=COLORS[name], lw=2, zorder=2)
        ax.scatter([x[i]], [ev[i]], s=46, color=COLORS[name], edgecolor=SURF, linewidth=2, zorder=3)
    ax.set_title(a, loc="left", fontsize=10, color=INK)
    ax.set_ylim(ymin * 1.1, ymax * 1.1)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
for ax in axes[1]:
    ax.set_xlabel("견적가 ÷ 시장 선가")
for ax in axes[:, 0]:
    ax.set_ylabel("기대가치 ($mn/척)")
handles = [plt.Line2D([], [], color=COLORS[n], lw=2, marker="o", label=f"{n} (점 = 권장가)") for n in MODELS]
handles += [plt.Line2D([], [], color=INK, lw=1.2, ls=(0, (3, 2)), label="실제 계약가 (최적)"),
            plt.Rectangle((0, 0), 1, 1, color="#f1efe9", label="BEP 아래 (손해 구간)")]
fig.legend(handles=handles, loc="upper right", ncol=4, frameon=False, fontsize=9, labelcolor=INK)
fig.suptitle("anchor별 기대가치 곡선 — 해당 건을 빼고 학습한 모델", x=0.01, ha="left",
             fontsize=12, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(FIG / "ev_curves.png")
plt.close(fig)

(PROC / "calibration_report.txt").write_text("\n".join(lines), encoding="utf-8")
preds.to_csv(PROC / "calibration_predictions.csv", index=False, encoding="utf-8-sig")
print(f"\n그림: {FIG / 'reliability.png'}, {FIG / 'ev_curves.png'}")
