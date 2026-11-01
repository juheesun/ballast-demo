// 백엔드 호출은 전부 여기로 모은다. 명세: docs/api-spec.md
async function request(url, opts) {
  const res = await fetch(url, opts)
  if (!res.ok) {
    const body = await res.json().catch(() => null)          // 서버가 보낸 안내 문구(detail)가 있으면 그대로 보여 준다
    throw new Error(typeof body?.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`)
  }
  return res.json()
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request('/api/health'),
  bids: () => request('/api/bids'),
  presets: () => request('/api/scenarios/presets'),
  fx: () => request('/api/fx/latest'),
  curve: (bidId, params = {}) => request(`/api/bids/${bidId}/curve?` + new URLSearchParams(params)),
  risk: (bidId, assumptions = {}) => request(`/api/bids/${bidId}/risk`, json(assumptions)),
  compare: (bidId, scenario) => request('/api/scenario/compare', json({ bid_id: bidId, scenario })),
  chat: (bidId, message, params) => request('/api/chat', json({ bid_id: bidId, message, params })),
  history: () => request('/api/history'),
  scenarioTable: (bidId) => request(`/api/bids/${bidId}/scenario-table`),
}
