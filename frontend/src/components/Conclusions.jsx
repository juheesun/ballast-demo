import { usd, pct, signed, vsMarket, krw } from '../format.js'

// 숫자를 문장으로 옮기는 규칙. 기준값(임계치)은 여기서만 고친다.
const LOSS_WARN = 0.25, LOSS_MID = 0.10, WIN_LOW = 0.30, CUSHION_LOW = 0.05

function interp(grid, ratio, key) {
  const j = grid.findIndex((g) => g.ratio >= ratio)
  if (j <= 0) return grid[Math.max(j, 0)][key]
  const a = grid[j - 1], b = grid[j]
  return a[key] + ((b[key] - a[key]) * (ratio - a.ratio)) / (b.ratio - a.ratio)
}

export function buildVerdicts(data) {
  const s = data.summary, g = data.grid
  const market = s.quote_now / s.ratio_now
  const out = []

  // 1. 권장 견적가
  if (s.recommended == null) {
    out.push({ k: '권장 견적가', v: '권장 구간 없음', tag: ['warn', '주의'], d: '이 조건에서는 어떤 견적가에서도 기대가치가 0 이하입니다. 원가·납기 조건을 먼저 점검하세요.' })
  } else {
    out.push({ k: '권장 견적가', v: usd(s.recommended), tag: null,
      d: `시장 기준가 대비 ${vsMarket(s.recommended / market)}. 기대가치가 최고점의 85% 이상인 구간(${usd(s.band_lo)} ~ ${usd(s.band_hi)})의 하한이며, 최고점은 ${usd(s.best_quote)}입니다.` })
  }

  // 2. 현재 제안가 위치
  let pos
  if (s.band_lo == null) pos = ['권장 구간 없음', ['warn', '주의']]
  else if (s.quote_now < s.band_lo - 1e-6) pos = ['구간 아래', ['mid', '확인']]
  else if (s.quote_now > s.band_hi + 1e-6) pos = ['구간 위', ['warn', '주의']]
  else pos = ['구간 안', ['ok', '양호']]
  const posText = { '구간 아래': '권장 구간보다 낮게 제시했습니다. 낙찰 가능성은 높지만 이익을 덜 가져갑니다.', '구간 위': '권장 구간보다 높게 제시했습니다. 낙찰확률이 빠르게 떨어지는 영역입니다.', '구간 안': '기대가치가 최고점 근처입니다.', '권장 구간 없음': '비교할 구간이 없습니다.' }[pos[0]]
  out.push({ k: '현재 제안가 위치', v: `${usd(s.quote_now)} · ${pos[0]}`, tag: pos[1], d: `${vsMarket(s.ratio_now)} (시장 기준가 대비). 낙찰확률 ${pct(s.p_now, 0)}. ${posText}` })

  // 3. 손익분기 여유
  const cushion = (s.quote_now - s.bep) / s.quote_now
  out.push({ k: '손익분기 여유', v: `제안가가 ${pct(cushion, 1)} 높음`,
    tag: cushion < 0 ? ['warn', '손실'] : cushion < CUSHION_LOW ? ['mid', '얇음'] : null,
    d: `손익분기 선가 ${usd(s.bep)}(시장 기준가 대비 ${vsMarket(s.bep_ratio)}). 이 아래로 제시하면 수주해도 적자입니다.` })

  // 4. 환율 위험
  const lp = s.loss_prob_now
  const fxGap = (s.fx_breakeven / s.fx_assumed - 1) * 100
  out.push({ k: '환율·원가 위험', v: `손실 확률 ${pct(lp, 0)}`,
    tag: lp >= LOSS_WARN ? ['warn', '높음'] : lp >= LOSS_MID ? ['mid', '보통'] : ['ok', '낮음'],
    d: `인도 시점 환율이 ${krw(s.fx_breakeven)}(입찰 시점 대비 ${signed(fxGap, 1, '%')}) 아래로 가면 적자입니다. 인도까지 ${s.months}개월, 과거 월별 변동성 기준입니다.` })

  // 5. 가격 민감도
  const step = 0.01
  const dP = interp(g, s.ratio_now + step, 'p') - interp(g, s.ratio_now, 'p')
  out.push({ k: '가격 민감도', v: `1%p 올리면 ${Math.abs(dP * 100).toFixed(1)}%p ${dP < 0 ? '하락' : '상승'}`,
    tag: s.p_now < WIN_LOW ? ['warn', '낙찰 낮음'] : null,
    d: `제안가 부근에서 시장 기준가 대비 견적을 1%p 올릴 때 낙찰확률의 변화입니다. 현재 낙찰확률 ${pct(s.p_now, 0)}.` })

  // 6. 위험 반영 기대가치
  const evRisk = interp(g, s.ratio_now, 'ev_risk')
  out.push({ k: '기대가치 (위험 반영)', v: `${s.ev_now.toFixed(1)} → ${evRisk.toFixed(1)} $M`, tag: null,
    d: `환율·원가 변동을 반영하면 제안가 기준 기대가치가 이만큼 줄어듭니다. 앞 숫자는 낙찰확률 × (견적가 − 손익분기).` })
  return out
}

export default function Conclusions({ data }) {
  const items = buildVerdicts(data)
  return (
    <section>
      <h2 className="section-title">판단 요약</h2>
      <div className="verdicts">
        {items.map((it) => (
          <div className={`card verdict ${it.tag ? it.tag[0] : ''}`} key={it.k}>
            <div className="k"><span>{it.k}</span>{it.tag && <span className={`tag ${it.tag[0]}`}>{it.tag[1]}</span>}</div>
            <div className="v">{it.v}</div>
            <div className="d">{it.d}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
