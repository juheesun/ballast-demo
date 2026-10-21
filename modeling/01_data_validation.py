"""
데이터 검증 3종 (낙찰확률 모델 착수 전 점검)

  ① 낙찰 여부가 단순 규칙으로 결정되는가 (모델이 '합성 규칙'만 외우게 되는지)
  ② 손익분기(BEP)·마진 분포가 쓸 만한가
  ③ 학습/평가 분할에서 누수가 생기는가 (anchor 그룹, 시간 분할)

사용법:  python modeling/01_data_validation.py
         (레포 루트에서 실행. dataset.json 경로를 인자로 줘도 됨)
결과:    콘솔 출력 + modeling/processed/validation_report.txt
의존성:  pandas, numpy
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "dataset.json"
OUT = Path(__file__).resolve().parent / "processed" / "validation_report.txt"

# 모델 입력 후보 (outcome·scenario·메모 필드는 제외)
MEMO = {"ship.owner", "ship.spec", "ship.size_source", "price.total_krw_100m",
        "price.per_ship_krw_100m", "price.fx_used", "cost_at_bid.est_cost_source"}
INPUT_GROUPS = ("ship", "price", "market", "cost_at_bid")

lines = []


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def section(t):
    out("\n" + "=" * 70)
    out(t)
    out("=" * 70)


# ---------------------------------------------------------------- 로드
def load(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for g in raw:
        real = g["real"]
        q0 = real["price"]["quote_usd_mn"]
        for r in [real] + g.get("scenarios", []):
            sc = r.get("scenario") or {}
            f = {"bid_id": r["bid_id"], "anchor": r["anchor_id"],
                 "variant": sc.get("variant", "REAL"),
                 "train": bool(r.get("use_in_training")),
                 "size_source": r["ship"].get("size_source")}
            for grp in INPUT_GROUPS + ("outcome",):
                for k, v in r[grp].items():
                    f[f"{grp}.{k}"] = v
            f["qrel"] = round(r["price"]["quote_usd_mn"] / q0, 3)  # 실제 견적 대비
            b = pd.Period(r["ship"]["bid_month"], "M")
            dl = pd.Period(r["ship"]["delivery_month"], "M")
            f["lead_months"] = (dl - b).n
            rows.append(f)
    df = pd.DataFrame(rows)
    df["won"] = df["outcome.won"].astype(bool)
    return df


def best_threshold(x, y):
    """x <= t 이면 낙찰로 보는 단일 임계값 중 정확도 최대"""
    best = (0.0, None)
    for t in np.unique(x):
        acc = ((x <= t) == y).mean()
        if acc > best[0]:
            best = (acc, t)
    return best


df = load(DATA)
tr = df[df.train].copy()
input_cols = [c for c in df.columns
              if c.split(".")[0] in INPUT_GROUPS and c not in MEMO]

section("개요")
out(f"전체 {len(df)}건 / 학습용 {len(tr)}건 (낙찰 {tr.won.sum()}, 실주 {(~tr.won).sum()}, "
    f"낙찰률 {tr.won.mean():.0%})")
out(f"독립 단위(anchor) {tr.anchor.nunique()}개 → 실제로 서로 다른 입찰 상황은 이만큼뿐")

# ---------------------------------------------------------------- ①
section("① 낙찰 여부가 단순 규칙으로 결정되는가")

t = tr.groupby("variant").agg(n=("won", "size"), won=("won", "mean"),
                              qrel=("qrel", "first")).sort_values("qrel")
out("변형별 낙찰률 (qrel = 실제 견적 대비 비율)")
out(t.to_string())

lead0 = tr.groupby("anchor").lead_months.transform("min")
rule = (tr.qrel <= 1.0) & (tr.lead_months == lead0)
acc = (rule == tr.won).mean()
miss = tr.loc[rule != tr.won, "variant"].value_counts().to_dict()
out(f"\n규칙 '실제 견적 이하 & 납기 지연 없음 → 낙찰' 정확도: {acc:.1%}")
out(f"  규칙과 어긋나는 행: {miss}")

mono = tr[tr.variant != "C"].groupby("qrel").won.mean()
out("\n견적 비율별 낙찰률 (납기 변형 C 제외):")
out(mono.to_string())
viol = [q for q in mono.index if q < 1.0 and mono[q] < mono.get(1.0, 1)]
if viol:
    out(f"  ⚠ 단조성 위반: 견적이 더 싼 {viol}에서 지고 1.00에서는 이김 "
        "(E: 경쟁사 가격이 입력에 없어 모델이 설명할 수 없는 행)")

real_rows = df[df.variant == "REAL"].set_index("anchor")
out("\nanchor별 실제 건의 price_ratio와 크기 출처:")
out(real_rows[["price.price_ratio", "size_source"]].to_string())
circ = real_rows[real_rows.size_source.str.startswith("추정", na=False)
                 & real_rows.index.isin(tr.anchor)]
out(f"  ⚠ 학습 anchor 중 {len(circ)}/{tr.anchor.nunique()}개는 크기를 단가로 역산 → "
    "price_ratio가 구조적으로 1.00 근처")

a, thr = best_threshold(tr["price.price_ratio"].values, tr.won.values)
out(f"\n전체 공통 price_ratio 임계값 하나로 분류: 정확도 {a:.1%} (임계 {thr:.4f})")
out(f"  비교: 전부 '실주'로 찍으면 {1 - tr.won.mean():.1%}")

# ---------------------------------------------------------------- ②
section("② 손익분기(BEP)·마진 분포")

ratio = (df["cost_at_bid.bep_usd_mn"] / df["price.market_price_usd_mn"]).round(4)
out(f"BEP ÷ 시장 선가: 고유값 {sorted(ratio.unique())}")
if ratio.nunique() == 1:
    out("  ⚠ 모든 행에서 BEP = 시장 선가 × 0.90 → BEP는 시장 선가 외 정보가 없음")
same = ((df["price.price_ratio"] < ratio) == df["cost_at_bid.below_bep"]).all()
out(f"below_bep ⇔ price_ratio < {ratio.iloc[0]}: {same} "
    "(→ below_bep는 price_ratio와 중복)")
out(f"below_bep=True: 전체 {df['cost_at_bid.below_bep'].sum()}건, 학습 "
    f"{tr['cost_at_bid.below_bep'].sum()}건, 그중 anchor별 "
    f"{tr[tr['cost_at_bid.below_bep']].anchor.value_counts().to_dict()}")

won = tr[tr.won]
m = won["outcome.actual_margin"]
out(f"\n낙찰 건 실제 마진 (n={len(m)}): 평균 {m.mean():+.1%}, 중앙 {m.median():+.1%}, "
    f"최소 {m.min():+.1%}, 최대 {m.max():+.1%}")
out(won.groupby("variant")["outcome.actual_margin"]
    .agg(["count", "min", "mean", "max"]).round(4).to_string())
neg_real = real_rows[(real_rows["outcome.actual_margin"] < 0)
                     & real_rows.index.isin(tr.anchor)]
for a_, r in neg_real.iterrows():
    out(f"  ⚠ 실제 수주 {a_}의 마진이 {r['outcome.actual_margin']:+.1%} "
        f"(price_ratio {r['price.price_ratio']:.3f} < 0.90). 시장 선가 보정값 확인 필요")
out("  마진 차이는 거의 outcome 필드(인도 환율, 원가 초과)에서 나옴 → 입력으로는 예측 불가")
lost_m = tr.loc[~tr.won, "outcome.actual_margin"].notna().sum()
out(f"실주 행에도 actual_margin이 {lost_m}건 채워져 있음('땄다면' 가정치) → 마진 모델 학습에서 제외")

# ---------------------------------------------------------------- ③
section("③ 분할 누수")

zero_var = [c for c in input_cols if tr[c].nunique() <= 1]
out(f"분산 0 (값이 하나뿐) 입력 {len(zero_var)}개 → 제거: {zero_var}")
within = [c for c in input_cols if (tr.groupby("anchor")[c].nunique() > 1).any()]
out(f"anchor 안에서 변하는 입력: {within}")
id_like = [c for c in input_cols if c not in zero_var and c not in within]
out(f"anchor마다 고정된 입력 {len(id_like)}개 → 사실상 'anchor 이름표'로 작동할 위험:")
out("  " + ", ".join(f"{c}({tr[c].nunique()})" for c in id_like))

cols = [c for c in input_cols if c not in zero_var]
dup = tr.groupby("anchor").apply(
    lambda g: g.duplicated(subset=cols, keep=False).sum(), include_groups=False)
out(f"\nanchor 안에서 입력이 완전히 같은 행: {dup.to_dict()} "
    "(REAL·J·K는 outcome만 다름 → 같은 점이 3배 가중)")
conf = tr.groupby(cols, dropna=False).won.nunique()
out(f"입력이 같은데 정답이 다른 묶음: {(conf > 1).sum()}개")

month_ok = (tr.groupby("anchor")["ship.bid_month"].nunique() == 1).all()
out(f"\n같은 anchor의 행이 모두 같은 bid_month인가: {month_ok} "
    "→ 시간 분할이면 anchor가 train/test에 갈라지지 않음")
cut = "2025-11"
trn, tst = tr[tr["ship.bid_month"] <= cut], tr[tr["ship.bid_month"] > cut]
out(f"시간 분할(≤{cut}): train {len(trn)}건 {sorted(trn.anchor.unique())} / "
    f"test {len(tst)}건 {sorted(tst.anchor.unique())} (test 낙찰 {tst.won.sum()})")
out("  ⚠ test가 anchor 2개뿐 → 평가 수치가 크게 흔들림")

loao = []
for a_ in sorted(tr.anchor.unique()):
    tt, te = tr[tr.anchor != a_], tr[tr.anchor == a_]
    _, t_ = best_threshold(tt["price.price_ratio"].values, tt.won.values)
    loao.append(((te["price.price_ratio"] <= t_) == te.won).mean())
out(f"\n베이스라인(price_ratio 임계값) Leave-One-Anchor-Out 정확도: "
    f"평균 {np.mean(loao):.1%}, anchor별 {[f'{x:.0%}' for x in loao]}")

# ---------------------------------------------------------------- 저장
OUT.parent.mkdir(exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\n저장: {OUT}")
