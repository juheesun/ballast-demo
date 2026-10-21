# 밸러스트 (Ballast)

조선소 영업·구매 담당자를 위한 **수주 견적 의사결정 지원 시스템**. 2026 K-조선 해커톤 출품작.

입찰 건 하나를 넣으면 견적가별 **낙찰확률**과 **기대가치(낙찰확률 × (견적가 − 손익분기 선가))**를 계산해서,
손해 보지 않으면서 이길 수 있는 **권장 견적 구간**을 보여줍니다. 환율·원가·경쟁사 가격이 바뀌면 곡선이 어떻게 움직이는지
반사실 시나리오로 확인할 수 있습니다.

## 폴더 구조

```
ballast/
├── data/                    입찰 데이터셋 (데이터 팀 관리)
│   ├── dataset.json         입찰 106건 (실제 10 + 시나리오 96)
│   ├── market_monthly.json  월별 시장 값 (환율, 신조선가 등)
│   └── fx_history.json      원/달러 환율 이력 (월별 2010~, 연별 1990~)
├── docs/                    데이터셋 설명서, 필드 상세
└── modeling/                모델링 (A·B 공통)
    ├── features.py          ★ 공유 전처리 모듈. 모든 모델·시연 화면이 이것만 씀
    ├── win_model.py         낙찰확률 모델 클래스 (WinModel)
    ├── 01_data_validation.py   데이터 검증 3종
    ├── 02_build_features.py    학습 표 생성 + 점검
    ├── 03_train_models.py      로지스틱 회귀 vs LightGBM 학습·비교
    ├── 04_calibration_eval.py  캘리브레이션·결정 평가 + 그림
    └── figures/             평가 그림
```

`modeling/processed/`(중간 결과)와 `modeling/models/`(학습된 모델 .pkl)는 git에 올리지 않습니다.
아래 순서대로 실행하면 각자 컴퓨터에 다시 생깁니다.

## 실행

```bash
pip install -r requirements.txt

# 레포 루트에서
python modeling/01_data_validation.py
python modeling/02_build_features.py
python modeling/03_train_models.py      # → modeling/models/win_logit.pkl
python modeling/04_calibration_eval.py
```

## 낙찰확률 모델 쓰는 법 (B · 시연 화면)

```python
import sys; sys.path.insert(0, "modeling")
from features import load_table, price_grid
from win_model import WinModel

m = WinModel.load("modeling/models/win_logit.pkl")
df = load_table("data/dataset.json")
row = df[df.variant == "REAL"].iloc[0]

grid = price_grid(row, lo=0.85, hi=1.15, n=61)    # 견적가만 바꾼 61개
p = m.predict_proba(grid)                         # 낙찰확률
ev = p * (grid.quote_usd_mn - grid.bep_usd_mn)    # 기대가치 ($mn/척)
band = grid.quote_usd_mn[ev >= 0.85 * ev.max()]   # 권장 구간
recommended = band.min()                          # 권장가 = 권장 구간 하한
```

- 전처리는 반드시 `features.py`를 거칠 것. 각자 따로 하면 모델 결과가 서로 안 맞습니다.
- 가격을 바꾸는 시나리오는 `features.with_price(df, ratio_mult=0.97)`처럼 쓰면 견적가 비율과 손익분기 아래 여부가 같이 다시 계산됩니다.

## 현재 결과 요약 (낙찰확률 모델, A 파트)

| 항목 | 결과 |
|---|---|
| 주 모델 | 로지스틱 회귀, ship 피처 세트 (가격 비율, 리드타임, 크기, 척수, 사양 2종, 신규 선주) |
| 평가 | 실제 건 하나씩 빼고 학습 (8-fold). Brier 0.158 (기준선 0.202), ECE 0.085 |
| 확률 보정 | 하지 않음 (Platt 보정 시 반대로 과소확신) |
| 권장가 정책 | 기대가치 봉우리 대신 **권장 구간 하한** (7건 중 7건 낙찰) |
| LightGBM | 확률을 과신해서 비교용으로만 사용 |

자세한 과정·한계는 `modeling/processed/*_report.txt`(실행 후 생성)와 노션 정리 페이지를 참고하세요.

## 협업 규칙

- `main`에는 바로 push하지 않고, 각자 브랜치에서 작업한 뒤 Pull Request로 합칩니다.
  - 브랜치 이름 예: `modeling-margin`, `modeling-scenario`, `data-update`
- 데이터(`data/`)가 바뀌면 PR 설명에 무엇이 바뀌었는지 적고, `01`~`04`를 다시 돌려 결과가 달라졌는지 확인합니다.
- 새 파이썬 패키지를 쓰면 `requirements.txt`에 추가합니다.
