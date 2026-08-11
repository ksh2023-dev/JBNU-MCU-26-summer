# 데이터 계약 문서 (프론트엔드 → 백엔드)

연수매칭 · 의대 연구 추천 시스템
수정: 김승하 · **v6.1**

**v6 → v6.1 변경사항**
- 필터 패널의 초기화 버튼은 검색어를 유지하고 필터만 초기화하도록 명확화
- 백엔드 API 요청/응답 구조 변경 없음

(v5 → v6: getPopularProfessors → getFeaturedProfessors, 우수 교수 → 최근 연구 활동 교수, /api/professors/featured → 그대로)

> 읽는 법: "어떤 버튼을 누르면 → 프론트가 무엇을 요청하고 → 백엔드가 무슨 모양으로 응답하는지"의 약속입니다.
> 언어(프론트=JavaScript, 백엔드=Python/Java 등)는 서로 달라도 되지만, 주고받는 데이터의 모양(=칸 이름)은 이 문서로 똑같이 맞춥니다.
> 백엔드는 이 JSON 모양대로만 응답하면 되고, 프론트는 이 모양의 가짜 데이터(`data/professors.js`)로 화면을 먼저 만듭니다.

---

## 0. 대전제 — 할루시네이션 방지 4원칙

이 프로젝트는 없는 값을 지어내는 순간 서비스가 실패합니다. 아래 4원칙은 백엔드가 응답을 만들 때, 그리고 AI(Claude)로 데이터를 수집·정리·생성할 때 반드시 지킵니다.

1. 모든 논문에는 `pmid`가 필수. `pmid`가 없는 논문은 응답에 넣지 않는다.
2. 값이 없는 필드는 지어내지 말고 `null`로 보낸다. (화면 표시 문구 "정보 없음"은 프론트가 붙인다. 빈칸으로 두지 않는다)
3. `matchScore`가 임계값(`minScore`) 미만인 교수는 결과에서 제외한다. 억지로 채우지 않는다.
4. 응답에 데이터 수집 기준일(`collectedAt`)을 담는다. 교수명·이메일·논문 값은 DB 원본 그대로, 재작성 금지.

AI로 데이터를 만들 때 프롬프트 맨 앞에 붙일 규칙 (그대로 복사):

```
너는 <교수_데이터> 안의 값만 사용한다.
- 데이터에 없는 교수·논문·연구실·이메일·ORCID를 절대 생성하지 마라.
- 값이 없으면 지어내지 말고 null로 두어라.
- 논문은 pmid가 있는 것만 포함하라. 제목·학술지·연도는 원본 그대로 두어라.
- 근거가 부족하면 "제공된 데이터로는 확인할 수 없습니다"라고만 답하라.
```

---

## 1. 공통 데이터 객체

### 1-1. 교수 카드 (검색 결과 · 간략 추천 1건)

```json
{
  "id": "P-012",
  "name": "김민수",
  "profileImageUrl": null,
  "professorType": "임상의학",
  "department": "순환기내과",
  "specialties": ["심장영상", "심부전"],
  "keywords": ["cardiac imaging", "심장 MRI", "biomarker"],
  "matchScore": 0.87
}
```

- 같은 모양을 교수 검색 결과와 교수 간략 추천 페이지에서 공통으로 사용
- `id` — 내부 식별자, 화면에는 표시하지 않음
- `profileImageUrl` — 없으면 `null` (프론트가 이니셜 아바타로 대체 / 저작권 때문에 없을 가능성 높음)
- `professorType` — 교수 구분 필터값. 값 집합: `기초의학 | 임상의학 | 의학교육학 | 인문사회의학`
- `department` — 소속교실 또는 진료과
- `specialties` — 전문 분야. 여러 개를 담는 배열(`[ ]`). 값이 하나여도 배열로 보냄(예: `["심장영상"]`). 없으면 빈 배열 `[]`
- `keywords` — 전체 배열을 보내고, 카드에는 프론트가 앞 3~4개만 노출
- `matchScore` — 0~1 사이 실수. 관련도순 정렬·임계값 컷에 사용
- 찜 여부·이메일은 카드에 넣지 않음 — 찜 여부는 프론트가 `id`를 localStorage와 대조해 판단, 이메일은 상세에서만 표시

### 1-2. 교수 상세

```json
{
  "id": "P-012",
  "name": "김민수",
  "profileImageUrl": null,
  "professorType": "임상의학",
  "department": "순환기내과",
  "labName": null,
  "specialties": ["심장영상", "심부전"],
  "keywords": ["cardiac imaging", "심장 MRI", "biomarker", "..."],
  "email": "kim@jbnu.ac.kr",
  "homepageUrl": null,
  "papers": [
    { "title": "Prognostic value of cardiac MRI ...", "journal": "JACC", "year": 2022, "pmid": "35123456" }
  ]
}
```

- 위쪽 `id` ~ `specialties` · `keywords`는 카드(1-1)와 동일한 칸 이름을 사용
- `labName` · `homepageUrl` · `email` — 데이터 없으면 `null`
- `homepageUrl` — 임상 교수는 병원 홈페이지, 기초 교수는 학교 홈페이지 URL
- `keywords` — 상세에서는 전체 노출
- `papers` — 최신순 1편 + 인용수 상위 2편 = 3편 (7/23 회의 결정). 각 논문 `pmid` 필수, 없으면 빈 배열 `[]`
- `pmid` — 화면에 표시하지 않음. PubMed 링크 생성에만 사용: `https://pubmed.ncbi.nlm.nih.gov/{pmid}/` (프론트가 생성)

---

## 2. API 엔드포인트

프론트의 `api/professorApi.js` 함수와 1:1로 대응합니다.

### API ① 교수 검색·목록 조회 — `getProfessors(query, filters)`

- 트리거: 검색 버튼 / Enter, 필터 선택 시 즉시 재조회, 페이지 번호 클릭

요청:

```json
{
  "query": "심장",
  "filters": {
    "professorType": ["임상의학", "기초의학"],
    "favoriteIds": ["P-001", "P-008", "P-013"]
  },
  "sort": "relevance",
  "minScore": 0.3,
  "page": 1,
  "pageSize": 5
}
```

(`filters.favoriteIds`는 "찜한 교수만 보기" ON일 때만 포함)

응답:

```json
{
  "results": [],
  "total": 12,
  "page": 1,
  "pageSize": 5,
  "collectedAt": "2026-08-05"
}
```

(`results`에는 교수 카드(1-1) 배열이 들어감)

- `sort` — MVP는 `relevance`(관련도순)만 필수
- `minScore` — 이 값 미만 교수는 백엔드가 제외 (원칙 3)
- `total` — 전체 결과 수. 프론트가 이 값으로 페이지 수 계산(5명씩)
- **"찜한 교수만 보기" 필터** — 프론트가 localStorage의 찜 id 목록을 읽어 `filters.favoriteIds`로 검색 요청에 실어 보낸다. 백엔드는 이 목록으로도 교집합(AND)을 걸어 최종 결과를 만든 뒤, 그 결과를 5명씩 페이지네이션해 반환한다.
- **왜 프론트에서 거르지 않는가** — 백엔드가 먼저 5명씩 잘라 준 결과를 프론트가 다시 찜만 남기면, 그 페이지엔 찜 교수가 0~2명만 남고 `total`(예: 12)과도 어긋나 페이지 수 계산이 깨진다. 그래서 찜 필터는 반드시 백엔드 교집합 단계에서 처리한다.

찜 필터 처리 흐름:

```
① localStorage에서 찜 id 읽기        → ["P-001", "P-008", "P-013"]
② 검색 조건과 함께 백엔드에 전달      → query + filters(favoriteIds 포함)
③ 백엔드가 교집합(AND) 계산          → "심장" 검색 ∩ professorType ∩ 찜 id 목록
④ 그 결과를 5명씩 페이지네이션        → page / pageSize 기준으로 자름
⑤ 프론트에 반환                     → results + total (찜 필터까지 반영된 최종 수)
```

- `favoriteIds` 없음 / `null` — "찜한 교수만 보기"가 꺼진 기본 상태. 찜 필터 없이 전체 검색.
- `favoriteIds: []` (빈 배열) — 필터는 켰지만 찜한 교수가 0명. 교집합 결과 없음 → `results: []`, `total: 0`.
- `favoriteIds: ["P-001", ...]` — 필터 켜짐. 이 id들과 교집합을 걸어 반환.
- 찜 자체의 저장·추가·삭제는 그대로 localStorage 담당(아래 "찜하기 · 찜 취소 · 찜 목록" 참고). 바뀐 것은 "찜만 보기" 필터링 주체가 프론트 → 백엔드로 옮겨진 점뿐.

### API ② 교수 상세 조회 — `getProfessorById(id)`

- 트리거: 카드의 [자세히 보기] 클릭
- 요청: `GET /api/professors/{id}` (예: `/api/professors/P-012`)
- 응답: 교수 상세 객체(1-2)
- 없는 id: HTTP 404 + `{ "error": "not_found" }`

### API ③ 최근 연구 활동 교수 조회 — `getFeaturedProfessors()`

- 트리거: 교수 검색(메인) 페이지 진입 시
- 요청: `GET /api/professors/featured`
- 응답: `{ "results": [ 교수 카드 3~5개 ], "collectedAt": "..." }`
- 선정 기준 — 최근 논문을 낸 교수 → 데이터 수집이 어려울 시 이 기능은 생략

### 찜하기 · 찜 취소 · 찜 목록 — 백엔드 API 없음 (localStorage)

- 프론트 함수 `getFavorites()` / `addFavorite(id)` / `removeFavorite(id)`로 처리
- 로그인 미구현 결정에 따라 찜은 전부 브라우저 localStorage (로그인 없이 가능, 단 동일 기기에서만 유지)
- 저장 형태: 찜한 교수 id 배열 (예: `["P-012", "P-034"]`)
- 이 함수들은 실제 백엔드가 생겨도 fetch로 바뀌지 않고 그대로 유지됩니다 (교체 대상은 `getProfessors` / `getProfessorById` / `getFeaturedProfessors`)
- 단, "찜한 교수만 보기" 필터는 예외 — 찜의 저장·추가·삭제는 여전히 localStorage지만, 검색할 때는 이 localStorage 목록을 읽어 `filters.favoriteIds`로 백엔드에 보내 교집합 처리한다(위 API ① 참고).
- `isFavorite` · `favoriteDate`는 mock 데이터 테스트용으로만 사용. 백엔드 실제 응답(계약)에는 넣지 않음 (찜 상태·날짜는 localStorage 소관)

---

## 3. 프론트엔드 내부 처리 (백엔드 요청 불필요)

- 찜하기 / 찜 취소 / 찜 목록 조회 — localStorage
- 필터 초기화 — 현재 검색어는 유지하고, 교수 구분·찜한 교수만 보기 필터를 기본값으로 되돌린다. 필터 초기화 시 페이지는 1페이지로 돌아간다. MVP 정렬은 relevance 고정이므로 별도 초기화 대상이 아니다.
- 페이지네이션 — 응답의 `total`로 페이지 계산, 페이지 클릭 시 API ①을 `page`만 바꿔 재호출
- 논문 제목 클릭 → PubMed 이동 — `pmid`로 링크 생성
- 찜 여부 표시 — `id`를 localStorage와 대조

---

## 4. 값 없음 처리 규칙 (원칙 2 · 빈칸 절대 금지)

| 필드 | 값이 없을 때 | 화면 표시 |
| --- | --- | --- |
| `profileImageUrl` | `null` | 이니셜 아바타 |
| `email` | `null` | "정보 없음" |
| `labName` | `null` | "정보 없음" |
| `homepageUrl` | `null` | 링크 숨김 |
| `papers` | `[]` | "등록된 대표 논문 없음" |
| 검색 결과 | `results: []`, `total: 0` | "검색 결과가 없습니다 (정보 없음)" |

---

## 5. 백엔드·검색엔진팀에 확정 요청하는 항목

이 계약을 마무리하려면 아래 답이 필요합니다. (회의록 "확인이 필요한 사항"과 동일)

1. `matchScore`를 무슨 기준으로 계산하는가? (계약상 0~1 실수로만 정의, 계산법은 백엔드/검색엔진팀)
2. "찜한 교수만 보기" 필터 — 백엔드가 검색 요청의 `filters.favoriteIds`(찜한 교수 id 목록)를 받아 `query`·`professorType`와 교집합(AND)으로 처리하고, 그 결과를 페이지네이션해 `total`까지 반영해 줄 수 있는가? (`favoriteIds` 없음/`null`=전체 검색, `[]`=결과 없음으로 구분)
3. 최근 연구 활동 교수(API ③) 선정 기준 — 최근 논문을 낸 교수를 보여주기로 결정.
4. 로그인 기능은 구현하지 않기로 결정

---

## 6. 화면 ↔ API 매핑

| 화면 | 사용하는 것 |
| --- | --- |
| 1. 메인(교수 검색) | `getProfessors`(검색), `getFeaturedProfessors`(최근 연구 활동 교수) |
| 2. 검색 결과 | `getProfessors` → 교수 카드(1-1) |
| 3. 교수 상세 | `getProfessorById` |
| 4. 찜 목록 | localStorage(`getFavorites`) + `getProfessorById` |
| 5. 로그인 | MVP 미구현 |

> 프로토타입 연결: 프론트 `data/professors.js` 배열 1건이 곧 1-1 교수 카드 모양입니다. 지금은 `professorApi.js` 함수들이 이 mock 데이터를 걸러 반환하고, 백엔드가 완성되면 `professorApi.js` 내부만 fetch 호출로 교체하면 페이지 코드는 그대로 둡니다.
