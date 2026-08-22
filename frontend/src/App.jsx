import { BrowserRouter, Routes, Route } from 'react-router-dom'

import Header from './components/Header.jsx'
import Footer from './components/Footer.jsx'

import HomePage from './pages/HomePage.jsx'
import SearchResultPage from './pages/SearchResultPage.jsx'
import ProfessorDetailPage from './pages/ProfessorDetailPage.jsx'
import FavoritesPage from './pages/FavoritesPage.jsx'

// 공통 CSS(index.css / global.css)는 main.jsx 에서 먼저 불러온다.

function App() {
  return (
    // BrowserRouter: 주소(URL)에 따라 화면을 바꿔주는 기능을 앱 전체에 켜준다
    <BrowserRouter>
      {/* Header / Footer는 여기 한 번만 두면 모든 페이지에서 공통으로 보인다 */}
      <Header />

      <main className="app-main">
        {/* Routes 안에서 "주소가 이거면 이 페이지" 를 하나씩 정해준다 */}
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/search" element={<SearchResultPage />} />
          {/* :id 는 자리표시자. /professors/P-012 처럼 아무 값이나 들어올 수 있다 */}
          <Route path="/professors/:id" element={<ProfessorDetailPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
        </Routes>
      </main>

      <Footer />
    </BrowserRouter>
  )
}

export default App
