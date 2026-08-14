/**
 * professorApi.js — 교수 관련 API 함수 모음 (API ①·②·③ 백엔드 연결 완료)
 *
 * 「데이터 계약 문서 v6.2」의 2. API 엔드포인트와 1:1로 대응합니다.
 *
 *   getProfessors(query, options)   API ① 교수 검색·목록 조회
 *   getProfessorById(id)            API ② 교수 상세 조회
 *   getFeaturedProfessors()         API ③ 최근 연구 활동 교수 조회
 *
 *   getFavorites() / addFavorite(id) / removeFavorite(id)
 *     → 찜하기는 백엔드 API가 없습니다. 브라우저 localStorage 만 사용합니다.
 *
 * 연결 현황
 *   getProfessors()          실제 백엔드 호출 (POST /api/professors/search)
 *   getProfessorById()       실제 백엔드 호출 (GET /api/professors/{id})
 *   getFeaturedProfessors()  실제 백엔드 호출 (GET /api/professors/featured)
 *   getFavoriteProfessors()  아직 data/professors.js 의 가짜 데이터
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

/**
 * 기본 관련도 임계값. 이 값보다 낮은 교수는 백엔드가 결과에서 제외합니다 (계약 원칙 3).
 * 계약 v6.2 기준 개발용 임시값이며, 최종 threshold 는 matchScore 산식과 함께 정해집니다.
 *
 * 빈 검색어(전체 조회)에서는 백엔드가 이 값을 적용하지 않습니다 (v6.2 browse 정책).
 * 그때도 프론트는 값을 그대로 실어 보내면 되고, 백엔드가 무시합니다.
 */
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
 * API ① 교수 검색·목록 조회 — 실제 백엔드 연결 완료
 *
 * 언제 쓰나: 검색 버튼/Enter, 필터 선택, 페이지 번호 클릭
 *
 * 요청: POST /api/professors/search (계약 v6.2 확정 경로)
 *       받은 인자를 계약 API ①의 요청 JSON 모양 그대로 본문에 담아 보냅니다.
 *
 *   getProfessors('심장', {
 *     filters: { professorType: ['임상의학'] },
 *     sort: 'relevance',
 *     minScore: 0.3,
 *     page: 1,
 *     pageSize: 5,
 *   })
 *
 * 검색·점수·정렬·페이지네이션은 전부 백엔드가 수행합니다 (계약 v6.2 API ①).
 *   - query 는 교수명·keywords·specialties·논문 제목·논문 초록·소속에서 부분일치
 *   - query 있음: matchScore 내림차순, 동점이면 이름 오름차순, minScore 미만 제외
 *   - query 없음: 전체 목록 조회(browse) — matchScore 는 null, minScore 미적용,
 *     이름 오름차순. 이때 matchScore: null 은 누락이 아니라 정상입니다 (원칙 2)
 *   - 찜 필터·교수 구분 필터를 모두 건 "뒤에" 페이지를 자르고, total 도 그 최종 수입니다
 *
 * 그래서 이 함수는 응답을 가공하지 않고 그대로 돌려줍니다.
 * 프론트에서 다시 거르거나 정렬하거나 자르지 않습니다.
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
 *     프론트가 현재 페이지의 5명을 다시 거르지 않고, 백엔드가 교집합을 건 뒤에
 *     페이지를 자릅니다. 그래야 total 이 찜 필터까지 반영된 값이 됩니다.
 *   @param {string}   options.sort                   정렬 방식. MVP는 'relevance'(관련도순)만
 *   @param {number}   options.minScore               이 값 미만인 교수는 제외
 *   @param {number}   options.page                   몇 번째 페이지인지 (1부터 시작)
 *   @param {number}   options.pageSize               한 페이지에 몇 명인지
 *
 * @returns {Promise<{results: object[], total: number, page: number,
 *                    pageSize: number, collectedAt: string}>}
 *   results     현재 페이지에 보여줄 교수 카드 배열
 *   total       조건에 맞는 전체 교수 수 (페이지 수 계산에 사용). 페이지를 자르기 "전" 값
 *   page        요청한 page 를 그대로 되돌려줍니다
 *   pageSize    요청한 pageSize 를 그대로 되돌려줍니다
 *   collectedAt 데이터 수집 기준일 ('YYYY-MM-DD')
 * @throws {Error} HTTP 오류·네트워크 오류. 호출하는 페이지가 오류 화면으로 갈라집니다
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

  // 계약 API ①의 요청 JSON 과 같은 모양으로 조립합니다.
  //
  // favoriteIds 는 null 과 [] 를 반드시 구분해 보냅니다. JSON.stringify 는 null 을
  // 그대로 남기고, 백엔드는 null·없음을 "찜 필터 꺼짐"으로 받습니다.
  //   null      필터 꺼짐 — 찜과 무관하게 전체 검색
  //   []        필터는 켰지만 찜한 교수가 0명 → results: [], total: 0
  //   [id...]   이 id 들과 교집합(AND)
  const requestBody = {
    query,
    filters: { professorType, favoriteIds },
    sort,
    minScore,
    page,
    pageSize,
  }

  return request('/professors/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  })
}

/**
 * API ② 교수 상세 조회 — 실제 백엔드 연결 완료
 *
 * 언제 쓰나: 카드의 [자세히 보기] 클릭
 *
 * 요청: GET /api/professors/{id} (계약 v6.2 API ②, 예: /api/professors/P-012)
 *
 * 응답은 계약 1-2 교수 상세 객체입니다. 이 함수는 가공하지 않고 그대로 돌려줍니다.
 *   - labName · email · homepageUrl 은 값이 없으면 null 로 옵니다 (계약 원칙 2).
 *     "정보 없음" 표시와 홈페이지 링크 숨김은 화면 쪽 몫입니다 (계약 4장).
 *   - keywords 는 상세에서 전체가 옵니다. 프론트가 개수를 자르지 않습니다.
 *   - papers 는 pmid 가 있는 논문만 오고, 없으면 빈 배열 [] 입니다 (계약 원칙 1).
 *     PubMed 주소는 pmid 로 화면이 직접 만듭니다 (계약 1-2).
 *
 * @param {string} id 교수 id (예: 'P-001')
 * @returns {Promise<object>} 계약 1-2 교수 상세 객체
 * @throws {Error} HTTP 오류·네트워크 오류.
 *   없는 id 는 계약대로 HTTP 404 + { "error": "not_found" } 로 오고,
 *   request() 가 error.status = 404 를 붙여 던집니다.
 *   호출하는 페이지는 이 값으로 "미발견"과 "불러오기 실패"를 갈라냅니다.
 */
export async function getProfessorById(id) {
  return request(`/professors/${encodeURIComponent(id)}`)
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
