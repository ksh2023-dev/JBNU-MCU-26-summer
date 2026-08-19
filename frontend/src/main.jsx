import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// CSS 는 "아래에 깔리는 것부터" 순서대로 불러온다.
//   index.css  : 브라우저 기본값 정리 + 문서 단위 설정
//   global.css : 공통 디자인 토큰(색·형태·전환) + Header/본문/Footer 레이아웃
// 그 다음에 각 페이지·컴포넌트 CSS 가 자기 파일에서 import 된다.
import './index.css'
import './styles/global.css'

import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
