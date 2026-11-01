import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useBid } from '../context.js'
import { useAsync } from '../hooks.js'
import { usd, pct, signed, vsMarket, krw } from '../format.js'
import BidBar from '../components/BidBar.jsx'
import Figure from '../components/Figure.jsx'
import { EvChart } from '../components/charts.jsx'
import MarginPathChart from '../components/MarginPathChart.jsx'

// MVP2 · 반사실 시나리오. 왼쪽: 질문(문장)이나 버튼으로 조건을 바꾼다 / 오른쪽: 결과가 기준 조건과 겹쳐 바뀐다.
const ZERO = { comp_pct: 0, steel_pct: 0, fx_pct: 0, fx_krw: null, delay_months: 0, quote_pct: 0 }
const KEYS = ['comp_pct', 'steel_pct', 'fx_pct', 'delay_months', 'quote_pct']
const same = (a, b) => KEYS.every((k) => Math.abs((a[k] || 0) - (b[k] || 0)) < 1e-9) && (a.fx_krw || null) === (b.fx_krw || null)
const dtext = (v, d, unit, bad = v < 0) => (v == null || Math.abs(v) < 0.5 * 10 ** -d ? null : { neg: bad, text: signed(v, d, unit) })
// 비교 표 첫 화면에서 뺄 행 (근거 보기에서는 전부 보인다)
const EVIDENCE_ONLY = new Set(['comp_m10', 'combo'])
const HEDGE_STEPS = [0, 0.2, 0.4, 0.5, 0.6, 0.8, 1]

// 버튼으로 바로 물어볼 수 있는 질문 (화면 문구 = 보내는 문장). 해석 규칙은 backend/chat.py
const SUGGEST = [
  '경쟁사 견적이 5% 낮아지면?',
  '환율이 1,300원까지 떨어지면?',
  '우리 견적가를 3% 낮추면?',
  '후판가가 10% 오르면?',
  '납기가 6개월 늦어지면?',
  '경쟁사 5% 낮고 후판가 10% 오르면?',
]


// 조건 하나씩 나빠질 때 기대가치가 얼마나 줄어드는지 보여 줄 4가지 (비교 표의 행 id)
const BAR_IDS = ['comp_m5', 'fx_m5', 'delay_3', 'steel_p10']
const BAR_SHORT = { comp_m5: '경쟁사', fx_m5: '환율', delay_3: '납기', steel_p10: '후판가' }
const BAR_LABEL = { comp_m5: '경쟁사 -5%', fx_m5: '환율 -5%', delay_3: '납기 3개월 지연', steel_p10: '후판가 +10%' }
const RISK_NAME = { 경쟁: '경쟁사 저가 입찰', 환율: '환율 하락', 비용: '후판가 상승', 납기: '납기 지연', 복합: '복합 조건' }

// 접어 두는 근거 한 줄. 펼칠 때만 안을 그린다(그래프가 닫힌 상태에서 크기를 못 재는 문제를 피한다)
function Fold({ title, hint, children }) {
  const [open, setOpen] = useState(false)
  return (
    <details className="fold" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary><span><b>{title}</b>{hint && <em>{hint}</em>}</span><i>{open ? '접기' : '펼치기'} ▾</i></summary>
      {open && <div className="fold-body">{children}</div>}
    </details>
  )
}

function VStat({ k, v, was, tone, sub }) {
  return (
    <div className={`vb-stat ${tone || ''}`}>
      <span className="k">{k}</span>
      <b>{v}</b>
      {was != null && <span className="was">기준 {was}</span>}
      {sub && <span className="sub">{sub}</span>}
    </div>
  )
}

function Bubble({ m }) {
  if (m.role === 'user') return <div className="msg-u">{m.text}</div>
  return (
    <div className="msg-a">
      {m.pending ? <span className="typing">계산 중…</span> : (
        <>
          {m.lines.map((l, i) => <p key={i}>{l}</p>)}
          {m.metrics?.length > 0 && (
            <div className="pills">{m.metrics.map((x) => <span className="pill" key={x.label}>{x.label} <b>{x.value}</b></span>)}</div>
          )}
          {m.todo && <p className="todo"><b>이렇게 해 보세요</b>{m.todo}</p>}
          {m.notes?.map((n, i) => <p className="warnline" key={i}>{n}</p>)}
        </>
      )}
    </div>
  )
}

export default function ScenarioPage() {
  const { bid, bidId, health } = useBid()
  const [params, setParams] = useState(ZERO)
  const [msgs, setMsgs] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [hedgeRatio, setHedgeRatio] = useState(0.5)
  const endRef = useRef(null)

  const table = useAsync(() => (bidId ? api.scenarioTable(bidId) : Promise.resolve(null)), [bidId]).data
  const { data, error } = useAsync(() => (bidId ? api.compare(bidId, params) : Promise.resolve(null)), [bidId, JSON.stringify(params)], 120)
  const path = useAsync(() => (bidId ? api.marginPath(bidId, params) : Promise.resolve(null)), [bidId, JSON.stringify(params)], 120).data
  const adv = useAsync(() => (bidId ? api.advice(bidId, params) : Promise.resolve(null)), [bidId, JSON.stringify(params)], 120).data
  const hedge = useAsync(() => (bidId ? api.hedge(bidId, params, hedgeRatio) : Promise.resolve(null)), [bidId, JSON.stringify(params), hedgeRatio], 120).data

  // 입찰을 바꾸면 대화를 새로 시작한다
  useEffect(() => {
    if (!bid) return
    setParams(ZERO)
    setMsgs([{ role: 'ai', lines: [
      `지금 보고 있는 입찰은 ${bid.id}(${bid.shipyard}), 견적가 ${usd(bid.quote_now)}(시장가 대비 ${vsMarket(bid.ratio_now)}), 납기까지 ${bid.lead_months}개월이에요.`,
      '바뀌었으면 하는 조건을 말로 물어보세요. 여러 조건을 한 번에 섞어도 돼요. 아래 질문을 눌러도 됩니다.',
    ] }])
  }, [bidId, bid?.id])
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [msgs])

  const send = async (raw) => {
    const message = (raw ?? text).trim()
    if (!message || busy || !bidId) return
    setText(''); setBusy(true)
    setMsgs((m) => [...m, { role: 'user', text: message }, { role: 'ai', pending: true }])
    try {
      const r = await api.chat(bidId, message, params)
      if (r.changed) setParams({ ...ZERO, ...r.params })
      setMsgs((m) => [...m.slice(0, -1), { role: 'ai', lines: r.lines, metrics: r.metrics, notes: r.notes, todo: r.todo }])
    } catch (e) {
      setMsgs((m) => [...m.slice(0, -1), { role: 'ai', lines: [`계산하지 못했어요 (${e.message}). 백엔드가 켜져 있는지 확인하세요.`] }])
    }
    setBusy(false)
  }

  const atBase = same(params, ZERO)
  const chips = useMemo(() => {
    const out = []
    const sg = (v) => `${v > 0 ? '+' : '-'}${Math.abs(v * 100).toFixed(0)}%`
    if (params.comp_pct) out.push({ k: 'comp_pct', t: `경쟁사 견적 ${sg(params.comp_pct)}` })
    if (params.steel_pct) out.push({ k: 'steel_pct', t: `후판가 ${sg(params.steel_pct)}` })
    if (params.fx_krw) out.push({ k: 'fx_krw', t: `환율 ${params.fx_krw.toLocaleString()}원` })
    else if (params.fx_pct) out.push({ k: 'fx_pct', t: `환율 ${sg(params.fx_pct)}` })
    if (params.delay_months) out.push({ k: 'delay_months', t: `납기 +${params.delay_months}개월` })
    if (params.quote_pct) out.push({ k: 'quote_pct', t: `우리 견적가 ${sg(params.quote_pct)}` })
    return out
  }, [params])
  const removeChip = (k) => setParams({ ...params, [k]: k === 'fx_krw' ? null : 0 })

  const base = table?.find((r) => r.id === 'base')
  const rowOf = (id) => table?.find((r) => r.id === id)

  // 위험 카드에 쓰는 한 줄: 그 조건이 낙찰확률을 깎는지 적자확률을 키우는지
  const riskLine = (w) => {
    const r = rowOf(w.id)
    if (!r || !base) return `기대가치 ${signed(w.d_ev, 1)} $M/척`
    const p = `낙찰확률 ${pct(base.p_now, 0)} → ${pct(r.p_now, 0)}`
    const l = `적자확률 ${pct(base.loss_prob_now, 0)} → ${pct(r.loss_prob_now, 0)}`
    const fxLine = w.group === '환율' && atBase && adv?.fx_breakeven != null ? `, ${krw(adv.fx_breakeven)} 밑이면 적자` : ''
    if (w.group === '경쟁' || w.group === '납기') return `${w.label}: ${p}`
    if (w.group === '환율') return `${w.label}: ${l}${fxLine}`
    if (w.group === '복합') return `${w.label}: ${p}, ${l}`
    return `${w.label}: ${l}`
  }

  // 조건 하나씩 나빠질 때 기대가치 감소 (막대)
  const bars = table
    ? BAR_IDS.map((id) => rowOf(id)).filter(Boolean).map((r) => ({ id: r.id, d: -r.d_ev })).sort((a, b) => b.d - a.d)
    : []
  const barMax = bars.length ? Math.max(...bars.map((x) => x.d), 0.01) : 1
  const barNote = (() => {
    if (bars.length < 3 || bars[0].d <= 0) return null
    const top = bars.filter((x) => x.d >= 0.5 * bars[0].d).map((x) => BAR_SHORT[x.id])
    const small = bars.filter((x) => x.d < 0.25 * bars[0].d).map((x) => BAR_SHORT[x.id])
    return `→ 이 건은 ${top.join('와 ')}만 챙기면 돼요.${small.length ? ` ${small.join('·')}는 영향이 작아요.` : ''}`
  })()

  return (
    <>
      <div className="workspace">
        <section className="card chat">
          <div className="chat-head"><h2>시나리오 질문</h2><p>조건을 말하면 다시 계산해서 답해요</p></div>
          <div className="chat-body">
            {msgs.map((m, i) => <Bubble m={m} key={i} />)}
            <div ref={endRef} />
          </div>
          <div className="suggest">
            <div className="lab">이어서 물어보기</div>
            <div className="row">
              {SUGGEST.map((q) => <button key={q} className="chip" disabled={busy} onClick={() => send(q)}>{q}</button>)}
              {!atBase && <button className="chip" disabled={busy} onClick={() => send('초기화')}>조건 초기화</button>}
            </div>
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send() }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="예: 중국이 5% 싸게 들어오고 환율이 1,350원이면?" maxLength={200} />
            <button type="submit" disabled={busy || !text.trim()} aria-label="보내기">→</button>
          </form>
        </section>

        <div className="stack">
          <BidBar />
          <div className="cond-row">
            <button className={`cond ${atBase ? 'on' : ''}`} onClick={() => setParams(ZERO)}>기준</button>
            {chips.map((c) => <button key={c.k} className="cond on x" onClick={() => removeChip(c.k)} title="누르면 이 조건을 뺍니다">{c.t}</button>)}
            {atBase && <span className="hint">아직 바꾼 조건이 없어요</span>}
          </div>
          {error && <p className="msg err">불러오지 못했습니다: {error}</p>}

          {/* 1. 판단: 결론 한 줄 + 핵심 숫자 4개 */}
          {adv && data && (() => {
            const b = data.base.summary, s = data.scenario.summary
            const was = (x, y, f) => (atBase ? null : f(x) === f(y) ? null : f(x))
            return (
              <section className={`card verdict-box ${adv.verdict.level}`}>
                <div className="vb-title"><span className="vb-pill">판단</span><h2>{adv.verdict.head}</h2></div>
                <p className="vb-text">{adv.verdict.text}</p>
                <div className="vb-stats">
                  <VStat k="낙찰확률" v={pct(s.p_now, 0)} was={was(b.p_now, s.p_now, (x) => pct(x, 0))} />
                  <VStat k="예상 마진" v={pct(s.margin_mean_now, 1)} was={was(b.margin_mean_now, s.margin_mean_now, (x) => pct(x, 1))} />
                  <VStat k="적자확률" v={pct(s.loss_prob_now, 0)} was={was(b.loss_prob_now, s.loss_prob_now, (x) => pct(x, 0))} />
                  <VStat k="버틸 수 있는 환율" tone="fx" v={adv.fx_breakeven != null ? krw(adv.fx_breakeven) : '사실상 없음'}
                    sub={adv.fx_breakeven == null ? '환율이 절반으로 내려가도 적자가 아니에요'
                      : adv.fx_gap < 0 ? `이 밑이면 적자 (지금보다 ${pct(adv.fx_gap, 0)})` : `지금 환율보다 ${pct(adv.fx_gap, 0)} 높아야 본전`} />
                </div>
                <p className="todo"><b>이렇게 해 보세요</b>{adv.verdict.todo}</p>
                <p className="vb-note">판단 기준: 견적가가 손익분기 선가 아래면 손해, 아니면 권장 범위(기대가치가 최고점의 85% 이상) 아래·위·안. 최종 결정은 담당자가 합니다.</p>
              </section>
            )
          })()}

          {/* 2. 주의할 것과 할 일: 위험 2개 + 조건 하나씩 나빠질 때 막대 */}
          {adv && (
            <section className="card card-pad">
              <h2 className="card-title">주의할 것과 할 일</h2>
              {adv.watch.length === 0 ? <p className="card-note">기대가치를 줄이는 조건이 없어요.</p> : (
                <div className="risk-grid">
                  {adv.watch.map((w, i) => (
                    <div className={`risk-card r${i + 1}`} key={w.id}>
                      <div className="risk-tag">위험 {i + 1}{i === 0 ? ' · 영향 가장 큼' : ''}</div>
                      <div className="risk-title">{RISK_NAME[w.group] || w.label}</div>
                      <p className="risk-line">{riskLine(w)}</p>
                      <p className="risk-todo"><b>할 일 ·</b> {w.todo}</p>
                      <button className="risk-apply" onClick={() => setParams({ ...ZERO, ...w.params })}>이 조건으로 보기</button>
                    </div>
                  ))}
                </div>
              )}
              {bars.length > 0 && (
                <div className="evbars">
                  <h3>조건 하나씩 나빠질 때 기대가치가 얼마나 줄어드나 <span className="unit">$M/척</span></h3>
                  {bars.map((x, i) => (
                    <div className="evbar" key={x.id}>
                      <span className="nm">{BAR_LABEL[x.id]}</span>
                      <span className="track"><span className={`fill ${x.d >= 0.5 * bars[0].d ? 'hot' : ''}`} style={{ width: `${Math.max((x.d / barMax) * 100, 2)}%` }} /></span>
                      <span className="val">−{x.d.toFixed(1)}</span>
                    </div>
                  ))}
                  {barNote && <p className="evbar-note">{barNote}</p>}
                </div>
              )}
            </section>
          )}

          {/* 3. 근거 보기: 기본은 접혀 있음 */}
          {data && (
            <section className="card card-pad">
              <h2 className="card-title">근거 보기<span className="unit">기본은 접혀 있음</span></h2>
              <Fold title="견적가별 기대가치 그래프" hint={data.scenario.summary.recommended != null ? `(이익 우선가 ${usd(data.scenario.summary.best_quote)}·수주 우선가 ${usd(data.scenario.summary.recommended)}가 어디서 나왔는지)` : ''}>
                <Figure title="견적가별 기대가치: 기준 vs 바뀐 조건" unit="$M / 척"
                  note="회색 점선이 기준 조건, 파란 선이 바뀐 조건입니다. 세로선은 견적가(우리 견적가를 바꿔 물으면 함께 움직입니다).">
                  <EvChart data={data.scenario} base={data.base} height={340} />
                </Figure>
              </Fold>
              {path && (() => {
                const end = (x) => x.points[x.points.length - 1]
                const pb = end(path.base), ps = end(path.scenario), moved = !atBase
                const range = (e) => `${pct(e.p10, 1)} ~ ${pct(e.p90, 1)}`
                return (
                  <Fold title="인도 시점 마진 범위" hint={`(${range(ps)})`}>
                    <h3 className="card-title">계약부터 인도까지 마진 범위<span className="unit">마진 %</span></h3>
                    <MarginPathChart data={path} height={300} />
                    <p className="breakdown">
                      인도 시점({path.scenario.months}개월) 마진 범위 <b>{range(ps)}</b>, 적자확률 <b>{pct(ps.loss_prob, 0)}</b>
                      {moved && <> (기준 {path.base.months}개월: {range(pb)}, 적자 {pct(pb.loss_prob, 0)})</>}
                    </p>
                    <p className="card-note">{`주황 띠는 환율·원가 시뮬레이션 10~90% 범위, 주황 선은 중앙값${moved ? ', 회색 점선은 기준 조건의 중앙값' : ''}입니다. 공정 이름은 납기를 4등분한 표시입니다. 달마다 아직 안 받은 대금과 아직 안 산 달러 원가를 그 시점 환율로 정산한다고 보고, 원가 초과는 건조가 진행되며 조금씩 반영된다고 가정했습니다.`}</p>
                  </Fold>
                )
              })()}
              {table && (() => {
                const fx10 = rowOf('fx_m10')
                const fxNote = base && fx10 && fx10.recommended != null && base.recommended != null && fx10.recommended > base.recommended
                return (
                  <Fold title="전체 시나리오 표" hint={`(${table.length - 1}개 조건)`}>
                    <p className="card-note">행을 누르면 그 조건이 적용됩니다. 수주 우선가의 ⚠는 그 가격에서 적자확률이 안전 기준(10%)을 넘는다는 뜻입니다.</p>
                    <table className="data">
                      <thead><tr><th>조건</th><th>낙찰확률</th><th>예상 마진</th><th>적자확률</th><th>기대가치</th><th>변화</th><th>이익 우선가</th><th>수주 우선가</th></tr></thead>
                      <tbody>
                        {table.map((r) => (
                          <tr key={r.id} className={`row ${r.id === 'base' ? 'base' : ''} ${same(params, { ...ZERO, ...r.params }) ? 'on' : ''}`} onClick={() => setParams({ ...ZERO, ...r.params })}>
                            <td>{r.label}{r.id === 'fx_m10' && fxNote ? ' ※' : ''}</td><td>{pct(r.p_now, 0)}</td>
                            <td className={r.margin_mean_now < 0 ? 'neg' : ''}>{pct(r.margin_mean_now, 1)}</td><td>{pct(r.loss_prob_now, 0)}</td>
                            <td>{r.ev_now.toFixed(1)}</td>
                            <td className={r.d_ev < 0 ? 'neg' : ''}>{r.id === 'base' ? '–' : signed(r.d_ev, 1)}</td>
                            <td>{r.recommended != null ? usd(r.best_quote) : '–'}</td>
                            <td className={r.loss_prob_win > (data.scenario.summary.loss_target ?? 0.1) ? 'neg' : ''}
                              title={r.loss_prob_win != null ? `이 가격의 적자확률 ${pct(r.loss_prob_win, 0)}` : undefined}>
                              {r.recommended != null ? usd(r.recommended) : '–'}{r.loss_prob_win > (data.scenario.summary.loss_target ?? 0.1) ? ' ⚠' : ''}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {fxNote && (
                      <p className="note-line">※ 환율 −10%에서 이익·수주 우선가가 오히려 오르는 이유: 환율이 내리면 원화로 쓰는 원가가 달러로는 비싸져 손익분기 선가가 올라가고, 남는 견적가도 함께 올라가요. 낙찰확률은 그대로라 기대가치는 줄어요.</p>
                    )}
                    <p className="card-note">{health?.source === 'mock' ? '낙찰확률 모델이 연결되기 전의 예시 계산입니다. ' : ''}경쟁사·후판가·환율 조건의 반영 방식은 학습이 아니라 팀이 정한 규칙입니다. 발표에서 가정이라고 밝혀야 합니다.</p>
                  </Fold>
                )
              })()}
              {hedge && (
                <Fold title="환헤지 계산" hint="(받을 달러 중 지금 환율로 고정하는 비율)">
                  <div className="seg hedge-seg">
                    {HEDGE_STEPS.map((h) => <button key={h} className={Math.abs(h - hedgeRatio) < 1e-9 ? 'on' : ''} onClick={() => setHedgeRatio(h)}>{h * 100}%</button>)}
                  </div>
                  <table className="data tight">
                    <thead><tr><th /><th>헤지 없음</th><th>헤지 {pct(hedge.hedged.ratio, 0)}</th></tr></thead>
                    <tbody>
                      <tr><td>적자확률</td><td>{pct(hedge.none.loss_prob, 0)}</td><td className={hedge.hedged.loss_prob > hedge.none.loss_prob ? 'neg' : 'pos'}><b>{pct(hedge.hedged.loss_prob, 0)}</b></td></tr>
                      <tr><td>예상 마진</td><td>{pct(hedge.none.margin_mean, 1)}</td><td>{pct(hedge.hedged.margin_mean, 1)}</td></tr>
                      <tr><td>마진 범위 (10~90%)</td><td>{pct(hedge.none.margin_p10, 1)} ~ {pct(hedge.none.margin_p90, 1)}</td><td>{pct(hedge.hedged.margin_p10, 1)} ~ {pct(hedge.hedged.margin_p90, 1)}</td></tr>
                      <tr><td>버틸 수 있는 환율</td><td>{hedge.none.fx_breakeven != null ? krw(hedge.none.fx_breakeven) : '사실상 없음'}</td><td>{hedge.hedged.fx_breakeven != null ? krw(hedge.hedged.fx_breakeven) : '사실상 없음'}</td></tr>
                    </tbody>
                  </table>
                  <p className="card-note">
                    {hedge.hedged.loss_prob > hedge.none.loss_prob
                      ? '예상 마진이 마이너스라 헤지로는 위험이 줄지 않아요. 견적가를 먼저 올려야 해요.'
                      : '헤지한 만큼은 환율이 올라도 이익을 못 봐요. 헤지 비용(선물환 포인트)은 0으로 가정했습니다.'}
                  </p>
                </Fold>
              )}
              <Fold title="계산에 쓴 가정" hint="(후판 원가 비중 10%, 원가 초과 0·4·8% 등)">
                <ul className="assume-list">
                  <li>후판 원가 비중 <b>10%</b>: 후판가가 오르면 손익분기 선가가 그 비중만큼 올라요.</li>
                  <li>원가 초과 <b>0% · 4% · 8%</b>가 각각 50% · 30% · 20% 확률 (팀 가정, 데이터에는 세 수준만 있음).</li>
                  <li>환율은 과거 월별 변동(월 약 1.9%)을 무작위로 5,000번 이어 붙여 만든 경로예요. 추세는 뺐어요.</li>
                  <li>환율 위험은 <b>원화 원가{data?.scenario?.summary?.krw_cost_share != null ? ` ${pct(data.scenario.summary.krw_cost_share, 0)}` : ''}</b>에만 걸려요. 달러로 사는 원가는 환율이 바뀌어도 달러로는 그대로예요.</li>
                  <li>대금은 계약·착공·진수·인도에 <b>20 · 20 · 20 · 40%</b>로 받고, 받는 시점의 환율로 환산해요. 헤지 비용은 0으로 가정했어요.</li>
                  <li>경쟁사·납기 조건은 낙찰확률 모델에 넣는 팀 규칙이에요. 납기가 늦어지면 낙찰확률도 떨어지고 환율에 노출되는 기간도 길어져요.</li>
                  <li>위 값은 임시 가정이라 발표에서 "가정"이라고 밝혀야 해요. 견적리스크 화면의 <b>가정 배지</b>에서 고칠 수 있어요.</li>
                </ul>
              </Fold>
            </section>
          )}
        </div>
      </div>
    </>
  )
}
