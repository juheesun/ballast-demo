# -*- coding: utf-8 -*-
"""SHAP 요인 분해: ① 낙찰확률(글로벌/이 입찰/시나리오 차이) ② 기대가치 변화 ③ 마진 변화.

낙찰확률 모델(A)은 모델 종류와 상관없이 쓰도록 '모델 불가지' 방식(permutation)으로 설명한다.
확률(0~1) 공간에서 계산하므로 값은 '%p 기여'로 읽는다.
※ A 문서: 신규 선주·스크러버·LNG 는 anchor 이름표처럼 작동 → 막대는 회색으로 표시하고 해석에서 제외.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from b_common import COL, BINARY_LABEL_COLS, setup_plot, FIGURES, ascii_minus
from plots import BLUE, GRAY, RED, GREEN

SEED = 42
NICE = {"price_ratio": "견적가 비율", "lead_months": "납기까지 개월", "log_size": "선박 크기(log)", "num_ships": "척수",
        "is_new_owner": "신규 선주*", "spec_scrubber": "스크러버*", "spec_lng_df": "LNG 이중연료*"}
nice = lambda c: NICE.get(c, c)


class WinExplainer:
    def __init__(self, engine, feats: list, train_tbl: pd.DataFrame):
        import shap
        self.engine, self.feats, self.train = engine, feats, train_tbl.reset_index(drop=True)
        template = self.train.iloc[0].to_dict()

        def f(X):
            df = pd.DataFrame([template] * len(X)); df[feats] = np.asarray(X, float)
            return engine._predict(df)
        self.f = f
        masker = shap.maskers.Independent(self.train[feats].to_numpy(float), max_samples=len(self.train))
        self.explainer = shap.Explainer(f, masker, algorithm="permutation", seed=SEED)
        self.n_evals = 2 * len(feats) + 1 + 200

    def values(self, X: pd.DataFrame):
        sv = self.explainer(X[self.feats].to_numpy(float), max_evals=self.n_evals)
        return pd.DataFrame(sv.values, columns=self.feats), float(np.mean(sv.base_values))

    def global_importance(self) -> pd.Series:
        v, _ = self.values(self.train)
        return v.abs().mean().sort_values()

    def scenario_row(self, bid_id: str, sc=None) -> pd.DataFrame:
        """제안가 기준 입력 한 줄 (시나리오 반영)."""
        r = self.engine.row(bid_id).copy()
        if sc is not None:
            r[COL["ratio"]] = r[COL["ratio"]] / (1 + sc.comp_pct)
            r[COL["lead"]] = r[COL["lead"]] + sc.delay_months
            for k, v in sc.overrides.items(): r[k] = v
        return pd.DataFrame([r])

    def local(self, bid_id: str, sc=None):
        v, base = self.values(self.scenario_row(bid_id, sc))
        return v.iloc[0], base

    def scenario_diff(self, bid_id: str, sc) -> pd.Series:
        return self.local(bid_id, sc)[0] - self.local(bid_id, None)[0]


def _colors(index, vals):
    return [GRAY if c in BINARY_LABEL_COLS else (RED if v < 0 else GREEN) for c, v in zip(index, vals)]


def plot_global(imp: pd.Series, base_val: float | None = None, fname=None, title="글로벌 요인 중요도"):
    plt = setup_plot()
    fig, ax = plt.subplots(figsize=(6.6, 3.8))
    ax.barh([nice(c) for c in imp.index], imp.values * 100, color=[GRAY if c in BINARY_LABEL_COLS else BLUE for c in imp.index])
    ax.set_xlabel("평균 |SHAP| (낙찰확률 %p)"); ax.set_title(title)
    ax.text(0.99, 0.02, "* 회색: anchor 이름표 가능성 → 해석 제외", transform=ax.transAxes, ha="right", fontsize=7.5, color="#555")
    plt.tight_layout()
    if fname:
        fig.savefig(FIGURES / fname, bbox_inches="tight"); plt.close(fig)
    return fig


def plot_local(sv: pd.Series, base_val: float, p_now: float, title: str, fname=None):
    plt = setup_plot(); s = sv.sort_values()
    fig, ax = plt.subplots(figsize=(6.6, 3.8))
    ax.barh([nice(c) for c in s.index], s.values * 100, color=_colors(s.index, s.values))
    ax.axvline(0, color="k", lw=.8); ax.set_xlabel("낙찰확률 기여 (%p)")
    ax.set_title(ascii_minus(f"{title}\n낙찰확률 {p_now:.1%} = 평균 {base_val:.1%} + 요인 합 {s.sum()*100:+.1f}%p"), fontsize=10)
    plt.tight_layout()
    if fname:
        fig.savefig(FIGURES / fname, bbox_inches="tight"); plt.close(fig)
    return fig


def plot_scenario_breakdown(cmp: dict, diff: pd.Series, label: str, fname=None):
    """왼쪽: 기대가치 변화 = 낙찰확률 효과 + 건당 이익 효과 / 오른쪽: 낙찰확률 변화의 피처별 기여."""
    plt = setup_plot(); b, s = cmp["base"].summary, cmp["scen"].summary
    ev_b, ev_s, d_p, d_pr = b["ev_now"], s["ev_now"], cmp["d_ev_prob"], cmp["d_ev_profit"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.9), gridspec_kw={"width_ratios": [1, 1.2]})
    ax = axes[0]
    lab = ["기본\n기대가치", "낙찰확률\n효과", "건당 이익\n효과", "바뀐 조건\n기대가치"]
    bottoms = [0, ev_b + min(d_p, 0), ev_b + d_p + min(d_pr, 0), 0]
    heights = [ev_b, abs(d_p), abs(d_pr), ev_s]
    cols = ["#8aa0e6", GREEN if d_p >= 0 else RED, GREEN if d_pr >= 0 else RED, BLUE]
    ax.bar(lab, heights, bottom=bottoms, color=cols)
    for i, v in enumerate([ev_b, d_p, d_pr, ev_s]):
        ax.text(i, bottoms[i] + heights[i], f"{v:+.2f}" if i in (1, 2) else f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("$mn/척"); ax.set_title("기대가치 변화 분해 (제안가 기준)")
    ax = axes[1]; d = diff[diff.abs() > 1e-4].sort_values()
    if len(d): ax.barh([nice(c) for c in d.index], d.values * 100, color=_colors(d.index, d.values))
    ax.axvline(0, color="k", lw=.8); ax.set_xlabel("낙찰확률 변화 기여 (%p)")
    ax.set_title(f"낙찰확률 {b['p_now']:.1%} → {s['p_now']:.1%} 의 요인")
    plt.suptitle(ascii_minus(f"요인 분해 · {label}"), y=1.02); plt.tight_layout()
    if fname:
        fig.savefig(FIGURES / fname, bbox_inches="tight"); plt.close(fig)
    return fig


def plot_margin_shapley(contrib: dict, label: str, fname=None):
    plt = setup_plot()
    keys = ["견적가", "환율", "원가 초과"]; vals = [contrib[k] * 100 for k in keys]
    fig, ax = plt.subplots(figsize=(5.8, 3.3))
    ax.barh(keys, vals, color=[GREEN if v >= 0 else RED for v in vals]); ax.axvline(0, color="k", lw=.8)
    for i, v in enumerate(vals): ax.text(v, i, f" {v:+.1f}%p", va="center", fontsize=9)
    ax.set_xlabel("마진 변화 기여 (%p)"); ax.set_title(ascii_minus(f"마진 요인 분해 · {label}\n합계 {contrib['합계']*100:+.1f}%p"), fontsize=10)
    plt.tight_layout()
    if fname:
        fig.savefig(FIGURES / fname, bbox_inches="tight"); plt.close(fig)
    return fig
