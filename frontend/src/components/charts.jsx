import {
  ComposedChart, Area, Line, XAxis, YAxis, ReferenceArea, ReferenceLine, ReferenceDot, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { usd, signed, pct } from '../format.js'

const INK = '#0f1a2e', LINE = '#2f5fa8', ACCENT = '#d9773f', LOSS = '#c0392b', BASE = '#8d97a8', BAND = '#dbe6f5', MUTED = '#8190a5', RULE = '#e1e6ee'
const marketOf = (s) => s.quote_now / s.ratio_now
const toX = (ratio) => (ratio - 1) * 100                         // 시장 기준가 대비 %
const xOfQuote = (s, q) => (q / marketOf(s) - 1) * 100
const tickX = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}%`
const nearest = (rows, x) => rows.reduce((a, r) => (Math.abs(r.x - x) < Math.abs(a.x - x) ? r : a), rows[0])

// 빗금 패턴은 문서에 한 번만 정의한다 (Layout 에서 <HatchDefs /> 를 한 번 렌더). 차트는 fill="url(#hatch-loss)" 로 참조.
export function HatchDefs() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <defs>
        <pattern id="hatch-loss" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="7" stroke={LOSS} strokeWidth="1.1" strokeOpacity="0.5" />
        </pattern>
      </defs>
    </svg>
  )
}

// 눈금을 5·10·20 같은 깔끔한 간격으로
function niceScale(min, max) {
  const step = [1, 2, 5, 10, 20, 50].find((st) => (max - min) / st <= 6) || 100
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step
  const ticks = []; for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(v)
  return { domain: [lo, hi], ticks }
}

const axis = { tick: { fontSize: 11.5, fill: MUTED }, axisLine: { stroke: RULE }, tickLine: { stroke: RULE } }
const xDomain = (rows) => [Math.floor(rows[0].x), Math.ceil(rows.at(-1).x)]
const xTicks = (rows) => { const [a, b] = xDomain(rows); const t = []; for (let v = Math.ceil(a / 5) * 5; v <= b; v += 5) t.push(v); return t }

function Tip({ active, payload, extra }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  return (
    <div style={{ background: '#fff', border: `1px solid ${RULE}`, borderRadius: 8, boxShadow: '0 4px 14px rgba(15,26,46,.12)', padding: '8px 12px', fontSize: 12.5, lineHeight: 1.6 }}>
      <div style={{ fontWeight: 600 }}>{usd(r.quote)} <span style={{ fontWeight: 400, color: MUTED }}>시장가 대비 {signed(r.x, 1, '%')}</span></div>
      {extra(r)}
    </div>
  )
}

/** 견적가별 기대가치. base 를 주면 기준 조건을 회색 점선으로 겹쳐 그린다. */
export function EvChart({ data, base = null, height = 380 }) {
  const s = data.summary
  const rows = data.grid.map((g, i) => ({ x: toX(g.ratio), quote: g.quote, ev: g.ev, p: g.p, base_ev: base ? base.grid[i].ev : null }))
  const [x0, x1] = xDomain(rows)
  const bepX = toX(s.bep_ratio), nowX = toX(s.ratio_now)
  const recX = s.recommended != null ? xOfQuote(s, s.recommended) : null
  const rec = recX != null ? nearest(rows, recX) : null
  const recLeft = recX != null && recX < nowX
  const ys = rows.flatMap((r) => [r.ev, r.base_ev]).filter((v) => v != null)
  const yScale = niceScale(Math.min(...ys, 0), Math.max(...ys, 1))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 22, right: 18, bottom: 6, left: 0 }}>
        <CartesianGrid stroke="#eef1f6" vertical={false} />
        <XAxis type="number" dataKey="x" domain={[x0, x1]} ticks={xTicks(rows)} tickFormatter={tickX} {...axis} />
        <YAxis width={44} domain={yScale.domain} ticks={yScale.ticks} {...axis} tickFormatter={(v) => v.toFixed(0)} />
        {bepX > x0 && <ReferenceArea x1={x0} x2={Math.min(bepX, x1)} fill="url(#hatch-loss)" stroke="none" ifOverflow="hidden" />}
        {s.band_lo != null && <ReferenceArea x1={xOfQuote(s, s.band_lo)} x2={xOfQuote(s, s.band_hi)} fill={BAND} fillOpacity={0.75} stroke="none" />}
        <ReferenceLine y={0} stroke={INK} strokeWidth={1} />
        {bepX > x0 && <ReferenceLine x={bepX} stroke={LOSS} strokeDasharray="4 3" label={{ value: '손익분기', position: 'insideBottomLeft', fill: LOSS, fontSize: 11.5, dy: -6, dx: 4 }} />}
        <ReferenceLine x={nowX} stroke={INK} strokeWidth={1.4} label={{ value: '제안가', position: recLeft ? 'insideTopRight' : 'insideTopLeft', fill: INK, fontSize: 11.5, dy: -16 }} />
        {base && <Line dataKey="base_ev" stroke={BASE} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />}
        <Line dataKey="ev" stroke={LINE} strokeWidth={2.4} dot={false} isAnimationActive={false} />
        {rec && <ReferenceDot x={rec.x} y={rec.ev} r={5.5} fill={ACCENT} stroke="#fff" strokeWidth={1.5}
          label={{ value: `권장가 ${usd(s.recommended)}`, position: recLeft ? 'top' : 'top', fill: ACCENT, fontSize: 12, fontWeight: 600, dy: -4 }} />}
        <Tooltip cursor={{ stroke: INK, strokeWidth: 0.8 }} content={<Tip extra={(r) => (
          <div style={{ color: '#4b5260' }}>낙찰확률 {pct(r.p, 0)} · 기대가치 {r.ev.toFixed(2)}{base ? ` (기준 ${r.base_ev.toFixed(2)})` : ''}</div>
        )} />} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** 인도 시점 마진 범위(10~90%)와 중앙값. 0% 아래는 손실. */
export function MarginBandChart({ data, height = 300 }) {
  const s = data.summary
  const rows = data.grid.map((g) => ({ x: toX(g.ratio), quote: g.quote, band: [g.margin_p10 * 100, g.margin_p90 * 100], p50: g.margin_p50 * 100, p10: g.margin_p10 * 100, p90: g.margin_p90 * 100, loss: g.loss_prob }))
  const lo = Math.min(...rows.map((r) => r.p10)), hi = Math.max(...rows.map((r) => r.p90))
  const [x0, x1] = xDomain(rows)
  const yScale = niceScale(Math.min(lo, 0), Math.max(hi, 0))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 14, right: 14, bottom: 6, left: 0 }}>
        <CartesianGrid stroke="#eef1f6" vertical={false} />
        <XAxis type="number" dataKey="x" domain={[x0, x1]} ticks={xTicks(rows)} tickFormatter={tickX} {...axis} />
        <YAxis width={44} domain={yScale.domain} ticks={yScale.ticks} {...axis} tickFormatter={(v) => `${v}%`} />
        <ReferenceArea y1={yScale.domain[0]} y2={0} fill="url(#hatch-loss)" stroke="none" />
        <Area dataKey="band" stroke="none" fill={ACCENT} fillOpacity={0.22} isAnimationActive={false} />
        <ReferenceLine y={0} stroke={INK} />
        <ReferenceLine x={toX(s.ratio_now)} stroke={INK} strokeWidth={1.2} />
        <Line dataKey="p50" stroke={ACCENT} strokeWidth={2.2} dot={false} isAnimationActive={false} />
        <Tooltip cursor={{ stroke: INK, strokeWidth: 0.8 }} content={<Tip extra={(r) => (
          <div style={{ color: '#4b5260' }}>마진 중앙 {r.p50.toFixed(1)}% · 범위 {r.p10.toFixed(1)}~{r.p90.toFixed(1)}%</div>
        )} />} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** 견적가별 환율·원가 손실 확률 */
export function LossChart({ data, height = 300 }) {
  const s = data.summary
  const rows = data.grid.map((g) => ({ x: toX(g.ratio), quote: g.quote, loss: g.loss_prob * 100 }))
  const [x0, x1] = xDomain(rows)
  const top = Math.max(10, Math.ceil(Math.max(...rows.map((r) => r.loss)) / 10) * 10)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 14, right: 14, bottom: 6, left: 0 }}>
        <CartesianGrid stroke="#eef1f6" vertical={false} />
        <XAxis type="number" dataKey="x" domain={[x0, x1]} ticks={xTicks(rows)} tickFormatter={tickX} {...axis} />
        <YAxis width={44} domain={[0, top]} {...axis} tickFormatter={(v) => `${v}%`} />
        <Area dataKey="loss" stroke={LOSS} strokeWidth={2} fill={LOSS} fillOpacity={0.1} isAnimationActive={false} />
        <ReferenceLine x={toX(s.ratio_now)} stroke={INK} strokeWidth={1.2} label={{ value: `제안가 ${(s.loss_prob_now * 100).toFixed(0)}%`, position: 'insideTopRight', fill: INK, fontSize: 11.5, dy: 2 }} />
        <Tooltip cursor={{ stroke: INK, strokeWidth: 0.8 }} content={<Tip extra={(r) => <div style={{ color: '#4b5260' }}>손실 확률 {r.loss.toFixed(1)}%</div>} />} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
