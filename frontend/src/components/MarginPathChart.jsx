import {
  ComposedChart, Area, Line, XAxis, YAxis, ReferenceArea, ReferenceLine, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'

// MVP2 · 계약부터 인도까지 마진 범위(10~90%)가 어떻게 벌어지는지. 데이터: POST /api/scenario/margin-path
// 주황 띠 = 바뀐 조건의 마진 범위, 주황 선 = 중앙값, 회색 점선 = 기준 조건의 중앙값. 0% 아래(빗금)는 적자.
const INK = '#0f1a2e', ACCENT = '#d9773f', BASE = '#8d97a8', MUTED = '#8190a5', RULE = '#e1e6ee'
const axis = { tick: { fontSize: 11.5, fill: MUTED }, axisLine: { stroke: RULE }, tickLine: { stroke: RULE } }
const pc = (v, d = 1) => (v == null ? '–' : `${v.toFixed(d)}%`)

function niceScale(min, max) {
  const step = [1, 2, 5, 10, 20, 50].find((st) => (max - min) / st <= 6) || 100
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step
  const ticks = []; for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(v)
  return { domain: [lo, hi], ticks }
}

// x 축 눈금: 공정 이름 + 개월
function MilestoneTick({ x, y, payload, labels }) {
  const name = labels[payload.value]
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={13} textAnchor="middle" fill={INK} fontSize={11.5} fontWeight={600}>{name}</text>
      <text dy={28} textAnchor="middle" fill={MUTED} fontSize={11}>{payload.value}개월</text>
    </g>
  )
}

function Tip({ active, payload, hasBase }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  return (
    <div style={{ background: '#fff', border: `1px solid ${RULE}`, borderRadius: 8, boxShadow: '0 4px 14px rgba(15,26,46,.12)', padding: '8px 12px', fontSize: 12.5, lineHeight: 1.6 }}>
      <div style={{ fontWeight: 600 }}>계약 후 {r.month}개월{r.label ? ` · ${r.label}` : ''}</div>
      {r.p50 != null && (
        <div style={{ color: '#4b5260' }}>마진 중앙 {pc(r.p50)} · 범위 {pc(r.p10)}~{pc(r.p90)} · 적자 확률 {pc(r.loss, 0)}</div>
      )}
      {hasBase && r.base_p50 != null && <div style={{ color: MUTED }}>기준 조건 중앙 {pc(r.base_p50)}</div>}
    </div>
  )
}

export default function MarginPathChart({ data, height = 320 }) {
  const { base, scenario: scen, milestones } = data
  const same = base.months === scen.months && base.points.every((p, i) => p.p50 === scen.points[i]?.p50)
  const last = Math.max(base.months, scen.months)
  const labels = Object.fromEntries(milestones.map((m) => [m.month, m.label]))
  const rows = []
  for (let t = 0; t <= last; t++) {
    const s = scen.points[t], b = base.points[t]
    rows.push({
      month: t, label: labels[t],
      band: s ? [s.p10 * 100, s.p90 * 100] : null, p10: s ? s.p10 * 100 : null, p50: s ? s.p50 * 100 : null, p90: s ? s.p90 * 100 : null,
      loss: s ? s.loss_prob * 100 : null, base_p50: b ? b.p50 * 100 : null,
    })
  }
  const ys = rows.flatMap((r) => [r.p10, r.p90, r.base_p50]).filter((v) => v != null)
  const y = niceScale(Math.min(...ys, 0), Math.max(...ys, 0))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 14, right: 18, bottom: 22, left: 0 }}>
        <CartesianGrid stroke="#eef1f6" vertical={false} />
        <XAxis type="number" dataKey="month" domain={[0, last]} ticks={milestones.map((m) => m.month)} interval={0}
          tick={<MilestoneTick labels={labels} />} axisLine={axis.axisLine} tickLine={axis.tickLine} />
        <YAxis width={48} domain={y.domain} ticks={y.ticks} {...axis} tickFormatter={(v) => `${v}%`} />
        {y.domain[0] < 0 && <ReferenceArea y1={y.domain[0]} y2={0} fill="url(#hatch-loss)" stroke="none" />}
        <Area dataKey="band" stroke="none" fill={ACCENT} fillOpacity={0.22} isAnimationActive={false} connectNulls={false} />
        <ReferenceLine y={0} stroke={INK} strokeWidth={1} />
        {milestones.slice(1, -1).map((m) => <ReferenceLine key={m.month} x={m.month} stroke={RULE} strokeDasharray="3 3" />)}
        {!same && <Line dataKey="base_p50" stroke={BASE} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />}
        <Line dataKey="p50" stroke={ACCENT} strokeWidth={2.4} dot={false} isAnimationActive={false} />
        <Tooltip cursor={{ stroke: INK, strokeWidth: 0.8 }} content={<Tip hasBase={!same} />} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
