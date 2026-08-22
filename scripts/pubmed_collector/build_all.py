"""PubMed 수집 3단계: 전체 교수(243명)의 인용문 목록으로 논문을 수집하는 파이프라인.

흐름: 입력(교수별 인용문) 읽기
      → 인용문마다 제목 추출 (규칙 기반 파싱)
      → PubMed에 제목으로 검색해 PMID 확보 (1차: "제목"[Title] 구문 → 2차: 일반 term)
      → PMID 중복 제거 → efetch 상세 수집 (1단계 부품 재사용)
      → OpenAlex 인용수 부착 (2단계 부품 재사용)
      → 대표 3편 + latestPaper 선정 (2단계 부품 재사용)
      → 교수 1명이 끝날 때마다 data/output/professors_papers.json에 즉시 저장 (재개 가능)

안정성: 외부 API 호출(esearch·efetch·OpenAlex)은 일시 오류(5xx·네트워크 예외)면
5초 → 15초 간격으로 최대 3회 시도한다. 그래도 실패하면 배치 전체를 죽이는 대신
- 제목 검색 실패 → 그 논문만 notFound("HTTP 오류")로 기록하고 계속,
- efetch·OpenAlex 실패 → 그 교수를 review.fetchFailed에 기록하고 다음 교수로 계속한다.
  fetchFailed 교수는 저장되지 않으므로 재실행하면 자동으로 다시 시도된다.

전략 (작업지시서-3단계):
- 교수 본인 프로필 페이지의 논문 인용문 = 신원 보증 기준점. 인용문에서 뽑은 "제목"으로
  검색하므로, 이름+소속 검색보다 동명이인 위험이 낮다.
- (참고) 이름+소속 검색이라면 소속을 Jeonbuk/Chonbuk 두 표기로 병기해야 하지만(1단계 PR 리뷰),
  이번 방식은 제목 검색이라 직접 해당 없음 — 기록용 주석으로만 남긴다.
- 논문 0건인 82명은 이번 단계에서 수집하지 않는다. 빈 papers로 두고 review.noPapers에 기록만
  한다 (이름 기반 보완·KCI는 팀 결정 대기 중인 별도 작업).
- 논문 수 인위적 상한(MAX_PAPERS) 없음 — 인용문에 있는 논문은 전부 시도한다 (1단계 PR 리뷰 반영).

데이터 계약 v6.3:
- 원칙 1: pmid 없는 논문은 넣지 않는다 (재사용하는 fetch_papers가 보장).
- 원칙 2: 없는 값은 지어내지 않고 null. 검색 결과가 모호하면(같은 제목이 여럿) 넣지 않는다.
- 원칙 4: 수집 기준일(collectedAt)을 담고, 제목·학술지·연도는 PubMed 원본 그대로 둔다.
- papers·latestPaper의 칸 이름은 data/sample/professors.sample.json과 동일하게 유지한다.
"""

import difflib
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

# 1·2단계 부품 재사용 (기존 파일은 수정하지 않는다 — 같은 폴더라 바로 import 가능)
import fetch_one           # fetch_papers(pmids): efetch 상세 수집 + ESEARCH_URL
import enrich_citations    # read_openalex_api_key / fetch_cited_by_counts / attach_citations / select_representative_papers

# ===== 실행 옵션 (실행 전 이 부분만 수정하면 됩니다) ============================
FORCE_REFRESH = False   # True면 저장된 결과를 무시하고 전부 다시 수집
LIMIT = None            # 개발·검증용: 입력 목록 앞 N명만 처리 (None이면 전체 243명)
# run_all.py --limit N 스모크 테스트용 — 환경변수가 있으면 위 LIMIT보다 우선한다
import os as _os
if _os.environ.get("PIPELINE_LIMIT"):
    LIMIT = int(_os.environ["PIPELINE_LIMIT"])

# ==============================================================================

# API 예절: PubMed 호출(esearch·efetch) 사이 0.4초 — 1단계와 같은 값
SLEEP_SECONDS = 0.4

# 재시도 정책 — 일시적 서버 오류(5xx)·네트워크 예외 한 번에 수십 분짜리 배치 전체가
# 죽지 않게 한다. 4xx는 요청 자체가 잘못된 것이라 다시 보내도 같은 결과 → 재시도 없음.
RETRY_ATTEMPTS = 3      # 같은 호출을 최대 3회까지 시도
RETRY_WAITS = [5, 15]   # 시도 사이 대기(초): 1→2회차 5초, 2→3회차 15초

# 검색 결과가 이 수를 넘으면 "어느 논문인지 지목 불가"로 보고 notFound 처리한다.
# 제목 검색에서는 동명이인 대신 '흔한 문구가 여러 논문과 겹치는' 위험이 있는데,
# 그때 첫 번째 결과를 집으면 남의 논문이 붙는다 — 불확실하면 넣지 않는다 (계약 원칙 2).
AMBIGUOUS_HIT_LIMIT = 5

# 제목 후보 최소 길이(문자) — 이보다 짧은 조각은 제목으로 보지 않는다
MIN_TITLE_CHARS = 10

# 입출력 위치: (저장소 루트)/data/… — 어느 폴더에서 실행해도 같은 곳을 읽고 쓴다
ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "data" / "input" / "professor_paper_lists.json"
OUTPUT_PATH = ROOT / "data" / "output" / "professors_papers.json"


# ---------------------------------------------------------------------------
# 인용문 → 제목 추출 (규칙 기반 파싱)
#
# 인용문은 대체로 "저자들. 제목. 학술지. 연도;권(호):쪽" 구조다.
# 마침표+공백으로 조각을 나눈 뒤, "저자 조각"과 "서지 꼬리 조각"을 걸러내고
# 남은 조각에서 제목을 고른다. 완벽할 수 없으므로 실패는 지어내지 않고
# parseFailed(추출 실패)·notFound(검색 실패)로 기록해 사람이 검수하게 한다.
# ---------------------------------------------------------------------------

# 저자 한 명 꼴: "Oh SM" / "van der Berg JT" — 마지막 단어가 대문자 이니셜(1~3자)
_AUTHOR_LAST_RE = re.compile(r"[A-Z][A-Z.\-]{0,2}$")
_AUTHOR_WORD_RE = re.compile(r"[A-Za-z][A-Za-z.'’\-]*$")

# 서지 꼬리(학술지 권·호·쪽·연도·doi 등) 신호
_TAIL_PATTERNS = [
    re.compile(r"(19|20)\d{2}\s*;"),               # "2021;36(14)" — 연도;권
    re.compile(r";\s*\d+\s*\("),                   # ";36(" — 권(호
    re.compile(r"\d+\s*\(\d+\)\s*:"),              # "36(14):e101"
    re.compile(r"\bdoi\b|10\.\d{4,}/", re.I),      # doi 표기
    re.compile(r"\bEpub\b|\bPMID\b", re.I),        # 전자출판일·PMID 표기
    re.compile(r"^\(?(19|20)\d{2}\)?\s*[.,;]?$"),  # 연도만 있는 조각 "2012."
]


def _is_author_token(token):
    """쉼표로 나눈 토큰 하나가 '성 + 이니셜' 저자 표기인지 판별한다."""
    t = token.strip().rstrip(".")
    if not t:
        return False
    if t.lower() in {"et al", "and et al"}:
        return True
    words = t.split()
    if len(words) < 2 or len(words) > 4:           # "Kim NJ"~"van der Berg JT" 범위
        return False
    if not _AUTHOR_LAST_RE.fullmatch(words[-1]):   # 마지막 단어 = 대문자 이니셜
        return False
    return all(_AUTHOR_WORD_RE.fullmatch(w) for w in words[:-1])


def _is_author_segment(segment):
    """조각 하나가 저자 목록인지 판별 — 쉼표 토큰의 6할 이상이 저자 표기면 저자 조각."""
    tokens = [t for t in segment.split(",") if t.strip()]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if _is_author_token(t))
    if len(tokens) == 1:
        return hits == 1
    return hits / len(tokens) >= 0.6


def _is_reference_tail(segment):
    """조각 하나가 학술지 서지 꼬리(연도·권·호·쪽·doi 등)인지 판별한다."""
    return any(p.search(segment) for p in _TAIL_PATTERNS)


def _clean_title(text):
    """제목 후보에서 공백을 정리하고 끝의 마침표를 뗀다. ('?'로 끝나는 제목은 그대로 둔다)"""
    return re.sub(r"\s+", " ", text).strip().rstrip(" .")


def extract_title(citation):
    """인용문 문자열에서 논문 제목을 뽑는다. 실패하면 None (호출한 쪽이 parseFailed 기록).

    규칙:
    ① 마침표(.·?·!)+공백으로 조각을 나눈다.
    ② 저자 조각·서지 꼬리 조각·URL·너무 짧은 조각을 제외해 제목 후보를 만든다.
    ③ 저자 조각 바로 다음 후보가 있으면 그것이 제목 ("저자들. 제목. 학술지…" 구조).
    ④ 없으면 연도 숫자가 없는 후보를 우선하고, 그중 가장 긴 조각을 제목으로 본다.
       (인용문이 제목 하나뿐인 항목도 이 규칙으로 처리된다)
    """
    text = re.sub(r"\s+", " ", citation or "").strip()  # \s는 NBSP 등 유니코드 공백도 걸러낸다
    if not text:
        return None

    segments = [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]

    author_idx = None
    candidates = []  # (조각 위치, 정리된 제목 후보)
    for i, seg in enumerate(segments):
        if _is_author_segment(seg):
            if author_idx is None:
                author_idx = i
            continue
        if _is_reference_tail(seg) or re.match(r"https?://", seg):
            continue
        title = _clean_title(seg)
        if len(title) >= MIN_TITLE_CHARS:
            candidates.append((i, title))

    if not candidates:
        return None

    # ③ "저자들. 제목. …" — 저자 조각 바로 다음 후보가 가장 믿을 만하다
    if author_idx is not None:
        for i, title in candidates:
            if i == author_idx + 1:
                return title

    # ④ 연도 숫자가 없는 후보 우선("전남대학교출판부, 2015" 같은 출판 정보 배제), 그다음 긴 순
    candidates.sort(key=lambda c: (1 if re.search(r"(19|20)\d{2}", c[1]) else 0, -len(c[1])))
    return candidates[0][1]


# ---------------------------------------------------------------------------
# 외부 API 호출 재시도
# ---------------------------------------------------------------------------

class FetchFailedError(Exception):
    """efetch·OpenAlex가 재시도 후에도 실패했다는 신호.

    main()이 이걸 받아 교수를 review.fetchFailed에 기록하고 다음 교수로 넘어간다.
    해당 교수는 저장되지 않으므로 재실행하면 자동으로 다시 시도된다.
    """

    def __init__(self, stage, cause):
        super().__init__(f"{stage} 실패: {cause}")
        self.stage = stage   # "efetch" 또는 "openalex"
        self.cause = cause   # "HTTP 500" 같은 한 줄 요약


def _describe_error(exc):
    """예외를 기록용 한 줄로 요약한다 (HTTP 응답이 있으면 상태 코드, 없으면 예외 이름)."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(exc).__name__


def call_with_retry(description, func):
    """외부 API 호출 1건을 재시도로 감싼다. func는 인자 없는 함수(lambda)로 받는다.

    - 5xx 응답·네트워크 예외(타임아웃·연결 끊김 등): 5초 → 15초 쉬며 최대 3회 시도
    - 4xx 응답: 요청 자체의 문제라 다시 보내도 같은 결과 — 즉시 실패
    - 끝까지 실패하면 마지막 예외를 그대로 올린다 — 기록하고 계속할지는 호출한 쪽이 정한다
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return func()
        except requests.exceptions.RequestException as exc:
            response = getattr(exc, "response", None)
            if response is not None and 400 <= response.status_code < 500:
                raise
            if attempt == RETRY_ATTEMPTS:
                raise
            wait = RETRY_WAITS[attempt - 1]
            print(
                f"[재시도 {attempt + 1}/{RETRY_ATTEMPTS}] {description} "
                f"오류({_describe_error(exc)}) — {wait}초 후 다시 시도"
            )
            time.sleep(wait)


# ---------------------------------------------------------------------------
# PubMed 제목 검색
# ---------------------------------------------------------------------------

def _esearch(term):
    """esearch 1회 호출 — (전체 건수, PMID 목록) 반환. 출처: fetch_one.py의 search_pmids 변형.

    sort=relevance: 기본 정렬(최신순)은 여러 건이 걸릴 때 최신 논문이 무조건 1위가 되어
    남의 논문을 집을 수 있다. 관련도순이면 검색 문구와 가장 잘 맞는 논문이 1위가 된다.
    """
    params = {"db": "pubmed", "term": term, "retmax": 1, "retmode": "json", "sort": "relevance"}
    resp = requests.get(fetch_one.ESEARCH_URL, params=params, timeout=30)
    resp.raise_for_status()  # 통신 실패(4xx/5xx)면 여기서 멈춘다 — 재실행하면 이어서 진행(resume)
    result = resp.json()["esearchresult"]
    return int(result.get("count", "0") or 0), result.get("idlist", [])


def search_pmid_by_title(title):
    """제목으로 PMID 1건을 찾는다. 못 찾거나 모호하면 None (호출한 쪽이 notFound 기록).

    1차: "제목"[Title] 구문 검색 — 제목 칸에서 정확히 그 문구를 찾는다.
    2차: 1차가 0건이면 제목을 일반 term으로 검색 — 특수문자·표기 차이로
         구문 검색이 실패해도 단어 단위 검색으로는 걸리는 경우를 구제한다.

    통신이 재시도 후에도 실패하면 RequestException이 그대로 올라간다 —
    호출한 쪽(process_professor)이 그 논문만 notFound("HTTP 오류")로 기록하고 계속한다.
    """
    # 검색 필드 문법과 충돌하는 문자를 걷어낸다 (["]는 구문 경계, []는 필드 표기, ()는 묶음)
    query = re.sub(r"\s+", " ", re.sub(r'["\[\]{}()]', " ", title)).strip()
    if not query:
        return None

    time.sleep(SLEEP_SECONDS)
    count, ids = call_with_retry("PubMed 제목 검색(esearch)", lambda: _esearch(f'"{query}"[Title]'))
    if count == 0:
        time.sleep(SLEEP_SECONDS)
        count, ids = call_with_retry("PubMed 제목 검색(esearch)", lambda: _esearch(query))

    if count == 0 or not ids:
        return None
    if count > AMBIGUOUS_HIT_LIMIT:
        # 같은 문구가 여러 논문에 걸린다 — 어느 논문인지 지목할 수 없으므로 넣지 않는다 (원칙 2)
        return None
    return ids[0]


def _normalize_title(text):
    """제목 비교용 정규화 — 소문자로 바꾸고 문장부호·공백 차이를 없앤다."""
    return re.sub(r"[^0-9a-z가-힣]+", " ", (text or "").lower()).strip()


def titles_match(extracted, fetched):
    """인용문에서 뽑은 제목과 PubMed가 준 제목이 같은 논문인지 검증한다.

    검색은 어디까지나 '후보 찾기'다. 특히 2차(일반 term) 검색은 단어만 겹치는
    다른 논문을 돌려줄 수 있으므로, 수집한 제목을 인용문의 제목과 대조해
    일치하지 않으면 버린다 — 본인 페이지의 인용문이 신원 보증 기준점이기 때문이다.
    - 포함 관계 허용: 인용문 제목이 일부만 추출됐거나(부제 누락) 학술지명이 붙은 경우
    - 그 외에는 문자열 유사도 75% 이상일 때만 같은 논문으로 본다
    """
    a, b = _normalize_title(extracted), _normalize_title(fetched)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


# ---------------------------------------------------------------------------
# 교수 1명 처리 + 중간 저장(resume)
# ---------------------------------------------------------------------------

def empty_record():
    """논문 0건 교수의 자리 — 지어내지 않고 빈 값으로 둔다 (이름 기반 보완은 별도 단계)."""
    return {
        "papers": [],
        "latestPaper": None,
        "allPapers": [],
        "stats": {"cited": 0, "sourceEntries": 0, "collected": 0, "notFound": 0},
    }


def process_professor(name, entries, progress_label, api_key):
    """교수 1명의 인용문 목록을 논문 수집 결과로 바꾼다.

    반환: (교수 결과 dict, 파싱 실패 인용문 목록, 검색 실패 항목 목록)
    - 검색 실패 항목은 {"title": ...} 모양이고, 재시도까지 실패한 통신 오류로 포기한
      항목에는 "reason": "HTTP 오류"가 붙는다 (사람이 구분해 검수할 수 있게).
    - efetch·OpenAlex가 재시도 후에도 실패하면 FetchFailedError를 던진다 —
      main()이 fetchFailed로 기록하고 다음 교수로 넘어간다.
    """
    parse_failed = []      # 제목 추출 실패 인용문
    not_found = []         # 검색 실패(0건·모호·제목 불일치·통신 오류) 항목
    pmid_to_title = {}     # 확보한 PMID → 인용문에서 뽑은 제목 (입력 순서 유지 + 중복 제거)

    for entry in entries:
        citation = entry[0] if entry else ""
        title = extract_title(citation)
        if title is None:
            parse_failed.append(citation)
            continue
        try:
            pmid = search_pmid_by_title(title)
        except requests.exceptions.RequestException as exc:
            # 재시도까지 실패한 통신 오류 — 이 논문만 포기하고 다음 인용문으로 계속한다
            print(f"제목 검색 통신 실패({_describe_error(exc)}) → notFound(HTTP 오류) 기록 후 계속")
            not_found.append({"title": title, "reason": "HTTP 오류"})
            continue
        if pmid is None:
            not_found.append({"title": title})
        elif pmid not in pmid_to_title:   # PMID 기준 중복 제거 (같은 논문이 두 번 인용된 경우)
            pmid_to_title[pmid] = title

    searched = len(entries) - len(parse_failed)
    print(f"{progress_label} {name}: 인용문 {len(entries)}건 → PMID {len(pmid_to_title)}건 확보")

    # efetch 상세 수집 — 1단계 부품 재사용 (PMID를 쉼표로 묶어 한 번에 요청).
    # 재시도까지 실패하면 이 교수 전체를 fetchFailed로 넘긴다 (저장 안 함 → 재실행 때 자동 재시도).
    try:
        papers = (
            call_with_retry("PubMed 상세 수집(efetch)", lambda: fetch_one.fetch_papers(list(pmid_to_title)))
            if pmid_to_title
            else []
        )
    except requests.exceptions.RequestException as exc:
        raise FetchFailedError("efetch", _describe_error(exc))

    # 제목 대조 검증 — 검색이 돌려준 논문이 인용문의 그 논문이 맞는지 확인하고,
    # 다르면 결과에서 빼고 notFound로 돌린다 (불확실하면 넣지 않는다 — 원칙 2)
    verified = []
    for paper in papers:
        claimed_title = pmid_to_title.get(paper["pmid"], "")
        if titles_match(claimed_title, paper["title"]):
            verified.append(paper)
        else:
            print(f"제목 불일치로 제외: PMID {paper['pmid']} (다른 논문으로 판단 → notFound 기록)")
            not_found.append({"title": claimed_title})
    papers = verified

    # OpenAlex 인용수(50개 묶음) + 대표 3편 선정 — 2단계 부품 재사용.
    # efetch와 마찬가지로, 재시도까지 실패하면 이 교수 전체를 fetchFailed로 넘긴다.
    if papers:
        try:
            counts = call_with_retry(
                "OpenAlex 인용수 조회",
                lambda: enrich_citations.fetch_cited_by_counts([p["pmid"] for p in papers], api_key),
            )
        except requests.exceptions.RequestException as exc:
            raise FetchFailedError("openalex", _describe_error(exc))
        papers = enrich_citations.attach_citations(papers, counts)
        selected_papers, latest_paper = enrich_citations.select_representative_papers(papers)
    else:
        selected_papers, latest_paper = [], None

    record = {
        "papers": selected_papers,        # 대표 3편 — 계약 1-2와 같은 칸: title/journal/year/pmid
        "latestPaper": latest_paper,      # API ③ 정렬용 내부 필드: pmid/publishedAt
        "allPapers": papers,              # 전체 수집 논문 + citedByCount + abstract (내부용)
        "stats": {
            "cited": searched,            # 제목 추출에 성공해 검색을 시도한 인용문 수
            "sourceEntries": len(entries),  # 입력 인용문 수
            "collected": len(papers),     # 수집된 논문 수 (PMID 중복 제거 후)
            "notFound": len(not_found),   # 검색 실패 수
        },
    }
    return record, parse_failed, not_found


def load_state():
    """저장된 산출물을 읽어 이어서 진행할 준비를 한다. 없거나 FORCE_REFRESH면 새로 시작."""
    if not FORCE_REFRESH and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("professors", {})
        state.setdefault("review", {})
        for key in ("noPapers", "parseFailed", "notFound", "fetchFailed"):
            state["review"].setdefault(key, [])   # 이전 버전 산출물에 없던 목록도 채워 준다
        print(f"기존 산출물 발견: 교수 {len(state['professors'])}명 완료됨 → 이어서 진행 (resume)")
        return state
    return {
        "collectedAt": None,
        "professors": {},
        "review": {"noPapers": [], "parseFailed": [], "notFound": [], "fetchFailed": []},
    }


def save_state(state):
    """교수 1명이 끝날 때마다 호출 — 중간에 끊겨도 여기까지는 남는다 (갱신 로직의 기초).

    임시 파일에 먼저 쓰고 바꿔치기해서, 저장 도중 끊겨도 기존 파일이 깨지지 않게 한다.
    """
    state["collectedAt"] = date.today().isoformat()  # 수집 기준일 (계약 원칙 4)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)  # ensure_ascii=False: 한글 보존
    os.replace(tmp_path, OUTPUT_PATH)


def print_summary(state, elapsed_seconds, run_professors, run_searched):
    """실행이 끝날 때 사람이 검수할 수 있게 누적 통계를 요약한다."""
    professors = state["professors"]
    review = state["review"]
    searched = sum(p["stats"]["cited"] for p in professors.values())
    not_found = sum(p["stats"]["notFound"] for p in professors.values())
    collected = sum(p["stats"]["collected"] for p in professors.values())
    success = searched - not_found
    rate = (success / searched * 100) if searched else 0.0

    print("\n===== 누적 현황 =====")
    print(f"저장된 교수: {len(professors)}명 (논문 0건 {len(review['noPapers'])}명 포함)")
    print(f"제목 검색: 시도 {searched}건 / 성공 {success}건 ({rate:.1f}%) / notFound {not_found}건")
    print(f"수집 논문: {collected}편 (PMID 중복 제거 후)")
    print(
        f"review: noPapers {len(review['noPapers'])} / parseFailed {len(review['parseFailed'])}"
        f" / notFound {len(review['notFound'])} / fetchFailed {len(review['fetchFailed'])}"
    )
    if review["fetchFailed"]:
        names = ", ".join(e["professor"] for e in review["fetchFailed"])
        print(f"fetchFailed 교수는 저장되지 않았습니다 — 다시 실행하면 자동으로 재시도됩니다: {names}")
    print(f"이번 실행: 교수 {run_professors}명 · 검색 {run_searched}건 · {elapsed_seconds:.0f}초")
    print(f"저장 위치: {OUTPUT_PATH}")


def main():
    # OpenAlex API 키 — 없으면 발급 방법을 안내하고 여기서 중단한다 (exit 1).
    # 2단계 부품(enrich_citations)의 파서를 그대로 써서 같은 .env 값을 일관되게 읽는다.
    # PubMed(E-utilities) 호출에는 키가 필요 없다 — 이 키는 OpenAlex 전용이다.
    api_key = enrich_citations.read_openalex_api_key()

    if not INPUT_PATH.exists():
        print(f"입력 파일이 없습니다: {INPUT_PATH}")
        sys.exit(1)
    with open(INPUT_PATH, encoding="utf-8") as f:
        input_data = json.load(f)

    items = list(input_data.items())
    if LIMIT is not None:
        items = items[:LIMIT]
        print(f"LIMIT={LIMIT}: 입력 앞 {len(items)}명만 처리합니다 (검증용)")

    total_with_papers = sum(1 for _, entries in items if entries)
    print(f"대상: 교수 {len(items)}명 (논문 보유 {total_with_papers}명 · 0건 {len(items) - total_with_papers}명)")

    state = load_state()
    run_professors = 0
    run_searched = 0
    started = time.monotonic()
    position = 0  # 논문 보유 교수 기준 진행 번호 — "[12/161]"의 12

    for name, entries in items:
        if entries:
            position += 1
        if name in state["professors"]:
            print(f"{name}: 이미 완료 — 건너뜀 (resume)")
            continue

        if not entries:
            # 논문 0건 교수: 수집하지 않고 빈 papers + review.noPapers 기록만 (지시서 1장)
            state["professors"][name] = empty_record()
            state["review"]["noPapers"].append(name)
            save_state(state)
            print(f"{name}: 논문 0건 → review.noPapers 기록")
            continue

        try:
            record, parse_failed, not_found = process_professor(
                name, entries, f"[{position}/{total_with_papers}]", api_key
            )
        except FetchFailedError as exc:
            # 이 교수는 저장하지 않는다 — 재실행하면 자동으로 다시 시도된다.
            # 같은 교수의 옛 실패 기록은 갈아끼워, 실패가 반복돼도 목록이 불어나지 않게 한다.
            failed = state["review"]["fetchFailed"]
            failed[:] = [e for e in failed if e["professor"] != name]
            failed.append({"professor": name, "stage": exc.stage, "error": exc.cause})
            save_state(state)
            print(f"  → {name}: {exc.stage} 통신 실패 — fetchFailed 기록, 다음 교수로 계속")
            continue

        state["professors"][name] = record
        # 이번에 성공했으니 이전 실행에서 남았을 수 있는 fetchFailed 기록은 걷어낸다
        state["review"]["fetchFailed"] = [
            e for e in state["review"]["fetchFailed"] if e["professor"] != name
        ]
        for citation in parse_failed:
            state["review"]["parseFailed"].append({"professor": name, "citation": citation[:80]})
        for item in not_found:
            state["review"]["notFound"].append({"professor": name, **item})
        save_state(state)  # 교수 1명 끝날 때마다 즉시 저장 — 끊겨도 여기까지 보존

        run_professors += 1
        run_searched += record["stats"]["cited"]
        print(
            f"  → 수집 {record['stats']['collected']}편 · 대표 {len(record['papers'])}편"
            f" · notFound {record['stats']['notFound']} · parseFailed {len(parse_failed)}"
        )

    print_summary(state, time.monotonic() - started, run_professors, run_searched)


if __name__ == "__main__":
    main()
