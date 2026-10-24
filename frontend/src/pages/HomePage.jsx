import { api } from '../api.js'
import { useBid } from '../context.js'
import { useAsync } from '../hooks.js'
import { usd, pct, krw } from '../format.js'
import BidBar from '../components/BidBar.jsx'
import StatStrip from '../components/Stat.jsx'
import Figure from '../components/Figure.jsx'
import Conclusions from '../components/Conclusions.jsx'
import { EvChart, MarginBandChart, LossChart } from '../components/charts.jsx'

// MVP1 · 환율 기반 견적 리스크 (달러 견적 기준)
export default function HomePage() {
  const { bidId, health } = useBid()
  const { data, error, loading } = useAsync(() => (bidId ? api.curve(bidId) : Promise.resolve(null)), [bidId])

  return (
    <>
      <div className="page-head">
        <h1>환율 기반 견적 리스크</h1>
        <p>견적가(USD)를 바꿔가며 낙찰확률, 기대가치, 인도 시점의 환율 손실 위험을 함께 봅니다.</p>
      </div>
      <div className="stack">
      <BidBar />
      {error && <p className="msg err">불러오지 못했습니다: {error}</p>}
      {loading && !data && <p className="msg">계산 중…</p>}
      {data && (() => {
        const s = data.summary
        return (
          <>
            <StatStrip items={[
              { k: '제안가 기준 낙찰확률', v: pct(s.p_now, 0), meter: s.p_now, s: '이 견적가로 낙찰될 확률' },
              { k: '기대가치 (척당)', v: `${s.ev_now.toFixed(1)} $M`, s: '낙찰확률 × (견적가 − 손익분기)' },
              { k: '환율·원가 손실 확률', v: pct(s.loss_prob_now, 0), s: `인도 시점(${s.months}개월 후) 마진이 0% 미만일 확률` },
              { k: '권장 견적가', v: s.recommended != null ? usd(s.recommended) : '없음', tone: 'accent', s: s.band_lo != null ? `권장 구간 ${usd(s.band_lo)} ~ ${usd(s.band_hi)}` : '기대가치가 0 이하' },
            ]} />

            <Figure title="견적가별 기대가치" unit="$M / 척 · 가로축: 시장 기준가 대비 견적"
              note="파란 띠가 권장 구간(기대가치가 최고점의 85% 이상), 빗금은 손익분기 선가 아래입니다. 권장가는 구간의 하한입니다.">
              <EvChart data={data} />
            </Figure>

            <div className="two">
              <Figure title="인도 시점 마진 범위" unit="%" note="환율 변동 시뮬레이션의 10~90% 범위(주황 면)와 중앙값(선). 0% 아래 빗금이 적자입니다.">
                <MarginBandChart data={data} />
              </Figure>
              <Figure title="견적가별 환율·원가 손실 확률" unit="%" note="견적을 높게 부를수록 환율이 나빠져도 적자를 피할 여유가 커집니다.">
                <LossChart data={data} />
              </Figure>
            </div>

            <Conclusions data={data} />
            <p className="card-note">
              {health?.source === 'mock'
                ? '낙찰확률 모델이 아직 연결되지 않아 낙찰확률은 예시 계산입니다. 손익분기와 환율 위험은 실제 계산입니다.'
                : '낙찰확률은 합성 시나리오로 학습한 모델이며 독립된 입찰 상황이 8개뿐입니다. 절대값보다 곡선의 모양과 조건 간 차이로 읽으세요.'}
            </p>
          </>
        )
      })()}
      </div>
    </>
  )
}
