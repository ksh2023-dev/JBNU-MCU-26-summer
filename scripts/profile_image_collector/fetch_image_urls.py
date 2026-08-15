"""전북대병원 교수 프로필 페이지에서 프로필 사진의 URL만 수집하는 스크립트.

- 입력: data/input/professor_pages.json  (교수 한글명 → 프로필 페이지 URL)
- 출력: data/output/profile_images.json  (교수 한글명 → 사진 절대 URL 또는 null)
- 이미지 파일 자체는 다운로드하지 않는다. URL 문자열만 수집한다.

사진 판별 기준 (2026-08-15, 실제 페이지 3개의 HTML을 사전 확인해 결정):
- 교수 본인 사진은  <img src="/thumbnail/mdclStf/MS....PNG" alt="{교수명} 대표 이미지">  형태로
  정적 HTML에 들어 있다. (자바스크립트 렌더링 아님 → 표준 라이브러리로 파싱 가능)
- 같은 페이지에 placeholder(/images/prog/no-img.png), 타 교수 배너(/images/prog/doctor-img01.png),
  사이트 공통 로고(/images/common/...)가 섞여 있으므로,
  "src에 /thumbnail/mdclStf/ 경로가 있고 + alt에 교수명이 포함된 것"만 본인 사진으로 인정한다.
- 조건에 맞는 이미지가 없으면 null로 기록한다. (데이터 계약 0장 원칙 2 — 값을 지어내지 않는다)
"""

# ── 설정 ─────────────────────────────────────────────────────────
# 개발·테스트용 인원 제한: None이면 전체(243명), 숫자(예: 10)를 넣으면 앞 N명만 처리
LIMIT = None

import json
import time
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

# 경로는 이 스크립트의 위치 기준으로 계산한다 → 어느 폴더에서 실행해도 동일하게 동작
ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "data" / "input" / "professor_pages.json"
OUTPUT_PATH = ROOT / "data" / "output" / "profile_images.json"

SLEEP_SECONDS = 0.5      # 서버 예절: 호출 사이 대기 시간
TIMEOUT_SECONDS = 15     # 응답을 기다리는 최대 시간
# 파이썬 기본 User-Agent는 사이트에서 차단될 수 있어 일반 브라우저 값을 사용
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 교수 본인 사진(실제 업로드 사진)만 갖는 경로 조각 — 소문자로 비교
PHOTO_PATH_MARKER = "/thumbnail/mdclstf/"


class ImgCollector(HTMLParser):
    """HTML 문서에서 모든 <img> 태그의 src·alt 속성만 모으는 파서 (표준 라이브러리)."""

    def __init__(self):
        super().__init__()
        self.images = []  # (src, alt) 튜플 목록

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            attr = dict(attrs)
            self.images.append((attr.get("src") or "", attr.get("alt") or ""))


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


def extract_photo_url(html, page_url, name):
    """페이지 HTML에서 교수 본인 사진의 절대 URL을 찾는다. 없으면 None.

    판별 조건 두 가지를 모두 만족해야 본인 사진으로 인정한다.
    1) src 경로에 /thumbnail/mdclStf/ 포함  → placeholder·공통 로고 제외
    2) alt에 교수명 포함                    → 페이지에 섞여 있는 타 교수 이미지 제외
    """
    parser = ImgCollector()
    parser.feed(html)
    parser.close()
    for src, alt in parser.images:
        absolute_url = urljoin(page_url, src)  # 상대 경로("/thumbnail/...")를 절대 URL로 변환
        if PHOTO_PATH_MARKER in absolute_url.lower() and name in alt:
            return absolute_url
    return None  # 사진이 없거나 placeholder뿐 → null (원칙 2 — 지어내지 않는다)


def main():
    # 1) 입력 파일 읽기
    with open(INPUT_PATH, encoding="utf-8") as f:
        pages = json.load(f)

    items = list(pages.items())
    if LIMIT is not None:
        items = items[:LIMIT]  # 개발·테스트용으로 앞 N명만

    total = len(items)
    print(f"수집 시작: {total}명 처리 (입력 전체 {len(pages)}명, LIMIT={LIMIT})")

    images = {}
    success = no_photo = failed = 0

    # 2) 한 명씩 페이지를 가져와 사진 URL 추출
    for index, (name, url) in enumerate(items, start=1):
        html = fetch_html(url)
        if html is None:
            images[name] = None  # 요청 실패 → null로 기록하고 계속 진행
            failed += 1
            print(f"  [{index}/{total}] {name}: 요청 실패 → null")
        else:
            photo_url = extract_photo_url(html, url, name)
            images[name] = photo_url  # 사진 없음(placeholder 포함)도 null
            if photo_url is not None:
                success += 1
            else:
                no_photo += 1

        # 10명 단위 진행 상황 출력
        if index % 10 == 0:
            print(f"  진행: {index}/{total} (성공 {success} / 사진 없음 {no_photo} / 요청 실패 {failed})")

        # 서버 예절: 마지막 호출 뒤에는 기다릴 필요 없음
        if index < total:
            time.sleep(SLEEP_SECONDS)

    # 3) 결과 저장 (계약의 collectedAt 형식 "YYYY-MM-DD"와 동일)
    result = {
        "collectedAt": date.today().isoformat(),
        "source": "https://www.jbuh.co.kr 교수 프로필 페이지",
        "images": images,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 4) 종료 통계
    print("=" * 60)
    print(f"완료: 성공 {success} / 사진 없음 {no_photo} / 요청 실패 {failed}  (총 {total}명)")
    print(f"저장 위치: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
