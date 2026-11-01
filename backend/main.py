"""FastAPI 앱.  실행(저장소 최상위에서):  uvicorn backend.main:app --reload --port 8000
API 명세는 docs/api-spec.md. 자동 문서: http://localhost:8000/docs
"""
from __future__ import annotations
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import Backend, PRESETS
from .chat import answer, advice
from .margin_path import margin_path, hedge
from .quote_risk import evaluate as quote_risk, ship_info

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


class CostItemIn(BaseModel):
    key: str
    label: Optional[str] = None
    share: float = Field(..., ge=0, le=1, description="원가 중 이 항목의 비중")
    usd_share: float = Field(0.0, ge=0, le=1, description="이 항목 안에서 달러로 사는 비중")


class MilestoneIn(BaseModel):
    key: str
    label: Optional[str] = None
    at: float = Field(..., ge=0, le=1, description="받는 시점 (납기 대비, 0 = 계약, 1 = 인도)")
    weight: float = Field(..., ge=0, le=1, description="대금 중 이 시점에 받는 비율")


class RiskIn(BaseModel):
    """견적 리스크 화면의 가정. 비워 두면 선종·규모별 기본값 (backend/quote_risk.py)"""
    costs: Optional[List[CostItemIn]] = None
    milestones: Optional[List[MilestoneIn]] = None
    hedge: float = Field(0.0, ge=0, le=1, description="받을 달러 중 선물환으로 고정하는 비율")
    loss_target: float = Field(0.10, gt=0, lt=1, description="안전 시작 견적가 기준 적자확률")


def _check(bid_id: str):
    if bid_id not in set(b["id"] for b in be.bids()):
        raise HTTPException(404, f"입찰 {bid_id} 를 찾을 수 없습니다")
    try:
        be.eng.row(bid_id)
    except KeyError:                                   # 목록에는 있지만 낙찰확률 모델 표에 없는 입찰 (예: REAL-07, 08)
        raise HTTPException(422, f"{bid_id} 는 낙찰확률 모델 데이터에 없어 계산할 수 없어요. 다른 입찰을 골라 주세요.")


@app.get("/api/health")
def health():
    return {"status": "ok", "source": be.source, "reason": be.reason}


@app.get("/api/bids")
def bids():
    out = []
    for b in be.bids():
        sh = ship_info(b["id"])
        out.append({**b, "ship_type": sh["type"], "size_teu": sh["size_teu"], "num_ships": sh["num_ships"]})
    return out


@app.post("/api/bids/{bid_id}/risk")
def risk(bid_id: str, body: RiskIn = RiskIn()):
    """MVP1 · 원가 통화 구분 · 대금 분할 · 환헤지를 반영한 적자확률, 원화 금액, 판단 도구, 과거 검증. 계산은 backend/quote_risk.py"""
    _check(bid_id)
    return quote_risk(be, bid_id, body.model_dump())


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


class HedgeIn(CompareIn):
    ratio: float = Field(0.0, ge=0, le=1, description="받을 달러 중 입찰 시점 환율로 고정하는 비율")


@app.post("/api/scenario/advice")
def scenario_advice(body: CompareIn):
    """MVP2 · 결론 박스(chat.verdict_parts) · 버틸 수 있는 환율 · 주의할 것과 할 일"""
    _check(body.bid_id)
    return advice(be, body.bid_id, body.scenario.model_dump())


@app.post("/api/scenario/hedge")
def scenario_hedge(body: HedgeIn):
    """MVP2 · 환헤지 비율별 적자확률·예상 마진·버틸 수 있는 환율. 계산은 backend/margin_path.py"""
    _check(body.bid_id)
    return hedge(be, body.bid_id, body.scenario.model_dump(), body.ratio)


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


@app.get("/api/history")
def history():
    return be.history()
