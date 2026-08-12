from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import config
from ..data import Store, get_store
from ..schemas import FeaturedResponse, ProfessorDetail, SearchRequest, SearchResponse
from ..services import search as search_service

router = APIRouter(prefix="/api/professors", tags=["professors"])


@router.post("/search", response_model=SearchResponse, response_model_by_alias=True)
def search_professors(req: SearchRequest, store: Store = Depends(get_store)):
    """API ① 교수 검색·목록 조회 — 프론트 getProfessors(query, filters)와 1:1."""
    return search_service.search(store, req)


# 주의: /{professor_id}보다 먼저 등록해야 "featured"가 id로 해석되지 않는다
@router.get("/featured", response_model=FeaturedResponse, response_model_by_alias=True)
def featured_professors(store: Store = Depends(get_store)):
    """API ③ 최근 연구 활동 교수 — 최근 논문 발행일 내림차순 상위 FEATURED_COUNT명 (v6)."""
    cards = [
        search_service._to_card(p, None)
        for p in store.recently_active(config.FEATURED_COUNT)
    ]
    return FeaturedResponse(results=cards, collected_at=store.collected_at)


@router.get(
    "/{professor_id}",
    response_model=ProfessorDetail,
    response_model_by_alias=True,
    responses={404: {"description": "존재하지 않는 id", "content": {"application/json": {"example": {"error": "not_found"}}}}},
)
def professor_detail(professor_id: str, store: Store = Depends(get_store)):
    """API ② 교수 상세 조회."""
    professor = store.get(professor_id)
    if professor is None:
        # 계약: HTTP 404 + {"error": "not_found"}
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return professor
