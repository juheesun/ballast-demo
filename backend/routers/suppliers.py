"""
공급사 평가 API (MVP3, E 담당)

점수 계산은 supplier/supplier_score.py를 그대로 사용한다.
데이터는 서버 시작 시 supplier/sample_suppliers.json을 읽어 메모리에 둔다.
(서버를 껐다 켜면 등록·수정한 내용은 초기화됨. DB 연결은 팀과 정한 뒤 교체)
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]          # 레포 루트 (C:\Ballast)
sys.path.insert(0, str(ROOT / "supplier"))
from supplier_score import score_supplier, load_suppliers, WEIGHTS  # noqa: E402

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


class SupplierIn(BaseModel):
    """공급사 입력 형식. 범위를 벗어난 값은 FastAPI가 자동으로 막는다."""
    name: str = Field(..., examples=["한빛엔진"])
    category: str = Field(..., examples=["엔진"])
    debt_ratio: float = Field(..., ge=0, description="부채비율 (0.8 = 80%)")
    operating_margin: float = Field(..., ge=-1, le=1, description="영업이익률 (0.09 = 9%)")
    current_ratio: float = Field(..., ge=0, description="유동비율 (1.6 = 160%)")
    industry_score: float = Field(..., ge=0, le=100, description="업계 평가 0~100")
    trade_years: float = Field(..., ge=0, description="거래 기간(년)")
    trade_amount_usd_mn: float = Field(..., ge=0, description="누적 거래액 ($mn)")


class SupplierCreate(SupplierIn):
    supplier_id: str = Field(..., examples=["SUP-0011"])


# 메모리 저장소: {supplier_id: 공급사 정보}
_store = {s["supplier_id"]: s for s in load_suppliers(ROOT / "supplier" / "sample_suppliers.json")}


def _with_score(s: dict) -> dict:
    """공급사 정보에 점수 결과(scores, total_score, grade)를 붙여서 반환."""
    r = score_supplier(s)
    return {**s, "scores": r["scores"], "total_score": r["total_score"], "grade": r["grade"]}


@router.get("")
def list_suppliers(grade: str | None = None, sort: str = "total_score"):
    """공급사 목록. ?grade=A 로 등급 필터, 기본은 총점 높은 순."""
    items = [_with_score(s) for s in _store.values()]
    if grade:
        items = [x for x in items if x["grade"] == grade.upper()]
    if sort == "total_score":
        items.sort(key=lambda x: x["total_score"], reverse=True)
    return items


@router.post("/score-preview")
def score_preview(s: SupplierIn):
    """저장하지 않고 점수만 미리 계산 (입력 폼에서 실시간 미리보기용)."""
    r = score_supplier({**s.model_dump(), "supplier_id": "PREVIEW"})
    return {"scores": r["scores"], "total_score": r["total_score"], "grade": r["grade"]}


@router.get("/{supplier_id}")
def get_supplier(supplier_id: str):
    if supplier_id not in _store:
        raise HTTPException(404, f"{supplier_id} 공급사가 없습니다")
    return _with_score(_store[supplier_id])


@router.get("/{supplier_id}/score")
def get_supplier_score(supplier_id: str):
    """평가 점수만 반환 (api-spec.md 의 MVP3 초안 경로)."""
    if supplier_id not in _store:
        raise HTTPException(404, f"{supplier_id} 공급사가 없습니다")
    r = score_supplier(_store[supplier_id])
    return {"supplier_id": supplier_id, "scores": r["scores"],
            "total_score": r["total_score"], "grade": r["grade"], "weights": WEIGHTS}


@router.post("", status_code=201)
def create_supplier(s: SupplierCreate):
    if s.supplier_id in _store:
        raise HTTPException(409, f"{s.supplier_id}는 이미 등록되어 있습니다")
    _store[s.supplier_id] = s.model_dump()
    return _with_score(_store[s.supplier_id])


@router.put("/{supplier_id}")
def update_supplier(supplier_id: str, s: SupplierIn):
    if supplier_id not in _store:
        raise HTTPException(404, f"{supplier_id} 공급사가 없습니다")
    _store[supplier_id] = {**s.model_dump(), "supplier_id": supplier_id}
    return _with_score(_store[supplier_id])