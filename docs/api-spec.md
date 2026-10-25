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
| GET/POST | `/api/suppliers` | 공급사 목록(점수 높은 순) / 등록 | MVP3 · 구현됨 |
| GET/PUT/DELETE | `/api/suppliers/{id}` | 공급사 조회 / 수정 / 삭제 (재무, 업계 평판, 거래기간·거래액) | MVP3 · 구현됨 |
| GET | `/api/suppliers/{id}/score` | 평가 점수 (`sc`, `label`) | MVP3 · 구현됨 |
| POST | `/api/suppliers/score-preview` | 저장 없이 점수만 계산 | MVP3 · 구현됨 |
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

---
## v0.3 추가 (MVP2 · 시나리오)

### POST /api/scenario/margin-path
계약부터 인도까지 달마다 마진 범위. 계산은 `backend/margin_path.py` (modeling/ 의 MarginModel 과 같은 난수라 마지막 달 값 = 카드의 예상 마진·적자 확률).
요청: `/api/scenario/compare` 와 같음 → `{ "bid_id": "REAL-05", "scenario": { "fx_pct": -0.05 } }`
응답: `{ source, bid_id, base, scenario, milestones }`
- `base` / `scenario`: `{ quote, bep, months, points[] }`, `points[]` = `{ month, p10, p50, p90, mean, loss_prob }` (month 0 = 계약, months = 인도)
- `milestones[]`: `{ month, label }` 계약·강재절단·탑재·진수·인도. 납기를 4등분한 화면용 표시이고 계산에는 쓰지 않는다.
- 원가 초과는 `t / months` 만큼 반영 (인도 시점에 전부).

### scenario-table 행에 `margin_mean_now` 추가
`GET /api/bids/{id}/scenario-table` 각 행에 인도 시점 기대 마진(`margin_mean_now`)을 추가했다.

### /api/chat 해석 규칙 확장
- 환율: `달러`, `달러 값/가치`, `원화`(원화 강세 = 환율 하락으로 부호 반대), `강세/약세`, `절상/절하`
- 숫자 없이 방향만 말하면 % 조건은 5%, 납기 지연은 3개월로 가정하고 `notes` 로 알린다.
- 납기: `개월` 외에 `달`, `년` 단위도 읽는다.

---
## v0.3 추가 (MVP4 · 과거 이력)

### GET /api/history (변경)
응답에 엑셀 업로드분이 뒤에 붙는다. 업로드 행은 `origin: "upload"`, `id: "UP-0001"` 형식, 같은 필드. `uploaded` = 업로드 건수.
`margin` 은 모든 행에서 **추정값**이다 (실제 건도 인도 전 입찰 시점 예상치). 화면 표기는 "추정 마진".

### POST /api/history/upload?save=false|true&name=파일명
요청 본문에 `.xlsx` 파일 그대로 (5MB 이하). `save=false` 는 미리보기만, `true` 는 저장 (오류 줄이 있으면 422).
첫 줄 열 이름: 입찰일·조선소·견적($M)·시장가($M)·결과(낙찰/실주) 필수 / 선주·척수·실주 사유(가격·납기·사양·금융·기타)·마진(%)·메모 선택.
응답: `rows[]`(줄 번호 `line`, 값, `errors[]`, `duplicate`), `file_errors[]`, `error_rows`, `new_rows`, `skipped`, `saved`.
중복: 입찰일·조선소·선주·견적·시장가·결과가 모두 같으면 같은 기록으로 보고 저장하지 않는다 (이미 저장된 기록 / 파일 안에서 겹치는 줄).
저장: SQLite `data/history.db` (git 에 올리지 않음, `dataset.json` 은 수정하지 않음). 테스트는 `BALLAST_HISTORY_DB=다른경로.db`.

### GET /api/history/stats → 미구현 (팀 합의 대기)
위 MVP3·4 표의 명세는 그대로 둔다. 현재 낙찰률·실주 사유·견적 수준별 낙찰률은 화면(HistoryPage.jsx)이 `/api/history` 행으로 계산한다.
구현하게 되면 계산을 서버 한 곳으로 옮기고 화면은 그 값을 쓴다 (두 곳에서 따로 계산해 숫자가 어긋나지 않도록).

---
## v0.3 추가 (MVP3 · 공급사 평가)

### 공급사 평가 서버 API (구현됨)
필드·단위·점수는 `SuppliersPage.jsx` 기준. 점수 계산은 `supplier/supplier_score.py`에서 하고, 화면의 `score()`는 서버가 꺼졌을 때 예시 표시용으로만 쓴다. 규칙을 바꾸면 두 곳을 같이 고친다.
데이터는 서버 메모리에 저장하며, 재시작하면 `supplier/sample_suppliers.json`(가상 공급사 10곳)으로 초기화된다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/suppliers` | 목록 (점수 높은 순) |
| POST | `/api/suppliers` | 등록 (id는 서버가 부여) |
| GET | `/api/suppliers/{id}` | 조회 |
| PUT | `/api/suppliers/{id}` | 수정 |
| DELETE | `/api/suppliers/{id}` | 삭제 |
| GET | `/api/suppliers/{id}/score` | 점수만 |
| POST | `/api/suppliers/score-preview` | 저장 없이 점수만 계산 |

입력: `{ name, item, debt, opm, cur, rep, memo, years, amount }`
- `debt` 부채비율·`opm` 영업이익률·`cur` 유동비율은 %, `rep`는 A~D, `years`는 년, `amount`는 억원

응답: 입력 필드 + `id`, `sample`, `sc: { fin, rep, trust, total }`, `label`(양호/보통/주의)
- 점수 = 재무 40 + 업계 평판 30 + 거래 신뢰 30
- 오류: 없는 id 404, 범위 밖 값 422
