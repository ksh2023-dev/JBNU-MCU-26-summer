"""PubMed에서 교수 1명의 논문을 수집해 JSON으로 저장하는 1단계 검증 스크립트.

흐름: 검색(esearch) → 수집(efetch) → 저장(JSON 파일)

데이터 계약 v6.3 0장 "할루시네이션 방지 4원칙"을 그대로 따른다.
- pmid가 없는 논문은 결과에 넣지 않는다. (원칙 1)
- API 응답에 없는 값은 지어내지 않고 null(None)로 둔다. (원칙 2)
- 수집 기준일(collectedAt)을 결과에 담는다. 값은 원본 그대로, 재작성 금지. (원칙 4)
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

# ===== 입력 (실행 전 이 부분만 수정하면 됩니다) =================================
AUTHOR_NAME_EN = "REPLACE_ME"   # 예: "Gil Dong Hong" — 실행 전 실제 교수 영문명으로 교체
AFFILIATION = "Jeonbuk National University"
MAX_PAPERS = 20
# ==============================================================================

# PubMed E-utilities(공식 API) 주소 — API 키 없이 사용한다
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# API 예절: 키 없이는 초당 3회 제한 → 호출 사이에 0.4초 쉰다
SLEEP_SECONDS = 0.4

# 저장 위치: (저장소 루트)/data/output/professor_test.json
# 이 파일이 scripts/pubmed_collector/ 안에 있으므로 두 단계 위가 저장소 루트다.
# 이렇게 잡아 두면 어느 폴더에서 실행해도 같은 곳에 저장된다.
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "output" / "professor_test.json"

# PubMed가 월을 "May"처럼 영문 약어로 줄 때 숫자로 바꾸기 위한 표
MONTH_TO_NUM = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def search_pmids(author_query):
    """[1단계: 검색] esearch에 '이름[Author] AND 소속[Affiliation]'을 보내 PMID 목록을 얻는다.

    PubMed는 논문마다 고유 번호(PMID)를 붙여 두므로,
    먼저 검색으로 PMID 목록만 얻고 → 상세 내용은 2단계에서 PMID로 다시 요청한다.
    """
    params = {
        "db": "pubmed",          # PubMed 데이터베이스에서
        "term": author_query,    # 이 검색식으로 찾고
        "retmax": MAX_PAPERS,    # 최대 MAX_PAPERS건까지만 받는다
        "retmode": "json",       # 응답은 다루기 쉬운 JSON으로
    }
    resp = requests.get(ESEARCH_URL, params=params, timeout=30)
    resp.raise_for_status()  # 통신 실패(4xx/5xx)면 여기서 바로 멈춰서 알린다

    result = resp.json()["esearchresult"]
    pmids = result.get("idlist", [])
    print(f"검색 결과: 전체 {result.get('count', '?')}건 중 {len(pmids)}건 수집 (MAX_PAPERS={MAX_PAPERS})")
    return pmids


def fetch_papers(pmids):
    """[2단계: 수집] efetch(XML)로 논문 상세를 받아 계약 형식의 목록으로 만든다.

    칸 이름(title/journal/year/pmid)은 데이터 계약 papers 항목과 동일하게 유지한다.
    abstract/publishedAt은 뒤 단계(초록 검색·featured 정렬)에서 쓸 파이프라인 내부용 필드다.
    """
    # API 예절: 직전 esearch 호출과 간격을 둔다
    time.sleep(SLEEP_SECONDS)

    # PMID들을 쉼표로 묶어 한 번에 요청한다 (호출 횟수를 줄이는 것도 API 예절)
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    resp = requests.get(EFETCH_URL, params=params, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    papers = []
    for article in root.findall("PubmedArticle"):
        # --- pmid: 계약 원칙 1 — pmid 없는 논문은 결과에 넣지 않는다 ---
        pmid = (article.findtext("MedlineCitation/PMID") or "").strip()
        if not pmid:
            print("pmid 없음 → 결과에서 제외 (계약 원칙 1)")
            continue

        art = article.find("MedlineCitation/Article")
        if art is None:
            print(f"논문 본문 정보 없음 → 결과에서 제외: PMID {pmid}")
            continue

        # --- title: 제목 안에 <i>유전자명</i> 같은 태그가 섞일 수 있어 itertext로 전부 이어 붙인다 ---
        title_el = art.find("ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        title = title or None  # 응답에 없으면 지어내지 않고 null (계약 원칙 2)

        # --- journal: 학술지 이름 ---
        journal = (art.findtext("Journal/Title") or "").strip() or None

        # --- year: 발행 연도. Year 칸이 없으면 "2020 Jan-Feb" 같은 MedlineDate에서 연도만 뽑는다 ---
        pub_date_el = art.find("Journal/JournalIssue/PubDate")
        year = None
        if pub_date_el is not None:
            year_text = (pub_date_el.findtext("Year") or "").strip()
            if not year_text:
                match = re.search(r"\d{4}", pub_date_el.findtext("MedlineDate") or "")
                year_text = match.group() if match else ""
            if year_text.isdigit():
                year = int(year_text)

        # --- publishedAt(YYYY-MM-DD): 전자 출판일(ArticleDate)이 가장 정확해서 먼저 보고,
        #     없으면 학술지 발행일(PubDate)로 시도한다.
        #     연·월·일이 전부 있을 때만 만들고, 일부만 있으면 지어내지 않고 null (계약 원칙 2) ---
        published_at = None
        for date_el in (art.find("ArticleDate"), pub_date_el):
            if date_el is None:
                continue
            y = (date_el.findtext("Year") or "").strip()
            m = (date_el.findtext("Month") or "").strip()
            d = (date_el.findtext("Day") or "").strip()
            m = MONTH_TO_NUM.get(m, m)  # "May" → "05" (이미 숫자면 그대로)
            if y.isdigit() and m.isdigit() and d.isdigit():
                published_at = f"{y}-{int(m):02d}-{int(d):02d}"
                break

        # --- abstract: 초록이 배경/방법/결과처럼 여러 문단으로 나뉘어 올 수 있어 이어 붙인다 ---
        abstract_parts = []
        for part in art.findall("Abstract/AbstractText"):
            text = "".join(part.itertext()).strip()
            if not text:
                continue
            label = part.get("Label")  # 문단 제목(BACKGROUND 등)이 있으면 같이 남긴다
            abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = "\n".join(abstract_parts) or None
        if abstract is None:
            # 초록이 없는 논문은 null로 두고, 사람이 검수할 수 있게 콘솔에 알린다
            print(f"초록 없음: PMID {pmid}")

        papers.append({
            "title": title,
            "journal": journal,
            "year": year,
            "pmid": pmid,
            "publishedAt": published_at,
            "abstract": abstract,
        })

    print(f"수집 완료: 논문 {len(papers)}건")
    return papers


def save_result(author_query, papers):
    """[3단계: 저장] 수집 결과를 data/output/professor_test.json 파일로 저장한다."""
    result = {
        "collectedAt": date.today().isoformat(),  # 실행일 YYYY-MM-DD (계약 원칙 4: 수집 기준일 기록)
        "authorQuery": author_query,              # 어떤 검색식으로 모았는지 남겨 재현할 수 있게 한다
        "papers": papers,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)  # data/output 폴더가 없으면 만든다
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)  # ensure_ascii=False: 한글이 깨지지 않게
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    # 실행 전 안전장치: 교수 이름을 아직 바꾸지 않았으면 안내하고 멈춘다
    if AUTHOR_NAME_EN == "REPLACE_ME":
        raise SystemExit(
            "fetch_one.py 상단의 AUTHOR_NAME_EN을 실제 교수 영문명으로 바꾼 뒤 다시 실행하세요. "
            '(예: AUTHOR_NAME_EN = "Gil Dong Hong")'
        )

    # 검색에 사용할 문자열: "이름[Author] AND 소속[Affiliation]"
    author_query = f"{AUTHOR_NAME_EN}[Author] AND {AFFILIATION}[Affiliation]"
    print(f"PubMed 검색: {author_query}")

    pmids = search_pmids(author_query)
    if not pmids:
        # 0건이면 저장하지 않고 멈춘다 — 보통 영문명 표기(하이픈·띄어쓰기 등)가 달라서 그렇다
        raise SystemExit("검색 결과가 0건입니다. 교수 영문명 표기(예: Gil-Dong / Gil Dong)를 확인해 주세요.")

    papers = fetch_papers(pmids)
    save_result(author_query, papers)
