import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

import {
  getProfessorById,
  getFavorites,
  addFavorite,
  removeFavorite,
} from '../api/professorApi.js'

import '../styles/ProfessorDetailPage.css'

// 값이 없을 때(null) 화면에 대신 보여줄 문구. 빈칸으로 두지 않는다. (계약 원칙 2)
const NO_DATA = '정보 없음'

function ProfessorDetailPage() {
  const { id } = useParams() // 주소 /professors/P-001 에서 "P-001" 을 꺼낸다
  const navigate = useNavigate()

  // 화면 상태 4가지를 따로 관리한다
  const [professor, setProfessor] = useState(null) // 불러온 교수 (없으면 null)
  const [isLoading, setIsLoading] = useState(true) // 불러오는 중인가?
  // "교수가 없음(404)" 과 "불러오기 자체가 실패함(네트워크 오류 등)" 은 다른 상황이라 따로 구분한다
  const [hasError, setHasError] = useState(false)
  const [isFavorite, setIsFavorite] = useState(false) // 찜한 교수인가?

  // id 가 바뀔 때마다 교수 정보를 다시 불러온다
  useEffect(() => {
    // 응답이 늦게 도착했는데 이미 다른 교수로 넘어간 경우, 옛날 결과를 무시하기 위한 표시
    let ignore = false

    async function load() {
      setIsLoading(true)
      setHasError(false) // 이전 교수에서 났던 에러를 지우고 새로 시작한다

      try {
        // getProfessorById 는 async 라서 await 로 결과를 기다린다
        const found = await getProfessorById(id)

        if (ignore) return
        setProfessor(found) // 없는 id 면 null 이 들어온다 → 미발견 화면

        // 찜 여부는 백엔드가 아니라 localStorage 로 판단한다
        setIsFavorite(getFavorites().includes(id))
      } catch (err) {
        // 백엔드가 연결되면 없는 id 는 null 이 아니라 404 에러로 온다
        if (ignore) return

        if (err?.status === 404 || err?.code === 'not_found') {
          // 교수가 없는 것뿐이므로 에러가 아니라 미발견으로 처리한다
          setProfessor(null)
        } else {
          // 네트워크 오류 등 진짜 실패. 미발견과 구분해서 보여준다
          setHasError(true)
        }
      } finally {
        // finally 는 성공하든 에러가 나든 항상 실행된다.
        // 그래서 예외가 나도 화면이 "불러오는 중" 에 멈추지 않는다.
        if (!ignore) setIsLoading(false)
      }
    }

    load()

    return () => {
      ignore = true
    }
  }, [id])

  // 찜하기 / 찜 취소 토글
  function handleToggleFavorite() {
    if (isFavorite) {
      removeFavorite(id)
      setIsFavorite(false)
    } else {
      addFavorite(id)
      setIsFavorite(true)
    }
  }

  /* ---------- 1) 불러오는 중 ---------- */
  if (isLoading) {
    return <p className="detail-message">불러오는 중입니다...</p>
  }

  /* ---------- 2) 불러오기 실패 (네트워크 오류 등) ---------- */
  // 미발견(3번)보다 먼저 검사한다. 실패했을 때는 professor 가 null 이라
  // 순서를 바꾸면 "교수가 없다" 는 엉뚱한 안내가 뜨기 때문이다.
  if (hasError) {
    return (
      <div className="detail-message">
        <p>정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>
        <button
          type="button"
          className="detail-button"
          onClick={() => navigate(-1)}
        >
          <ArrowLeftIcon />
          목록으로 돌아가기
        </button>
      </div>
    )
  }

  /* ---------- 3) 없는 id ---------- */
  if (!professor) {
    return (
      <div className="detail-message">
        <p>해당 교수를 찾을 수 없습니다.</p>
        <button
          type="button"
          className="detail-button"
          onClick={() => navigate(-1)}
        >
          <ArrowLeftIcon />
          목록으로 돌아가기
        </button>
      </div>
    )
  }

  /* ---------- 4) 정상 화면 ---------- */

  // 논문은 pmid 또는 kciId 중 최소 하나를 가진다. (계약 v6.4 1-2)
  // 둘 다 없는 논문은 응답에 오지 않지만, 만약 들어오면 화면에서 뺀다. (원칙 1)
  // pmid 만 보고 거르면 kciId 만 있는 국내 논문이 통째로 사라진다.
  const papers = professor.papers.filter((paper) => paper.pmid || paper.kciId)

  return (
    <div className="detail-page">
      {/* 상단: 제목 + 목록으로 돌아가기 */}
      <div className="detail-top">
        <h1 className="detail-title">교수 상세</h1>
        <button
          type="button"
          className="detail-button"
          // navigate(-1) = 브라우저 뒤로가기
          onClick={() => navigate(-1)}
        >
          <ArrowLeftIcon />
          목록으로 돌아가기
        </button>
      </div>

      {/* 프로필 카드 */}
      <section className="detail-card detail-profile">
        <div className="detail-profile__left">
          {professor.profileImageUrl ? (
            <img
              className="detail-avatar"
              src={professor.profileImageUrl}
              alt={`${professor.name} 교수 사진`}
            />
          ) : (
            // 사진이 없으면(null) 이름 첫 글자로 만든 이니셜 아바타를 대신 보여준다
            <div className="detail-avatar detail-avatar--initial" aria-hidden="true">
              {professor.name.charAt(0)}
            </div>
          )}
        </div>

        <div className="detail-profile__right">
          <div className="detail-nameline">
            <h2 className="detail-name">{professor.name} 교수</h2>

            {/* 배지에는 교수 구분(professorType)을 넣는다. 직급 데이터는 없다 */}
            <span className="detail-badge">{professor.professorType}</span>

            <button
              type="button"
              className={
                isFavorite
                  ? 'detail-favorite is-active'
                  : 'detail-favorite'
              }
              onClick={handleToggleFavorite}
            >
              <HeartIcon filled={isFavorite} />
              {isFavorite ? '찜 취소' : '찜하기'}
            </button>
          </div>

          {/* 소속 교실 / 진료과 */}
          <p className="detail-department">{professor.department}</p>

          {/* 연구실(labName) 행은 계약 v6.4 에서 필드 자체가 삭제되어 없앴습니다.
              값이 null 이라 "정보 없음"을 띄우던 것이 아니라, 이제 응답에 오지 않습니다. */}
          <dl className="detail-info">
            <dt>이메일</dt>
            <dd>
              {professor.email ? (
                <a href={`mailto:${professor.email}`}>{professor.email}</a>
              ) : (
                NO_DATA
              )}
            </dd>

            {/*
              계약서 규칙: homepageUrl 은 값이 없으면 "링크 숨김".
              즉 "정보 없음"을 쓰지 않고, 라벨(dt)까지 줄 전체를 화면에서 뺀다.
              && 는 앞이 거짓이면 아무것도 그리지 않는다 (null · 빈 문자열 "" 모두 거짓)
            */}
            {professor.homepageUrl && (
              <>
                <dt>연구실 홈페이지</dt>
                <dd>
                  <a
                    href={professor.homepageUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    홈페이지 바로가기
                    <ExternalLinkIcon />
                  </a>
                </dd>
              </>
            )}
          </dl>
        </div>
      </section>

      <div className="detail-columns">
        {/*
          연구 분야 — 계약 v6.4 4장: specialties 가 빈 배열이면 "해당 영역 표시 생략".
          "정보 없음"을 띄우지 않고 카드 자체를 그리지 않습니다.
          (한쪽만 남으면 CSS 의 :only-child 규칙이 가로 전체를 쓰게 합니다)
        */}
        {professor.specialties.length > 0 && (
          <section className="detail-card">
            <h3 className="detail-section-title">연구 분야</h3>
            <ul className="detail-specialties">
              {professor.specialties.map((specialty) => (
                <li key={specialty}>{specialty}</li>
              ))}
            </ul>
          </section>
        )}

        {/*
          연구 키워드 — 계약 v6.4 는 "화면 미표시"로 바뀌었지만,
          노출 유지 여부를 팀에 다시 논의 요청한 상태라 기존 UI 를 그대로 둡니다.
          (PR #26 리뷰 4번 — 팀 결정 후 반영)
        */}
        <section className="detail-card">
          <h3 className="detail-section-title">연구 키워드</h3>
          {professor.keywords.length > 0 ? (
            <ul className="detail-keywords">
              {professor.keywords.map((keyword) => (
                <li key={keyword} className="detail-pill">
                  {keyword}
                </li>
              ))}
            </ul>
          ) : (
            <p className="detail-empty">{NO_DATA}</p>
          )}
        </section>
      </div>

      {/* 대표 논문 */}
      <section className="detail-card">
        <h3 className="detail-section-title">대표 논문</h3>

        {papers.length === 0 ? (
          <p className="detail-empty">등록된 대표 논문이 없습니다</p>
        ) : (
          <ol className="detail-papers">
            {papers.map((paper, index) => (
              // 식별자는 논문마다 다르므로 목록의 key 로 쓰기 좋다.
              // kciId 만 있는 국내 논문도 있으므로 두 값 중 있는 쪽을 쓴다.
              <li key={paper.pmid ?? paper.kciId} className="detail-paper">
                <span className="detail-paper__no">{index + 1}</span>

                <div className="detail-paper__body">
                  <p className="detail-paper__title">{paper.title}</p>
                  <p className="detail-paper__meta">
                    {paper.journal ?? NO_DATA} · {paper.year ?? NO_DATA}
                  </p>
                </div>

                {/*
                  원문 링크 (계약 v6.4 3장)
                    pmid 있음                → PubMed. 둘 다 있어도 PubMed 를 우선한다
                    pmid 없고 kciId 만 있음  → KCI 논문 페이지

                  KCI 주소 형식은 아직 백엔드와 최종 확인 전이라, 지금은 주소를
                  지어내지 않고 버튼을 그리지 않는다. 형식이 확정되면 여기에
                  kciId 분기를 한 줄 추가하면 된다. (원칙 2 — 없는 값을 만들지 않는다)
                */}
                {paper.pmid && (
                  <a
                    className="detail-button"
                    href={`https://pubmed.ncbi.nlm.nih.gov/${paper.pmid}/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    PubMed 보기
                    <ExternalLinkIcon />
                  </a>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

/* ------------------------------------------------------------------
 * 아이콘 — 외부 아이콘 라이브러리 없이 인라인 SVG 로 그립니다.
 *
 * 예전에는 '←' '↗' '♡' '♥' 문자를 그대로 썼는데, 글꼴에 따라 크기·굵기·세로 위치가
 * 제각각이라 다른 화면의 아이콘(HomePage / ProfessorCard 는 전부 인라인 SVG)과
 * 톤이 맞지 않았습니다. 같은 규격(16px, stroke-width 1.8)으로 맞춥니다.
 *
 * 옆에 안내 문구가 글자로 함께 있으므로 전부 장식용(aria-hidden)입니다.
 * ------------------------------------------------------------------ */

/** 공통 SVG 틀 — 크기·선 두께를 한 곳에서 맞춘다 */
function Icon({ children, fill = 'none' }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill={fill}
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

/** [목록으로 돌아가기] 앞 화살표 — 교수 카드의 오른쪽 화살표를 뒤집은 모양 */
function ArrowLeftIcon() {
  return (
    <Icon>
      <path d="M20 12H6M11.5 6l-6 6 6 6" />
    </Icon>
  )
}

/** 새 탭으로 여는 링크 표시 */
function ExternalLinkIcon() {
  return (
    <Icon>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M18 14.5v4A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6h4" />
    </Icon>
  )
}

/** 찜 하트 — 교수 카드와 같은 path 를 쓰고, 찜한 상태에서만 안을 채운다 */
function HeartIcon({ filled }) {
  return (
    <Icon fill={filled ? 'currentColor' : 'none'}>
      <path d="M12 20.3 4.7 13a4.6 4.6 0 0 1 6.5-6.5l.8.8.8-.8A4.6 4.6 0 0 1 19.3 13Z" />
    </Icon>
  )
}

export default ProfessorDetailPage
