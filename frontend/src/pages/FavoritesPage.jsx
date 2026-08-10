import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { getFavoriteProfessors, removeFavorite } from '../api/professorApi.js'
import ProfessorCard from '../components/ProfessorCard.jsx'
import Pagination from '../components/Pagenation.jsx'
import '../styles/FavoritesPage.css'

// 한 페이지에 보여줄 찜 교수 수
const PAGE_SIZE = 5

function FavoritesPage() {
  const navigate = useNavigate()

  const [favorites, setFavorites] = useState([]) // 찜한 교수 카드 전체
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false) // 불러오기 자체가 실패했는가?
  const [currentPage, setCurrentPage] = useState(1) // 현재 페이지 (1부터)

  // 페이지에 처음 들어왔을 때 한 번 전체를 불러온다.
  // (찜은 localStorage 라 양이 적어, 전체를 받아 프론트에서 페이지를 나눈다.
  //  서버가 나눠 보내주는 검색 페이지와는 방식이 다르다.)
  useEffect(() => {
    let ignore = false // 응답이 늦게 와서 페이지를 이미 떠난 경우, 옛 결과 무시용

    async function load() {
      setIsLoading(true)
      setHasError(false)
      try {
        const data = await getFavoriteProfessors() // { results, total, collectedAt }
        if (ignore) return
        setFavorites(data.results)
      } catch {
        if (ignore) return
        setHasError(true)
      } finally {
        if (!ignore) setIsLoading(false)
      }
    }

    load()
    return () => {
      ignore = true
    }
  }, [])

  // 전체 페이지 수 (최소 1). 찜이 줄어들면 이 값도 줄어든다.
  const totalPages = Math.max(1, Math.ceil(favorites.length / PAGE_SIZE))

  // 현재 페이지에 해당하는 부분만 잘라낸다 (프론트에서 페이지 나누기)
  const startIndex = (currentPage - 1) * PAGE_SIZE
  const visibleFavorites = favorites.slice(startIndex, startIndex + PAGE_SIZE)

  // 찜 취소 → 저장소에서 지우고, 화면 목록에서도 그 카드를 빼서 즉시 사라지게 한다
  function handleRemoveFavorite(id) {
    removeFavorite(id) // localStorage 라 sync

    const remaining = favorites.filter((professor) => professor.id !== id)
    setFavorites(remaining)

    // 찜을 지워서 현재 페이지가 사라진 경우(예: 2페이지의 마지막 1명을 삭제),
    // 존재하는 마지막 페이지로 자동으로 당겨준다.
    // (useEffect 로 뒤늦게 고치지 않고, 목록이 줄어드는 바로 이 자리에서 함께 정한다)
    const nextTotalPages = Math.max(1, Math.ceil(remaining.length / PAGE_SIZE))
    if (currentPage > nextTotalPages) setCurrentPage(nextTotalPages)
  }

  // 자세히 보기 → 상세 페이지로 이동 (라우팅은 카드가 아니라 페이지가 담당)
  function handleDetail(id) {
    navigate(`/professors/${id}`)
  }

  /* ---------- 1) 불러오는 중 ---------- */
  if (isLoading) {
    return <p className="favorites-message">불러오는 중입니다...</p>
  }

  /* ---------- 2) 불러오기 실패 ---------- */
  if (hasError) {
    return (
      <p className="favorites-message">
        찜 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
      </p>
    )
  }

  /* ---------- 3) 찜한 교수가 하나도 없음 ---------- */
  if (favorites.length === 0) {
    return (
      <div className="favorites-empty">
        <p>아직 찜한 교수가 없습니다.</p>
        <button
          type="button"
          className="favorites-button"
          onClick={() => navigate('/')}
        >
          교수 검색하러 가기 →
        </button>
      </div>
    )
  }

  /* ---------- 4) 정상 목록 ---------- */
  // 화면에 보이는 범위 (예: 총 7명 중 6–7명). 값을 지어내지 않고 실제로 계산한다.
  const rangeStart = startIndex + 1
  const rangeEnd = startIndex + visibleFavorites.length

  return (
    <div className="favorites-page">
      <div className="favorites-header">
        <h1 className="favorites-title">찜한 교수 목록</h1>
        <span className="favorites-count">총 {favorites.length}명</span>
      </div>

      <ul className="favorites-list">
        {visibleFavorites.map((professor) => (
          <li key={professor.id}>
            <ProfessorCard
              professor={professor}
              variant="search" // 목업의 가로형 카드
              isFavorite={true} // 이 페이지의 카드는 전부 찜한 교수
              onToggleFavorite={handleRemoveFavorite} // 여기선 항상 "찜 취소"
              onDetail={handleDetail}
            />
          </li>
        ))}
      </ul>

      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        onPageChange={setCurrentPage}
      />

      <p className="favorites-range">
        총 {favorites.length}명 중 {rangeStart}–{rangeEnd}명 표시
      </p>
    </div>
  )
}

export default FavoritesPage
