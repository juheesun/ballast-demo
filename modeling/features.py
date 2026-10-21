"""
피처 전처리 공유 모듈 (낙찰확률 모델 · 마진 모델 · 시나리오 엔진 공통)

두 모델과 시연 화면이 같은 입력을 같은 방식으로 변환하도록, 전처리는 전부 여기서만 합니다.

    from features import load_table, Preprocessor, FEATURE_SETS, leave_one_anchor_out

    df = load_table("dataset.json")                 # 학습용 행만, 피처 열 포함
    pre = Preprocessor("core").fit(df_train)        # train 폴드에서만 fit (누수 방지)
    X_train = pre.transform(df_train)
    X_test  = pre.transform(df_test)

의존성: pandas, numpy (sklearn 없이 동작)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ 설정
# 학습에서 뺄 시나리오 변형.
#   E: 견적을 5% 낮췄는데 실주. 원인(경쟁사 가격)이 입력에 없어서
#      '더 싸면 진다'는 잘못된 신호를 줌. 데이터 팀이 L을 뺀 것과 같은 이유.
#   데이터 팀과 합의가 바뀌면 이 튜플만 고치면 됩니다. 빈 튜플 = 전부 사용.
EXCLUDE_VARIANTS: tuple[str, ...] = ("E",)

NUMERIC = [
    "price_ratio",          # 견적가 ÷ 시장 선가 (기대가치 곡선의 x축)
    "lead_months",          # 납기월 − 입찰월 (개월)
    "log_size_teu",         # log(TEU)
    "num_ships",
    "usd_krw",
    "newbuild_13k_usd_mn",
    "prev_year_target_achievement",
    "steel_plate_krw_ton",  # 지금은 값이 하나뿐이라 fit 때 자동 제거됨
    "yard_backlog_years",
    "kr_share",
    "container_orders_year",
    "secondhand_index",
]
BINARY = ["spec_scrubber", "spec_lng_df", "is_new_owner"]
CATEGORICAL = ["shipyard"]

# 피처 세트: 작게 시작해서 하나씩 늘리며 성능이 실제로 오르는지 확인
FEATURE_SETS: dict[str, list[str]] = {
    # anchor 안에서 실제로 변하는 입력만. 1순위.
    "core": ["price_ratio", "lead_months"],
    # 배 자체의 특성 추가 (anchor마다 고정 → '이름표' 위험 있음)
    "ship": ["price_ratio", "lead_months", "log_size_teu", "num_ships",
             "spec_scrubber", "spec_lng_df", "is_new_owner"],
    # 조선소·시장 값까지 전부 (8개 anchor로는 과적합 가능성 큼, 비교용)
    "full": ["price_ratio", "lead_months", "log_size_teu", "num_ships",
             "spec_scrubber", "spec_lng_df", "is_new_owner", "shipyard",
             "usd_krw", "newbuild_13k_usd_mn", "prev_year_target_achievement",
             "steel_plate_krw_ton", "yard_backlog_years", "kr_share",
             "container_orders_year", "secondhand_index"],
}

# 일부러 피처로 쓰지 않는 입력과 이유
#   below_bep        : price_ratio < 0.9 와 같은 값 (중복)
#   bep_usd_mn, est_cost_krw_100m, cost_ratio, expected_fx
#                    : 전부 시장 선가 × 0.9 에서 파생 → 새 정보 없음
#   quote_usd_mn, market_price_usd_mn : 절대 금액. 비율(price_ratio)로 대체
#   bid_date, bid_month : 시간 분할 키. 피처로 넣으면 anchor 이름표가 됨


# ------------------------------------------------------------------ 로드
def _month_diff(later: str, earlier: str) -> int:
    return (pd.Period(later, "M") - pd.Period(earlier, "M")).n


def bid_to_row(bid: dict) -> dict:
    """입찰 1건(dataset.json 형식, outcome 없어도 됨)을 평평한 dict로.
    학습 데이터와 시연 화면의 새 입찰이 반드시 이 함수 하나를 거치게 할 것."""
    s, p, m, c = bid["ship"], bid["price"], bid.get("market", {}), bid.get("cost_at_bid", {})
    o = bid.get("outcome") or {}
    sc = bid.get("scenario") or {}
    return {
        # 식별·분할용 (피처 아님)
        "bid_id": bid.get("bid_id"),
        "anchor_id": bid.get("anchor_id", bid.get("bid_id")),
        "variant": sc.get("variant", "REAL" if bid.get("origin") == "real" else None),
        "use_in_training": bool(bid.get("use_in_training", False)),
        "bid_month": s["bid_month"],
        # 원값 (시나리오 엔진이 가격을 바꿀 때 필요)
        "quote_usd_mn": p.get("quote_usd_mn"),
        "market_price_usd_mn": p.get("market_price_usd_mn"),
        "bep_usd_mn": c.get("bep_usd_mn"),
        "below_bep": c.get("below_bep"),
        # 피처
        "price_ratio": p.get("price_ratio"),
        "lead_months": _month_diff(s["delivery_month"], s["bid_month"]),
        "log_size_teu": np.log(s["size_teu"]) if s.get("size_teu") else np.nan,
        "num_ships": s.get("num_ships"),
        "spec_scrubber": s.get("spec_scrubber"),
        "spec_lng_df": s.get("spec_lng_df"),
        "is_new_owner": s.get("is_new_owner"),
        "shipyard": s.get("shipyard"),
        **{k: m.get(k) for k in ["usd_krw", "newbuild_13k_usd_mn",
                                  "prev_year_target_achievement", "steel_plate_krw_ton",
                                  "yard_backlog_years", "kr_share",
                                  "container_orders_year", "secondhand_index"]},
        # 정답 (입력 금지)
        "won": o.get("won"),
        "actual_margin": o.get("actual_margin"),
    }


def load_table(path: str | Path, training_only: bool = True,
               exclude_variants: tuple[str, ...] = EXCLUDE_VARIANTS) -> pd.DataFrame:
    """dataset.json → 한 행 = 입찰 1건인 표.
    training_only=True 이면 use_in_training=True 이고 exclude_variants에 없는 행만."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for g in raw:
        for b in [g["real"]] + g.get("scenarios", []):
            rows.append(bid_to_row(b))
    df = pd.DataFrame(rows)
    if training_only:
        df = df[df.use_in_training & ~df.variant.isin(exclude_variants)]
    df = df.reset_index(drop=True)
    df["won"] = df["won"].astype("boolean")
    df["sample_weight"] = dedup_weight(df)
    return df


def dedup_weight(df: pd.DataFrame) -> pd.Series:
    """같은 anchor 안에서 입력이 완전히 같은 행(REAL·J·K)은 사실상 같은 점이 3번 들어간 것.
    가중치 1/중복수를 주면 그 점이 1번 들어간 것과 같아짐. 쓸지는 모델 쪽에서 선택."""
    keys = ["anchor_id"] + [c for c in FEATURE_SETS["full"] if c in df.columns]
    cnt = df.groupby(keys, dropna=False)["bid_id"].transform("size")
    return (1.0 / cnt).astype(float)


def attach_market(bid: dict, market_monthly_path: str | Path) -> dict:
    """시연용: 새 입찰의 bid_month로 market_monthly.json에서 그달 값을 찾아 market 묶음을 채움."""
    mm = json.loads(Path(market_monthly_path).read_text(encoding="utf-8"))
    month = bid["ship"]["bid_month"]
    hit = next((r for r in mm if r["year_month"] == month), None)
    if hit is None:
        raise KeyError(f"market_monthly에 {month} 값이 없습니다")
    out = dict(bid)
    out["market"] = {k: v for k, v in hit.items() if k not in ("year_month", "assumed_fields")}
    return out


# ------------------------------------------------------------------ 시나리오 엔진용
def with_price(df: pd.DataFrame, quote_usd_mn=None, ratio_mult: float | None = None) -> pd.DataFrame:
    """가격만 바꾼 사본. 가격에 묶인 열(price_ratio, below_bep)을 함께 다시 계산.
      with_price(df, quote_usd_mn=200)  : 견적가를 직접 지정
      with_price(df, ratio_mult=0.97)   : '가격 3% 인하'
      with_price(df, ratio_mult=1.05)   : '경쟁사가 5% 낮게' = 우리가 상대적으로 5% 비싸짐"""
    out = df.copy()
    if quote_usd_mn is not None:
        out["quote_usd_mn"] = quote_usd_mn
    elif ratio_mult is not None:
        out["quote_usd_mn"] = out["quote_usd_mn"] * ratio_mult
    out["price_ratio"] = out["quote_usd_mn"] / out["market_price_usd_mn"]
    out["below_bep"] = out["quote_usd_mn"] < out["bep_usd_mn"]
    return out


def price_grid(row: pd.Series | pd.DataFrame, lo: float = 0.85, hi: float = 1.15,
               n: int = 61) -> pd.DataFrame:
    """입찰 1건을 견적가만 바꿔 n개로 복제 (기대가치 곡선용). x축은 price_ratio."""
    base = row.to_frame().T if isinstance(row, pd.Series) else row.iloc[[0]]
    ratios = np.linspace(lo, hi, n)
    grid = pd.concat([base] * n, ignore_index=True)
    grid["quote_usd_mn"] = ratios * grid["market_price_usd_mn"].astype(float)
    return with_price(grid)


# ------------------------------------------------------------------ 변환기
class Preprocessor:
    """피처 세트 선택 → 결측 대체 → 범주 원-핫 → 분산 0 제거 → 표준화.
    통계값(중앙값, 평균, 표준편차, 범주 목록)은 fit에 넣은 train 폴드에서만 계산."""

    def __init__(self, feature_set: str | list[str] = "core", scale: bool = True):
        self.features = FEATURE_SETS[feature_set] if isinstance(feature_set, str) else list(feature_set)
        self.scale = scale  # 로지스틱 회귀 True, LightGBM은 False여도 됨

    def _raw(self, df: pd.DataFrame) -> pd.DataFrame:
        X = pd.DataFrame(index=df.index)
        for f in self.features:
            if f in BINARY:
                X[f] = df[f].astype("boolean").fillna(False).astype(float)
            elif f in CATEGORICAL:
                X[f] = df[f].astype("string").fillna("미상")
            else:
                X[f] = pd.to_numeric(df[f], errors="coerce").astype(float)
        return X

    def fit(self, df: pd.DataFrame) -> "Preprocessor":
        X = self._raw(df)
        self.num_cols_ = [f for f in self.features if f not in CATEGORICAL]
        self.cat_cols_ = [f for f in self.features if f in CATEGORICAL]
        self.medians_ = X[self.num_cols_].median()
        self.categories_ = {c: sorted(X[c].unique()) for c in self.cat_cols_}
        Z = self._encode(X)
        std = Z.std(ddof=0)
        # 값이 하나뿐인 열 (부동소수 오차로 std가 1e-16 같은 값이 나오므로 고유값 수로 판정)
        self.dropped_ = [c for c in Z.columns if Z[c].nunique() <= 1]
        self.columns_ = [c for c in Z.columns if c not in self.dropped_]
        self.mean_ = Z[self.columns_].mean()
        self.std_ = std[self.columns_]
        return self

    def _encode(self, X: pd.DataFrame) -> pd.DataFrame:
        Z = X[self.num_cols_].fillna(self.medians_)
        for c in self.cat_cols_:
            # 첫 범주를 기준으로 빼서(drop-first) 로지스틱 계수가 해석되게
            for cat in self.categories_[c][1:]:
                Z[f"{c}={cat}"] = (X[c] == cat).astype(float)
        return Z

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        Z = self._encode(self._raw(df))
        for c in self.columns_:          # train에 없던 범주 → 0
            if c not in Z:
                Z[c] = 0.0
        Z = Z[self.columns_].astype(float)
        if self.scale:
            Z = (Z - self.mean_) / self.std_
        return Z

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)

    def describe(self) -> str:
        s = f"피처 {len(self.columns_)}개: {self.columns_}"
        if self.dropped_:
            s += f"\n  분산 0이라 제거: {self.dropped_}"
        return s


# ------------------------------------------------------------------ 분할
def leave_one_anchor_out(df: pd.DataFrame):
    """메인 평가: anchor 하나씩 test로 (8-fold). 같은 실제 건의 변형이 train/test에 갈라지지 않음."""
    for a in sorted(df.anchor_id.unique()):
        te = df.anchor_id == a
        yield a, df.index[~te], df.index[te]


def time_split(df: pd.DataFrame, cut: str = "2025-11"):
    """보조 평가: bid_month ≤ cut 이 train. 같은 anchor는 입찰월이 같아 자동으로 그룹 분할됨."""
    tr = df.bid_month <= cut
    return df.index[tr], df.index[~tr]
