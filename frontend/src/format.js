// 숫자 표시 규칙을 한 곳에서 관리한다.
export const usd = (v, d = 1) => (v == null ? '–' : `$${v.toFixed(d)}M`)
export const pct = (v, d = 1) => (v == null ? '–' : `${(v * 100).toFixed(d)}%`)
export const signed = (v, d = 1, unit = '') => (v == null ? '–' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}${unit}`)
// 시장 기준가 대비 견적 비율(1.075) → "+7.5%"
export const vsMarket = (ratio, d = 1) => (ratio == null ? '–' : signed((ratio - 1) * 100, d, '%'))
export const krw = (v) => (v == null ? '–' : `${Math.round(v).toLocaleString('ko-KR')}원`)
