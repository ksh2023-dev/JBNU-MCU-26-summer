# PubMed 수집기 — 1단계: 교수 1명 검증용

교수 1명의 **영문명**으로 PubMed(의학 논문 데이터베이스)를 검색해서,
그 교수의 논문 정보(제목·학술지·연도·PMID·초록·발행일)를
`data/output/professor_test.json` 파일로 저장하는 스크립트입니다.

- 데이터 계약(`docs/data-contract-v6.3.md`) 0장 "할루시네이션 방지 4원칙"을 따릅니다.
  - PMID가 없는 논문은 저장하지 않습니다.
  - API 응답에 없는 값은 지어내지 않고 `null`로 저장합니다.
- 1단계라서 **교수 1명만** 수집합니다. (전체 교수 반복, DB 저장, 인용수 조회는 다음 단계)
- PubMed 공식 API(E-utilities)를 사용하며 **API 키는 필요 없습니다.**

## 폴더 구성

| 파일 | 설명 |
| --- | --- |
| `fetch_one.py` | 실행 스크립트 (검색 → 수집 → 저장) |
| `requirements.txt` | 필요한 외부 라이브러리 목록 (`requests` 하나) |
| `README.md` | 이 문서 |

## 준비물

- Python 3.9 이상 — 터미널에서 `python --version`으로 확인 (없으면 [python.org](https://www.python.org/downloads/)에서 설치)
- 인터넷 연결

## 실행 방법 (Windows PowerShell 기준)

> 모든 명령은 **저장소 루트 폴더**(프로젝트 README.md가 보이는 위치)에서 실행하세요.

### 1. 가상환경(venv) 만들기 — 처음 한 번만

```powershell
python -m venv .venv
```

- "가상환경"은 이 프로젝트 전용 파이썬 공간입니다. 컴퓨터의 다른 프로그램과 섞이지 않게 해 줍니다.
- 폴더 이름을 `.venv`로 하면 `.gitignore`에 이미 등록되어 있어서 git에 올라가지 않습니다.

### 2. 가상환경 활성화 — 터미널을 새로 열 때마다

```powershell
.\.venv\Scripts\Activate.ps1
```

- 성공하면 프롬프트 맨 앞에 `(.venv)`가 붙습니다.
- ⚠️ "이 시스템에서 스크립트를 실행할 수 없으므로..." 오류가 나면, 아래 명령을 한 번 실행하고 다시 시도하세요
  (현재 사용자에게만 스크립트 실행을 허용하는 표준 설정입니다):

  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

- macOS/Linux는 `source .venv/bin/activate` 를 사용합니다.

### 3. 라이브러리 설치 — 처음 한 번만

```powershell
pip install -r scripts/pubmed_collector/requirements.txt
```

### 4. 교수 영문명 입력

`scripts/pubmed_collector/fetch_one.py` 파일을 열어 맨 위의 상수를 실제 교수 영문명으로 바꿉니다.

```python
AUTHOR_NAME_EN = "Gil Dong Hong"   # ← "REPLACE_ME"를 실제 이름으로 교체
```

- 이름 표기는 PubMed에 등록된 형태를 따라야 합니다. 검색이 0건이면
  [pubmed.ncbi.nlm.nih.gov](https://pubmed.ncbi.nlm.nih.gov/)에서 직접 검색해 표기(하이픈·띄어쓰기)를 확인하세요.

### 5. 실행

```powershell
python scripts/pubmed_collector/fetch_one.py
```

### 6. 결과 확인

- `data/output/professor_test.json` 파일이 만들어집니다. (없던 폴더는 자동 생성)
- 콘솔에 `초록 없음: PMID XXXX`가 보이면 → 그 논문은 PubMed에 초록이 등록되어 있지 않은 것입니다.
  오류가 아니며 `abstract: null`로 저장됩니다. 다만 **사람이 한 번 검수**하라는 표시입니다.

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

## 자주 생기는 문제

| 증상 | 원인과 해결 |
| --- | --- |
| `AUTHOR_NAME_EN을 실제 교수 영문명으로 바꾼 뒤 다시 실행하세요.` | 4번 단계를 건너뛴 것 → 이름을 바꾸고 다시 실행 |
| `검색 결과가 0건입니다.` | 영문명 표기가 PubMed와 다름 (예: `Gil-Dong` vs `Gil Dong`) → PubMed 웹에서 표기 확인 |
| `ModuleNotFoundError: No module named 'requests'` | 가상환경이 활성화되지 않았거나(2번) 설치를 안 함(3번) |
| `'python' 용어가 인식되지 않습니다` | `python` 대신 `py`로 실행해 보고, 안 되면 Python 설치 |
| 통신 오류 (`ConnectionError`, `HTTPError` 등) | 인터넷 연결 확인 후 잠시 뒤 재시도 (PubMed 서버가 일시적으로 바쁠 수 있음) |

---

# 2단계: 인용수 수집 + 대표 논문 3편 선정 (`enrich_citations.py`)

1단계가 만든 `data/output/professor_test.json`을 읽어서,

1. 각 논문의 **인용수**를 [OpenAlex](https://openalex.org/)에서 받아 `citedByCount` 칸으로 붙이고,
2. 데이터 계약 1-2의 규칙 **"최신순 1편 + 인용수 상위 2편 = 3편"** 으로 대표 논문을 뽑아
3. `data/output/professor_test_enriched.json` 파일로 저장합니다.

- OpenAlex는 무료지만 **2026-02-13부터 무료 계정의 API 키가 필요합니다.** (PubMed는 계속 키 없이 사용)
- 인용수는 PMID로 조회하며, **50개씩 묶어서** 요청합니다 (논문 수만큼 호출하지 않기 위함).
- OpenAlex에 등록되지 않은 논문의 인용수는 **`0`이 아니라 `null`** 로 둡니다 (계약 원칙 2 — 없는 값을 지어내지 않음).
- 2단계도 **교수 1명 기준**입니다. (전체 교수 반복, `professors.json` 최종 조립은 3단계)

## 준비물

- 1단계와 동일 (Python 3.9 이상 · 인터넷 연결 · `requests`)
- **1단계 결과 파일** `data/output/professor_test.json` — 없으면 위 1단계를 먼저 실행하세요.
- **OpenAlex 무료 계정의 API 키** — 아래 1번에서 준비합니다.

## 실행 방법 (Windows PowerShell 기준)

> 1단계와 마찬가지로 **저장소 루트 폴더**에서, 가상환경을 활성화한 상태로 실행하세요.

### 1. OpenAlex API 키 준비

OpenAlex는 **2026-02-13부터 mailto(polite pool) 방식을 폐지**하고 모든 API 호출에 무료 계정의
`api_key`를 요구합니다. 키는 공개 저장소에 커밋하지 않도록 코드가 아니라
**저장소 루트의 `.env` 파일**에서 읽습니다.

1. [openalex.org](https://openalex.org/)에서 무료 계정을 만듭니다.
2. 로그인 후 설정(Settings)에서 API 키를 복사합니다.
3. 루트의 `.env.example`을 복사해 루트에 `.env` 파일을 만들고 값을 채웁니다.

```text
OPENALEX_API_KEY=발급받은키
```

- `.env`는 `.gitignore`에 등록되어 있어 **커밋되지 않습니다.** (그래도 커밋 전 `git status`로 한 번 확인하세요)
- 키 없이 실행하면 발급 방법을 안내하고 멈춥니다(exit 1).

### 2. 실행

```powershell
python scripts/pubmed_collector/enrich_citations.py
```

### 3. 결과 확인

- `data/output/professor_test_enriched.json` 파일이 만들어집니다.
- 콘솔 마지막 줄에 통계가 나옵니다:

  ```text
  전체 20편 / 인용수 확보 20 / OpenAlex 미등재 0 / 대표 3편: ['42560326', '36432736', '34885962']
  ```

- 중간에 `OpenAlex 미등재: PMID XXXX`가 보이면 → 그 논문이 OpenAlex에 없다는 뜻입니다.
  오류가 아니며 `citedByCount: null`로 저장되고, **대표 "인용수 상위 2편" 후보에서는 제외**됩니다.

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

## 대표 3편을 뽑는 규칙

| 자리 | 기준 |
| --- | --- |
| 최신 1편 | `publishedAt` 내림차순 1위. `publishedAt`이 없으면 `year`로 비교하고, 둘 다 없으면 후보에서 제외 |
| 인용 상위 2편 | 최신 1편을 **뺀** 나머지 중 `citedByCount` 내림차순 2편. `citedByCount`가 `null`이면 후보에서 제외 |

- 전체 논문이 3편 미만이면 **있는 만큼만** 담습니다. 없는 논문을 채우지 않습니다 (계약 원칙 2).
- 동점 처리: 인용수가 같으면 **연도가 최신인 쪽**, 연도까지 같으면 PMID 오름차순.
  (순서를 고정해 두지 않으면 실행할 때마다 결과가 달라져 재현이 안 됩니다)

## 자주 생기는 문제 (2단계)

| 증상 | 원인과 해결 |
| --- | --- |
| `OPENALEX_API_KEY를 찾지 못했습니다.` | 위 1번(API 키 준비)을 건너뛴 것 → 키를 발급받아 `.env`에 채우고 다시 실행 |
| `입력 파일이 없습니다: ...professor_test.json` | 1단계를 아직 실행하지 않음 → 위 1단계를 먼저 실행 |
| `OpenAlex 미등재`가 여러 건 보임 | 오류 아님. 해당 논문이 OpenAlex에 없는 것 → `citedByCount: null`, 인용 상위 후보에서 제외 |
| 대표 논문이 3편보다 적음 | 정상. 논문이 3편 미만이거나, 인용수를 확보한 논문이 부족한 경우 (없는 값을 채우지 않음) |
| 통신 오류 (`ConnectionError`, `HTTPError` 등) | 인터넷 연결 확인 후 잠시 뒤 재시도 |

---

# 3단계: 전체 교수(243명) 논문 파이프라인 (`build_all.py`)

`data/input/professor_paper_lists.json`(교수 한글명 → 본인 프로필 페이지의 논문 인용문 목록)을 읽어,
인용문마다 **논문 제목을 뽑아 PubMed에 제목으로 검색**하고(동명이인 위험이 낮은 방식),
1단계(efetch 상세 수집)·2단계(OpenAlex 인용수 + 대표 3편 선정) 부품을 재사용해
교수별 결과를 `data/output/professors_papers.json` 한 파일로 모읍니다.

- 논문 인용문이 0건인 교수(82명)는 이번 단계에서 수집하지 않고, 빈 `papers`로 두고 `review.noPapers`에 이름만 기록합니다.
- 제목 추출 실패는 `review.parseFailed`, 검색 실패(0건·같은 제목이 너무 많아 모호·검색 결과의 제목이 인용문과 불일치)는 `review.notFound`에 남깁니다 — 지어내지 않고 사람이 검수합니다.
- 검색이 돌려준 논문은 **인용문에서 뽑은 제목과 대조 검증**한 뒤에만 수집합니다. 단어만 겹치는 남의 논문이 붙는 것을 막기 위한 안전장치입니다.
- **교수 1명이 끝날 때마다 결과를 즉시 저장**하므로, 중간에 끊겨도 다시 실행하면 이어서 진행됩니다(재개).

## 1. .env 준비 — 처음 한 번만

OpenAlex API 키는 공개 저장소에 커밋하지 않도록 코드가 아니라 **저장소 루트의 `.env` 파일**에서 읽습니다.
(2단계와 같은 키를 그대로 씁니다 — 발급 방법은 위 2단계 절의 "1. OpenAlex API 키 준비" 참고.
PubMed 호출에는 키가 필요 없습니다.)

1. 루트의 `.env.example`을 복사해 루트에 `.env` 파일을 만듭니다.
2. `OPENALEX_API_KEY=` 값을 발급받은 키로 채웁니다.

```text
OPENALEX_API_KEY=발급받은키
```

- `.env`는 `.gitignore`에 등록되어 있어 **커밋되지 않습니다.** (그래도 커밋 전 `git status`로 한 번 확인하세요)
- 값이 없으면 스크립트가 발급 방법을 안내하고 멈춥니다(exit 1).

## 2. LIMIT 검증 — 전체 실행 전에 반드시

`scripts/pubmed_collector/build_all.py` 상단의 상수로 **앞 N명만** 먼저 돌려 봅니다.

```python
LIMIT = 5   # 입력 목록 앞 5명만 처리 (None이면 전체 243명)
```

```powershell
python scripts/pubmed_collector/build_all.py
```

- 진행 로그가 `[1/2] 오상민: 인용문 8건 → PMID 8건 확보` 형태로 나오고, 끝에 누적 통계가 출력되면 정상입니다.
- 확인이 끝나면 `LIMIT = None`으로 되돌립니다.

## 3. 전체 실행

```powershell
python scripts/pubmed_collector/build_all.py
```

- `LIMIT = None` 상태로 실행하면 243명 전체를 처리합니다.
- PubMed 예절상 호출 사이 0.4초씩 쉬며 제목 검색이 약 2,000회라 **전체 실행은 수십 분**이 걸립니다. 터미널을 켜 둔 채 기다려 주세요.
- 결과: `data/output/professors_papers.json` (`data/output/`은 `.gitignore` 대상이라 커밋되지 않습니다)

## 4. 재개(resume) 방법

- **그냥 같은 명령을 다시 실행하면 됩니다.** 교수 1명이 끝날 때마다 저장되므로, 이미 완료된 교수는 `이미 완료 — 건너뜀 (resume)` 로그와 함께 건너뛰고 나머지만 이어서 수집합니다.
- 처음부터 전부 다시 수집하려면 파일 상단의 `FORCE_REFRESH = True`로 바꾸고 실행합니다. (기존 결과를 무시하고 덮어씀)

## 저장되는 JSON 모양

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

## 자주 생기는 문제 (3단계)

| 증상 | 원인과 해결 |
| --- | --- |
| `OPENALEX_API_KEY를 찾지 못했습니다.` | 위 1번(.env 준비)을 건너뛴 것 → 키를 발급받아 `.env`에 채우기 (발급 방법은 2단계 절 참고) |
| 실행이 중간에 끊김 (통신 오류 등) | 같은 명령을 다시 실행 — 완료된 교수는 건너뛰고 이어서 진행(재개) |
| `notFound`가 많아 보임 | 한글 서적·국내 학술지 인용문은 PubMed에 없는 것이 정상 → 검수 목록으로만 활용 |
| 진행 로그의 한글이 깨져 보임 | 콘솔 인코딩 문제 → PowerShell에서 `chcp 65001` 실행 후 재시도 (수집 결과 파일은 항상 UTF-8로 정상 저장됨) |

---

# C단계: MeSH·교수 영문명·이메일 보강 (`enrich_authors_mesh.py`)

3단계가 이미 확보한 PMID로 **efetch만 다시 호출**해(재수집 없음) 논문의 MeSH와 저자 상세를 읽고,
교수별 영문명(`nameEn`)·키워드 후보·이메일을 `data/output/professors_enriched_meta.json`에 채웁니다.
878편이 efetch 5묶음이라 전체 실행도 10초 남짓입니다.

```powershell
python scripts/pubmed_collector/enrich_authors_mesh.py
```

## 본인 저자를 가려내는 규칙

교수의 논문에 실린 저자 중 **전북대(Jeonbuk/Chonbuk National University) 소속 + 한글 성의 로마자 표기와
일치**하는 사람만 후보로 모은 뒤, 아래를 **전부** 만족할 때만 확정합니다. 하나라도 어긋나면 `nameEn`을
`null`로 두고 후보 전원의 근거와 함께 `review`에 남깁니다 (지어내지 않는다 — 계약 원칙 2).

- 전북대 소속으로 **2편 이상**에서 관측
- 후보가 2명 이상이면 1위가 2위보다 **2편 이상** 앞섬 (margin 규칙)
- **인용문 교차검증** — 교수 본인 프로필의 인용문(3단계 입력)에서 저자 "성 이니셜"을 뽑아 후보별 등장
  비율을 계산하고, 1위 + 0.6 이상 + 2위와 0.25 이상 차이일 것. 프로필에 제목만 적혀 저자부를 읽을 수
  없는 교수(대부분)는 교차검증 불가로 보고 위 두 조건만 적용합니다.

## 이메일 채택·보류 규칙

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

## 저장되는 JSON 모양 (C단계)

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
