import { useBid } from '../context.js'
import { usd, vsMarket, krw } from '../format.js'

// 분석 중인 입찰 정보를 한 줄로. 모든 분석 화면 맨 위에 쓴다.
export default function BidBar() {
  const { bids, bid, bidId, setBidId, health } = useBid()
  if (!bid) return null
  const Item = ({ k, children }) => <div className="item"><span className="k">{k}</span><span className="v">{children}</span></div>
  return (
    <div className="card bidbar">
      <div className="item">
        <span className="k">입찰</span>
        <select value={bidId} onChange={(e) => setBidId(e.target.value)}>
          {bids.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
      </div>
      <Item k="시장 기준가">{usd(bid.market_price)}</Item>
      <Item k="제안가">{usd(bid.quote_now)} <span style={{ fontWeight: 400, color: 'var(--ink-3)' }}>({vsMarket(bid.ratio_now)})</span></Item>
      <Item k="손익분기 선가">{usd(bid.bep)}</Item>
      <Item k="납기까지">{bid.lead_months}개월</Item>
      <Item k="입찰 시점 환율">{krw(bid.expected_fx)}</Item>
      {health?.source === 'mock' && <span className="badge warn">예시 데이터 · 낙찰확률 모델 연결 전</span>}
    </div>
  )
}
