# API 명세 (v0.1)

기준 주소: `http://localhost:8000` · 자동 문서: `/docs` · 프론트는 `/api/...` 로 호출 (Vite 프록시)
담당: A(리드/통합)가 명세를 관리한다. 새 API 를 추가하거나 응답을 바꿀 때는 이 파일을 먼저 고치고 알린다.

## 공통
- 금액 단위는 모두 **$M(백만 달러) / 척**. 비율은 소수(0.58 = 58%).
- `ratio` = 견적가 ÷ 시장 기준가 (1.075 = 시장가 대비 +7.5%)
- 응답의 `source`: `"model"`(A 의 낙찰확률 모델) | `"mock"`(예시 계산). `mock` 이면 화면에 '예시 데이터'를 표시한다.

## MVP1·2 (구현됨)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 상태, `source`, 예시 모드 사유 |
| GET | `/api/bids` | 분석 가능한 입찰 목록 (실제 10건) |
| GET | `/api/bids/{bid_id}/curve` | 견적가별 곡선 + 요약. 쿼리: `comp_pct, steel_pct, fx_pct, fx_krw, delay_months` |
| POST | `/api/scenario/compare` | 기준 vs 시나리오 곡선·요약·차이·기대가치 분해 |
| GET | `/api/bids/{bid_id}/scenario-table` | 모든 프리셋의 낙찰확률·기대가치·손실확률 한 표 |
| GET | `/api/scenarios/presets` | 시나리오 버튼 목록 (화면의 버튼은 이 목록으로 그림) |
| GET | `/api/fx/latest` | 최신 USD/KRW (market_monthly.json) |

### 시나리오 파라미터
| 이름 | 의미 | 범위 |
|---|---|---|
| `comp_pct` | 경쟁사 견적 변화 (-0.05 = 5% 싸게) | -0.5 ~ 0.5 |
| `steel_pct` | 후판가 변화 | -0.5 ~ 1.0 |
| `fx_pct` | 환율 변화 | -0.5 ~ 0.5 |
| `fx_krw` | 환율을 원 단위로 지정 (`fx_pct` 보다 우선) | > 0 |
| `delay_months` | 납기 지연 개월 | 0 ~ 36 |

※ 경쟁사·후판·환율 반영 방식은 학습 결과가 아니라 팀이 정한 규칙이다 (`modeling/scenario_engine.py` 참고).

### `GET /api/bids/{id}/curve` 응답 (요약)
- `summary`: `quote_now, ratio_now, bep, bep_ratio, months, p_now, profit_now, ev_now, loss_prob_now, margin_mean_now, best_quote, best_ratio, best_ev, band_lo, band_hi, recommended, recommended_below_bep, fx_assumed, fx_breakeven`
- `grid[]`: `ratio, quote, p, ev, ev_risk, loss_prob, margin_rule, margin_mean, margin_p10, margin_p50, margin_p90`
- `recommended` = 기대가치가 최고점의 85% 이상인 구간의 하한 (A 의 정책). 기대가치가 모두 0 이하면 `null`.
- `fx_breakeven` = 이 제안가에서 원화 매출 = 원가 가 되는 인도 시점 환율.

### `POST /api/scenario/compare`
요청: `{ "bid_id": "REAL-10", "scenario": { "comp_pct": -0.05, "steel_pct": 0.1 } }`
응답: `{ source, bid_id, base, scenario, delta, decomposition }`
- `decomposition`: 기대가치 변화 = 낙찰확률 효과 + 건당 이익 효과 (제안가 기준)

## MVP3·4 (담당 팀원이 채움 · 초안)

| 메서드 | 경로 | 설명 | 담당 |
|---|---|---|---|
| GET/POST | `/api/suppliers` | 공급사 목록 / 등록 | MVP3 |
| GET/PUT | `/api/suppliers/{id}` | 공급사 조회 / 수정 (재무, 업계 평가, 거래기간·거래액) | MVP3 |
| GET | `/api/suppliers/{id}/score` | 평가 점수 | MVP3 |
| GET | `/api/history` | 낙찰/실주 이력 (필터: result, from, to, shipyard) | MVP4 |
| GET | `/api/history/stats` | 낙찰률, 실주 사유별 건수 | MVP4 |


---
## v0.2 추가

### POST /api/chat  (MVP2 · 질문형 시나리오)
한국어 문장을 조건으로 바꿔 계산하고 답을 문장으로 돌려준다. 해석은 규칙 기반(`backend/chat.py`)이라 외부 API 가 필요 없다.

요청: `{ "bid_id": "REAL-10", "message": "경쟁사가 5% 싸게 들어오면?", "params": { 현재 적용 중인 조건 } }`
응답: `params`(누적된 조건), `active`/`understood`(칩 문구), `lines`(답변 문장), `metrics`(낙찰확률·예상 마진·적자확률), `notes`(지원하지 않는 질문 안내), `changed`
- 새 문장에 나온 조건만 덮어쓰고 나머지는 유지한다. "초기화"라고 하면 모두 기준으로 돌아간다.
- 알아듣는 조건: 경쟁사 견적(%) · 후판가(%) · 환율(% 또는 원) · 납기 지연(개월) · 우리 견적가(%)
- 환헤지·납기 단축·선주/사양 질문은 계산하지 않고 `notes` 로 이유를 알린다.

### 시나리오 조건에 `quote_pct` 추가
`/api/scenario/compare` 의 `scenario` 와 `/api/bids/{id}/curve` 에 `quote_pct`(-0.3~0.3). 곡선은 그대로 두고 제안가 위치만 옮겨 그 견적가의 낙찰확률·기대가치를 읽는다.

### GET /api/history  (MVP4 · 과거 이력)
`data/dataset.json` 의 입찰 106건(실제 10 + 시나리오 96). 행: `id, origin(real|scenario), variant, date, shipyard, owner, quote, market, ratio, won, loss_reason, margin, note`.
실제 공개 건은 모두 낙찰이고 실주 사례는 시나리오 변형이므로 화면에 구분 표시를 한다.

### MVP3 공급사 평가
현재는 서버 API 없이 브라우저(localStorage)에만 저장하는 화면이다. 점수 규칙(재무 40·평판 30·거래 30)은 임시이며 `frontend/src/pages/SuppliersPage.jsx` 의 `score()` 만 고치면 된다. 서버 저장이 필요하면 `GET/POST /api/suppliers` 를 추가한다.

## v0.3 추가 (견적 리스크 2차 수정)

### GET /api/bids 응답에 선종·규모
`ship_type`("컨테이너선"), `size_teu`, `num_ships` 추가. 입찰 정보 줄에 "컨테이너선 15,500TEU · 2척"으로 보인다.

### POST /api/bids/{id}/risk  (MVP1 · 원가 통화·대금 분할·환헤지 반영)
계산은 `backend/quote_risk.py`. 낙찰확률·기대가치·권장가는 `/curve` 와 같고, 환율·원가 위험만 아래 가정으로 다시 계산한다.

요청(전부 선택, 비우면 선종·규모별 기본값):
```json
{ "costs": [{ "key": "equip", "share": 0.5, "usd_share": 0.6 }, ...],
  "milestones": [{ "key": "contract", "at": 0, "weight": 0.2 }, ...],
  "hedge": 0.3, "loss_target": 0.10 }
```
- `costs`: 원가 항목(후판·강재/인건비/엔진·기자재/기타)의 비중과 그중 달러로 사는 비중. 환율 위험은 원화 원가에만 걸린다.
- `milestones`: 대금 분할(기본 계약·착공·진수·인도 20/20/20/40). `at` 은 납기 대비 시점(0~1). 받는 시점 환율로 환산한다.
- `hedge`: 받을 달러 중 입찰 시점 환율로 고정하는 비율 (선물환 비용 0 가정).
- `loss_target`: 안전 시작 견적가·판단 도구의 적자확률 기준.
- 비중 합계가 100%가 아니면 비율대로 나누고 `notes` 로 알린다.

응답: `assumptions`(적용된 값), `summary`(적자확률·예상 마진·`fx_breakeven`·`krw_cost_share`·`safe_quote` 등), `grid`(견적가별 적자확률·마진 범위),
`money`(억 원: 척당/전체 척 이익, 실행원가와 항목별 금액, 안전 시작 견적가), `simple`(예전 가정의 적자확률·손익분기 환율),
`decision`(`raise`: 견적가를 올려 기준을 맞출 때 / `hedge`: 헤지로 맞출 때 필요한 비율), `backtest`(2010년 이후 납기 길이 구간에서 실제 환율이 시뮬레이션 10~90% 범위에 든 비율).
가정을 (원화 100%, 인도 100%, 헤지 0)으로 두면 `/curve` 의 적자확률·마진과 정확히 같다.
