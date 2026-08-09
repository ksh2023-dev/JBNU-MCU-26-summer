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

  // 화면 상태 3가지를 따로 관리한다
  const [professor, setProfessor] = useState(null) // 불러온 교수 (없으면 null)
  const [isLoading, setIsLoading] = useState(true) // 불러오는 중인가?
  const [isFavorite, setIsFavorite] = useState(false) // 찜한 교수인가?

  // id 가 바뀔 때마다 교수 정보를 다시 불러온다
  useEffect(() => {
    // 응답이 늦게 도착했는데 이미 다른 교수로 넘어간 경우, 옛날 결과를 무시하기 위한 표시
    let ignore = false

    async function load() {
      setIsLoading(true)

      // getProfessorById 는 async 라서 await 로 결과를 기다린다
      const found = await getProfessorById(id)

      if (ignore) return
      setProfessor(found) // 없는 id 면 null 이 들어온다

      // 찜 여부는 백엔드가 아니라 localStorage 로 판단한다
      setIsFavorite(getFavorites().includes(id))
      setIsLoading(false)
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

  /* ---------- 2) 없는 id ---------- */
  if (!professor) {
    return (
      <div className="detail-message">
        <p>해당 교수를 찾을 수 없습니다.</p>
        <button
          type="button"
          className="detail-button"
          onClick={() => navigate(-1)}
        >
          ← 목록으로 돌아가기
        </button>
      </div>
    )
  }

  /* ---------- 3) 정상 화면 ---------- */

  // 논문 중 pmid 가 있는 것만 화면에 넣는다. (계약 원칙 1)
  const papers = professor.papers.filter((paper) => paper.pmid)

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
          ← 목록으로 돌아가기
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
              {isFavorite ? '♥ 찜 취소' : '♡ 찜하기'}
            </button>
          </div>

          {/* 소속 교실 / 진료과 */}
          <p className="detail-department">{professor.department}</p>

          <dl className="detail-info">
            <dt>연구실</dt>
            {/* labName 이 null 이면 지어내지 않고 "정보 없음" */}
            <dd>{professor.labName ?? NO_DATA}</dd>

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
                    홈페이지 바로가기 ↗
                  </a>
                </dd>
              </>
            )}
          </dl>
        </div>
      </section>

      <div className="detail-columns">
        {/* 연구 분야 - specialties 는 문자열 배열이라 이름만 나열한다 */}
        <section className="detail-card">
          <h3 className="detail-section-title">연구 분야</h3>
          {professor.specialties.length > 0 ? (
            <ul className="detail-specialties">
              {professor.specialties.map((specialty) => (
                <li key={specialty}>{specialty}</li>
              ))}
            </ul>
          ) : (
            <p className="detail-empty">{NO_DATA}</p>
          )}
        </section>

        {/* 연구 키워드 - 상세 페이지에서는 전체를 보여준다 */}
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
              // pmid 는 논문마다 다르므로 목록의 key 로 쓰기 좋다
              <li key={paper.pmid} className="detail-paper">
                <span className="detail-paper__no">{index + 1}</span>

                <div className="detail-paper__body">
                  <p className="detail-paper__title">{paper.title}</p>
                  <p className="detail-paper__meta">
                    {paper.journal ?? NO_DATA} · {paper.year ?? NO_DATA}
                  </p>
                  <p className="detail-paper__meta">PMID: {paper.pmid}</p>
                </div>

                {/* pmid 로 PubMed 주소를 직접 만들어 새 탭으로 연다 */}
                <a
                  className="detail-button"
                  href={`https://pubmed.ncbi.nlm.nih.gov/${paper.pmid}/`}
                  target="_blank"
                  rel="noreferrer"
                >
                  PubMed 보기 ↗
                </a>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

export default ProfessorDetailPage
