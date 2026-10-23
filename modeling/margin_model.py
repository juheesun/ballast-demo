# -*- coding: utf-8 -*-
"""마진 모델 (구조식 + 환율·원가 몬테카를로).

데이터에서 확인된 사실 (05_train_margin.py 가 검증):
    실제 마진 = 1 − 실제 원가 ÷ (견적가 × 인도 환율 ÷ 100)
    실제 원가 = 추정 원가 × (1 + 원가 초과율)
→ 입찰 시점 마진은  1 − (1 + 원가초과) × BEP ÷ (견적가 × g),   g = 인도환율 ÷ 입찰환율.
입찰 시점에 모르는 것은 g 와 원가초과 두 가지뿐이라, 회귀로 '배우지' 않고 분포에서 뽑아 기대 마진·손실 확률을 계산한다.
(낙찰 건만으로 회귀하면 선택 편향 때문에 마진을 낮게 배움 → 05_train_margin.py 참고)
"""
from __future__ import annotations
import itertools, math, pickle
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class MarginModel:
    fx_returns: np.ndarray                                    # 월별 로그수익률 (추세 제거)
    cost_overrun_values: tuple = (0.0, 0.04, 0.08)            # 데이터에 나온 원가 초과 수준 (실제/D/K 변형)
    cost_overrun_probs: tuple = (0.5, 0.3, 0.2)               # ※ 팀 가정. 실제 분포는 데이터로 알 수 없음
    n_sims: int = 5000
    seed: int = 42
    _cache: dict = field(default_factory=dict, repr=False)

    # ── 충격 뽑기: 같은 난수를 견적가·시나리오 전체에 재사용(공통 난수) → 곡선이 매끄럽고 비교가 공정 ──
    def shocks(self, months: int):
        months = max(int(months), 1)
        if months not in self._cache:
            rng = np.random.default_rng(self.seed)
            g = np.exp(rng.choice(self.fx_returns, size=(self.n_sims, months), replace=True).sum(axis=1))
            ov = rng.choice(self.cost_overrun_values, size=self.n_sims, p=self.cost_overrun_probs)
            self._cache[months] = (g, ov)
        return self._cache[months]

    @staticmethod
    def rule_margin(quote, bep):
        return 1.0 - np.asarray(bep, float) / np.asarray(quote, float)

    def summarize(self, quote, bep, months: int, overrun_scale: float = 1.0) -> pd.DataFrame:
        """견적가 배열별: 규칙 마진, 기대 마진, 10/50/90% 마진, 마진<0 확률(환율·원가 손실 확률), 기대 건당 이익($mn)."""
        q = np.atleast_1d(np.asarray(quote, float))
        g, ov = self.shocks(months)
        cost = (1.0 + ov * overrun_scale)[None, :] * float(bep) / g[None, :]       # 인도 시점 원가($mn 환산)
        profit = q[:, None] - cost
        margin = profit / q[:, None]
        return pd.DataFrame({
            "margin_rule": self.rule_margin(q, bep),
            "margin_mean": margin.mean(axis=1),
            "margin_p10": np.percentile(margin, 10, axis=1),
            "margin_p50": np.percentile(margin, 50, axis=1),
            "margin_p90": np.percentile(margin, 90, axis=1),
            "loss_prob": (margin < 0).mean(axis=1),
            "profit_mean": profit.mean(axis=1),
        })

    def save(self, path):
        d = {k: getattr(self, k) for k in ("fx_returns", "cost_overrun_values", "cost_overrun_probs", "n_sims", "seed")}
        pickle.dump(d, open(path, "wb"))

    @classmethod
    def load(cls, path):
        return cls(**pickle.load(open(path, "rb")))


def margin_shapley(quote, bep, g, overrun, quote_ref=None) -> dict:
    """마진 변화를 세 요인(견적가·환율·원가초과)으로 정확히 나눈다 (Shapley, 요인 3개라 8가지 조합을 전부 계산).
    기준: 견적가=quote_ref, g=1, 원가초과=0 → 바뀐 값: quote, g, overrun.  합 = 마진 변화량."""
    quote_ref = quote if quote_ref is None else quote_ref
    base = dict(q=quote_ref, g=1.0, ov=0.0); new = dict(q=quote, g=g, ov=overrun)
    f = lambda s: 1.0 - (1.0 + s["ov"]) * bep / (s["q"] * s["g"])
    names = ["q", "g", "ov"]; out = {n: 0.0 for n in names}
    for n in names:
        others = [x for x in names if x != n]
        for k in range(len(others) + 1):
            for sub in itertools.combinations(others, k):
                w = math.factorial(k) * math.factorial(len(names) - k - 1) / math.factorial(len(names))
                s0 = {x: (new[x] if x in sub else base[x]) for x in names}
                s1 = dict(s0); s1[n] = new[n]
                out[n] += w * (f(s1) - f(s0))
    return {"견적가": out["q"], "환율": out["g"], "원가 초과": out["ov"], "합계": f(new) - f(base)}
