import { useEffect, useState } from 'react'

// 비동기 값을 불러오는 공통 훅. deps 가 바뀌면 다시 불러오고, 늦게 도착한 옛 응답은 버린다.
export function useAsync(fn, deps, delay = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    const t = setTimeout(() => {
      fn().then((data) => alive && setState({ data, error: null, loading: false }))
        .catch((e) => alive && setState({ data: null, error: e.message, loading: false }))
    }, delay)
    return () => { alive = false; clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
