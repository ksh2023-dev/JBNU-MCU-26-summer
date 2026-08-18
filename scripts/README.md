# scripts — 데이터 수집 스크립트 모음

하위 폴더별로 나뉘어 있던 README를 이 문서 하나로 합쳤습니다. 의존성도 폴더별 venv/requirements 대신
**`scripts/requirements.txt` 하나**로 통일했습니다 (2026-08-15).

| 폴더 | 스크립트 | 하는 일 | 출력 |
| --- | --- | --- | --- |
| `roster_crawler/` | `crawl_roster.py` | 의대 홈페이지에서 교수 명단 수집 + 병원 명단과 diff | `data/output/roster_crawled.json` |
| `profile_image_collector/` | `fetch_image_urls.py` | 병원 프로필 페이지에서 사진 URL만 수집 | `data/output/profile_images.json` |
| `pubmed_collector/` | `fetch_one.py` → `enrich_citations.py` → `build_all.py` | 논문 수집(1단계) → 인용수+대표 3편(2단계) → 243명 전체 파이프라인(3단계) | `data/output/professors_papers.json` 등 |

모든 스크립트 공통 원칙:

- 데이터 계약(`docs/data-contract-v6.4.md`) 0장 **할루시네이션 방지 4원칙**을 따릅니다 — 없는 값은 `null`, 논문은 **`pmid` 또는 `kciId` 중 하나가 필수**(둘 다 없는 논문은 저장 금지, v6.4), 확신 없는 값은 `review`에 기록.
- 운영 중인 서버 예절: 요청 사이 0.4~0.5초 대기, 실패 시 1회 재시도 후 `null`/`review` 처리하고 전체 실행은 계속.
- 파일 상단의 `LIMIT` 상수로 앞 N명만 테스트 실행 가능 (`None`이면 전체). **전체 실행 전 LIMIT으로 먼저 검증하세요.**
- `data/output/`은 `.gitignore` 대상이라 커밋되지 않습니다. `data/input` 승격은 검수 후 사람이 결정합니다.

## 공통 준비 (처음 한 번만)

### 1. 가상환경 만들기·활성화

저장소 루트에서:

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

- 성공하면 프롬프트 맨 앞에 `(.venv)`가 붙습니다. 터미널을 새로 열 때마다 활성화 명령만 다시 실행합니다.
- ⚠️ Windows에서 "이 시스템에서 스크립트를 실행할 수 없으므로..." 오류가 나면 한 번만 실행:
  `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- `'python' 용어가 인식되지 않습니다` → `py`로 실행해 보고, 안 되면 [python.org](https://www.python.org/downloads/)에서 설치 (Python 3.9 이상, "Add python.exe to PATH" 체크).

### 2. 라이브러리 설치 — 통합 requirements

```powershell
pip install -r scripts/requirements.txt
```

- scripts 전체의 외부 의존성은 현재 `requests` 하나입니다.
- `profile_image_collector`·`roster_crawler`는 표준 라이브러리만 쓰지만, 위 한 번의 설치로 모든 스크립트가 동작합니다.

### 3. OpenAlex API 키 (.env) — pubmed_collector 2·3단계에만 필요

OpenAlex는 **2026-02-13부터 mailto(polite pool) 방식을 폐지**하고 모든 API 호출에 무료 계정의 `api_key`를
요구합니다. 키는 공개 저장소에 커밋하지 않도록 코드가 아니라 **저장소 루트의 `.env` 파일**에서 읽습니다.
(PubMed 호출에는 키가 필요 없습니다.)

1. [openalex.org](https://openalex.org/)에서 무료 계정을 만들고, 설정(Settings)에서 API 키를 복사합니다.
2. 루트의 `.env.example`을 복사해 루트에 `.env`를 만들고 값을 채웁니다:

```text
OPENALEX_API_KEY=발급받은키
```

- `.env`는 `.gitignore`에 등록되어 있어 **커밋되지 않습니다.** (그래도 커밋 전 `git status`로 한 번 확인하세요)
- 키 없이 2·3단계를 실행하면 발급 방법을 안내하고 멈춥니다(exit 1).

---

# 1. 교수 명단 크롤러 (`roster_crawler/crawl_roster.py`)

전북대 의대 홈페이지의 **교실/교수** 메뉴를 따라 들어가(허브 → 교실 → 분과) 교수 명단을 수집하고,
기존 병원 기반 명단(`data/input/professor_pages.json`, 243명)과 **이름을 대조(diff)** 해서
`data/output/roster_crawled.json`으로 저장합니다.

목적: ① 홈페이지 기반의 **갱신 가능한 교수 명단** 확보(신규 임용 대응)
② 병원 명단에 **빠져 있을 수 있는 기초의학 계열 교수** 커버리지 확인.

> **영문명(nameEn)에 대해** — 의대 영문판 사이트에는 교수 명단이 없는 것으로 확인되어(학과 소개만 있음)
> 영문명 수집과 한↔영 매칭은 이번 범위에서 제외했습니다. `nameEn`은 전원 `null`이며,
> 추후 논문 저자 정보에서 채울 예정입니다.

- 수집 항목: `name`(한글) · `professorType`(기초의학/임상의학/의학교육학/인문사회의학) ·
  `department`(교실) · `division`(내과학교실 분과, 없으면 null) · `position`(직위) ·
  `specialty`(전공) · `phone` · `homepageUrl`
- 페이지에 없는 값은 `null`, 확신 없는 값은 넣지 않고 `review`에 기록.
- 운영 중인 학교 홈페이지라 요청 사이 0.5초씩 쉬고, 병렬 없이 순차 수집합니다.

## 실행 방법

1. **URL 확인** — `crawl_roster.py` 상단의 `LIST_URL_KO`가 교수소개 허브 페이지인지 확인합니다.
   (기본값: `https://med.jbnu.ac.kr/med/12619/subview.do` / `REPLACE_ME`면 안내 후 중단)
2. **LIMIT 검증** — `LIMIT = 5`로 앞 5명만 수집해 교실 목록·수집 로그·통계가 정상인지 확인합니다.
   LIMIT 상태에서는 수집 인원이 적어 `diff.hospitalOnly`가 수백 명으로 나오는 것이 **정상**입니다
   (전체 실행에서만 diff가 의미를 가집니다).

   ```powershell
   python scripts/roster_crawler/crawl_roster.py
   ```

3. **전체 실행** — `LIMIT = None`으로 되돌리고 같은 명령을 실행합니다. 40여 페이지를 0.5초 간격으로
   돌므로 1~2분쯤 걸립니다.

## diff 읽는 법

| 칸 | 뜻 | 활용 |
| --- | --- | --- |
| `diff.newOnly` | **의대 홈페이지에만** 있는 교수 (이름·대분류·교실) | 병원 명단에 없던 기초의학 계열 교수일 가능성 — 명단 보강 후보 |
| `diff.matched` | 양쪽 명단에 모두 있는 인원 수 | 커버리지 확인 |
| `diff.hospitalOnly` | **병원 명단에만** 있는 이름 | 의대 홈페이지 미게시·퇴직·표기 차이 등 — 검수 대상 |
| `review` | 요청 실패·이름 표기 특이 등 확인이 필요한 기록 | 사람이 하나씩 확인 |

- 이름 대조는 **공백을 뺀 한글 이름** 기준입니다. 동명이인은 같은 이름으로 묶이므로
  `newOnly`/`hospitalOnly`에 안 보인다고 같은 사람이라는 보장은 없습니다 (검수 필요).

## 자주 생기는 문제 (roster_crawler)

| 증상 | 원인과 해결 |
| --- | --- |
| `LIST_URL_KO를 … 채운 뒤 다시 실행하세요.` | 상단 상수가 `REPLACE_ME`인 상태 → URL 채우기 |
| `교실 메뉴를 찾지 못함 — 페이지 구조 변경 의심` (review) | 홈페이지 개편으로 메뉴 마크업이 바뀐 것 → probe부터 다시 필요 |
| `요청 실패: …` (review) | 일시적 통신 오류 → 다시 실행 (해당 페이지만 다시 시도됨) |
| `페이지네이션 감지 …` (review) | 교실 페이지가 여러 쪽으로 나뉜 구조로 바뀐 것 → 스크립트 보강 필요 |

---

# 2. 프로필 사진 URL 수집기 (`profile_image_collector/fetch_image_urls.py`)

전북대병원 홈페이지의 교수 프로필 페이지(243명)에서 **프로필 사진의 URL만** 모아
`data/output/profile_images.json`으로 저장합니다.

- 이미지 파일을 다운로드하지 않습니다. URL 문자열만 수집합니다.
- 사진이 없거나 기본(placeholder) 이미지인 교수는 `null`로 기록합니다.
- 입력 파일: `data/input/professor_pages.json` (repo에 이미 포함되어 있음)

## 실행 방법

```bash
python scripts/profile_image_collector/fetch_image_urls.py
```

- 다른 폴더에서 실행해도 경로를 스크립트 위치 기준으로 계산하므로 정상 동작합니다.
- 전체 243명 실행 시 호출 사이 0.5초씩 기다리므로 **약 5~10분** 걸립니다.
- 테스트: 파일 상단 `LIMIT = 10`으로 앞 10명만 확인 후 `None`으로 되돌리기.
- 10명 단위로 진행 상황이 출력되고, 끝나면 통계가 나옵니다: `완료: 성공 N / 사진 없음 N / 요청 실패 N`

## 출력 파일 모양

```json
{
  "collectedAt": "2026-08-15",
  "source": "https://www.jbuh.co.kr 교수 프로필 페이지",
  "images": {
    "유희철": "https://www.jbuh.co.kr/thumbnail/mdclStf/MS_202506271000151320.PNG",
    "양재도": null
  }
}
```

## 사진을 어떻게 찾나요?

프로필 페이지의 정적 HTML 안에 교수 사진이 아래 형태로 들어 있습니다 (2026-08-15 사전 확인).

```html
<img src="/thumbnail/mdclStf/MS_2025....PNG" alt="유희철 대표 이미지">
```

같은 페이지에 placeholder(`no-img.png`) · 타 교수 배너 · 사이트 로고 이미지가 섞여 있어서,
**src 경로에 `/thumbnail/mdclStf/`가 있고 + alt에 교수명이 포함된 이미지**만 본인 사진으로 인정합니다.
둘 중 하나라도 어긋나면 안전하게 `null`로 둡니다.

## 참고 사항

- 프로필 사진은 **비영리·내부 테스트 용도** 사용으로 팀장 승인을 받았습니다 (2026-08 작업지시서).
- 수집 결과를 서비스 데이터에 반영할 때는 `profileImageUrl` 필드 규칙(`docs/data-contract-v6.4.md` 1-1장)을 따릅니다.

---

# 3. PubMed 수집기 (`pubmed_collector/`)

| 단계 | 스크립트 | 하는 일 |
| --- | --- | --- |
| 1단계 | `fetch_one.py` | 교수 1명 영문명으로 PubMed 검색 → 논문 상세 수집 (검증용) |
| 2단계 | `enrich_citations.py` | OpenAlex 인용수 부착 + 대표 논문 3편 선정 (교수 1명 기준) |
| 3단계 | `build_all.py` | 243명 전체: 인용문 → 제목 검색 → 1·2단계 부품 재사용 → 한 파일로 조립 |

PubMed 공식 API(E-utilities)는 **API 키가 필요 없습니다.** OpenAlex 키(2·3단계)는 위 공통 준비 3번 참고.

## 3-1. 1단계: 교수 1명 검증용 (`fetch_one.py`)

교수 1명의 **영문명**으로 PubMed를 검색해 논문 정보(제목·학술지·연도·PMID·초록·발행일)를
`data/output/professor_test.json`으로 저장합니다.

1. `fetch_one.py` 상단의 상수를 실제 교수 영문명으로 바꿉니다:

   ```python
   AUTHOR_NAME_EN = "Gil Dong Hong"   # ← "REPLACE_ME"를 실제 이름으로 교체
   ```

   이름 표기는 PubMed에 등록된 형태를 따라야 합니다. 검색이 0건이면
   [pubmed.ncbi.nlm.nih.gov](https://pubmed.ncbi.nlm.nih.gov/)에서 직접 검색해 표기(하이픈·띄어쓰기)를 확인하세요.

2. 실행:

   ```powershell
   python scripts/pubmed_collector/fetch_one.py
   ```

3. 결과: `data/output/professor_test.json`. 콘솔의 `초록 없음: PMID XXXX`는 오류가 아니라
   PubMed에 초록이 없는 것 → `abstract: null`로 저장되며, **사람이 한 번 검수**하라는 표시입니다.

저장되는 JSON 모양:

```json
{
  "collectedAt": "2026-08-15",
  "authorQuery": "Gil Dong Hong[Author] AND Jeonbuk National University[Affiliation]",
  "papers": [
    {
      "title": "논문 제목",
      "journal": "학술지 이름",
      "year": 2024,
      "pmid": "12345678",
      "publishedAt": "2024-05-01",
      "abstract": "초록 본문 (없으면 null)"
    }
  ]
}
```

## 3-2. 2단계: 인용수 수집 + 대표 논문 3편 선정 (`enrich_citations.py`)

1단계가 만든 `data/output/professor_test.json`을 읽어,

1. 각 논문의 **인용수**를 [OpenAlex](https://openalex.org/)에서 받아 `citedByCount` 칸으로 붙이고,
2. 데이터 계약 1-2의 규칙 **"최신순 1편 + 인용수 상위 2편 = 3편"** 으로 대표 논문을 뽑아
3. `data/output/professor_test_enriched.json`으로 저장합니다.

- 인용수는 PMID로 조회하며, **50개씩 묶어서** 요청합니다 (논문 수만큼 호출하지 않기 위함).
- OpenAlex에 등록되지 않은 논문의 인용수는 **`0`이 아니라 `null`** 로 둡니다.

실행 (.env에 OpenAlex 키 필요 — 공통 준비 3번):

```powershell
python scripts/pubmed_collector/enrich_citations.py
```

결과 확인 — 콘솔 마지막 줄에 통계가 나옵니다:

```text
전체 20편 / 인용수 확보 20 / OpenAlex 미등재 0 / 대표 3편: ['42560326', '36432736', '34885962']
```

`OpenAlex 미등재: PMID XXXX`는 오류가 아니며 `citedByCount: null`로 저장되고,
**대표 "인용수 상위 2편" 후보에서는 제외**됩니다.

저장되는 JSON 모양:

```json
{
  "collectedAt": "2026-08-15",
  "papersWithCitations": [
    {
      "title": "논문 제목",
      "journal": "학술지 이름",
      "year": 2024,
      "pmid": "12345678",
      "publishedAt": "2024-05-01",
      "abstract": "초록 본문 (없으면 null)",
      "citedByCount": 12
    }
  ],
  "selectedPapers": [
    { "title": "논문 제목", "journal": "학술지 이름", "year": 2024, "pmid": "12345678" }
  ],
  "latestPaper": { "pmid": "12345678", "publishedAt": "2024-05-01" }
}
```

- `papersWithCitations` — 전체 논문 + `citedByCount` (검수용)
- `selectedPapers` — 계약 1-2 `papers` 모양의 대표 3편. 순서는 **최신 1편 → 인용 상위 2편**
- `latestPaper` — API ③(최근 연구 활동 교수) 정렬용 **백엔드 내부 필드**. 계약 응답에는 나가지 않습니다
- `selectedPapers` · `latestPaper`의 칸 이름은 `data/sample/professors.sample.json`과 똑같습니다 (3단계에서 그대로 조립)

### 대표 3편을 뽑는 규칙

| 자리 | 기준 |
| --- | --- |
| 최신 1편 | `publishedAt` 내림차순 1위. `publishedAt`이 없으면 `year`로 비교하고, 둘 다 없으면 후보에서 제외 |
| 인용 상위 2편 | 최신 1편을 **뺀** 나머지 중 `citedByCount` 내림차순 2편. `citedByCount`가 `null`이면 후보에서 제외 |

- 전체 논문이 3편 미만이면 **있는 만큼만** 담습니다. 없는 논문을 채우지 않습니다.
- 동점 처리: 인용수가 같으면 **연도가 최신인 쪽**, 연도까지 같으면 PMID 오름차순.
  (순서를 고정해 두지 않으면 실행할 때마다 결과가 달라져 재현이 안 됩니다)

## 3-3. 3단계: 전체 교수(243명) 논문 파이프라인 (`build_all.py`)

`data/input/professor_paper_lists.json`(교수 한글명 → 본인 프로필 페이지의 논문 인용문 목록)을 읽어,
인용문마다 **논문 제목을 뽑아 PubMed에 제목으로 검색**하고(동명이인 위험이 낮은 방식),
1단계·2단계 부품을 재사용해 교수별 결과를 `data/output/professors_papers.json` 한 파일로 모읍니다.

- 논문 인용문이 0건인 교수(82명)는 이번 단계에서 수집하지 않고, 빈 `papers`로 두고 `review.noPapers`에 이름만 기록합니다.
- 제목 추출 실패는 `review.parseFailed`, 검색 실패(0건·같은 제목이 너무 많아 모호·검색 결과의 제목이 인용문과 불일치)는 `review.notFound`에 남깁니다 — 지어내지 않고 사람이 검수합니다.
- 검색이 돌려준 논문은 **인용문에서 뽑은 제목과 대조 검증**한 뒤에만 수집합니다. 단어만 겹치는 남의 논문이 붙는 것을 막기 위한 안전장치입니다.
- **교수 1명이 끝날 때마다 결과를 즉시 저장**하므로, 중간에 끊겨도 다시 실행하면 이어서 진행됩니다(재개).

실행 순서:

1. `.env`에 OpenAlex 키 준비 (공통 준비 3번 — 2단계와 같은 키)
2. **LIMIT 검증**: `build_all.py` 상단 `LIMIT = 5`로 앞 5명만 실행 →
   `[1/2] 오상민: 인용문 8건 → PMID 8건 확보` 형태의 로그와 누적 통계 확인
3. **전체 실행**: `LIMIT = None`으로 되돌리고 재실행

   ```powershell
   python scripts/pubmed_collector/build_all.py
   ```

   PubMed 예절상 호출 사이 0.4초씩 쉬며 제목 검색이 약 2,000회라 **전체 실행은 수십 분**이 걸립니다.
   터미널을 켜 둔 채 기다려 주세요.

4. **재개(resume)**: 중간에 끊기면 **같은 명령을 다시 실행하면 됩니다.** 이미 완료된 교수는
   `이미 완료 — 건너뜀 (resume)` 로그와 함께 건너뜁니다. 처음부터 다시 수집하려면
   상단 `FORCE_REFRESH = True`로 바꾸고 실행합니다 (기존 결과를 무시하고 덮어씀).

저장되는 JSON 모양:

```json
{
  "collectedAt": "2026-08-15",
  "professors": {
    "오상민": {
      "papers": [ { "title": "...", "journal": "...", "year": 2021, "pmid": "..." } ],
      "latestPaper": { "pmid": "...", "publishedAt": "..." },
      "allPapers": [ { "...": "전체 수집 논문 + citedByCount + abstract (내부 검수용)" } ],
      "stats": { "cited": 8, "sourceEntries": 8, "collected": 7, "notFound": 1 }
    }
  },
  "review": {
    "noPapers": ["황정환", "..."],
    "parseFailed": [ { "professor": "...", "citation": "인용문 앞 80자..." } ],
    "notFound": [ { "professor": "...", "title": "..." } ]
  }
}
```

- `papers`(대표 3편)·`latestPaper`의 칸 이름은 계약 1-2 및 `data/sample/professors.sample.json`과 동일합니다 (다음 단계에서 그대로 조립).
- `stats` — `sourceEntries` 입력 인용문 수 / `cited` 제목 추출에 성공해 검색을 시도한 수 / `collected` 수집 논문 수(PMID 중복 제거 후) / `notFound` 검색 실패 수
- `review` — 사람이 검수할 목록. **오류가 아니라** "지어내지 않고 남겨 둔" 항목입니다.
  한글 서적·국내지 인용문은 PubMed에 없어 `notFound`에 쌓이는 것이 정상입니다.

## 자주 생기는 문제 (pubmed_collector)

| 증상 | 원인과 해결 |
| --- | --- |
| `AUTHOR_NAME_EN을 실제 교수 영문명으로 바꾼 뒤 다시 실행하세요.` | 1단계 이름 교체를 건너뛴 것 → 이름을 바꾸고 다시 실행 |
| `검색 결과가 0건입니다.` | 영문명 표기가 PubMed와 다름 (예: `Gil-Dong` vs `Gil Dong`) → PubMed 웹에서 표기 확인 |
| `ModuleNotFoundError: No module named 'requests'` | 가상환경 미활성화 또는 `pip install -r scripts/requirements.txt` 미실행 |
| `'python' 용어가 인식되지 않습니다` | `python` 대신 `py`로 실행해 보고, 안 되면 Python 설치 |
| `OPENALEX_API_KEY를 찾지 못했습니다.` | 공통 준비 3번을 건너뛴 것 → 키를 발급받아 `.env`에 채우고 다시 실행 |
| `입력 파일이 없습니다: ...professor_test.json` | 2단계 전에 1단계를 먼저 실행해야 함 |
| `OpenAlex 미등재`가 여러 건 보임 | 오류 아님 → `citedByCount: null`, 인용 상위 후보에서 제외 |
| 대표 논문이 3편보다 적음 | 정상. 논문이 3편 미만이거나 인용수 확보 논문이 부족한 경우 (없는 값을 채우지 않음) |
| 실행이 중간에 끊김 (3단계) | 같은 명령을 다시 실행 — 완료된 교수는 건너뛰고 이어서 진행(재개) |
| `notFound`가 많아 보임 (3단계) | 한글 서적·국내 학술지 인용문은 PubMed에 없는 것이 정상 → 검수 목록으로만 활용 |
| 진행 로그의 한글이 깨져 보임 | 콘솔 인코딩 문제 → PowerShell에서 `chcp 65001` 실행 후 재시도 (결과 파일은 항상 UTF-8 정상 저장) |
| 통신 오류 (`ConnectionError`, `HTTPError` 등) | 인터넷 연결 확인 후 잠시 뒤 재시도 (서버가 일시적으로 바쁠 수 있음) |
