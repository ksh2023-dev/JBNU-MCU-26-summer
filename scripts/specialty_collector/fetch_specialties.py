"""전북대병원 교수 프로필 페이지에서 전문진료분야(specialties)를 수집하는 스크립트.

- 입력: data/input/professor_pages.json  (교수 한글명 → 프로필 페이지 URL)
- 출력: data/output/specialties.json     (교수 한글명 → { raw, specialties })

probe 결과 (2026-08-16, 실제 페이지 3개 + 표본 8개 총 11개의 HTML을 사전 확인해 결정):
- "전문진료분야"는 <div class="infoBox ib1"> 블록에 정적 HTML로 들어 있다.
  (자바스크립트 렌더링 아님 → 표준 라이브러리로 파싱 가능)
  구조:
    <div class="infoBox ib1">
        <div class="info-title icon"><strong class="tit">...전문진료분야</strong></div>
        <div class="info-con"><p class="conText"> 간담도, 췌장질환, 이식외과, ... </p></div>
    </div>
- 확인한 11개 페이지 전부에서 항목 구분자는 쉼표(,) 하나만 사용했다. 가운뎃점(·)은
  발견되지 않았지만, 지시서에 언급된 만큼 안전하게 쉼표·가운뎃점 둘 다 구분자로 처리한다.
- 공백은 항목마다 제각각(공백 없음/한 칸/두 칸)이라 분리 후 strip으로 정리한다.
- "전문진료분야" 블록 자체가 없는 페이지도 있을 수 있다 → 그 경우 raw=None, specialties=[].
- LIMIT=10 실측 뒤 전체(243명) 1차 실행 결과를 검수하다가, "관절(어깨,무릎)통증"처럼
  괄호 안에도 쉼표를 쓰는 사례가 다수 있어 단순 split이 "관절(어깨" / "무릎)통증"으로
  괄호를 깨뜨리는 문제를 발견했다 → 괄호(원문에 있는 종류는 ( )·[ ] 두 가지) 안의
  구분자는 무시하도록 split_specialties()에서 depth를 세어 처리한다.
"""

# ── 설정 ─────────────────────────────────────────────────────────
# 개발·테스트용 인원 제한: None이면 전체(243명), 숫자(예: 10)를 넣으면 앞 N명만 처리
LIMIT = None

import json
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

# 경로는 이 스크립트의 위치 기준으로 계산한다 → 어느 폴더에서 실행해도 동일하게 동작
ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "data" / "input" / "professor_pages.json"
OUTPUT_PATH = ROOT / "data" / "output" / "specialties.json"

SLEEP_SECONDS = 0.5      # 서버 예절: 호출 사이 대기 시간 (운영 중인 병원 서버 → 병렬 금지)
TIMEOUT_SECONDS = 15     # 응답을 기다리는 최대 시간
# 파이썬 기본 User-Agent는 사이트에서 차단될 수 있어 일반 브라우저 값을 사용
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# "전문진료분야" 블록의 <p class="conText"> 안 내용을 뽑는 정규식 (probe로 확인한 구조)
SPECIALTY_PATTERN = re.compile(
    r'전문진료분야.*?<p class="conText">(.*?)</p>', re.S
)
# 항목 구분자: 쉼표 또는 가운뎃점
SEPARATOR_CHARS = ",·"
# 괄호 쌍 (여는 문자 → 닫는 문자) — 괄호 안의 구분자는 항목을 나누지 않는다
BRACKET_PAIRS = {"(": ")", "[": "]"}
BRACKET_CLOSERS = set(BRACKET_PAIRS.values())


def split_specialties(raw_text):
    """구분자로 나누되, 괄호 안의 구분자는 무시한다.

    예: "관절(어깨,무릎)통증, 척추질환" → ["관절(어깨,무릎)통증", "척추질환"]
    (괄호 안의 쉼표까지 나눠 버리면 "관절(어깨"처럼 괄호가 깨진 항목이 생긴다 — probe 후 발견)
    """
    parts = []
    buf = []
    depth = 0
    for ch in raw_text:
        if ch in BRACKET_PAIRS:
            depth += 1
            buf.append(ch)
        elif ch in BRACKET_CLOSERS:
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in SEPARATOR_CHARS and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


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
    match = SPECIALTY_PATTERN.search(html)
    if match is None:
        return None, []

    raw_text = re.sub(r"\s+", " ", match.group(1)).strip()
    if not raw_text:
        return None, []

    specialties = split_specialties(raw_text)
    return raw_text, specialties


def main():
    # 1) 입력 파일 읽기
    with open(INPUT_PATH, encoding="utf-8") as f:
        pages = json.load(f)

    items = list(pages.items())
    if LIMIT is not None:
        items = items[:LIMIT]  # 개발·테스트용으로 앞 N명만

    total = len(items)
    print(f"수집 시작: {total}명 처리 (입력 전체 {len(pages)}명, LIMIT={LIMIT})")

    specialties_result = {}
    collected = empty = failed = 0

    # 2) 한 명씩 페이지를 가져와 전문진료분야 추출
    for index, (name, url) in enumerate(items, start=1):
        html = fetch_html(url)
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
            print(f"  진행: {index}/{total} (수집 {collected} / 빈 값 {empty} / 요청 실패 {failed})")

        # 서버 예절: 마지막 호출 뒤에는 기다릴 필요 없음
        if index < total:
            time.sleep(SLEEP_SECONDS)

    # 3) 결과 저장 (계약의 collectedAt 형식 "YYYY-MM-DD"와 동일)
    result = {
        "collectedAt": date.today().isoformat(),
        "specialties": specialties_result,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 4) 종료 통계
    print("=" * 60)
    print(f"완료: 수집 {collected} / 빈 값 {empty} / 요청 실패 {failed}  (총 {total}명)")
    print(f"저장 위치: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
