# scripts — 데이터 수집 스크립트 모음

하위 폴더별로 나뉘어 있던 README를 이 문서 하나로 합쳤습니다. 의존성도 폴더별 venv/requirements 대신
**`scripts/requirements.txt` 하나**로 통일했습니다 (2026-08-15).

| 폴더 | 스크립트 | 하는 일 | 출력 |
| --- | --- | --- | --- |
| `roster_crawler/` | `crawl_roster.py` | 의대 홈페이지에서 교수 명단 수집 + 병원 명단과 diff | `data/output/roster_crawled.json` |
| `profile_image_collector/` | `fetch_image_urls.py` | 병원 프로필 페이지에서 사진 URL만 수집 | `data/output/profile_images.json` |
| `pubmed_collector/` | `fetch_one.py` → `enrich_citations.py` → `build_all.py` | 논문 수집(1단계) → 인용수+대표 3편(2단계) → 243명 전체 파이프라인(3단계) | `data/output/professors_papers.json` 등 |
| `kci_collector/` | `fetch_kci.py` | KCI(국내 학술지) 논문 수집 + PubMed 논문과의 중복 표시 | `data/output/kci_papers.json` |
| `keyword_translator/` | `translate_keywords.py` | 영문 MeSH 키워드 → 한글 번역 (KOSTOM 사전 + KCI 수확 메모리) | `data/output/keywords_ko.json` |

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
- 가져온 페이지 HTML을 `data/output/_cache_profile_pages/`에 남깁니다 — 같은 페이지를 읽는
  3단계(전문진료분야)가 재요청 없이 이 캐시를 재사용합니다 (같은 서버를 두 번 돌지 않기 위함).
  캐시는 부산물이라 지워도 무해하며(재조회), `.gitignore` 대상입니다.
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

## 3-4. C단계: MeSH·교수 영문명·이메일 보강 (`enrich_authors_mesh.py`)

3단계가 이미 확보한 PMID로 **efetch만 다시 호출**해(재수집 없음) 논문의 MeSH와 저자 상세를 읽고,
교수별 영문명(`nameEn`)·키워드 후보·이메일을 `data/output/professors_enriched_meta.json`에 채웁니다.
878편이 efetch 5묶음이라 전체 실행도 10초 남짓입니다.

가상환경·설치는 위 「공통 준비」를 그대로 따릅니다. OpenAlex 키는 필요 없습니다 (PubMed efetch만 호출).

```powershell
python scripts/pubmed_collector/enrich_authors_mesh.py
```

### 본인 저자를 가려내는 규칙

교수의 논문에 실린 저자 중 **전북대(Jeonbuk/Chonbuk National University) 소속 + 한글 성의 로마자 표기와
일치**하는 사람만 후보로 모은 뒤, 아래를 **전부** 만족할 때만 확정합니다. 하나라도 어긋나면 `nameEn`을
`null`로 두고 후보 전원의 근거와 함께 `review`에 남깁니다 (지어내지 않는다 — 계약 원칙 2).

- 전북대 소속으로 **2편 이상**에서 관측
- 후보가 2명 이상이면 1위가 2위보다 **2편 이상** 앞섬 (margin 규칙)
- **인용문 교차검증** — 교수 본인 프로필의 인용문(3단계 입력)에서 저자 "성 이니셜"을 뽑아 후보별 등장
  비율을 계산하고, 1위 + 0.6 이상 + 2위와 0.25 이상 차이일 것. 프로필에 제목만 적혀 저자부를 읽을 수
  없는 교수(대부분)는 교차검증 불가로 보고 위 두 조건만 적용합니다.

### 이메일 채택·보류 규칙

소속 문자열에 실린 주소는 **그 저자가 아니라 교신저자·부서 공용 주소일 수 있어서**, 근거가 그 사람을
특정할 때만 채택합니다. 나머지는 `email: null`로 두고 주소를 `review`에 보존합니다 (오발송 방지).

**채택**

| 근거 | 예 |
| --- | --- |
| 인용문 교차검증 통과 | (위 판정에서 교차검증까지 통과한 교수) |
| `initialsCombo` — 이니셜 조합 완전일치 | `smoh@`(Sang-Min Oh) · `sjs@`(손지선: 성 S + 이름 JS) |
| `fullGivenName` — 이름 전체 포함 | `sunjun@`(Sun-Jun Kim) |
| `lastNameAndInitials` — 성 + 이니셜 (근거 두 겹) | `shkimgi@`(kim + SH) · `entejlee@`(lee + EJ) |

**보류** (`review`의 `emailHoldReason`으로 구분)

| 사유 | 뜻 | 예 |
| --- | --- | --- |
| `nameFragmentOnly` | 이름 조각(3자 이상)만 일치 | `admin@`(Min-Ho Kim의 'min') · `sunhee@`(Sun-Young Kim의 'sun') |
| `localPartMismatch` | 이름 근거가 없음 (성만 일치하거나 전혀 무관) | `oklee@`(Dae-Woo Lee) · `cardiolab@`(Jin-Ho Park) |

- **이름 조각은 자동 채택하지 않습니다** — `min`·`sun`·`jin`·`hee` 같은 3글자 조각은 한국 이름에 너무
  흔해서 남의 주소가 우연히 걸립니다. 사람이 확인해 확정할 항목입니다.
- **성 단독 일치도 채택하지 않습니다** — 김·이·박은 명단 안에만 수십 명이라 `oklee@`가 이대우인지
  다른 이씨인지 알 수 없습니다.
- 접두 일치는 인정하지 않습니다 — `kjsjdk@`는 앞 세 글자가 김종승의 이니셜과 맞지만 보류합니다.
- 보류된 주소를 사람이 확인했다면 `data/input/manual_overrides.json`에 `field: "email"`로 확정합니다.

저장되는 JSON 모양:

```json
{
  "collectedAt": "2026-08-16",
  "professors": {
    "오상민": {
      "nameEn": "Sang-Min Oh",
      "nameEnVariants": ["Sang-Min Oh"],
      "keywordsCandidate": ["COVID-19", "SARS-CoV-2", "..."],
      "keywordsCandidateAll": ["Humans", "Adult", "..."],
      "email": null,
      "evidence": { "papersObserved": 3, "citationRatio": 1.0, "crossChecked": true, "...": "..." }
    }
  },
  "review": [
    { "professor": "...", "reason": "...", "candidates": [ { "candidate": "...", "papers": 2, "citationRatio": 1.0 } ] },
    { "professor": "...", "reason": "이메일 보류 — ...", "emailHoldReason": "nameFragmentOnly", "withheldEmail": "..." }
  ]
}
```

- `keywordsCandidate`는 MeSH 검색 태그(Humans·Adult·Female 등 연구 주제가 아닌 항목)를 뺀 상위 10개이고,
  빼기 전 목록은 `keywordsCandidateAll`에 함께 담습니다. **키워드 최종 확정·한글 번역은 이 단계 밖**입니다.
- `review`는 오류 목록이 아니라 **사람이 확인할 목록**입니다. 확정한 값은 수동 검수 대장에 적습니다.

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

---

# 4. KCI 논문 수집기 (`kci_collector/fetch_kci.py`)

KCI(한국학술지인용색인) Open API로 **국내 학술지 논문**을 교수별로 수집해
`data/output/kci_papers.json`으로 저장합니다.

PubMed 수집(3장)에서 국내 논문은 `pmid`가 없어 담지 못했습니다 —
계약 v6.4에서 `kciId`가 도입되어(원칙 1: **pmid 또는 kciId 필수**) 이 단계로 보완합니다.

- 대상: `data/output/professors.json`에 수록된 교수 전원 (계약 0-2 = 의대 공식 명단 기준, 182명)
- 수집 항목: `kciId` · 제목(원어/영문) · 학술지 · 연도 · `doi` · `url` · **KCI 피인용수** · 초록(원어/영문)
- 부수 수집: 본인 저자 항목의 **영문명 · ORCID** (영문명 미확정 교수 보완, 동명이인 검증용)
- 산출물의 키는 **교수 id**(`P-012`)입니다. 이름을 키로 쓰면 동명이인이 한 칸에 뭉개지므로,
  레코드 안에 `name`을 함께 두어 사람이 읽을 수 있게 합니다.
- **이 단계는 KCI 산출물 생성까지입니다.** PubMed 논문과의 병합은 다음(조립) 단계이며,
  여기서는 `duplicateOf`에 "같은 논문으로 보이는 pmid"만 표시합니다.

> ✅ **2026-08-18 실제 응답으로 검증 완료** — 아래 "실제 응답 구조(실측)"가 그 결과입니다.
> 단위 테스트의 표본 XML도 실제 응답 구조로 갈아 끼웠습니다.
>
> 🔐 **응답에 인증키가 그대로 돌아옵니다** (`<inputData><key>`). 응답 원문을 파일로 저장하거나
> 이슈·채팅에 붙일 때는 이 부분을 지우세요. 산출물(`kci_papers.json`)에는 들어가지 않으며,
> 스크립트가 오류 로그에 남기는 응답 조각에서도 키를 자동으로 가립니다.

## 원칙 (계약 0-1)

| 원칙 | 이 스크립트에서 |
| --- | --- |
| 1. pmid 또는 kciId 필수 | `article-id`가 없는 응답 항목은 버립니다 |
| 2. 없는 값은 지어내지 않는다 | 피인용수·초록·DOI가 없으면 `0`/`""`이 아니라 `null`. **소속이 전북대로 확인되지 않은 논문은 채택하지 않고** `review.affiliationUnmatched`에 남깁니다 |
| 2. 불확실하면 합치지 않는다 | 중복 판별이 애매하면 별개로 두고 `review.duplicateAmbiguous`에 남깁니다 |
| 4. 수집 기준일 기록 | `collectedAt`에 실행일을 담고, 제목·학술지·연도는 KCI 원본 그대로 둡니다 |

## 본인 논문 판별 — 왜 소속을 보는가

KCI 검색은 **이름(`author`)** 으로 합니다. 이름만으로는 동명이인·타 기관 저자의 논문이 섞여 오므로,
응답 안에서 **교수와 같은 이름인 저자의 소속에 `전북대`가 들어 있을 때만** 채택합니다.
PubMed 수집에서 오귀속을 막았던 기준과 같습니다 — 근거가 없으면 넣지 않습니다.

| 상황 | 처리 | `review.affiliationUnmatched`의 `reason` |
| --- | --- | --- |
| 같은 이름 저자의 소속에 `전북대` 포함 | **채택** | — |
| 같은 이름 저자의 소속이 다른 기관 | 제외 | `타 기관` |
| 같은 이름 저자의 소속이 비어 있음 | 제외 | `소속 정보 없음` |
| 응답에 같은 이름의 저자가 없음 | 제외 | `동명 저자 없음` |

판정 키워드(`AFFILIATION_KEYWORDS`)는 실측으로 정했습니다 — 한글 `전북대`·`전북의대`·
`전북의학전문대학원`과 영문 `Jeonbuk/Chonbuk National Univ…`(대소문자 무시).
`jeonbuk`만으로 판정하면 전북 소재의 무관한 기관까지 걸리므로 기관명 전체를 키워드로 씁니다.

## 동명이인 — 자동 배정하지 않는다

대상 명단에 **같은 이름의 교수가 둘 이상이면**(현재 `이창훈` P-176/P-177) 검색 결과를
**어느 쪽에도 배정하지 않습니다.** KCI 검색은 이름 기준이고 둘 다 전북대 소속이라
소속으로도 가를 수 없기 때문입니다 — 근거가 없으면 채우지 않습니다(원칙 2).

- 같은 이름의 교수 **전원**이 `papers: []` 인 레코드를 받습니다
  (`stats.homonymUnassigned`에 보류한 편수가 남아, "결과 없음"과 구분됩니다)
- `authorInfo`도 비웁니다 — 영문명·ORCID 역시 누구 것인지 알 수 없습니다
- 후보 논문은 **각 논문의 저자 ORCID·소속·영문명과 함께** `review.homonymUnassigned`에 남깁니다.
  사람이 이걸 보고 수동 검수 대장에서 배정합니다 (ORCID가 사실상 유일한 판별 단서입니다)
- 검색은 이름당 한 번만 합니다 (같은 이름이면 결과가 같으므로)

## 해석할 수 없는 응답은 0건이 아니다 (fail-closed)

**'논문 0건'으로 저장하려면 근거가 있어야 합니다** — KCI가 `resultMsg`에 "No Data"라고
답했거나 `<total>0</total>`이 온 경우뿐입니다. 그 근거 없이 비어 있는 응답(점검 페이지·
프록시 오류 페이지·응답 형식 변경)은 0건이 아니라 **오류**로 다룹니다.

| 응답 | 처리 |
| --- | --- |
| `resultMsg`가 "No Data" · `<total>0</total>` | 정상 0건 — 빈 `papers`로 저장하고 `review.noResult`에 기록 |
| `resultMsg`에 그 밖의 문구 (인증키 오류 등) | 즉시 중단(exit 1). 모든 교수에서 같은 오류가 나므로 계속할 의미가 없습니다 |
| `record`도 `resultMsg`도 없음 / `record`에 `article-id`가 하나도 없음 / XML이 깨짐 | **재시도**(3회, 5→15초) 후에도 실패하면 그 교수는 `review.fetchFailed`에 기록하고 다음 교수로 계속 |

- 실패한 교수는 **레코드를 저장하지 않습니다.** 빈 `papers`를 남기면 다음 단계가
  "국내 논문 없음"으로 읽고, 재실행해도 완료된 것으로 보고 건너뛰기 때문입니다.
  저장하지 않으면 이전 실행의 결과가 그대로 남고, 재실행 시 자동으로 다시 시도됩니다.
- 원인 파악을 위해 응답 원문 앞 200자를 로그에 남기되 **인증키는 가립니다**(`<key>***</key>`).

## 실행 방법

공통 준비(가상환경 · `pip install -r scripts/requirements.txt`)를 먼저 끝내 주세요.

1. **인증키 준비** — `open.kci.go.kr` → Open API 신청(활용 목적·**서비스 IP** 기재) → 승인 후 인증키 확인.
   환경변수 `KCI_API_KEY`로 넘기거나, 저장소 루트 `.env`에 한 줄 추가합니다 (양식: `.env.example`).

   ```text
   KCI_API_KEY=발급받은키
   ```

   - **환경변수가 `.env`보다 우선**입니다 (`run_all.py`의 `--env-file` 주입이 적용되도록).
   - 키가 없으면 발급 절차를 안내하고 **바로 멈춥니다**(exit 1). 호출은 하지 않습니다.
   - **인증키는 신청 시 등록한 IP에서만 동작합니다.** Vercel·GitHub Actions처럼 IP가 유동인 곳에서는
     쓸 수 없고, 고정 IP 수집 서버에서 실행해야 합니다 (계약 v6.4 7장).

2. **LIMIT 검증** — `kci_collector/fetch_kci.py` 상단 `LIMIT = 2`로 앞 2명만 실행해
   결과 한 건을 눈으로 확인합니다 (아래 "실제 응답 구조(실측)"와 대조).
   응답 형식이 바뀌었다면 여기서 티가 납니다 — 채택 0편이거나 제목·학술지가 비어 나옵니다.

   ```powershell
   python scripts/kci_collector/fetch_kci.py
   ```

3. **전체 실행** — `LIMIT = None`으로 되돌리고 같은 명령을 실행합니다.
   교수 1명당 최소 0.5초(결과가 100편을 넘으면 쪽 수만큼 더)를 쉽니다.
   실측(2026-08-18): 182명 전체 수집(`FORCE_REFRESH`)에 **약 15분**(899초)이 걸렸습니다.
   동명이인이 많은 이름은 결과가 수백~수천 건이라 여러 쪽을 돕니다
   (이창훈 1,489건 · 김종현 983건 · 김원 945건 — 검색 결과 총 50,216편).

4. **재개(resume)** — 중간에 끊기면 **같은 명령을 다시 실행**하면 됩니다. 이미 저장된 교수는
   건너뜁니다. `review.fetchFailed`에 기록된 교수는 저장되지 않았으므로 자동으로 다시 시도됩니다.
   처음부터 다시 모으려면 `FORCE_REFRESH = True`로 두고 실행합니다.

5. **단위 테스트** — 인증키 없이 실행할 수 있습니다.

   ```powershell
   python -m unittest discover -s scripts/kci_collector -v
   ```

   표본 XML은 **2026-08-18 실제 응답 구조 그대로**입니다(내용만 축약·치환).
   특히 `FailClosedTest`와 `test_결과_0건과_오류_구분`은 반드시 유지하세요 — 이 구분이 깨지면
   인증키가 틀렸거나 API가 장애일 때 182명 전원이 조용히 '논문 0건'으로 저장됩니다.

## 저장되는 JSON 모양

```json
{
  "collectedAt": "2026-08-18",
  "professors": {
    "P-012": {
      "name": "황주희",
      "papers": [
        { "kciId": "ART002712345", "title": "국내 심부전 …", "titleEn": "Prognostic Factors …",
          "journal": "대한내과학회지", "year": 2021, "doi": "http://dx.doi.org/10.3904/…",
          "url": "https://www.kci.go.kr/…", "citedByCountKci": 4,
          "abstract": "…", "abstractEn": "…", "duplicateOf": "38123456" }
      ],
      "authorInfo": {
        "nameEn": "Joo-Hee Hwang", "orcid": "0000-0002-…",
        "nameEnVariants": ["Joo-Hee Hwang", "Joo Hee Hwang"],
        "orcidCandidates": [{ "value": "0000-0002-…", "count": 7 }]
      },
      "stats": { "found": 12, "adopted": 9, "affiliationUnmatched": 3, "homonymUnassigned": 0 }
    },
    "P-176": {
      "name": "이창훈",
      "papers": [],
      "authorInfo": { "nameEn": null, "orcid": null, "nameEnVariants": [], "orcidCandidates": [] },
      "stats": { "found": 8, "adopted": 0, "affiliationUnmatched": 2, "homonymUnassigned": 6 }
    }
  },
  "review": { "affiliationUnmatched": [], "homonymUnassigned": [], "duplicateAmbiguous": [],
              "fetchFailed": [], "noResult": [] }
}
```

| 칸 | 뜻 |
| --- | --- |
| 최상위 키 | **교수 id** (`professors.json`의 `id`). 레코드 안의 `name`은 사람이 읽기 위한 것 |
| `papers[].duplicateOf` | 같은 논문으로 판별된 PubMed `pmid` (아니면 `null`). **합치지는 않습니다** |
| `authorInfo.nameEn` / `orcid` | 대표값(관측된 값 중 최빈값). 하나도 없으면 `null` |
| `authorInfo.nameEnVariants` | 관측된 영문명 표기 **전부** (많이 나온 순) — 표기 흔들림을 사람이 볼 수 있게 |
| `authorInfo.orcidCandidates` | `{value, count}` 목록. **2개 이상이면 동명이인이 섞였다는 신호**입니다 |
| `stats.found` / `adopted` / `affiliationUnmatched` | 검색 결과 / 채택 / 소속 미확인 제외 |
| `stats.homonymUnassigned` | 동명이인이라 배정을 보류한 편수. `papers`가 빈 이유가 "결과 없음"인지 "배정 보류"인지 구분합니다 |

### `review` 읽는 법

모든 기록에 `professor`(이름)가 있고, 단독 교수의 기록에는 `professorId`도 함께 들어갑니다
(동명이인은 어느 id인지 정할 수 없어 `professorId`가 `null`입니다).

| 목록 | 모양 | 뜻·할 일 |
| --- | --- | --- |
| `affiliationUnmatched` | `{professorId, professor, kciId, title, reason, affiliations}` | 소속이 확인 안 돼 뺀 논문. `affiliations`는 응답의 소속 표기 원본 — 본인 논문인데 빠졌다면 소속 표기를 확인 |
| `homonymUnassigned` | `{professor, professorIds, reason, candidates[]}` | **동명이인이라 배정하지 않은 후보 논문.** `candidates[]`는 논문 정보 + `author{nameEn, orcid, affiliation}` — 사람이 ORCID로 확인해 수동 배정 |
| `duplicateAmbiguous` | `{professorId, professor, kciId, title, year, reason, candidatePmids}` | 같은 논문일 수 있으나 확정 못 한 건. 사람이 확인해 조립 단계에 반영 |
| `fetchFailed` | `{professorId, professor, stage, error}` | 통신 실패·해석 불가 응답. 레코드를 저장하지 않았으므로 다시 실행하면 자동 재시도 |
| `noResult` | `{professorId, professor}` | KCI 검색 결과가 0건. 국내 논문이 없거나 이름 검색이 안 걸린 것 |

### 중복 판별 규칙 (계약 v6.4 1-2)

같은 교수의 PubMed 논문(`professors_papers.json`의 `allPapers`)과만 대조합니다 —
다른 교수의 논문과 합치면 오귀속이 됩니다.

1. **DOI 일치** (`https://doi.org/`·대소문자 차이는 무시) → `duplicateOf`에 pmid
2. DOI가 없으면 **정규화 제목 + 연도 일치** (영문 제목 우선 — PubMed 제목이 영문이므로)
3. 후보가 여럿 / 제목은 같은데 연도가 다름 / 제목이 닮기만 함 → **애매**로 두고 `review`에 기록

> ⚠️ 현재 `professors_papers.json`에는 **DOI 칸이 없습니다**(PubMed 3단계가 수집하지 않음).
> 그래서 실제로는 1번 규칙이 동작하지 않고 **2번(제목+연도)만으로 판별**됩니다 — 계약 1-2 ②로
> 정상 동작이며, 이 스크립트는 현재 상태 그대로 둡니다(실행 시작 시 로그로 알려 줍니다).
> **PubMed 수집에 `doi`가 추가되면 1순위 규칙(DOI 일치)이 켜져 판별 정확도가 올라갑니다.**
> 이 코드는 `doi` 칸이 생기면 수정 없이 그대로 1번 규칙을 씁니다.

## 실제 응답 구조 (2026-08-18 실측)

```xml
<MetaData>
  <inputData>            <!-- 요청을 그대로 되돌려 준다. key도 포함되므로 원문 공유 주의 -->
    <key>…</key><apiCode>articleSearch</apiCode><author>강경표</author>
    <page>1</page><displayCount>100</displayCount>
  </inputData>
  <outputData>
    <result><total>69</total></result>          <!-- 결과가 없으면 total 대신 resultMsg -->
    <record>
      <journalInfo>
        <journal-name>대한내과학회지</journal-name>   <!-- lang 속성 없음 -->
        <publisher-name>…</publisher-name>
        <pub-year>2021</pub-year><pub-mon>03</pub-mon><volume>96</volume><issue>1</issue>
      </journalInfo>
      <articleInfo article-id="ART003365943">        <!-- ← kciId -->
        <article-categories>…</article-categories><article-regularity>Y</article-regularity>
        <title-group>
          <article-title lang="original"><![CDATA[…]]></article-title>
          <article-title lang="foreign"><![CDATA[…]]></article-title>   <!-- 있을 때만 -->
          <article-title lang="english"><![CDATA[…]]></article-title>
        </title-group>
        <author-group>
          <author english="Kyung Pyo Kang" orc-id="0000-…">강경표(전북대학교 의과대학 내과학교실)</author>
        </author-group>
        <abstract-group>
          <abstract lang="original"><![CDATA[…]]></abstract>
          <abstract lang="english"><![CDATA[…]]></abstract>
        </abstract-group>
        <fpage>…</fpage><lpage>…</lpage>
        <doi>http://dx.doi.org/10.3904/kjm.2026.101.4.209</doi>   <!-- 빈 값인 논문이 절반쯤 -->
        <uci></uci>
        <citation-count kci="4" wos="0">4</citation-count>        <!-- kci 속성을 쓴다 -->
        <url>https://www.kci.go.kr/…artiId=ART003365943</url>
        <verified>Y</verified>
      </articleInfo>
    </record>
  </outputData>
</MetaData>
```

### 작성 당시 예상과 달랐던 것 (코드 수정으로 반영됨)

| 항목 | 실측 | 대응 |
| --- | --- | --- |
| **오류 응답** | `error` 태그가 **없다.** 오류도 **HTTP 200**이고, 결과 0건과 **같은 자리**(`result/resultMsg`)에 문구만 다르게 온다. 0건="No Data" / 키 오류="등록되지 않은 key 입니다." / 잘못된 코드="등록되지 않은 서비스" | `parse_response`가 `resultMsg`를 읽어 'No Data' 계열만 0건으로 보고, 나머지 문구는 모두 오류로 던진다. **모르는 문구도 오류로 취급** — 인증키 문제를 '논문 0건'으로 삼키면 182명이 통째로 빈 결과가 되기 때문 |
| **저자 소속 표기** | 대부분 한글(`전북대학교`·`전북대학교병원`·`전북의대`)이지만 **영문만 오는 논문이 실제로 있다** (`…, Jeonbuk National University Hospital, Jeonju`, 옛 표기 `Chonbuk National University …`). KCI가 긴 영문 소속을 **150자에서 자르기도** 한다 | `AFFILIATION_KEYWORDS`에 영문 표기와 한글 약칭을 함께 넣음 (제외 목록 사후 점검으로 45편 회수) |
| `doi` | 값이 있으면 **전체 URL**(`http://dx.doi.org/…`), 없으면 빈 요소. 강경표 69편 중 35편만 값 있음 | 원본 그대로 저장하고(원칙 4), 비교할 때만 `normalize_doi`로 접두 URL 제거 |
| `citation-count` | `kci`·`wos` **두 속성 + 텍스트**를 모두 가짐 (텍스트는 kci와 같은 값) | `kci` 속성을 쓴다. `kci="0"`은 0회 인용(값 있음), 태그 자체가 없으면 `null`(미상) |
| `article-title` `lang` | `original` / `english` 외에 **`foreign`** 이 있다 | `english`만 `titleEn`으로 쓴다(`foreign`은 영어가 아닐 수 있음) |
| `journal-name` | `lang` 속성이 **없다** | 속성 없는 노드를 원어로 보는 기존 처리로 그대로 동작 |
| 제목·초록 | **CDATA**로 감싸여 온다 | ElementTree가 자동 처리 — 수정 불필요 |
| `displayCount` | **최소 10 · 최대 100** (5를 보내면 10, 200을 보내면 100으로 조정됨) | 100 사용 — 변경 없음 |
| `page` | 정상 동작 (1쪽과 2쪽 결과가 겹치지 않음, 끝을 넘기면 0건) | 변경 없음 |
| `author` 단독 검색 | **동작한다** (`title` 없이도 검색됨) — 다만 동명이인이 대량으로 섞인다 (강상율 372건 중 본인 18건) | 소속 판정으로 거른다 |

### 아직 확인되지 않은 것

- `affiliation` 검색 파라미터의 정확한 이름·표기 규칙 (기본값 `USE_AFFILIATION_PARAM = False` 유지)
- 일일 호출 한도. 182명 전체 실행(약 300여 회 호출)에서는 한도 오류가 나지 않았습니다

## 자주 생기는 문제 (kci_collector)

| 증상 | 원인과 해결 |
| --- | --- |
| `KCI_API_KEY를 찾지 못했습니다` | 환경변수·`.env` 어디에도 키가 없음 → 실행 방법 1번 |
| `KCI가 오류 응답을 돌려줬습니다: …` 후 중단 | 인증키·IP·파라미터 문제. 모든 교수에서 같은 오류가 나므로 여기서 멈춥니다. 키를 고치고 다시 실행하면 완료분은 건너뜁니다 |
| `수집 실패(해석 불가 응답 — …)` | 점검 페이지·프록시 오류 등으로 응답을 해석할 수 없음. 3회 재시도 후 그 교수만 건너뜁니다(레코드 미저장) → 잠시 뒤 다시 실행 |
| 채택 0편인데 검색 결과는 많음 | 소속 표기가 예상과 다름 → `review.affiliationUnmatched`의 `affiliations`를 확인 후 `AFFILIATION_KEYWORDS` 조정 |
| `… 20쪽까지만 수집했습니다` | 한 이름의 결과가 2,000건 초과 → `MAX_PAGES` 조정 검토 |
| `저장 실패: kci_papers.json을 다른 프로그램이 열고 있습니다` | 윈도우에서 편집기·백신 등이 산출물을 잡고 있는 것. 0.5초 간격으로 5회까지 다시 시도하고, 그래도 안 되면 `.json.tmp`에 남긴 뒤 다음 저장에서 반영합니다. **실행 중에는 산출물 파일을 열지 마세요** |
| 영문명·ORCID가 여러 개라는 경고 | 동명이인이 섞였을 가능성 → `authorInfo.orcidCandidates`와 해당 교수 논문 검수 |
| `papers`가 비었는데 `stats.found`는 큼 | `stats.homonymUnassigned`가 0보다 크면 **동명이인 배정 보류**, 0이면 소속 불일치로 전부 제외된 것 |

## 알려진 한계 (kci_collector)

- **동명이인**: KCI 검색은 이름 기준이라 같은 이름의 두 교수를 자동으로 가를 수 없습니다.
  그래서 **자동 배정을 하지 않고** 후보를 `review.homonymUnassigned`로 넘깁니다(위 "동명이인" 절).
  배정은 사람이 ORCID·소속을 보고 수동 검수 대장에서 결정합니다 —
  **그 전까지 해당 교수들의 `papers`는 빈 배열로 남습니다.**
- `affiliation` 검색 파라미터는 이름·표기 규칙을 확인하지 못해 기본값 `USE_AFFILIATION_PARAM = False`입니다.
  본인 판별은 응답 안의 소속으로 하므로 꺼 두어도 오귀속은 생기지 않습니다.
- KCI 검색은 **저자 이름 기준**이라 3장의 `review.notFound`(963건, 제목 기준 실패)와 1:1로 대응하지 않습니다.
  겹치는 논문은 `duplicateOf`로, 새로 들어오는 논문은 그대로 채택됩니다.

---

# 5. 파이프라인 오케스트레이터 (`run_all.py`)

위 수집기들과 조립기를 **순서대로 1회** 실행하는 단일 진입점입니다. cron은 이 파일 하나만 부릅니다.

cron에 단계별 명령을 따로 걸면 앞 단계가 끝나기 전에 다음이 시작될 수 있습니다(논문 수집만 수십 분).
순서 보장은 이 스크립트가 책임집니다. **반복은 cron의 몫이고, 이 파일은 1회 실행 묶음입니다.**
표준 라이브러리만 쓰므로 수집 서버에 추가 설치가 필요 없습니다.

## 실행 순서 (9단계)

| # | 단계 | 스크립트 | 주기 | 주요 출력 |
| --- | --- | --- | --- | --- |
| 1 | 교수 명단 크롤 | `roster_crawler/crawl_roster.py` | **월 1회** (기본 제외) | `roster_crawled.json` |
| 2 | 프로필 사진 URL | `profile_image_collector/fetch_image_urls.py` | 주 1회 | `profile_images.json` |
| 3 | 전문진료분야 | `specialty_collector/fetch_specialties.py` | 주 1회 | `specialties.json` |
| 4 | 논문 수집(PubMed+OpenAlex) | `pubmed_collector/build_all.py` | 주 1회 | `professors_papers.json` |
| 5 | MeSH·영문명·이메일 보강 | `pubmed_collector/enrich_authors_mesh.py` | 주 1회 | `professors_enriched_meta.json` |
| 6 | KCI 논문 수집 | `kci_collector/fetch_kci.py` | 주 1회 (키 없으면 자동 건너뜀) | `kci_papers.json` |
| 7 | KCI 키워드 수집 | `kci_collector/fetch_kci_keywords.py` | 주 1회 (키 없으면 자동 건너뜀) | `kci_papers.json`에 덧씌움 |
| 8 | 키워드 한글 번역 | `keyword_translator/translate_keywords.py` | 주 1회 (로컬 사전 조회, 몇 초) | `keywords_ko.json` |
| 9 | 최종 조립 | `assembler/build_professors.py` | 주 1회 | `professors.json` · `professors_extra.json` |

3단계·8단계·9단계의 자세한 동작은 `specialty_collector/README.md`·`keyword_translator/README.md`·
`assembler/README.md`를 봅니다.

## 단계 사이의 의존 관계

- **[2] → [3] (부드러운 의존)** — 2·3단계는 **같은 병원 프로필 페이지**를 읽습니다. 2단계가
  페이지 HTML을 `data/output/_cache_profile_pages/`에 남기고, 3단계는 신선한(24시간 이내)
  캐시가 있으면 재요청 없이 재사용합니다 — 기본 순서(2 → 3)에서는 3단계가 몇 초에 끝납니다.
  캐시가 없어도 3단계는 스스로 요청하므로 실패하지 않습니다 (단독 실행도 그대로 동작).
- **[4] → [5]** — 5단계는 4단계 산출물 `professors_papers.json`을 입력으로 씁니다(없으면 `exit 1`).
- **[6] → [7]** — 키워드 보강은 **전체 재수집이 아니라** 6단계가 만든 `kci_papers.json`의 `kciId`로
  상세(`articleDetail`)만 불러 같은 파일에 얹습니다. 그 파일이 없으면 `exit 1`로 끝납니다.
- **[5] → [8]** — 키워드 한글 번역은 5단계 산출물의 영문 MeSH 키워드를 번역 대상으로 읽습니다.
  7단계까지 채워진 `kci_papers.json`이 있으면 한·영 키워드 쌍을 번역 메모리에 수확하므로
  KCI 단계들 **뒤**에 둡니다 (수확은 보너스라 KCI가 건너뛰어도 사전만으로 정상 동작합니다).
- **[1]·[2]·[3]·[4]·[5]·[8] → [9]** — 조립기는 앞 산출물들을 `load_json`으로 그대로 엽니다.
  하나라도 없으면 트레이스백을 뱉고 죽습니다. 단 [8]의 `keywords_ko.json`만은 없어도
  경고 후 진행합니다(`keywordsKo` 전원 `[]`) — 그래도 번역 없는 조립이 조용히 배포되지 않게
  run_all은 선행 조건으로 확인합니다. 조립기는 이 번역표로 교수마다 `keywordsKo`
  (백엔드 내부 필드 — 화면 미표시·검색 매칭 전용)를 채웁니다.
- **[6]은 9단계 산출물 `professors.json`을 수집 대상 명단으로 읽습니다(순환 의존).** 순서가 6 → 9라
  같은 회차에는 채워지지 않고 늘 **직전 회차**의 조립 결과를 기준으로 돕니다.

**선행 산출물이 없는 단계는 `건너뜀(선행 산출물 없음)`으로 자동 제외됩니다** — 실패가 아니라
'아직 차례가 아닌 것'으로 봅니다. 산출물이 하나도 없는 **새 서버의 최초 실행에서는 6·7단계가 건너뛰어지고**,
그 회차의 9단계가 `professors.json`을 만들면 **다음 회차부터 저절로 실행**됩니다. 사람이 손댈 것은 없습니다.

단, **이번 실행의 앞 단계가 그 파일을 만들 예정이면 있는 것으로 칩니다.** 예를 들어
`professors_papers.json`이 아직 없어도 같은 실행에서 4단계가 돌 예정이면 5·9단계는 정상 실행됩니다.
어느 쪽이든 계획표(`--dry-run`)에 사유와 파일 이름이 그대로 찍힙니다.

> 새 서버의 첫 회차는 `--include-roster`로 도는 것을 권합니다. 그러지 않으면 1단계 산출물
> `roster_crawled.json`이 없어 9단계(최종 조립)까지 건너뛰어집니다.

## 사용법

저장소 루트에서 가상환경을 활성화한 뒤 실행합니다. 하위 스크립트는 `run_all.py`를 실행한
파이썬(`sys.executable`)으로 호출되므로 **가상환경이 그대로 따라갑니다.**

```powershell
# 기본: 주 1회 묶음 (2~9단계, 명단 크롤 제외)
python scripts/run_all.py

# 월 1회: 명단 크롤까지 포함한 전체
python scripts/run_all.py --include-roster

# 무엇이 돌지 먼저 확인 (실제 실행 없음)
python scripts/run_all.py --dry-run
```

| 옵션 | 뜻 |
| --- | --- |
| `--include-roster` | 1단계(교수 명단 크롤)를 포함합니다. 월 1회용이라 기본은 제외 |
| `--only 4,5` | 지정한 단계만 실행. `--only 1`처럼 직접 적으면 1단계도 실행됩니다 |
| `--skip 2,3` | 지정한 단계를 건너뜁니다 (`--only`와 함께 쓸 수 없습니다) |
| `--dry-run` | 실제 실행 없이 계획표만 출력. 락도 잡지 않습니다 |
| `--continue-on-error` | 단계가 실패해도 다음 단계를 계속 진행 (기본은 즉시 중단) |
| `--env-file PATH` | 쓸 `.env` 경로 (기본: 저장소 루트 `.env`). 여기서 읽은 값은 각 단계에도 전달됩니다 |
| `--force-unlock` | 남아 있는 락 파일을 강제로 회수하고 실행 (도는 실행이 없는 것이 확실할 때만) |
| `--limit N` | 각 수집 단계를 **앞 N명만** 처리 — 파이프라인 스모크 테스트용 (`--limit 10`이면 전 단계가 몇 분에 끝난다). 산출물이 N명짜리로 줄어드니 **운영 실행에는 쓰지 말 것**. 각 스크립트의 `LIMIT` 상수를 환경변수(`PIPELINE_LIMIT`)로 덮는 방식이라 파일을 되돌릴 필요가 없다 |

## 실행 전 사전 점검

1. `OPENALEX_API_KEY`가 있는지 확인합니다. **그 키가 필요한 단계(현재는 4단계)가 이번 실행에
   들어 있을 때만** 필수로 보고, 없으면 즉시 중단합니다(수십 분을 버리기 전에 멈춥니다).
   그 단계가 없는 실행(예: `--only 2`·`--only 5`)은 키가 없어도 진행합니다.
   5단계는 확보한 PMID로 efetch만 다시 부르므로 OpenAlex 키가 필요 없습니다.
2. `KCI_API_KEY`가 없으면 **6·7단계**를 `건너뜀(키없음)`으로 자동 제외합니다.
   (이 키는 IP에 묶여 있어 고정 IP 수집 서버에서만 동작합니다 — 계약 v6.4 7장)
3. 선행 산출물이 필요한 단계(5·6·7·8·9)는 그 파일이 있는지 확인해, 없으면
   `건너뜀(선행 산출물 없음)`으로 자동 제외합니다.
4. 각 단계 스크립트가 실제로 있는지 확인해 계획표로 출력합니다. 없으면 `건너뜀(missing)`.

건너뛴 단계는 사유가 계획표와 종료 요약에 그대로 남으므로, **안 돈 단계를 성공으로 착각할 일이 없습니다.**

## `.env` 값이 각 단계에 전달되는 방식

`run_all.py`는 `--env-file`(기본: 루트 `.env`)을 파싱해 **각 단계 프로세스의 환경변수로 넘깁니다.**
수집 스크립트들은 원래 저장소 루트 `.env`를 직접 읽기 때문에, 이렇게 넘기지 않으면
`--env-file`로 지정한 파일이 조용히 무시됩니다.

그래서 각 수집 스크립트의 키 읽기 함수는 **환경변수를 먼저 보고, 없을 때만 루트 `.env`를 읽습니다.**

```python
api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
if not api_key and ENV_PATH.exists():
    ...  # 기존 .env 파서
```

- 단독 실행 시에는 환경변수가 없으므로 지금까지처럼 루트 `.env`를 읽습니다(기존 동작 그대로).
- `run_all.py` 경유 시에만 지정한 파일이 적용됩니다. 셸에 같은 이름의 환경변수가 있어도 **파일 값이 이깁니다.**
- **새로 추가하는 수집 스크립트도 이 규칙을 따라야 합니다.**
  현재 키를 읽는 두 함수 — `enrich_citations.read_openalex_api_key()`,
  `fetch_kci.read_kci_api_key()` — 모두 반영되어 있습니다.
  (7단계 키워드 수집기는 `fetch_kci.read_kci_api_key()`를 그대로 불러 쓰므로 자동으로 따릅니다)

## 중복 실행 방지 (락 파일)

- **위치**: `data/output/.run_all.lock` — 시작 시각과 PID가 기록됩니다.
- 실행 중 락이 있으면 **새 실행을 거부**합니다(종료 코드 3). cron 주기보다 실행이 길어질 때
  두 프로세스가 같은 산출물을 동시에 쓰는 사고를 막기 위한 것입니다.
- 락은 정상 종료·실패·Ctrl+C·종료 신호 어느 경우에도 해제됩니다.
- **스테일 락 자동 회수** — 강제 종료(`kill -9`·전원 차단)로 락만 남은 경우, 기록된 PID가 이미
  죽었으면 **경고를 남기고 자동으로 회수한 뒤 계속 진행**합니다. 사람이 손댈 때까지 cron이 매 회차
  조용히 실패하는 상황을 막기 위한 것입니다.
- 거부하든 회수하든 **콘솔과 로그 파일 양쪽에** 락의 시작 시각·PID·경과 시간을 남깁니다.

```
기존 락 발견: .../data/output/.run_all.lock
       시작 시각 2026-08-18 19:26:11 · PID 21432 · 경과 95분 01초
[경고] 스테일 락 — PID 21432 프로세스가 이미 없습니다(강제 종료·전원 차단 추정). 자동으로 회수하고 진행합니다.
```

- PID가 **아직 살아 있으면** 거부합니다. PID 기록이 없거나 손상된 락도 생사를 알 수 없어 거부합니다
  (도는 실행을 덮치는 쪽이 훨씬 위험합니다).
- 그 경우 정말 도는 실행이 없다면 회수합니다.

  ```bash
  python scripts/run_all.py --force-unlock
  ```

## 로그

- 콘솔 출력을 그대로 흘려보내면서 같은 내용을 `data/output/logs/run_YYYYMMDD_HHMMSS.log`에 남깁니다
  (폴더 자동 생성, `.gitignore` 대상).
- 사전 점검 실패·락 거부도 로그로 남습니다 — cron에서 원인을 찾을 수 있게.
- 단계마다 시작/종료 시각·소요 시간·종료 코드가 찍히고, 끝에 단계별 상태 표와
  최종 `professors.json`의 교수 수·`collectedAt`이 출력됩니다.

## 종료 코드

| 코드 | 뜻 |
| --- | --- |
| 0 | 전 단계 성공(또는 건너뜀) |
| 1 | 한 단계 이상 실패 |
| 2 | 사전 점검 실패 (`OPENALEX_API_KEY`가 필요한 단계를 실행하는데 키가 없음 · 잘못된 옵션) |
| 3 | 이미 실행 중(락 파일) — 이번 실행은 아무것도 하지 않음 |
| 130 | 사용자 중단(Ctrl+C) 또는 종료 신호 |

## cron 등록 예시

> 실제 등록은 수집 서버 세팅 단계에서 진행합니다 (아래는 양식).

```cron
# 주 1회: 월요일 03:00 — 논문·사진·전문분야·KCI·키워드 번역·조립
0 3 * * 1  cd /path/to/repo && .venv/bin/python scripts/run_all.py >> data/output/logs/cron.log 2>&1
# 월 1회: 매월 1일 04:00 — 명단 갱신 포함 전체
0 4 1 * *  cd /path/to/repo && .venv/bin/python scripts/run_all.py --include-roster >> data/output/logs/cron.log 2>&1
```

- 두 일정이 겹쳐도 락 파일이 뒤에 시작한 쪽을 거부하므로 산출물이 섞이지 않습니다.
- 종료 코드가 0이 아니면 실패입니다. `cron.log` 끝의 **실행 요약** 표에서 어느 단계인지 확인합니다.

## 실패했을 때 확인 순서

1. **로그부터 봅니다** — `data/output/logs/`에서 가장 최근 `run_*.log`.
   파일 끝의 `===== 실행 요약 =====` 표에 단계별 상태(성공/실패/건너뜀/중단됨)가 있습니다.
2. **어느 단계인지 확인했으면** 이 문서의 해당 수집기 절에서 증상별 대처를 봅니다.
3. **락 때문에 거부됐다면** — 스테일 락은 자동 회수되므로 손댈 필요가 없습니다. 그래도 거부됐다면
   기록된 PID가 살아 있거나 PID 기록이 손상된 경우입니다. `--force-unlock`으로 회수합니다.
4. **재실행** — 실패한 단계만 다시 돌리려면 `--only`를 씁니다 (예: `--only 4`).

### 재실행 시 resume 동작

| # | 단계 | 재실행하면 |
| --- | --- | --- |
| 1 | 교수 명단 크롤 | 처음부터 다시 (1~2분) |
| 2 | 프로필 사진 URL | 처음부터 다시 (5~10분) |
| 3 | 전문진료분야 | 처음부터 다시 — 단 **2단계가 24시간 안에 남긴 페이지 캐시가 있으면 재요청 없이 몇 초**에 끝난다 (캐시 없는 교수만 직접 요청) |
| 4 | 논문 수집 | **이어서 진행** — 저장된 교수는 건너뛰고 `review.fetchFailed`만 자동 재시도. 전부 다시 받으려면 `FORCE_REFRESH = True` |
| 5 | MeSH·영문명·이메일 보강 | 위 3-4장 참고 |
| 6 | KCI 논문 수집 | **이어서 진행** (위 4장 참고) |
| 7 | KCI 키워드 수집 | **이어서 진행** — `_cache_kci_details.json` 캐시를 재사용하므로 이미 받은 상세는 다시 부르지 않습니다 |
| 8 | 키워드 한글 번역 | 처음부터 다시 — 로컬 사전 조회라 몇 초면 끝납니다 |
| 9 | 최종 조립 | 처음부터 다시 (앞 산출물을 읽어 합치는 단계라 빠릅니다) |

각 단계는 별도 프로세스로 돌기 때문에 한 단계가 죽어도 다른 단계의 산출물은 그대로 남습니다.
기본 모드에서는 실패 시 즉시 중단하므로 **뒤 단계가 옛 데이터로 조립되는 일은 없습니다.**
일부 실패를 감수하고 끝까지 돌리려면 `--continue-on-error`를 씁니다(이 경우에도 종료 코드는 0이 아닙니다).
