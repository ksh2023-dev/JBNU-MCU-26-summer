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

- OpenAlex도 PubMed처럼 **무료이고 API 키가 필요 없습니다.**
- 인용수는 PMID로 조회하며, **50개씩 묶어서** 요청합니다 (논문 수만큼 호출하지 않기 위함).
- OpenAlex에 등록되지 않은 논문의 인용수는 **`0`이 아니라 `null`** 로 둡니다 (계약 원칙 2 — 없는 값을 지어내지 않음).
- 2단계도 **교수 1명 기준**입니다. (전체 교수 반복, `professors.json` 최종 조립은 3단계)

## 준비물

- 1단계와 동일 (Python 3.9 이상 · 인터넷 연결 · `requests`)
- **1단계 결과 파일** `data/output/professor_test.json` — 없으면 위 1단계를 먼저 실행하세요.

## 실행 방법 (Windows PowerShell 기준)

> 1단계와 마찬가지로 **저장소 루트 폴더**에서, 가상환경을 활성화한 상태로 실행하세요.

### 1. 연락처 이메일 입력

`scripts/pubmed_collector/enrich_citations.py` 파일을 열어 맨 위의 상수를 실제 이메일로 바꿉니다.
(1단계에서 `AUTHOR_NAME_EN`을 바꾸던 것과 같은 방식입니다.)

```python
CONTACT_EMAIL = "hong@jbnu.ac.kr"   # ← "REPLACE_ME"를 실제 이메일로 교체
```

- OpenAlex는 요청에 연락처를 담으면 더 빠른 응답 풀(polite pool)로 처리해 줍니다. **API 예절**이라 반드시 채웁니다.
- 바꾸지 않고 실행하면 안내 문구를 띄우고 멈춥니다.

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
| `CONTACT_EMAIL을 실제 이메일로 바꾼 뒤 다시 실행하세요.` | 위 1번 단계를 건너뛴 것 → 이메일을 채우고 다시 실행 |
| `입력 파일이 없습니다: ...professor_test.json` | 1단계를 아직 실행하지 않음 → 위 1단계를 먼저 실행 |
| `OpenAlex 미등재`가 여러 건 보임 | 오류 아님. 해당 논문이 OpenAlex에 없는 것 → `citedByCount: null`, 인용 상위 후보에서 제외 |
| 대표 논문이 3편보다 적음 | 정상. 논문이 3편 미만이거나, 인용수를 확보한 논문이 부족한 경우 (없는 값을 채우지 않음) |
| 통신 오류 (`ConnectionError`, `HTTPError` 등) | 인터넷 연결 확인 후 잠시 뒤 재시도 |
