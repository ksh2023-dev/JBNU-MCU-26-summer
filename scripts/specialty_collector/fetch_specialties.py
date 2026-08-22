"""전북대병원 교수 프로필 페이지에서 전문진료분야(specialties)를 수집하는 스크립트.

- 입력: data/input/professor_pages.json  (교수 한글명 → 프로필 페이지 URL)
- 출력: data/output/specialties.json     (교수 한글명 → { raw, specialties })

전문진료분야 판별 기준 (2026-08-16, 실제 페이지 11개의 HTML을 사전 확인해 결정):
- 전문진료분야는 <div class="infoBox ib1"> 블록에 정적 HTML로 들어 있다.
  (자바스크립트 렌더링 아님 → 표준 라이브러리 HTMLParser로 파싱 가능)

    <div class="infoBox ib1">
        <div class="info-title icon"><strong class="tit"><i ...></i> 전문진료분야</strong></div>
        <div class="info-con"><p class="conText"> 간담도, 췌장질환, 이식외과, ... </p></div>
    </div>

- 같은 페이지의 탭메뉴·breadcrumb에도 "전문진료분야"라는 문자열이 따로 등장하고,
  뒤따르는 다른 섹션(infoBox ib2 = 외래진료일정 등)에도 <p class="conText">가 또 있다.
  그래서 "문자열을 찾고 그 뒤의 conText를 가져오는" 방식은, 실제 블록이 없는 페이지에서
  엉뚱한 섹션의 내용을 교수의 전문진료분야로 집어온다.
  → infoBox ib1 블록 안에 들어왔을 때만 conText 텍스트를 모은다.
- 블록의 제목(<strong class="tit">)이 실제로 "전문진료분야"인지도 함께 확인한다.
  블록이 없거나 제목이 다르면 (None, []) — 지어내지 않는다 (데이터 계약 0장 원칙 2).

정리 규칙:
- HTML 엔티티는 html.unescape()로 디코딩한다 (&amp; · &nbsp; · &middot;).
  특히 가운뎃점을 &middot;로 쓴 페이지는 디코딩하지 않으면 항목 분리 자체가 무효가 된다.
- conText 안의 태그는 텍스트만 남기되, <br>은 버리지 않고 구분자(", ")로 치환한다.
  그냥 버리면 "심장질환<br>부정맥"이 "심장질환부정맥" 한 덩어리가 된다.
- 항목 구분자는 쉼표(,)와 가운뎃점(·). 단 괄호 안의 구분자는 항목을 나누지 않는다.
  ("관절(어깨,무릎)통증"을 "관절(어깨" / "무릎)통증"으로 쪼개지 않기 위함)
- raw는 위 규칙으로 평문화한 conText 문자열이다. 원문의 <br>은 raw에서 ", "로 보인다.
"""

# ── 설정 ─────────────────────────────────────────────────────────
# 개발·테스트용 인원 제한: None이면 전체(243명), 숫자(예: 10)를 넣으면 앞 N명만 처리
LIMIT = None
# run_all.py --limit N 스모크 테스트용 — 환경변수가 있으면 위 LIMIT보다 우선한다
import os as _os
if _os.environ.get("PIPELINE_LIMIT"):
    LIMIT = int(_os.environ["PIPELINE_LIMIT"])


import hashlib
import json
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

# 경로는 이 스크립트의 위치 기준으로 계산한다 → 어느 폴더에서 실행해도 동일하게 동작
ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "data" / "input" / "professor_pages.json"
OUTPUT_PATH = ROOT / "data" / "output" / "specialties.json"

# 페이지 HTML 캐시 — 2단계(프로필 사진)가 '같은' 프로필 페이지를 먼저 읽고 남긴 HTML을 재사용한다.
# 파이프라인에서 2단계 직후에 돌면 재요청 없이 몇 초 만에 끝난다 (병원 서버 부하도 절반).
# 신선도 한도를 넘긴 캐시는 쓰지 않는다 — 오래된 페이지로 전문진료분야를 갱신하는 일을 막는다.
# 캐시에 없거나 오래된 교수만 직접 요청하고, 그 HTML은 캐시에 다시 남긴다.
USE_PAGE_CACHE = True
CACHE_MAX_AGE_HOURS = 24
CACHE_DIR = ROOT / "data" / "output" / "_cache_profile_pages"

SLEEP_SECONDS = 0.5      # 서버 예절: 호출 사이 대기 시간 (운영 중인 병원 서버 → 병렬 금지)
TIMEOUT_SECONDS = 15     # 응답을 기다리는 최대 시간
# 파이썬 기본 User-Agent는 사이트에서 차단될 수 있어 일반 브라우저 값을 사용
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
SOURCE = "https://www.jbuh.co.kr 교수 프로필 페이지"

# 전문진료분야 블록을 식별하는 class 조합과 제목 문구
BLOCK_CLASSES = ("infoBox", "ib1")
BLOCK_TITLE = "전문진료분야"
# <br>을 대신할 구분자 — 줄바꿈으로 나뉜 항목이 서로 붙지 않게 한다
BR_SEPARATOR = ", "

# 항목 구분자: 쉼표 또는 가운뎃점
SEPARATOR_CHARS = ",·"
# 괄호 쌍 — 여는 문자 → 짝이 되는 닫는 문자. 괄호 안의 구분자는 항목을 나누지 않는다
BRACKET_PAIRS = {"(": ")", "[": "]"}


class SpecialtyCollector(HTMLParser):
    """전문진료분야 블록(infoBox ib1)의 제목과 conText 텍스트만 모으는 파서.

    블록 밖의 conText(외래진료일정 등 다른 섹션)는 무시한다.
    블록 안에서만 텍스트를 모으기 위해 <div> 중첩 깊이를 직접 센다.
    """

    def __init__(self):
        super().__init__()
        self.found_block = False   # infoBox ib1 블록을 실제로 만났는가
        self.title_chunks = []     # 블록 제목(<strong class="tit">) 텍스트
        self.text_chunks = []      # 블록 안 <p class="conText"> 텍스트
        self._div_depth = 0        # 블록 안에서의 <div> 중첩 깊이 (0이면 블록 밖)
        self._in_title = False     # 지금 블록의 <strong class="tit"> 안인가
        self._in_context = False   # 지금 블록의 <p class="conText"> 안인가

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()

        if tag == "div":
            if self._div_depth > 0:
                self._div_depth += 1  # 이미 블록 안 → 중첩 깊이만 센다
            elif all(name in classes for name in BLOCK_CLASSES):
                self._div_depth = 1   # 블록 진입
                self.found_block = True
        elif self._div_depth > 0:
            # 아래 세 가지는 블록 안에서만 의미가 있다
            if tag == "strong" and "tit" in classes:
                self._in_title = True
            elif tag == "p" and "conText" in classes:
                self._in_context = True
            elif tag == "br" and self._in_context:
                self.text_chunks.append(BR_SEPARATOR)

    def handle_endtag(self, tag):
        if tag == "strong":
            self._in_title = False
        elif tag == "p":
            self._in_context = False
        elif tag == "div" and self._div_depth > 0:
            self._div_depth -= 1
            if self._div_depth == 0:
                # 블록을 빠져나왔다 → 이후 conText는 다른 섹션이므로 모으지 않는다
                self._in_title = self._in_context = False

    def handle_data(self, data):
        if self._in_title:
            self.title_chunks.append(data)
        elif self._in_context:
            self.text_chunks.append(data)

    def has_specialty_block(self):
        """전문진료분야 블록을 제대로 찾았는지 (블록 존재 + 제목 일치)."""
        return self.found_block and BLOCK_TITLE in normalize_text("".join(self.title_chunks))


def normalize_text(text):
    """HTML 엔티티를 디코딩하고 연속 공백을 한 칸으로 정리한다."""
    text = unescape(text)             # &amp; · &nbsp; · &middot; 디코딩
    text = text.replace("\xa0", " ")  # &nbsp;가 남긴 비줄바꿈 공백 → 일반 공백
    return re.sub(r"\s+", " ", text).strip()


def split_specialties(raw_text):
    """구분자로 나누되, 괄호 안의 구분자는 무시한다.

    예: "관절(어깨,무릎)통증, 척추질환" → ["관절(어깨,무릎)통증", "척추질환"]
    (괄호 안의 쉼표까지 나눠 버리면 "관절(어깨"처럼 괄호가 깨진 항목이 생긴다)

    여는 괄호는 짝이 맞는 닫는 괄호로만 닫힌다. 짝이 맞지 않으면("A(B]C") 괄호가
    열린 상태로 남아 그 뒤를 나누지 않는다 — 애매할 때는 쪼개지 않는 쪽이 안전하다.
    """
    parts = []
    buf = []
    expected_closers = []  # 아직 닫히지 않은 괄호의 닫는 문자 (스택)

    for ch in raw_text:
        if ch in BRACKET_PAIRS:
            expected_closers.append(BRACKET_PAIRS[ch])
            buf.append(ch)
        elif expected_closers and ch == expected_closers[-1]:
            expected_closers.pop()
            buf.append(ch)
        elif ch in SEPARATOR_CHARS and not expected_closers:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)

    parts.append("".join(buf).strip())
    return [p for p in parts if p]  # 빈 조각 제거


def fetch_html(url):
    """URL의 HTML 문자열을 가져온다. 실패하면 1회 재시도, 그래도 실패하면 None.

    실패해도 예외를 밖으로 던지지 않는다 → 한 명이 실패해도 전체 실행은 계속된다.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as error:
            print(f"    요청 실패 (시도 {attempt}/2): {error}")
            if attempt == 1:
                time.sleep(SLEEP_SECONDS)  # 재시도 전 잠깐 대기
    return None


def extract_specialties(html):
    """페이지 HTML에서 전문진료분야 원본 문자열(raw)과 분리한 배열(specialties)을 반환한다.

    항목이 없으면 (None, []) — 지어내지 않는다 (데이터 계약 0장 원칙 2).
    """
    parser = SpecialtyCollector()
    parser.feed(html)
    parser.close()

    if not parser.has_specialty_block():
        return None, []  # 블록 자체가 없음 → 다른 섹션을 대신 집어오지 않는다

    raw_text = normalize_text("".join(parser.text_chunks))
    specialties = split_specialties(raw_text)
    if not specialties:
        return None, []  # 블록은 있으나 내용이 비어 있음

    return raw_text, specialties


def load_cache_index():
    """캐시 색인을 읽는다. 없거나 깨졌으면 빈 색인 — 캐시는 없어도 되는 부산물이다."""
    try:
        with open(CACHE_DIR / "index.json", encoding="utf-8") as f:
            return json.load(f).get("pages") or {}
    except (OSError, ValueError):
        return {}


def cached_html(cache_index, name, url):
    """캐시에서 이 교수의 최신 HTML을 꺼낸다. 못 쓰는 캐시(URL 다름·오래됨·파일 없음)면 None."""
    entry = cache_index.get(name)
    if not entry or entry.get("url") != url:
        return None
    try:
        fetched_at = datetime.fromisoformat(entry.get("fetchedAt") or "")
    except ValueError:
        return None
    if datetime.now() - fetched_at > timedelta(hours=CACHE_MAX_AGE_HOURS):
        return None  # 신선도 초과 — 오래된 페이지로 갱신하지 않는다
    try:
        return (CACHE_DIR / entry["file"]).read_text(encoding="utf-8")
    except OSError:
        return None


def save_page_cache(cache_index, name, url, html):
    """직접 가져온 HTML도 캐시에 남긴다. 실패해도 수집은 계속한다."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        file_name = hashlib.md5(name.encode("utf-8")).hexdigest() + ".html"
        (CACHE_DIR / file_name).write_text(html, encoding="utf-8")
        cache_index[name] = {
            "url": url,
            "fetchedAt": datetime.now().isoformat(timespec="seconds"),
            "file": file_name,
        }
        (CACHE_DIR / "index.json").write_text(
            json.dumps({
                "_comment": "프로필 페이지 HTML 캐시 색인 — 2단계가 쓰고 3단계가 읽는다. 지워도 무해(재조회).",
                "pages": cache_index,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        print(f"    캐시 저장 실패(무시하고 계속): {error}")


def main():
    # 1) 입력 파일 읽기
    with open(INPUT_PATH, encoding="utf-8") as f:
        pages = json.load(f)

    items = list(pages.items())
    if LIMIT is not None:
        items = items[:LIMIT]  # 개발·테스트용으로 앞 N명만

    total = len(items)
    cache_index = load_cache_index() if USE_PAGE_CACHE else {}
    print(f"수집 시작: {total}명 처리 (입력 전체 {len(pages)}명, LIMIT={LIMIT}, "
          f"페이지 캐시 {len(cache_index)}건 보유)")

    specialties_result = {}
    collected = empty = failed = cache_hits = 0

    # 2) 한 명씩 페이지를 확보(캐시 → 직접 요청)해 전문진료분야 추출
    for index, (name, url) in enumerate(items, start=1):
        html = cached_html(cache_index, name, url) if USE_PAGE_CACHE else None
        from_cache = html is not None
        if from_cache:
            cache_hits += 1
        else:
            html = fetch_html(url)
            if html is not None and USE_PAGE_CACHE:
                save_page_cache(cache_index, name, url, html)

        if html is None:
            specialties_result[name] = {"raw": None, "specialties": []}
            failed += 1
            print(f"  [{index}/{total}] {name}: 요청 실패 → raw=None, specialties=[]")
        else:
            raw_text, specialties = extract_specialties(html)
            specialties_result[name] = {"raw": raw_text, "specialties": specialties}
            if specialties:
                collected += 1
            else:
                empty += 1

        # 10명 단위 진행 상황 출력
        if index % 10 == 0:
            print(f"  진행: {index}/{total} (수집 {collected} / 빈 값 {empty} / 요청 실패 {failed} "
                  f"/ 캐시 재사용 {cache_hits})")

        # 서버 예절: 실제로 서버를 부른 경우에만 기다린다 (캐시 재사용은 대기 불필요)
        if not from_cache and index < total:
            time.sleep(SLEEP_SECONDS)

    # 3) 결과 저장 (계약의 collectedAt 형식 "YYYY-MM-DD"와 동일)
    result = {
        "collectedAt": date.today().isoformat(),
        "source": SOURCE,
        "specialties": specialties_result,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 4) 종료 통계
    print("=" * 60)
    print(f"완료: 수집 {collected} / 빈 값 {empty} / 요청 실패 {failed}  (총 {total}명, "
          f"캐시 재사용 {cache_hits} / 직접 요청 {total - cache_hits})")
    print(f"저장 위치: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
