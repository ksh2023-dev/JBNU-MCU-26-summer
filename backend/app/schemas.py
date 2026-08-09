"""데이터 계약 v4의 JSON 모양을 그대로 옮긴 Pydantic 모델.

칸 이름(camelCase)은 계약 문서가 기준이며, 여기서 바꾸면 프론트가 깨진다.
값이 없는 필드는 null로 직렬화된다(원칙 2) — 필드 생략 금지.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ProfessorType = Literal["기초의학", "임상의학", "의학교육학", "인문사회의학"]


class ContractModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Paper(ContractModel):
    title: str
    journal: str | None = None
    year: int | None = None
    pmid: str  # 원칙 1: pmid 없는 논문은 응답에 넣지 않는다


class ProfessorCard(ContractModel):
    """1-1. 교수 카드 — 검색 결과·우수 교수 공통."""

    id: str
    name: str
    profile_image_url: str | None = None
    professor_type: ProfessorType
    department: str
    specialties: list[str] = []
    keywords: list[str] = []
    # 우수 교수(API ③)처럼 질의가 없는 맥락에서는 점수가 없으므로 null 허용 (원칙 2)
    match_score: float | None = Field(default=None, ge=0.0, le=1.0)


class ProfessorDetail(ContractModel):
    """1-2. 교수 상세."""

    id: str
    name: str
    profile_image_url: str | None = None
    professor_type: ProfessorType
    department: str
    lab_name: str | None = None
    specialties: list[str] = []
    keywords: list[str] = []
    email: str | None = None
    homepage_url: str | None = None
    papers: list[Paper] = []


class SearchFilters(ContractModel):
    professor_type: list[ProfessorType] = []


class SearchRequest(ContractModel):
    """API ① 요청 본문 — 프론트 getProfessors(query, filters)가 조립해 보내는 단일 JSON."""

    query: str = ""
    filters: SearchFilters = SearchFilters()
    sort: Literal["relevance"] = "relevance"
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=5, ge=1, le=50)


class SearchResponse(ContractModel):
    results: list[ProfessorCard]
    total: int
    page: int
    page_size: int
    collected_at: str  # 원칙 4: 데이터 수집 기준일


class FeaturedResponse(ContractModel):
    results: list[ProfessorCard]
    collected_at: str
