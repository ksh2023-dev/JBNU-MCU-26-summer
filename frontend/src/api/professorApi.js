/**
 * professorApi.js — 교수 관련 API 함수 모음 (지금은 mock 단계)
 *
 * 「데이터 계약 문서 v6」의 2. API 엔드포인트와 1:1로 대응합니다.
 *
 *   getProfessors(query, options)   API ① 교수 검색·목록 조회
 *   getProfessorById(id)            API ② 교수 상세 조회
 *   getFeaturedProfessors()         API ③ 최근 연구 활동 교수 조회
 *
 *   getFavorites() / addFavorite(id) / removeFavorite(id)
 *     → 찜하기는 백엔드 API가 없습니다. 브라우저 localStorage 만 사용합니다.
 *
 * 연결 현황
 *   getFeaturedProfessors()  실제 백엔드 호출 (GET /api/professors/featured)
 *   getProfessors() · getProfessorById()  아직 data/professors.js 의 가짜 데이터
 *
 * 함수 이름·인자·돌려주는 값의 모양을 계약대로 맞춰 두었기 때문에,
 * "이 파일 안쪽만" fetch 호출로 바꾸면 되고
 * 이 함수를 쓰는 페이지 코드는 고치지 않아도 됩니다.
 * (getFeaturedProfessors 교체 때 HomePage.jsx 를 고치지 않은 것이 그 예입니다)
 *
 * 모든 함수는 async 입니다. 실제 통신처럼 await 로 쓰게 하기 위해서입니다.
 */

import { professors, MOCK_COLLECTED_AT } from '../data/professors.js'

/** 한 페이지에 보여줄 교수 수 (계약: 5명씩) */
export const DEFAULT_PAGE_SIZE = 5

/** 기본 관련도 임계값. 이 값보다 낮은 교수는 결과에서 제외 (계약 원칙 3) */
export const DEFAULT_MIN_SCORE = 0.3

/** 찜한 교수 id 배열을 저장할 localStorage 키 */
const FAVORITES_STORAGE_KEY = 'favoriteProfessorIds'

/** 실제 서버 통신처럼 보이도록 잠깐 기다리는 시간(ms) — 아직 mock 인 함수들만 사용 */
const MOCK_DELAY_MS = 300

/** 지정한 시간만큼 기다리는 도우미 함수 */
function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * 백엔드 API 공통 경로.
 * 개발 중에는 vite.config.js 의 proxy 가 이 경로를 http://localhost:8000 으로 넘깁니다.
 * 그래서 여기에는 호스트를 적지 않고 상대 경로만 둡니다.
 */
const API_BASE_PATH = '/api'

/**
 * 백엔드 JSON API 호출 공통 처리. (이 파일 안에서만 사용)
 *
 * fetch 는 404·500 같은 HTTP 오류에서도 예외를 던지지 않습니다.
 * 그래서 res.ok 를 직접 확인해 오류를 예외로 바꿔 줍니다.
 * 그래야 페이지의 try/catch 가 "불러오지 못했습니다" 화면으로 갈라질 수 있습니다.
 *
 * 오류에 status 를 붙여 둡니다. 계약 API ② 의 404(not_found) 처럼
 * 상태 코드로 갈라야 하는 경우에 쓰기 위해서입니다.
 *
 * @param {string} path    API_BASE_PATH 뒤에 붙는 경로 (예: '/professors/featured')
 * @param {object} [options] fetch 옵션 (method · headers · body 등)
 * @returns {Promise<object>} 응답 JSON
 * @throws {Error} HTTP 오류이면 예외. error.status 에 상태 코드가 담깁니다
 */
async function request(path, options) {
  const response = await fetch(`${API_BASE_PATH}${path}`, options)

  if (!response.ok) {
    const error = new Error(`request_failed_${response.status}`)
    error.status = response.status
    throw error
  }

  return response.json()
}

/**
 * 교수 카드 객체를 복사해서 돌려줍니다.
 * 화면 쪽에서 값을 바꿔도 원본 mock 데이터가 오염되지 않게 하기 위해서입니다.
 * (배열 필드도 새 배열로 복사)
 */
function cloneProfessor(professor) {
  return {
    ...professor,
    specialties: [...professor.specialties],
    keywords: [...professor.keywords],
  }
}

/**
 * [임시 구현 · UI 테스트 전용] 검색어가 교수 정보에 포함되는지 확인합니다.
 *
 * ※ 이것은 확정된 검색 규칙이 아닙니다.
 *   - query 가 실제로 어디까지 매칭되는지(교수명·전문분야·키워드·논문제목·초록)는
 *     아직 정해지지 않았습니다. (데이터 계약 문서 5장 2번 — 백엔드·검색엔진팀 확정 대기)
 *   - 아래에서 이름/소속/전문분야/키워드를 훑는 것은, 검색 화면이 동작하는지
 *     눈으로 확인하기 위해 임시로 정한 동작일 뿐입니다.
 *   - 실제 검색은 전부 백엔드가 수행하므로, 기준이 확정되면 이 함수는
 *     프론트에서 통째로 사라지고 fetch 결과를 그대로 받게 됩니다.
 *   - 따라서 페이지/컴포넌트 코드가 이 매칭 방식에 의존하면 안 됩니다.
 */
function matchesQuery(professor, query) {
  const keyword = query.trim().toLowerCase()
  if (keyword === '') return true // 검색어가 없으면 전체 대상

  const searchTargets = [
    professor.name,
    professor.department,
    ...professor.specialties,
    ...professor.keywords,
  ]

  return searchTargets.some((text) => text.toLowerCase().includes(keyword))
}

/**
 * API ① 교수 검색·목록 조회
 *
 * 언제 쓰나: 검색 버튼/Enter, 필터 선택, 페이지 번호 클릭
 *
 * 인자 모양은 계약 문서 API ①의 요청 JSON과 똑같이 맞췄습니다.
 * 그래서 나중에 fetch 로 바꿀 때 받은 인자를 그대로 body 로 보내면 됩니다.
 *
 *   getProfessors('심장', {
 *     filters: { professorType: ['임상의학'] },
 *     sort: 'relevance',
 *     minScore: 0.3,
 *     page: 1,
 *     pageSize: 5,
 *   })
 *
 * @param {string} query    검색어 (예: '심장'). 없으면 전체 조회
 * @param {object} options  검색 조건 (계약 요청 JSON에서 query 를 뺀 나머지)
 *   @param {object}   options.filters                필터 묶음
 *   @param {string[]} options.filters.professorType  교수 구분 필터. 빈 배열이면 전체
 *   @param {string[]|null} options.filters.favoriteIds  "찜한 교수만 보기" 필터.
 *     계약 API ①에 따라 세 가지 상태를 구분합니다.
 *       null / 없음        필터 꺼짐 — 찜과 무관하게 전체 검색
 *       []  (빈 배열)      필터는 켰지만 찜한 교수가 0명 → results: [], total: 0
 *       ['P-001', ...]     이 id 들과 교집합(AND)
 *     프론트가 현재 페이지의 5명을 다시 거르지 않고, 여기서 교집합을 건 뒤에
 *     페이지를 자릅니다. 그래야 total 이 찜 필터까지 반영된 값이 됩니다.
 *   @param {string}   options.sort                   정렬 방식. MVP는 'relevance'(관련도순)만
 *   @param {number}   options.minScore               이 값 미만인 교수는 제외
 *   @param {number}   options.page                   몇 번째 페이지인지 (1부터 시작)
 *   @param {number}   options.pageSize               한 페이지에 몇 명인지
 *
 * @returns {Promise<{results: object[], total: number, page: number,
 *                    pageSize: number, collectedAt: string}>}
 *   results     현재 페이지에 보여줄 교수 카드 배열
 *   total       조건에 맞는 전체 교수 수 (페이지 수 계산에 사용)
 *   collectedAt 데이터 수집 기준일
 */
export async function getProfessors(query = '', options = {}) {
  const {
    filters = {},
    sort = 'relevance',
    minScore = DEFAULT_MIN_SCORE,
    page = 1,
    pageSize = DEFAULT_PAGE_SIZE,
  } = options
  const { professorType = [], favoriteIds = null } = filters

  // 백엔드가 생기면 아래 requestBody 를 그대로 요청 본문으로 보내면 됩니다.
  // (계약 문서 API ①의 요청 모양과 동일)
  //
  // const requestBody = {
  //   query,
  //   filters: { professorType, favoriteIds },
  //   sort, minScore, page, pageSize,
  // }
  // const response = await fetch('/api/professors', {
  //   method: 'POST',
  //   headers: { 'Content-Type': 'application/json' },
  //   body: JSON.stringify(requestBody),
  // })
  // return response.json()

  await delay(MOCK_DELAY_MS)

  // 1) 관련도 임계값 미만 제외 (계약 원칙 3)
  // 2) 교수 구분 필터
  // 3) 검색어 매칭
  // 4) 찜 목록 교집합 ("찜한 교수만 보기")
  //    1~4는 모두 AND 조건이라 거는 순서는 결과에 영향을 주지 않습니다.
  //    중요한 것은 이 네 가지를 전부 건 "뒤에" 페이지를 자른다는 점입니다.
  //    (그래야 total 이 찜 필터까지 반영된 최종 수가 됩니다 — 계약 API ①)
  const filtered = professors
    .filter((professor) => professor.matchScore >= minScore)
    .filter(
      (professor) =>
        professorType.length === 0 ||
        professorType.includes(professor.professorType),
    )
    .filter((professor) => matchesQuery(professor, query))
    .filter(
      (professor) =>
        // 배열이 아니면(null·미전달) 필터가 꺼진 상태 → 전부 통과
        // 빈 배열이면 includes 가 항상 false → 전부 제외 → results: [], total: 0
        !Array.isArray(favoriteIds) || favoriteIds.includes(professor.id),
    )

  // 5) 정렬 — MVP는 관련도순(matchScore 높은 순)만 사용
  const sorted = [...filtered]
  if (sort === 'relevance') {
    sorted.sort((a, b) => b.matchScore - a.matchScore)
  }

  // 6) 페이지 자르기 — 예: page 2, pageSize 5 → 6번째부터 10번째까지
  const startIndex = (page - 1) * pageSize
  const pageItems = sorted.slice(startIndex, startIndex + pageSize)

  return {
    results: pageItems.map(cloneProfessor),
    total: sorted.length, // 페이지를 자르기 "전" 전체 개수
    page,
    pageSize,
    collectedAt: MOCK_COLLECTED_AT,
  }
}

/**
 * API ② 교수 상세 조회
 *
 * 언제 쓰나: 카드의 [자세히 보기] 클릭
 *
 * 주의: mock 데이터에는 카드용 정보만 있습니다.
 * 연구실명 · 이메일 · 홈페이지 · 논문은 실제 값을 지어내면 안 되므로
 * 계약 원칙 2에 따라 null / 빈 배열로 돌려줍니다.
 * (화면에는 "정보 없음", "등록된 대표 논문 없음"으로 표시)
 * 실제 값은 백엔드가 완성되면 채워집니다.
 *
 * @param {string} id 교수 id (예: 'P-001')
 * @returns {Promise<object>} 교수 상세 객체
 * @throws {Error} 없는 id 이면 에러. error.status = 404, error.code = 'not_found'
 */
export async function getProfessorById(id) {
  await delay(MOCK_DELAY_MS)

  const found = professors.find((professor) => professor.id === id)

  if (!found) {
    // 실제 백엔드는 HTTP 404 + { "error": "not_found" } 로 응답합니다.
    const error = new Error('not_found')
    error.status = 404
    error.code = 'not_found'
    throw error
  }

  const card = cloneProfessor(found)

  return {
    id: card.id,
    name: card.name,
    profileImageUrl: card.profileImageUrl,
    professorType: card.professorType,
    department: card.department,
    labName: null, // 값 없음 → null
    specialties: card.specialties,
    keywords: card.keywords, // 상세에서는 전체 노출
    email: null, // 값 없음 → null
    homepageUrl: null, // 값 없음 → null (화면에서는 링크 숨김)
    papers: [], // pmid 없는 논문은 넣지 않으므로 빈 배열
  }
}

/**
 * API ③ 최근 연구 활동 교수 조회 — 실제 백엔드 연결 완료
 *
 * 언제 쓰나: 메인(교수 검색) 페이지에 들어왔을 때
 *
 * 요청: GET /api/professors/featured
 *
 * 선정은 전부 백엔드가 수행합니다 (계약 v6.2 API ③).
 *   - 교수별 '가장 최근 논문의 발행일' 최신순 상위 3명
 *   - 그 판정에 쓰이는 latestPaper 는 백엔드 내부 필드라 응답에 오지 않습니다.
 *     프론트는 이 필드를 받지도, 알 필요도 없습니다.
 *   - 유효 후보가 3명 미만이면 있는 만큼만 옵니다. 없는 교수를 채우지 않습니다.
 *
 * 그래서 이 함수는 응답을 가공하지 않고 그대로 돌려줍니다.
 * 프론트에서 다시 정렬하거나 slice(0, 3) 하지 않습니다.
 *
 * featured 카드의 matchScore 는 검색어가 없으므로 항상 null 입니다.
 * 이는 누락이 아니라 정상 상태이며(계약 1-1 · 원칙 2), 카드 UI 가 점수를
 * 표시하지 않으므로 렌더링에도 영향이 없습니다.
 *
 * @returns {Promise<{results: object[], collectedAt: string}>}
 *   results     교수 카드 배열. 계약 v6.2 기준 3명 (유효 후보가 적으면 그보다 적을 수 있음)
 *   collectedAt 데이터 수집 기준일 ('YYYY-MM-DD')
 * @throws {Error} HTTP 오류·네트워크 오류. 호출하는 페이지가 오류 화면으로 갈라집니다
 */
export async function getFeaturedProfessors() {
  return request('/professors/featured')
}

/* ------------------------------------------------------------------
 * 찜하기 — 백엔드 API 없음. 브라우저 localStorage 만 사용합니다.
 * 저장 형태: 찜한 교수 id 배열 (예: ['P-001', 'P-003'])
 * 아래 3개 함수는 백엔드가 생겨도 fetch 로 바뀌지 않고 그대로 유지됩니다.
 * ------------------------------------------------------------------ */

/**
 * 찜한 교수 id 목록을 가져옵니다.
 * 저장된 값이 없거나 깨져 있으면 빈 배열을 돌려줍니다.
 *
 * @returns {string[]} 예: ['P-001', 'P-003']
 */
export function getFavorites() {
  try {
    const saved = localStorage.getItem(FAVORITES_STORAGE_KEY)
    if (!saved) return []

    const parsed = JSON.parse(saved)
    // 저장된 값이 배열이 아니면(예: 다른 코드가 잘못 저장) 빈 배열로 처리
    return Array.isArray(parsed) ? parsed : []
  } catch {
    // localStorage 를 쓸 수 없거나 JSON 형식이 깨진 경우
    return []
  }
}

/**
 * 교수를 찜 목록에 추가합니다. 이미 있으면 그대로 둡니다.
 *
 * @param {string} id 교수 id
 * @returns {string[]} 변경된 찜 목록
 */
export function addFavorite(id) {
  const favorites = getFavorites()
  if (favorites.includes(id)) return favorites

  const updated = [...favorites, id]
  saveFavorites(updated)
  return updated
}

/**
 * 교수를 찜 목록에서 제거합니다.
 *
 * @param {string} id 교수 id
 * @returns {string[]} 변경된 찜 목록
 */
export function removeFavorite(id) {
  const updated = getFavorites().filter((favoriteId) => favoriteId !== id)
  saveFavorites(updated)
  return updated
}

/**
 * 찜한 교수들의 카드 객체를 가져옵니다.
 * getFavorites()로 얻은 id 목록을 카드 데이터로 바꿔 돌려줍니다.
 * 지금은 mock 배열에서 찾고, 백엔드가 생기면 이 안쪽만 fetch로 바꾸면 됩니다.
 * (그래서 지금부터 async 입니다)
 *
 * @returns {Promise<{results: object[], total: number, collectedAt: string}>}
 */
export async function getFavoriteProfessors() {
  await delay(MOCK_DELAY_MS)

  const favoriteIds = getFavorites() // localStorage의 id 배열 (sync)

  const results = favoriteIds
    .map((id) => professors.find((professor) => professor.id === id))
    .filter(Boolean) // 데이터에서 사라진 교수는 조용히 제외 (지어내지 않음)
    .map(cloneProfessor) // 원본 mock 오염 방지용 복사

  return {
    results,
    total: results.length,
    collectedAt: MOCK_COLLECTED_AT,
  }
}

/** 찜 목록을 localStorage 에 저장합니다. (이 파일 안에서만 사용) */
function saveFavorites(ids) {
  try {
    localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(ids))
  } catch {
    // 저장 공간이 꽉 찼거나 브라우저가 막은 경우 — 화면이 멈추지 않도록 무시
  }
}
