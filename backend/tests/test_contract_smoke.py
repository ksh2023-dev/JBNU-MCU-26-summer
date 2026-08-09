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


def test_empty_query_browse_returns_null_score():
    res = client.post("/api/professors/search", json={"query": ""})
    body = res.json()
    assert body["total"] == 5
    assert all(c["matchScore"] is None for c in body["results"])


def test_no_results_is_empty_not_error():
    res = client.post("/api/professors/search", json={"query": "zzz없는검색어zzz"})
    assert res.status_code == 200
    assert res.json()["results"] == []
    assert res.json()["total"] == 0


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


def test_featured():
    res = client.get("/api/professors/featured")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"results", "collectedAt"}
    assert 3 <= len(body["results"]) <= 5
