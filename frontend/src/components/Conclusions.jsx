import { usd, pct, signed, vsMarket, krw, eok } from '../format.js'
import { Info } from './Info.jsx'

// 숫자를 문장으로 옮기는 규칙. 기준값(임계치)은 여기서만 고친다.
const LOSS_WARN = 0.25, CUSHION_LOW = 0.05

function interp(grid, ratio, key) {
  const j = grid.findIndex((g) => g.ratio >= ratio)
  if (j <= 0) return grid[Math.max(j, 0)][key]
  const a = grid[j - 1], b = grid[j]
  return a[key] + ((b[key] - a[key]) * (ratio - a.ratio)) / (b.ratio - a.ratio)
}

// 수주 우선가에서의 적자확률과 안전 기준. 기준을 넘으면 over = true → 화면에 경고
// (수주 우선가는 낙찰확률·기대가치만 보고 정한 값이라 환율 위험은 따로 본다)
export function winRisk(data) {
  const s = data.summary
  if (s.recommended == null) return null
  const loss = interp(data.grid, s.recommended / (s.quote_now / s.ratio_now), 'loss_prob')
  const target = data.assumptions?.loss_target ?? s.loss_target ?? 0.10
  return { loss, target, over: loss > target + 1e-9 }
}

// 판단 요약 한 줄씩: [항목, 값, 꼬리표(tone), ⓘ 설명]
export function buildSummary(data) {
  const s = data.summary, g = data.grid, m = data.money
  const market = s.quote_now / s.ratio_now
  const wr = winRisk(data)
  const pos = s.band_lo == null ? ['권장 범위 없음', 'warn'] : s.quote_now < s.band_lo - 1e-6 ? ['범위 아래', 'mid']
    : s.quote_now > s.band_hi + 1e-6 ? ['범위 위', 'mid'] : ['범위 안', 'ok']
  const cushion = (s.quote_now - s.bep) / s.quote_now
  const dP = interp(g, s.ratio_now + 0.01, 'p') - interp(g, s.ratio_now, 'p')
  const fx = s.fx_breakeven == null ? '사실상 없음' : `${krw(s.fx_breakeven)} (${signed((s.fx_breakeven / s.fx_assumed - 1) * 100, 1, '%')})`
  return [
    { k: '이익 우선가', v: s.recommended != null ? `${usd(s.best_quote)} (${vsMarket(s.best_quote / market)})` : '없음',
      why: '기대가치가 가장 높은 견적가. 평균적으로 가장 많이 남습니다.' },
    { k: '수주 우선가', v: s.recommended != null ? `${usd(s.recommended)} (${vsMarket(s.recommended / market)})` : '없음',
      tone: wr?.over ? 'neg' : '', tag: wr?.over ? [`적자 ${pct(wr.loss, 0)}`, 'warn'] : null,
      why: `권장 범위(${usd(s.band_lo)} ~ ${usd(s.band_hi)}, 기대가치가 최고점의 85% 이상)의 아래 끝. 꼭 따야 할 때 여기까지 내려도 기대가치를 크게 잃지 않습니다.`
        + (wr?.over ? ` 단, 이 가격에서는 환율·원가로 적자가 날 확률이 ${pct(wr.loss, 0)}로 안전 기준(${pct(wr.target, 0)})을 넘습니다.` : '') },
    { k: '현재 견적가 위치', v: `시장 대비 ${vsMarket(s.ratio_now)}`, tag: pos },
    { k: '손익분기 여유', v: `${pct(cushion, 1)} (${s.quote_now < s.bep ? '−' : ''}${usd(Math.abs(s.quote_now - s.bep))})`, tone: cushion < 0 ? 'neg' : cushion < CUSHION_LOW ? 'mid' : 'pos',
      why: `손익분기 선가 ${usd(s.bep)}. 이 아래로 내면 수주해도 적자입니다.` },
    { k: '버틸 수 있는 환율', v: fx, tone: s.loss_prob_now >= LOSS_WARN ? 'neg' : '',
      why: '환율이 이 아래로 내려가 인도 때까지 머물면 적자입니다. 괄호는 입찰 시점 환율 대비입니다.' },
    { k: '가격 민감도', v: `1%p 올리면 낙찰 ${signed(dP * 100, 1, '%p')}`, why: '시장 기준가 대비 견적을 1%p 올릴 때 낙찰확률의 변화입니다.' },
    { sep: true },
    { k: '척당 예상 이익', v: eok(m.profit_ship_mean), tone: m.profit_ship_mean < 0 ? 'neg' : '',
      why: `환율·원가 시뮬레이션 평균. 10~90% 범위 ${eok(m.profit_ship_p10)} ~ ${eok(m.profit_ship_p90)}.` },
    { k: `전체 ${m.num_ships}척 합계`, v: eok(m.profit_total_mean), tone: m.profit_total_mean < 0 ? 'neg' : '' },
    { k: '실행원가 (척당)', v: eok(m.cost_total), why: `원가 구성(아래 계산 가정)의 합계. 견적가는 ${eok(m.quote_krw)}, 환율 ${krw(m.fx)} 기준.` },
    { k: '안전 시작 견적가', v: s.safe_quote != null ? `${usd(s.safe_quote)} (${eok(m.safe_quote_krw)})` : '범위 밖',
      why: '적자확률이 안전 기준 이하가 되는 가장 낮은 견적가. 견적을 이보다 낮게 시작하지 마세요.' },
  ]
}

// 한 줄 조언: 이익 우선가·수주 우선가로 옮기면 낙찰확률·기대가치가 어떻게 바뀌나
export function evTip(data) {
  const s = data.summary
  if (s.recommended == null) return null
  const at = (q) => {
    const r = q / (s.quote_now / s.ratio_now)
    return { q, p: interp(data.grid, r, 'p'), ev: interp(data.grid, r, 'ev') }
  }
  const best = at(s.best_quote), win = at(s.recommended), wr = winRisk(data)
  const near = (q) => Math.abs(q - s.quote_now) < 0.05
  const line = (name, x) => `${name} ${usd(x.q)}: 낙찰 ${pct(x.p, 0)}, 기대가치 ${x.ev.toFixed(1)} $M`
  return {
    text: `지금 ${usd(s.quote_now)}: 낙찰 ${pct(s.p_now, 0)}, 기대가치 ${s.ev_now.toFixed(1)} $M`,
    options: [
      { key: 'best', label: '이익 우선가로', text: line('이익 우선가', best), q: best.q, here: near(best.q) },
      { key: 'win', label: '수주 우선가로', text: line('수주 우선가', win), q: win.q, here: near(win.q),
        warn: wr?.over ? `이 가격에서는 적자확률 ${pct(wr.loss, 0)}로 안전 기준(${pct(wr.target, 0)})을 넘어요.` : null },
    ],
  }
}

export default function Conclusions({ data, onMove }) {
  const items = buildSummary(data), tip = evTip(data)
  return (
    <section className="card card-pad summary">
      <h2 className="card-title">판단 요약<span className="unit">지금 견적가 {usd(data.summary.quote_now)} 기준</span></h2>
      <dl className="kv">
        {items.map((it, i) => it.sep ? <hr key={i} /> : (
          <div className="kv-row" key={it.k}>
            <dt>{it.k}{it.why && <Info text={it.why} />}</dt>
            <dd className={it.tone || ''}>{it.v}{it.tag && <span className={`tag ${it.tag[1]}`}>{it.tag[0]}</span>}</dd>
          </div>
        ))}
      </dl>
      {tip && (
        <div className="tip">
          <span className="tip-now">{tip.text}</span>
          {tip.options.map((o) => (
            <div className="tip-row" key={o.key}>
              <span>{o.text}{o.warn && <span className="tip-warn">⚠ {o.warn}</span>}</span>
              {o.here ? <span className="tag ok">지금 여기</span>
                : onMove && <button type="button" className="btn" onClick={() => onMove(o.q)}>{o.label}</button>}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
