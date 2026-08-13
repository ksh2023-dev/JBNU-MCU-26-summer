import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 개발 서버에서 /api 로 시작하는 요청을 백엔드(uvicorn --port 8000)로 넘긴다.
  // 프론트 코드가 상대 경로('/api/...')만 쓰게 되어 origin·포트에 묶이지 않는다.
  // 배포 환경 설정은 추후 별도로 결정한다.
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
