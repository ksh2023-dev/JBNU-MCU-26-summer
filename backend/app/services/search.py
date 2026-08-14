"""API ① 검색·점수 계산.

matchScore MVP 산식 (계약 5장 1번에 대한 백엔드 제안):
  이름 일치 1.0 / 그 외 필드 가중 합 — 키워드 0.4, 전문분야 0.3, 논문제목 0.2, 소속 0.1.
  질의 토큰별 부분일치(대소문자 무시)한 가중치를 합산하고 1.0으로 캡.
검색 범위(5장 2번): 교수명·전문분야·키워드·논문제목·소속까지. 초록은 MVP 제외.

빈 질의는 탐색(browse)으로 간주한다: 점수를 만들 근거가 없으므로 matchScore는
null이고(원칙 2) minScore 컷을 적용하지 않는다. 억지 점수를 채우지 않는다(원칙 3).
"""

from ..schemas import ProfessorCard, ProfessorDetail, SearchRequest, SearchResponse
from ..data import Store

WEIGHTS = {
    "keywords": 0.4,
    "specialties": 0.2,
    "papers": 0.4,
    "department": 0.1,
}


def _score(professor: ProfessorDetail, tokens: list[str]) -> float:
    query = " ".join(tokens)
    if query and query in professor.name.lower():
        return 1.0

    fields = {
        "keywords": [k.lower() for k in professor.keywords],
        "specialties": [s.lower() for s in professor.specialties],
        "papers": [p.title.lower() for p in professor.papers],
        "department": [professor.department.lower()],
    }
    score = 0.0
    for name, values in fields.items():
        matched = sum(1 for t in tokens if any(t in v for v in values))
        score += WEIGHTS[name] * (matched / len(tokens))
    return min(score, 1.0)


def _to_card(professor: ProfessorDetail, match_score: float | None) -> ProfessorCard:
    return ProfessorCard(
        id=professor.id,
        name=professor.name,
        profile_image_url=professor.profile_image_url,
        professor_type=professor.professor_type,
        department=professor.department,
        specialties=professor.specialties,
        keywords=professor.keywords,
        match_score=match_score,
    )


def search(store: Store, req: SearchRequest) -> SearchResponse:
    pool = store.professors
    if req.filters.professor_type:
        pool = [p for p in pool if p.professor_type in req.filters.professor_type]
    if req.filters.favorite_ids is not None:
        # 교집합(AND) — 빈 배열이면 pool도 비어 results: [], total: 0이 된다 (v6 계약)
        favorite_ids = set(req.filters.favorite_ids)
        pool = [p for p in pool if p.id in favorite_ids]

    tokens = req.query.lower().split()
    if tokens:
        scored = [(p, _score(p, tokens)) for p in pool]
        # 원칙 3: 임계값 미만은 제외하고, 억지로 채우지 않는다
        scored = [(p, s) for p, s in scored if s >= req.min_score]
        scored.sort(key=lambda ps: (-ps[1], ps[0].name))
    else:
        scored = [(p, None) for p in sorted(pool, key=lambda p: p.name)]

    start = (req.page - 1) * req.page_size
    page_items = scored[start : start + req.page_size]

    return SearchResponse(
        results=[_to_card(p, s) for p, s in page_items],
        total=len(scored),
        page=req.page,
        page_size=req.page_size,
        collected_at=store.collected_at,
    )
