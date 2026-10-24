"""
공급사 평가 점수화 (MVP3, E 담당)

공급사 정보를 넣으면 항목별 점수(0~100)와 총점, 등급을 계산한다.
기준값과 가중치는 팀 논의 후 아래 상수만 고치면 된다.

실행 (레포 루트에서):
    python supplier/supplier_score.py
"""
import json
from pathlib import Path

# 항목별 가중치 (합계 1.0)
WEIGHTS = {
    "financial": 0.4,   # 재무제표
    "industry": 0.2,    # 업계 평가
    "trade_years": 0.2, # 거래 기간
    "trade_amount": 0.2 # 거래액
}

# 등급 기준 (총점 이상이면 해당 등급)
GRADES = [(80, "A"), (65, "B"), (50, "C"), (0, "D")]


def scale(value, worst, best):
    """value를 worst(0점)~best(100점) 사이로 선형 변환. 범위 밖은 0 또는 100."""
    ratio = (value - worst) / (best - worst)
    return round(max(0.0, min(1.0, ratio)) * 100, 1)


def financial_score(s):
    """재무 점수: 부채비율(낮을수록 좋음), 영업이익률, 유동비율 평균."""
    debt = scale(s["debt_ratio"], worst=3.0, best=0.5)         # 300% → 0점, 50% → 100점
    margin = scale(s["operating_margin"], worst=-0.05, best=0.15)
    liquidity = scale(s["current_ratio"], worst=0.5, best=2.0)
    return round((debt + margin + liquidity) / 3, 1)


def score_supplier(s):
    """공급사 1곳의 항목별 점수, 총점, 등급을 반환."""
    scores = {
        "financial": financial_score(s),
        "industry": float(s["industry_score"]),                    # 이미 0~100으로 입력
        "trade_years": scale(s["trade_years"], worst=0, best=10),  # 10년 이상이면 만점
        "trade_amount": scale(s["trade_amount_usd_mn"], worst=0, best=50),
    }
    total = round(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 1)
    grade = next(g for cut, g in GRADES if total >= cut)
    return {
        "supplier_id": s["supplier_id"],
        "name": s["name"],
        "scores": scores,
        "total_score": total,
        "grade": grade,
    }


def load_suppliers(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    path = Path(__file__).parent / "sample_suppliers.json"
    for s in load_suppliers(path):
        r = score_supplier(s)
        print(f'{r["supplier_id"]} {r["name"]:<10} 총점 {r["total_score"]:>5}  등급 {r["grade"]}  {r["scores"]}')
