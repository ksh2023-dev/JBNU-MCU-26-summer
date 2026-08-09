# Backend — 연수매칭 · 의대 연구 추천 API

데이터 계약 v4(`데이터_계약_백엔드전달_최종.pdf`)를 그대로 구현하는 FastAPI 서버.
지금은 `data/sample/professors.sample.json`(합성 샘플 5명)을 메모리에 올려 응답한다.
실데이터 파이프라인(`scripts/`)이 완성되면 데이터 파일만 교체한다.

## 실행

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- Swagger(계약 문서의 살아있는 버전): http://localhost:8000/docs
- 헬스체크: `GET /health`

## 테스트

```bash
cd backend && source .venv/bin/activate
pytest
```

## 엔드포인트 (계약 2장)

| 계약 | 엔드포인트 | 프론트 함수 |
|---|---|---|
| API ① 검색·목록 | `POST /api/professors/search` (단일 JSON 본문) | `getProfessors(query, filters)` |
| API ② 상세 | `GET /api/professors/{id}` — 없으면 404 + `{"error":"not_found"}` | `getProfessorById(id)` |
| API ③ 우수 교수 | `GET /api/professors/featured` | `getPopularProfessors()` |

찜하기 관련 API는 계약대로 **없음** (프론트 localStorage 소관).

## 설정 (환경변수, 전부 선택)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATA_FILE` | `data/sample/professors.sample.json` | 데이터 JSON 경로 |
| `DEFAULT_MIN_SCORE` | `0.3` | 요청에 minScore가 없을 때 기본 임계값 |
| `FEATURED_IDS` | `P-001,P-002,P-005` | 우수 교수 수동 큐레이션 (선정 기준 확정 전 임시) |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 프론트 개발 서버 origin |

## 계약 해석 메모 (팀 확인 필요 항목)

- **API ①의 HTTP 모양**: 계약은 요청 payload만 정의 → `POST /api/professors/search`로 구현. 프론트와 확정 필요.
- **빈 질의(query: "")**: 점수를 만들 근거가 없으므로 `matchScore: null` + minScore 컷 미적용(원칙 2·3). 카드가 항상 점수를 가진다고 가정하지 말 것.
- **우수 교수 카드의 matchScore**: 질의가 없으므로 `null`.
- **matchScore MVP 산식**: 이름 일치 1.0 / 키워드 0.4 · 전문분야 0.3 · 논문제목 0.2 · 소속 0.1 가중 합(토큰 부분일치). 계약 5장 1번에 대한 제안 — 개선은 `app/services/search.py`만 수정.
