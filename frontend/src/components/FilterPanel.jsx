/**
 * FilterPanel.jsx — 검색 결과 페이지(SearchResultPage) 왼쪽의 필터 패널
 *
 * 「데이터 계약 문서 v4」기준
 *   - 교수 구분(professorType)은 API ① 요청의 filters.professorType 과 같은 모양(문자열 배열)입니다.
 *   - "찜한 교수만 보기"는 백엔드 요청 없이 프론트가 localStorage 로 거르는 조건이라,
 *     체크 여부(true/false)만 부모에게 전달합니다.
 *   - 계약 3장의 "초기화 = 검색어·필터·정렬을 기본값으로 되돌림"은 페이지 전체 범위라
 *     이 컴포넌트는 클릭 사실만 알립니다.
 *   - 필터는 "선택 시 즉시 재조회"가 트리거이므로 [필터 적용] 버튼을 두지 않습니다.
 *
 * 이 컴포넌트가 "하지 않는" 일 (역할을 좁게 유지하기 위한 약속)
 *   - professorApi.js 를 import 하지 않습니다. (getProfessors / getFavorites 직접 호출 없음)
 *   - localStorage 에 직접 접근하지 않습니다.
 *   - 페이지 이동(라우팅)을 직접 하지 않습니다.
 *   - 자기 상태를 갖지 않습니다(useState 없음). 선택 상태는 부모가 관리하고 props 로 내려줍니다.
 *
 * 화면에 두지 않는 항목
 *   - 최소 관련도(minScore) 선택 UI : matchScore 계산 기준이 아직 확정되지 않았습니다.
 *     (계약 5장 1번 — 백엔드·검색엔진팀 확정 대기) 요청값은 부모가 기본값으로 보냅니다.
 *   - 정렬 · 페이지네이션 : 시안에서도 패널 바깥 영역이라 SearchResultPage 담당입니다.
 */

import './FilterPanel.css'

/**
 * 교수 구분 필터에 쓰는 값 집합.
 * 계약 1-1: professorType 은 아래 4가지만 사용합니다.
 * 지금은 이 4개를 내보내는 공용 상수가 프로젝트에 없어서 여기에 둡니다.
 * (다른 화면에서도 필요해지면 그때 공용 파일로 옮깁니다)
 */
const PROFESSOR_TYPES = ['기초의학', '임상의학', '의학교육학', '인문사회의학']

/**
 * @param {object}   props
 * @param {string[]} props.selectedProfessorTypes  체크된 교수 구분. 빈 배열이면 전체
 * @param {(nextTypes: string[]) => void} props.onProfessorTypesChange
 *        체크박스 변경 시 "바뀐 배열 전체"를 부모에게 전달
 * @param {boolean}  props.favoritesOnly           "찜한 교수만 보기" 체크 여부
 * @param {(next: boolean) => void} props.onFavoritesOnlyChange  체크 여부만 부모에게 전달
 * @param {() => void} props.onReset               초기화 버튼 클릭을 부모에게 알림
 */
function FilterPanel({
  selectedProfessorTypes = [],
  onProfessorTypesChange,
  favoritesOnly = false,
  onFavoritesOnlyChange,
  onReset,
}) {
  /**
   * 체크박스 하나를 켜고 끕니다.
   * 여기서 목록을 다시 조회하지는 않습니다. 새 배열을 만들어 부모에게 넘기기만 합니다.
   */
  function handleProfessorTypeToggle(type, checked) {
    const nextTypes = checked
      ? [...selectedProfessorTypes, type]
      : selectedProfessorTypes.filter((selected) => selected !== type)

    onProfessorTypesChange(nextTypes)
  }

  return (
    <aside className="filter-panel">
      <div className="filter-panel__header">
        <h2 className="filter-panel__title">필터</h2>
        <button type="button" className="filter-panel__reset" onClick={onReset}>
          <span aria-hidden="true">↺</span> 초기화
        </button>
      </div>

      <div className="filter-panel__group">
        <h3 className="filter-panel__group-title">교수 구분</h3>

        {PROFESSOR_TYPES.map((type) => (
          <label key={type} className="filter-panel__option">
            <input
              type="checkbox"
              checked={selectedProfessorTypes.includes(type)}
              onChange={(event) =>
                handleProfessorTypeToggle(type, event.target.checked)
              }
            />
            {type}
          </label>
        ))}
      </div>

      {/* 찜 조건은 교수 구분과 성격이 달라(백엔드 요청에 들어가지 않음) 구분선 아래에 둡니다 */}
      <label className="filter-panel__option filter-panel__option--favorites">
        <input
          type="checkbox"
          checked={favoritesOnly}
          onChange={(event) => onFavoritesOnlyChange(event.target.checked)}
        />
        찜한 교수만 보기
      </label>

      <p className="filter-panel__hint">필터는 선택 시 즉시 반영됩니다.</p>
    </aside>
  )
}

export default FilterPanel
