"""FastAPI 앱.  실행(저장소 최상위에서):  uvicorn backend.main:app --reload --port 8000
API 명세는 docs/api-spec.md. 자동 문서: http://localhost:8000/docs
"""
from __future__ import annotations
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import Backend, PRESETS
from .chat import answer
from .margin_path import margin_path

app = FastAPI(title="견적 리스크 매니저 API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
be = Backend()


class ScenarioIn(BaseModel):
    comp_pct: float = Field(0.0, ge=-0.5, le=0.5, description="경쟁사 견적 변화 (-0.05 = 5% 싸게)")
    steel_pct: float = Field(0.0, ge=-0.5, le=1.0, description="후판가 변화")
    fx_pct: float = Field(0.0, ge=-0.5, le=0.5, description="환율 변화 (입찰 시점 대비)")
    fx_krw: Optional[float] = Field(None, gt=0, description="환율을 원 단위로 직접 지정 (fx_pct 보다 우선)")
    delay_months: int = Field(0, ge=0, le=36, description="납기 지연 개월 수")
    quote_pct: float = Field(0.0, ge=-0.3, le=0.3, description="우리 견적가 변화 (-0.03 = 3% 낮춤)")


class ChatIn(BaseModel):
    bid_id: str
    message: str = Field(..., max_length=300)
    params: ScenarioIn = ScenarioIn()


class CompareIn(BaseModel):
    bid_id: str
    scenario: ScenarioIn = ScenarioIn()


def _check(bid_id: str):
    if bid_id not in set(b["id"] for b in be.bids()):
        raise HTTPException(404, f"입찰 {bid_id} 를 찾을 수 없습니다")


@app.get("/api/health")
def health():
    return {"status": "ok", "source": be.source, "reason": be.reason}


@app.get("/api/bids")
def bids():
    return be.bids()


@app.get("/api/bids/{bid_id}/curve")
def curve(bid_id: str, comp_pct: float = Query(0.0, ge=-0.5, le=0.5), steel_pct: float = Query(0.0, ge=-0.5, le=1.0),
          fx_pct: float = Query(0.0, ge=-0.5, le=0.5), fx_krw: Optional[float] = Query(None, gt=0),
          delay_months: int = Query(0, ge=0, le=36), quote_pct: float = Query(0.0, ge=-0.3, le=0.3)):
    _check(bid_id)
    return be.curve(bid_id, dict(comp_pct=comp_pct, steel_pct=steel_pct, fx_pct=fx_pct, fx_krw=fx_krw,
                                 delay_months=delay_months, quote_pct=quote_pct))


@app.post("/api/scenario/compare")
def compare(body: CompareIn):
    _check(body.bid_id)
    return be.compare(body.bid_id, body.scenario.model_dump())


@app.post("/api/scenario/margin-path")
def scenario_margin_path(body: CompareIn):
    """MVP2 · 계약~인도 달마다 마진 범위(10·50·90%)와 적자 확률. 기준 vs 시나리오. 계산은 backend/margin_path.py"""
    _check(body.bid_id)
    return margin_path(be, body.bid_id, body.scenario.model_dump())


@app.get("/api/bids/{bid_id}/scenario-table")
def scenario_table(bid_id: str):
    _check(bid_id)
    return be.scenario_table(bid_id)


@app.get("/api/scenarios/presets")
def presets():
    return PRESETS


@app.get("/api/fx/latest")
def fx_latest():
    return be.fx_latest()


@app.post("/api/chat")
def chat(body: ChatIn):
    """질문형 시나리오: 한국어 문장 → 조건(JSON) → 계산 → 답변. 규칙 기반 해석이라 외부 API 가 필요 없다."""
    _check(body.bid_id)
    return answer(be, body.bid_id, body.message, body.params.model_dump())


from .routers import history             # MVP4 과거 이력: dataset.json + 엑셀 업로드분(SQLite)
history.be = be
app.include_router(history.router)
