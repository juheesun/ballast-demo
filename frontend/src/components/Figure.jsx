// 그래프 카드: 제목 · 단위 · 주석
export default function Figure({ title, unit, note, children }) {
  return (
    <section className="card card-pad">
      <h2 className="card-title">{title}{unit && <span className="unit">{unit}</span>}</h2>
      {children}
      {note && <p className="card-note">{note}</p>}
    </section>
  )
}
