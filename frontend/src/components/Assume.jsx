import { useEffect, useState } from 'react'

// 가정값: 값 옆에 '가정' 배지. 누르면 그 자리에서 고친다 (Enter·바깥 클릭 = 적용, Esc = 취소).
// value 는 0~1 비율, 화면에는 % 로 보인다.
export default function Assume({ value, onChange, min = 0, max = 100, title }) {
  const [edit, setEdit] = useState(false)
  const [draft, setDraft] = useState('')
  const shown = Math.round(value * 1000) / 10
  useEffect(() => { if (!edit) setDraft(String(shown)) }, [shown, edit])

  const commit = () => {
    const v = parseFloat(draft)
    if (!Number.isNaN(v)) onChange(Math.max(min, Math.min(max, v)) / 100)
    setEdit(false)
  }
  if (edit) {
    return (
      <span className="assume editing">
        <input autoFocus type="number" min={min} max={max} step="1" value={draft} onChange={(e) => setDraft(e.target.value)}
          onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEdit(false) }} />%
      </span>
    )
  }
  return (
    <button type="button" className="assume" onClick={() => setEdit(true)} title={title || '가정값입니다. 눌러서 바로 고칠 수 있어요.'}>
      {shown}%<span className="assume-tag">가정</span>
    </button>
  )
}
