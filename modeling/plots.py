# -*- coding: utf-8 -*-
"""그래프: 기대가치 곡선(권장 구간·손익분기선), 환율 위험."""
from __future__ import annotations
import numpy as np
from b_common import setup_plot, FIGURES, pct, ascii_minus

BLUE, GRAY, RED, GREEN, ORANGE = "#3b4fc4", "#8e8e99", "#c0392b", "#2e8b57", "#d9822b"


def plot_ev(res, base_res=None, title="견적가별 기대가치", fname=None):
    """res: 보여줄 조건 EvalResult, base_res: 비교할 기본 조건(회색 점선)."""
    plt = setup_plot(); g, s = res.grid, res.summary
    x = (g["ratio"] - 1) * 100
    fig, ax = plt.subplots(figsize=(8.2, 4.3))
    ax.axhline(0, color=GRAY, lw=.8)
    if base_res is not None:
        gb = base_res.grid
        ax.plot((gb["ratio"] - 1) * 100, gb["ev"], "--", color=GRAY, label="기본 조건")
        ax.axvline((base_res.summary["bep_ratio"] - 1) * 100, color=GRAY, ls=":", lw=1)
    ax.plot(x, g["ev"], color=BLUE, lw=2.6, label="바뀐 조건" if base_res is not None else "기대가치")
    ax.axvspan(x.min(), (s["bep_ratio"] - 1) * 100, color="#f3e0cc", alpha=.8, label="손익분기선 아래")
    ax.axvline((s["bep_ratio"] - 1) * 100, color=RED, ls="--", lw=1.2)
    if s["band_lo"] is not None:
        r_lo, r_hi = s["band_lo"] / (s["quote_now"] / s["ratio_now"]), s["band_hi"] / (s["quote_now"] / s["ratio_now"])
        ax.axvspan((r_lo - 1) * 100, (r_hi - 1) * 100, color="#c9d4f5", alpha=.6, label="권장 구간 (기대가치 ≥ 최고의 85%)")
        ev_lo = float(np.interp(r_lo, g["ratio"], g["ev"]))
        ax.plot((r_lo - 1) * 100, ev_lo, "*", color=ORANGE, ms=15, zorder=5, label=f"권장가 ${s['recommended']:.1f}mn (구간 하한)")
    ib = int(np.argmax(g["ev"]))
    ax.plot(x[ib], g["ev"][ib], "o", mfc="white", mec=BLUE, ms=8, mew=2, label="기대가치 봉우리")
    ax.axvline((s["ratio_now"] - 1) * 100, color="k", lw=1.4)
    ax.text((s["ratio_now"] - 1) * 100, ax.get_ylim()[1], " 제안가", va="top", fontsize=8)
    ax.set_xlabel("견적가 (시장 기준가 대비 %)"); ax.set_ylabel("기대가치 ($mn/척)")
    ax.set_title(ascii_minus(title)); ax.legend(fontsize=7.5, loc="best"); plt.tight_layout()
    if fname:
        fig.savefig(FIGURES / fname, bbox_inches="tight"); plt.close(fig)
    return fig


def plot_fx_risk(res, title="환율·원가 위험", fname=None):
    plt = setup_plot(); g, s = res.grid, res.summary
    x = (g["ratio"] - 1) * 100
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.8))
    ax = axes[0]
    ax.plot(x, g["loss_prob"] * 100, color=RED, lw=2.2); ax.fill_between(x, 0, g["loss_prob"] * 100, color=RED, alpha=.12)
    ax.axvline((s["ratio_now"] - 1) * 100, color="k", lw=1.2)
    ax.set_title(f"환율·원가 손실 확률 (인도까지 {s['months']}개월)"); ax.set_xlabel("견적가 (시장 기준가 대비 %)"); ax.set_ylabel("%")
    ax = axes[1]
    ax.plot(x, g["ev"], "--", color=GRAY, label="기대가치 (A 공식)")
    ax.plot(x, g["ev_risk"], color=BLUE, lw=2.2, label="환율·원가 위험 반영")
    ax.axhline(0, color=GRAY, lw=.8); ax.axvline((s["ratio_now"] - 1) * 100, color="k", lw=1.2)
    ax.set_title("기대가치 ($mn/척)"); ax.set_xlabel("견적가 (시장 기준가 대비 %)"); ax.legend(fontsize=8)
    plt.suptitle(ascii_minus(title), y=1.02); plt.tight_layout()
    if fname:
        fig.savefig(FIGURES / fname, bbox_inches="tight"); plt.close(fig)
    return fig
