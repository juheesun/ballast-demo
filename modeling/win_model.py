"""
낙찰확률 모델 (로지스틱 회귀 · LightGBM)

    from win_model import WinModel
    m = WinModel.load("modeling/models/win_logit.pkl")
    p = m.predict_proba(df)          # df: features.load_table / bid_to_row 형식, 낙찰확률 배열

시연·시나리오 엔진(B)은 이 클래스만 쓰면 됩니다. 전처리는 안에서 features.Preprocessor로 처리.
의존성: pandas, numpy, scikit-learn, lightgbm
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from features import Preprocessor

# 단조 제약: 이 피처가 커지면 낙찰확률은 내려가기만 해야 함
#   price_ratio  : 비싸게 낼수록 불리
#   lead_months  : 납기를 늦게 제시할수록 불리 (시나리오 C)
MONOTONE_DECREASING = {"price_ratio", "lead_months"}


def make_estimator(kind: str, columns: list[str]):
    if kind == "logit":
        # 데이터가 72건이라 L2 규제를 기본값(C=1)으로 둠
        return LogisticRegression(C=1.0, max_iter=1000)
    if kind == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(
            n_estimators=200, learning_rate=0.05,
            num_leaves=4, max_depth=2, min_child_samples=5,   # 작은 데이터용으로 얕게
            reg_lambda=1.0, subsample=1.0, colsample_bytree=1.0,
            monotone_constraints=[-1 if c in MONOTONE_DECREASING else 0 for c in columns],
            monotone_constraints_method="advanced",
            random_state=0, verbose=-1,
        )
    raise ValueError(kind)


class WinModel:
    """Preprocessor + 분류기를 하나로 묶은 낙찰확률 모델."""

    def __init__(self, kind: str = "logit", feature_set: str | list[str] = "core",
                 use_weight: bool = False):
        self.kind = kind
        self.feature_set = feature_set
        self.use_weight = use_weight

    def fit(self, df: pd.DataFrame) -> "WinModel":
        # 로지스틱은 표준화 필요, 트리는 불필요
        self.pre_ = Preprocessor(self.feature_set, scale=(self.kind == "logit")).fit(df)
        X = self.pre_.transform(df)
        y = df["won"].astype(bool).values
        self.est_ = make_estimator(self.kind, list(X.columns))
        w = df["sample_weight"].values if self.use_weight else None
        self.est_.fit(X, y, sample_weight=w)
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        X = self.pre_.transform(df)
        return self.est_.predict_proba(X)[:, 1]

    @property
    def name(self) -> str:
        fs = self.feature_set if isinstance(self.feature_set, str) else "custom"
        return f"{self.kind}/{fs}{'/w' if self.use_weight else ''}"

    def coefficients(self) -> pd.DataFrame:
        """로지스틱 전용: 표준화 계수와, 원래 단위로 되돌린 '1단위당 오즈비'."""
        if self.kind != "logit":
            raise ValueError("로지스틱 모델에서만 계수를 해석할 수 있습니다")
        coef = pd.Series(self.est_.coef_[0], index=self.pre_.columns_)
        raw = coef / self.pre_.std_
        return pd.DataFrame({"표준화 계수": coef, "원단위 계수": raw,
                             "오즈비(원단위 +1)": np.exp(raw)})

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str | Path) -> "WinModel":
        with open(path, "rb") as f:
            return pickle.load(f)
