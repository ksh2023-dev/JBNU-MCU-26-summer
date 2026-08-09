/**
 * ProfessorCard.jsx — 교수 카드 1장을 그리는 공통 컴포넌트
 *
 * 「데이터 계약 문서 v4」의 1-1. 교수 카드 객체 하나를 받아서 화면에 그립니다.
 * 두 화면에서 같은 컴포넌트를 재사용합니다.
 *
 *   variant="featured"  메인(HomePage)의 '우수 교수' 영역 — 세로형 compact 카드
 *   variant="search"    검색 결과(SearchResultPage) 목록 — 가로형 리스트 카드
 *
 * 이 컴포넌트가 "하지 않는" 일 (역할을 좁게 유지하기 위한 약속)
 *   - professorApi.js 를 import 하지 않습니다.
 *   - localStorage 에 직접 접근하지 않습니다. (찜 저장은 부모 페이지 담당)
 *   - 페이지 이동(라우팅)을 직접 하지 않습니다. (onDetail 로 부모에게 알리기만)
 *   - professor 객체에 없는 값(직급·이메일·isFavorite 등)을 만들어 붙이지 않습니다.
 *
 * 계약에 따라 화면에 표시하지 않는 값
 *   - id         : 내부 식별자라서 표시하지 않습니다. (콜백으로 전달만 함)
 *   - matchScore : 데이터에는 있지만 확정 UI에 점수 표시가 없어 노출하지 않습니다.
 */

import { useState } from 'react'
import './ProfessorCard.css'

/**
 * 카드에 보여줄 키워드 최대 개수.
 * 계약 문서: "keywords 는 전체 배열을 보내고, 카드에는 프론트가 앞 3~4개만 노출"
 * featured / search 구분 없이 4개로 통일합니다.
 */
const MAX_VISIBLE_KEYWORDS = 4

/**
 * 배열이 아닌 값(undefined, null, 문자열 등)이 들어와도 빈 배열로 바꿔 줍니다.
 * 값이 없다고 해서 임의의 값을 만들지는 않습니다. (계약 원칙 2)
 *
 * @param {unknown} value
 * @returns {unknown[]} 원래 배열이거나 빈 배열
 */
function toArray(value) {
  return Array.isArray(value) ? value : []
}

/**
 * 프로필 사진이 없을 때 사용할 이니셜 글자를 만듭니다.
 *
 *   '가상교수A' → '가상'     (한글 등: 앞 2글자)
 *   'Jane Doe'  → 'JD'       (공백으로 나뉘면 각 단어 첫 글자 2개)
 *   ''          → '?'        (이름이 없으면 물음표)
 *
 * 사진을 지어내지 않고 이름이라는 "있는 데이터"만으로 만드는 대체 표시입니다.
 *
 * @param {string} name 교수 이름
 * @returns {string} 아바타에 표시할 1~2글자
 */
function getInitials(name) {
  const trimmed = typeof name === 'string' ? name.trim() : ''
  if (trimmed === '') return '?'

  const words = trimmed.split(/\s+/)
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase()
  }
  return trimmed.slice(0, 2)
}

/**
 * 교수 카드 1장
 *
 * @param {object}   props
 * @param {object}   props.professor          계약 1-1 교수 카드 객체 (필수)
 * @param {'featured'|'search'} [props.variant='search'] 표시 형태
 * @param {boolean}  [props.isFavorite=false] 찜 여부. 부모가 localStorage 상태를 보고 내려줍니다
 * @param {(id: string) => void} [props.onToggleFavorite] 찜 버튼 클릭. 없으면 찜 버튼을 그리지 않습니다
 * @param {(id: string) => void} [props.onDetail]         [자세히 보기] 클릭
 */
function ProfessorCard({
  professor,
  variant = 'search',
  isFavorite = false,
  onToggleFavorite,
  onDetail,
}) {
  /**
   * 불러오기에 실패한 이미지 주소를 기억합니다.
   * true/false 대신 "주소"를 담는 이유: 같은 카드 자리에 다른 교수가 들어와
   * 사진 주소가 바뀌면, 이전 실패 기록 때문에 새 사진이 가려지는 일을 막기 위해서입니다.
   */
  const [failedImageUrl, setFailedImageUrl] = useState(null)

  // professor 가 아직 없을 때(로딩 중 등) 화면이 깨지지 않도록 아무것도 그리지 않습니다.
  if (!professor) return null

  // 계약에 없는 값은 만들지 않고, 배열만 안전하게 빈 배열로 맞춰 둡니다.
  const specialties = toArray(professor.specialties)
  const keywords = toArray(professor.keywords)

  // 앞 4개만 칩으로 보여주고, 남은 개수는 실제 배열 길이로 정확히 계산합니다.
  const visibleKeywords = keywords.slice(0, MAX_VISIBLE_KEYWORDS)
  const hiddenKeywordCount = keywords.length - visibleKeywords.length

  // 사진 주소가 null/빈 문자열이거나, 불러오기에 실패했으면 이니셜 아바타를 씁니다.
  const imageUrl =
    typeof professor.profileImageUrl === 'string'
      ? professor.profileImageUrl.trim()
      : ''
  const showImage = imageUrl !== '' && imageUrl !== failedImageUrl

  // 예상 밖의 값이 들어와도 레이아웃이 깨지지 않도록 두 가지 중 하나로 고정합니다.
  const cardVariant = variant === 'featured' ? 'featured' : 'search'

  return (
    <article className={`professor-card professor-card--${cardVariant}`}>
      <div className="professor-card__profile">
        {showImage ? (
          <img
            className="professor-card__avatar"
            src={imageUrl}
            alt={`${professor.name} 교수 프로필 사진`}
            onError={() => setFailedImageUrl(imageUrl)}
          />
        ) : (
          // 이름이 바로 옆에 글자로 있으므로, 이니셜은 보조 표시(aria-hidden)로 둡니다.
          <div
            className="professor-card__avatar professor-card__avatar--initial"
            aria-hidden="true"
          >
            {getInitials(professor.name)}
          </div>
        )}
      </div>

      <div className="professor-card__body">
        <div className="professor-card__heading">
          <h3 className="professor-card__name">{professor.name} 교수</h3>
          {/* professorType: 기초의학 | 임상의학 | 의학교육학 | 인문사회의학 */}
          <span className="professor-card__type">{professor.professorType}</span>
        </div>

        {/* department: 소속교실 또는 진료과 */}
        <p className="professor-card__department">{professor.department}</p>

        {/* 전문 분야가 없으면(빈 배열) 이 줄 자체를 그리지 않습니다. */}
        {specialties.length > 0 && (
          <div className="professor-card__row">
            <span className="professor-card__label">전문 분야</span>
            <span className="professor-card__specialties">
              {specialties.join(', ')}
            </span>
          </div>
        )}

        {/* 연구 키워드가 없으면(빈 배열) 이 줄 자체를 그리지 않습니다. */}
        {keywords.length > 0 && (
          <div className="professor-card__row">
            <span className="professor-card__label professor-card__label--keywords">
              연구 키워드
            </span>
            <ul className="professor-card__keywords">
              {visibleKeywords.map((keyword, index) => (
                <li className="professor-card__keyword" key={`${keyword}-${index}`}>
                  {keyword}
                </li>
              ))}
              {hiddenKeywordCount > 0 && (
                <li className="professor-card__keyword professor-card__keyword--more">
                  +{hiddenKeywordCount}
                </li>
              )}
            </ul>
          </div>
        )}
      </div>

      <div className="professor-card__actions">
        {/* 부모가 찜 처리를 맡을 때만(=onToggleFavorite 를 넘겼을 때만) 찜 버튼을 그립니다. */}
        {onToggleFavorite && (
          <button
            type="button"
            className="professor-card__button professor-card__favorite"
            aria-pressed={isFavorite}
            onClick={() => onToggleFavorite(professor.id)}
          >
            <svg
              className="professor-card__icon"
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill={isFavorite ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 20.3 4.7 13a4.6 4.6 0 0 1 6.5-6.5l.8.8.8-.8A4.6 4.6 0 0 1 19.3 13Z" />
            </svg>
            {isFavorite ? '찜 취소' : '찜하기'}
          </button>
        )}

        <button
          type="button"
          className="professor-card__button professor-card__detail"
          onClick={() => onDetail?.(professor.id)}
        >
          자세히 보기
          <svg
            className="professor-card__icon"
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
        </button>
      </div>
    </article>
  )
}

export default ProfessorCard
