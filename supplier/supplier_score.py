"""
공급사 평가 점수 (MVP3, E 담당)

frontend/src/pages/SuppliersPage.jsx 의 score() 와 같은 규칙이다.
재무 40 + 업계 평판 30 + 거래 신뢰 30 = 100점.
규칙을 바꾸면 이 파일과 SuppliersPage.jsx 의 score() 를 같이 고친다.
(화면의 score() 는 서버가 꺼졌을 때 예시 데이터를 보여주는 용도로만 쓰인다)

실행 (레포 루트에서):
    python supplier/supplier_score.py
"""
import json
from pathlib import Path

GRADE = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25}   # 업계 평판 등급 → 비율


def clamp(v):
    return max(0.0, min(1.0, v))


def score(s):
    """공급사 1곳의 점수. 단위: debt·opm·cur 는 %, years 는 년, amount 는 억원."""
    fin = (clamp(1 - (s["debt"] - 100) / 300)      # 부채비율 100% 이하 만점, 400% 0점
           + clamp(s["opm"] / 10)                  # 영업이익률 10% 이상 만점
           + clamp((s["cur"] - 80) / 120)          # 유동비율 80% 0점, 200% 이상 만점
           ) / 3 * 40
    rep = GRADE.get(s["rep"], 0.5) * 30
    trust = clamp(s["years"] / 10) * 15 + clamp(s["amount"] / 500) * 15
    total = int(fin + rep + trust + 0.5)           # 화면의 Math.round 와 같게 반올림
    return {"fin": round(fin, 2), "rep": round(rep, 2), "trust": round(trust, 2), "total": total}


def label(total):
    """화면과 같은 구간: 75 이상 양호, 55 이상 보통, 그 아래 주의."""
    return "양호" if total >= 75 else "보통" if total >= 55 else "주의"


def load_suppliers(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    path = Path(__file__).parent / "sample_suppliers.json"
    for s in load_suppliers(path):
        sc = score(s)
        print(f'{s["id"]:<4} {s["name"]:<14} {sc["total"]:>3}점 {label(sc["total"])}  {sc}')