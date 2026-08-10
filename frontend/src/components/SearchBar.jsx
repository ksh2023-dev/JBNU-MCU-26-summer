/**
 * SearchBar.jsx — 검색어 입력창 (메인 · 검색 결과 공통)
 *
 * 「데이터 계약 문서 v4」 API ① getProfessors(query, filters) 의 요청 값 중
 * query 하나만 담당합니다. filters · sort · minScore · page 는 다루지 않습니다.
 *
 * 메인(HomePage)과 검색 결과(SearchResultPage)에서 같은 컴포넌트를 씁니다.
 * 두 화면의 차이는 폭과 위치뿐이라 variant prop 없이 부모 레이아웃이 정합니다.
 *
 * 이 컴포넌트가 "하지 않는" 일 (역할을 좁게 유지하기 위한 약속)
 *   - professorApi.js 를 import 하지 않습니다. (getProfessors 호출은 부모 페이지 담당)
 *   - useNavigate 등 라우터를 직접 쓰지 않습니다. (onSearch 로 부모에게 알리기만)
 *   - 검색 대상 범위(교수명·전문분야·키워드·논문제목·초록)를 문구로 단정하지 않습니다.
 *     계약 문서 5장 2번에서 아직 확정 대기 중인 항목입니다.
 *     그래서 안내 문구(hintText)는 기본값 없이, 부모가 넘길 때만 표시합니다.
 */

import { useState } from 'react'
import './SearchBar.css'

/**
 * 검색어 입력창
 *
 * @param {object}   props
 * @param {(query: string) => void} props.onSearch  검색 실행 콜백 (필수).
 *   공백을 제거한 검색어를 넘깁니다. 검색어가 비어 있으면 '' 을 그대로 넘기고,
 *   그 경우 무엇을 할지는 부모가 정합니다. (계약상 "검색어 없음 = 전체 조회"도 유효)
 * @param {string} [props.initialValue='']  입력창 초기값.
 *   검색 결과 페이지에서 현재 검색어를 채워 보여줄 때 씁니다.
 *   이후 값 관리는 이 컴포넌트 내부 state 가 담당합니다.
 * @param {string} [props.placeholder='검색어를 입력하세요']  입력창 안내 문구.
 * @param {string} [props.hintText]  입력창 아래 보조 문구. 넘겼을 때만 표시됩니다.
 */
function SearchBar({
  onSearch,
  initialValue = '',
  placeholder = '검색어를 입력하세요',
  hintText,
}) {
  const [value, setValue] = useState(initialValue)

  /**
   * 검색 실행 — [검색] 버튼 클릭과 Enter 가 모두 여기로 들어옵니다.
   *
   * 버튼이 type="submit" 이고 input 이 <form> 안에 있어서,
   * Enter 는 브라우저 기본 동작으로 같은 submit 을 일으킵니다.
   * 그래서 onKeyDown 을 따로 두지 않아도 두 동작이 갈라지지 않습니다.
   */
  function handleSubmit(event) {
    event.preventDefault() // 폼 제출로 페이지가 새로고침되지 않도록
    onSearch(value.trim())
  }

  return (
    <div className="search-bar">
      <form className="search-bar__form" onSubmit={handleSubmit} role="search">
        <div className="search-bar__field">
          <SearchIcon className="search-bar__icon" />
          <input
            type="text"
            className="search-bar__input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
            aria-label="검색어"
          />
        </div>

        <button type="submit" className="search-bar__button">
          <SearchIcon className="search-bar__icon" />
          검색
        </button>
      </form>

      {/* 검색 대상·예시 문구는 부모가 넘길 때만 표시합니다. */}
      {hintText && <p className="search-bar__hint">{hintText}</p>}
    </div>
  )
}

/** 돋보기 아이콘 — 외부 아이콘 라이브러리 없이 인라인 SVG 로 그립니다. */
function SearchIcon({ className }) {
  return (
    <svg
      className={className}
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <line x1="16.5" y1="16.5" x2="21" y2="21" />
    </svg>
  )
}

export default SearchBar
