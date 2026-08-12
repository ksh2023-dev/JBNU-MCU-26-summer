"""계약(v4) 스모크 테스트 — 응답의 칸 이름·모양이 계약 문서와 일치하는지 확인."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CARD_FIELDS = {"id", "name", "profileImageUrl", "professorType", "department", "specialties", "keywords", "matchScore"}
DETAIL_FIELDS = {
    "id", "name", "profileImageUrl", "professorType", "department", "labName",
    "specialties", "keywords", "email", "homepageUrl", "papers",
}


def test_search_response_shape():
    res = client.post("/api/professors/search", json={"query": "심장"})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"results", "total", "page", "pageSize", "collectedAt"}
    assert body["total"] >= 1
    for card in body["results"]:
        assert set(card) == CARD_FIELDS
        assert 0.0 <= card["matchScore"] <= 1.0


def test_min_score_cut():
    res = client.post("/api/professors/search", json={"query": "심장", "minScore": 0.99})
    body = res.json()
    assert all(c["matchScore"] >= 0.99 for c in body["results"])


def test_professor_type_filter():
    res = client.post("/api/professors/search", json={"query": "", "filters": {"professorType": ["기초의학"]}})
    assert all(c["professorType"] == "기초의학" for c in res.json()["results"])


def test_empty_query_browse_returns_null_score_sorted_by_name():
    res = client.post("/api/professors/search", json={"query": ""})
    body = res.json()
    assert body["total"] == 5
    assert all(c["matchScore"] is None for c in body["results"])
    # 질의가 없으면 이름 가나다순 정렬
    names = [c["name"] for c in body["results"]]
    assert names == sorted(names)
    assert names == ["김민수", "박지훈", "이서연", "정우진", "최은정"]


def test_no_results_is_empty_not_error():
    res = client.post("/api/professors/search", json={"query": "zzz없는검색어zzz"})
    assert res.status_code == 200
    assert res.json()["results"] == []
    assert res.json()["total"] == 0


def test_favorite_ids_absent_means_no_filter():
    # favoriteIds 없음/null = "찜한 교수만 보기" 꺼짐 → 전체 검색
    res = client.post("/api/professors/search", json={"query": "", "filters": {}})
    assert res.json()["total"] == 5


def test_favorite_ids_explicit_null_means_no_filter():
    # v6 계약: favoriteIds 없음/null 은 동일하게 "필터 꺼짐" — null도 명시적으로 검증
    res = client.post("/api/professors/search", json={"query": "", "filters": {"favoriteIds": None}})
    assert res.json()["total"] == 5


def test_favorite_ids_empty_means_zero_results():
    # favoriteIds: [] = 필터는 켰지만 찜 0명 → results: [], total: 0
    res = client.post("/api/professors/search", json={"query": "", "filters": {"favoriteIds": []}})
    body = res.json()
    assert body["results"] == []
    assert body["total"] == 0


def test_favorite_ids_intersect_with_query_and_type():
    # 교집합(AND): query ∩ professorType ∩ favoriteIds
    res = client.post(
        "/api/professors/search",
        json={
            "query": "심장",
            "filters": {"professorType": ["임상의학"], "favoriteIds": ["P-001", "P-003", "P-999"]},
        },
    )
    body = res.json()
    assert [c["id"] for c in body["results"]] == ["P-001"]
    assert body["total"] == 1


def test_favorite_ids_total_reflects_filter_for_pagination():
    # total은 찜 필터까지 반영된 수여야 프론트 페이지 계산이 맞는다
    res = client.post(
        "/api/professors/search",
        json={"query": "", "filters": {"favoriteIds": ["P-001", "P-002", "P-004"]}, "pageSize": 2},
    )
    body = res.json()
    assert body["total"] == 3
    assert len(body["results"]) == 2


def test_pagination_total_consistent():
    p1 = client.post("/api/professors/search", json={"query": "", "page": 1, "pageSize": 2}).json()
    p2 = client.post("/api/professors/search", json={"query": "", "page": 2, "pageSize": 2}).json()
    assert p1["total"] == p2["total"] == 5
    assert len(p1["results"]) == 2
    assert p1["results"][0]["id"] != p2["results"][0]["id"]


def test_detail_shape_and_papers_have_pmid():
    res = client.get("/api/professors/P-001")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == DETAIL_FIELDS
    assert body["papers"], "P-001은 논문이 있어야 함"
    for paper in body["papers"]:
        assert set(paper) == {"title", "journal", "year", "pmid"}
        assert paper["pmid"]


def test_detail_nulls_not_omitted():
    body = client.get("/api/professors/P-003").json()
    assert body["email"] is None  # 원칙 2: 값 없음 = null, 필드 생략 금지
    assert body["labName"] is None


def test_detail_404_contract():
    res = client.get("/api/professors/P-999")
    assert res.status_code == 404
    assert res.json() == {"error": "not_found"}


def test_featured_recent_papers_descending():
    res = client.get("/api/professors/featured")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"results", "collectedAt"}
    assert 3 <= len(body["results"]) <= 5  # v6 계약: 카드 3~5개
    # 최근 논문 발행일 내림차순: P-001(2025-11) > P-003(2025-04) > P-005(2024-11)
    # P-004는 latestPaper가 없으므로 후보 제외
    assert [c["id"] for c in body["results"]] == ["P-001", "P-003", "P-005"]
    # latestPaper는 내부 필드 — 카드 응답에 새어 나가면 안 된다
    assert all(set(c) == CARD_FIELDS for c in body["results"])


def test_featured_count_configurable(monkeypatch):
    # FEATURED_COUNT(환경변수 → config)를 바꾸면 카드 수가 따라간다
    from app import config

    monkeypatch.setattr(config, "FEATURED_COUNT", 2)
    res = client.get("/api/professors/featured")
    assert [c["id"] for c in res.json()["results"]] == ["P-001", "P-003"]

    # 후보(latestPaper 보유 4명)보다 크게 잡으면 있는 만큼만 반환 — 억지로 채우지 않는다
    monkeypatch.setattr(config, "FEATURED_COUNT", 10)
    res = client.get("/api/professors/featured")
    assert [c["id"] for c in res.json()["results"]] == ["P-001", "P-003", "P-005", "P-002"]
