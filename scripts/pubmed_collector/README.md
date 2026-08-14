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
