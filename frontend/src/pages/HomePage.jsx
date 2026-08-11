/**
 * HomePage.jsx — 메인(교수 검색) 페이지
 *
 * 「데이터 계약 문서 v6」 6장 화면 매핑의 "1. 메인(교수 검색)" 화면입니다.
 * 세 부분으로 이루어집니다.
 *
 *   ① 검색 영역          — 기존 SearchBar 로 검색어를 받아 검색 결과 페이지로 넘긴다
 *   ② 최근 연구 활동 교수  — API ③ getFeaturedProfessors() 의 results 를 기존 ProfessorCard 로 표시
 *   ③ 기능 안내          — API·데이터를 쓰지 않는 정적 안내 영역
 *
 * 이 페이지가 "하지 않는" 일 (역할을 좁게 유지하기 위한 약속)
 *   - Header / Footer 를 그리지 않습니다. App.jsx 가 이미 상위에서 렌더링합니다.
 *   - 검색창·교수 카드를 새로 만들지 않고 공통 컴포넌트를 그대로 씁니다.
 *   - featured 목록을 정렬하거나 점수(matchScore)로 고르지 않습니다.
 *     선정 기준("최근 논문을 낸 교수")의 판정은 전부 백엔드 몫이고(v6 API ③),
 *     프론트는 받은 results 를 순서 그대로 보여주기만 합니다.
 *   - 검색어가 어떤 필드에 매칭되는지 문구로 단정하지 않습니다.
 *     v6 는 query 를 API ① 요청 필드로만 정의하고 매칭 범위는 정의하지 않습니다.
 *     그래서 SearchBar 에 hintText(검색 예시)를 넘기지 않습니다.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { getFeaturedProfessors } from '../api/professorApi.js'
import SearchBar from '../components/SearchBar.jsx'
import ProfessorCard from '../components/ProfessorCard.jsx'
import '../styles/HomePage.css'

/**
 * 하단 기능 안내 영역의 내용.
 *
 * 이 영역은 서비스가 무엇을 하는지 설명하는 정적 UI 입니다.
 * API 를 호출하지 않고, 교수 데이터도 쓰지 않습니다.
 *
 * ※ matchScore 의 계산 기준은 v6 5장 1번에서 아직 미확정입니다.
 *   그래서 "관련도 기반 추천"처럼 추천 방식이 확정된 것처럼 들리는 표현 대신,
 *   화면에서 실제로 일어나는 일만 적습니다.
 */
const GUIDES = [
  {
    title: '교수 검색',
    description: '검색어로 교수 정보를 찾아보세요.',
    icon: <SearchGuideIcon />,
  },
  {
    title: '찜한 교수 관리',
    description: '관심 있는 교수를 찜하고 목록에서 확인하세요.',
    icon: <HeartGuideIcon />,
  },
  {
    title: '관련 교수 탐색',
    description: '입력한 검색어와 관련된 교수를 확인하세요.',
    icon: <LinkGuideIcon />,
  },
  {
    title: '연구 정보 확인',
    description: '교수의 연구 분야와 대표 논문을 확인하세요.',
    icon: <DocumentGuideIcon />,
  },
]

function HomePage() {
  const navigate = useNavigate()

  // 최근 연구 활동 교수(API ③) 관련 상태.
  // 이 세 값은 아래 featured 섹션 "안에서만" 쓰입니다.
  // v6 API ③에는 "데이터 수집이 어려울 시 이 기능은 생략"이라고 적혀 있어,
  // 이 목록이 비거나 불러오기에 실패해도 검색 영역은 그대로 동작해야 하기 때문입니다.
  const [featured, setFeatured] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false)

  // 페이지에 들어왔을 때 한 번 불러온다. (v6 API ③ 트리거: 메인 페이지 진입 시)
  useEffect(() => {
    let ignore = false // 응답이 늦게 와서 페이지를 이미 떠난 경우, 옛 결과 무시용

    async function load() {
      setIsLoading(true)
      setHasError(false)
      try {
        const data = await getFeaturedProfessors() // { results, collectedAt }
        if (ignore) return
        // 응답 순서를 그대로 씁니다. 프론트에서 다시 정렬하지 않습니다.
        setFeatured(data.results)
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

  /**
   * 검색 실행 — SearchBar 가 공백을 지운 검색어를 넘겨준다.
   *
   * 검색은 검색 결과 페이지가 담당하므로 여기서는 주소만 바꿉니다.
   * (getProfessors 호출은 SearchResultPage 몫)
   * 검색어가 비어 있으면 query 없이 이동합니다. 계약상 "검색어 없음 = 전체 조회"입니다.
   */
  function handleSearch(query) {
    if (query === '') {
      navigate('/search')
      return
    }
    navigate(`/search?query=${encodeURIComponent(query)}`)
  }

  // 자세히 보기 → 상세 페이지로 이동 (라우팅은 카드가 아니라 페이지가 담당)
  function handleDetail(id) {
    navigate(`/professors/${id}`)
  }

  return (
    <div className="home-page">
      {/* ---------- ① 검색 영역 ---------- */}
      <section className="home-hero">
        <h1 className="home-hero__title">
          연구 분야와 키워드로
          <br />
          <span className="home-hero__accent">적합한 교수</span>를 찾아보세요
        </h1>

        <div className="home-hero__search">
          {/* placeholder 는 SearchBar 의 기본값("검색어를 입력하세요")을 그대로 쓴다 */}
          <SearchBar onSearch={handleSearch} />
        </div>
      </section>

      {/* ---------- ② 최근 연구 활동 교수 ---------- */}
      <section className="home-featured">
        <div className="home-featured__header">
          <div>
            <h2 className="home-featured__title">최근 연구 활동 교수</h2>
            <p className="home-featured__subtitle">
              최근 논문이 등록된 교수를 소개합니다.
            </p>
          </div>

          {/* 검색어 없이 전체 조회로 이동한다 */}
          <button
            type="button"
            className="home-featured__all"
            onClick={() => navigate('/search')}
          >
            전체 보기
            <ArrowIcon />
          </button>
        </div>

        {/* 불러오는 중 / 실패 / 비어 있음 / 정상 — 이 섹션 안에서만 갈라진다 */}
        {isLoading ? (
          <p className="home-featured__message">불러오는 중입니다...</p>
        ) : hasError ? (
          <p className="home-featured__message">
            교수 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </p>
        ) : featured.length === 0 ? (
          <p className="home-featured__message">현재 표시할 교수가 없습니다.</p>
        ) : (
          // 응답이 3~5개로 달라질 수 있어 개수를 고정하지 않고 CSS grid 가 나눠 담는다
          <ul className="home-featured__list">
            {featured.map((professor) => (
              <li key={professor.id}>
                <ProfessorCard
                  professor={professor}
                  variant="featured"
                  // 이 화면의 카드에는 찜 버튼을 두지 않는다.
                  // onToggleFavorite 를 넘기지 않으면 ProfessorCard 가 버튼을 그리지 않는다.
                  onDetail={handleDetail}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ---------- ③ 기능 안내 (정적) ---------- */}
      <section className="home-guide">
        <h2 className="home-guide__title">이용 안내</h2>

        <ul className="home-guide__list">
          {GUIDES.map((guide) => (
            <li className="home-guide__item" key={guide.title}>
              <span className="home-guide__icon" aria-hidden="true">
                {guide.icon}
              </span>
              <div>
                <h3 className="home-guide__item-title">{guide.title}</h3>
                <p className="home-guide__item-text">{guide.description}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

/* ------------------------------------------------------------------
 * 아이콘 — 외부 아이콘 라이브러리 없이 인라인 SVG 로 그립니다.
 * 안내 문구가 바로 옆에 글자로 있으므로 전부 장식용(aria-hidden 은 부모가 지정)입니다.
 * ------------------------------------------------------------------ */

/** 공통 SVG 틀 — 크기·선 두께를 한 곳에서 맞춘다 */
function GuideIcon({ children }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="26"
      height="26"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

function SearchGuideIcon() {
  return (
    <GuideIcon>
      <circle cx="11" cy="11" r="7" />
      <line x1="16.5" y1="16.5" x2="21" y2="21" />
    </GuideIcon>
  )
}

function HeartGuideIcon() {
  return (
    <GuideIcon>
      <path d="M12 20.3 4.7 13a4.6 4.6 0 0 1 6.5-6.5l.8.8.8-.8A4.6 4.6 0 0 1 19.3 13Z" />
    </GuideIcon>
  )
}

function LinkGuideIcon() {
  return (
    <GuideIcon>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7L11.5 7" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1.5-1.5" />
    </GuideIcon>
  )
}

function DocumentGuideIcon() {
  return (
    <GuideIcon>
      <path d="M14 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V7.5Z" />
      <path d="M14 3v4.5h4.5" />
      <line x1="9" y1="13" x2="15" y2="13" />
      <line x1="9" y1="16.5" x2="13" y2="16.5" />
    </GuideIcon>
  )
}

/** [전체 보기] 옆 화살표 */
function ArrowIcon() {
  return (
    <svg
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

export default HomePage
