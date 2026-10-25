import { useEffect, useMemo, useState } from 'react'

// MVP3 · 공급사 평가. 데이터와 점수는 서버(/api/suppliers)에서 받는다.
// 서버에 연결할 수 없으면 아래 SEED 를 예시 데이터로 보여준다(저장되지 않음).
const API = '/api/suppliers'
const GRADE = { A: 1, B: 0.75, C: 0.5, D: 0.25 }
const SEED = [
  { id: 's1', name: '가온철강', item: '후판', debt: 120, opm: 8.5, cur: 160, rep: 'A', memo: '납기 준수율 높음', years: 12, amount: 620 },
  { id: 's2', name: '한결기전', item: '엔진·기자재', debt: 260, opm: 3.2, cur: 105, rep: 'B', memo: '', years: 4, amount: 140 },
  { id: 's3', name: '새빛도장', item: '도장', debt: 390, opm: -1.5, cur: 82, rep: 'C', memo: '최근 납기 지연 2건', years: 1, amount: 18 },
]
const EMPTY = { name: '', item: '', debt: '', opm: '', cur: '', rep: 'B', memo: '', years: '', amount: '' }
const NUMS = ['debt', 'opm', 'cur', 'years', 'amount']
const clamp = (v) => Math.max(0, Math.min(1, v))

// 점수 규칙 (재무 40 + 업계 평판 30 + 거래 신뢰 30). 서버의 supplier/supplier_score.py 와 같은 규칙이다.
// 평소에는 서버가 계산한 값을 쓰고, 이 함수는 서버가 꺼졌을 때 예시 데이터에만 쓴다. 규칙을 바꾸면 두 곳을 같이 고친다.
export function score(s) {
  const fin = (clamp(1 - (Number(s.debt) - 100) / 300) + clamp(Number(s.opm) / 10) + clamp((Number(s.cur) - 80) / 120)) / 3 * 40
  const rep = (GRADE[s.rep] ?? 0.5) * 30
  const trust = clamp(Number(s.years) / 10) * 15 + clamp(Number(s.amount) / 500) * 15
  return { fin, rep, trust, total: Math.round(fin + rep + trust) }
}
const grade = (t) => (t >= 75 ? 'a' : t >= 55 ? 'b' : 'c')
const label = (t) => (t >= 75 ? '양호' : t >= 55 ? '보통' : '주의')

async function req(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`${method} ${url} 실패 (${r.status})`)
  return r.status === 204 ? null : r.json()
}

// 폼 값(문자열)을 서버가 받는 형식으로 바꾼다
const toPayload = (f) => ({
  name: f.name.trim(), item: f.item, rep: f.rep, memo: f.memo,
  ...Object.fromEntries(NUMS.map((k) => [k, Number(f[k])])),
})

function Field({ label: lb, unit, children }) {
  return <div className="field"><label>{lb}{unit && <span className="unit"> ({unit})</span>}</label>{children}</div>
}

export default function SuppliersPage() {
  const [list, setList] = useState([])
  const [offline, setOffline] = useState(false)  // true = 서버 연결 안 됨, 예시 데이터 표시 중
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [sel, setSel] = useState(null)
  const [form, setForm] = useState(null)         // null = 닫힘

  const reload = () =>
    req('GET', API)
      .then((data) => { setList(data); setOffline(false) })
      .catch(() => { setList(SEED); setOffline(true) })
      .finally(() => setLoading(false))
  useEffect(() => { reload() }, [])

  const rows = useMemo(() => list.map((s) => ({ ...s, sc: s.sc ?? score(s) })).sort((a, b) => b.sc.total - a.sc.total), [list])
  const cur = rows.find((r) => r.id === sel) || rows[0]
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const num = (k, ph) => <input type="number" step="any" value={form[k]} onChange={set(k)} placeholder={ph} />
  const valid = form && form.name.trim() && NUMS.every((k) => form[k] !== '' && !isNaN(Number(form[k])))

  const save = async () => {
    setErr('')
    try {
      const saved = form.id
        ? await req('PUT', `${API}/${form.id}`, toPayload(form))
        : await req('POST', API, toPayload(form))
      await reload()
      setSel(saved.id); setForm(null)
    } catch (e) { setErr(`저장하지 못했습니다. 백엔드 서버가 켜져 있는지 확인하세요. (${e.message})`) }
  }
  const remove = async (id) => {
    setErr('')
    try { await req('DELETE', `${API}/${id}`); await reload(); setSel(null) }
    catch (e) { setErr(`삭제하지 못했습니다. (${e.message})`) }
  }

  return (
    <>
      <div className="page-head">
        <h1>공급사 평가</h1>
        <p>공급사를 등록하고 재무 상태, 업계 평판, 거래 신뢰도를 입력하면 평가 점수를 계산합니다.</p>
      </div>
      <div className="stack">
        <div className="toolbar">
          <button className="btn primary" disabled={offline} onClick={() => setForm({ ...EMPTY })} style={{ opacity: offline ? 0.5 : 1 }}>+ 공급사 등록</button>
          <span className="grow" />
          <span className="badge">
            {offline
              ? '서버에 연결할 수 없어 예시 데이터를 보여주는 중입니다. 등록·수정은 서버가 켜진 뒤에 할 수 있습니다'
              : '점수 규칙: 재무 40 · 평판 30 · 거래 30'}
          </span>
        </div>
        {err && <div className="badge">{err}</div>}

        {form && (
          <section className="card card-pad">
            <h2 className="card-title">{form.id ? '공급사 수정' : '공급사 등록'}</h2>
            <div className="form-grid">
              <div className="form-sec">기본 정보</div>
              <Field label="공급사명"><input value={form.name} onChange={set('name')} placeholder="예: ○○철강" /></Field>
              <Field label="공급 품목"><input value={form.item} onChange={set('item')} placeholder="예: 후판, 엔진" /></Field>
              <div />
              <div className="form-sec">재무 상태</div>
              <Field label="부채비율" unit="%">{num('debt', '예: 150')}</Field>
              <Field label="영업이익률" unit="%">{num('opm', '예: 5.5')}</Field>
              <Field label="유동비율" unit="%">{num('cur', '예: 130')}</Field>
              <div className="form-sec">업계 평가</div>
              <Field label="업계 평판 등급">
                <select value={form.rep} onChange={set('rep')}><option value="A">A · 매우 좋음</option><option value="B">B · 좋음</option><option value="C">C · 보통</option><option value="D">D · 나쁨</option></select>
              </Field>
              <Field label="메모"><input value={form.memo} onChange={set('memo')} placeholder="평판 근거, 특이사항" /></Field>
              <div />
              <div className="form-sec">거래 신뢰도</div>
              <Field label="거래 기간" unit="년">{num('years', '예: 6')}</Field>
              <Field label="누적 거래액" unit="억원">{num('amount', '예: 300')}</Field>
            </div>
            <div className="toolbar" style={{ marginTop: 16, marginBottom: 0 }}>
              <button className="btn primary" disabled={!valid} onClick={save} style={{ opacity: valid ? 1 : 0.5 }}>저장</button>
              <button className="btn ghost" onClick={() => setForm(null)}>취소</button>
              {!valid && <span className="badge">이름과 모든 숫자 항목을 채워 주세요</span>}
            </div>
          </section>
        )}

        <div className="two wide-left">
          <section className="card card-pad">
            <h2 className="card-title">공급사 목록<span className="unit">{rows.length}곳 · 점수순</span></h2>
            {loading ? <p className="empty">불러오는 중…</p> : rows.length === 0 ? <p className="empty">등록된 공급사가 없습니다.</p> : (
              <table className="data">
                <thead><tr><th>공급사</th><th className="l">품목</th><th>부채비율</th><th>거래</th><th>점수</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className={`row ${cur?.id === r.id ? 'on' : ''}`} onClick={() => setSel(r.id)}>
                      <td>{r.name}</td><td className="l">{r.item || '–'}</td><td>{r.debt}%</td><td>{r.years}년 · {r.amount}억</td>
                      <td><span className={`score ${grade(r.sc.total)}`}>{r.sc.total}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {cur && (
            <section className="card card-pad">
              <h2 className="card-title">{cur.name}<span className="unit"><span className={`score ${grade(cur.sc.total)}`}>{cur.sc.total}</span> {label(cur.sc.total)}</span></h2>
              <div className="bars" style={{ marginTop: 12 }}>
                {[['재무 상태', cur.sc.fin, 40], ['업계 평판', cur.sc.rep, 30], ['거래 신뢰', cur.sc.trust, 30]].map(([k, v, max]) => (
                  <div className="bar-row" key={k}><span>{k}</span><div className="track"><i style={{ width: `${(v / max) * 100}%` }} /></div><span className="val">{v.toFixed(0)} / {max}</span></div>
                ))}
              </div>
              <table className="data" style={{ marginTop: 14 }}>
                <tbody>
                  <tr><td>부채비율 · 영업이익률 · 유동비율</td><td>{cur.debt}% · {cur.opm}% · {cur.cur}%</td></tr>
                  <tr><td>업계 평판 등급</td><td>{cur.rep}</td></tr>
                  <tr><td>거래 기간 · 누적 거래액</td><td>{cur.years}년 · {cur.amount}억원</td></tr>
                  {cur.memo && <tr><td>메모</td><td>{cur.memo}</td></tr>}
                </tbody>
              </table>
              <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
                {!cur.sample && !offline && <button className="btn" onClick={() => setForm({ ...cur })}>수정</button>}
                {!offline && <button className="btn ghost" onClick={() => remove(cur.id)}>삭제</button>}
                {cur.sample && <span className="badge">예시 데이터</span>}
              </div>
            </section>
          )}
        </div>
      </div>
    </>
  )
}
