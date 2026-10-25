"""
공급사 평가 API (MVP3, E 담당)

필드·단위·점수는 frontend/src/pages/SuppliersPage.jsx 에 맞춘다.
점수 계산은 supplier/supplier_score.py 한 곳에서만 한다.
데이터는 서버 메모리에 저장한다. 서버를 재시작하면 supplier/sample_suppliers.json 으로 초기화된다.
"""
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]          # 레포 루트
sys.path.insert(0, str(ROOT / "supplier"))
from supplier_score import score, label, load_suppliers  # noqa: E402

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


class SupplierIn(BaseModel):
    """등록·수정 입력. 화면의 폼 항목과 같다."""
    name: str = Field(..., min_length=1, examples=["○○철강"])
    item: str = Field("", description="공급 품목", examples=["후판"])
    debt: float = Field(..., ge=0, description="부채비율 (%)", examples=[150])
    opm: float = Field(..., ge=-100, le=100, description="영업이익률 (%)", examples=[5.5])
    cur: float = Field(..., ge=0, description="유동비율 (%)", examples=[130])
    rep: Literal["A", "B", "C", "D"] = Field("B", description="업계 평판 등급")
    memo: str = Field("", description="평판 근거, 특이사항")
    years: float = Field(..., ge=0, description="거래 기간 (년)", examples=[6])
    amount: float = Field(..., ge=0, description="누적 거래액 (억원)", examples=[300])


_store = {s["id"]: s for s in load_suppliers(ROOT / "supplier" / "sample_suppliers.json")}
_next = len(_store) + 1


def _out(s: dict) -> dict:
    """화면이 쓰는 형식: 공급사 필드 + sc(fin, rep, trust, total) + label."""
    sc = score(s)
    return {**s, "sc": sc, "label": label(sc["total"])}


def _get(supplier_id: str) -> dict:
    if supplier_id not in _store:
        raise HTTPException(404, f"공급사 {supplier_id} 를 찾을 수 없습니다")
    return _store[supplier_id]


@router.get("")
def list_suppliers():
    """공급사 목록, 점수 높은 순."""
    return sorted((_out(s) for s in _store.values()), key=lambda x: x["sc"]["total"], reverse=True)


@router.post("/score-preview")
def score_preview(s: SupplierIn):
    """저장하지 않고 점수만 계산."""
    sc = score(s.model_dump())
    return {"sc": sc, "label": label(sc["total"])}


@router.get("/{supplier_id}")
def get_supplier(supplier_id: str):
    return _out(_get(supplier_id))


@router.get("/{supplier_id}/score")
def get_score(supplier_id: str):
    sc = score(_get(supplier_id))
    return {"id": supplier_id, "sc": sc, "label": label(sc["total"])}


@router.post("", status_code=201)
def create_supplier(s: SupplierIn):
    global _next
    new_id = f"s{_next}"
    _next += 1
    _store[new_id] = {"id": new_id, "sample": False, **s.model_dump()}
    return _out(_store[new_id])


@router.put("/{supplier_id}")
def update_supplier(supplier_id: str, s: SupplierIn):
    old = _get(supplier_id)
    _store[supplier_id] = {"id": supplier_id, "sample": old.get("sample", False), **s.model_dump()}
    return _out(_store[supplier_id])


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: str):
    _get(supplier_id)
    del _store[supplier_id]