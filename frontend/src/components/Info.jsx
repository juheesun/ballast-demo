// ⓘ 아이콘: 마우스를 올리거나 눌러서(탭 포커스) '이게 왜 필요한지' 한 줄을 본다.
export function Info({ text }) {
  return (
    <span className="info" tabIndex={0} aria-label={text}>
      ⓘ<span className="info-tip" role="tooltip">{text}</span>
    </span>
  )
}

// 그래프 범례: 요소마다 표시 · 이름 · ⓘ. items: [{ kind: line|dash|band|hatch|dot|vline, color, label, why }]
export function Legend({ items }) {
  return (
    <div className="legend">
      {items.map((it) => (
        <span className="lg" key={it.label}>
          <i className={`sw ${it.kind}`} style={{ '--c': it.color }} />
          {it.label}
          {it.why && <Info text={it.why} />}
        </span>
      ))}
    </div>
  )
}
