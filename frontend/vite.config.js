import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api 로 시작하는 요청은 FastAPI(8000)로 넘긴다 → CORS 설정 없이 개발 가능
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
})
