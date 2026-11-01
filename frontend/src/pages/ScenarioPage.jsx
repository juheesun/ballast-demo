import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useBid } from '../context.js'
import { useAsync } from '../hooks.js'
import { usd, pct, signed, vsMarket, krw } from '../format.js'
import BidBar from '../components/BidBar.jsx'
import StatStrip from '../components/Stat.jsx'
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

  return (
    <>
      <div className="page-head">
        <h1>반사실 시나리오</h1>
        <p>"만약 ~라면?"을 물어보면 오른쪽 그래프와 숫자가 기준 조건과 나란히 바뀝니다.</p>
      </div>
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
          {adv && (
            <section className={`card verdict-box ${adv.verdict.level}`}>
              <div className="vb-head">{adv.verdict.head}</div>
              <p>{adv.verdict.text}</p>
              <p className="todo"><b>이렇게 해 보세요</b>{adv.verdict.todo}</p>
              <p className="vb-note">판단 기준: 견적가가 손익분기 선가 아래면 손해, 아니면 권장 구간(기대가치가 최고점의 85% 이상) 아래·위·안. 최종 결정은 담당자가 합니다.</p>
            </section>
          )}
          {error && <p className="msg err">불러오지 못했습니다: {error}</p>}
          {data && (() => {
            const b = data.base.summary, s = data.scenario.summary, d = data.delta
            return (
              <>
                <StatStrip items={[
                  { k: '낙찰확률', from: pct(b.p_now, 0), v: pct(s.p_now, 0), meter: s.p_now, delta: dtext(d.p_now * 100, 1, '%p'), s: '견적가 기준' },
                  { k: '예상 마진', from: pct(b.margin_mean_now, 1), v: pct(s.margin_mean_now, 1), delta: dtext(d.margin_mean_now * 100, 1, '%p'), s: '인도 시점 시뮬레이션 평균' },
                  { k: '적자확률', from: pct(b.loss_prob_now, 0), v: pct(s.loss_prob_now, 0), delta: dtext(d.loss_prob_now * 100, 1, '%p', d.loss_prob_now > 0), s: '낮을수록 안전' },
                  { k: '권장 견적가', from: b.recommended != null ? usd(b.recommended) : '–', v: s.recommended != null ? usd(s.recommended) : '없음', tone: 'accent', delta: d.recommended != null ? dtext(d.recommended, 1, 'M') : null, s: '권장 구간 하한' },
                ]} />
                <div className="two">
                  {adv && (
                    <section className="card card-pad">
                      <h2 className="card-title">버틸 수 있는 환율<span className="unit">인도 시점 원/달러</span></h2>
                      <div className="big">{adv.fx_breakeven != null ? krw(adv.fx_breakeven) : '사실상 없음'}</div>
                      <p className="card-note">
                        {adv.fx_gap == null ? '환율이 절반으로 내려가도 이 견적가로는 적자가 나지 않아요.'
                          : adv.fx_gap < 0
                            ? `지금 조건의 환율 ${krw(adv.fx_assumed)}보다 ${pct(-adv.fx_gap, 1)} 낮아요. 환율이 이 아래로 내려가 인도 때까지 머물면 이 견적가로는 적자예요.`
                            : `이미 지금 조건의 환율 ${krw(adv.fx_assumed)}보다 ${pct(adv.fx_gap, 1)} 높아요. 환율이 그만큼 올라야 겨우 본전이에요.`}
                      </p>
                    </section>
                  )}
                  {hedge && (
                    <section className="card card-pad">
                      <h2 className="card-title">환헤지 계산<span className="unit">받을 달러 중 지금 환율로 고정하는 비율</span></h2>
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
                    </section>
                  )}
                </div>
                <Figure title="견적가별 기대가치: 기준 vs 바뀐 조건" unit="$M / 척"
                  note="회색 점선이 기준 조건, 파란 선이 바뀐 조건입니다. 세로선은 견적가(우리 견적가를 바꿔 물으면 함께 움직입니다).">
                  <EvChart data={data.scenario} base={data.base} height={340} />
                </Figure>
              </>
            )
          })()}

          {adv && (
            <section className="card card-pad">
              <h2 className="card-title">주의할 것과 할 일<span className="unit">아래 표에서 기대가치가 가장 많이 줄어드는 조건</span></h2>
              {adv.watch.length === 0 ? <p className="card-note">기대가치를 줄이는 조건이 없어요.</p> : (
                <div className="watch">
                  {adv.watch.map((w, i) => (
                    <div className="watch-item" key={w.id}>
                      <div className="watch-k"><span className="n">{i + 1}</span>
                        <button className="cond" onClick={() => setParams({ ...ZERO, ...w.params })} title="누르면 이 조건이 적용됩니다">{w.label}</button>
                        <span className="neg">기대가치 {signed(w.d_ev, 1)} $M/척</span>
                      </div>
                      <p><b>할 일</b> {w.todo}</p>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {table && (() => {
            const row = (r, withDelta) => (
              <tr key={r.id} className={`row ${r.id === 'base' ? 'base' : ''} ${same(params, { ...ZERO, ...r.params }) ? 'on' : ''}`} onClick={() => setParams({ ...ZERO, ...r.params })}>
                <td>{r.label}{r.id === 'fx_m10' && fxNote ? ' ※' : ''}</td><td>{pct(r.p_now, 0)}</td><td className={r.margin_mean_now < 0 ? 'neg' : ''}>{pct(r.margin_mean_now, 1)}</td><td>{pct(r.loss_prob_now, 0)}</td>
                <td>{r.ev_now.toFixed(1)}</td>
                {withDelta && <td className={r.d_ev < 0 ? 'neg' : ''}>{r.id === 'base' ? '–' : signed(r.d_ev, 1)}</td>}
                <td>{r.recommended != null ? usd(r.recommended) : '–'}</td>
              </tr>
            )
            const head = (withDelta) => <thead><tr><th>조건</th><th>낙찰확률</th><th>예상 마진</th><th>적자확률</th><th>기대가치</th>{withDelta && <th>변화</th>}<th>권장가</th></tr></thead>
            const base = table.find((r) => r.id === 'base'), fx10 = table.find((r) => r.id === 'fx_m10')
            const fxNote = base && fx10 && fx10.recommended != null && base.recommended != null && fx10.recommended > base.recommended
            return (
              <section className="card card-pad">
                <h2 className="card-title">시나리오 비교<span className="unit">행을 누르면 그 조건이 적용됩니다</span></h2>
                <table className="data">
                  {head(false)}
                  <tbody>{table.filter((r) => !EVIDENCE_ONLY.has(r.id)).map((r) => row(r, false))}</tbody>
                </table>
                {fxNote && (
                  <p className="note-line">※ 환율 −10%에서 권장가가 오히려 오르는 이유: 환율이 내리면 같은 원화 원가를 달러로 바꾼 손익분기 선가가 올라가서, 남는 견적가(권장가)도 함께 올라가요. 낙찰확률은 그대로라 기대가치는 줄어요.</p>
                )}
                <p className="card-note">
                  {health?.source === 'mock' ? '낙찰확률 모델이 연결되기 전의 예시 계산입니다. ' : ''}
                  경쟁사·후판가·환율 조건의 반영 방식은 학습이 아니라 팀이 정한 규칙입니다. 발표에서 가정이라고 밝혀야 합니다.
                  예상 마진·적자확률은 견적리스크 화면과 같은 기본 가정(원가 중 원화 비중·대금 분할 20/20/20/40, 헤지 없음)으로 계산합니다.
                </p>
                <details className="evidence">
                  <summary>근거 보기 · 전체 조건 표와 계약~인도 마진 범위</summary>
                  <table className="data">
                    {head(true)}
                    <tbody>{table.map((r) => row(r, true))}</tbody>
                  </table>
                  {path && (() => {
                    const end = (x) => x.points[x.points.length - 1]
                    const pb = end(path.base), ps = end(path.scenario), moved = !atBase
                    const range = (e) => `${pct(e.p10, 1)} ~ ${pct(e.p90, 1)}`
                    return (
                      <div className="evidence-fig">
                        <h3 className="card-title">계약부터 인도까지 마진 범위<span className="unit">마진 %</span></h3>
                        <MarginPathChart data={path} height={300} />
                        <p className="breakdown">
                          인도 시점({path.scenario.months}개월) 마진 범위 <b>{range(ps)}</b>, 적자확률 <b>{pct(ps.loss_prob, 0)}</b>
                          {moved && <> (기준 {path.base.months}개월: {range(pb)}, 적자 {pct(pb.loss_prob, 0)})</>}
                        </p>
                        <p className="card-note">{`주황 띠는 환율·원가 시뮬레이션 10~90% 범위, 주황 선은 중앙값${moved ? ', 회색 점선은 기준 조건의 중앙값' : ''}입니다. 공정 이름은 납기를 4등분한 표시입니다. 달마다 아직 안 받은 대금과 아직 안 산 달러 원가를 그 시점 환율로 정산한다고 보고, 원가 초과는 건조가 진행되며 조금씩 반영된다고 가정했습니다.`}</p>
                      </div>
                    )
                  })()}
                </details>
              </section>
            )
          })()}
        </div>
      </div>
    </>
  )
}
