/**
 * SearchResultPage.jsx — 검색 결과 페이지
 *
 * 「데이터 계약 문서 v6.1」 6장 화면 매핑의 "2. 검색 결과" 화면입니다.
 * API ① getProfessors(query, options) 하나만 사용합니다.
 *
 * 이 페이지가 "하지 않는" 일 (역할을 좁게 유지하기 위한 약속)
 *   - Header / Footer 를 그리지 않습니다. App.jsx 가 이미 상위에서 렌더링합니다.
 *   - 검색창·필터·교수 카드·페이지네이션을 새로 만들지 않고 공통 컴포넌트를 그대로 씁니다.
 *   - matchScore 를 계산하거나 결과를 다시 정렬하지 않습니다.
 *     계산 기준은 v6.1 5장 1번에서 아직 미확정이고, 정렬은 전부 백엔드 몫입니다.
 *   - 응답으로 받은 현재 페이지의 교수들을 프론트에서 다시 걸러내지 않습니다.
 *     특히 "찜한 교수만 보기"는 filters.favoriteIds 로 검색 단계에서 교집합을 겁니다.
 *     (v6.1 API ① — 5명을 받아 프론트가 다시 거르면 total 과 페이지 수가 깨집니다)
 *   - 화면에 보일 값을 지어내지 않습니다. 결과 수·카드·페이지 수는 모두 응답값에서 옵니다.
 *
 * URL 규칙 (메인 페이지와 공유)
 *   - 검색어 있음: /search?query=심장
 *   - 검색어 없음: /search   (계약상 "검색어 없음 = 전체 조회")
 *   - URL 에 담는 것은 query 하나뿐입니다.
 *     교수 구분·찜 필터·페이지는 이 컴포넌트의 state 로만 관리합니다.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  getProfessors,
  getFavorites,
  addFavorite,
  removeFavorite,
  DEFAULT_PAGE_SIZE,
  DEFAULT_MIN_SCORE,
} from '../api/professorApi.js'
import SearchBar from '../components/SearchBar.jsx'
import FilterPanel from '../components/FilterPanel.jsx'
import ProfessorCard from '../components/ProfessorCard.jsx'
import Pagination from '../components/Pagenation.jsx'
import '../styles/SearchResultPage.css'

/**
 * 이 화면의 카드에 보여줄 연구 키워드 개수.
 *
 * 계약 1-1: "keywords 는 전체 배열을 보내고, 카드에는 프론트가 앞 3~4개만 노출"
 * 그중 이 화면은 3개로 통일합니다.
 *
 * ※ 프론트가 키워드의 중요도·관련도를 계산해서 고르는 것이 아닙니다.
 *   API 가 돌려준 배열의 순서를 그대로 두고 "표시 개수"만 앞에서 자릅니다.
 *   keywords 배열의 우선순위·정렬 기준은 추후 백엔드·검색엔진팀과 별도로 합의합니다.
 */
const MAX_VISIBLE_KEYWORDS = 3

/** MVP 정렬은 관련도순 하나뿐입니다. (계약 API ① — sort 는 'relevance' 고정) */
const SORT = 'relevance'

/**
 * 카드에 넘길 교수 객체를 만듭니다.
 *
 * 원본 객체를 건드리지 않고 복사본의 keywords 만 앞 3개로 줄입니다.
 * (원본을 잘라 버리면 같은 데이터를 쓰는 다른 화면까지 영향을 받습니다)
 * specialties 는 그대로 둡니다 — 전문 분야는 개수 제한 대상이 아닙니다.
 *
 * @param {object} professor 계약 1-1 교수 카드 객체
 * @returns {object} keywords 만 앞 3개로 줄인 복사본
 */
function withVisibleKeywords(professor) {
  // 값이 배열이 아니면(예상 밖의 응답) 손대지 않고 그대로 넘깁니다.
  // 없는 값을 만들어 채우지 않기 위해서입니다. (계약 원칙 2)
  if (!Array.isArray(professor.keywords)) return professor

  return {
    ...professor,
    keywords: professor.keywords.slice(0, MAX_VISIBLE_KEYWORDS),
  }
}

function SearchResultPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  /**
   * 검색어는 URL 에서 읽습니다. (state 로 따로 두지 않습니다)
   * 메인 페이지에서 /search?query=... 로 넘어오는 규칙을 그대로 따르고,
   * 뒤로가기·앞으로가기로 주소가 바뀌면 이 값도 함께 바뀝니다.
   */
  const query = searchParams.get('query') ?? ''

  // ---- 검색 조건 (URL 에 넣지 않고 이 컴포넌트 안에서만 관리) ----
  const [professorTypes, setProfessorTypes] = useState([]) // 빈 배열 = 전체
  const [favoritesOnly, setFavoritesOnly] = useState(false)

  /**
   * 페이지 번호는 "어느 검색어 기준의 몇 페이지인지"를 함께 담아 둡니다.
   *
   * 이렇게 두면 URL 의 검색어가 바뀌는 순간(검색 버튼은 물론 뒤로가기·앞으로가기까지)
   * 아래 page 가 저절로 1이 됩니다. 렌더 중이나 effect 안에서 setState 로 뒤늦게
   * 되돌릴 필요가 없고, 옛 페이지 번호로 요청이 한 번 더 나가는 일도 없습니다.
   */
  const [pageState, setPageState] = useState({ query, page: 1 })

  // 저장해 둔 검색어와 지금 URL 의 검색어가 다르면 그 페이지 번호는 이미 지난 것입니다.
  const page = pageState.query === query ? pageState.page : 1

  /** 현재 검색어를 기준으로 페이지를 옮깁니다. */
  function goToPage(nextPage) {
    setPageState({ query, page: nextPage })
  }

  /**
   * 검색 요청의 filters.favoriteIds 로 보낼 값. (계약 API ①)
   *   null    필터 꺼짐 — 찜과 무관하게 전체 검색
   *   []      필터는 켰지만 찜한 교수가 0명 → results: [], total: 0
   *   [id...] 이 id 들과 교집합
   *
   * 아래 favoriteIds(하트 표시용)와 일부러 나눠 두었습니다.
   * 필터가 꺼져 있을 때 찜 버튼을 눌러도 이 값은 그대로여서, 하트만 바뀌고
   * 불필요한 재조회가 일어나지 않습니다.
   */
  const [requestFavoriteIds, setRequestFavoriteIds] = useState(null)

  /**
   * localStorage 의 찜 id 목록. 카드의 하트를 채울지 판단하는 데만 씁니다.
   * (계약: 찜 여부는 백엔드 응답이 아니라 id 를 localStorage 와 대조해 프론트가 판단)
   */
  const [favoriteIds, setFavoriteIds] = useState(() => getFavorites())

  // ---- 검색 결과 ----
  const [results, setResults] = useState([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false)

  /**
   * 검색 조건이 바뀔 때마다 API ① 을 호출합니다.
   * (검색어 · 교수 구분 · 찜 필터 · 페이지 — 계약 API ①의 트리거와 같습니다)
   *
   * page 는 위에서 검색어와 함께 계산해 둔 값이라, 검색어가 바뀌는 렌더에서 이미 1입니다.
   * 그래서 조건 하나가 바뀔 때 요청도 한 번만 나갑니다.
   */
  useEffect(() => {
    let ignore = false // 응답이 늦게 와서 조건이 이미 바뀐 경우, 옛 결과 무시용

    async function load() {
      setIsLoading(true)
      setHasError(false)
      try {
        // 인자 모양은 계약 API ①의 요청 JSON 과 같습니다.
        const data = await getProfessors(query, {
          filters: {
            professorType: professorTypes,
            favoriteIds: requestFavoriteIds,
          },
          sort: SORT,
          minScore: DEFAULT_MIN_SCORE,
          page,
          pageSize: DEFAULT_PAGE_SIZE,
        })
        if (ignore) return

        // 찜을 취소해 결과가 줄면서 지금 보던 페이지가 사라질 수 있습니다.
        // 그때는 존재하는 마지막 페이지로 당겨 다시 조회합니다.
        // (isLoading 을 켜 둔 채로 두어 "결과 없음"이 잠깐 스치지 않게 합니다)
        const lastPage = Math.max(1, Math.ceil(data.total / data.pageSize))
        if (page > lastPage) {
          setPageState({ query, page: lastPage })
          return
        }

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
  }, [query, professorTypes, requestFavoriteIds, page])

  /**
   * 검색 실행 — SearchBar 가 공백을 지운 검색어를 넘겨줍니다.
   * 검색어는 URL 로 관리하므로 주소를 바꾸고, 조회는 위 effect 가 이어서 합니다.
   */
  function handleSearch(nextQuery) {
    // 새 검색은 항상 1페이지부터. (새 검색어 기준의 1페이지로 명시해 둡니다)
    setPageState({ query: nextQuery, page: 1 })

    if (nextQuery === '') {
      setSearchParams({}) // /search — 계약상 "검색어 없음 = 전체 조회"
      return
    }
    setSearchParams({ query: nextQuery }) // /search?query=...
  }

  /** 교수 구분 체크박스 변경 — 조건이 바뀌었으므로 1페이지부터 다시 봅니다. */
  function handleProfessorTypesChange(nextTypes) {
    setProfessorTypes(nextTypes)
    goToPage(1)
  }

  /** "찜한 교수만 보기" 변경 — 켤 때 지금 찜 목록을 요청값으로 싣습니다. */
  function handleFavoritesOnlyChange(nextChecked) {
    setFavoritesOnly(nextChecked)
    // 켰는데 찜한 교수가 0명이면 빈 배열([])이 그대로 실려 total 0 이 됩니다. (계약 API ①)
    setRequestFavoriteIds(nextChecked ? favoriteIds : null)
    goToPage(1)
  }

  /**
   * 필터 초기화 (v6.1 3장)
   * 검색어와 URL 의 query 는 그대로 두고, 필터와 페이지만 기본값으로 되돌립니다.
   * 정렬은 relevance 고정이라 되돌릴 것이 없습니다.
   */
  function handleReset() {
    // 이미 빈 배열이면 같은 배열을 그대로 둡니다.
    // 새 배열을 넣으면 조건이 그대로인데도 재조회가 일어나기 때문입니다.
    setProfessorTypes((prev) => (prev.length === 0 ? prev : []))
    setFavoritesOnly(false)
    setRequestFavoriteIds(null)
    goToPage(1)
  }

  /** 찜하기 / 찜 취소 — 저장은 localStorage 담당 (계약: 백엔드 API 없음) */
  function handleToggleFavorite(id) {
    const nextFavoriteIds = favoriteIds.includes(id)
      ? removeFavorite(id)
      : addFavorite(id)

    setFavoriteIds(nextFavoriteIds) // 하트 표시는 즉시 갱신

    // "찜한 교수만 보기"가 켜져 있으면 교집합 대상이 달라졌으므로 다시 조회합니다.
    // 꺼져 있으면 검색 결과가 달라질 이유가 없어 재조회하지 않습니다.
    if (favoritesOnly) setRequestFavoriteIds(nextFavoriteIds)
  }

  /** 자세히 보기 → 상세 페이지로 이동 (라우팅은 카드가 아니라 페이지가 담당) */
  function handleDetail(id) {
    navigate(`/professors/${id}`)
  }

  // 전체 페이지 수는 응답의 total 로만 계산합니다. (계약 API ①)
  const totalPages = Math.max(1, Math.ceil(total / DEFAULT_PAGE_SIZE))

  // 화면에 보이는 범위 (예: 총 7명 중 6–7명). 값을 지어내지 않고 실제로 계산합니다.
  const rangeStart = (page - 1) * DEFAULT_PAGE_SIZE + 1
  const rangeEnd = (page - 1) * DEFAULT_PAGE_SIZE + results.length

  return (
    <div className="search-page">
      {/* key: 뒤로가기 등으로 URL 의 검색어가 바뀌면 입력창도 그 값으로 다시 그립니다.
          (SearchBar 는 initialValue 를 처음 한 번만 읽습니다) */}
      <SearchBar
        key={query}
        initialValue={query}
        onSearch={handleSearch}
        placeholder="교수명, 연구 분야, 관심 키워드로 검색해보세요"
      />

      <div className="search-page__layout">
        <FilterPanel
          selectedProfessorTypes={professorTypes}
          onProfessorTypesChange={handleProfessorTypesChange}
          favoritesOnly={favoritesOnly}
          onFavoritesOnlyChange={handleFavoritesOnlyChange}
          onReset={handleReset}
        />

        <section className="search-page__results">
          <div className="search-page__summary">
            {/* 결과 수는 응답이 온 뒤에만 적습니다. 오기 전에 0명이라고 단정하지 않습니다. */}
            <p className="search-page__count">
              {isLoading || hasError ? '검색 결과' : `검색 결과: 총 ${total}명`}
            </p>
            {/* MVP 정렬은 관련도순 하나뿐이라 고르는 UI 를 두지 않습니다. */}
            <p className="search-page__sort">정렬: 관련도순</p>
          </div>

          {/* 불러오는 중 / 실패 / 결과 없음 / 정상 */}
          {isLoading ? (
            <p className="search-page__message">불러오는 중입니다...</p>
          ) : hasError ? (
            <p className="search-page__message">
              검색 결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
            </p>
          ) : results.length === 0 ? (
            // 계약 4장의 문구를 그대로 사용합니다.
            <p className="search-page__message">검색 결과가 없습니다 (정보 없음)</p>
          ) : (
            <>
              <ul className="search-page__list">
                {results.map((professor) => (
                  <li key={professor.id}>
                    <ProfessorCard
                      professor={withVisibleKeywords(professor)}
                      variant="search"
                      // 찜 여부는 응답이 아니라 localStorage 와 대조해 판단합니다.
                      isFavorite={favoriteIds.includes(professor.id)}
                      onToggleFavorite={handleToggleFavorite}
                      onDetail={handleDetail}
                    />
                  </li>
                ))}
              </ul>

              <Pagination
                currentPage={page}
                totalPages={totalPages}
                onPageChange={goToPage}
              />

              <p className="search-page__range">
                총 {total}명 중 {rangeStart}–{rangeEnd}명 표시
              </p>
            </>
          )}
        </section>
      </div>
    </div>
  )
}

export default SearchResultPage
