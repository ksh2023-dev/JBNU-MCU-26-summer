"""1단계가 모은 논문 목록에 인용수를 붙이고, 대표 논문 3편을 뽑는 2단계 스크립트.

흐름: 1단계 결과 읽기 → OpenAlex에서 인용수 조회 → 대표 3편 선정 → 저장

데이터 계약 v6.3을 그대로 따른다.
- 0장 원칙 2: OpenAlex에 없는 논문의 인용수는 0으로 지어내지 않고 null로 둔다.
- 0장 원칙 4: 수집 기준일(collectedAt)을 결과에 담는다.
- 1-2 papers: "최신순 1편 + 인용수 상위 2편 = 3편" (7/23 회의 결정)
- selectedPapers/latestPaper의 칸 이름은 professors.sample.json과 똑같이 맞춘다
  (3단계에서 교수 객체에 그대로 끼워 넣기 위함).
"""

import json
import time
from datetime import date
from pathlib import Path

import requests

# OpenAlex API 키는 코드가 아니라 저장소 루트의 .env 파일에서 읽는다 (OPENALEX_API_KEY 값).
# 2026-02-13부터 OpenAlex가 mailto(polite pool) 방식을 폐지하고 모든 호출에 무료 계정의
# api_key를 요구하며, 키를 공개 저장소에 커밋하지 않기 위해서이기도 하다. (양식: 루트 .env.example)
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# OpenAlex API 주소 — 무료지만 2026-02-13부터 무료 계정의 API 키가 필요하다
OPENALEX_URL = "https://api.openalex.org/works"

# 한 번에 물어볼 PMID 개수. 한 건씩 부르면 논문 수만큼 호출하게 되므로,
# 1단계 efetch에서 PMID를 쉼표로 묶었던 것과 같은 원리로 50개씩 묶어서 요청한다.
BATCH_SIZE = 50

# API 예절: 요청 사이에 0.3초 쉰다
SLEEP_SECONDS = 0.3

# 입출력 위치: (저장소 루트)/data/output/
# 이 파일이 scripts/pubmed_collector/ 안에 있으므로 두 단계 위가 저장소 루트다.
# 이렇게 잡아 두면 어느 폴더에서 실행해도 같은 곳을 읽고 쓴다.
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "output"
INPUT_PATH = DATA_DIR / "professor_test.json"           # 1단계 산출물
OUTPUT_PATH = DATA_DIR / "professor_test_enriched.json"  # 2단계 산출물


def read_openalex_api_key():
    """루트 .env에서 OPENALEX_API_KEY 값을 읽는다 (외부 라이브러리 없이 몇 줄짜리 파서).

    API 키를 공개 저장소에 커밋하지 않기 위해 코드가 아니라 .env 파일에서 읽는다.
    (.env는 .gitignore에 등록되어 있고, 양식은 루트 .env.example 참고)
    3단계 build_all.py도 이 함수를 그대로 가져다 써서 같은 .env 값을 일관되게 쓴다.
    """
    api_key = ""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "OPENALEX_API_KEY":
                api_key = value.strip().strip('"').strip("'")
    if not api_key:
        raise SystemExit(
            "OPENALEX_API_KEY를 찾지 못했습니다.\n"
            "OpenAlex는 2026-02-13부터 모든 API 호출에 무료 계정의 api_key를 요구합니다.\n"
            "발급 방법: openalex.org에서 무료 계정을 만들고 → 설정(Settings)에서 API 키를 복사한 뒤\n"
            "→ 저장소 루트의 .env 파일에 아래 한 줄을 추가해 주세요 (양식: .env.example).\n"
            "  OPENALEX_API_KEY=발급받은키\n"
            "(.env는 .gitignore에 등록되어 있어 커밋되지 않습니다)"
        )
    return api_key


def load_papers():
    """[1단계 결과 읽기] professor_test.json에서 논문 목록을 읽어 온다."""
    if not INPUT_PATH.exists():
        raise SystemExit(
            f"입력 파일이 없습니다: {INPUT_PATH}\n"
            "먼저 fetch_one.py를 실행해 1단계 결과를 만들어 주세요."
        )
    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    papers = data.get("papers", [])
    print(f"1단계 결과 읽음: 논문 {len(papers)}건 ({INPUT_PATH.name})")
    return papers


def fetch_cited_by_counts(pmids, api_key):
    """[인용수 조회] OpenAlex에 PMID를 50개씩 묶어 물어보고 {pmid: 인용수} 표를 만든다.

    filter=pmid:1111|2222|3333 처럼 세로줄(|)로 이어 붙이면 한 번에 여러 건을 조회할 수 있다.
    응답에 없는 PMID는 이 표에 담기지 않으며, 호출한 쪽에서 null로 처리한다 (계약 원칙 2).
    """
    counts = {}

    # 50개씩 잘라서 반복 — 논문이 20건이면 1회, 243건이면 5회로 끝난다
    for start in range(0, len(pmids), BATCH_SIZE):
        batch = pmids[start:start + BATCH_SIZE]
        params = {
            "filter": "pmid:" + "|".join(batch),
            "per-page": BATCH_SIZE,
            "api_key": api_key,  # 2026-02-13부터 모든 호출에 필수 (mailto/polite pool 폐지)
        }
        resp = requests.get(OPENALEX_URL, params=params, timeout=60)
        resp.raise_for_status()  # 통신 실패(4xx/5xx)면 여기서 바로 멈춰서 알린다

        for work in resp.json().get("results", []):
            # OpenAlex는 pmid를 "https://pubmed.ncbi.nlm.nih.gov/12345678" 형태의 주소로 준다.
            # 우리가 가진 값은 숫자뿐이라, 주소의 마지막 조각(숫자)만 떼어 내 맞춘다.
            pmid_url = (work.get("ids") or {}).get("pmid") or ""
            pmid = pmid_url.rstrip("/").split("/")[-1]
            if pmid:
                counts[pmid] = work.get("cited_by_count")

        print(f"OpenAlex 조회: {len(batch)}건 요청 → {len(counts)}건 누적 확인")
        time.sleep(SLEEP_SECONDS)  # API 예절: 다음 요청까지 잠시 쉰다

    return counts


def attach_citations(papers, counts):
    """[붙이기] 각 논문에 citedByCount를 붙인다. OpenAlex에 없으면 null로 둔다 (계약 원칙 2)."""
    enriched = []
    for paper in papers:
        cited = counts.get(paper["pmid"])
        if cited is None:
            # 0으로 지어내지 않는다. 사람이 검수할 수 있게 콘솔에도 알린다.
            print(f"OpenAlex 미등재: PMID {paper['pmid']}")
        enriched.append({**paper, "citedByCount": cited})
    return enriched


def select_representative_papers(papers):
    """[대표 3편 선정] 계약 1-2 규칙 "최신순 1편 + 인용수 상위 2편".

    ① 최신 1편 — publishedAt 내림차순 1위.
       publishedAt이 없으면 year로 비교하고, 둘 다 없으면 최신 후보에서 제외한다.
       (비교는 "2026-08-06" / "2025" 같은 문자열 순서로 한다. 앞자리가 연도라 연도 비교가 먼저 이뤄지고,
        같은 연도라면 날짜가 있는 쪽이 더 뒤에 와서 우선한다 — 근거가 더 확실한 쪽을 고르는 셈이다.)
    ② 인용 상위 2편 — ①로 뽑힌 논문을 제외한 나머지 중 citedByCount 내림차순 2편.
       citedByCount가 null(OpenAlex 미등재)인 논문은 인용 후보에서 제외한다 — 0으로 취급하지 않는다.
    ③ 전체 논문이 3편 미만이면 있는 만큼만 담는다. 없는 논문을 채우지 않는다 (계약 원칙 2).

    동점 처리 규칙:
    - 최신 1편: publishedAt/year 값이 같으면 pmid 오름차순으로 앞선 것을 고른다.
      (순서를 고정해 두지 않으면 실행할 때마다 결과가 달라져 재현이 안 된다)
    - 인용 상위: 인용수가 같으면 연도(year)가 최신인 쪽을 우선하고,
      연도까지 같으면 pmid 오름차순으로 고른다.
    """
    # --- ① 최신 1편 ---
    # 정렬 키가 되는 날짜 문자열을 만든다. 둘 다 없으면 None → 후보에서 제외.
    def latest_key(paper):
        return paper.get("publishedAt") or (str(paper["year"]) if paper.get("year") else None)

    latest_candidates = [p for p in papers if latest_key(p)]
    latest = None
    if latest_candidates:
        # 날짜 내림차순, 동점이면 pmid 오름차순 → (-날짜, pmid) 대신 두 번 정렬해 뜻을 그대로 드러낸다
        latest_candidates.sort(key=lambda p: p["pmid"])
        latest_candidates.sort(key=latest_key, reverse=True)
        latest = latest_candidates[0]

    # --- ② 인용 상위 2편 (최신 1편 제외, null 제외) ---
    cited_candidates = [
        p for p in papers
        if p.get("citedByCount") is not None and (latest is None or p["pmid"] != latest["pmid"])
    ]
    cited_candidates.sort(key=lambda p: p["pmid"])                       # 동점의 마지막 기준
    cited_candidates.sort(key=lambda p: p.get("year") or 0, reverse=True)  # 인용수 동점이면 연도 최신 우선
    cited_candidates.sort(key=lambda p: p["citedByCount"], reverse=True)   # 1순위: 인용수
    top_cited = cited_candidates[:2]

    # --- ③ 계약 1-2 papers 모양(title/journal/year/pmid)으로만 추린다 ---
    # 순서는 "최신 1편 → 인용 상위 2편". abstract·publishedAt·citedByCount는
    # 파이프라인 내부용이라 계약 응답에 나가지 않으므로 여기서 뺀다.
    selected = ([latest] if latest else []) + top_cited
    selected_papers = [
        {"title": p["title"], "journal": p["journal"], "year": p["year"], "pmid": p["pmid"]}
        for p in selected
    ]

    # latestPaper는 API ③(최근 연구 활동 교수) 정렬용 백엔드 내부 필드다.
    # 최신 1편을 year로만 골랐다면 publishedAt은 지어내지 않고 null로 둔다 (계약 원칙 2).
    latest_paper = None
    if latest:
        latest_paper = {"pmid": latest["pmid"], "publishedAt": latest.get("publishedAt")}

    return selected_papers, latest_paper


def save_result(papers_with_citations, selected_papers, latest_paper):
    """[저장] 결과를 data/output/professor_test_enriched.json 파일로 저장한다."""
    result = {
        "collectedAt": date.today().isoformat(),  # 실행일 YYYY-MM-DD (계약 원칙 4)
        "papersWithCitations": papers_with_citations,
        "selectedPapers": selected_papers,
        "latestPaper": latest_paper,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)  # ensure_ascii=False: 한글이 깨지지 않게
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    # 실행 전 안전장치: API 키가 없으면 발급 방법을 안내하고 멈춘다 (exit 1)
    api_key = read_openalex_api_key()

    papers = load_papers()
    if not papers:
        raise SystemExit("1단계 결과에 논문이 0건입니다. fetch_one.py를 먼저 확인해 주세요.")

    counts = fetch_cited_by_counts([p["pmid"] for p in papers], api_key)
    papers_with_citations = attach_citations(papers, counts)
    selected_papers, latest_paper = select_representative_papers(papers_with_citations)
    save_result(papers_with_citations, selected_papers, latest_paper)

    # 통계: 사람이 결과를 바로 검수할 수 있게 한 줄로 요약한다
    with_citation = sum(1 for p in papers_with_citations if p["citedByCount"] is not None)
    missing = len(papers_with_citations) - with_citation
    selected_pmids = [p["pmid"] for p in selected_papers]
    print(
        f"전체 {len(papers_with_citations)}편 / 인용수 확보 {with_citation} / "
        f"OpenAlex 미등재 {missing} / 대표 {len(selected_pmids)}편: {selected_pmids}"
    )
