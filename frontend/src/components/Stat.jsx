// 핵심 수치 카드. items: [{ k, v, s, from, delta, tone, meter(0~1) }]
export default function StatStrip({ items, cols }) {
  return (
    <div className="stats" style={cols ? { gridTemplateColumns: `repeat(${cols}, 1fr)` } : undefined}>
      {items.map((it) => (
        <div className="card stat" key={it.k}>
          <div className="k">{it.k}</div>
          {it.from && <div className="from">기준 {it.from}</div>}
          <div className={`v ${it.tone || ''}`}>{it.v}</div>
          {it.meter != null && <div className="meter"><i style={{ width: `${Math.max(0, Math.min(1, it.meter)) * 100}%` }} /></div>}
          <div className="s">{it.delta && <span className={`delta ${it.delta.neg ? 'neg' : 'pos'}`}>{it.delta.text}</span>}{it.s}</div>
        </div>
      ))}
    </div>
  )
}
