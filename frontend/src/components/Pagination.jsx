import './Pagination.css'

/**
 * Pagination.jsx — 페이지 번호 이동 버튼 (여러 페이지에서 재사용하는 공통 컴포넌트)
 *
 * 데이터를 모르는 순수 UI 컴포넌트입니다.
 * 현재 페이지와 전체 페이지 수만 받고, 버튼을 누르면
 * onPageChange(새 페이지 번호)로 부모에게 알리기만 합니다.
 * 페이지가 1개뿐이면 아무것도 그리지 않습니다.
 */

/**
 * 이전 / 다음 화살표.
 *
 * 예전에는 '‹' '›' 문자를 그대로 썼는데, 글꼴에 따라 크기·굵기·세로 위치가 제각각이라
 * 다른 화면의 아이콘(전부 인라인 SVG)과 톤이 맞지 않았습니다.
 * ProfessorCard / HomePage 와 같은 규격(16px, stroke-width 1.8)으로 맞춥니다.
 *
 * 버튼 쪽에 aria-label 이 붙어 있으므로 이 그림 자체는 장식입니다. (aria-hidden)
 *
 * @param {object} props
 * @param {'prev'|'next'} props.direction 화살표 방향
 */
function ChevronIcon({ direction }) {
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
      <path d={direction === 'prev' ? 'M15 5 8 12l7 7' : 'M9 5l7 7-7 7'} />
    </svg>
  )
}

/**
 * @param {object} props
 * @param {number} props.currentPage 현재 페이지 (1부터 시작)
 * @param {number} props.totalPages  전체 페이지 수
 * @param {(page: number) => void} props.onPageChange 페이지 버튼 클릭 시 호출
 */
function Pagination({ currentPage, totalPages, onPageChange }) {
  // 페이지가 1개 이하이면 페이지네이션을 그릴 필요가 없다
  if (totalPages <= 1) return null

  // [1, 2, 3, ...] 페이지 번호 배열을 만든다
  const pages = Array.from({ length: totalPages }, (_, index) => index + 1)

  return (
    <nav className="pagination" aria-label="페이지 이동">
      <button
        type="button"
        className="pagination__button"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1} // 첫 페이지면 '이전'을 막는다
        aria-label="이전 페이지"
      >
        <ChevronIcon direction="prev" />
      </button>

      {pages.map((page) => (
        <button
          key={page}
          type="button"
          className={
            page === currentPage
              ? 'pagination__button is-current'
              : 'pagination__button'
          }
          onClick={() => onPageChange(page)}
          aria-current={page === currentPage ? 'page' : undefined}
        >
          {page}
        </button>
      ))}

      <button
        type="button"
        className="pagination__button"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages} // 마지막 페이지면 '다음'을 막는다
        aria-label="다음 페이지"
      >
        <ChevronIcon direction="next" />
      </button>
    </nav>
  )
}

export default Pagination
