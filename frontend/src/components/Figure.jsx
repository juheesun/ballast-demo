import { Info } from './Info.jsx'

// 그래프 카드: 제목(ⓘ: 이 그래프가 왜 필요한지) · 단위 · 주석
export default function Figure({ title, unit, note, info, children }) {
  return (
    <section className="card card-pad">
      <h2 className="card-title">{title}{info && <Info text={info} />}{unit && <span className="unit">{unit}</span>}</h2>
      {children}
      {note && <p className="card-note">{note}</p>}
    </section>
  )
}
