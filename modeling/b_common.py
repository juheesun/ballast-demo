# -*- coding: utf-8 -*-
"""B 공통: 경로, A 코드와 맞물리는 설정, 원본 JSON 로더, 환율 수익률, 그래프 폰트.

A(낙찰확률 모델) 코드는 features.py / win_model.py 를 '문서에 적힌 사용법'으로만 부릅니다.
  features.load_table(path), features.price_grid(row, lo, hi, n), WinModel.load(path), model.predict_proba(df)
컬럼 이름이 A 코드와 다르면 아래 COL 만 고치면 됩니다. check_contract() 가 어긋남을 알려줍니다.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

# ───────────────────────── 경로 ─────────────────────────
HERE = Path(__file__).resolve().parent            # .../modeling
ROOT = HERE.parent                                # 저장소 최상위 (modeling/ 의 부모)
# 데이터 위치: 저장소는 data/ 안에, 처음 받은 폴더는 최상위에 dataset.json 이 있음 → 둘 다 지원
DATA_DIR = next((d for d in (ROOT / "data", ROOT) if (d / "dataset.json").exists()), ROOT / "data")
DATASET, FX_HISTORY, MARKET_MONTHLY = DATA_DIR / "dataset.json", DATA_DIR / "fx_history.json", DATA_DIR / "market_monthly.json"
MODELS, PROCESSED, FIGURES = HERE / "models", HERE / "processed", HERE / "figures"
for _p in (MODELS, PROCESSED, FIGURES):
    _p.mkdir(exist_ok=True)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# ───────────── A 코드와 맞물리는 설정 (이름이 다르면 여기만 수정) ─────────────
COL = dict(
    bid_id="bid_id",          # 입찰 번호 (REAL-03, REAL-03-A ...)
    quote="quote_usd_mn",     # 견적가 ($mn/척)
    bep="bep_usd_mn",         # 손익분기 선가 ($mn)
    ratio="price_ratio",      # 견적가 ÷ 시장 선가 (낙찰확률 모델의 입력)
    lead="lead_months",       # 납기월 − 입찰월 (낙찰확률 모델의 입력)
)
# A 문서: 이 이진 피처들은 anchor 1~2개를 가리키는 '이름표'처럼 작동 → 시나리오 토글/설명에 쓰지 않기
BINARY_LABEL_COLS = ("is_new_owner", "spec_scrubber", "spec_lng_df")
WIN_MODEL_PATH = MODELS / "win_logit.pkl"
WIN_OOF_PATH = PROCESSED / "win_oof.csv"          # (선택) A 가 저장한 LOAO 예측: bid_id, p_oof
DEFAULT_WIN_FEATURES = ["price_ratio", "lead_months", "log_size", "num_ships",
                        "spec_scrubber", "spec_lng_df", "is_new_owner"]   # A 'ship' 세트 (7개)
EXCLUDE_VARIANTS_DEFAULT = ("E",)                 # A: 시나리오 E 는 학습 제외

# ───────────────────────── 원본 JSON ─────────────────────────
def months_between(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-")); yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def load_raw() -> pd.DataFrame:
    """dataset.json → 입찰 1건 = 1행. B 가 쓰는 값(원가·환율·결과)만 뽑아 둠. 인덱스 = bid_id."""
    data = json.load(open(DATASET, encoding="utf-8"))
    rows = []
    for g in data:
        for r in [g["real"]] + g.get("scenarios", []):
            o, c, p, s = r["outcome"], r["cost_at_bid"], r["price"], r["ship"]
            rows.append(dict(
                bid_id=r["bid_id"], variant=(r.get("scenario") or {}).get("variant", "REAL"),
                anchor_id=r["anchor_id"], use_in_training=bool(r["use_in_training"]),
                won=int(o["won"]), actual_margin=o.get("actual_margin"),
                quote=p["quote_usd_mn"], market_price=p["market_price_usd_mn"],
                bep=c["bep_usd_mn"], expected_fx=c["expected_fx"], est_cost_krw_100m=c["est_cost_krw_100m"],
                delivery_fx=o.get("delivery_fx"), cost_overrun=o.get("cost_overrun") or 0.0,
                lead_months=months_between(s["bid_month"], s["delivery_month"]),
                shipyard=s["shipyard"]))
    return pd.DataFrame(rows).set_index("bid_id", drop=False)


def train_ids(raw: pd.DataFrame, features_module=None) -> list:
    """A 와 같은 학습 행: use_in_training 이고 제외 변형(E)이 아닌 것."""
    excl = tuple(getattr(features_module, "EXCLUDE_VARIANTS", EXCLUDE_VARIANTS_DEFAULT)) if features_module else EXCLUDE_VARIANTS_DEFAULT
    m = raw["use_in_training"] & ~raw["variant"].isin(excl)
    return raw.index[m].tolist()


def load_fx_returns(demean: bool = True) -> np.ndarray:
    """fx_history.json 월별 로그수익률. demean=True 면 과거 추세를 빼고 변동성만 사용."""
    fx = json.load(open(FX_HISTORY, encoding="utf-8"))["monthly"]
    s = pd.DataFrame(fx).sort_values("year_month")["usd_krw"].values
    r = np.diff(np.log(s))
    return r - r.mean() if demean else r

# ───────────────────────── A 연결 ─────────────────────────
def load_win_assets():
    """(features 모듈, 학습된 WinModel, 전체 표) 를 돌려줌."""
    try:
        import features, win_model
    except ImportError as e:
        raise SystemExit(f"A 담당 코드(features.py, win_model.py)를 {HERE} 에서 찾지 못했습니다: {e}")
    if not WIN_MODEL_PATH.exists():
        raise SystemExit(f"{WIN_MODEL_PATH} 이 없습니다. A 의 03_train_models.py 를 먼저 실행하세요.")
    model = win_model.WinModel.load(str(WIN_MODEL_PATH))
    table = features.load_table(str(DATASET))
    return features, model, table


def win_feature_names(model, features_module) -> list:
    """낙찰확률 모델이 쓰는 피처 이름. 못 찾으면 A 'ship' 세트 기본값."""
    for attr in ("feature_names", "features", "cols", "feature_names_", "columns"):
        v = getattr(model, attr, None)
        if isinstance(v, (list, tuple)) and v and all(isinstance(x, str) for x in v):
            return list(v)
    fs = getattr(features_module, "FEATURE_SETS", None)
    if isinstance(fs, dict) and "ship" in fs:
        return list(fs["ship"])
    return list(DEFAULT_WIN_FEATURES)


def check_contract(features_module, model, table) -> None:
    """A 코드와의 약속을 점검. 어긋나면 어디를 고칠지 알려주고 멈춘다."""
    need = [COL["bid_id"], COL["quote"], COL["bep"], COL["ratio"], COL["lead"]]
    miss = [c for c in need if c not in table.columns]
    if miss:
        raise SystemExit(f"[계약 위반] load_table() 결과에 {miss} 컬럼이 없습니다.\n"
                         f"  현재 컬럼: {list(table.columns)}\n  → b_common.py 의 COL 을 A 코드의 이름에 맞게 고치세요.")
    row = table.iloc[0]
    g = features_module.price_grid(row, 0.85, 1.15, 31)
    miss = [c for c in (COL["quote"], COL["bep"], COL["ratio"], COL["lead"]) if c not in g.columns]
    if miss:
        raise SystemExit(f"[계약 위반] price_grid() 결과에 {miss} 컬럼이 없습니다. 현재 컬럼: {list(g.columns)}")
    p = np.asarray(model.predict_proba(g)).reshape(len(g), -1)[:, -1]
    if not np.all(np.diff(p) <= 1e-9):
        print("⚠ 견적가가 오를 때 낙찰확률이 단조 감소하지 않습니다. 시나리오 그래프가 이상하게 보일 수 있어요.")
    print(f"[계약 점검 통과] 피처 {win_feature_names(model, features_module)}")

# ───────────────────────── 그래프 · 보고서 ─────────────────────────
_FONT_READY = False


def ascii_minus(s):
    """그래프 글자용: 유니코드 마이너스(−)를 일반 하이픈(-)으로. 나눔고딕에 U+2212 가 없어 □ 로 보이는 것을 막는다."""
    return str(s).replace("\u2212", "-")


def setup_plot():
    """한글 폰트 준비. 노트북 커널이 폰트 설치 전에 matplotlib 을 이미 불러온 경우에도 시스템 폰트를 다시 등록한다."""
    global _FONT_READY
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    if not _FONT_READY:
        names = {f.name for f in fm.fontManager.ttflist}
        if not names & {"NanumGothic", "Malgun Gothic", "AppleGothic", "Noto Sans CJK KR"}:
            for f in fm.findSystemFonts():                      # Colab: apt 로 설치한 나눔 폰트를 직접 등록
                if "Nanum" in f:
                    try: fm.fontManager.addfont(f)
                    except Exception: pass
            names = {f.name for f in fm.fontManager.ttflist}
        for cand in ("NanumGothic", "Malgun Gothic", "AppleGothic", "Noto Sans CJK KR"):
            if cand in names:
                plt.rcParams["font.family"] = [cand, "DejaVu Sans"]   # 한글은 cand, 없는 기호(−, ★ 등)는 DejaVu 로
                break
        else:
            print("⚠ 한글 폰트를 못 찾았습니다. 그래프 글자가 깨질 수 있어요. (Colab: 노트북 0단계를 다시 실행하고 런타임을 재시작)")
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.dpi"] = 110
        _FONT_READY = True
    return plt


class Report:
    """화면에 찍으면서 파일로도 저장."""
    def __init__(self, path: Path):
        self.path, self.lines = path, []

    def __call__(self, *a):
        s = " ".join(str(x) for x in a)
        print(s); self.lines.append(s)

    def save(self):
        self.path.write_text("\n".join(self.lines), encoding="utf-8")
        print(f"→ 저장: {self.path}")


pct = lambda r: f"{(r - 1) * 100:+.1f}%"
