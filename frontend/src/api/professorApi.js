/**
 * 교수 데이터 접근 창구.
 *
 * 페이지(pages/)는 data/professors.js 를 직접 import 하지 않고 이 파일의 함수만 씁니다.
 * 그래야 나중에 백엔드가 완성됐을 때 "이 파일 안쪽만" fetch로 바꾸면 되고,
 * 페이지 코드는 한 줄도 고칠 필요가 없습니다.
 *
 * 데이터 모양은 "데이터 계약 문서 v4" 를 그대로 따릅니다.
 *
 * 지금은 가짜 데이터를 쓰지만 함수를 전부 async 로 만들어 둡니다.
 * (진짜 fetch도 async 이기 때문에, 미리 async로 맞춰두면 페이지 코드를 안 고쳐도 됩니다)
 */

import professors, { COLLECTED_AT } from '../data/professors.js'

/* ------------------------------------------------------------------
 * 내부 도우미 (이 파일 안에서만 사용)
 * ------------------------------------------------------------------ */

// 상세 객체에서 "교수 카드(1-1)"에 해당하는 칸만 골라낸다.
// 백엔드도 목록 응답에는 이 칸들만 보내주기로 했으므로, 미리 똑같이 맞춰둔다.
function toCard(professor) {
  return {
    id: professor.id,
    name: professor.name,
    profileImageUrl: professor.profileImageUrl,
    professorType: professor.professorType,
    department: professor.department,
    specialties: professor.specialties,
    keywords: professor.keywords,
    matchScore: professor.matchScore,
  }
}

// 검색어가 교수 정보 어딘가에 들어있는지 확인한다.
// (실제 검색 범위는 백엔드/검색엔진팀이 확정할 항목이라, 지금은 넉넉하게 맞춰본다)
function matchesQuery(professor, query) {
  if (!query) return true // 검색어가 비어 있으면 전부 통과

  const keyword = query.trim().toLowerCase()
  const haystack = [
    professor.name,
    professor.department,
    ...professor.specialties,
    ...professor.keywords,
  ]
    .join(' ')
    .toLowerCase()

  return haystack.includes(keyword)
}

/* ------------------------------------------------------------------
 * API ① 교수 검색·목록 조회
 * ------------------------------------------------------------------ */

/**
 * getProfessors(query, filters)
 *
 * @param {string} query    검색어 (예: "심장")
 * @param {object} filters  { professorType: [], sort, minScore, page, pageSize }
 * @returns {Promise<{results, total, page, pageSize, collectedAt}>}
 *
 * 나중에 백엔드가 생기면 이 함수 안쪽만 아래처럼 바꾼다:
 *   const res = await fetch('/api/professors', { method: 'POST', ... })
 *   return await res.json()
 */
export async function getProfessors(query = '', filters = {}) {
  // 값을 안 넘겨도 동작하도록 기본값을 정해둔다
  const {
    professorType = [], // 빈 배열이면 "전체"
    sort = 'relevance', // MVP는 관련도순만 사용
    minScore = 0.3, // 이 점수 미만인 교수는 결과에서 제외 (계약 원칙 3)
    page = 1,
    pageSize = 5, // 한 페이지에 5명
  } = filters

  // 1) 검색어로 거르기
  let list = professors.filter((professor) => matchesQuery(professor, query))

  // 2) 교수 구분 필터로 거르기 (선택된 게 있을 때만)
  if (professorType.length > 0) {
    list = list.filter((professor) =>
      professorType.includes(professor.professorType),
    )
  }

  // 3) 점수가 낮은 교수는 제외 (억지로 결과를 채우지 않는다)
  list = list.filter((professor) => professor.matchScore >= minScore)

  // 4) 정렬 - 관련도순(점수 높은 순)
  if (sort === 'relevance') {
    // slice()로 복사한 뒤 정렬. 원본 배열을 건드리지 않기 위해서다.
    list = list.slice().sort((a, b) => b.matchScore - a.matchScore)
  }

  // 5) 페이지 자르기. total 은 "자르기 전" 전체 개수여야 페이지 수 계산이 맞는다.
  const total = list.length
  const start = (page - 1) * pageSize
  const pageItems = list.slice(start, start + pageSize)

  return {
    results: pageItems.map(toCard),
    total,
    page,
    pageSize,
    collectedAt: COLLECTED_AT,
  }
}

/* ------------------------------------------------------------------
 * API ② 교수 상세 조회
 * ------------------------------------------------------------------ */

/**
 * getProfessorById(id)
 *
 * @param {string} id  예: "P-001"
 * @returns {Promise<object|null>}  없는 id 면 null
 *
 * 백엔드 연결 시: GET /api/professors/{id}
 * 없는 id 는 HTTP 404 + { "error": "not_found" } 로 오므로, 그때도 null 을 돌려주면 된다.
 */
export async function getProfessorById(id) {
  const found = professors.find((professor) => professor.id === id)

  // find 는 못 찾으면 undefined 를 준다. 페이지에서 다루기 쉽도록 null 로 통일한다.
  return found ?? null
}

/* ------------------------------------------------------------------
 * API ③ 우수 교수 조회
 * ------------------------------------------------------------------ */

/**
 * getPopularProfessors()
 * 메인(교수 검색) 페이지에 들어올 때 보여줄 우수 교수 3~5명.
 *
 * 백엔드 연결 시: GET /api/professors/featured
 * (선정 기준은 데이터팀과 협의 중이라, 지금은 점수 높은 순 3명으로 대신한다)
 */
export async function getPopularProfessors() {
  const top3 = professors
    .slice()
    .sort((a, b) => b.matchScore - a.matchScore)
    .slice(0, 3)

  return {
    results: top3.map(toCard),
    collectedAt: COLLECTED_AT,
  }
}

/* ------------------------------------------------------------------
 * 찜하기 - 백엔드 API 없음. 브라우저 localStorage 에만 저장한다.
 *
 * 로그인을 만들지 않기로 해서, 찜 목록은 그 브라우저에만 남습니다.
 * (다른 기기·다른 브라우저에서는 안 보임)
 *
 * 저장 형태: 교수 id 배열  예) ["P-001", "P-003"]
 *
 * 아래 3개 함수는 백엔드가 생겨도 fetch 로 바뀌지 않고 그대로 유지됩니다.
 * ------------------------------------------------------------------ */

// localStorage 에 저장할 때 쓸 이름표
const FAVORITES_KEY = 'favoriteProfessorIds'

/**
 * getFavorites()
 * @returns {string[]} 찜한 교수 id 배열. 하나도 없으면 빈 배열 []
 */
export function getFavorites() {
  // localStorage 에는 문자열만 저장되므로, 꺼낸 뒤 JSON.parse 로 배열로 되돌린다.
  const saved = localStorage.getItem(FAVORITES_KEY)
  if (!saved) return []

  try {
    const parsed = JSON.parse(saved)
    // 저장된 값이 이상하게 망가져 있어도 화면이 깨지지 않도록 확인한다
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/**
 * addFavorite(id)  찜하기
 * @returns {string[]} 바뀐 뒤의 찜 목록
 */
export function addFavorite(id) {
  const favorites = getFavorites()

  // 이미 찜한 교수면 중복으로 넣지 않는다
  if (favorites.includes(id)) return favorites

  const next = [...favorites, id]
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(next))
  return next
}

/**
 * removeFavorite(id)  찜 취소
 * @returns {string[]} 바뀐 뒤의 찜 목록
 */
export function removeFavorite(id) {
  const next = getFavorites().filter((savedId) => savedId !== id)
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(next))
  return next
}
