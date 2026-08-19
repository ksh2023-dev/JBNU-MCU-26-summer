/**
 * FavoritesPage.jsx — 찜한 교수 목록 페이지
 *
 * 「데이터 계약 문서 v6.3」 6장 화면 매핑의 "4. 찜 목록" 화면입니다.
 * 찜 목록 전용 백엔드 API는 없고, API ① getProfessors() 를 재사용합니다. (v6.3 확정)
 *
 *   ① localStorage 에서 찜 id 배열을 읽는다        getFavorites()
 *   ② query: "" + filters.favoriteIds 로 검색한다   getProfessors()
 *   ③ 응답의 results / total 을 그대로 화면에 쓴다
 *
 * 이 페이지가 "하지 않는" 일 (계약 v6.3 API ①)
 *   - 교수별로 getProfessorById() 를 찜 개수만큼 호출하지 않습니다.
 *   - 응답을 다시 거르거나(filter) 정렬하거나(sort) 자르지(slice) 않습니다.
 *     교집합·이름 오름차순·페이지네이션·total 계산은 전부 백엔드 몫입니다.
 *     (query 가 "" 이므로 browse 정책 — matchScore 는 null, minScore 미적용, 이름 오름차순)
 *   - 화면에 보일 수를 localStorage 길이로 세지 않습니다. 항상 응답의 total 을 씁니다.
 *     찜 id 중 데이터에 없는 교수가 섞여 있으면 둘은 서로 다를 수 있습니다. (v6.3)
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  getProfessors,
  getProfessorById,
  getFavorites,
  removeFavorite,
  DEFAULT_PAGE_SIZE,
} from '../api/professorApi.js'
import ProfessorCard from '../components/ProfessorCard.jsx'
import Pagination from '../components/Pagination.jsx'
import {
  buildContactDraft,
  toMailtoHref,
  openMailto,
} from '../utils/contactMail.js'
import '../styles/FavoritesPage.css'

function FavoritesPage() {
  const navigate = useNavigate()

  /**
   * localStorage 의 찜 id 배열.
   *
   * 요청에 실어 보낼 값이면서, 동시에 재조회 트리거이기도 합니다.
   * 찜을 취소하면 removeFavorite 가 "새 배열"을 돌려주므로 아래 effect 가 다시 돕니다.
   *
   * 이 화면에서는 항상 배열입니다. null(찜 필터 꺼짐 = 전체 교수 목록)로 보내지 않습니다.
   * 찜이 0명이면 빈 배열 [] 이 그대로 실려 results: [], total: 0 이 옵니다. (계약 v6.3)
   */
  const [favoriteIds, setFavoriteIds] = useState(() => getFavorites())

  const [page, setPage] = useState(1) // 현재 페이지 (1부터)
  const [results, setResults] = useState([]) // 현재 페이지의 교수 카드 (응답 그대로)
  const [total, setTotal] = useState(0) // 조건에 맞는 전체 교수 수 (응답값)
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false) // 불러오기 자체가 실패했는가?
  const [contactNotice, setContactNotice] = useState('')

  /**
   * 찜 목록이나 페이지가 바뀔 때마다 API ① 을 호출합니다.
   * (계약 v6.3 3장: 페이지 클릭 시 API ① 을 page 만 바꿔 재호출)
   */
  useEffect(() => {
    let ignore = false // 응답이 늦게 와서 조건이 이미 바뀐 경우, 옛 결과 무시용

    async function load() {
      setIsLoading(true)
      setHasError(false)
      try {
        // 인자 모양은 계약 v6.3 API ①의 요청 JSON 과 같습니다.
        // sort('relevance')·minScore 는 getProfessors 의 기본값이 그대로 실립니다.
        // 검색어가 "" 라 백엔드가 minScore 를 무시합니다. (v6.3 browse 정책)
        const data = await getProfessors('', {
          filters: { professorType: [], favoriteIds },
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        })
        if (ignore) return

        // 찜을 취소해 결과가 줄면서 지금 보던 페이지가 사라질 수 있습니다.
        // 그때는 존재하는 마지막 페이지로 당겨 다시 조회합니다.
        // 새 total 은 응답이 와야 알 수 있어(없는 id 가 섞이면 찜 개수와 다릅니다)
        // 프론트에서 미리 계산하지 않고 이 자리에서 응답값으로 판단합니다.
        //
        // 여기서 isLoading 을 끄지 않고 그대로 둡니다. 아래 성공 경로에서만 끄기 때문에
        // 페이지를 당기는 동안 "찜한 교수가 없습니다" 가 잠깐 스치지 않습니다.
        const lastPage = Math.max(1, Math.ceil(data.total / data.pageSize))
        if (page > lastPage) {
          setPage(lastPage)
          return
        }

        // 응답을 가공하지 않고 그대로 씁니다. (계약 v6.3 API ①)
        setResults(data.results)
        setTotal(data.total)
        setIsLoading(false)
      } catch {
        if (ignore) return
        setHasError(true)
        setIsLoading(false)
      }
    }

    load()
    return () => {
      ignore = true
    }
  }, [favoriteIds, page])

  /**
   * 찜 취소 — 저장은 localStorage 담당 (계약: 백엔드 API 없음)
   *
   * removeFavorite 가 갱신된 id 배열을 돌려주므로, 그 값을 그대로 state 에 넣습니다.
   * 배열이 바뀌면 위 effect 가 다시 돌아 서버에서 이 페이지를 새로 받아옵니다.
   * (프론트가 목록에서 직접 빼거나 페이지 수를 다시 계산하지 않습니다)
   */
  function handleRemoveFavorite(id) {
    setFavoriteIds(removeFavorite(id))
  }

  // 자세히 보기 → 상세 페이지로 이동 (라우팅은 카드가 아니라 페이지가 담당)
  function handleDetail(id) {
    navigate(`/professors/${id}`)
  }

  // 종이비행기 클릭 → 이메일은 '상세 전용'이라 이 시점에 상세를 불러와 이메일을 얻는다.
  async function handleContact(id) {
    setContactNotice('') // 이전 안내 지우기
    try {
      const detail = await getProfessorById(id)

      if (!detail.email) {
        // 이메일은 계약상 카드에 없고 상세에만 있습니다.
        // 값이 없으면(null) 주소를 지어내지 않고 메일 창을 열지 않습니다. (계약 원칙 2)
        setContactNotice(
          '아직 이 교수님의 이메일 정보가 없어 메일 작성 창을 열 수 없습니다.',
        )
        return
      }

      const { subject, body } = buildContactDraft(detail)
      openMailto(toMailtoHref(detail.email, subject, body))
    } catch {
      setContactNotice('교수 정보를 불러오지 못해 메일 작성 창을 열 수 없습니다.')
    }
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
  // 검색 실패가 아니라 "아직 찜한 교수가 없음" 입니다. (계약 v6.3)
  if (total === 0) {
    return (
      <div className="favorites-empty">
        <p>아직 찜한 교수가 없습니다.</p>
        <button
          type="button"
          className="favorites-button"
          onClick={() => navigate('/')}
        >
          교수 검색하러 가기
          <ArrowRightIcon />
        </button>
      </div>
    )
  }

  /* ---------- 4) 정상 목록 ---------- */
  // 전체 페이지 수는 응답의 total 로만 계산합니다. (계약 v6.3 API ①)
  const totalPages = Math.max(1, Math.ceil(total / DEFAULT_PAGE_SIZE))

  // 화면에 보이는 범위 (예: 총 7명 중 6–7명). 값을 지어내지 않고 실제로 계산합니다.
  const rangeStart = (page - 1) * DEFAULT_PAGE_SIZE + 1
  const rangeEnd = (page - 1) * DEFAULT_PAGE_SIZE + results.length

  return (
    <div className="favorites-page">
      <div className="favorites-header">
        <h1 className="favorites-title">찜한 교수 목록</h1>
        <span className="favorites-count">총 {total}명</span>
      </div>

      {contactNotice && <p className="favorites-notice">{contactNotice}</p>}

      <ul className="favorites-list">
        {results.map((professor) => (
          <li key={professor.id}>
            <ProfessorCard
              professor={professor}
              variant="search" // 목업의 가로형 카드
              isFavorite={true} // 이 페이지의 카드는 전부 찜한 교수
              onToggleFavorite={handleRemoveFavorite} // 여기선 항상 "찜 취소"
              onContact={handleContact}
              onDetail={handleDetail}
            />
          </li>
        ))}
      </ul>

      {/* Pagination 컴포넌트 내부는 건드리지 않고, 감싸는 자리(여백·구분선)만
          검색 결과 페이지와 같은 값으로 잡습니다. */}
      <div className="favorites-pagination">
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      </div>

      <p className="favorites-range">
        총 {total}명 중 {rangeStart}–{rangeEnd}명 표시
      </p>
    </div>
  )
}

/**
 * [교수 검색하러 가기] 옆 화살표.
 *
 * 예전에는 '→' 문자를 그대로 썼는데, 같은 자리에 있는 메인 화면의
 * [전체 보기] 버튼은 인라인 SVG 를 쓰고 있어 두 버튼의 화살표 모양이 서로 달랐습니다.
 * HomePage 의 ArrowIcon 과 같은 path·규격(16px, stroke-width 1.8)을 씁니다.
 *
 * 옆에 안내 문구가 글자로 함께 있으므로 장식용(aria-hidden)입니다.
 */
function ArrowRightIcon() {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 12h14M12.5 6l6 6-6 6" />
    </svg>
  )
}

export default FavoritesPage
