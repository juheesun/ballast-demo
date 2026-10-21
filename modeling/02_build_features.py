"""
피처 전처리 실행 + 점검

사용법:  python modeling/02_build_features.py
결과:    modeling/processed/train_table.csv   (학습용 표: 식별열 + 원피처 + 정답)
         modeling/processed/feature_check.txt (점검 결과)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from features import (EXCLUDE_VARIANTS, FEATURE_SETS, Preprocessor, load_table,  # noqa: E402
                      leave_one_anchor_out, price_grid, time_split, with_price)

DATA = HERE.parent / "data" / "dataset.json"
OUT = HERE / "processed"
OUT.mkdir(exist_ok=True)
lines = []


def out(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def check(name, ok):
    out(f"  [{'OK' if ok else '실패'}] {name}")
    if not ok:
        raise SystemExit(f"점검 실패: {name}")


# ------------------------------------------------------------ 표 만들기
df = load_table(DATA)
everything = load_table(DATA, training_only=False)
out(f"학습 표: {len(df)}건 (낙찰 {int(df.won.sum())}, 실주 {int((~df.won).sum())}), "
    f"anchor {df.anchor_id.nunique()}개, 제외 변형 {EXCLUDE_VARIANTS}")
out(f"변형별 행 수: {df.variant.value_counts().sort_index().to_dict()}")
df.to_csv(OUT / "train_table.csv", index=False, encoding="utf-8-sig")

# ------------------------------------------------------------ 피처 세트별 결과
out("\n피처 세트별 (전체 학습 표로 fit):")
for name in FEATURE_SETS:
    pre = Preprocessor(name).fit(df)
    X = pre.transform(df)
    out(f"- {name}: {X.shape[1]}열")
    out("  " + pre.describe().replace("\n", "\n  "))

# ------------------------------------------------------------ 점검
out("\n점검:")
check("정답(won)에 결측 없음", df.won.notna().all())
check("outcome 계열 열이 피처 세트에 없음",
      not any(f in s for s in FEATURE_SETS.values() for f in ("won", "actual_margin")))

for name in FEATURE_SETS:
    pre = Preprocessor(name).fit(df)
    X = pre.transform(df)
    check(f"[{name}] 변환 결과에 NaN 없음", not X.isna().any().any())
    if pre.scale:
        check(f"[{name}] 표준화 후 평균≈0, 표준편차≈1",
              np.allclose(X.mean(), 0, atol=1e-9) and np.allclose(X.std(ddof=0), 1, atol=1e-9))

# 폴드마다 train에서만 fit 하는지: test 통계가 섞이지 않아야 함
folds = list(leave_one_anchor_out(df))
check(f"Leave-One-Anchor-Out 폴드 {len(folds)}개, train/test anchor 겹침 없음",
      all(set(df.loc[tr, "anchor_id"]).isdisjoint(df.loc[te, "anchor_id"]) for _, tr, te in folds))
tr_idx, te_idx = time_split(df)
check(f"시간 분할 train {len(tr_idx)} / test {len(te_idx)}, anchor 겹침 없음",
      set(df.loc[tr_idx, "anchor_id"]).isdisjoint(df.loc[te_idx, "anchor_id"]))
pre = Preprocessor("full").fit(df.loc[tr_idx])
Xte = pre.transform(df.loc[te_idx])
check("train에 없던 조선소가 test에 나와도 변환됨 (열 순서 유지)",
      list(Xte.columns) == pre.columns_ and not Xte.isna().any().any())

# 시나리오 엔진 함수가 데이터셋 값을 재현하는지
re = with_price(everything)
check("with_price가 원래 price_ratio를 재현 (오차 0.001 이내)",
      np.allclose(re.price_ratio, everything.price_ratio.astype(float), atol=1e-3))
check("with_price가 원래 below_bep를 재현",
      (re.below_bep == everything.below_bep.astype(bool)).all())
g = price_grid(df.iloc[0])
check("price_grid: 61개 견적가, price_ratio 0.85~1.15",
      len(g) == 61 and np.isclose(g.price_ratio.min(), 0.85) and np.isclose(g.price_ratio.max(), 1.15))

out(f"\n중복 가중치(sample_weight) 분포: {df.sample_weight.round(3).value_counts().sort_index().to_dict()}")
out(f"\n저장: {OUT / 'train_table.csv'}")
(OUT / "feature_check.txt").write_text("\n".join(lines), encoding="utf-8")
