# Backend — 연수매칭 · 의대 연구 추천 API

데이터 계약 v4(`데이터_계약_백엔드전달_최종.pdf`)를 그대로 구현하는 FastAPI 서버.
지금은 `data/sample/professors.sample.json`(합성 샘플 5명)을 메모리에 올려 응답한다.
실데이터 파이프라인(`scripts/`)이 완성되면 데이터 파일만 교체한다.

## 실행

### macOS / Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Windows (PowerShell)

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- `py`가 없다는 오류가 나면 `python -m venv .venv` 로 실행 (Python 3.11+ 설치 필요: https://www.python.org/downloads/ — 설치 시 "Add python.exe to PATH" 체크)
- `Activate.ps1`에서 "스크립트를 실행할 수 없습니다" 오류가 나면 PowerShell에서 한 번만 실행:
  `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- cmd(명령 프롬프트)를 쓴다면 활성화 명령만 다름: `.venv\Scripts\activate.bat`

- Swagger(계약 문서의 살아있는 버전): http://localhost:8000/docs
- 헬스체크: `GET /health`

## 테스트

### macOS / Linux

```bash
cd backend && source .venv/bin/activate
pytest
```

### Windows (PowerShell)

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest
```

가상환경이 켜져 있으면(프롬프트 앞 `(.venv)` 표시) 두 OS 모두 명령은 `pytest` 하나다.
14개 테스트가 전부 통과해야 정상. 서버 없이 도는 테스트라 uvicorn 실행은 필요 없다.

수동으로 API를 확인하려면 서버 실행 후 브라우저에서 http://localhost:8000/docs 를 열어
각 엔드포인트의 [Try it out]으로 요청을 보내면 된다 (Windows에는 curl 대신 이 방법 권장).

## 엔드포인트 (계약 2장)

| 계약 | 엔드포인트 | 프론트 함수 |
|---|---|---|
| API ① 검색·목록 | `POST /api/professors/search` (단일 JSON 본문) | `getProfessors(query, filters)` |
| ① `filters.favoriteIds` (v6) | 없음/`null`=필터 꺼짐 · `[]`=결과 없음 · `["P-001",...]`=교집합(AND) 후 페이지네이션 | "찜한 교수만 보기" |
| API ② 상세 | `GET /api/professors/{id}` — 없으면 404 + `{"error":"not_found"}` | `getProfessorById(id)` |
| API ③ 최근 활동 교수 | `GET /api/professors/featured` | `getFeaturedProfessors()` |

찜하기 관련 API는 계약대로 **없음** (프론트 localStorage 소관).

## 설정 (환경변수, 전부 선택)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATA_FILE` | `data/sample/professors.sample.json` | 데이터 JSON 경로 |
| `DEFAULT_MIN_SCORE` | `0.3` | 요청에 minScore가 없을 때 기본 임계값 |
| `FEATURED_COUNT` | `3` | API ③ 카드 수 — 최근 논문 발행일(`latestPaper.publishedAt`) 내림차순 상위 N명 (계약상 3~5) |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 프론트 개발 서버 origin |

### 환경변수 설정 방법

전부 선택 사항 — 설정하지 않으면 위 기본값으로 동작한다. 서버를 켜기 **전에**, 같은 터미널에서 설정한다.

**macOS / Linux**

```bash
# 방법 1: 해당 명령 한 번에만 적용 (명령 앞에 붙임)
FEATURED_COUNT=5 uvicorn app.main:app --reload --port 8000

# 방법 2: 현재 터미널 세션 전체에 적용
export FEATURED_COUNT=5
export DATA_FILE=/절대/경로/professors.json
uvicorn app.main:app --reload --port 8000
```

**Windows (PowerShell)**

```powershell
# 현재 터미널 세션 전체에 적용 (값은 따옴표로)
$env:FEATURED_COUNT = "5"
$env:DATA_FILE = "C:\경로\professors.json"
uvicorn app.main:app --reload --port 8000
```

**Windows (cmd)**

```bat
set FEATURED_COUNT=5
uvicorn app.main:app --reload --port 8000
```

- 어느 OS든 터미널을 닫으면 초기화된다 — 영구 설정이 필요하면 팀과 상의 후 `.env` 방식 도입 검토
- 확인: 값이 적용됐는지 보려면 `echo $FEATURED_COUNT`(macOS/Linux) / `echo $env:FEATURED_COUNT`(PowerShell)
- `--reload` 자동 재시작은 코드 변경만 감지한다 — 환경변수를 바꿨다면 서버를 껐다가(Ctrl+C) 다시 켜야 반영된다

## 계약 해석 메모 (팀 확인 필요 항목)

- **API ①의 HTTP 모양**: 계약은 요청 payload만 정의 → `POST /api/professors/search`로 구현. 프론트와 확정 필요.
- **빈 질의(query: "")**: 점수를 만들 근거가 없으므로 `matchScore: null` + minScore 컷 미적용(원칙 2·3). 카드가 항상 점수를 가진다고 가정하지 말 것.
- **우수 교수 카드의 matchScore**: 질의가 없으므로 `null`.
- **matchScore MVP 산식**: 이름 일치 1.0 / 키워드 0.4 · 전문분야 0.3 · 논문제목 0.2 · 소속 0.1 가중 합(토큰 부분일치). 계약 5장 1번에 대한 제안 — 개선은 `app/services/search.py`만 수정.
