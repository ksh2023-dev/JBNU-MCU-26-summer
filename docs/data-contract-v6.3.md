# 데이터 계약 문서 (프론트엔드 → 백엔드)

연수매칭 · 의대 연구 추천 시스템
수정: 김승하 · **v6.3**

> ## 📌 이 문서(v6.3)가 현재 최신 기준 문서입니다
>
> 프론트엔드·백엔드 구현의 기준(source of truth)은 **v6.3**입니다.
> `data-contract-v6.2.md` 이하 파일은 **이력 보존용**이며, 내용이 v6.3과 다르면 **v6.3이 우선**합니다.
>
> | 버전 | 파일 | 상태 |
> | --- | --- | --- |
> | **v6.3** | `docs/data-contract-v6.3.md` | **현재 기준** |
> | v6.2 | `docs/data-contract-v6.2.md` | 이력 (직전 버전) |
> | v6.1 · v6 | `docs/data-contract-v6.1.md` · `docs/data-contract-v6.md` | 이력 |

---

## 변경 이력

아래 각 절의 제목이 그 절이 설명하는 개정 버전입니다. 본문의 "이번 개정"과 같은 표현은 **그 절의 버전**을 가리킵니다.

### v6.2 → v6.3 (이번 개정 — 현재 문서)

이번 개정의 범위는 **찜 목록 화면(FavoritesPage)의 교수 데이터 조회 방식 확정 하나**입니다. 그 밖의 내용은 v6.2와 동일합니다.

- 찜 목록 화면의 **교수 데이터 조회 방식 확정** — 별도 Favorites API를 만들지 않고 기존 API ①을 재사용한다
- API ①에 **찜 목록 화면에서의 `filters.favoriteIds` 재사용 규칙** 명시 (`query: ""` + `favoriteIds`)
- `filters.favoriteIds`에 **존재하지 않는 교수 id가 섞인 경우의 처리 명시** — 교집합에서 제외하고 `total`은 실제 존재하는 교수 수
- 「찜하기 · 찜 취소 · 찜 목록」을 **찜 id 저장(localStorage)** 과 **교수 데이터 조회(API ①)** 로 나눠 기술
- 3장 "찜 목록 조회 — localStorage" 표현을 조회 주체에 맞게 수정
- 6장 화면 ↔ API 매핑에서 찜 목록 화면을 `getFavorites()` + API ① 방식으로 변경

> **요청/응답 필드와 엔드포인트는 v6.2와 완전히 동일합니다.** 새 API·새 필드는 추가하지 않았습니다.
> v6.3 개정은 이미 계약에 있는 API ①의 `filters.favoriteIds`를 찜 목록 화면에서 어떻게 쓰는지를 확정하는 것이 목적이며, **백엔드에 새로 구현할 동작도 없습니다.**

### v6.1 → v6.2 (이전 개정)

> 아래는 **v6.2 개정 시점의 기록**입니다. v6.3의 변경 범위가 아닙니다.

- API ① 교수 검색의 HTTP 경로·메서드 명시 — `POST /api/professors/search`
- `matchScore` 타입을 `number | null`로 명확화 (빈 검색어·featured에서는 `null`)
- 빈 검색어(`query: ""`) **browse 정책** 신설 — 이름 오름차순, `minScore` 미적용
- `query`의 **검색 대상 필드 확정** — 논문 초록 포함
- `relevance` 정렬에서 **동점 시 이름 오름차순** 명시
- API ③ 최근 연구 활동 교수 **선정 기준을 "가장 최근 논문 발행일 최신순"으로 구체화**
- featured **반환 기준을 최신순 상위 3명으로 확정**
- `collectedAt` 형식 명시 (`"YYYY-MM-DD"`)
- `minScore`의 `0.3`이 **개발용 임시값**임을 명시
- 할루시네이션 방지 **원칙 3 보완** — `minScore` 적용 대상을 검색어가 있는 경우로 한정하고, 빈 검색어(`query: ""`) 전체 조회에서는 `minScore`를 적용하지 않도록 예외를 명시
- 5장 「확정 요청 항목」을 실제로 **미확정인 항목만 남기도록 정리**

> 요청/응답의 **칸 이름과 구조는 v6.1과 동일**합니다. v6.2 개정은 그동안 문서에 비어 있던 규칙을 계약으로 확정하는 것이 목적이었으며, 대부분은 이미 백엔드에 구현되어 동작하는 내용입니다.
> **단, 모든 항목이 구현 완료된 것은 아닙니다.** 특히 **논문 초록 검색**은 v6.2에서 계약으로 확정한 사항이지만 현재 백엔드 검색 로직에는 아직 반영되지 않았습니다. 계약이 먼저 확정되고 구현이 뒤따르는 항목은 해당 위치에 별도로 표시했습니다.

### 그 이전

(v6 → v6.1: 필터 패널의 초기화 버튼은 검색어를 유지하고 필터만 초기화하도록 명확화 / 백엔드 API 요청·응답 구조 변경 없음)
(v5 → v6: getPopularProfessors → getFeaturedProfessors, 우수 교수 → 최근 연구 활동 교수, /api/professors/featured → 그대로)

---

> 읽는 법: "어떤 버튼을 누르면 → 프론트가 무엇을 요청하고 → 백엔드가 무슨 모양으로 응답하는지"의 약속입니다.
> 언어(프론트=JavaScript, 백엔드=Python/Java 등)는 서로 달라도 되지만, 주고받는 데이터의 모양(=칸 이름)은 이 문서로 똑같이 맞춥니다.
> 백엔드는 이 JSON 모양대로만 응답하면 되고, 프론트는 이 모양의 가짜 데이터(`data/professors.js`)로 화면을 먼저 만듭니다.

---

## 0. 대전제 — 할루시네이션 방지 4원칙

이 프로젝트는 없는 값을 지어내는 순간 서비스가 실패합니다. 아래 4원칙은 백엔드가 응답을 만들 때, 그리고 AI(Claude)로 데이터를 수집·정리·생성할 때 반드시 지킵니다.

1. 모든 논문에는 `pmid`가 필수. `pmid`가 없는 논문은 응답에 넣지 않는다.
2. 값이 없는 필드는 지어내지 말고 `null`로 보낸다. (화면 표시 문구 "정보 없음"은 프론트가 붙인다. 빈칸으로 두지 않는다)
3. **검색어가 있는 경우**, `matchScore`가 임계값(`minScore`) 미만인 교수는 결과에서 제외한다. 억지로 채우지 않는다.
   - 빈 검색어(`query: ""`) 전체 조회에서는 `matchScore`가 `null`이라 임계값 비교가 불가능하므로 `minScore`를 적용하지 않는다. (2장 API ① browse 정책)
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
- `matchScore` — **`number | null`** (아래 참고)
- 찜 여부·이메일은 카드에 넣지 않음 — 찜 여부는 프론트가 `id`를 localStorage와 대조해 판단, 이메일은 상세에서만 표시

#### `matchScore` — `number | null` (v6.2 확정)

| 상황 | 값 |
| --- | --- |
| 검색어가 있는 검색 결과 (`query`에 값 있음) | `0 ~ 1` 사이 실수 (관련도 점수) |
| 빈 검색어 전체 조회 (`query: ""`) | `null` |
| featured 교수 카드 (API ③) | `null` |

- **`matchScore: null`은 값이 누락된 오류가 아닙니다.** 해당 상황에서는 검색어가 없어 관련도 점수를 계산하지 않았다는 **정상 상태**입니다. (원칙 2·3 — 근거 없는 점수를 지어내지 않는다)
- 위 예시 JSON의 `0.87`은 검색 결과 기준 값입니다.
- 프론트는 `matchScore`가 항상 숫자라고 가정하지 않습니다. 현재 교수 카드 UI는 점수를 화면에 표시하지 않으므로 `null`이어도 렌더링에 문제가 없습니다.

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

| 계약 | 경로 | 프론트 함수 |
| --- | --- | --- |
| API ① 교수 검색·목록 조회 | `POST /api/professors/search` | `getProfessors(query, filters)` |
| API ② 교수 상세 조회 | `GET /api/professors/{id}` | `getProfessorById(id)` |
| API ③ 최근 연구 활동 교수 조회 | `GET /api/professors/featured` | `getFeaturedProfessors()` |

### API ① 교수 검색·목록 조회 — `getProfessors(query, filters)`

- 트리거: 검색 버튼 / Enter, 필터 선택 시 즉시 재조회, 페이지 번호 클릭
- **요청 방식 (v6.2 확정)**

```text
POST /api/professors/search
Content-Type: application/json
```

아래 요청 JSON을 이 엔드포인트의 **요청 본문(body)** 에 담아 보냅니다.

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

(`filters.favoriteIds`는 검색 결과 화면의 "찜한 교수만 보기"가 ON일 때, 그리고 찜 목록 화면에서 포함한다 — 아래 "찜한 교수만 보기" 필터 참고)

#### 요청 필드 기본값·제약

| 필드 | 타입 | 기본값 | 비고 |
| --- | --- | --- | --- |
| `query` | string | `""` | 빈 문자열이면 전체 목록 조회(browse) |
| `filters.professorType` | string[] | `[]` | 빈 배열이면 전체. 허용값: `기초의학` / `임상의학` / `의학교육학` / `인문사회의학` |
| `filters.favoriteIds` | string[] \| null | `null` | `null`·없음 = 찜 필터 OFF, `[]` = 찜 필터 ON + 찜 0명 → 결과 0. 찜 목록 화면은 항상 배열로 보낸다 |
| `sort` | string | `"relevance"` | MVP는 `relevance`만 지원 |
| `minScore` | number | `0.3` (**개발용 임시값**) | 0 ~ 1 |
| `page` | number | `1` | 1 이상 |
| `pageSize` | number | `5` | 한 페이지에 보여줄 교수 수 |

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

- `total` — 전체 결과 수. 프론트가 이 값으로 페이지 수 계산(5명씩). **모든 필터를 적용한 뒤의 최종 개수**이며, 페이지를 자르기 전 값이다
- `page` · `pageSize` — 요청한 값을 그대로 되돌려준다
- `collectedAt` — 데이터 수집 기준일
  - `"YYYY-MM-DD"` 형식 문자열 (예: `"2026-08-09"`)
  - 원본 데이터 파일의 기준일이며, 요청할 때마다 바뀌는 값이 아니다 (원칙 4)

#### 검색 대상 필드 (v6.2 확정)

`query`는 아래 필드에서 **부분일치(대소문자 무시)** 로 검색한다.

- 교수명 (`name`)
- `keywords`
- `specialties`
- 논문 제목
- **논문 초록**
- 소속 (`department`)

> ⚠️ **논문 초록 검색은 v6.2 계약상 확정 사항이며, 현재 백엔드 검색 로직에는 반영이 필요하다.** 나머지 대상 필드는 이미 구현되어 동작한다.

#### 정렬 규칙 (v6.2 확정)

```text
query가 있는 경우:
- matchScore 내림차순
- matchScore 동점이면 이름 오름차순

query가 없는 경우:
- 이름 오름차순
```

- 동점 시 이름 오름차순을 쓰는 이유 — 순서를 고정해 두지 않으면 페이지를 넘길 때 같은 점수의 교수 순서가 흔들려 **중복되거나 누락**될 수 있다
- `sort` — MVP는 `relevance`(관련도순)만 사용한다

#### 빈 검색어(`query: ""`) — 전체 목록 조회(browse) (v6.2 확정)

`query: ""`는 **검색 실패가 아니라 전체 교수 목록 조회(browse)** 로 간주한다. (첫 진입, 검색어를 지운 경우, 필터만 건 경우)

| 항목 | 동작 |
| --- | --- |
| `filters.professorType` | 그대로 적용 |
| `filters.favoriteIds` | 그대로 적용 |
| `matchScore` | `null` — 점수를 만들 근거가 없으므로 지어내지 않는다 (원칙 2) |
| `minScore` | **적용하지 않는다** — `matchScore`가 `null`이라 "임계값 미만" 판정이 불가능하다 |
| 정렬 | **이름 오름차순** |
| 페이지네이션 | 위 필터·정렬을 모두 마친 뒤 `page` / `pageSize` 기준으로 자른다 |
| `total` | 필터 적용 후 전체 결과 수 |

정리하면:

```text
query 있음
→ matchScore 계산
→ minScore 적용
→ matchScore 내림차순
→ 동점이면 이름 오름차순

query 없음
→ 전체 목록 조회
→ matchScore = null
→ minScore 미적용
→ 이름 오름차순
```

> ⚠️ 이 규칙은 `sort: "name"` 같은 **새로운 요청 값을 추가한다는 뜻이 아니다.** MVP의 `sort` 요청값은 기존과 동일하게 `"relevance"` 하나뿐이며, 빈 `query`일 때 백엔드가 browse 정책에 따라 이름순으로 처리하는 **예외 규칙**이다.
> 프론트는 빈 검색어일 때도 `minScore`를 그대로 실어 보내도 된다. 백엔드가 무시한다.

#### `minScore`

- 이 값 미만의 `matchScore`를 가진 교수는 백엔드가 결과에서 제외한다 (원칙 3)
- **현재 개발용 임시 기본값: `0.3`** — 프론트와 백엔드가 임시로 맞춰 둔 자리표시자다
- **최종 threshold는 추후 확정** (5장 참고). `matchScore` 산식이 바뀌면 점수 분포가 달라지므로 함께 재조정한다
- 빈 `query`에서는 위 browse 정책에 따라 **적용하지 않는다**

#### "찜한 교수만 보기" 필터 (`filters.favoriteIds`)

프론트가 localStorage의 찜 id 목록을 읽어 `filters.favoriteIds`로 검색 요청에 실어 보낸다. 백엔드는 이 목록으로도 교집합(AND)을 걸어 최종 결과를 만든 뒤, 그 결과를 5명씩 페이지네이션해 반환한다.

- **왜 프론트에서 거르지 않는가** — 백엔드가 먼저 5명씩 잘라 준 결과를 프론트가 다시 찜만 남기면, 그 페이지엔 찜 교수가 0~2명만 남고 `total`(예: 12)과도 어긋나 페이지 수 계산이 깨진다. 그래서 찜 필터는 반드시 백엔드 교집합 단계에서 처리한다.

찜 필터 처리 흐름:

```
① localStorage에서 찜 id 읽기        → ["P-001", "P-008", "P-013"]
② 검색 조건과 함께 백엔드에 전달      → query + filters(favoriteIds 포함)
③ 백엔드가 교집합(AND) 계산          → "심장" 검색 ∩ professorType ∩ 찜 id 목록
④ 그 결과를 5명씩 페이지네이션        → page / pageSize 기준으로 자름
⑤ 프론트에 반환                     → results + total (찜 필터까지 반영된 최종 수)
```

세 가지 상태:

- `favoriteIds` 없음 / `null` — "찜한 교수만 보기"가 꺼진 기본 상태. 찜 필터 없이 전체 검색.
- `favoriteIds: []` (빈 배열) — 필터는 켰지만 찜한 교수가 0명. 교집합 결과 없음 → `results: []`, `total: 0`.
- `favoriteIds: ["P-001", ...]` — 필터 켜짐. `query` ∩ `professorType` ∩ 이 id 목록의 교집합을 걸어 반환.

- 교집합을 모두 적용한 **뒤에** 페이지네이션을 수행하고, `total`도 최종 필터 결과 수를 반환한다.
- 찜 자체의 저장·추가·삭제는 그대로 localStorage 담당(아래 "찜하기 · 찜 취소 · 찜 목록" 참고). 바뀐 것은 "찜만 보기" 필터링 주체가 프론트 → 백엔드로 옮겨진 점뿐.

#### 존재하지 않는 교수 id가 섞인 경우 (v6.3 명시)

`favoriteIds`에 **DB에 존재하지 않는 교수 id**가 들어 있을 수 있다. localStorage에 남아 있는데 데이터가 갱신되면서 사라진 교수가 대표적인 경우다.

- 없는 id는 교집합 단계에서 **제외**된다. 백엔드는 없는 교수를 만들어 채우지 않는다 (원칙 2)
- `total`은 **실제로 존재하는 교수 수**를 반환한다
- 그 결과 프론트 localStorage의 찜 개수와 응답 `total`이 다를 수 있다. 화면에 표시하는 수는 언제나 응답의 `total`을 기준으로 하며, 프론트가 localStorage 길이로 대신 세지 않는다

```text
localStorage 찜 id : ["P-001", "P-008", "P-999"]   ← P-999 는 존재하지 않음
교집합 결과        : ["P-001", "P-008"]
응답               : total = 2  (3 이 아니다)
```

- 이는 v6.2에서 이미 정한 교집합 규칙의 자연스러운 결과이며, **백엔드 동작 변경 없이 문서로 명시만 한 것이다**

#### 찜 목록 화면(FavoritesPage)의 교수 데이터 조회 (v6.3 확정)

찜 목록 화면은 **별도의 백엔드 API를 두지 않고 API ①을 그대로 재사용한다.**

- 찜 id의 저장·추가·삭제는 기존과 동일하게 localStorage가 담당한다
- 화면은 `getFavorites()`로 읽은 찜 id 배열을 `filters.favoriteIds`에 실어 API ①을 호출한다
- 교수별로 API ② `getProfessorById()`를 찜 개수만큼(N번) 호출하지 않는다

요청:

```json
{
  "query": "",
  "filters": { "professorType": [], "favoriteIds": ["P-001", "P-008"] },
  "sort": "relevance",
  "minScore": 0.3,
  "page": 1,
  "pageSize": 5
}
```

- `query`가 항상 `""`이므로 위 **browse 정책이 그대로 적용된다.** 즉 `matchScore`는 `null`, `minScore`는 **미적용**, 정렬은 **이름 오름차순**이다. (`minScore`는 값을 실어 보내도 되고, 백엔드가 무시한다)
- 교집합 · 정렬 · 페이지네이션 · `total` 계산은 전부 백엔드가 수행한다. 프론트는 응답을 다시 거르거나 정렬하거나 자르지 않는다
- 응답 `results`는 교수 카드(1-1)이며, 찜 목록 화면도 검색 결과와 같은 카드 UI를 사용한다
- 이 화면에서 `filters.favoriteIds`는 **항상 배열**이다. `null`로 보내지 않는다 — `null`은 "찜 필터 꺼짐 = 전체 교수 목록"을 뜻해 찜 목록 화면의 의미와 정반대가 된다

**찜이 0명일 때 (`favoriteIds: []`)**

| 항목 | 값 |
| --- | --- |
| 응답 `results` | `[]` |
| 응답 `total` | `0` |
| 화면 | 찜 목록 비어 있음(empty state)으로 그린다. "검색 결과가 없습니다"가 아니다 |

- 찜 목록 화면의 빈 상태는 **검색 실패가 아니라 "아직 찜한 교수가 없음"** 이다. 화면 문구도 그에 맞게 쓴다
- 없는 id만 들어 있어 교집합 결과가 0이 된 경우(`total: 0`)도 화면에서는 같은 빈 상태로 처리한다

> 백엔드가 새로 구현할 것은 없다. 검색 결과 화면의 "찜한 교수만 보기"와 완전히 같은 요청이고, 다른 점은 `query`가 항상 비어 있다는 것뿐이다.

### API ② 교수 상세 조회 — `getProfessorById(id)`

- 트리거: 카드의 [자세히 보기] 클릭
- 요청: `GET /api/professors/{id}` (예: `/api/professors/P-012`)
- 응답: 교수 상세 객체(1-2)
- 없는 id: HTTP 404 + `{ "error": "not_found" }`

### API ③ 최근 연구 활동 교수 조회 — `getFeaturedProfessors()`

- 트리거: 교수 검색(메인) 페이지 진입 시
- 요청: `GET /api/professors/featured`
- 응답: `{ "results": [ 교수 카드 배열 ], "collectedAt": "..." }`
- `collectedAt` — API ①과 동일하게 데이터 수집 기준일. `"YYYY-MM-DD"` 형식 문자열 (예: `"2026-08-09"`)이며, 요청할 때마다 바뀌는 값이 아니다 (원칙 4)

#### 선정 기준 (v6.2 구체화)

- 교수별 **가장 최근 논문의 발행일**을 기준으로 **최신순(내림차순)** 정렬해 상위 3명을 반환한다
- 가장 최근 논문 정보가 없는 교수는 **featured 후보에서 제외**한다 (없는 값을 지어내지 않는다 — 원칙 2)
- 선정 기준값은 백엔드 내부 데이터의 `latestPaper.publishedAt`을 사용한다
- **`latestPaper`는 백엔드 내부 선정용 필드다.** 교수 카드(1-1)와 교수 상세(1-2) 응답에는 **포함되지 않는다.** 프론트는 이 필드를 받지 않으며 알 필요도 없다
- featured 교수 카드의 `matchScore`는 검색어가 없으므로 항상 `null`

#### 반환 개수 — **3명 확정** (v6.2)

- **MVP 계약상 featured 반환 기준값은 3명으로 확정한다.** (v6.1의 "3~5개" 표기는 이 규칙으로 대체된다)
- 교수별 가장 최근 논문의 발행일 기준 **최신순으로 정렬해 상위 3명**을 반환한다
- **선정은 백엔드가 수행한다.** 프론트는 별도로 `slice(0, 3)` 하지 않고 받은 결과를 그대로 표시한다
- 백엔드에는 반환 수를 조정할 수 있는 `FEATURED_COUNT` 설정이 있으며 **기본값은 `3`**이다. **MVP에서는 해당 값을 3으로 사용한다.** 추후 반환 수 변경이 필요한 경우 팀 협의 후 조정한다

**예외 — 유효 후보가 3명 미만인 경우**

> 최근 논문 정보가 있는 교수 중 최신순 상위 3명을 반환한다. 유효한 featured 후보가 3명 미만인 경우에는 **존재하는 후보만 반환하며, 없는 교수를 임의로 채우지 않는다.** (0장 원칙 2)

- 여기서 "3명 고정"은 **선정 기준값 N=3을 고정한다**는 뜻이다. 유효 후보 자체가 3명 미만일 때 가짜 데이터를 만들어 배열 길이를 항상 3으로 맞춘다는 뜻이 아니다
- 프론트는 이 예외 상황에서 **받은 개수만큼만** 렌더링한다

### 찜하기 · 찜 취소 · 찜 목록

찜은 **"id 저장"과 "교수 데이터 조회"를 나눠서** 처리한다. (v6.3에서 구분을 명확히 함)

#### ① 찜 id의 저장 · 추가 · 삭제 — 백엔드 API 없음 (localStorage)

- 프론트 함수 `getFavorites()` / `addFavorite(id)` / `removeFavorite(id)`로 처리
- 로그인 미구현 결정에 따라 찜은 전부 브라우저 localStorage (로그인 없이 가능, 단 동일 기기에서만 유지)
- 저장 형태: 찜한 교수 id 배열 (예: `["P-012", "P-034"]`)
- 이 세 함수는 실제 백엔드가 생겨도 fetch로 바뀌지 않고 그대로 유지됩니다 (교체 대상은 `getProfessors` / `getProfessorById` / `getFeaturedProfessors`)
- `isFavorite` · `favoriteDate`는 mock 데이터 테스트용으로만 사용. 백엔드 실제 응답(계약)에는 넣지 않음 (찜 상태·날짜는 localStorage 소관)

#### ② 찜한 교수의 데이터 조회 — API ① (백엔드)

localStorage가 갖고 있는 것은 **id뿐**이라, 화면에 그릴 이름 · 소속 · 전문 분야 · 키워드는 백엔드에서 받아야 한다. 이 조회는 아래 두 화면 모두 **API ①** 이 담당한다.

| 화면 | 요청 |
| --- | --- |
| 검색 결과의 "찜한 교수만 보기" ON | `query`(사용자 검색어) + `filters.favoriteIds` 교집합 |
| 찜 목록 화면(FavoritesPage) | `query: ""` + `filters.favoriteIds` (v6.3 확정, 위 API ① 참고) |

- 두 경우 모두 백엔드가 교집합을 건 **뒤에** 페이지를 자르고 `total`을 계산한다
- 찜 목록 조회를 위한 **별도 엔드포인트는 만들지 않는다**

정리하면 **찜의 저장 주체는 localStorage, 찜한 교수 데이터의 조회 주체는 백엔드(API ①)** 다.

---

## 3. 프론트엔드 내부 처리 (백엔드 요청 불필요)

- 찜하기 / 찜 취소 / 찜 **id 목록 읽기** — localStorage (`addFavorite` / `removeFavorite` / `getFavorites`)
  - 단, 찜 목록 화면에 그릴 **교수 데이터 조회는 백엔드 요청(API ①)이 필요하므로 이 장에 해당하지 않는다** (v6.3, 2장 API ① 참고)
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
| `specialties` · `keywords` | `[]` | 해당 영역 표시 생략 |
| `matchScore` | `null` (빈 검색어 · featured) | 점수를 표시하지 않음 (현재 카드 UI는 점수 미노출) |
| 검색 결과 | `results: []`, `total: 0` | "검색 결과가 없습니다 (정보 없음)" |
| featured 결과 | 유효 후보가 3명 미만이면 있는 만큼만 (없는 교수를 채우지 않음) | 후보가 충분하면 3명 표시 / 3명 미만이면 받은 개수만큼 표시 |

---

## 5. 아직 확정이 필요한 항목

이 계약을 마무리하려면 아래 답이 필요합니다.

1. **`matchScore` 최종 산식** — 계약상 `0~1` 실수(또는 `null`)로만 정의되어 있고, 계산 방법은 백엔드/검색엔진팀 소관입니다. 현재 백엔드에 MVP 산식이 구현되어 동작하고 있으나 **팀 최종 확정은 아닙니다.**
2. **`minScore` 최종 threshold** — 현재 `0.3`은 프론트/백엔드가 개발용으로 임시로 맞춰 둔 값입니다. `matchScore` 산식이 확정되면 점수 분포에 맞춰 함께 정합니다.

### 이미 결정되어 이 목록에서 내려온 항목

| 항목 | 결정 내용 |
| --- | --- |
| "찜한 교수만 보기" 백엔드 교집합 처리 | **해결** — 백엔드가 `filters.favoriteIds`를 받아 `query`·`professorType`과 교집합(AND)으로 처리하고, 페이지네이션과 `total`까지 반영한다 (2장 API ①) |
| 빈 `query` 처리 정책 | **확정** — 전체 목록 조회(browse). 이름 오름차순, `minScore` 미적용, `matchScore: null` |
| `matchScore`의 `null` 허용 | **확정** — `number \| null`. 검색어가 없는 맥락에서는 `null`이 정상 |
| 최근 연구 활동 교수(API ③) 선정 기준 | **확정** — 가장 최근 논문의 발행일 최신순. 발행 정보 없는 교수는 후보 제외 |
| featured 반환 개수 | **확정** — 최근 논문 발행일 최신순 상위 3명. 유효 후보가 3명 미만이면 존재하는 후보만 반환 |
| 검색 대상 필드 | **확정** — 교수명 · `keywords` · `specialties` · 논문 제목 · **논문 초록** · `department` |
| API ① HTTP 경로·메서드 | **확정** — `POST /api/professors/search` |
| 로그인 기능 | **미구현으로 결정** — 찜은 localStorage로 처리 |
| 찜 목록 화면의 교수 데이터 조회 방식 | **확정 (v6.3)** — 별도 Favorites API를 만들지 않고 API ①을 재사용한다. `query: ""` + `filters.favoriteIds`로 요청하고 교집합 · 이름 오름차순 · 페이지네이션 · `total`은 백엔드가 처리한다 (2장 API ①) |

---

## 6. 화면 ↔ API 매핑

| 화면 | 사용하는 것 |
| --- | --- |
| 1. 메인(교수 검색) | `getProfessors`(검색), `getFeaturedProfessors`(최근 연구 활동 교수) |
| 2. 검색 결과 | `getProfessors` → 교수 카드(1-1) |
| 3. 교수 상세 | `getProfessorById` |
| 4. 찜 목록 | localStorage(`getFavorites`)로 찜 id 읽기 + API ① `getProfessors("", { filters: { favoriteIds } })` → 교수 카드(1-1) |
| 5. 로그인 | MVP 미구현 |

### 프론트 API 연결 현황 (v6.3 시점)

프론트 `data/professors.js` 배열 1건이 곧 1-1 교수 카드 모양입니다. 이 mock 데이터는 백엔드 연결 전에 화면을 먼저 만들기 위한 것이며, 함수 이름·인자·반환 모양을 계약대로 맞춰 두었기 때문에 **`professorApi.js` 내부만 바꾸면 페이지 코드는 그대로 둘 수 있습니다.**

| 프론트 함수 | 계약 | 현재 상태 |
| --- | --- | --- |
| `getProfessors()` | API ① | **실제 백엔드 호출** — `POST /api/professors/search` |
| `getProfessorById()` | API ② | **실제 백엔드 호출** — `GET /api/professors/{id}` |
| `getFeaturedProfessors()` | API ③ | **실제 백엔드 호출** — `GET /api/professors/featured` |
| `getFavoriteProfessors()` | (계약 엔드포인트 아님) | **아직 `data/professors.js` mock 기반** |

- 계약의 API ①·②·③은 **모두 실제 백엔드에 연결되어 있습니다.** mock 데이터로 응답하는 계약 API는 없습니다
- `getFavoriteProfessors()`는 찜 목록 화면이 쓰던 **프론트 내부 헬퍼**이며 계약의 엔드포인트가 아닙니다. v6.3에서 찜 목록 조회를 API ① 재사용으로 확정했으므로, 이 함수는 새 엔드포인트가 아니라 `getProfessors("", { filters: { favoriteIds } })` 호출로 **대체**됩니다 (2장 API ① 참고)
- 따라서 `data/professors.js`는 이 대체가 끝나면 계약 응답과 무관한 테스트용 자료로만 남습니다
