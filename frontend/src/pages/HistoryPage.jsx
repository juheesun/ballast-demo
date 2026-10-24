import { useMemo, useState } from 'react'
import { api } from '../api.js'
import { useAsync } from '../hooks.js'
import { pct, signed } from '../format.js'
import StatStrip from '../components/Stat.jsx'

// MVP4 · 과거 이력. data/dataset.json 의 입찰 결과(낙찰/실주)를 조회·필터하고 낙찰률을 본다.
const BINS = [
  { k: '시장가 -5% 미만', f: (r) => r < 0.95 }, { k: '-5% ~ 0%', f: (r) => r >= 0.95 && r < 1 },
  { k: '0% ~ +3%', f: (r) => r >= 1 && r < 1.03 }, { k: '+3% ~ +6%', f: (r) => r >= 1.03 && r < 1.06 },
  { k: '+6% ~ +10%', f: (r) => r >= 1.06 && r < 1.1 }, { k: '+10% 이상', f: (r) => r >= 1.1 },
]
const PAGE = 14
const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null)

function Seg({ value, onChange, options }) {
  return <div className="seg">{options.map(([v, l]) => <button key={v} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>)}</div>
}

export default function HistoryPage() {
  const { data, error, loading } = useAsync(() => api.history(), [])
  const [res, setRes] = useState('all')
  const [origin, setOrigin] = useState('all')
  const [yard, setYard] = useState('')
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(PAGE)

  const all = data?.rows || []
  const yards = useMemo(() => [...new Set(all.map((r) => r.shipyard))].sort(), [all])
  const reasons = useMemo(() => [...new Set(all.map((r) => r.loss_reason).filter(Boolean))], [all])
  const rows = useMemo(() => all.filter((r) =>
    (res === 'all' || (res === 'won') === r.won) && (origin === 'all' || r.origin === origin) && (!yard || r.shipyard === yard) && (!reason || r.loss_reason === reason)
  ), [all, res, origin, yard, reason])

  const won = rows.filter((r) => r.won), lost = rows.filter((r) => !r.won)
  const rate = rows.length ? won.length / rows.length : null
  const byBin = BINS.map((b) => { const g = rows.filter((r) => b.f(r.ratio)); return { ...b, n: g.length, w: g.filter((r) => r.won).length } })
  const byReason = reasons.map((k) => ({ k, n: lost.filter((r) => r.loss_reason === k).length })).filter((x) => x.n)
  const maxReason = Math.max(1, ...byReason.map((x) => x.n))
  const vs = (r) => signed((r - 1) * 100, 1, '%')

  return (
    <>
      <div className="page-head">
        <h1>과거 이력</h1>
        <p>지난 입찰의 낙찰·실주 결과를 조회하고, 견적 수준별 낙찰률과 실주 사유를 봅니다.</p>
      </div>
      {error && <p className="msg err">불러오지 못했습니다: {error}</p>}
      {loading && !data && <p className="msg">불러오는 중…</p>}
      {data && (
        <div className="stack">
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <Seg value={res} onChange={(v) => { setRes(v); setOpen(PAGE) }} options={[['all', '전체'], ['won', '낙찰'], ['lost', '실주']]} />
            <Seg value={origin} onChange={(v) => { setOrigin(v); setOpen(PAGE) }} options={[['all', '실제 + 시나리오'], ['real', '실제 건만'], ['scenario', '시나리오만']]} />
            <select className="btn" value={yard} onChange={(e) => { setYard(e.target.value); setOpen(PAGE) }}><option value="">조선소 전체</option>{yards.map((y) => <option key={y}>{y}</option>)}</select>
            <select className="btn" value={reason} onChange={(e) => { setReason(e.target.value); setOpen(PAGE) }}><option value="">실주 사유 전체</option>{reasons.map((y) => <option key={y}>{y}</option>)}</select>
          </div>

          <StatStrip items={[
            { k: '조회된 입찰', v: `${rows.length}건`, s: `낙찰 ${won.length} · 실주 ${lost.length}` },
            { k: '낙찰률', v: pct(rate, 0), meter: rate ?? 0, s: origin === 'real' ? '실제 공개 입찰 기준' : '시나리오 포함 · 실제 수주율이 아님' },
            { k: '낙찰 건 평균 견적', v: won.length ? vs(avg(won.map((r) => r.ratio))) : '–', s: '시장 기준가 대비' },
            { k: '실주 건 평균 견적', v: lost.length ? vs(avg(lost.map((r) => r.ratio))) : '–', s: '시장 기준가 대비' },
          ]} />

          <div className="two">
            <section className="card card-pad">
              <h2 className="card-title">견적 수준별 낙찰률<span className="unit">시장 기준가 대비</span></h2>
              <div className="bars" style={{ marginTop: 10 }}>
                {byBin.map((b) => (
                  <div className="bar-row" key={b.k}><span>{b.k}</span><div className="track"><i style={{ width: `${b.n ? (b.w / b.n) * 100 : 0}%` }} /></div><span className="val">{b.n ? `${Math.round((b.w / b.n) * 100)}% (${b.w}/${b.n})` : '–'}</span></div>
                ))}
              </div>
            </section>
            <section className="card card-pad">
              <h2 className="card-title">실주 사유<span className="unit">건수</span></h2>
              <div className="bars" style={{ marginTop: 10 }}>
                {byReason.length === 0 && <p className="empty">실주 건이 없습니다.</p>}
                {byReason.map((x) => (
                  <div className="bar-row" key={x.k}><span>{x.k}</span><div className="track"><i className="lose" style={{ width: `${(x.n / maxReason) * 100}%` }} /></div><span className="val">{x.n}건</span></div>
                ))}
              </div>
            </section>
          </div>

          <section className="card card-pad">
            <h2 className="card-title">입찰 목록<span className="unit">{rows.length}건</span></h2>
            <table className="data">
              <thead><tr><th>입찰</th><th className="l">입찰일</th><th className="l">조선소</th><th>견적</th><th>시장가 대비</th><th>결과</th><th className="l">실주 사유</th><th>실제 마진</th></tr></thead>
              <tbody>
                {rows.slice(0, open).map((r) => (
                  <tr key={r.id} title={r.note || r.source}>
                    <td>{r.id} {r.origin === 'scenario' && <span className="tagc sim">시나리오</span>}</td>
                    <td className="l">{r.date}</td><td className="l">{r.shipyard}</td><td>${r.quote.toFixed(1)}M</td><td>{vs(r.ratio)}</td>
                    <td><span className={`tagc ${r.won ? 'win' : 'lose'}`}>{r.won ? '낙찰' : '실주'}</span></td>
                    <td className="l">{r.loss_reason || '–'}</td><td className={r.margin < 0 ? 'neg' : ''}>{r.margin == null ? '–' : pct(r.margin, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <p className="empty">조건에 맞는 입찰이 없습니다.</p>}
            {rows.length > open && <div className="toolbar" style={{ marginTop: 12, marginBottom: 0, justifyContent: 'center' }}><button className="btn" onClick={() => setOpen(open + PAGE)}>더 보기 ({rows.length - open}건)</button></div>}
            <p className="card-note">실제 공개 입찰 10건은 모두 낙찰입니다. 실주 사례는 팀이 만든 시나리오 변형이라 "시나리오" 표시가 붙으며, 낙찰률을 실제 수주 성과로 읽으면 안 됩니다. 마진은 낙찰 건의 실제값, 실주 건은 "땄다면"의 값입니다.</p>
          </section>
        </div>
      )}
    </>
  )
}
