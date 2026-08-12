"""데이터 저장소 — 지금은 JSON 파일을 메모리에 올려 사용한다.

Phase 2에서 SQLite로 옮기더라도 이 모듈의 함수 시그니처는 유지해서
라우터·검색 로직이 저장 방식에 묶이지 않게 한다.
"""

import json
from functools import lru_cache

from . import config
from .schemas import ProfessorRecord


class Store:
    def __init__(self, professors: list[ProfessorRecord], collected_at: str):
        self.professors = professors
        self.collected_at = collected_at
        self._by_id = {p.id: p for p in professors}

    def get(self, professor_id: str) -> ProfessorRecord | None:
        return self._by_id.get(professor_id)

    def recently_active(self, count: int) -> list[ProfessorRecord]:
        """API ③ — 최근 논문 발행일 내림차순 상위 count명. 발행 정보 없으면 후보 제외."""
        candidates = [p for p in self.professors if p.latest_paper is not None]
        candidates.sort(key=lambda p: p.latest_paper.published_at, reverse=True)
        return candidates[:count]


@lru_cache(maxsize=1)
def get_store() -> Store:
    raw = json.loads(config.DATA_FILE.read_text(encoding="utf-8"))
    professors = [ProfessorRecord.model_validate(p) for p in raw["professors"]]
    # 원칙 1 방어선: pmid가 비어 있는 논문은 로드 단계에서 제거한다
    for p in professors:
        p.papers = [paper for paper in p.papers if paper.pmid and paper.pmid.strip()]
    return Store(professors, raw["collectedAt"])
