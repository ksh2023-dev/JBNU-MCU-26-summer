"""PubMed 수집 3단계: 전체 교수(243명)의 인용문 목록으로 논문을 수집하는 파이프라인.

흐름: 입력(교수별 인용문) 읽기
      → 인용문마다 제목·학술지명 추출 (뒤에서부터 서지 꼬리를 떼는 역방향 파싱)
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
import citation_utils      # 저자 표기 판별 (C단계 enrich_authors_mesh와 공유)
import fetch_one           # fetch_papers(pmids): efetch 상세 수집 + ESEARCH_URL
import enrich_citations    # read_openalex_api_key / fetch_cited_by_counts / attach_citations / select_representative_papers

# ===== 실행 옵션 (실행 전 이 부분만 수정하면 됩니다) ============================
FORCE_REFRESH = False   # True면 저장된 결과를 무시하고 전부 다시 수집
LIMIT = None            # 개발·검증용: 입력 목록 앞 N명만 처리 (None이면 전체 243명)
# ==============================================================================

# API 예절: PubMed 호출(esearch·efetch) 사이 0.4초 — 1단계와 같은 값
SLEEP_SECONDS = 0.4

# 재시도 정책 — 일시적 서버 오류(5xx)·네트워크 예외 한 번에 수십 분짜리 배치 전체가
# 죽지 않게 한다. 4xx는 요청 자체가 잘못된 것이라 다시 보내도 같은 결과 → 재시도 없음.
RETRY_ATTEMPTS = 3      # 같은 호출을 최대 3회까지 시도
RETRY_WAITS = [5, 15]   # 시도 사이 대기(초): 1→2회차 5초, 2→3회차 15초

# 제목 검색에서 받아 볼 후보 수. 예전에는 1위만 받고 "히트 수가 많으면 모호"로 버렸는데,
# 정답이 2·3위에 있거나(7편) 1위가 정답인데 히트 수 때문에 버려진(10편) 손실이 있었다.
# 후보를 늘려도 채택 기준(titles_match)은 그대로라 오귀속 위험은 늘지 않는다.
SEARCH_RETMAX = 10

# efetch를 한 번에 요청할 PMID 수 — 후보가 늘어 URL이 길어지므로 나눠 부른다
EFETCH_BATCH = 100

# 제목 후보 최소 길이(문자) — 이보다 짧은 조각은 제목으로 보지 않는다
MIN_TITLE_CHARS = 10

# 제목의 한글 비중이 이 값을 넘으면 PubMed 검색을 건너뛴다.
#
# 왜 필요한가: 한글 제목에 섞인 영문 낱말만 걸려 엉뚱한 논문이 붙는다. 실제로
#   "대상포진 Up-to-Date"                → "Up-to-Date."(Int J Urol 2018)
#   "…만성폐쇄성폐질환(COPD) 임상진료지침"  → "Copd."(BMJ Clin Evid 2011)
#   "…Donepezil이 인지 기능에 미치는 효과"  → "Donepezil."(Drugs & Aging 1997)
# 이 붙었다. PubMed는 국제지, KCI는 국내지라는 수집 설계와도 맞다.
#
# 임계값 근거(2026-08-21 실측, 제목 추출 성공 1,974건):
#   10% 이상 245건 · 20% 이상 228 · 30% 이상 223 · 50% 이상 202 · 90% 이상 162
#   10~30% 구간 22건은 **영문 제목에 한글 학술지명만 붙은 것**이라 검색 대상으로 남겨야 한다
#   ("Extrapelvic endometriosis. 대한외과학회지"). 30%를 넘으면 제목 자체가 한글이다.
#   30% 이상 223건이 실제로 끌어온 논문은 2건뿐이었고 둘 다 오귀속이었다(오탐 0건).
KOREAN_TITLE_RATIO = 0.30

# 입출력 위치: (저장소 루트)/data/… — 어느 폴더에서 실행해도 같은 곳을 읽고 쓴다
ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "data" / "input" / "professor_paper_lists.json"
OUTPUT_PATH = ROOT / "data" / "output" / "professors_papers.json"
# 사람이 검수해 확정한 오귀속 목록 (커밋 대상 — 산출물에서 지우면 재실행 때 되살아난다)
MANUAL_EXCLUSIONS_PATH = ROOT / "data" / "input" / "manual_exclusions.json"


# ---------------------------------------------------------------------------
# 인용문 → 제목·학술지명 추출 (역방향 파싱)
#
# Vancouver/NLM 인용 형식은 앞쪽(저자·제목)보다 뒤쪽이 규칙적이다:
#     [저자들.] 제목. 학술지명. 연도 월 일;권(호):쪽.
# 그래서 앞에서부터 첫 마침표까지를 제목으로 보면, 제목 안에 마침표나 숫자가
# 있을 때(예: "… Records of 2000-2019.") 거기서 잘리고 그 다음 조각인 학술지명이
# 제목 자리로 올라온다 — 실제로 "J Korean Med Sci"가 제목으로 뽑혀 엉뚱한 논문이
# 붙는 오귀속이 발생했다.
#
# 그래서 뒤에서부터 떼어낸다:
#   ⓪ 역순 형식("학술지명. 연도;권(호):쪽 (제목)")이면 괄호 안이 제목이다
#   ① 서지 꼬리(doi·Epub·PMID → 연도·권·호·쪽)를 잘라내고
#   ② 남은 "…제목. 학술지명"에서 뒤쪽 학술지명을 떼어내고
#   ③ 제목 앞뒤에 붙은 저자 목록과 앞머리 연도를 떼어낸다
#   ④ 남은 앞부분 전체가 제목이다 — 제목 안의 마침표·숫자에 영향받지 않는다
#
# 꼬리 시작 위치는 하나로 단정할 수 없다(제목 안의 연도, "2025, 제목, 학술지"처럼
# 연도가 맨 앞에 오는 표기 등). 그래서 후보를 이른 것부터 차례로 잘라 보고,
# 제목이 남는 첫 후보를 채택한다. 어느 후보로도 제목이 남지 않으면 아예 자르지 않고
# 마지막으로 한 번 더 시도한다.
#
# 형식이 예상과 다르면 제목을 추측하지 않는다 — None을 돌려주고 호출한 쪽이
# parseFailed에 기록해 사람이 검수하게 한다 (계약 원칙 2: 지어내지 않는다).
# ---------------------------------------------------------------------------

# 저자 표기 판별은 citation_utils.py에 있다 — C단계 enrich_authors_mesh.py가 같은 규칙을
# 써야 하기 때문이다. 여기서는 이름만 짧게 빌려 쓴다.
_NAME_WORD = citation_utils.NAME_WORD
_GLUED_AUTHOR = citation_utils.GLUED_AUTHOR
_GLUED_FULLNAME = citation_utils.GLUED_FULLNAME
_SEMI_AUTHOR_RUN = citation_utils.SEMI_AUTHOR_RUN
_CREDENTIAL_PREFIX_RE = citation_utils.CREDENTIAL_PREFIX_RE
_ET_AL_PREFIX_RE = citation_utils.ET_AL_PREFIX_RE

# 인용문 앞머리의 표기 — "<주저자>", "<i>" 같은 꼬리표. 한글이 든 것과 html 태그만 뗀다
# (제목 안에 나오는 "[18F]", "[2000]"을 건드리지 않기 위해서다)
_LEADING_MARKER_RE = re.compile(r"^(?:</?[a-zA-Z]{1,6}>|[<\[][^<>\[\]]*[가-힣][^<>\[\]]*[>\]])\s*")

# ① 인용문 맨 끝에 붙는 부가 정보 — 꼬리를 찾기 전에 먼저 떼어낸다
_TRAILING_NOISE = [
    re.compile(r"\s*https?://\S+\s*$", re.I),
    re.compile(r"\s*PMID:?\s*\d+.*$", re.I),
    re.compile(r"\s*PMCID:?\s*\S+.*$", re.I),
    re.compile(r"\s*Epub\s+.*$", re.I),
    re.compile(r"\s*doi:?\s*10\.\d{4,}/\S*\s*$", re.I),
]

# ② 서지 꼬리의 시작 신호. 제목 안에도 연도가 들어갈 수 있으므로("2000-2019",
#    "The 2017 … Charts") '연도 뒤에 권·호 구분자가 오는' 모양만 꼬리로 인정한다.
_TAIL_START_RE = re.compile(
    r"""
      (?<![-–\d])(?:19|20)\d{2}                         # 연도 "2021" (앞에 하이픈·숫자가 붙으면
                                                        #  "2007-2021:" 같은 연도 범위라 꼬리가 아니다)
      (?:\s+[A-Za-z]{3,9}(?:\s*[-–]\s*[A-Za-z]{3,9})?)? #  " Sep" / " Nov-Dec"
      (?:\s+\d{1,2})?                                   #  " 13"
      \s*[;:,]                                          # 뒤따르는 권·호 구분자
    | \d+\s*\(\s*(?:19|20)\d{2}\s*\)                    # "17 (2023) 436-443"
    | \(\s*(?:19|20)\d{2}\s*\)                          # "… (2010)"
    | \b(?:19|20)\d{2}\s*\.?\s*$                        # 끝에 연도만 "… 2018"
    | \b\d{1,4}\s*[-–]\s*\d{1,4}\s*\.?\s*$              # 끝에 쪽 범위 "753-757."
    """,
    re.X,
)

# 제목 앞머리에 오는 발행연도: "2025, 제목…" / "(2013) 제목…". 뒤에 구분자나 괄호가
# 있을 때만 뗀다 — "2017 Korean National Growth Charts"처럼 연도로 시작하는 제목 보호.
_YEAR_PREFIX_RE = re.compile(
    r"^\s*(?:\(\s*(?:19|20)\d{2}\s*\)|\[\s*(?:19|20)\d{2}\s*\]|(?:19|20)\d{2}\s*[.,;:])\s*"
)

# ⓪ 역순 형식의 제목 자리 — 인용문 맨 끝의 괄호
_TRAILING_PAREN_RE = re.compile(r"\(([^()]+)\)\s*$")

# 학술지명은 대문자(또는 숫자)로 시작한다 — "J Korean Med Sci" "Nutrients" "BMB report"
_JOURNAL_START_RE = re.compile(r"[A-Z0-9]")

# 학술지명 자리로 인정할 최대 길이(단어). "Allergy Asthma Immunol Res" 같은 약어가 대상
_JOURNAL_MAX_WORDS = 8
# 학술지명을 떼어낸 뒤 제목으로 남아야 하는 최소 단어 수 — 이보다 적게 남으면 떼지 않는다
_TITLE_MIN_WORDS = 4
# 제목 후보 최소 길이(문자) — 이보다 짧은 조각은 제목으로 보지 않는다
MIN_TITLE_CHARS = 10

# 제목의 한글 비중이 이 값을 넘으면 PubMed 검색을 건너뛴다.
#
# 왜 필요한가: 한글 제목에 섞인 영문 낱말만 걸려 엉뚱한 논문이 붙는다. 실제로
#   "대상포진 Up-to-Date"                → "Up-to-Date."(Int J Urol 2018)
#   "…만성폐쇄성폐질환(COPD) 임상진료지침"  → "Copd."(BMJ Clin Evid 2011)
#   "…Donepezil이 인지 기능에 미치는 효과"  → "Donepezil."(Drugs & Aging 1997)
# 이 붙었다. PubMed는 국제지, KCI는 국내지라는 수집 설계와도 맞다.
#
# 임계값 근거(2026-08-21 실측, 제목 추출 성공 1,974건):
#   10% 이상 245건 · 20% 이상 228 · 30% 이상 223 · 50% 이상 202 · 90% 이상 162
#   10~30% 구간 22건은 **영문 제목에 한글 학술지명만 붙은 것**이라 검색 대상으로 남겨야 한다
#   ("Extrapelvic endometriosis. 대한외과학회지"). 30%를 넘으면 제목 자체가 한글이다.
#   30% 이상 223건이 실제로 끌어온 논문은 2건뿐이었고 둘 다 오귀속이었다(오탐 0건).
KOREAN_TITLE_RATIO = 0.30


# 저자 판별 — 구현은 citation_utils.py에 있다 (C단계와 공유)
_is_author_token = citation_utils.is_author_token
_is_author_segment = citation_utils.is_author_segment
_is_fullname_token = citation_utils.is_fullname_token
_is_name_fragment = citation_utils.is_name_fragment
_looks_like_author = citation_utils.looks_like_author


_HANGUL_RE = re.compile(r"[가-힣]")
_LETTER_RE = re.compile(r"[가-힣A-Za-z]")


def hangul_ratio(text):
    """제목에서 한글이 차지하는 비중. 글자(한글+로마자)만 세고 숫자·기호는 빼서
    "제 10판(2012)" 같은 표기에 좌우되지 않게 한다."""
    letters = _LETTER_RE.findall(text or "")
    if not letters:
        return 0.0
    return len(_HANGUL_RE.findall(text or "")) / len(letters)


def is_korean_title(title):
    """PubMed 검색을 건너뛸 한글 제목인가 (KOREAN_TITLE_RATIO 주석 참고)."""
    return hangul_ratio(title) >= KOREAN_TITLE_RATIO


def _clean_title(text):
    """제목 후보에서 공백을 정리하고 끝의 마침표를 뗀다. ('?'로 끝나는 제목은 그대로 둔다)"""
    return re.sub(r"\s+", " ", text).strip().rstrip(" .")


def _strip_trailing_noise(text):
    """인용문 끝의 doi·Epub·PMID·URL을 떼어낸다 (꼬리 탐색을 방해하므로 먼저 처리)."""
    for pattern in _TRAILING_NOISE:
        text = pattern.sub("", text)
    return text.strip()


def _split_journal(head):
    """② "…제목. 학술지명"에서 뒤쪽 학술지명을 떼어 (제목부, 학술지명)으로 나눈다.

    확신이 없으면 떼지 않고 (head, None)을 돌려준다 — 제목이 잘리는 것보다
    학술지명이 제목에 붙어 있는 편이 낫다(검색은 그래도 성공한다).
    경계는 마침표 우선, 없으면 쉼표 — "제목, J Craniofac Surg" 형식도 있기 때문이다.
    """
    for boundary in (r"\.\s*(?=\S)", r",\s+"):
        spots = [m.end() for m in re.finditer(boundary, head)]
        if not spots:
            continue
        cut = spots[-1]                            # 가장 뒤쪽 경계 = 학술지명 시작
        journal = head[cut:].strip(" .,;:")
        title_part = head[:cut].strip(" .,;:")
        if not journal or not title_part:
            continue
        if not _JOURNAL_START_RE.match(journal):
            continue                               # 학술지명은 대문자로 시작한다.
            # 이 조건이 없으면 "…development, improvement, and prospects"의
            # "and prospects"가 학술지명으로 떨어져 제목이 잘린다.
        if len(journal.split()) > _JOURNAL_MAX_WORDS:
            continue                               # 너무 길다 — 학술지명이 아니라 제목의 일부
        if len(title_part.split()) < _TITLE_MIN_WORDS or len(title_part) < MIN_TITLE_CHARS:
            continue                               # 떼고 나면 제목이 남지 않는다 — 떼지 않는다
        return title_part, journal
    return head, None


def _strip_leading_authors(text):
    """③-1 제목 앞에 붙은 저자 목록을 떼어낸다.

    지원하는 표기:
      · "Lee CS, Kim JG, Yang YM. 제목…"                (성 + 이니셜)
      · "Shin YS, Zhang LT, Zhao C, et al. 제목…"        (et al. 접두)
      · "Heung Yong Jin, Kyung Ae Lee, Tae Sun Park. 제목…"  (전체 이름)
      · "Jun Tak Choi, MD, Jeong-Hwan Seo, MD, PhD, … 제목…"  (학위 표기 섞임)
      · "Kim, Yeshin; Kang, Dong Woo; …; Suh, Jeewon. 제목…"  (세미콜론 목록)
      · "Choo, Ahn SH, Oh DS, … Shin BS. 제목…"          (첫 이름에 이니셜 누락)

    전부 저자였으면 빈 문자열을 돌려준다 — 호출한 쪽이 이 후보를 버리고 다음을 시도한다.
    """
    stripped = text.lstrip(" .")

    # "Last, First; Last, First. 제목" 형식은 통째로 떼어낸다
    semi = _SEMI_AUTHOR_RUN.match(stripped)
    if semi:
        rest = stripped[semi.end():].strip()
        if len(rest) >= MIN_TITLE_CHARS:
            return rest

    parts = stripped.split(",")

    # 문맥까지 보는 판정 — 저자로 보이는 토큰이 하나뿐이고 뒤에 제목이 붙어 있지도 않으면
    # 저자로 보지 않는다 ("Serum Vitamin D" 같은 제목을 통째로 잃지 않기 위해서다)
    end = citation_utils.author_run_end(parts, 0)
    if end == 0:
        # 전체 이름 표기 저자 목록 — 연속 2명 이상일 때만 저자로 본다
        k = 0
        while k < len(parts) and _is_fullname_token(parts[k]):
            k += 1
        if k >= 2:
            end = k
        elif _is_name_fragment(parts[0]) and citation_utils.author_run_end(parts, 1) - 1 >= 2:
            # 첫 이름에 이니셜이 빠진 원문 오타("Choo, Ahn SH, Oh DS, …") — 한 칸만 봐준다.
            # 첫 토큰이 '성 하나'처럼 짧을 때만이다. 이 조건이 없으면
            # "제목…. Lee DW, Kim JG, Yang YM"의 제목까지 저자로 먹어 버린다.
            end = citation_utils.author_run_end(parts, 1)
    if end == 0:
        return text

    rest = ",".join(parts[end:]).strip()
    # 마지막 저자가 제목과 붙어 있는 경우
    for pattern in (r"^(" + _GLUED_AUTHOR + r")\.\s*(?=\S)",
                    r"^(" + _GLUED_FULLNAME + r")\.\s*(?=\S)"):
        glued = re.match(pattern, rest)
        if glued and (_looks_like_author(glued.group(1)) or _is_fullname_token(glued.group(1))):
            rest = rest[glued.end():]
            break
    rest = _CREDENTIAL_PREFIX_RE.sub("", rest)     # "PhD. 제목…"
    rest = _ET_AL_PREFIX_RE.sub("", rest)          # "et al. 제목…"
    return rest.strip()


def _strip_trailing_authors(text):
    """③-2 제목 뒤에 붙은 저자 목록을 떼어낸다 ("제목. Lee DW, Kim JG, Yang YM")."""
    parts = text.split(",")
    j = len(parts)
    while j > 0 and _looks_like_author(parts[j - 1]):
        j -= 1
    # 앞쪽과 같은 문맥 조건 — 뒤에 붙은 저자가 한 명뿐이고 그 앞이 제목과 마침표로
    # 이어지지 않으면 저자로 보지 않는다
    if len(parts) - j == 1 and len(parts[j].split()) > 2:
        glued = re.search(r"\.\s*(" + _GLUED_AUTHOR + r")\s*$", ",".join(parts[:j]).strip())
        if not (glued and _looks_like_author(glued.group(1))):
            return text
    if j == len(parts):
        return text
    head = ",".join(parts[:j]).strip()
    # 첫 저자가 제목과 붙어 있는 경우: "… Case Reports. Lee DW"
    glued = re.search(r"\.\s*(" + _GLUED_AUTHOR + r")\s*$", head)
    if glued and _looks_like_author(glued.group(1)):
        head = head[: glued.start()]
    return head.strip(" .,")


def _title_from_head(head):
    """꼬리를 떼어낸 앞부분에서 (제목, 학술지명)을 뽑는다. 제목이 안 남으면 (None, 학술지명)."""
    title_part, journal = _split_journal(head)
    title_part = _strip_trailing_authors(_strip_leading_authors(title_part))
    title = _clean_title(_YEAR_PREFIX_RE.sub("", title_part))
    if len(title) < MIN_TITLE_CHARS:
        return None, journal
    return title, journal


def _parse_reversed(text):
    """⓪ 역순 형식 "학술지명. 연도;권(호):쪽 (제목)" 이면 (제목, 학술지명)을 돌려준다.

    정윤규 교수 인용문 10건이 전부 이 형식이다. 일반 파싱에 맡기면 첫 꼬리 신호에서
    잘려 "Arch Craniofac Surg"(학술지명)가 제목이 되어 버린다.

    맨 뒤 괄호가 곧 제목이라고 단정하면 안 된다 — "제목? (학술지명…)" 처럼 반대인
    인용문도 있다(오세웅 교수 7건). 그래서 괄호 앞부분이 '서지 꼬리를 가진 학술지명'
    모양일 때만 역순으로 판정한다.
    """
    paren = _TRAILING_PAREN_RE.search(text)
    if not paren:
        return None
    inner = _clean_title(paren.group(1))
    if len(inner) < MIN_TITLE_CHARS or len(inner.split()) < _TITLE_MIN_WORDS:
        return None
    head = text[: paren.start()].strip(" .,;:-–")
    if not head:
        return None
    tails = list(_TAIL_START_RE.finditer(head))
    if not tails:
        return None                                # 서지 꼬리가 없으면 역순 형식이 아니다
    journal = head[: tails[0].start()].strip(" .,;:-–")
    if not journal or len(journal.split()) > _JOURNAL_MAX_WORDS:
        return None                                # 앞부분이 학술지명 한 덩어리가 아니다
    if not _JOURNAL_START_RE.match(journal):
        return None
    return inner, journal


def parse_citation(citation):
    """인용문에서 (제목, 학술지명)을 뽑는다. 제목을 못 뽑으면 (None, 학술지명).

    학술지명은 titles_match()가 "제목 자리에 학술지명이 들어온" 파싱 실패를
    걸러내는 데 쓴다. 학술지명을 못 찾았으면 None이다.
    """
    text = re.sub(r"\s+", " ", citation or "").strip()  # \s는 NBSP 등 유니코드 공백도 걸러낸다
    if not text:
        return None, None
    text = _LEADING_MARKER_RE.sub("", _strip_trailing_noise(text)).strip()
    if not text:
        return None, None

    reversed_form = _parse_reversed(text)
    if reversed_form:
        return reversed_form

    # 꼬리 후보를 이른 것부터 잘라 보고, 제목이 남는 첫 후보를 채택한다.
    # 마지막 후보 len(text)는 "꼬리를 못 찾았으니 자르지 않는다"는 뜻이다.
    cuts = [m.start() for m in _TAIL_START_RE.finditer(text)] + [len(text)]
    journal = None
    for cut in cuts:
        head = text[:cut].strip(" .,;:-–")
        if not head:
            continue
        title, found_journal = _title_from_head(head)
        journal = found_journal or journal
        if title:
            return title, found_journal
    return None, journal                           # 지어내지 않는다 — parseFailed로 넘긴다


def extract_title(citation):
    """인용문에서 제목만 뽑는다 (parse_citation의 얇은 껍데기). 실패하면 None."""
    return parse_citation(citation)[0]


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

def _esearch(term, retmax=1):
    """esearch 1회 호출 — (전체 건수, PMID 목록) 반환. 출처: fetch_one.py의 search_pmids 변형.

    sort=relevance: 기본 정렬(최신순)은 여러 건이 걸릴 때 최신 논문이 무조건 1위가 되어
    남의 논문을 집을 수 있다. 관련도순이면 검색 문구와 가장 잘 맞는 논문이 1위가 된다.
    다만 아래 search_pmid_candidates()가 순위가 아니라 제목 대조로 고르므로,
    정렬 순서에 결과가 좌우되지는 않는다.
    """
    params = {"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json", "sort": "relevance"}
    resp = requests.get(fetch_one.ESEARCH_URL, params=params, timeout=30)
    resp.raise_for_status()  # 통신 실패(4xx/5xx)면 여기서 멈춘다 — 재실행하면 이어서 진행(resume)
    result = resp.json()["esearchresult"]
    return int(result.get("count", "0") or 0), result.get("idlist", [])


def search_pmid_candidates(title):
    """제목으로 후보 PMID를 최대 SEARCH_RETMAX건 받아 온다. 못 찾으면 빈 목록.

    1차: "제목"[Title] 구문 검색 — 제목 칸에서 정확히 그 문구를 찾는다.
    2차: 1차가 0건이면 제목을 일반 term으로 검색 — 특수문자·표기 차이로
         구문 검색이 실패해도 단어 단위 검색으로는 걸리는 경우를 구제한다.

    **채택하지 않는다.** 어느 후보가 맞는지는 호출한 쪽이 efetch로 받은 실제 제목과
    titles_match()로 대조해 결정한다. 예전에는 여기서 retmax=1로 1위만 받고
    "히트 수가 많으면 모호하니 버린다"(hit>5)로 판단했는데, 둘 다 틀린 기준이었다:
      · 일반 term 검색의 히트 수는 단어 조합 때문에 자연히 커서 모호도를 뜻하지 않는다.
        실제로 정답이 1위인데 hit>5라는 이유만으로 버린 논문이 10편 있었다.
      · 1위만 보면 2·3위에 있는 정답을 아예 못 본다 (7편이 이 경우였다).
    후보를 늘려도 판정 기준(titles_match)은 그대로이므로 오귀속 위험은 늘지 않는다.

    통신이 재시도 후에도 실패하면 RequestException이 그대로 올라간다 —
    호출한 쪽(process_professor)이 그 논문만 notFound("HTTP 오류")로 기록하고 계속한다.
    """
    # 검색 필드 문법과 충돌하는 문자를 걷어낸다 (["]는 구문 경계, []는 필드 표기, ()는 묶음)
    query = re.sub(r"\s+", " ", re.sub(r'["\[\]{}()]', " ", title)).strip()
    if not query:
        return []

    time.sleep(SLEEP_SECONDS)
    count, ids = call_with_retry(
        "PubMed 제목 검색(esearch)", lambda: _esearch(f'"{query}"[Title]', SEARCH_RETMAX)
    )
    if count == 0:
        time.sleep(SLEEP_SECONDS)
        count, ids = call_with_retry(
            "PubMed 제목 검색(esearch)", lambda: _esearch(query, SEARCH_RETMAX)
        )
    return ids


def _normalize_title(text):
    """제목 비교용 정규화 — 소문자로 바꾸고 문장부호·공백 차이를 없앤다."""
    return re.sub(r"[^0-9a-z가-힣]+", " ", (text or "").lower()).strip()


# 부분 일치(포함 관계)를 허용할, 인용문에서 뽑은 제목의 최소 크기.
# 근거: "J Korean Med Sci"(4단어·16자) 같은 학술지명이 제목 자리로 잘못 올라오면,
# 그 문구를 제목 안에 담고 있는 남의 논문(정정·회신 공지 등)에 그대로 포함되어
# 오귀속이 검증을 통과해 버렸다. 짧을수록 우연히 포함될 확률이 높다.
# 문턱은 '인용문에서 뽑은 쪽'에만 건다 — PubMed가 준 제목은 실제 논문 제목이라
# 짧아도("Young girl with chest pain") 파싱 실패 조각이 아니기 때문이다.
SUBSTRING_MIN_WORDS = 6
SUBSTRING_MIN_CHARS = 40

# 유사도 문턱 — 기존 값 0.75를 유지한다. 실제 수집 데이터로 확인한 근거:
# 같은 논문인데 표기가 다른 최악의 사례가 "Malaria-induced splenic infarction" ↔
# "Falciparum Malaria-Induced Splenic Infarction"(0.86)이고, 학술지명이 제목으로
# 올라온 오귀속 사례는 전부 0.2 미만이라 두 무리가 0.75를 사이에 두고 확실히 갈린다.
SIMILARITY_THRESHOLD = 0.75

# 정정·철회 공지 레코드 — 원논문 제목을 그대로 품고 있어서 부분 일치로 통과해 버린다.
# 실제로 원논문 대신 이 레코드가 수집된 사례가 3건 있었다(송은기·김성훈·이재홍).
# 회신(Letter to the Editor)·논평(Comment on)은 교수 본인이 저자일 수 있으므로 넣지 않는다.
_CORRECTION_NOTICE_RE = re.compile(
    r"^\s*(?:erratum|corrigendum|correction|publisher'?s?\s+correction|author\s+correction"
    r"|retraction|retraction\s+note|notice\s+of\s+retraction|withdrawn"
    r"|expression\s+of\s+concern)\b",
    re.I,
)


def _comparable_pieces(extracted):
    """비교에 쓸 조각들 — 추출 제목 전체와, 문장(.?!) 단위로 나눈 조각.

    "Is Propofol Good Choice for Procedural Sedation? Evaluation of Propofol …"처럼
    인용문이 두 문장이고 그중 한 문장이 논문 제목인 경우를 구제한다.
    조각도 아래 길이 문턱을 넘어야 쓰이므로 학술지명 같은 짧은 조각은 통과하지 못한다.
    """
    whole = _normalize_title(extracted)
    pieces = [whole]
    for sentence in re.split(r"(?<=[.?!])\s+", extracted or ""):
        piece = _normalize_title(sentence)
        if piece and piece != whole:
            pieces.append(piece)
    return pieces


def titles_match(extracted, fetched, journal=None):
    """인용문에서 뽑은 제목과 PubMed가 준 제목이 같은 논문인지 검증한다.

    검색은 어디까지나 '후보 찾기'다. 특히 2차(일반 term) 검색은 단어만 겹치는
    다른 논문을 돌려줄 수 있으므로, 수집한 제목을 인용문의 제목과 대조해
    일치하지 않으면 버린다 — 본인 페이지의 인용문이 신원 보증 기준점이기 때문이다.
    - journal이 주어지고 추출 제목이 그 학술지명과 같으면 즉시 거부한다
      (제목 자리에 학술지명이 들어온 것 = 파싱 실패이므로 어떤 논문도 인정하지 않는다)
    - 정정·철회 공지 레코드는 거부한다 (인용문이 그 공지를 가리키는 게 아닌 한)
    - 포함 관계는 추출 제목(또는 그 문장 조각)이 충분히 길 때만 허용한다
    - 그 외에는 문자열 유사도 SIMILARITY_THRESHOLD 이상일 때만 같은 논문으로 본다
    """
    a, b = _normalize_title(extracted), _normalize_title(fetched)
    if not a or not b:
        return False
    if journal and a == _normalize_title(journal):
        return False
    if _CORRECTION_NOTICE_RE.match(fetched or "") and not _CORRECTION_NOTICE_RE.match(extracted or ""):
        return False                               # 원논문을 가리키는 인용문에 공지를 붙이지 않는다
    for piece in _comparable_pieces(extracted):
        if len(piece) < SUBSTRING_MIN_CHARS or len(piece.split()) < SUBSTRING_MIN_WORDS:
            continue                               # 짧은 조각은 포함만으로 인정하지 않는다
        if piece in b or b in piece:
            return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD


# ---------------------------------------------------------------------------
# 사람이 확정한 제외 목록 + 학술지·연도 대조(기록 전용)
# ---------------------------------------------------------------------------

def load_manual_exclusions():
    """data/input/manual_exclusions.json — 사람이 오귀속으로 확정한 (PMID, 교수) 목록.

    산출물에서 직접 지우면 다음 전체 실행에서 그대로 되살아나므로 설정 파일에 남긴다
    (조립기의 manual_overrides.json과 같은 패턴).
    근거(reason)가 없는 항목은 무시하고 경고한다 — 왜 뺐는지 모르는 제외는 두지 않는다.
    """
    if not MANUAL_EXCLUSIONS_PATH.exists():
        return {}
    with open(MANUAL_EXCLUSIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("exclusions", data)
    table = {}
    for pmid, entry in entries.items():
        if pmid.startswith("_") or not isinstance(entry, dict):
            continue
        if not (entry.get("reason") or "").strip():
            print(f"근거(reason)가 없어 무시합니다: manual_exclusions.json의 PMID {pmid}")
            continue
        names = entry.get("professors")
        if names is None:
            names = [entry["professor"]] if entry.get("professor") else []
        table[str(pmid)] = {"professors": set(names), "reason": entry["reason"]}
    if table:
        print(f"수동 제외 목록: {len(table)}건 (data/input/manual_exclusions.json)")
    return table


def manual_exclusion_reason(exclusions, professor, pmid):
    """이 교수에게서 이 PMID를 빼야 하면 그 근거를, 아니면 None."""
    entry = exclusions.get(str(pmid))
    if entry is None:
        return None
    if entry["professors"] and professor not in entry["professors"]:
        return None                                # 다른 교수에게는 정상일 수 있다
    return entry["reason"]


# --- 학술지명·연도 대조 -------------------------------------------------------
# 채택을 막지 않는다. review.journalMismatch 목록을 만들어 사람이 검수하게 할 뿐이다.
#
# 자동 거부로 쓰지 않는 이유(2026-08-21 시뮬레이션): 현재 수집 1,132편에 적용하면
# 27편이 걸리는데 전건 대조 결과 진짜 오귀속은 10편뿐이고 16편은 정상이었다(정밀도 37%).
# 오탐의 원인은 규칙이 아니라 원본 데이터다 —
#   · 학술지 개명 ("Korean J Lab Med" → "Ann Lab Med")·자매지
#   · 원문 오타 ("Front Nutr"이라 적었지만 doi는 10.3389/fneur = Frontiers in Neurology)
#   · 학술지 자리에 서지 조각이 들어온 파싱 실패 ("Akata", "Hyunjun Lee")
# 이런 걸 규칙으로 가를 수 없어서, 걸러내는 대신 목록으로 남겨 사람이 본다.

# NLM 약어는 기능어를 빼고 만든다 ("Journal of Korean Medical Science" → "J Korean Med Sci").
# 'journal'은 빼지 않는다 — 약어의 'J'와 대응시켜야 하기 때문이다.
_JOURNAL_STOPWORDS = {"of", "the", "and", "for", "in", "on", "a", "an", "de", "der", "und"}
_JOURNAL_TOKEN_SIM = 0.80        # 원문 오타 구제 ("Rresearch"↔"research" 0.94)
YEAR_TOLERANCE = 2               # Epub 선공개·정식출판 차이를 감안한 허용 폭(년)

_MONTH_WORDS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
}


def _journal_tokens(name):
    """학술지명을 대조용 토큰으로 — 붙여 쓴 약어를 떼고, 소문자·알파벳만 남긴다."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name or "")
    text = re.sub(r"[^A-Za-z\s]+", " ", text).lower()
    return [t for t in text.split() if t and t not in _JOURNAL_STOPWORDS]


def _journal_token_match(x, y):
    """토큰 하나끼리 같은 낱말로 볼 수 있는가 — 약어(접두)·철자 차이·오타를 견딘다."""
    if x.startswith(y) or y.startswith(x):                    # med ⊂ medical, j ⊂ journal
        return True
    if len(x) >= 4 and len(y) >= 4 and x[:4] == y[:4]:        # tumor↔tumour, internal↔international
        return True
    return difflib.SequenceMatcher(None, x, y).ratio() >= _JOURNAL_TOKEN_SIM


def _journal_initials_match(a, b):
    """'JCN' ↔ [journal, clinical, neurology] 처럼 머리글자 약어인 경우."""
    for short, long_ in ((a, b), (b, a)):
        if len(short) == 1 and 2 <= len(short[0]) <= 5 and len(long_) >= len(short[0]):
            if short[0] == "".join(t[0] for t in long_[: len(short[0])]):
                return True
    return False


def journals_match(cited, record):
    """인용문 학술지명과 레코드 학술지명이 같은 학술지인가. 근거가 없으면 True(통과)."""
    a, b = _journal_tokens(cited), _journal_tokens(record)
    if not a or not b:
        return True
    if _journal_initials_match(a, b):
        return True
    if len(a) == len(b) and all(_journal_token_match(x, y) for x, y in zip(a, b)):
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    i = 0
    for token in long_:                            # 짧은 쪽이 긴 쪽에 순서대로 들어 있는가
        if i < len(short) and _journal_token_match(token, short[i]):
            i += 1
    return i == len(short)


def is_plausible_journal(name):
    """파서가 뽑은 값이 정말 학술지명인가 — 아니면 대조하지 않는다.

    실제로 "2016 May" "Epub2016Jan8" "Suppl 1" 같은 서지 조각이 학술지 자리에 들어온다.
    이런 값으로 대조하면 무조건 불일치가 되어 멀쩡한 논문이 목록에 오른다.
    """
    if not name:
        return False
    if re.search(r"(?:19|20)\d{2}", name):          # 연도가 들어가면 학술지명이 아니다
        return False
    if re.match(r"^\s*(?:suppl|epub|vol|no|pp|pmid|doi)\b", name, re.I):
        return False
    tokens = _journal_tokens(name)
    if not tokens or all(t in _MONTH_WORDS for t in tokens):
        return False
    return any(len(t) >= 3 for t in tokens)


def citation_year(citation):
    """인용문의 발행연도. 없으면 None.

    parse_citation이 실제로 채택한 꼬리 위치의 연도를 쓴다. '첫 꼬리 신호'나
    '마지막 4자리 숫자'로 잡으면 제목 안의 연도나 쪽번호를 읽는다
    ("…in South Korea in 2007-2021: a nationwide…" → 2021, "Cancers 2021;13(15):2038" → 2038).
    """
    text = re.sub(r"\s+", " ", citation or "").strip()
    if not text:
        return None
    text = _LEADING_MARKER_RE.sub("", _strip_trailing_noise(text)).strip()
    if not text:
        return None
    matches = list(_TAIL_START_RE.finditer(text))
    if not matches:
        return None
    if _parse_reversed(text):                       # 역순 형식은 앞쪽 꼬리가 서지다
        chosen = matches[0]
    else:
        chosen = None
        for m in matches:
            head = text[: m.start()].strip(" .,;:-–")
            if head and _title_from_head(head)[0]:  # 제목이 남는 첫 후보 = 채택된 꼬리
                chosen = m
                break
        if chosen is None:
            return None
    found = re.search(r"(?:19|20)\d{2}", chosen.group(0))
    return int(found.group(0)) if found else None


def journal_mismatch(cited_journal, cited_year, paper):
    """인용문과 레코드의 학술지·연도가 어긋나면 사유를, 아니면 None. (채택을 막지 않는다)"""
    reasons = []
    if is_plausible_journal(cited_journal) and not journals_match(cited_journal, paper.get("journal")):
        reasons.append("학술지 다름")
    if cited_year is not None and paper.get("year"):
        if abs(cited_year - int(paper["year"])) > YEAR_TOLERANCE:
            reasons.append(f"연도 {abs(cited_year - int(paper['year']))}년 차")
    return " · ".join(reasons) if reasons else None


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


def process_professor(name, entries, progress_label, api_key, exclusions=None):
    """교수 1명의 인용문 목록을 논문 수집 결과로 바꾼다.

    반환: (교수 결과, parseFailed, notFound, ambiguous, journalMismatch,
           manualExcluded, koreanTitleSkipped)
    - 검색 실패 항목은 {"title": ...} 모양이고, 재시도까지 실패한 통신 오류로 포기한
      항목에는 "reason": "HTTP 오류"가 붙는다 (사람이 구분해 검수할 수 있게).
    - 모호 항목은 후보 여러 편이 제목 대조를 통과한 경우다. 어느 쪽인지 지목할 수 없으므로
      넣지 않고 review.ambiguous에 남겨 사람이 검수한다 (원칙 2: 불확실하면 넣지 않는다).
    - efetch·OpenAlex가 재시도 후에도 실패하면 FetchFailedError를 던진다 —
      main()이 fetchFailed로 기록하고 다음 교수로 넘어간다.

    흐름이 예전과 다른 점: 검색 단계에서 채택하지 않고 후보만 모은다. 후보 전부를
    efetch로 받아 실제 제목과 대조한 뒤에 고른다 — 검색 순위(relevance 1위)에
    결과가 좌우되지 않게 하기 위해서다.
    """
    parse_failed = []      # 제목 추출 실패 인용문
    not_found = []         # 검색 실패(0건·제목 불일치·통신 오류) 항목
    ambiguous = []         # 통과 후보가 둘 이상이라 지목 불가
    mismatched = []        # 학술지·연도가 어긋나 사람이 봐야 할 항목 (채택은 막지 않는다)
    excluded = []          # 사람이 확정한 오귀속이라 빼 버린 항목
    korean_skipped = []    # 한글 제목이라 PubMed 검색을 건너뛴 항목 (KCI 수집 대상)
    exclusions = exclusions if exclusions is not None else {}
    sources = []           # [{"title", "journal", "pmids"}] — 입력 순서 유지

    for entry in entries:
        citation = entry[0] if entry else ""
        title, journal = parse_citation(citation)
        if title is None:
            parse_failed.append(citation)
            continue
        if is_korean_title(title):
            # 한글 제목은 PubMed 대상이 아니다 — 섞인 영문 낱말만 걸려 남의 논문이 붙는다.
            # notFound가 아니라 별도 목록에 남긴다 (검색을 시도조차 하지 않았으므로).
            print(f"한글 제목 → PubMed 검색 건너뜀, KCI 수집 대상: {title[:55]}")
            korean_skipped.append({"title": title,
                                   "hangulRatio": round(hangul_ratio(title), 2)})
            continue
        try:
            pmids = search_pmid_candidates(title)
        except requests.exceptions.RequestException as exc:
            # 재시도까지 실패한 통신 오류 — 이 논문만 포기하고 다음 인용문으로 계속한다
            print(f"제목 검색 통신 실패({_describe_error(exc)}) → notFound(HTTP 오류) 기록 후 계속")
            not_found.append({"title": title, "reason": "HTTP 오류"})
            continue
        if not pmids:
            not_found.append({"title": title})
            continue
        sources.append({"title": title, "journal": journal, "pmids": pmids,
                        "year": citation_year(citation)})

    searched = len(entries) - len(parse_failed) - len(korean_skipped)
    candidate_pmids = list(dict.fromkeys(p for s in sources for p in s["pmids"]))
    print(f"{progress_label} {name}: 인용문 {len(entries)}건 → 후보 PMID {len(candidate_pmids)}건")

    # efetch 상세 수집 — 1단계 부품 재사용. 후보가 늘었으므로 EFETCH_BATCH개씩 나눠 부른다
    # (한 번에 쉼표로 묶으면 URL이 너무 길어진다).
    # 재시도까지 실패하면 이 교수 전체를 fetchFailed로 넘긴다 (저장 안 함 → 재실행 때 자동 재시도).
    fetched = []
    try:
        for start in range(0, len(candidate_pmids), EFETCH_BATCH):
            chunk = candidate_pmids[start:start + EFETCH_BATCH]
            fetched.extend(
                call_with_retry("PubMed 상세 수집(efetch)", lambda c=chunk: fetch_one.fetch_papers(c))
            )
    except requests.exceptions.RequestException as exc:
        raise FetchFailedError("efetch", _describe_error(exc))
    by_pmid = {p["pmid"]: p for p in fetched}

    # 제목 대조로 채택 — 인용문 하나당 통과 후보가 정확히 1편일 때만 넣는다.
    # 0편이면 notFound, 2편 이상이면 ambiguous (불확실하면 넣지 않는다 — 원칙 2)
    chosen = {}            # PMID → 인용문 제목 (입력 순서 유지 + 중복 제거)
    for source in sources:
        hits = [
            pmid for pmid in source["pmids"]
            if pmid in by_pmid and titles_match(source["title"], by_pmid[pmid]["title"], source["journal"])
        ]
        if len(hits) == 1:
            reason = manual_exclusion_reason(exclusions, name, hits[0])
            if reason:
                # 사람이 오귀속으로 확정한 논문 — 조용히 빼지 않고 근거와 함께 남긴다
                print(f"수동 제외: PMID {hits[0]} — {reason[:60]}")
                excluded.append({"pmid": hits[0], "title": by_pmid[hits[0]]["title"],
                                 "citedTitle": source["title"], "reason": reason})
                continue
            chosen.setdefault(hits[0], source["title"])
            mismatch = journal_mismatch(source["journal"], source["year"], by_pmid[hits[0]])
            if mismatch:
                mismatched.append({
                    "pmid": hits[0], "why": mismatch,
                    "citedTitle": source["title"], "citedJournal": source["journal"],
                    "citedYear": source["year"],
                    "recordTitle": by_pmid[hits[0]]["title"],
                    "recordJournal": by_pmid[hits[0]].get("journal"),
                    "recordYear": by_pmid[hits[0]].get("year"),
                })
        elif not hits:
            print(f"제목 대조 통과 후보 없음 → notFound: {source['title'][:70]}")
            not_found.append({"title": source["title"]})
        else:
            print(f"통과 후보 {len(hits)}편 → ambiguous: {source['title'][:70]}")
            ambiguous.append({
                "title": source["title"],
                "candidates": [{"pmid": p, "title": by_pmid[p]["title"]} for p in hits],
            })
    papers = [by_pmid[pmid] for pmid in chosen]

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
            "ambiguous": len(ambiguous),  # 통과 후보가 둘 이상이라 넣지 않은 수
            "excluded": len(excluded),    # 사람이 확정한 오귀속이라 뺀 수
            "koreanSkipped": len(korean_skipped),  # 한글 제목이라 검색하지 않은 수
        },
    }
    return record, parse_failed, not_found, ambiguous, mismatched, excluded, korean_skipped


def load_state():
    """저장된 산출물을 읽어 이어서 진행할 준비를 한다. 없거나 FORCE_REFRESH면 새로 시작."""
    if not FORCE_REFRESH and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("professors", {})
        state.setdefault("review", {})
        for key in ("noPapers", "parseFailed", "notFound", "ambiguous",
                    "journalMismatch", "manualExcluded", "koreanTitleSkipped",
                    "fetchFailed"):
            state["review"].setdefault(key, [])   # 이전 버전 산출물에 없던 목록도 채워 준다
        print(f"기존 산출물 발견: 교수 {len(state['professors'])}명 완료됨 → 이어서 진행 (resume)")
        return state
    return {
        "collectedAt": None,
        "professors": {},
        "review": {
            "noPapers": [], "parseFailed": [], "notFound": [], "ambiguous": [],
            "journalMismatch": [], "manualExcluded": [], "koreanTitleSkipped": [],
            "fetchFailed": []
        },
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
        f" / notFound {len(review['notFound'])} / ambiguous {len(review['ambiguous'])}"
        f" / journalMismatch {len(review['journalMismatch'])}"
        f" / manualExcluded {len(review['manualExcluded'])}"
        f" / koreanTitleSkipped {len(review['koreanTitleSkipped'])}"
        f" / fetchFailed {len(review['fetchFailed'])}"
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
    exclusions = load_manual_exclusions()

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
            (record, parse_failed, not_found, ambiguous, mismatched,
             excluded, korean_skipped) = process_professor(
                name, entries, f"[{position}/{total_with_papers}]", api_key, exclusions
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
        for item in ambiguous:
            state["review"]["ambiguous"].append({"professor": name, **item})
        for item in mismatched:
            state["review"]["journalMismatch"].append({"professor": name, **item})
        for item in excluded:
            state["review"]["manualExcluded"].append({"professor": name, **item})
        for item in korean_skipped:
            state["review"]["koreanTitleSkipped"].append({"professor": name, **item})
        save_state(state)  # 교수 1명 끝날 때마다 즉시 저장 — 끊겨도 여기까지 보존

        run_professors += 1
        run_searched += record["stats"]["cited"]
        print(
            f"  → 수집 {record['stats']['collected']}편 · 대표 {len(record['papers'])}편"
            f" · notFound {record['stats']['notFound']} · ambiguous {len(ambiguous)}"
            f" · parseFailed {len(parse_failed)} · 제외 {len(excluded)}"
            f" · 한글건너뜀 {len(korean_skipped)}"
        )

    print_summary(state, time.monotonic() - started, run_professors, run_searched)


if __name__ == "__main__":
    main()
