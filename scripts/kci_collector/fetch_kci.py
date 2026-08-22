"""KCI(한국학술지인용색인) 국내 학술지 논문 수집기.

흐름: 대상 교수 명단(professors.json) 읽기
      → 교수 이름으로 KCI 검색(apiCode=articleSearch, author=한글이름) · 페이지 순회
      → 응답 XML 파싱(kciId·제목·저자·소속·ORCID·피인용수·초록)
      → **본인 논문 판별**: 같은 이름 저자의 소속에 "전북대"가 있을 때만 채택
      → PubMed 산출물(professors_papers.json)과 대조해 중복 여부만 표시(duplicateOf)
      → 교수 1명이 끝날 때마다 data/output/kci_papers.json에 즉시 저장 (재개 가능)

산출물의 키는 **교수 id**(professors.json의 P-012)이고, 레코드 안에 name을 함께 둔다.
이름을 키로 쓰면 동명이인이 한 칸에 뭉개지기 때문이다. 그리고 대상 명단에 같은 이름의 교수가
둘 이상이면(예: 이창훈 P-176/P-177) **검색 결과를 어느 쪽에도 배정하지 않는다** —
KCI 검색은 이름 기준이라 두 사람을 가를 근거가 없다. 후보 논문은 저자 ORCID·소속과 함께
review.homonymUnassigned에 남겨 사람이 확인해 배정하게 한다 (근거 없으면 채우지 않는다).

이 단계는 **KCI 산출물 생성까지**다. 병합(하나의 논문으로 합치기)은 조립 단계에서 한다 —
여기서는 "이 KCI 논문은 저 pmid와 같은 논문으로 보인다"는 판별 정보만 남긴다.

안정성: 5xx·네트워크 예외·XML 파싱 실패·**해석할 수 없는 응답**은 5초 → 15초 간격으로
최대 3회 시도한다. 그래도 실패하면 그 교수만 review.fetchFailed에 기록하고 다음 교수로 계속한다.
fetchFailed 교수는 **레코드를 저장하지 않으므로**(빈 papers를 남기지 않는다) 이전 실행의
결과가 그대로 남고, 재실행하면 자동으로 다시 시도된다.

fail-closed 원칙: '논문 0건'으로 저장하려면 근거가 있어야 한다 — KCI가 "No Data"라고
답했거나 <total>0</total>이 왔을 때뿐이다. 근거 없이 비어 있는 응답(점검 페이지·프록시 오류·
형식 변경)은 0건이 아니라 오류로 다룬다. 이 구분이 없으면 API 장애 한 번에 교수 전원의
수집 결과가 조용히 빈 값으로 덮인다.

데이터 계약 v6.4:
- 원칙 1: 논문에는 pmid 또는 kciId가 필수 — kciId가 없는 응답 항목은 버린다.
- 원칙 2: 없는 값은 지어내지 않고 null. 소속이 확인되지 않은 논문은 채택하지 않고
  review.affiliationUnmatched에 남긴다. 중복 판별이 애매하면 합치지 않고
  review.duplicateAmbiguous에 남긴다.
- 원칙 4: 수집 기준일(collectedAt)을 담고, 제목·학술지·연도는 KCI 원본 그대로 둔다.
- 1-2 중복 처리: ① DOI 일치 → ② (DOI 없으면) 정규화 제목 + 연도 일치 → ③ 애매하면 별개.

2026-08-18 실제 응답으로 검증했다. 실측에서 예상과 달랐던 두 가지가 코드에 반영돼 있다:
- **오류에도 HTTP 200이 오고 error 태그가 없다.** 결과 0건("No Data")과 인증키 오류가
  똑같이 result/resultMsg로 오므로, 문구로 갈라 낸다 (parse_response 참고).
  이걸 틀리면 키 오류가 '논문 0건'으로 삼켜져 전원이 빈 결과로 저장된다.
- 저자 소속이 **영문으로만 오는 논문이 있다** → AFFILIATION_KEYWORDS에 영문 표기를 넣었다.
파싱은 태그 위치를 고정하지 않고 이름으로 자손을 찾는 방식(_iter_by_tag)이라 중첩 구조가
바뀌어도 견디지만, 태그 '이름' 자체가 바뀌면 값이 null로 빈다.
응답 구조는 scripts/README.md 4장 '실제 응답 구조(실측)' 참고.
"""

import difflib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

import requests

# ===== 실행 옵션 (실행 전 이 부분만 수정하면 됩니다) ============================
FORCE_REFRESH = False        # True면 저장된 결과를 무시하고 전부 다시 수집
LIMIT = None                 # 개발·검증용: 대상 명단 앞 N명만 처리 (None이면 전체)
# run_all.py --limit N 스모크 테스트용 — 환경변수가 있으면 위 LIMIT보다 우선한다
import os as _os
if _os.environ.get("PIPELINE_LIMIT"):
    LIMIT = int(_os.environ["PIPELINE_LIMIT"])

USE_AFFILIATION_PARAM = False  # True면 검색에 affiliation 파라미터도 함께 보낸다 (아래 설명)
# ==============================================================================

# affiliation 파라미터: 이름만으로 검색하면 동명이인의 논문까지 걸려 오므로 소속을 함께 주면
# 결과가 줄어든다. 다만 파라미터 이름·표기 규칙("전북대학교" vs "전북대")을 실제 응답으로
# 확인하지 못했고, 소속 표기가 다르면 본인 논문까지 사라질 수 있어 기본값은 끔이다.
# (본인 판별은 어차피 응답 안의 저자 소속으로 하므로, 켜지 않아도 오귀속은 생기지 않는다)
AFFILIATION_QUERY = "전북대학교"

API_URL = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
API_CODE = "articleSearch"   # 논문 검색

DISPLAY_COUNT = 100          # 한 번에 받을 건수 (KCI 최대값)
MAX_PAGES = 20               # 안전장치: 한 교수당 최대 2,000건까지만 순회한다

# API 예절: 호출 사이 0.5초 (지시서 2-5)
SLEEP_SECONDS = 0.5

# 재시도 정책 — 일시적 서버 오류(5xx)·네트워크 예외로 배치 전체가 죽지 않게 한다.
# 4xx는 요청 자체가 잘못된 것이라 다시 보내도 같은 결과 → 재시도 없음.
RETRY_ATTEMPTS = 3
RETRY_WAITS = [5, 15]        # 시도 사이 대기(초): 1→2회차 5초, 2→3회차 15초

# 산출물 저장(파일 교체) 재시도 — 윈도우에서 다른 프로그램이 파일을 열고 있을 때를 대비
SAVE_ATTEMPTS = 5
SAVE_RETRY_WAIT = 0.5

# 본인 논문 판정 키워드 — 저자 소속에 이 문자열이 들어 있어야 채택한다 (지시서 2-3-c).
# 비교는 소문자로 하므로 영문 키워드는 소문자로 적는다.
#
# 2026-08-18 실측: 소속은 대부분 한글("전북대학교", "전북대학교병원", "전북대학교 의과대학
# 내과학교실")이지만 영문으로만 오는 논문이 실제로 있었다
# (예: "Center for Clinical Pharmacology, Jeonbuk National University Hospital, Jeonju").
# 한글 키워드만 두면 이런 논문이 '타 기관'으로 빠지므로 영문 표기를 함께 넣는다.
# "jeonbuk"만 넣지 않는 이유: 전북대와 무관한 지역 기관(전북 소재 연구원 등)까지 걸린다.
AFFILIATION_KEYWORDS = (
    "전북대",                    # 전북대학교 · 전북대학교병원 · 전북대학병원 · 전북대학교 의과대학
    "전북의대",                  # 의학 논문에서 흔한 약칭 (전북의대 내과학 / 전북의대 산부인과 …)
    "전북의학전문대학원",         # 의전원 시기 표기
    "jeonbuk national univ",    # Jeonbuk National University / University Hospital / Univ.
    "chonbuk national univ",    # 옛 로마자 표기 (2020년 이전 논문)
    # ↓ KCI가 긴 영문 소속을 150자에서 잘라 "…of Jeonbuk"으로 끝나는 경우가 있다.
    #   전북대학교병원 임상의학연구소의 정식 영문명이라 다른 기관과 헷갈리지 않는다.
    "research institute of clinical medicine of jeonbuk",
)

# 제목이 완전히 같지는 않지만 이만큼 닮았고 연도도 같으면 "애매"로 분류해 사람에게 넘긴다.
DUPLICATE_SIMILARITY = 0.85
# 너무 짧은 제목은 우연히 닮을 수 있어 유사도 비교에서 뺀다.
MIN_TITLE_CHARS_FOR_SIMILARITY = 12

# 검수 목록(review)의 칸. 모든 기록에는 professor(이름)가 들어 있어 이름으로 지우고 다시 쓴다.
REVIEW_KEYS = (
    "affiliationUnmatched",   # 소속이 전북대로 확인되지 않아 채택하지 않은 논문
    "homonymUnassigned",      # 대상 명단에 같은 이름이 여럿 — 배정을 보류한 후보 논문
    "duplicateAmbiguous",     # PubMed 논문과 같은 것인지 확정하지 못한 논문
    "fetchFailed",            # 통신 실패로 건너뛴 교수 (재실행 시 자동 재시도)
    "noResult",               # 검색 결과가 0건인 교수
)

# 입출력 위치: (저장소 루트)/… — 어느 폴더에서 실행해도 같은 곳을 읽고 쓴다
ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
TARGET_PATH = ROOT / "data" / "output" / "professors.json"          # 대상 교수 명단(계약 0-2)
PUBMED_PATH = ROOT / "data" / "output" / "professors_papers.json"   # 3단계 산출물(중복 판별용)
OUTPUT_PATH = ROOT / "data" / "output" / "kci_papers.json"


# ---------------------------------------------------------------------------
# 인증키
# ---------------------------------------------------------------------------

def read_kci_api_key(env_path=ENV_PATH):
    """KCI_API_KEY를 읽는다 — 환경변수가 먼저, 없으면 루트 .env (외부 라이브러리 없이).

    키를 공개 저장소에 커밋하지 않으려고 코드가 아니라 .env에서 읽는다
    (.env는 .gitignore 대상, 양식은 루트 .env.example).
    2단계 enrich_citations.read_openalex_api_key와 같은 방식이다 — 다만 기존 스크립트를
    수정하지 않기 위해(지시서 4장) import 대신 같은 모양의 파서를 여기에 둔다.

    환경변수를 먼저 보는 이유: scripts/run_all.py가 `--env-file`로 지정한 .env를 파싱해
    하위 단계 프로세스의 환경변수로 넘긴다. 이렇게 해야 지정한 파일이 실제로 적용된다.
    이 스크립트를 단독으로 실행할 때는 환경변수가 없으므로 지금까지처럼 루트 .env를 읽는다.
    """
    api_key = os.environ.get("KCI_API_KEY", "").strip()
    if not api_key and env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "KCI_API_KEY":
                api_key = value.strip().strip('"').strip("'")
    if not api_key:
        raise SystemExit(
            "KCI_API_KEY를 찾지 못했습니다.\n"
            "KCI Open API는 신청·승인 후 발급되는 인증키가 있어야 호출할 수 있습니다.\n"
            "발급 방법: open.kci.go.kr → Open API 신청(활용 목적·서비스 IP 기재) → 승인 후 인증키 확인\n"
            "→ 환경변수 KCI_API_KEY로 넘기거나, 저장소 루트의 .env 파일에 아래 한 줄을 추가해 주세요"
            " (양식: .env.example).\n"
            "  KCI_API_KEY=발급받은키\n"
            "주의: 인증키는 신청 시 등록한 IP에서만 동작합니다 (계약 v6.4 7장 — 고정 IP 수집 서버).\n"
            "(.env는 .gitignore에 등록되어 있어 커밋되지 않습니다)"
        )
    return api_key


# ---------------------------------------------------------------------------
# XML 파싱
#
# KCI 응답의 중첩 구조(MetaData > outputData > record > articleInfo …)를 코드에 고정하지
# 않고, '태그 이름'으로 자손을 찾는다. 가이드와 실제 응답의 계층이 조금 달라도 값을 집기
# 위해서다. 대신 이름이 다르면 못 찾으므로, 못 찾은 값은 지어내지 않고 null로 둔다(원칙 2).
# ---------------------------------------------------------------------------

# lang 속성 표기가 문서마다 다를 수 있어 별칭을 함께 본다.
# 원어(original)에는 lang 속성이 아예 없는 경우("")도 포함한다.
_LANG_ALIASES = {
    "original": {"original", "korean", "ko", "kor", "kr", ""},
    "english": {"english", "en", "eng"},
}

# "황주희(전북대학교 의과대학)" 처럼 이름 뒤 괄호에 들어 있는 소속
_AFFILIATION_IN_PARENS = re.compile(r"[（(]\s*([^()（）]*?)\s*[)）]\s*$")


def _clean(text):
    """공백을 정리하고 빈 문자열은 None으로 — 빈칸을 값으로 남기지 않는다 (원칙 2)."""
    if text is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    return cleaned or None


def _local(tag):
    """네임스페이스가 붙은 태그({ns}article-title)에서 이름만 떼어 낸다."""
    return str(tag).rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _iter_by_tag(elem, *tags):
    """자손(자기 자신 포함) 중 이름이 tags에 해당하는 요소를 모두 돌려준다 — 깊이 무관."""
    wanted = {t.lower() for t in tags}
    for node in elem.iter():
        if _local(node.tag) in wanted:
            yield node


def _first_text(elem, *tags):
    """tags에 해당하는 첫 요소의 텍스트 (없으면 None)."""
    for node in _iter_by_tag(elem, *tags):
        text = _clean(node.text)
        if text:
            return text
    return None


def _text_by_lang(elem, tag, lang):
    """lang 속성으로 원어/영문을 골라 텍스트를 가져온다 (예: article-title lang=english)."""
    aliases = _LANG_ALIASES[lang]
    for node in _iter_by_tag(elem, tag):
        node_lang = (node.get("lang") or "").strip().lower()
        if node_lang in aliases:
            text = _clean(node.text)
            if text:
                return text
    return None


def _attr(node, *names):
    """속성 이름 표기 차이(orc-id / orcid / orcId)를 흡수해 첫 값을 돌려준다."""
    for name in names:
        for key, value in node.attrib.items():
            if _local(key).replace("_", "-") == name.lower():
                cleaned = _clean(value)
                if cleaned:
                    return cleaned
    return None


def _to_year(value):
    """'2021' · '2021-03' 같은 표기에서 4자리 연도만 int로 뽑는다. 없으면 None."""
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def parse_author(node):
    """저자 요소 하나를 {name, affiliation, nameEn, orcid}로 바꾼다.

    소속은 ① 이름 뒤 괄호("황주희(전북대학교)") ② affiliation/institution 속성
    ③ 하위 요소 순으로 찾는다. 셋 다 없으면 None — 소속 불명이므로 채택되지 않는다.
    """
    raw = _clean(node.text) or ""
    name, affiliation = raw, None

    match = _AFFILIATION_IN_PARENS.search(raw)
    if match:
        name = _clean(raw[: match.start()]) or ""
        affiliation = _clean(match.group(1))

    if not affiliation:
        affiliation = _attr(node, "affiliation", "institution", "inst-name")
    if not affiliation:
        for child in node:
            if _local(child.tag) in {"affiliation", "institution", "inst-name", "org-name"}:
                affiliation = _clean(child.text)
                if affiliation:
                    break

    return {
        "name": name,
        "affiliation": affiliation,
        "nameEn": _attr(node, "english", "name-english", "author-english"),
        "orcid": _attr(node, "orc-id", "orcid"),
    }


def parse_article(record):
    """record(또는 articleInfo) 요소 하나를 논문 dict로 바꾼다. kciId가 없으면 None.

    kciId가 없는 항목을 버리는 이유: 계약 원칙 1(pmid 또는 kciId 필수) — 식별자 없는
    논문은 어차피 응답에 넣을 수 없고, 링크도 만들 수 없다.
    """
    article_info = next(_iter_by_tag(record, "articleinfo"), record)
    kci_id = _attr(article_info, "article-id", "articleid")
    if not kci_id:
        # 속성이 아니라 요소로 오는 형태(<article-id>ART…</article-id>)도 받아 준다
        kci_id = _first_text(record, "article-id")
    if not kci_id:
        return None

    authors = [parse_author(node) for node in _iter_by_tag(record, "author")]

    # 피인용수: <citation-count kci="4"/>(속성)와 <citation-count>4</citation-count>(텍스트)
    # 두 형태를 모두 받는다. 없으면 0으로 채우지 않고 None (원칙 2 — 0회와 미상은 다르다).
    cited = None
    for node in _iter_by_tag(record, "citation-count", "citationcount"):
        cited = _attr(node, "kci") or _clean(node.text)
        if cited:
            break
    cited_count = int(cited) if cited and str(cited).isdigit() else None

    return {
        "kciId": kci_id,
        "title": _text_by_lang(record, "article-title", "original"),
        "titleEn": _text_by_lang(record, "article-title", "english"),
        "journal": (
            _text_by_lang(record, "journal-name", "original")
            or _first_text(record, "journal-name")
        ),
        "year": _to_year(_first_text(record, "pub-year", "pub-date", "year")),
        "doi": _first_text(record, "doi"),
        "url": _first_text(record, "url"),
        "citedByCountKci": cited_count,
        "abstract": _text_by_lang(record, "abstract", "original"),
        "abstractEn": _text_by_lang(record, "abstract", "english"),
        "authors": authors,
    }


class KciApiError(Exception):
    """KCI가 오류 응답(인증키 오류 등)을 돌려줬다는 신호 — 재시도해도 같은 결과다.

    모든 교수에서 똑같이 나는 종류라 main()이 즉시 멈춘다.
    """


class KciUnexpectedResponseError(Exception):
    """응답을 해석할 수 없다 — 논문도 없고, 0건이라는 근거도 없다.

    KciApiError와 나누는 이유: 이쪽은 **일시적일 수 있다**(점검 페이지·프록시 오류·형식 변경).
    그래서 재시도 경로를 그대로 타고, 끝까지 실패하면 그 교수만 fetchFailed로 남기고
    다음 교수로 넘어간다. 절대 '논문 0건'으로 취급하지 않는다 — 그러면 조용히 전원의
    수집 결과가 빈 값으로 덮여 버린다.
    """


# 결과 0건일 때 KCI가 보내는 안내 문구. 오류가 아니라 정상이다.
# 2026-08-18 실측: <result><resultMsg>No Data</resultMsg></result>
_NO_DATA_PATTERN = re.compile(r"no\s*data|no\s*result|데이터[가]?\s*없", re.I)

# 로그에 남길 응답 원문 길이 (원인 파악용)
_SNIPPET_CHARS = 200

# 응답 안의 인증키를 가린다 — KCI는 요청을 그대로 되돌려 주므로 <key>에 키가 들어 있고,
# 중간 프록시의 오류 페이지에는 요청 URL(?key=…)이 그대로 찍히기도 한다.
_SECRET_PATTERNS = (
    (re.compile(r"(<key>)[^<]*(</key>)", re.I), r"\1***\2"),
    (re.compile(r"([?&]key=)[^&\s\"'<]+", re.I), r"\1***"),
)


def _mask_secrets(text):
    """로그로 나갈 문자열에서 인증키를 가린다."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _snippet(xml_bytes):
    """응답 원문 앞부분을 로그용 한 줄로 만든다 (인증키 마스킹 필수)."""
    text = xml_bytes.decode("utf-8", errors="replace") if isinstance(xml_bytes, bytes) else str(xml_bytes)
    text = re.sub(r"\s+", " ", _mask_secrets(text)).strip()
    return text[:_SNIPPET_CHARS] + ("…" if len(text) > _SNIPPET_CHARS else "")


def parse_response(xml_bytes):
    """응답 XML을 (논문 목록, 전체 건수)로 바꾼다. 전체 건수를 못 찾으면 None.

    - ET.fromstring은 XML 선언의 인코딩을 따르므로 bytes를 그대로 넘긴다.
    - 오류면 예외를 던진다. 결과 0건과 오류를 구분하기 위해서다 —
      0건은 정상이고, 오류는 사람이 손봐야 한다.

    2026-08-18 실측 — **오류에도 HTTP 200이 오고, error 태그는 없다.**
    결과도 오류도 모두 <result><resultMsg>…</resultMsg></result> 한 칸으로 온다:
      · 결과 0건    → "No Data"
      · 인증키 오류 → "등록되지 않은 key 입니다."
      · 잘못된 코드 → "등록되지 않은 서비스"
    그래서 resultMsg가 'No Data' 계열이면 빈 결과로, 그 밖의 문구면 오류로 본다.

    **빈 결과로 인정하려면 근거가 있어야 한다 (fail-closed).**
    논문도 없고 'No Data'도 <total>0</total>도 없는 응답은 우리가 해석할 수 없는 것이므로
    0건이 아니라 KciUnexpectedResponseError로 처리한다. 점검 페이지·프록시 오류 페이지·
    응답 형식 변경이 '논문 0건'으로 둔갑하면, 그 한 번의 실행으로 교수 전원의 수집 결과가
    조용히 빈 값으로 덮여 버린다. 해석할 수 없으면 멈추는 쪽이 안전하다.
    """
    root = ET.fromstring(xml_bytes)  # 깨진 XML이면 ParseError → 호출한 쪽이 재시도

    # 논문 1편의 경계를 정한다. 기본은 <record>(학술지 정보 + 논문 정보를 함께 감싼 단위)다.
    records = list(_iter_by_tag(root, "record"))
    article_infos = list(_iter_by_tag(root, "articleinfo"))
    if not records:
        records = article_infos
    elif len(article_infos) > len(records):
        # record 하나에 논문이 여럿 들어 있는 구조 — record 단위로 읽으면 첫 편만 남고
        # 나머지가 조용히 사라진다. 논문 단위로 쪼개되, 바깥에 있는 학술지명·발행연도는
        # 못 붙을 수 있으므로(그 값은 null이 된다) 사람이 알 수 있게 알린다.
        print(f"  ! 응답 구조 주의: record {len(records)}개 안에 논문 {len(article_infos)}편"
              " — 논문 단위로 파싱합니다 (학술지·연도가 비면 scripts/README.md 4장 참고)")
        records = article_infos

    if not records:
        # 항목이 하나도 없다 — article-id 속성을 가진 요소가 있으면 그것을 논문으로 본다
        # (컨테이너 태그 이름이 가이드와 다른 경우 대비)
        records = [node for node in root.iter() if _attr(node, "article-id", "articleid")]

    # 전체 건수(있으면 마지막 쪽 판단에 쓴다). 태그 이름을 못 찾으면 None —
    # 그때는 '받은 건수 < displayCount'로 마지막 쪽을 판단한다.
    total = None
    for node in _iter_by_tag(root, "total", "totalcount", "total-count"):
        digits = _clean(node.text)
        if digits and digits.isdigit():
            total = int(digits)
            break

    if not records:
        # 결과가 없다 — '정상적인 0건'이라는 근거를 찾는다. 없으면 오류다 (fail-closed)
        for node in _iter_by_tag(root, "resultmsg", "errormsg", "errmsg", "error"):
            message = _clean(node.text)
            if not message:
                continue
            if _NO_DATA_PATTERN.search(message):
                return [], total     # 근거 ①: "No Data" 안내 문구
            # 아는 오류든 모르는 문구든 0건으로 삼키지 않는다
            raise KciApiError(message)

        if total == 0:
            return [], total         # 근거 ②: <total>0</total>

        # 근거가 없다 — 논문도 없고 0건이라는 표시도 없다. 우리가 해석할 수 없는 응답이다.
        raise KciUnexpectedResponseError(
            f"논문도 0건 안내도 없는 응답 (최상위 태그 <{_local(root.tag)}>): {_snippet(xml_bytes)}"
        )

    articles = [a for a in (parse_article(r) for r in records) if a]

    if records and not articles:
        # record는 있는데 하나도 논문으로 못 만들었다 = 전부 article-id가 없다.
        # 형식이 바뀐 신호이므로 조용히 0건으로 두지 않는다 (kciId 없는 논문은 계약상 못 쓴다).
        raise KciUnexpectedResponseError(
            f"record {len(records)}개가 모두 article-id 없음: {_snippet(xml_bytes)}"
        )

    return articles, total


# ---------------------------------------------------------------------------
# 호출 (재시도 포함)
# ---------------------------------------------------------------------------

def _describe_error(exc):
    """예외를 기록용 한 줄로 요약한다 (HTTP 응답이 있으면 상태 코드, 없으면 예외 이름).

    해석 불가 응답은 이름만 남기면 원인을 알 수 없으므로 사유(마스킹된 원문 포함)를 함께 남긴다.
    """
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    if isinstance(exc, KciUnexpectedResponseError):
        return f"해석 불가 응답 — {exc}"
    return type(exc).__name__


# 다시 시도해 볼 만한 실패 — 일시적일 수 있는 것들만 넣는다
RETRYABLE_ERRORS = (
    requests.exceptions.RequestException,   # 5xx·타임아웃·연결 끊김
    ET.ParseError,                          # 응답이 중간에 잘려 XML이 깨진 경우
    KciUnexpectedResponseError,             # 점검 페이지 등 해석할 수 없는 응답
)


def call_with_retry(description, func):
    """외부 API 호출 1건을 재시도로 감싼다. func는 인자 없는 함수(lambda)로 받는다.

    - 5xx·네트워크 예외·XML 파싱 실패·해석 불가 응답: 5초 → 15초 쉬며 최대 3회 시도
      (파싱 실패를 재시도에 넣는 이유: 응답이 중간에 잘리면 XML이 깨져 들어온다)
    - 4xx: 요청 자체의 문제라 다시 보내도 같은 결과 — 즉시 실패
    - KciApiError(인증키 오류 등)도 재시도하지 않는다 — 기다린다고 풀리지 않는다
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return func()
        except RETRYABLE_ERRORS as exc:
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


def fetch_page(api_key, name, page):
    """검색 1쪽을 가져온다 — (논문 목록, 전체 건수)."""
    params = {
        "apiCode": API_CODE,
        "key": api_key,
        "author": name,
        "displayCount": DISPLAY_COUNT,
        "page": page,
    }
    if USE_AFFILIATION_PARAM:
        params["affiliation"] = AFFILIATION_QUERY
    response = requests.get(API_URL, params=params, timeout=30)
    response.raise_for_status()
    return parse_response(response.content)


def fetch_articles(api_key, name):
    """교수 1명의 검색 결과를 페이지 순회로 전부 모은다 (kciId 기준 중복 제거)."""
    articles, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        time.sleep(SLEEP_SECONDS)  # API 예절
        page_articles, total = call_with_retry(
            f"KCI 검색({name} {page}쪽)", lambda: fetch_page(api_key, name, page)
        )
        for article in page_articles:
            if article["kciId"] in seen:  # 쪽 경계에서 같은 논문이 두 번 오는 경우 대비
                continue
            seen.add(article["kciId"])
            articles.append(article)

        if len(page_articles) < DISPLAY_COUNT:   # 마지막 쪽
            break
        if total is not None and len(articles) >= total:
            break
    else:
        # MAX_PAGES를 다 쓰고도 끝이 아닌 경우 — 조용히 자르지 않고 알린다
        print(f"  ! {name}: {MAX_PAGES}쪽({MAX_PAGES * DISPLAY_COUNT}건)까지만 수집했습니다 — 확인 필요")
    return articles


# ---------------------------------------------------------------------------
# 본인 논문 판별
#
# 이름만으로 검색하면 동명이인·타 기관 저자의 논문이 섞여 온다. PubMed 수집에서
# 오귀속을 막았던 기준과 같게, "같은 이름 저자의 소속에 전북대가 있을 때만" 채택한다.
# 소속이 비었거나 다른 기관이면 지어내지 않고 review로 넘긴다 (원칙 2).
# ---------------------------------------------------------------------------

def normalize_name(text):
    """이름 비교용 — 공백을 없앤다 ('황 주희' ↔ '황주희')."""
    return re.sub(r"\s+", "", text or "")


def is_jbnu(affiliation):
    """소속 문자열이 전북대 계열인지 (AFFILIATION_KEYWORDS 중 하나라도 포함하면 참).

    영문 표기가 대소문자 섞여 오므로 소문자로 맞춰 비교한다 (한글은 영향 없음).
    """
    if not affiliation:
        return False
    text = affiliation.lower()
    return any(keyword in text for keyword in AFFILIATION_KEYWORDS)


def match_self_author(article, name):
    """논문의 저자 중 '이 교수 본인'을 찾는다 — (저자 dict 또는 None, 사유).

    사유는 review 기록용이다:
    - "동명 저자 없음": 검색어와 같은 이름의 저자가 응답 안에 없다 (검색 방식 확인 필요)
    - "소속 정보 없음": 이름은 같은데 소속이 비어 있다 → 본인인지 알 수 없다
    - "타 기관": 이름은 같은데 소속이 전북대가 아니다 → 동명이인으로 본다
    """
    target = normalize_name(name)
    same_name = [a for a in article["authors"] if normalize_name(a["name"]) == target]
    if not same_name:
        return None, "동명 저자 없음"

    for author in same_name:
        if is_jbnu(author["affiliation"]):
            return author, None

    if all(not a["affiliation"] for a in same_name):
        return None, "소속 정보 없음"
    return None, "타 기관"


# ---------------------------------------------------------------------------
# PubMed 논문과의 중복 판별 (계약 v6.4 1-2)
#
# 여기서 병합하지 않는다. "같은 논문으로 보인다"는 표시(duplicateOf=pmid)만 남기고,
# 애매하면 별개로 두고 review.duplicateAmbiguous에 넘긴다.
# ---------------------------------------------------------------------------

def normalize_title(text):
    """제목 비교용 정규화 — 소문자화 + 문장부호·공백 차이 제거 (한글도 남긴다)."""
    return re.sub(r"[^0-9a-z가-힣]+", " ", (text or "").lower()).strip()


def normalize_doi(text):
    """DOI 비교용 정규화 — 접두 URL과 대소문자 차이를 없앤다."""
    doi = (text or "").strip().lower()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi or None


def build_pubmed_index(pubmed_data):
    """PubMed 산출물을 교수별 중복 판별표로 바꾼다: {교수명: {byDoi, papers}}.

    대조 범위를 '같은 교수의 논문'으로 한정하는 이유: 병합은 교수 레코드 안에서 일어나고,
    다른 교수의 논문과 합치면 오귀속이 된다.
    """
    index = {}
    for professor, record in (pubmed_data.get("professors") or {}).items():
        by_doi, papers = {}, []
        for paper in record.get("allPapers") or []:
            pmid = paper.get("pmid")
            if not pmid:
                continue
            doi = normalize_doi(paper.get("doi"))   # 현재 3단계 산출물에는 doi 칸이 없다
            if doi:
                by_doi.setdefault(doi, set()).add(pmid)
            title = normalize_title(paper.get("title"))
            if title:
                papers.append({"title": title, "year": paper.get("year"), "pmid": pmid})
        index[professor] = {"byDoi": by_doi, "papers": papers}
    return index


def find_duplicate(article, professor_index):
    """KCI 논문 1편이 PubMed 논문과 같은 것인지 판별 — (pmid 또는 None, 애매 사유 또는 None).

    ① DOI 일치 (양쪽 모두 DOI가 있을 때만 성립)
    ② DOI가 없으면 정규화 제목 + 연도 일치 (영문 제목 우선 비교 — PubMed 제목이 영문이라서)
    ③ 후보가 여럿이거나 제목만 같고 연도가 다르거나 제목이 닮기만 하면 → 애매(별개로 둔다)
    """
    if not professor_index:
        return None, None

    doi = normalize_doi(article.get("doi"))
    if doi:
        candidates = professor_index["byDoi"].get(doi)
        if candidates:
            if len(candidates) == 1:
                return next(iter(candidates)), None
            return None, {"reason": "DOI가 같은 PubMed 논문이 여럿", "candidatePmids": sorted(candidates)}

    year = article.get("year")
    titles = [normalize_title(t) for t in (article.get("titleEn"), article.get("title")) if t]
    titles = [t for t in titles if t]
    if not titles:
        return None, None

    exact_same_year, exact_other_year, similar = set(), set(), set()
    for candidate in professor_index["papers"]:
        for title in titles:
            if candidate["title"] == title:
                (exact_same_year if candidate["year"] == year else exact_other_year).add(candidate["pmid"])
                break
            if (
                candidate["year"] == year
                and len(title) >= MIN_TITLE_CHARS_FOR_SIMILARITY
                and len(candidate["title"]) >= MIN_TITLE_CHARS_FOR_SIMILARITY
                and difflib.SequenceMatcher(None, title, candidate["title"]).ratio() >= DUPLICATE_SIMILARITY
            ):
                similar.add(candidate["pmid"])
                break

    if len(exact_same_year) == 1:
        return next(iter(exact_same_year)), None
    if len(exact_same_year) > 1:
        return None, {"reason": "제목·연도가 같은 PubMed 논문이 여럿", "candidatePmids": sorted(exact_same_year)}
    if exact_other_year:
        # 온라인 선공개/지면 발행 연도가 어긋난 경우일 수 있다 — 사람이 확인한다
        return None, {"reason": "제목은 같고 연도가 다름", "candidatePmids": sorted(exact_other_year)}
    if similar:
        return None, {"reason": "제목이 비슷하나 완전히 같지는 않음", "candidatePmids": sorted(similar)}
    return None, None


# ---------------------------------------------------------------------------
# 교수 1명 처리
#
# 산출물의 키는 교수 id(P-012)다. 이름은 사람이 읽기 위해 레코드 안에 name으로 함께 둔다.
# 이름을 키로 쓰면 동명이인이 한 칸에 뭉개지기 때문이다.
# ---------------------------------------------------------------------------

def classify_articles(articles, name, professor_id, professor_index):
    """검색 결과를 (채택 후보, 소속 미확인, 중복 애매)로 나눈다 — 네트워크를 쓰지 않는 순수 함수.

    '누구의 논문인가'는 여기서 정하지 않는다. 채택 후보에는 논문과 함께 근거가 된
    본인 저자 항목(author)을 붙여 돌려주고, 사람에게 배정할지 그대로 넣을지는 호출한 쪽이 정한다.
    professor_id가 None이면(동명이인 묶음) review 기록에도 id를 남기지 않는다.
    """
    adopted, unmatched, ambiguous = [], [], []

    for article in articles:
        author, reason = match_self_author(article, name)
        if author is None:
            # 채택하지 않는다 — 본인 논문이라는 근거가 없다 (원칙 2)
            unmatched.append({
                "professorId": professor_id,
                "professor": name,
                "kciId": article["kciId"],
                "title": article.get("title") or article.get("titleEn"),
                "reason": reason,
                # 사람이 바로 판단할 수 있게 응답에 있던 소속 표기를 그대로 보여 준다
                "affiliations": [a["affiliation"] for a in article["authors"] if a["affiliation"]][:5],
            })
            continue

        duplicate_pmid, ambiguous_info = find_duplicate(article, professor_index)
        if ambiguous_info:
            ambiguous.append({
                "professorId": professor_id,
                "professor": name,
                "kciId": article["kciId"],
                "title": article.get("titleEn") or article.get("title"),
                "year": article.get("year"),
                **ambiguous_info,
            })

        adopted.append({
            "paper": {
                "kciId": article["kciId"],
                "title": article.get("title"),
                "titleEn": article.get("titleEn"),
                "journal": article.get("journal"),
                "year": article.get("year"),
                "doi": article.get("doi"),
                "url": article.get("url"),
                "citedByCountKci": article.get("citedByCountKci"),
                "abstract": article.get("abstract"),
                "abstractEn": article.get("abstractEn"),
                "duplicateOf": duplicate_pmid,   # 병합은 조립 단계에서 — 여기서는 표시만
            },
            "author": author,
        })
    return adopted, unmatched, ambiguous


def build_author_info(adopted, name=""):
    """채택 논문들의 본인 저자 항목에서 영문명·ORCID를 모은다.

    표기가 논문마다 다를 수 있으므로 대표값(최빈값)만 남기지 않고 관측된 값을 함께 보존한다.
    - nameEn / orcid: 최빈값 (하나도 없으면 None — 지어내지 않는다)
    - nameEnVariants: 관측된 영문명 표기 목록 (많이 나온 순)
    - orcidCandidates: {value, count} 목록 — ORCID가 갈리면 동명이인이 섞였다는 신호다
    """
    name_en_counts = Counter(item["author"]["nameEn"] for item in adopted if item["author"]["nameEn"])
    orcid_counts = Counter(item["author"]["orcid"] for item in adopted if item["author"]["orcid"])

    if name and len(name_en_counts) > 1:
        print(f"  ! {name}: 영문명 표기 {len(name_en_counts)}가지 — 최빈값을 대표로 두고 전부 보존 (검수 필요)")
    if name and len(orcid_counts) > 1:
        print(f"  ! {name}: ORCID {len(orcid_counts)}가지 — 최빈값을 대표로 두고 전부 보존, 동명이인 여부 확인 필요")

    return {
        "nameEn": name_en_counts.most_common(1)[0][0] if name_en_counts else None,
        "orcid": orcid_counts.most_common(1)[0][0] if orcid_counts else None,
        "nameEnVariants": [value for value, _ in name_en_counts.most_common()],
        "orcidCandidates": [{"value": value, "count": count} for value, count in orcid_counts.most_common()],
    }


def build_record(name, adopted, found, unmatched_count, assign=True):
    """교수 1명분 산출물 레코드를 만든다.

    assign=False(동명이인)면 논문을 넣지 않는다 — 근거 없이 어느 한쪽에 붙이지 않기 위해서다.
    그때 papers는 빈 배열, authorInfo도 비우고, 몇 편이 미배정인지만 stats에 남긴다.
    """
    # assign=False면 논문도 저자 정보(영문명·ORCID)도 남기지 않는다 —
    # 영문명·ORCID 역시 같은 이름의 두 사람 중 누구 것인지 알 수 없기 때문이다.
    assigned = adopted if assign else []
    return {
        "name": name,                                   # 키는 id — 이름은 사람이 읽기 위해 함께 둔다
        "papers": [item["paper"] for item in assigned],
        "authorInfo": build_author_info(assigned, name if assign else ""),
        "stats": {
            "found": found,                             # 검색 결과 전체
            "adopted": len(adopted) if assign else 0,   # 이 교수에게 배정한 논문
            "affiliationUnmatched": unmatched_count,    # 소속 미확인으로 제외한 논문
            "homonymUnassigned": 0 if assign else len(adopted),  # 동명이인이라 배정 보류한 논문
        },
    }


def build_professor_record(name, articles, professor_index, professor_id=None):
    """이름이 겹치지 않는 교수 1명 — (레코드, 소속 불일치 목록, 중복 애매 목록)."""
    adopted, unmatched, ambiguous = classify_articles(articles, name, professor_id, professor_index)
    record = build_record(name, adopted, len(articles), len(unmatched))
    return record, unmatched, ambiguous


def build_homonym_entry(name, professor_ids, adopted):
    """동명이인 검수 기록 — 사람이 보고 손으로 배정할 수 있게 후보와 근거를 함께 남긴다.

    각 후보에 저자의 ORCID·소속·영문명을 붙이는 이유: 두 사람을 가를 수 있는 단서가
    사실상 이것뿐이기 때문이다 (이름·소속은 둘 다 전북대라 같을 수 있다).
    """
    return {
        "professor": name,
        "professorIds": list(professor_ids),
        "reason": f"대상 명단에 같은 이름의 교수가 {len(professor_ids)}명 — 자동 배정하지 않음",
        "candidates": [
            {
                **item["paper"],
                "author": {
                    "nameEn": item["author"]["nameEn"],
                    "orcid": item["author"]["orcid"],
                    "affiliation": item["author"]["affiliation"],
                },
            }
            for item in adopted
        ],
    }


def build_homonym_records(name, professor_ids, articles, professor_index):
    """동명이인 묶음 — 어느 쪽에도 배정하지 않는다 (근거가 없으면 채우지 않는다).

    반환: ({id: 레코드}, 소속 불일치 목록, 중복 애매 목록, 검수 기록 또는 None)
    이름으로 한 번만 검색하고, 같은 이름의 교수 전원에게 '빈 레코드'를 준다.
    후보 논문은 review.homonymUnassigned로 보내 사람이 배정하게 한다.
    """
    adopted, unmatched, ambiguous = classify_articles(articles, name, None, professor_index)
    records = {
        professor_id: build_record(name, adopted, len(articles), len(unmatched), assign=False)
        for professor_id in professor_ids
    }
    entry = build_homonym_entry(name, professor_ids, adopted) if adopted else None
    return records, unmatched, ambiguous, entry


# ---------------------------------------------------------------------------
# 대상 명단 · 상태 저장(resume)
# ---------------------------------------------------------------------------

def load_targets():
    """대상 교수 목록 — professors.json(계약 0-2, 의대 공식 명단 기준)에서 읽는다.

    반환: ([{"id": "P-012", "name": "황주희"}, …], {이름: [id, …]})
    두 번째 값으로 이름→id 표를 함께 돌려주는 이유: 같은 이름의 교수가 둘 이상이면
    (예: 이창훈 P-176/P-177) 검색 결과를 어느 쪽에도 배정하지 않기 때문이다.
    """
    if not TARGET_PATH.exists():
        raise SystemExit(
            f"대상 명단 파일이 없습니다: {TARGET_PATH}\n"
            "조립 단계(D) 산출물이 필요합니다. 먼저 professors.json을 만들어 주세요."
        )
    with open(TARGET_PATH, encoding="utf-8") as f:
        data = json.load(f)

    targets, ids_by_name = [], {}
    for professor in data.get("professors") or []:
        professor_id, name = professor.get("id"), professor.get("name")
        if not professor_id or not name:
            continue
        targets.append({"id": professor_id, "name": name})
        ids_by_name.setdefault(name, []).append(professor_id)
    return targets, ids_by_name


def load_pubmed_index():
    """3단계 산출물을 읽어 중복 판별표를 만든다. 없으면 빈 표 + 경고(수집은 계속)."""
    if not PUBMED_PATH.exists():
        print(f"! PubMed 산출물이 없어 중복 판별을 건너뜁니다: {PUBMED_PATH}")
        return {}
    with open(PUBMED_PATH, encoding="utf-8") as f:
        data = json.load(f)
    index = build_pubmed_index(data)
    papers = sum(len(v["papers"]) for v in index.values())
    with_doi = sum(len(v["byDoi"]) for v in index.values())
    print(f"중복 판별표: 교수 {len(index)}명 · 논문 {papers}편 (DOI 보유 {with_doi}편)")
    if papers and not with_doi:
        # 3단계 산출물에는 doi 칸이 없다 → 1순위 규칙(DOI)이 사실상 동작하지 않는다.
        # 지금 동작도 계약 1-2 ②로 정상이지만, DOI가 있으면 판별이 더 정확해진다.
        print("  ! PubMed 쪽에 DOI가 없어 중복 판별은 '제목+연도'로만 이뤄집니다 (계약 1-2 ②).")
        print("    PubMed 수집에 doi가 추가되면 1순위 규칙(DOI 일치)이 켜져 판별 정확도가 올라갑니다"
              " — 보완은 별도 PR 예정")
    return index


def load_state():
    """저장된 산출물을 읽어 이어서 진행할 준비를 한다. 없거나 FORCE_REFRESH면 새로 시작."""
    if not FORCE_REFRESH and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("professors", {})
        state.setdefault("review", {})
        for key in REVIEW_KEYS:
            state["review"].setdefault(key, [])
        print(f"기존 산출물 발견: 교수 {len(state['professors'])}명 완료됨 → 이어서 진행 (resume)")
        return state
    return {
        "collectedAt": None,
        "professors": {},
        "review": {key: [] for key in REVIEW_KEYS},
    }


def drop_professor_reviews(state, name):
    """그 이름의 지난 review 기록을 걷어낸다 — 다시 수집할 때 기록이 두 배로 불어나지 않게.

    id가 아니라 '이름'으로 지우는 이유: 검색·수집의 단위가 이름이라(같은 이름이면 한 번만
    검색한다) 그 이름에서 나온 기록은 한꺼번에 다시 만들어지기 때문이다.
    """
    review = state["review"]
    for key in REVIEW_KEYS:
        review[key] = [entry for entry in review[key] if entry.get("professor") != name]


def save_state(state):
    """교수 1명이 끝날 때마다 호출 — 중간에 끊겨도 여기까지는 남는다.

    임시 파일에 먼저 쓰고 바꿔치기해서, 저장 도중 끊겨도 기존 파일이 깨지지 않게 한다.

    바꿔치기(os.replace)를 재시도하는 이유 — 윈도우에서는 다른 프로그램이 산출물 파일을
    열어 두고 있으면 교체가 PermissionError(WinError 5)로 실패한다. 실측에서 진행 상황을
    보려고 파일을 읽는 것만으로도 40분짜리 실행이 여기서 죽었다. 편집기·백신·백업 도구도
    같은 일을 하므로, 잠깐 기다렸다 다시 시도한다. (열려 있는 시간은 대개 순간이다)
    """
    state["collectedAt"] = date.today().isoformat()  # 수집 기준일 (계약 원칙 4)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)  # ensure_ascii=False: 한글 보존

    for attempt in range(1, SAVE_ATTEMPTS + 1):
        try:
            os.replace(tmp_path, OUTPUT_PATH)
            return
        except PermissionError:
            if attempt == SAVE_ATTEMPTS:
                # 여기까지 왔으면 파일이 계속 잡혀 있다. 수집 결과를 버리지 않도록
                # 임시 파일을 남겨 두고 알린다 — 다음 저장에서 다시 교체를 시도한다.
                print(f"  ! 저장 실패: {OUTPUT_PATH.name}을 다른 프로그램이 열고 있습니다."
                      f" 임시 파일을 남겨 둡니다({tmp_path.name}) — 파일을 닫으면 다음 저장에서 반영됩니다")
                return
            time.sleep(SAVE_RETRY_WAIT)


def print_summary(state, elapsed_seconds, run_professors):
    """실행이 끝날 때 사람이 검수할 수 있게 누적 통계를 요약한다 (지시서 2-7)."""
    professors = state["professors"]
    review = state["review"]
    found = sum(p["stats"]["found"] for p in professors.values())
    adopted = sum(p["stats"]["adopted"] for p in professors.values())
    unmatched = sum(p["stats"]["affiliationUnmatched"] for p in professors.values())
    duplicates = sum(
        1 for p in professors.values() for paper in p["papers"] if paper["duplicateOf"]
    )
    homonym_ids = [pid for pid, p in professors.items() if p["stats"]["homonymUnassigned"]]
    homonym_papers = sum(len(entry["candidates"]) for entry in review["homonymUnassigned"])
    name_en = sum(1 for p in professors.values() if p["authorInfo"]["nameEn"])
    orcid = sum(1 for p in professors.values() if p["authorInfo"]["orcid"])

    print("\n===== 누적 현황 =====")
    print(f"처리한 교수: {len(professors)}명(id 기준) · 결과 0건 {len(review['noResult'])}명")
    print(f"검색 결과: {found}편 → 채택 {adopted}편 / 소속 불일치 제외 {unmatched}편")
    print(f"중복 판별: PubMed 논문과 동일로 표시(duplicateOf) {duplicates}편"
          f" · 애매 {len(review['duplicateAmbiguous'])}편")
    if homonym_ids:
        print(f"동명이인 미배정: 교수 {len(homonym_ids)}명({', '.join(homonym_ids)}) · 후보 논문 {homonym_papers}편"
              " — review.homonymUnassigned에서 사람이 배정")
    print(f"부수 수집: 영문명 {name_en}명 · ORCID {orcid}명")
    print("review: " + " / ".join(f"{key} {len(review[key])}" for key in REVIEW_KEYS))
    if review["fetchFailed"]:
        names = ", ".join(entry["professor"] for entry in review["fetchFailed"])
        print(f"fetchFailed 교수는 저장되지 않았습니다 — 다시 실행하면 자동으로 재시도됩니다: {names}")
    print(f"이번 실행: 교수 {run_professors}명 · {elapsed_seconds:.0f}초")
    print(f"저장 위치: {OUTPUT_PATH}")


def main():
    # 인증키 — 없으면 발급 절차를 안내하고 여기서 중단한다 (exit 1)
    api_key = read_kci_api_key()

    targets, ids_by_name = load_targets()
    if LIMIT is not None:
        targets = targets[:LIMIT]
        print(f"LIMIT={LIMIT}: 대상 명단 앞 {len(targets)}명만 처리합니다 (검증용)")
    homonyms = {name: ids for name, ids in ids_by_name.items() if len(ids) > 1}
    print(f"대상: 교수 {len(targets)}명 ({TARGET_PATH.name})")
    if homonyms:
        detail = " · ".join(f"{name} {'/'.join(ids)}" for name, ids in homonyms.items())
        print(f"동명이인 {len(homonyms)}건 — 검색 결과를 어느 쪽에도 배정하지 않습니다: {detail}")

    pubmed_index = load_pubmed_index()
    state = load_state()
    run_professors = 0
    started = time.monotonic()

    for position, target in enumerate(targets, start=1):
        professor_id, name = target["id"], target["name"]
        if professor_id in state["professors"]:
            print(f"{professor_id} {name}: 이미 완료 — 건너뜀 (resume)")
            continue

        try:
            # 검색은 이름으로 한다 — 같은 이름의 교수가 여럿이어도 호출은 한 번뿐이다
            articles = fetch_articles(api_key, name)
        except RETRYABLE_ERRORS as exc:
            # 재시도까지 실패했다 — 이 교수는 **저장하지 않는다.**
            # 빈 레코드(papers: [])를 남기지 않는 것이 중요하다: 그러면 다음 단계가
            # '국내 논문 없음'으로 읽고, 재실행해도 완료된 것으로 보고 건너뛴다.
            # 저장하지 않으면 이전 실행의 결과가 그대로 남고, 재실행 시 자동으로 다시 시도된다.
            drop_professor_reviews(state, name)
            state["review"]["fetchFailed"].append(
                {"professorId": professor_id, "professor": name,
                 "stage": "articleSearch", "error": _describe_error(exc)}
            )
            save_state(state)
            print(f"  → {name}: 수집 실패({_describe_error(exc)})"
                  " — fetchFailed 기록(레코드 미저장), 다음 교수로 계속")
            continue
        except KciApiError as exc:
            # 인증키·파라미터 오류는 모든 교수에서 똑같이 나므로 계속해 봐야 의미가 없다.
            # 여기까지 수집한 결과는 저장한 뒤 멈춘다.
            save_state(state)
            print(f"\nKCI가 오류 응답을 돌려줬습니다: {exc}")
            print("인증키·파라미터를 확인한 뒤 다시 실행해 주세요 (완료된 교수는 건너뜁니다).")
            sys.exit(1)

        professor_index = pubmed_index.get(name)   # 3단계 산출물은 이름을 키로 쓴다
        drop_professor_reviews(state, name)
        sibling_ids = ids_by_name[name]

        if len(sibling_ids) > 1:
            # 동명이인 — 근거 없이 배정하지 않는다. 같은 이름의 교수 전원에게 빈 레코드를 주고,
            # 후보 논문은 저자 ORCID·소속과 함께 검수 목록으로 넘긴다 (원칙 2).
            records, unmatched, ambiguous, entry = build_homonym_records(
                name, sibling_ids, articles, professor_index
            )
            state["professors"].update(records)
            if entry:
                state["review"]["homonymUnassigned"].append(entry)
            record = records[professor_id]
            print(
                f"[{position}/{len(targets)}] {name}({'/'.join(sibling_ids)}): 검색 {record['stats']['found']}편"
                f" → 동명이인이라 배정 보류 {record['stats']['homonymUnassigned']}편"
                f" · 소속 불일치 {record['stats']['affiliationUnmatched']}편"
            )
        else:
            record, unmatched, ambiguous = build_professor_record(
                name, articles, professor_index, professor_id
            )
            state["professors"][professor_id] = record
            print(
                f"[{position}/{len(targets)}] {professor_id} {name}: 검색 {record['stats']['found']}편"
                f" → 채택 {record['stats']['adopted']}편"
                f" · 소속 불일치 {record['stats']['affiliationUnmatched']}편"
                f" · 중복표시 {sum(1 for p in record['papers'] if p['duplicateOf'])}편"
            )

        state["review"]["affiliationUnmatched"].extend(unmatched)
        state["review"]["duplicateAmbiguous"].extend(ambiguous)
        if not articles:
            # 결과가 0건이면 배정할 것도 없다 — 동명이인이어도 id별로 그대로 기록한다
            for sibling_id in sibling_ids:
                state["review"]["noResult"].append({"professorId": sibling_id, "professor": name})
        save_state(state)  # 교수 1명 끝날 때마다 즉시 저장 — 끊겨도 여기까지 보존

        run_professors += 1

    print_summary(state, time.monotonic() - started, run_professors)


if __name__ == "__main__":
    main()
