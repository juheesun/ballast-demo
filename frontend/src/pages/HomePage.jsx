import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useBid } from '../context.js'
import { useAsync } from '../hooks.js'
import { usd, pct, krw, eok, signed, vsMarket } from '../format.js'
import BidBar from '../components/BidBar.jsx'
import StatStrip from '../components/Stat.jsx'
import Figure from '../components/Figure.jsx'
import Conclusions from '../components/Conclusions.jsx'
import Assume from '../components/Assume.jsx'
import { Info, Legend } from '../components/Info.jsx'
import { EvChart, MarginBandChart, LossChart, BacktestChart, COLORS as C } from '../components/charts.jsx'

// 화면 그래프 요소별 설명 (ⓘ). 문구는 여기서만 고친다.
const LEGEND = {
  ev: [
    { kind: 'line', color: C.LINE, label: '기대가치', why: '견적가마다 낙찰확률 × (견적가 − 손익분기). 높을수록 평균적으로 많이 남는 견적입니다.' },
    { kind: 'band', color: C.BAND, label: '권장 구간', why: '기대가치가 최고점의 85% 이상인 범위. 이 안이면 기대가치를 크게 잃지 않습니다.' },
    { kind: 'dot', color: C.ACCENT, label: '권장가', why: '권장 구간의 하한. 기대가치를 지키면서 낙찰확률이 가장 높은 견적가입니다.' },
    { kind: 'hatch', color: C.LOSS, label: '손익분기 아래', why: '이 견적가로 따면 원가도 못 건집니다. 들어가면 안 되는 영역입니다.' },
    { kind: 'vline', color: C.INK, label: '견적가', why: '지금 내려는 견적가의 위치입니다.' },
  ],
  margin: [
    { kind: 'band', color: C.ACCENT, label: '10~90% 범위', why: '환율·원가가 흔히 움직이는 폭에서 마진이 어디까지 흔들리는지 보여 줍니다. 폭이 맞는지는 위 과거 검증에서 확인합니다.' },
    { kind: 'line', color: C.ACCENT, label: '중앙값', why: '시뮬레이션의 절반은 이보다 높고 절반은 낮습니다.' },
    { kind: 'hatch', color: C.LOSS, label: '0% 아래', why: '마진이 0% 아래면 적자입니다. 띠가 여기에 많이 걸칠수록 위험합니다.' },
    { kind: 'vline', color: C.INK, label: '견적가', why: '지금 견적가에서의 마진 범위를 읽는 기준선입니다.' },
  ],
  loss: [
    { kind: 'line', color: C.LOSS, label: '적자확률', why: '견적을 높게 부를수록 환율이 나빠져도 버틸 여유가 커져 적자확률이 내려갑니다.' },
    { kind: 'dash', color: C.MUTED, label: '안전 기준', why: '이 확률 이하면 "안전하다"고 보는 기준입니다 (가정, 위에서 고칠 수 있음).' },
    { kind: 'dash', color: C.ACCENT, label: '안전 시작 견적가', why: '적자확률이 안전 기준 이하가 되는 가장 낮은 견적가입니다. 견적을 이보다 낮게 시작하지 마세요.' },
    { kind: 'vline', color: C.INK, label: '견적가', why: '지금 견적가의 적자확률입니다.' },
  ],
  backtest: [
    { kind: 'line', color: C.LINE, label: '실제 환율 변화', why: '그 달에 입찰했다면 납기 동안 환율이 실제로 얼마나 움직였는지입니다.' },
    { kind: 'band', color: C.ACCENT, label: '시뮬레이션 10~90% 범위', why: '이 화면이 "흔히 일어나는 폭"으로 쓰는 범위입니다. 실제 선이 이 안에 80% 정도 들어오면 폭이 맞다는 뜻입니다.' },
    { kind: 'dot', color: C.INK, label: '범위 밖', why: '시뮬레이션이 예상한 폭을 벗어난 구간입니다. 위로 벗어나면 환율이 예상보다 많이 오른 경우(우리에겐 이익)입니다.' },
  ],
}

// 적자확률이 왜 이 값인지: 예전 계산에서 가정을 하나씩 더할 때의 변화 (막대 = 적자확률)
function StepBars({ steps }) {
  const max = Math.max(...steps.map((x) => x.loss_prob), 0.01)
  return (
    <div className="steps">
      {steps.map((x, i) => {
        const last = i === steps.length - 1
        const d = i > 0 ? x.loss_prob - steps[i - 1].loss_prob : null
        return (
          <div className={`step ${last ? 'last' : ''}`} key={x.key}>
            <div className="step-k"><b>{x.label}</b><span>{x.detail}</span></div>
            <div className="step-bar"><i style={{ width: `${Math.max((x.loss_prob / max) * 100, 1.5)}%` }} /></div>
            <div className="step-v"><b>{pct(x.loss_prob, 0)}</b>{d != null && Math.abs(d) >= 0.005 && <span className={d < 0 ? 'pos' : 'neg'}>{signed(d * 100, 0, '%p')}</span>}</div>
          </div>
        )
      })}
    </div>
  )
}

// 원가 구성 · 대금 분할 · 헤지 · 안전 기준. 값은 모두 가정이고 그 자리에서 고친다.
function AssumptionsCard({ data, value, onChange, onReset }) {
  const a = value, m = data.money, s = data.summary
  const set = (k, i, f) => (v) => onChange({ ...a, [k]: a[k].map((x, j) => (j === i ? { ...x, [f]: v } : x)) })
  const sum = (k, f) => a[k].reduce((t, x) => t + x[f], 0)
  const off = (k, f) => Math.abs(sum(k, f) - 1) > 0.005
  return (
    <section className="card card-pad">
      <h2 className="card-title">계산 가정
        <Info text="실제 원가·대금 조건을 모르는 부분은 가정으로 둡니다. 배지를 눌러 바로 고치면 아래 숫자가 모두 다시 계산됩니다." />
        <span className="unit">{data.assumptions.basis} · <button type="button" className="linkbtn" onClick={onReset}>기본값으로</button></span>
      </h2>

      <div className="sub-title">원가 구성
        <Info text="달러로 사는 원가(수입 엔진·기자재 등)는 환율이 내리면 같이 싸집니다. 그래서 환율 위험은 원화로 쓰는 원가에만 걸립니다." />
      </div>
      <table className="data compact">
        <thead><tr><th>항목</th><th>원가 중 비중</th><th>그중 달러</th><th>금액</th></tr></thead>
        <tbody>
          {a.costs.map((c, i) => (
            <tr key={c.key}>
              <td>{c.label}</td>
              <td><Assume value={c.share} onChange={set('costs', i, 'share')} /></td>
              <td><Assume value={c.usd_share} onChange={set('costs', i, 'usd_share')} /></td>
              <td>{eok(m.cost_total * c.share / sum('costs', 'share'))}</td>
            </tr>
          ))}
          <tr className="total"><td>실행원가 합계</td><td className={off('costs', 'share') ? 'neg' : ''}>{pct(sum('costs', 'share'), 0)}</td><td /><td>{eok(m.cost_total)}</td></tr>
        </tbody>
      </table>
      <p className="hl">원가 중 원화 비중 <b>{pct(s.krw_cost_share, 0)}</b> <span className="assume-tag">가정</span> — 환율 위험은 이 부분에만 걸려요.</p>

      <div className="sub-title">대금 분할 수령
        <Info text="계약·착공·진수·인도에 나눠 받는 대금은 받는 시점의 환율로 바뀝니다. 앞에서 많이 받을수록(선수금) 환율 위험이 줄어듭니다." />
      </div>
      <div className="ms-row">
        {a.milestones.map((x, i) => (
          <div className="ms" key={x.key}><span className="k">{x.label}</span><Assume value={x.weight} onChange={set('milestones', i, 'weight')} /></div>
        ))}
        <div className={`ms sum ${off('milestones', 'weight') ? 'neg' : ''}`}><span className="k">합계</span><b>{pct(sum('milestones', 'weight'), 0)}</b></div>
      </div>

      <div className="ms-row">
        <div className="ms"><span className="k">환헤지 비율
          <Info text="받을 달러 중 선물환으로 입찰 시점 환율에 고정하는 비율입니다. 환율이 내려도 손해가 없지만, 올라도 이익을 못 봅니다. (헤지 비용은 0으로 가정)" />
        </span><Assume value={a.hedge} onChange={(v) => onChange({ ...a, hedge: v })} /></div>
        <div className="ms"><span className="k">안전 기준 (적자확률)
          <Info text="적자확률이 이 값 이하면 '안전'으로 봅니다. 안전 시작 견적가와 아래 판단 도구의 기준입니다." />
        </span><Assume value={a.loss_target} min={1} max={50} onChange={(v) => onChange({ ...a, loss_target: v })} /></div>
      </div>
      {data.notes.map((n) => <p className="warnline" key={n}>{n}</p>)}
    </section>
  )
}

// "견적가를 $X 올릴까, 헤지를 Y%로 늘릴까" 판단 도구
function DecisionCard({ data, onHedge }) {
  const s = data.summary, d = data.decision, r = d.raise, h = d.hedge, eok1 = data.money.fx / 100
  const tgt = pct(d.target, 0)
  return (
    <section className="card card-pad decision">
      <h2 className="card-title">적자확률을 {tgt} 이하로 낮추려면
        <Info text="같은 목표(적자확률 기준)를 견적가로 맞출지, 환헤지로 맞출지 비교합니다. 견적을 올리면 낙찰확률을 잃고, 헤지는 환율 상승 이익을 포기합니다." />
      </h2>
      <p className="lead">지금 견적가 {usd(s.quote_now)}의 적자확률은 <b className={d.ok_now ? 'pos' : 'neg'}>{pct(s.loss_prob_now, 0)}</b>
        {d.ok_now ? ` — 이미 기준(${tgt}) 이하예요. 견적을 올리거나 헤지를 늘리지 않아도 돼요.` : ` — 기준(${tgt})보다 높아요. 둘 중 하나를 고르세요.`}</p>
      {d.ok_now && (
        <ul className="okfacts">
          <li>버틸 수 있는 환율: {s.fx_breakeven != null
            ? <><b>{krw(s.fx_breakeven)}</b> (입찰 시점 대비 {signed((s.fx_breakeven / s.fx_assumed - 1) * 100, 1, '%')}) 아래로 내려가 머물면 적자</>
            : <b>환율이 절반으로 내려가도 적자가 나지 않음</b>}</li>
          {s.safe_quote != null && s.safe_quote < s.quote_now && (
            <li>견적을 <b>{usd(s.safe_quote)}</b>까지 낮춰도 적자확률 {tgt} 이하를 지켜요 (지금보다 {usd(s.quote_now - s.safe_quote)} 여유).</li>
          )}
          <li>더 엄격하게 보려면 왼쪽 '안전 기준'을 낮춰 보세요.</li>
        </ul>
      )}
      {!d.ok_now && (
        <div className="options">
          <div className="opt">
            <div className="opt-k">A. 견적가 올리기</div>
            {r ? (
              <>
                <div className="opt-v">+{usd(r.delta)} <span>→ {usd(r.quote)}</span></div>
                <ul>
                  <li>척당 {eok(r.delta * eok1)} 더 받기</li>
                  <li>낙찰확률 {pct(s.p_now, 0)} → <b className={r.dp < 0 ? 'neg' : ''}>{pct(r.p, 0)}</b> ({signed(r.dp * 100, 0, '%p')})</li>
                  <li>기대가치 {s.ev_now.toFixed(1)} → {r.ev.toFixed(1)} $M/척</li>
                </ul>
              </>
            ) : <p className="muted">계산 범위(시장가 +15%) 안에서는 견적만으로 기준을 못 맞춰요.</p>}
          </div>
          <div className="opt">
            <div className="opt-k">B. 환헤지 늘리기</div>
            {h ? (
              <>
                <div className="opt-v">{pct(data.assumptions.hedge, 0)} → {pct(h.ratio, 0)}</div>
                <ul>
                  <li>낙찰확률 그대로 ({pct(s.p_now, 0)})</li>
                  <li>적자확률 → <b>{pct(h.loss_prob, 0)}</b>, 예상 마진 {pct(h.margin_mean, 1)}</li>
                  <li>환율이 올라도 헤지한 만큼은 이익을 못 봐요</li>
                </ul>
                <button type="button" className="btn" onClick={() => onHedge(h.ratio)}>헤지 {pct(h.ratio, 0)} 적용해 보기</button>
              </>
            ) : <p className="muted">헤지 100%로도 못 맞춰요. 남은 위험이 원가 초과(가정)라서 견적가를 올려야 해요.</p>}
          </div>
        </div>
      )}
      {!d.ok_now && r && h && (
        <p className="card-note">낙찰을 지키는 게 우선이면 B, 환율 상승 이익까지 챙기려면 A입니다. 판단은 담당자가 합니다.</p>
      )}
    </section>
  )
}

// 견적가 슬라이더: 움직이면 아래 숫자·결론·그래프의 현재 위치가 모두 그 견적가 기준으로 다시 계산된다.
// 트랙 색: 빗금 = 손익분기 아래, 파란 띠 = 권장 구간
function QuoteSlider({ data, value, onChange }) {
  const s = data.summary, g = data.grid
  const lo = g[0].quote, hi = g[g.length - 1].quote, market = s.quote_now / s.ratio_now
  const [draft, setDraft] = useState(value)
  useEffect(() => { setDraft(value) }, [value])
  const at = (q) => `${((q - lo) / (hi - lo)) * 100}%`
  const bands = [`var(--line-2) 0%`]
  if (s.bep > lo) bands.splice(0, 1, `#f6dcd8 0%`, `#f6dcd8 ${at(s.bep)}`, `var(--line-2) ${at(s.bep)}`)
  if (s.band_lo != null) bands.push(`var(--line-2) ${at(s.band_lo)}`, `var(--band) ${at(s.band_lo)}`, `var(--band) ${at(s.band_hi)}`, `var(--line-2) ${at(s.band_hi)}`)
  bands.push('var(--line-2) 100%')
  const d = draft - s.quote_orig
  return (
    <section className="card card-pad qslider">
      <div className="qs-top">
        <div>
          <div className="qs-k">견적가 <Info text="슬라이더로 견적가를 바꿔 보세요. 결론·숫자·판단 요약·그래프의 현재 위치가 모두 이 견적가 기준으로 다시 계산됩니다." /></div>
          <div className="qs-v">{usd(draft, 1)} <span>{eok(draft * data.money.fx / 100)}</span></div>
        </div>
        <div className="qs-side">
          <div>시장 기준가 대비 <b>{vsMarket(draft / market)}</b></div>
          <div className="muted">{Math.abs(d) < 0.05 ? '입찰 견적가 그대로' : `입찰 견적가 ${usd(s.quote_orig)} 대비 ${signed(d, 1, 'M')}`}</div>
        </div>
      </div>
      <input type="range" min={lo} max={hi} step={0.1} value={draft} style={{ background: `linear-gradient(to right, ${bands.join(', ')})` }}
        onChange={(e) => setDraft(Number(e.target.value))} onMouseUp={() => onChange(draft)} onTouchEnd={() => onChange(draft)} onKeyUp={() => onChange(draft)}
        aria-label="견적가" />
      <div className="qs-ends">
        <span>{usd(lo, 0)} (공격적)</span>
        <span className="qs-btns">
          {s.recommended != null && <button type="button" className="btn" onClick={() => onChange(s.recommended)}>권장가 {usd(s.recommended)}로</button>}
          {Math.abs(d) >= 0.05 && <button type="button" className="btn ghost" onClick={() => onChange(null)}>입찰 견적가로</button>}
        </span>
        <span>{usd(hi, 0)} (보수적)</span>
      </div>
      <div className="qs-legend"><i className="lg-hatch" />손익분기 아래 <i className="lg-band" />권장 구간</div>
    </section>
  )
}

// MVP1 · 환율 기반 견적 리스크 (달러 견적 기준)
export default function HomePage() {
  const { bidId, health } = useBid()
  const [assume, setAssume] = useState(null)              // null = 서버 기본값(선종·규모별)
  const [quote, setQuote] = useState(null)                // null = 입찰 견적가
  useEffect(() => { setAssume(null); setQuote(null) }, [bidId])
  const { data, error, loading } = useAsync(() => (bidId ? api.risk(bidId, { ...(assume || {}), quote }) : Promise.resolve(null)),
    [bidId, JSON.stringify(assume), quote], 150)
  const shown = data && data.bid_id === bidId ? data : null

  return (
    <>
      <div className="page-head">
        <h1>환율 기반 견적 리스크</h1>
        <p>견적가를 움직여 보며 낙찰확률·기대가치와 환율로 적자가 날 위험을 함께 봅니다.</p>
      </div>
      <div className="stack">
      <BidBar />
      {error && <p className="msg err">불러오지 못했습니다: {error}</p>}
      {loading && !shown && <p className="msg">계산 중…</p>}
      {shown && (() => {
        const s = shown.summary, bt = shown.backtest
        const a = assume || shown.assumptions
        const v = shown.verdict, st = shown.steps
        const first = st[0], final = st[st.length - 1]
        const biggest = st.slice(1).reduce((b, x, i) => (Math.abs(x.loss_prob - st[i].loss_prob) > Math.abs(b.d) ? { x, d: x.loss_prob - st[i].loss_prob } : b), { x: null, d: 0 })
        return (
          <>
            <QuoteSlider data={shown} value={quote ?? s.quote_orig} onChange={setQuote} />
            <section className={`card verdict-box ${v.level}`}>
              <div className="vb-head">{v.head}</div>
              <p>{v.text}</p>
              <p className="todo"><b>이렇게 해 보세요</b>{v.todo}</p>
              <p className="vb-note">판단 기준: 적자확률이 안전 기준({pct(a.loss_target, 0)}) 이하면 낮음, 25% 이상이면 높음. 견적가가 손익분기 아래면 환율과 상관없이 손해. 이 가격으로 들어갈지는 반사실 화면에서 판단합니다.</p>
            </section>
            <StatStrip items={[
              { k: '낙찰확률', v: pct(s.p_now, 0), meter: s.p_now, s: '이 견적가로 낙찰될 확률' },
              { k: '기대가치 (척당)', v: `${s.ev_now.toFixed(1)} $M`, s: '낙찰확률 × (견적가 − 손익분기)' },
              { k: '적자확률', v: pct(s.loss_prob_now, 0), tone: s.loss_prob_now > a.loss_target ? 'warn' : '',
                s: `인도까지 ${s.months}개월 · 예전 계산이면 ${pct(shown.simple.loss_prob, 0)}` },
              { k: '권장 견적가', v: s.recommended != null ? usd(s.recommended) : '없음', tone: 'accent', s: s.band_lo != null ? `권장 구간 ${usd(s.band_lo)} ~ ${usd(s.band_hi)}` : '기대가치가 0 이하' },
            ]} />

            <div className="two wide-left">
              <Figure title="견적가별 기대가치" unit="척당 $M"
                info="얼마에 내야 평균적으로 가장 많이 남는지 봅니다. 너무 높으면 못 따고, 너무 낮으면 따도 남는 게 없습니다.">
                <EvChart data={shown} height={340} />
                <Legend items={LEGEND.ev} />
              </Figure>
              <Conclusions data={shown} onRecommended={() => setQuote(s.recommended)} />
            </div>
            <div className="two">
              <Figure title="견적가별 적자확률" unit="%" info="견적을 얼마 이상 불러야 환율이 나빠져도 버틸 수 있는지 봅니다.">
                <LossChart data={shown} target={a.loss_target} safe={s.safe_quote} />
                <Legend items={LEGEND.loss} />
              </Figure>
              <Figure title="인도 시점 마진 범위" unit="%" info="같은 견적가라도 환율·원가에 따라 마진이 흔들립니다. 얼마나 흔들리는지 봐야 견적의 여유를 정할 수 있습니다.">
                <MarginBandChart data={shown} />
                <Legend items={LEGEND.margin} />
              </Figure>
            </div>

            <h2 className="section-title">근거 <span className="section-sub">숫자가 왜 이렇게 나왔나</span></h2>
            <div className="two">
              <Figure title={`적자확률 ${pct(final.loss_prob, 0)}의 근거`} unit="가정을 하나씩 더할 때"
                info="예전 계산(원가 전부 원화, 대금은 인도 때 한 번에)에서 시작해, 실제 조선업 조건을 하나씩 반영하면 적자확률이 어떻게 바뀌는지 보여 줍니다.">
                <StepBars steps={st} />
                <p className="note-line">
                  {Math.abs(final.loss_prob - first.loss_prob) < 0.005
                    ? '가정을 반영해도 적자확률은 거의 그대로예요.'
                    : <>예전 계산 {pct(first.loss_prob, 0)} → 지금 {pct(final.loss_prob, 0)}. 가장 크게 바꾼 건 <b>{biggest.x?.label}</b>({signed(biggest.d * 100, 0, '%p')})이에요.</>}
                  {final.loss_prob > first.loss_prob + 0.005 && ' 예상 마진이 마이너스라, 환율이 올라 손해를 메울 기회가 줄어서 오히려 올라가요.'}
                </p>
              </Figure>
              {bt.n > 0 && (
                <Figure title="과거 검증: 시뮬레이션 범위가 맞나" unit={`${bt.from.slice(0, 4)}년 이후 ${bt.months}개월 구간 ${bt.n}개`}
                  info={`${bt.from}~${bt.to} 월별 환율로, 그 달에 입찰했다면 납기(${bt.months}개월) 동안 환율이 실제로 얼마나 움직였는지 한 달씩 밀며 확인했습니다. 구간이 서로 겹치고 시뮬레이션도 같은 기간 환율로 만들었으므로 참고용입니다.`}>
                  <BacktestChart bt={bt} />
                  <Legend items={LEGEND.backtest} />
                  <p className="note-line">실제 환율의 <b>{pct(bt.inside, 0)}</b>가 범위 안 (목표 80%) · 범위보다 오른 경우 {pct(bt.above, 0)}, 내린 경우 {pct(bt.below, 0)}
                    {bt.inside >= 0.8 ? ' → 범위가 과거 변동을 충분히 담아요.' : ' → 범위가 과거 변동보다 좁아요. 적자확률을 낮게 볼 수 있어요.'}</p>
                </Figure>
              )}
            </div>

            <h2 className="section-title">가정과 대응 <span className="section-sub">가정을 고치면 위 숫자가 모두 다시 계산돼요</span></h2>
            <div className="two">
              <AssumptionsCard data={shown} value={a} onChange={setAssume} onReset={() => setAssume(null)} />
              <DecisionCard data={shown} onHedge={(h) => setAssume({ ...a, hedge: h })} />
            </div>

            <p className="card-note">
              {health?.source === 'mock'
                ? '낙찰확률 모델이 아직 연결되지 않아 낙찰확률은 예시 계산입니다. 손익분기와 환율 위험은 실제 계산입니다.'
                : '낙찰확률은 합성 시나리오로 학습한 모델이며 독립된 입찰 상황이 8개뿐입니다. 절대값보다 곡선의 모양과 조건 간 차이로 읽으세요.'}
              {' '}원가 구성·대금 분할·헤지 비율은 팀 가정이며, 원화 금액은 입찰 시점 환율로 환산했습니다.
            </p>
          </>
        )
      })()}
      </div>
    </>
  )
}
