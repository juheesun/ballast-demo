import { useRef, useState } from 'react'
import { api } from '../api.js'
import { pct } from '../format.js'

// MVP4 · 새 입찰 기록 엑셀 업로드. 고르면 미리보기(오류 확인) → 오류가 없을 때만 저장 → onSaved 로 목록을 다시 불러온다.
const HEAD = '입찰일 · 조선소 · 견적($M) · 시장가($M) · 결과(낙찰/실주) 필수 · 선주 · 척수 · 실주 사유(가격/납기/사양/금융/기타) · 마진(%) · 메모 선택'

export default function HistoryUpload({ onSaved }) {
  const input = useRef(null)
  const [file, setFile] = useState(null)
  const [prev, setPrev] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const pick = async (f) => {
    setFile(f); setPrev(null); setMsg(null)
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.xlsx')) { setMsg({ err: true, t: '.xlsx 파일만 올릴 수 있습니다.' }); return }
    setBusy(true)
    try { setPrev(await api.historyUpload(f, false)) } catch (e) { setMsg({ err: true, t: `미리보기 실패: ${e.message}` }) }
    setBusy(false)
  }
  const reset = () => { setFile(null); setPrev(null); if (input.current) input.current.value = '' }
  const save = async () => {
    setBusy(true)
    try {
      const r = await api.historyUpload(file, true)
      setMsg({ t: `${r.saved}건을 저장했습니다${r.skipped ? ` (중복 ${r.skipped}건 건너뜀)` : ''}. 위 목록과 통계에 '업로드'로 반영됩니다.` }); reset(); onSaved()
    } catch (e) { setMsg({ err: true, t: `저장 실패: ${e.message}` }) }
    setBusy(false)
  }

  const valid = prev && !prev.file_errors.length && !prev.error_rows
  const ok = valid && prev.new_rows > 0
  const label = !valid ? '오류를 고친 뒤 다시 올려 주세요' : ok ? `${prev.new_rows}건 저장${prev.skipped ? ` (중복 ${prev.skipped}건 제외)` : ''}` : '새로 저장할 기록 없음 (모두 중복)'
  return (
    <section className="card card-pad">
      <h2 className="card-title">새 입찰 기록 올리기<span className="unit">엑셀 .xlsx</span></h2>
      <p className="card-note" style={{ marginTop: 4 }}>첫 줄 열 이름: {HEAD}</p>
      <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
        <input ref={input} type="file" accept=".xlsx" onChange={(e) => pick(e.target.files[0])} disabled={busy} />
        {prev && <button className="btn" onClick={save} disabled={!ok || busy}>{label}</button>}
        {prev && <button className="btn" onClick={reset} disabled={busy}>취소</button>}
      </div>
      {msg && <p className={`msg ${msg.err ? 'err' : ''}`}>{msg.t}</p>}
      {prev?.file_errors.map((t) => <p className="msg err" key={t}>{t}</p>)}
      {prev && prev.rows.length > 0 && (
        <table className="data" style={{ marginTop: 10 }}>
          <thead><tr><th>줄</th><th className="l">입찰일</th><th className="l">조선소</th><th>견적</th><th>시장가</th><th>결과</th><th className="l">실주 사유</th><th>마진</th><th className="l">확인</th></tr></thead>
          <tbody>
            {prev.rows.map((r) => (
              <tr key={r.line}>
                <td>{r.line}</td><td className="l">{r.date ?? '–'}</td><td className="l">{r.shipyard || '–'}</td>
                <td>{r.quote == null ? '–' : `$${r.quote.toFixed(1)}M`}</td><td>{r.market == null ? '–' : `$${r.market.toFixed(1)}M`}</td>
                <td>{r.won == null ? '–' : <span className={`tagc ${r.won ? 'win' : 'lose'}`}>{r.won ? '낙찰' : '실주'}</span>}</td>
                <td className="l">{r.loss_reason || '–'}</td><td>{r.margin == null ? '–' : pct(r.margin, 1)}</td>
                <td className={`l ${r.errors.length ? 'neg' : r.duplicate ? '' : 'pos'}`}>{r.errors.length ? r.errors.join(' · ') : r.duplicate ? `${r.duplicate} · 건너뜀` : '정상'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
