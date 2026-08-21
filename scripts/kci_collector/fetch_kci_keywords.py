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

def _article_info(root):
    """응답에서 articleInfo 요소를 찾는다. 없으면 None.

    referenceInfo(참고문헌)는 형제라 여기에 딸려 오지 않는다 — 파싱 범위를 좁히는 핵심이다.
    """
    return next(iter(fetch_kci._iter_by_tag(root, "articleinfo")), None)


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
#
# 원본은 keywordsRaw에 보존하고, 실행할 때마다 review.keywordFixes에도 기록한다.
# ---------------------------------------------------------------------------
KEYWORD_FIXES = {
    "ART001005699": {
        "clearAll": True,
        "reason": "키워드 자리 전체가 학술지 앞부속으로 오염됐다 — "
                  "'2003 217Received ：April 4' · '2003 Accepted ：June 3' · "
                  "'2003Address for reprints ：Ha-Young Choi' · 'M.D.' · "
                  "'Department ofNeurosurgery' · 'Research Institute for Clinical Me'. "
                  "쓸 수 있는 키워드가 하나도 없어 비운다",
    },
    "ART000872261": {
        "clearAll": True,
        "reason": "키워드 자리에 참고문헌이 통째로 들어왔다 — "
                  "'Flyer DC. Report of the New England Regional Infant Cardiac Program. "
                  "Pediatrics 1980;64:432-6' · 'James SD. Repair of Aneurysm Aortic "
                  "Coarctation … Ann Thorac Surg 2001' 등. 비운다",
    },
    "ART001224869": {
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


def apply_keyword_fix(kci_id, keywords):
    """KEYWORD_FIXES에 지목된 논문이면 손질한 키워드를, 아니면 받은 그대로 돌려준다."""
    fix = KEYWORD_FIXES.get(kci_id)
    if not fix:
        return keywords
    if fix.get("clearAll"):
        return {"ko": [], "en": []}
    keep = fix.get("keep", {})
    return {lang: list(keep[lang]) if lang in keep else list(keywords[lang])
            for lang in ("ko", "en")}


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


def split_keywords(keywords, unpack=True):
    """한 리스트로 섞여 온 키워드를 한글/영문으로 나눈다 (순서 유지, 중복 제거).

    KCI는 언어 속성을 주지 않으므로 글자로 가른다 — 한글 음절이 하나라도 있으면 ko다.
    "COVID-19"·"HbA1c" → en, "K-MMSE 검사" → ko.

    unpack=False면 뭉쳐 온 키워드를 쪼개지 않는다 — 원본을 keywordsRaw에 남길 때 쓴다.
    """
    result = {"ko": [], "en": []}
    seen = {"ko": set(), "en": set()}
    for keyword in keywords:
        text = fetch_kci._clean(keyword)
        if not text:
            continue
        for piece in (split_packed(text) if unpack else [text]):
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
    article = _article_info(root)

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

    # 요청한 논문이 맞는지 확인한다 — 다른 논문의 상세를 얹으면 그대로 오귀속이다
    returned_id = fetch_kci._attr(article, "article-id", "articleid")
    if returned_id and returned_id != kci_id:
        raise fetch_kci.KciUnexpectedResponseError(
            f"{kci_id}를 요청했는데 {returned_id} 응답이 왔습니다: {fetch_kci._snippet(xml_bytes)}"
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
    final = apply_keyword_fix(kci_id, split_keywords(keywords))
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
    return detail


def record_keyword_fixes(state, details):
    """손질한 논문을 review.keywordFixes에 남긴다 — 조용히 사라지지 않게."""
    entries = []
    for kci_id, fix in KEYWORD_FIXES.items():
        detail = details.get(kci_id)
        if not detail:
            continue
        entries.append({
            "kciId": kci_id,
            "reason": fix["reason"],
            "before": detail.get("keywordsRaw"),
            "after": detail["keywords"],
        })
    state.setdefault("review", {})["keywordFixes"] = entries
    return entries


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
    fixes = record_keyword_fixes(state, details)
    save_json(OUTPUT_PATH, state)
    print(f"\nkci_papers.json에 반영: 논문 항목 {applied}개 (사본 포함)")
    if fixes:
        print(f"오염 키워드 손질: {len(fixes)}편 (review.keywordFixes 참고)")
    print_summary(details, not_found, failed, time.monotonic() - started, run_count)


if __name__ == "__main__":
    main()
