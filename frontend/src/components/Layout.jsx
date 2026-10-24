import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { BidContext } from '../context.js'
import { HatchDefs } from './charts.jsx'

const BRAND = '견적 리스크 매니저'
const MENU = [
  { to: '/', label: '환율 견적리스크' },
  { to: '/scenario', label: '시나리오' },
  { to: '/suppliers', label: '공급사 평가' },
  { to: '/history', label: '과거 이력' },
]

export default function Layout() {
  const [bids, setBids] = useState([])
  const [health, setHealth] = useState(null)
  const [fx, setFx] = useState(null)
  const [error, setError] = useState(null)
  const [params, setParams] = useSearchParams()

  useEffect(() => {
    Promise.all([api.bids(), api.health(), api.fx()])
      .then(([b, h, f]) => { setBids(b); setHealth(h); setFx(f) })
      .catch((e) => setError(e.message))
  }, [])

  const bidId = params.get('bid') || bids[0]?.id || null
  const bid = useMemo(() => bids.find((b) => b.id === bidId) || null, [bids, bidId])
  const setBidId = (id) => setParams({ bid: id }, { replace: true })
  const search = bidId ? `?bid=${bidId}` : ''

  return (
    <BidContext.Provider value={{ bids, bid, bidId, setBidId, health }}>
      <HatchDefs />
      <header className="topbar">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 17h18l-2 3H5z" /><path d="M6 17l1-5h10l1 5" /><path d="M12 12V5l4 3" />
          </svg>
          {BRAND}
        </div>
        <nav className="nav">
          {MENU.map((m) => (
            <NavLink key={m.to} to={{ pathname: m.to, search }} end={m.to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              {m.label}
            </NavLink>
          ))}
        </nav>
        {fx && (
          <div className="ticker num">
            USD/KRW <b>{fx.usd_krw.toLocaleString('ko-KR', { minimumFractionDigits: 1 })}</b>
            {fx.change !== 0 && <span className="chg">{fx.change > 0 ? '▲' : '▼'} {Math.abs(fx.change).toFixed(1)}</span>}
            <span className="note">{fx.year_month}{fx.carried_over ? ' · 전월 값 이월' : ''}</span>
          </div>
        )}
      </header>
      <main className="page">
        {error ? (
          <p className="msg err">백엔드에 연결하지 못했습니다 ({error}). 터미널에서 <code>uvicorn backend.main:app --port 8000</code> 이 켜져 있는지 확인하세요.</p>
        ) : (
          <Outlet />
        )}
      </main>
    </BidContext.Provider>
  )
}
