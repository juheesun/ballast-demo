import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import HomePage from './pages/HomePage.jsx'
import ScenarioPage from './pages/ScenarioPage.jsx'
import SuppliersPage from './pages/SuppliersPage.jsx'
import HistoryPage from './pages/HistoryPage.jsx'

// 메뉴 = MVP 단위. 팀원은 자기 MVP 의 페이지 파일 하나만 채우면 된다.
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />            {/* MVP1 환율 기반 견적 리스크 */}
        <Route path="scenario" element={<ScenarioPage />} />  {/* MVP2 반사실 시나리오 */}
        <Route path="suppliers" element={<SuppliersPage />} /> {/* MVP3 공급사 평가 */}
        <Route path="history" element={<HistoryPage />} />     {/* MVP4 과거 데이터 */}
      </Route>
    </Routes>
  )
}
