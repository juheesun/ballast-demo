# 웹 화면 (FastAPI + React)

저장소 최상위에 `backend/`, `frontend/` 를 추가한다. `modeling/` 은 건드리지 않는다.

```
Ballast/
├─ data/  docs/  modeling/        (기존)
├─ backend/    FastAPI (modeling 의 B 코드를 불러다 씀)
├─ frontend/   React + Vite
└─ docs/api-spec.md
```

## 실행 (터미널 2개)
```bash
# 터미널 1 · 저장소 최상위에서
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --port 8000

# 터미널 2
cd frontend
npm install
npm run dev
```
브라우저에서 http://localhost:5173 · API 문서는 http://localhost:8000/docs

- A 의 모델(`modeling/features.py`, `win_model.py`, `models/win_logit.pkl`)이 없으면 자동으로 **예시 모드**로 뜨고 화면에 '예시 데이터'가 표시된다.
- 강제로 예시 모드: `BALLAST_MOCK=1 uvicorn backend.main:app --port 8000`

## 팀원이 일하는 곳
| 담당 | 파일 |
|---|---|
| MVP1 홈 | `frontend/src/pages/HomePage.jsx` |
| MVP2 시나리오 | `frontend/src/pages/ScenarioPage.jsx` (화면) · `backend/chat.py` (질문 해석 규칙) |
| MVP3 공급사 평가 | `frontend/src/pages/SuppliersPage.jsx` (지금은 브라우저 저장·임시 점수 규칙) → 서버 저장은 `backend/` 에 라우터 추가 |
| MVP4 과거 이력 | `frontend/src/pages/HistoryPage.jsx` + `GET /api/history` (dataset.json 기반) |
| 공통 (A) | `components/` (Layout, BidBar, Stat, Figure, charts), `styles.css`, `api.js`, `docs/api-spec.md` |

색·글자·간격은 `frontend/src/styles.css` 맨 위 토큰만 고치면 전체가 바뀐다.

## .gitignore 에 추가할 줄
```
node_modules/
frontend/dist/
```

파이썬 3.9 이상에서 동작한다 (맥 기본 3.9 확인 필요). 질문형 시나리오는 외부 API 없이 규칙으로 해석한다.
