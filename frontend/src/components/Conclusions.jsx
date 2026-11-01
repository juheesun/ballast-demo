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

// 권장 견적가 = 적자확률이 안전 기준 이하인 견적가 중 기대가치가 가장 높은 가격 (backend/quote_risk.py recommend())
// 판단 요약 한 줄씩: [항목, 값, 꼬리표(tone), ⓘ 설명]
export function buildSummary(data) {
  const s = data.summary, g = data.grid, m = data.money
  const market = s.quote_now / s.ratio_now
  const target = pct(s.loss_target ?? 0.1, 0)
  const pos = s.band_lo == null ? ['권장 범위 없음', 'warn'] : s.quote_now < s.band_lo - 1e-6 ? ['범위 아래', 'mid']
    : s.quote_now > s.band_hi + 1e-6 ? ['범위 위', 'mid'] : ['범위 안', 'ok']
  const cushion = (s.quote_now - s.bep) / s.quote_now
  const dP = interp(g, s.ratio_now + 0.01, 'p') - interp(g, s.ratio_now, 'p')
  const fx = s.fx_breakeven == null ? '사실상 없음' : `${krw(s.fx_breakeven)} (${signed((s.fx_breakeven / s.fx_assumed - 1) * 100, 1, '%')})`
  return [
    { k: '권장 견적가', v: s.recommended != null ? `${usd(s.recommended)} (${vsMarket(s.recommended / market)})` : '안전하게 딸 가격 없음',
      tone: s.recommended == null ? 'neg' : '',
      why: s.recommended != null
        ? `적자확률이 안전 기준(${target}) 이하인 견적가 중 기대가치가 가장 높은 가격입니다. 낙찰 ${pct(s.rec_p, 0)}, 기대가치 ${s.rec_ev?.toFixed(1)} $M, 적자확률 ${pct(s.rec_loss, 0)}.`
        : `적자확률을 ${target} 이하로 맞추려면 ${usd(s.rec_needed)}까지 올려야 하는데 그때 낙찰확률이 ${pct(s.rec_p, 0)}입니다.` },
    { k: '권장 범위', v: s.band_lo != null ? `${usd(s.band_lo)} ~ ${usd(s.band_hi)}` : '–',
      why: `기대가치가 최고점의 85% 이상이면서 적자확률이 ${target} 이하인 범위. 아래 끝은 꼭 따야 할 때 내려갈 수 있는 최저선입니다.` },
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
  ]
}

// 한 줄 조언: 권장 견적가(와 범위 아래 끝)로 옮기면 낙찰확률·기대가치·적자확률이 어떻게 바뀌나
export function evTip(data) {
  const s = data.summary
  if (s.recommended == null) return null
  const at = (q) => {
    const r = q / (s.quote_now / s.ratio_now)
    return { q, p: interp(data.grid, r, 'p'), ev: interp(data.grid, r, 'ev'), loss: interp(data.grid, r, 'loss_prob') }
  }
  const near = (q) => Math.abs(q - s.quote_now) < 0.05
  const line = (name, x) => `${name} ${usd(x.q)}: 낙찰 ${pct(x.p, 0)}, 기대가치 ${x.ev.toFixed(1)} $M, 적자 ${pct(x.loss, 0)}`
  const options = [{ key: 'rec', label: '권장 견적가로', ...at(s.recommended) }]
  if (s.band_lo != null && s.band_lo < s.recommended - 0.05) options.push({ key: 'floor', label: '범위 아래 끝으로', ...at(s.band_lo) })
  return {
    text: `지금 ${usd(s.quote_now)}: 낙찰 ${pct(s.p_now, 0)}, 기대가치 ${s.ev_now.toFixed(1)} $M, 적자 ${pct(s.loss_prob_now, 0)}`,
    options: options.map((o) => ({ ...o, text: line(o.key === 'rec' ? '권장 견적가' : '꼭 따야 할 때 최저선', o), here: near(o.q) })),
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
              <span>{o.text}</span>
              {o.here ? <span className="tag ok">지금 여기</span>
                : onMove && <button type="button" className="btn" onClick={() => onMove(o.q)}>{o.label}</button>}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
