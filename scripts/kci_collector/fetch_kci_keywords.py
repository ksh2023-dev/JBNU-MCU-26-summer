"""KCI 키워드 보강 — 이미 수집한 논문에 키워드·연구분야·저자 상세를 얹는다.

흐름: 기존 산출물(kci_papers.json) 읽기
      → 논문의 kciId로 apiCode=articleDetail 호출
      → 응답에서 키워드·연구분야·논문언어·저자 상세를 뽑아 캐시에 즉시 저장 (재개 가능)
      → 캐시를 kci_papers.json의 각 논문에 얹는다 (기존 필드는 건드리지 않는다)

**전체 재수집이 아니다.** 검색(articleSearch)은 다시 하지 않는다 — 이미 확보한 논문의
kciId로 상세(articleDetail)만 부른다. 본인 논문 판별·중복 판별은 fetch_kci.py가 이미 끝냈다.

왜 articleDetail인가: 지금 쓰는 articleSearch **응답에는 키워드가 없다**
(keyword는 요청 파라미터일 뿐 응답 필드가 아니다). 키워드는 articleDetail에만 있다.

2026-08-21 실측으로 확인한 응답 구조:
    MetaData > outputData > record > articleInfo
                                   > referenceInfo   ← **articleInfo의 형제다**
  referenceInfo 안에 참고문헌이 수십 건 들어 있어 doi·journal-name·title·volume 같은
  태그가 33개씩 나온다. 그래서 파싱 범위를 **articleInfo로 한정**한다. 문서 전체에서
  태그를 찾으면 참고문헌 값이 논문 값으로 둔갑한다.

    <article-categories>의약학 > 내과학</article-categories>
    <article-language>한국어</article-language>
    <keyword-group><keyword><![CDATA[…]]></keyword>…</keyword-group>
    <author author-division="1" author-part="제1" orc-id="0000-…">
      <name>·<name-eng>·<institution>

키워드 언어: **KCI가 한글·영문을 한 리스트에 구분 없이 섞어 준다** (lang 속성이 없다).
실측 예 — ART003365943: Diabetic ketoacidosis / Hamman syndrome / … / 당뇨병성 케톤산증 / …
한글 음절이 하나라도 있으면 ko, 아니면 en으로 나눈다. 번역은 하지 않는다(원본 그대로).
**짝을 맞추려 하지 않는다** — 두 리스트의 길이가 다를 수 있고, 한쪽만 있는 논문도 많다.

fail-closed: 해석할 수 없는 응답을 "키워드 0건"으로 저장하지 않는다. keywords를 빈 값으로
두는 것은 **articleInfo를 실제로 찾았는데 keyword-group이 없을 때뿐**이다. 점검 페이지·
프록시 오류·형식 변경은 KciUnexpectedResponseError로 다뤄 재시도하고, 끝내 실패하면
그 논문만 review.detailFailed에 남긴다 (재실행하면 자동으로 다시 시도된다).

재개(resume): 논문 1편을 받을 때마다 캐시 파일에 즉시 저장한다. 중간에 끊겨도 이어서 돈다.
kci_papers.json은 32MB라 논문마다 다시 쓰면 실행 시간이 한 시간 넘게 늘어나므로,
MERGE_EVERY편마다 그리고 마지막에 한 번 반영한다. 캐시가 이미 완전하므로 유실은 없다.

실행 (저장소 루트에서):
    python scripts/kci_collector/fetch_kci_keywords.py
"""

import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import requests

# KCI 수집기(1단계) 부품 재사용 — 기존 파일은 수정하지 않는다 (같은 폴더라 바로 import)
import fetch_kci

# ===== 실행 옵션 (실행 전 이 부분만 수정하면 됩니다) ============================
FORCE_REFRESH = False   # True면 캐시를 무시하고 전부 다시 조회
LIMIT = None            # 개발·검증용: 앞 N편만 처리 (None이면 전체)
# ==============================================================================

API_CODE = "articleDetail"
SLEEP_SECONDS = 0.5          # API 예절 — fetch_kci.py와 같은 값
MERGE_EVERY = 200            # 이 편수마다 kci_papers.json에 반영 (캐시는 매 편 저장한다)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "data" / "output" / "kci_papers.json"
CACHE_PATH = ROOT / "data" / "output" / "_cache_kci_details.json"

# 한글 음절과 낱자 — "K-MMSE 검사"처럼 영문이 섞여 있어도 한글이 하나라도 있으면 ko다
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


# ---------------------------------------------------------------------------
# 응답 파싱
# ---------------------------------------------------------------------------

def _article_infos(root):
    """응답의 articleInfo 요소를 모두 돌려준다.

    referenceInfo(참고문헌)는 형제라 여기에 딸려 오지 않는다 — 파싱 범위를 좁히는 핵심이다.
    개수 판단은 호출한 쪽에서 한다: 상세 조회는 논문 1편을 묻는 것이므로 2개 이상은 이상 신호다.
    """
    return list(fetch_kci._iter_by_tag(root, "articleinfo"))


# 한 칸에 여러 키워드가 뭉쳐 온 경우를 쪼갠다 — 2026-08-21 전수 확인에서 158개/104편.
# 통짜 문자열로 두면 검색에 걸리지 않아 사실상 못 쓰는 데이터가 된다.
#   'Pediatric epilepsy· Surgery· Development· Cognitive function.'
#     → ['Pediatric epilepsy', 'Surgery', 'Development', 'Cognitive function']
#
# 가운뎃점은 코드포인트가 여럿이다 (실측): · U+00B7 / ∙ U+2219 / • U+2022 / ․ U+2024
#
# 슬래시는 **양쪽에 공백이 있을 때만** 구분자로 본다.
#   'Free tissue flaps / Head and neck neoplasms / Microsurgery'  → 구분자 (공백 있음)
#   'db/db mice' · 'LC-MS/MS' · 'Th1/Th2 imbalance' · '과잉행동/충동성' → 낱말 안 (공백 없음)
# 공백 없는 '/'는 57개 중 대부분이 낱말 안이라 쪼개면 오히려 망가진다.
#
# 공백 마침표('. ')는 구분자로 쓰지 않는다 — 'et al.' 같은 약어와 구분이 안 되고,
# 영향 범위가 너무 넓다 (끝마침표를 정리했을 때 294편이 함께 바뀌었다).
PACKED_SEPARATOR = re.compile(r"[·∙•․;]|\s+/\s+")

# 쪼개면 안 되는 것들 — 관문에서 158개를 전건 대조해 사람이 가려냈다.
# 원본 문자열로 지목한다(kciId로 지목하면 그 논문의 다른 키워드까지 막힌다).
SPLIT_EXCLUSIONS = {
    "Survey with Korean·Western medicine":
        "가운뎃점이 낱말 안에 있다(한·양방 협진). 쪼개면 'Survey with Korean'이 깨진다",
    "1. 하행 흉부 대동맥류2. 대동맥 축착증1. Flyer DC. Report of the New England Regional "
    "Infant Car-diac Program. Pediatrics 1980;64:432-6.2. Deron MS":
        "키워드 자리에 참고문헌이 통째로 들어와 있다. 세미콜론이 '1980;64:432-6'의 일부라 "
        "쪼개면 더 망가진다",
    "External landmark· Leksell frame application· Thalamotomy· Pallidotomy."
    "VOLUME 34 September":
        "이 논문은 키워드 목록 전체가 학술지 앞부속(접수일·교신주소·소속)으로 오염돼 있다. "
        "쪼개도 쓸 수 없다",
    "Attention deficit hyperactivity disorder (ADHD)· Alpha-1C-adrenergic receptor gene "
    "(ADRA1C)· Endophe-notype· Temperament. Address for correspondence Jae-Won Kim":
        "마지막 조각에 교신저자 주소가 붙어 있다. 규칙으로 쪼개지 않고 "
        "아래 KEYWORD_FIXES에서 정상 4개를 직접 지정한다",
    "초등학생 및 중 ․ 고등학생용 KEDI 리더십특성검사(간편형)":
        "가운뎃점이 낱말 안에 있다(중·고등학생용). 쪼개면 '초등학생 및 중'이 깨진다",
}


# ---------------------------------------------------------------------------
# 오염된 키워드 손질 — 사람이 지목한 명시 목록
#
# KCI 원본의 키워드 자리에 참고문헌·투고일·교신저자 주소가 통째로 들어온 논문이 있다.
# 그대로 두면 검색에 저자 이름과 서지 정보가 걸린다. 자동 규칙으로 지우면 멀쩡한
# 키워드까지 다칠 수 있어, **논문을 하나씩 지목해** 처리한다
# (data/input/manual_exclusions.json과 같은 생각이다 — 재실행해도 유지되게 코드에 둔다).
#
#   clearAll : 그 논문의 키워드를 전부 버린다 (쓸 수 있는 것이 하나도 없을 때)
#   keep     : 그 언어의 키워드를 여기 적은 목록으로 갈아끼운다 (다른 언어는 그대로)
#   reason   : 왜 손댔는지. 반드시 남긴다
#   rawFingerprint : **그 판단을 내릴 때 KCI가 주던 원본 값의 지문**
#
# rawFingerprint가 있는 이유 — 손질은 "그때 그 값"을 보고 사람이 내린 판단이다.
# kciId만 보고 적용하면, KCI가 나중에 키워드를 정상으로 고쳐도 이 코드가 영구히 덮어써서
# 멀쩡한 데이터를 계속 지운다. 그래서 **현재 원본이 그때와 같을 때만** 적용하고,
# 달라졌으면 손대지 않고 review.keywordFixStale에 남긴다 (사람이 다시 확인해야 한다는 신호).
#
# 지문이 어긋나 stale로 빠지면 review.keywordFixStale에 현재 지문이 함께 찍힌다.
# 새 원본을 확인한 뒤 판단이 그대로면 그 값을 rawFingerprint에 옮겨 적으면 된다.
#
# 원본은 keywordsRaw에 보존하고, 실행할 때마다 review.keywordFixes에도 기록한다.
# ---------------------------------------------------------------------------
KEYWORD_FIXES = {
    "ART001005699": {
        "rawFingerprint": "sha256:5fca9fc30f409640",
        "clearAll": True,
        "reason": "키워드 자리 전체가 학술지 앞부속으로 오염됐다 — "
                  "'2003 217Received ：April 4' · '2003 Accepted ：June 3' · "
                  "'2003Address for reprints ：Ha-Young Choi' · 'M.D.' · "
                  "'Department ofNeurosurgery' · 'Research Institute for Clinical Me'. "
                  "쓸 수 있는 키워드가 하나도 없어 비운다",
    },
    "ART000872261": {
        "rawFingerprint": "sha256:c2ed0bf69fb0379a",
        "clearAll": True,
        "reason": "키워드 자리에 참고문헌이 통째로 들어왔다 — "
                  "'Flyer DC. Report of the New England Regional Infant Cardiac Program. "
                  "Pediatrics 1980;64:432-6' · 'James SD. Repair of Aneurysm Aortic "
                  "Coarctation … Ann Thorac Surg 2001' 등. 비운다",
    },
    "ART002051027": {
        "rawFingerprint": "sha256:23e412b184ee785a",
        "keep": {
            "en": [
                "Social network analysis",
                "Korean Journal of Medical Education",
                "Research trends",
            ],
        },
        "reason": "키워드 목록에 'Keywords'라는 맨 라벨이 값으로 들어와 있다. "
                  "자동 규칙(Keywords: 접두사 제거)은 콜론을 요구하므로 이 값은 걸리지 않는다 — "
                  "콜론을 선택으로 두면 'Keyword extraction' 같은 정상 키워드의 첫 낱말이 "
                  "잘려 나가기 때문이다. 나머지 3개는 정상이라 그대로 두고 라벨만 뺀다",
    },
    "ART001224869": {
        "rawFingerprint": "sha256:6dc8866a2fea5b80",
        "keep": {
            "en": [
                "Attention deficit hyperactivity disorder (ADHD)",
                "Alpha-1C-adrenergic receptor gene (ADRA1C)",
                "Endophe-notype",
                "Temperament",
            ],
        },
        "reason": "영문 키워드에 교신저자 주소가 섞여 들어왔다 — "
                  "'… Temperament. Address for correspondence Jae-Won Kim' · "
                  "'M.D. Department of Child and Adolescent Psychiatry' · "
                  "'College of Medicine' · 'Seoul National'. 정상 4개만 남긴다. "
                  "한글 키워드는 정상이라 그대로 둔다",
    },
}


def raw_fingerprint(raw):
    """원본 키워드({ko, en})의 지문 — 값이 바뀌면 지문도 바뀐다.

    긴 오염 문자열을 코드에 그대로 붙이면 읽기 어려워서 짧은 해시로 지목한다.
    무엇이 들어 있었는지는 각 fix의 reason에 사람 말로 적어 둔다.
    """
    canonical = json.dumps(
        {lang: list(raw.get(lang) or []) for lang in ("ko", "en")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def apply_keyword_fix(kci_id, keywords, raw):
    """지목된 논문이면 손질한 키워드를 돌려준다 — (키워드, stale 기록 또는 None).

    **현재 원본이 등록된 지문과 같을 때만** 손질한다. 달라졌으면 KCI 쪽 데이터가 바뀐 것이므로
    자동으로 덮어쓰지 않고 그대로 둔 채 stale 기록만 남긴다 (사람이 다시 판단할 몫이다).
    """
    fix = KEYWORD_FIXES.get(kci_id)
    if not fix:
        return keywords, None

    current = raw_fingerprint(raw)
    expected = fix.get("rawFingerprint")
    if current != expected:
        return keywords, {
            "kciId": kci_id,
            "reason": "원본 키워드가 손질 판단 당시와 달라졌습니다 — 손대지 않았습니다",
            "expectedFingerprint": expected,
            "currentFingerprint": current,
            "currentRaw": raw,
            "fixReason": fix["reason"],
        }

    if fix.get("clearAll"):
        return {"ko": [], "en": []}, None
    keep = fix.get("keep", {})
    return {lang: list(keep[lang]) if lang in keep else list(keywords[lang])
            for lang in ("ko", "en")}, None


def split_packed(text):
    """뭉쳐 온 키워드를 쪼갠다. 쪼개면 안 되는 것은 원본 그대로 한 개로 돌려준다."""
    if text in SPLIT_EXCLUSIONS:
        return [text]
    if not PACKED_SEPARATOR.search(text):
        # 구분자가 없으면 아예 손대지 않는다. 여기서 끝마침표까지 정리하면
        # 뭉치지 않은 키워드 수백 개가 함께 바뀌어, 무엇을 왜 고쳤는지 흐려진다.
        return [text]
    pieces = []
    for raw in PACKED_SEPARATOR.split(text):
        piece = re.sub(r"\s+", " ", raw).strip().strip(".").strip()
        if piece:
            pieces.append(piece)
    return pieces or [text]


# ---------------------------------------------------------------------------
# upstream(KCI) 오염 정제 — 자동으로 손대는 것은 아래 두 가지뿐이다
#
# KCI의 keyword 필드 자체에 학술지 앞부속·본문 조각이 섞여 들어온 논문이 있다
# (referenceInfo 문제가 아니다 — 원본 필드가 그렇게 저장돼 있다).
# 일반화할 수 있고 위험이 낮은 두 가지만 자동으로 처리하고, 나머지(날짜·이메일·
# 교신저자·참고문헌 조각)는 **지우지 않고** review.keywordSuspect에 기록만 한다.
# ---------------------------------------------------------------------------

# 규칙 2: 'Keywords:' 계열 접두사만 떼고 내용은 살린다.
#   'Keywords : Breast neoplasms' → 'Breast neoplasms'
# **콜론을 반드시 요구한다.** 콜론을 선택으로 두면 'Keyword extraction'처럼
# keyword로 시작하는 멀쩡한 키워드에서 첫 낱말이 잘려 나간다 (실측 관문에서 확인).
KEYWORD_LABEL_PREFIX = re.compile(r"^[\s.,;:]*key\s*words?\s*[:：]\s*", re.I)


def sanitize_keyword(text):
    """키워드 한 개를 정제한다. 버릴 값이면 None.

    규칙 1 — 글자·숫자가 하나도 없는 값(구두점만)은 버린다: '.', ',' 등.
      str.isalnum()은 한자·그리스문자도 글자로 인정한다. 실측에 守令·月暈 같은
      한자 키워드가 18건 있어서, 라틴/한글만 글자로 보면 멀쩡한 값이 지워진다.
    규칙 2 — 'Keywords:' 접두사만 떼어 낸다 (내용은 그대로 둔다).
    """
    if not any(ch.isalnum() for ch in text):
        return None
    stripped = KEYWORD_LABEL_PREFIX.sub("", text).strip()
    return stripped or None


# 자동으로 지우지 않고 사람에게 넘길 오염 신호. 지우기에는 판단이 필요한 것들이다.
# (자동 규칙으로 없애려면 정밀도가 충분해야 하는데, 이 값들은 형태가 제각각이다)
SUSPECT_PATTERNS = (
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    # 콜론을 요구한다 — 'Revised version of the Korean …' 같은 정상 키워드를 피하기 위해서다
    ("접수·게재일", re.compile(
        r"(접\s*수(\s*일|\s*번호)?|게재\s*승인\s*일|수정본\s*접\s*수|received|accepted)\s*[:：]", re.I)),
    ("교신저자·연락처", re.compile(
        r"교신저자|통신저자|corresponding author|address for (reprints?|correspondence)"
        r"|(tel|fax)\s*[.:]", re.I)),
    ("참고문헌·본문 조각", re.compile(r"et al\.|(19|20)\d{2}\s*[;:]\s*\d+|서\s*론")),
)


def detect_suspects(keywords):
    """정제 후에도 남은 오염 의심 값을 찾는다 — 기록만 하고 지우지 않는다."""
    suspects = []
    for lang in ("ko", "en"):
        for value in keywords[lang]:
            reasons = [name for name, pattern in SUSPECT_PATTERNS if pattern.search(value)]
            if reasons:
                suspects.append({"lang": lang, "value": value, "reasons": reasons})
    return suspects


def split_keywords(keywords, unpack=True):
    """한 리스트로 섞여 온 키워드를 한글/영문으로 나눈다 (순서 유지, 중복 제거).

    KCI는 언어 속성을 주지 않으므로 글자로 가른다 — 한글 음절이 하나라도 있으면 ko다.
    "COVID-19"·"HbA1c" → en, "K-MMSE 검사" → ko.

    unpack=False면 뭉쳐 온 키워드를 쪼개지 않고 정제도 하지 않는다
    — 원본을 keywordsRaw에 그대로 남길 때 쓴다.
    """
    result = {"ko": [], "en": []}
    seen = {"ko": set(), "en": set()}
    for keyword in keywords:
        text = fetch_kci._clean(keyword)
        if not text:
            continue
        for piece in (split_packed(text) if unpack else [text]):
            if unpack:
                # 정제는 최종 결과에만 적용한다 — keywordsRaw(unpack=False)는 원본 그대로 둔다
                piece = sanitize_keyword(piece)
                if not piece:
                    continue
            lang = "ko" if _HANGUL_RE.search(piece) else "en"
            if piece in seen[lang]:
                continue
            seen[lang].add(piece)
            result[lang].append(piece)
    return result


def parse_detail(xml_bytes, kci_id):
    """articleDetail 응답을 상세 dict로 바꾼다.

    해석할 수 없으면 KciUnexpectedResponseError를 던진다 — 조용히 빈 값으로 두지 않는다.
    KCI가 오류 문구를 돌려주면 KciApiError (재시도해도 같은 결과다).
    """
    root = ET.fromstring(xml_bytes)      # 깨진 XML이면 ParseError → 호출한 쪽이 재시도
    articles = _article_infos(root)

    if len(articles) > 1:
        # 상세 조회는 논문 1편을 묻는 것이다. 여러 개가 오면 첫 번째를 말없이 집을 게 아니라
        # 형식 변경 신호로 보고 거부한다 (fetch_kci.parse_response도 같은 자리를 명시 처리한다).
        raise fetch_kci.KciUnexpectedResponseError(
            f"{kci_id}: 한 응답에 articleInfo가 {len(articles)}개입니다 "
            f"(API 형식 변경 신호): {fetch_kci._snippet(xml_bytes)}"
        )
    article = articles[0] if articles else None

    if article is None:
        # 논문 정보가 없다 — '정상적인 0건'이라는 근거를 찾는다. 없으면 오류다 (fail-closed)
        for node in fetch_kci._iter_by_tag(root, "resultmsg", "errormsg", "errmsg", "error"):
            message = fetch_kci._clean(node.text)
            if not message:
                continue
            if fetch_kci._NO_DATA_PATTERN.search(message):
                return None              # 근거 있는 '해당 논문 없음' — 호출한 쪽이 기록한다
            raise fetch_kci.KciApiError(message)
        raise fetch_kci.KciUnexpectedResponseError(
            f"{kci_id}: articleInfo도 0건 안내도 없는 응답 "
            f"(최상위 <{fetch_kci._local(root.tag)}>): {fetch_kci._snippet(xml_bytes)}"
        )

    # 요청한 논문이 맞는지 확인한다 — 다른 논문의 상세를 얹으면 그대로 오귀속이다.
    # **식별자가 없으면 통과시키지 않는다.** 없는 것은 "확인 못 함"이지 "맞음"이 아니다.
    # fetch_kci.parse_response도 article-id 누락을 형식 변경 신호로 보고 fail-closed 처리한다.
    returned_id = fetch_kci._attr(article, "article-id", "articleid")
    if returned_id != kci_id:
        detail_text = (f"{returned_id} 응답이 왔습니다" if returned_id
                       else "응답에 article-id가 없습니다 (API 형식 변경 신호)")
        raise fetch_kci.KciUnexpectedResponseError(
            f"{kci_id}를 요청했는데 {detail_text}: {fetch_kci._snippet(xml_bytes)}"
        )

    keywords = [node.text for node in fetch_kci._iter_by_tag(article, "keyword")]
    categories = [c for c in (fetch_kci._clean(node.text)
                              for node in fetch_kci._iter_by_tag(article, "article-categories")) if c]

    authors = []
    for node in fetch_kci._iter_by_tag(article, "author"):
        authors.append({
            "name": fetch_kci._first_text(node, "name"),
            "nameEn": fetch_kci._first_text(node, "name-eng"),
            "orcid": fetch_kci._attr(node, "orc-id", "orcid"),
            # author-division: 1=주저자, 2=공동저자. author-part는 제1·참여·교신 표기
            "authorDivision": fetch_kci._attr(node, "author-division"),
            "authorPart": fetch_kci._attr(node, "author-part"),
            "affiliation": fetch_kci._first_text(node, "institution"),
        })

    raw = split_keywords(keywords, unpack=False)
    final, stale = apply_keyword_fix(kci_id, split_keywords(keywords), raw)
    detail = {
        "keywords": final,
        "articleCategories": categories,     # "의약학 > 내과학" — KCI 원본 표기 그대로 둔다
        "articleLanguage": fetch_kci._first_text(article, "article-language"),
        "authors": authors,
    }
    if raw != final:
        # 쪼갰거나 손질한 논문에만 원본을 남긴다 — 나중에 잘못 쪼갠 게 발견되면
        # 이 값으로 되돌릴 수 있다. 손대지 않은 논문에까지 넣으면 산출물만 커진다.
        detail["keywordsRaw"] = raw
    if stale:
        # 손질 대상인데 원본이 달라진 논문 — 덮어쓰지 않았다는 사실을 함께 들고 다닌다
        detail["keywordFixStale"] = stale
    return detail


def reprocess_detail(kci_id, detail):
    """캐시에 저장된 상세를 **현재 규칙으로 다시 계산한다** (API 재호출 없이).

    캐시에는 파싱이 끝난 값이 들어 있어서, 정제 규칙이나 KEYWORD_FIXES가 바뀌면
    옛 결과가 그대로 남는다. 원본(keywordsRaw, 없으면 손대지 않았다는 뜻이므로 keywords)에서
    다시 계산하면 재호출 없이 새 규칙을 전체에 적용할 수 있다.
    """
    raw = detail.get("keywordsRaw") or detail["keywords"]
    flat = list(raw.get("ko") or []) + list(raw.get("en") or [])

    rebuilt = dict(detail)
    raw_split = split_keywords(flat, unpack=False)
    final, stale = apply_keyword_fix(kci_id, split_keywords(flat), raw_split)
    rebuilt["keywords"] = final
    if raw_split != final:
        rebuilt["keywordsRaw"] = raw_split
    else:
        rebuilt.pop("keywordsRaw", None)
    if stale:
        rebuilt["keywordFixStale"] = stale
    else:
        rebuilt.pop("keywordFixStale", None)
    return rebuilt


def reprocess_cache(details):
    """캐시 전체를 현재 규칙으로 다시 계산하고, 바뀐 편수를 알린다."""
    changed = 0
    for kci_id, detail in list(details.items()):
        rebuilt = reprocess_detail(kci_id, detail)
        if rebuilt != detail:
            details[kci_id] = rebuilt
            changed += 1
    if changed:
        print(f"캐시 재처리: 현재 규칙으로 {changed}편의 키워드를 다시 계산했습니다 (API 재호출 없음)")
    return changed


def record_keyword_fixes(state, details):
    """손질·미적용·의심 값을 review에 남긴다 — 조용히 사라지거나 묻히지 않게.

    - keywordFixes      : 실제로 손질한 논문
    - keywordFixStale   : 지목은 돼 있으나 원본이 달라져 **손대지 않은** 논문 (사람이 재확인)
    - keywordFixMissing : 지목한 논문이 수집 대상에 없어 **적용된 적이 없는** 항목
    - keywordSuspect    : 자동 정제 뒤에도 남은 오염 의심 값 (지우지 않고 기록만)

    missing을 따로 남기는 이유: 사람이 등록한 개입이 조용히 무효가 되면 안 된다.
    논문이 산출물에서 빠졌거나 kciId를 잘못 적었을 때 이 목록으로 드러난다.
    """
    review = state.setdefault("review", {})

    entries, stale, missing = [], [], []
    for kci_id, fix in KEYWORD_FIXES.items():
        detail = details.get(kci_id)
        if not detail:
            missing.append({
                "kciId": kci_id,
                "reason": "지목한 논문이 수집 결과에 없어 손질이 적용되지 않았습니다 "
                          "— kciId 오타이거나 그 논문이 더 이상 수집되지 않는 것입니다",
                "fixReason": fix["reason"],
            })
            continue
        if "keywordFixStale" in detail:
            stale.append(detail["keywordFixStale"])
            continue
        entries.append({
            "kciId": kci_id,
            "reason": fix["reason"],
            "before": detail.get("keywordsRaw"),
            "after": detail["keywords"],
        })
    review["keywordFixes"] = entries
    review["keywordFixStale"] = stale
    review["keywordFixMissing"] = missing

    suspects = []
    for kci_id, detail in details.items():
        found = detect_suspects(detail["keywords"])
        if found:
            suspects.append({"kciId": kci_id, "suspects": found})
    review["keywordSuspect"] = suspects
    return entries, stale, missing, suspects


# ---------------------------------------------------------------------------
# 호출
# ---------------------------------------------------------------------------

def fetch_detail(api_key, kci_id):
    """논문 1편의 상세를 가져온다. 해당 논문이 없으면 None."""
    params = {"apiCode": API_CODE, "key": api_key, "id": kci_id}
    response = requests.get(fetch_kci.API_URL, params=params, timeout=30)
    response.raise_for_status()
    return parse_detail(response.content, kci_id)


# ---------------------------------------------------------------------------
# 캐시 (재개의 근거) + 산출물 반영
# ---------------------------------------------------------------------------

def load_cache():
    """kciId → 상세. FORCE_REFRESH면 무시하고 새로 시작한다."""
    if not FORCE_REFRESH and CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"기존 캐시 발견: {len(cache.get('details', {}))}편 완료됨 → 이어서 진행 (resume)")
        return cache
    return {"collectedAt": None, "details": {}, "notFound": [], "failed": []}


def save_json(path, payload):
    """임시 파일에 먼저 쓰고 바꿔치기한다 — 저장 도중 끊겨도 기존 파일이 깨지지 않는다.

    윈도우에서 다른 프로그램이 파일을 열고 있으면 교체가 PermissionError로 실패하므로
    잠깐 기다렸다 다시 시도한다 (fetch_kci.save_state와 같은 이유).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    for attempt in range(1, fetch_kci.SAVE_ATTEMPTS + 1):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if attempt == fetch_kci.SAVE_ATTEMPTS:
                print(f"  ! 저장 실패: {path.name}을 다른 프로그램이 열고 있습니다."
                      f" 임시 파일을 남겨 둡니다({tmp_path.name})")
                return
            time.sleep(fetch_kci.SAVE_RETRY_WAIT)


def merge_into_papers(state, details):
    """캐시의 상세를 kci_papers.json의 각 논문에 얹는다. 기존 필드는 건드리지 않는다.

    같은 논문이 여러 교수에게 걸쳐 있으므로(실측 1,069편) 모든 사본에 똑같이 얹는다.
    """
    applied = 0
    for record in state["professors"].values():
        for paper in record.get("papers") or []:
            detail = details.get(paper["kciId"])
            if not detail:
                continue
            paper["keywords"] = detail["keywords"]
            paper["articleCategories"] = detail["articleCategories"]
            paper["articleLanguage"] = detail["articleLanguage"]
            paper["authors"] = detail["authors"]
            if "keywordsRaw" in detail:      # 뭉쳐 온 키워드를 쪼갠 논문만 원본을 남긴다
                paper["keywordsRaw"] = detail["keywordsRaw"]
            else:
                paper.pop("keywordsRaw", None)
            applied += 1
    return applied


# ---------------------------------------------------------------------------

def print_summary(details, not_found, failed, elapsed_seconds, run_count):
    """사람이 검수할 수 있게 누적 통계를 요약한다."""
    ko_only = en_only = both = none = 0
    for detail in details.values():
        has_ko = bool(detail["keywords"]["ko"])
        has_en = bool(detail["keywords"]["en"])
        if has_ko and has_en:
            both += 1
        elif has_ko:
            ko_only += 1
        elif has_en:
            en_only += 1
        else:
            none += 1

    print("\n===== 누적 현황 =====")
    print(f"상세 확보: {len(details)}편")
    print(f"키워드 있는 논문: {len(details) - none}편 "
          f"(한글만 {ko_only} · 영문만 {en_only} · 둘 다 {both})")
    print(f"키워드 없는 논문: {none}편")
    total_ko = sum(len(d["keywords"]["ko"]) for d in details.values())
    total_en = sum(len(d["keywords"]["en"]) for d in details.values())
    print(f"키워드 총합: 한글 {total_ko}개 · 영문 {total_en}개")
    with_cat = sum(1 for d in details.values() if d["articleCategories"])
    with_orcid = sum(1 for d in details.values() if any(a["orcid"] for a in d["authors"]))
    print(f"연구분야 있는 논문: {with_cat}편 · ORCID 있는 논문: {with_orcid}편")
    if not_found:
        print(f"해당 논문 없음(KCI가 No Data 응답): {len(not_found)}편 — {not_found[:5]}")
    if failed:
        print(f"조회 실패: {len(failed)}편 — 재실행하면 자동으로 다시 시도됩니다")
        for item in failed[:5]:
            print(f"  · {item['kciId']}: {item['reason'][:100]}")
    print(f"이번 실행: {run_count}편 · {elapsed_seconds:.0f}초")
    print(f"저장 위치: {OUTPUT_PATH}")


def main():
    api_key = fetch_kci.read_kci_api_key()

    if not OUTPUT_PATH.exists():
        print(f"기존 KCI 산출물이 없습니다: {OUTPUT_PATH}\n"
              "먼저 scripts/kci_collector/fetch_kci.py 로 논문을 수집해 주세요.")
        sys.exit(1)
    with open(OUTPUT_PATH, encoding="utf-8") as f:
        state = json.load(f)

    # 같은 논문이 여러 교수에게 걸쳐 있으므로 kciId 기준으로 한 번만 부른다
    kci_ids = list(dict.fromkeys(
        paper["kciId"]
        for record in state["professors"].values()
        for paper in (record.get("papers") or [])
        if paper.get("kciId")
    ))
    if LIMIT is not None:
        kci_ids = kci_ids[:LIMIT]
        print(f"LIMIT={LIMIT}: 앞 {len(kci_ids)}편만 처리합니다 (검증용)")

    cache = load_cache()
    details = cache["details"]
    # 정제 규칙·KEYWORD_FIXES가 바뀌었을 수 있다 — 캐시를 현재 규칙으로 다시 계산한다.
    # 원본(keywordsRaw)에서 계산하므로 API를 다시 부르지 않는다.
    if reprocess_cache(details):
        save_json(CACHE_PATH, cache)
    not_found = cache.setdefault("notFound", [])
    failed = cache.setdefault("failed", [])

    todo = [k for k in kci_ids if k not in details and k not in not_found]
    print(f"대상: 유니크 논문 {len(kci_ids)}편 (이미 확보 {len(kci_ids) - len(todo)}편 · 조회할 {len(todo)}편)")
    print(f"예상 소요: 약 {len(todo) * SLEEP_SECONDS / 60:.0f}분")

    started = time.monotonic()
    run_count = 0
    for index, kci_id in enumerate(todo, 1):
        failed[:] = [f for f in failed if f["kciId"] != kci_id]   # 옛 실패 기록은 갈아끼운다
        time.sleep(SLEEP_SECONDS)
        try:
            detail = fetch_kci.call_with_retry(
                f"KCI 상세({kci_id})", lambda: fetch_detail(api_key, kci_id)
            )
        except fetch_kci.KciApiError as exc:
            # 인증키 오류 등 — 모든 논문에서 똑같이 나므로 즉시 멈춘다
            print(f"\nKCI가 오류를 돌려줬습니다: {fetch_kci._mask_secrets(str(exc))}")
            print("인증키·서비스 IP를 확인해 주세요. 여기까지는 캐시에 저장돼 있습니다.")
            break
        except fetch_kci.RETRYABLE_ERRORS as exc:
            reason = fetch_kci._mask_secrets(fetch_kci._describe_error(exc))
            print(f"  ! {kci_id} 조회 실패({reason[:80]}) — 건너뛰고 계속")
            failed.append({"kciId": kci_id, "reason": reason})
            save_json(CACHE_PATH, cache)
            continue

        if detail is None:
            not_found.append(kci_id)
            print(f"  ! {kci_id}: KCI에 해당 논문 없음(No Data)")
        else:
            details[kci_id] = detail
            run_count += 1
            counts = detail["keywords"]
            if index <= 5 or index % 100 == 0:
                print(f"[{index}/{len(todo)}] {kci_id}: 키워드 "
                      f"한글 {len(counts['ko'])} · 영문 {len(counts['en'])}"
                      f" · 분야 {detail['articleCategories']} · 언어 {detail['articleLanguage']}")

        cache["collectedAt"] = date.today().isoformat()
        save_json(CACHE_PATH, cache)      # 논문 1편마다 즉시 저장 — 끊겨도 이어서 돈다

        if index % MERGE_EVERY == 0:
            merge_into_papers(state, details)
            save_json(OUTPUT_PATH, state)
            print(f"  → 중간 반영: {OUTPUT_PATH.name} ({index}/{len(todo)}편)")

    applied = merge_into_papers(state, details)
    fixes, stale, missing, suspects = record_keyword_fixes(state, details)
    # 조회 실패도 산출물의 review에 남긴다 — 캐시에만 있으면 산출물만 보는 사람은 알 수 없다
    state.setdefault("review", {})["detailFailed"] = list(failed)
    save_json(OUTPUT_PATH, state)
    print(f"\nkci_papers.json에 반영: 논문 항목 {applied}개 (사본 포함)")
    if fixes:
        print(f"오염 키워드 손질: {len(fixes)}편 (review.keywordFixes 참고)")
    if stale:
        print(f"손질 미적용(원본이 달라짐): {len(stale)}편 — review.keywordFixStale 확인 필요")
    if missing:
        print(f"손질 대상이 수집 결과에 없음: {len(missing)}편 "
              f"({', '.join(m['kciId'] for m in missing)}) — review.keywordFixMissing 확인 필요")
    if suspects:
        print(f"오염 의심 값: {sum(len(x['suspects']) for x in suspects)}개"
              f" / {len(suspects)}편 (review.keywordSuspect — 지우지 않고 기록만)")
    print_summary(details, not_found, failed, time.monotonic() - started, run_count)


if __name__ == "__main__":
    main()
