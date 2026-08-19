"""전북대 의대 홈페이지 교수 명단 크롤러 — 교실/교수 메뉴를 따라 들어가는 2단 수집.

흐름: 허브(교실/교수) 페이지 → 대분류 4개(기초의학·임상의학·의학교육학·인문사회의학)
      → 교실별 하위 페이지(기초 10 · 임상 20여 개 · 의학교육학 · 인문사회의학)
      → (내과학교실처럼 분과 탭이 있으면) 분과 페이지까지 내려가 교수 명단을 수집
      → 기존 병원 기반 명단(data/input/professor_pages.json 243명)과 이름 대조(diff)
      → data/output/roster_crawled.json 저장

[작업지시서-명단크롤러-영문명 + 변경 지시 반영]
- 영문판 사이트에는 교수 명단이 없는 것으로 확인되어(학과 소개만 있음) LIST_URL_EN 기능과
  한↔영 매칭(지시서 3-3)은 이번 범위에서 제외한다. nameEn은 전원 null로 두고,
  추후 논문 저자 정보에서 채운다.
- 대분류(기초의학/임상의학/의학교육학/인문사회의학)를 각 교수의 professorType으로,
  교실 이름을 department로 함께 수집한다.

probe로 확인한 페이지 구조 (2026-08-16):
- 허브·교실 페이지 모두 정적 HTML — requests만으로 수집 가능 (자바스크립트 불필요)
- 메뉴 링크는 GNB·분과 탭 공통으로 <a id="top|tab_k2wiz_GNB_{자기id}"
  class="... k2wiz_GNB_{부모id}">이름<input .../></a> 꼴 → 부모-자식 관계를 복원할 수 있다
- 내과학교실은 분과 8개(감염~호흡기)가 별도 페이지이며, 교실 페이지의 탭 메뉴에만 보인다
- 교수 한 명은 <li class="_prFlLi"> 안에 이름(artclTitle strong, "송창호 교수" 꼴)과
  전공/직위(직급)/전화번호/홈페이지 <dt>/<dd> 쌍으로 들어 있다

데이터 계약 v6.3 0장 원칙을 그대로 따른다:
- 페이지에 없는 값은 지어내지 않고 null로 둔다 (원칙 2)
- 수집 기준일(collectedAt)을 담고, 이름·전공 등 값은 페이지 원문 그대로 둔다 (원칙 4)
- 확신 없는 값은 넣지 않고 review에 기록해 사람이 검수한다
"""

import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests

# ===== 입력 (실행 전 이 부분만 수정하면 됩니다) =================================
LIST_URL_KO = "https://med.jbnu.ac.kr/med/12619/subview.do"   # 교수소개(교실/교수) 허브
# LIST_URL_EN 없음 — 영문판에는 교수 명단이 없어 이번 범위에서 제외 (파일 상단 설명 참고)
LIMIT = None                 # 개발용: 숫자면 앞 N명만 수집하고 중단
# ==============================================================================

# 예절: 운영 중인 학교 홈페이지 — 요청 사이 0.5초, 비동기·병렬 없이 순차 수집
SLEEP_SECONDS = 0.5
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (JBNU-MCU roster crawler; student project)"}

# 입출력 위치: (저장소 루트)/data/… — 어느 폴더에서 실행해도 같은 곳을 읽고 쓴다
ROOT = Path(__file__).resolve().parents[2]
HOSPITAL_LIST_PATH = ROOT / "data" / "input" / "professor_pages.json"
OUTPUT_PATH = ROOT / "data" / "output" / "roster_crawled.json"

# 대분류 교실명 → 데이터 계약 1-1 professorType 값 ("...교실"을 뗀 형태)
# 이 4개에 없는 허브 하위 메뉴(예: "교원 임용 관련 및 임용 후 책무")는 교실이 아니므로 건너뛴다.
GROUP_TO_TYPE = {
    "기초의학교실": "기초의학",
    "임상의학교실": "임상의학",
    "의학교육학교실": "의학교육학",
    "인문사회의학교실": "인문사회의학",
}

# 메뉴 링크(GNB·분과 탭 공통 마크업): id의 top_/tab_ 접두사만 다르고 구조는 같다
MENU_LINK_RE = re.compile(
    r'<a\s+href="([^"]*)"\s+id="(?:top|tab)_k2wiz_GNB_(\d+)"\s+'
    r'class="[^"]*k2wiz_GNB_(\d+)"[^>]*>\s*([^<]+?)\s*<input',
    re.S,
)

# 교수 항목 마크업 (probe로 확인)
PRFL_ITEM_RE = re.compile(r'<li class="_prFlLi[^"]*">(.*?)</li>', re.S)
PRFL_TITLE_RE = re.compile(r'<div class="artclTitle">\s*<strong>(.*?)</strong>', re.S)
PRFL_DL_RE = re.compile(r"<dl>\s*<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
HREF_RE = re.compile(r'href="([^"]+)"')

# 이름 뒤에 붙는 직함 표기 — 직위(직급) 값과 이름을 분리할 때 쓴다
POSITION_SUFFIX_RE = re.compile(
    r"\s*(명예교수|석좌교수|임상교수|초빙교수|객원교수|겸임교수|외래교수|연구교수|부교수|조교수|교수|강사)\s*$"
)

# 병원 프로필 페이지(jbuh.co.kr)에서 "이 사람의" 진료과를 뽑는 마크업.
# probe로 확인: <strong class="mtName">이창훈</strong> <span class="mtPart">소화기내과</span>
# 페이지 안에 이름이 여러 번 나올 수 있어도(사이드바 "의료진 찾기" 목록 등) 이 조합은
# 프로필 본인 것 하나뿐이라 안정적으로 지목할 수 있다.
HOSPITAL_PROFILE_RE = re.compile(r'<strong class="mtName">([^<]+)</strong>\s*<span class="mtPart">([^<]*)</span>')


def strip_tags(html_fragment):
    """태그를 걷어내고 공백을 정리해 순수 텍스트만 남긴다."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_fragment)).strip()


def normalize_name(name):
    """이름 대조용 정규화 — 공백만 없앤다 (병원 명단과 표기 차이 최소화)."""
    return re.sub(r"\s+", "", name)


def fetch_html(url, review, context):
    """페이지 1장을 가져온다. 요청 사이 0.5초, 실패하면 1회 재시도, 그래도 실패면
    review에 기록하고 None을 돌려준다 (전체 수집은 계속 — 지어내지 않고 기록만)."""
    for attempt in (1, 2):
        time.sleep(SLEEP_SECONDS)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as exc:
            if attempt == 1:
                print(f"요청 실패({context}) → 1회 재시도: {type(exc).__name__}")
            else:
                review.append({"page": context, "url": url, "reason": f"요청 실패: {type(exc).__name__}"})
    return None


def parse_menu_links(html):
    """k2wiz 메뉴 링크를 [(자기id, 부모id, href, 이름)] 목록으로 뽑는다."""
    links = []
    for href, self_id, parent_id, title in MENU_LINK_RE.findall(html):
        links.append((self_id, parent_id, href.strip(), re.sub(r"\s+", " ", title).strip()))
    return links


def build_department_list(hub_html, hub_menu_id, review):
    """허브 메뉴에서 대분류 4개 아래의 교실 목록을 만든다.

    반환: [{"professorType", "department", "url", "menuId"}] — GNB 기준의 교실 페이지들.
    대분류에 하위 교실 메뉴가 없으면(의학교육학·인문사회의학) 대분류 자신이 곧 교실 1개다.
    """
    links = parse_menu_links(hub_html)
    departments = []
    for group_id, parent_id, href, title in links:
        if parent_id != hub_menu_id:
            continue
        professor_type = GROUP_TO_TYPE.get(title)
        if professor_type is None:
            print(f"교실 아님 → 건너뜀: {title}")
            continue
        children = [(cid, c_href, c_title) for cid, pid, c_href, c_title in links if pid == group_id]
        if children:
            for cid, c_href, c_title in sorted(children, key=lambda c: int(c[0])):
                departments.append(
                    {"professorType": professor_type, "department": c_title, "url": c_href, "menuId": cid}
                )
        else:
            departments.append(
                {"professorType": professor_type, "department": title, "url": href, "menuId": group_id}
            )
    if not departments:
        review.append({"page": "허브", "url": LIST_URL_KO, "reason": "교실 메뉴를 찾지 못함 — 페이지 구조 변경 의심"})
    return departments


def find_division_tabs(page_html, dept_menu_id):
    """교실 페이지의 분과 탭을 찾는다 (내과학교실: 감염~호흡기 8개).

    같은 마크업의 GNB 링크와 섞이지 않도록, 부모가 '이 교실 메뉴 id'인 링크만 분과로 본다.
    분과가 없는 교실이면 빈 목록.
    """
    tabs = [
        (self_id, href, title)
        for self_id, parent_id, href, title in parse_menu_links(page_html)
        if parent_id == dept_menu_id
    ]
    return sorted(tabs, key=lambda t: int(t[0]))


def parse_professors(page_html, review, context):
    """교실(또는 분과) 페이지에서 교수 항목들을 뽑는다.

    반환: [{"name", "position", "specialty", "phone", "homepageUrl"}]
    페이지에 없는 값은 null로 둔다 (계약 원칙 2 — 지어내지 않기).
    """
    professors = []
    for block in PRFL_ITEM_RE.findall(page_html):
        title_match = PRFL_TITLE_RE.search(block)
        raw_name = strip_tags(title_match.group(1)) if title_match else ""

        fields = {}
        homepage = None
        for dt, dd in PRFL_DL_RE.findall(block):
            key = strip_tags(dt)
            if key == "홈페이지":
                # 홈페이지 칸은 텍스트가 아니라 링크 주소가 값이다 (비어 있으면 null)
                href_match = HREF_RE.search(dd)
                url = (href_match.group(1).strip() if href_match else "")
                homepage = url or None
            else:
                fields[key] = strip_tags(dd) or None

        position = fields.get("직위(직급)")
        # "송창호 교수" → "송창호": 직위 값이 이름 뒤에 그대로 붙어 있으면 떼고,
        # 아니면 알려진 직함 접미(교수/부교수/…)를 뗀다
        name = raw_name
        if position and name.endswith(position):
            name = name[: -len(position)].strip()
        else:
            name = POSITION_SUFFIX_RE.sub("", name).strip()

        if not name:
            review.append({"page": context, "reason": f"이름을 읽지 못한 항목: '{raw_name}'"})
            continue
        if not re.fullmatch(r"[가-힣]{2,10}", name):
            # 한글 이름 꼴이 아니면 버리지 않고 기록만 — 값은 원문 그대로 (외국인 교수 등)
            review.append({"page": context, "name": name, "reason": "이름 표기가 일반적인 한글 이름 꼴이 아님 — 검수 필요"})

        professors.append(
            {
                "name": name,
                "position": position,
                "specialty": fields.get("전공"),
                "phone": fields.get("전화번호"),
                "homepageUrl": homepage,
            }
        )

    # 목록이 여러 페이지로 나뉘는 구조가 새로 생기면 놓친 인원이 생긴다 — 감지만 해서 알린다
    if "_paging" in page_html or "jf_viewPage" in page_html:
        review.append({"page": context, "reason": "페이지네이션 감지 — 2페이지 이후 인원 누락 가능, 확인 필요"})
    return professors


def get_mdcl_cd(url):
    """병원 프로필 URL의 mdclCd 쿼리 파라미터 값(진료과 코드)을 읽는다. 없으면 None."""
    query = parse_qs(urlparse(url).query)
    return (query.get("mdclCd") or [None])[0]


def is_dental(mdcl_cd):
    """mdclCd가 'DN'으로 시작하면 치과 계열로 분류한다 (삭제가 아니라 분류만 — 서비스 범위
    제외 여부는 회의 확정 대기)."""
    return bool(mdcl_cd) and mdcl_cd.startswith("DN")


def fetch_hospital_department(url, review, name):
    """병원 프로필 페이지에서 이 사람의 실제 진료과 텍스트를 읽어온다.

    동명 레코드가 여럿이라 겸직인지 동명이인인지 판단이 안 설 때만 호출한다
    (드문 경우라 병원 홈페이지 부담이 적다). 실패하거나 마크업을 찾지 못하면 None —
    호출한 쪽이 review에 기록하고 매칭을 보류한다 (확신 없는 매칭은 하지 않는다).
    """
    html = fetch_html(url, review, f"병원 프로필({name})")
    if html is None:
        return None
    match = HOSPITAL_PROFILE_RE.search(html)
    if match is None:
        review.append({"name": name, "url": url, "reason": "병원 프로필 마크업에서 진료과를 찾지 못함"})
        return None
    return match.group(2).strip()


def keywords_overlap(record, hospital_dept_text):
    """크롤 레코드의 소속 키워드가 병원 진료과 텍스트와 겹치는지 확인한다.

    division·specialty처럼 구체적인 값을 먼저 보고, 둘 다 없을 때만 department의
    '...교실' 접미를 뗀 값을 쓴다. department를 항상 섞으면 "내과"처럼 뭉뚱그린
    키워드가 여러 후보에 동시에 걸려 버려(예: 소화기·혈액종양 둘 다 "내과학교실") 정작
    구분에 필요한 division·specialty의 변별력이 묻힌다.
    """
    keywords = [kw for kw in (record.get("division"), record.get("specialty")) if kw]
    if not keywords:
        dept = re.sub(r"(학)?교실$", "", record.get("department") or "")
        if dept:
            keywords = [dept]
    return any(len(kw) >= 2 and kw in hospital_dept_text for kw in keywords)


def resolve_hospital_matches(professors, hospital_by_norm, review):
    """교수 레코드마다 matchedInHospitalList를 이름이 아니라 레코드 단위로 확정한다.

    - 이름이 한쪽에만 있으면 그대로 True/False.
    - 크롤 결과에 같은 이름이 여럿이면(겸직 게시 또는 동명이인 가능):
      * 후보 **전원에게 전화번호가 있고** 그 값이 전부 같을 때만 같은 사람이 여러 교실에
        겸직으로 게시된 것으로 보고 전원 매칭시킨다 (병원 홈페이지에 별도로 조회하지 않는다).
        하나라도 번호가 비어 있으면 "모른다"를 "같다"로 취급하지 않고 아래 동명이인 경로로
        넘긴다 — 번호가 있는 한 명만 보고 겸직으로 단정하면 서로 다른 두 사람이 한 사람으로
        합쳐져 버린다.
      * 전화번호가 서로 다르거나 하나라도 비어 있으면 동명이인일 수 있다 — 병원 프로필의
        실제 진료과를 읽어(fetch_hospital_department) division·specialty와 겹치는 레코드만
        매칭시키고, 나머지는 신규로 둔다. 두 레코드 모두에 "동명이인 확인됨" 메모를 남긴다.
      * 겹치는 레코드가 0개나 2개 이상이면 구분할 수 없으므로 review에 기록하고
        전원 매칭 안 함(False)으로 둔다 — 확신 없는 매칭은 지어내지 않는다(계약 원칙 2).
    """
    by_name = defaultdict(list)
    for p in professors:
        by_name[p["name"]].append(p)

    for name, candidates in by_name.items():
        hosp = hospital_by_norm.get(normalize_name(name))
        if hosp is None:
            for p in candidates:
                p["matchedInHospitalList"] = False
            continue
        if len(candidates) == 1:
            candidates[0]["matchedInHospitalList"] = True
            continue

        phones = [p["phone"] for p in candidates]
        if all(phones) and len(set(phones)) == 1:
            # 전원 번호가 있고 값이 모두 같다 — 같은 사람이 여러 교실에 겸직으로 게시된 것.
            # 비어 있는 번호는 여기서 걸러내지 않는다: 한 명만 번호가 있고 나머지가 비었을 때
            # "같은 번호"로 세면 모르는 것을 같다고 단정하는 셈이라 동명이인이 합쳐진다.
            for p in candidates:
                p["matchedInHospitalList"] = True
            continue

        # 동명 레코드의 전화번호가 다르거나 하나라도 비어 있다 — 동명이인 가능성
        dept_text = fetch_hospital_department(hosp["url"], review, name)
        if dept_text is None:
            for p in candidates:
                p["matchedInHospitalList"] = False
            review.append({"name": name, "reason": "병원 프로필 조회 실패로 동명이인 구분 불가 — 매칭 보류"})
            continue

        overlaps = [p for p in candidates if keywords_overlap(p, dept_text)]
        if len(overlaps) == 1:
            matched = overlaps[0]
            matched["matchedInHospitalList"] = True
            matched["homonymNote"] = f"동명이인 확인됨 — 병원 프로필 진료과('{dept_text}')와 일치해 매칭"
            for p in candidates:
                if p is not matched:
                    p["matchedInHospitalList"] = False
                    p["homonymNote"] = (
                        f"동명이인 확인됨 — 병원 프로필 진료과('{dept_text}')와 일치하지 않아 별도 인물로 처리(신규)"
                    )
        else:
            for p in candidates:
                p["matchedInHospitalList"] = False
            review.append(
                {
                    "name": name,
                    "reason": f"동명이인 구분 불가(겹치는 소속 {len(overlaps)}건) — 병원 진료과: '{dept_text}'",
                }
            )


def build_diff(professors, hospital_by_norm):
    """병원 명단과 크롤 결과를 레코드 단위로 비교해 diff를 만든다.

    hospitalOnly는 삭제가 아니라 분류만 한다 — mdclCd가 'DN'으로 시작하면
    hospitalOnlyDental(치과 계열, 서비스 범위 제외 여부는 회의 확정 대기),
    나머지는 hospitalOnlyOther로 나눠 둔다.
    """
    matched_norms = {normalize_name(p["name"]) for p in professors if p["matchedInHospitalList"]}
    matched = sum(1 for norm in hospital_by_norm if norm in matched_norms)

    new_only = []
    seen_new = set()
    for p in professors:
        if p["matchedInHospitalList"]:
            continue
        key = (p["name"], p["department"], p["division"])
        if key in seen_new:
            continue
        seen_new.add(key)
        entry = {"name": p["name"], "professorType": p["professorType"], "department": p["department"]}
        if p["division"]:
            entry["division"] = p["division"]
        if p.get("homonymNote"):
            entry["note"] = p["homonymNote"]
        new_only.append(entry)

    hospital_only_dental = []
    hospital_only_other = []
    for norm, hosp in hospital_by_norm.items():
        if norm in matched_norms:
            continue
        bucket = hospital_only_dental if is_dental(hosp["mdclCd"]) else hospital_only_other
        bucket.append(hosp["originalName"])

    return {
        "newOnly": new_only,
        "matched": matched,
        "hospitalOnlyDental": hospital_only_dental,
        "hospitalOnlyOther": hospital_only_other,
    }


def main():
    if LIST_URL_KO == "REPLACE_ME":
        print("파일 상단의 LIST_URL_KO를 의대 홈페이지 교수소개(허브) URL로 채운 뒤 다시 실행하세요.")
        sys.exit(1)

    # 비교 대상: 병원 기반 명단 243명 (이름 → 프로필 URL). URL의 mdclCd로 치과 계열을
    # 가려내고(진료과 코드가 'DN'으로 시작), 동명이인 판별 시 프로필 페이지 재조회에 쓴다.
    with open(HOSPITAL_LIST_PATH, encoding="utf-8") as f:
        hospital_pages = json.load(f)
    hospital_by_norm = {
        normalize_name(name): {"originalName": name, "url": url, "mdclCd": get_mdcl_cd(url)}
        for name, url in hospital_pages.items()
    }

    review = []
    print(f"허브 페이지 수집: {LIST_URL_KO}")
    hub_html = fetch_html(LIST_URL_KO, review, "허브")
    if hub_html is None:
        print("허브 페이지를 가져오지 못했습니다. 네트워크 상태를 확인한 뒤 다시 실행하세요.")
        sys.exit(1)

    hub_menu_id = re.search(r"/(\d+)/subview\.do", LIST_URL_KO).group(1)
    departments = build_department_list(hub_html, hub_menu_id, review)
    by_type = {}
    for dept in departments:
        by_type.setdefault(dept["professorType"], []).append(dept["department"])
    print(f"교실 페이지 {len(departments)}개 발견: " + ", ".join(f"{t} {len(ds)}개" for t, ds in by_type.items()))

    professors = []
    seen = set()   # (이름, 교실, 분과) 중복 방지

    def collect(page_html, dept, division):
        """페이지 1장에서 교수들을 뽑아 대분류·교실·분과 정보를 붙여 담는다."""
        context = dept["department"] + (f"({division})" if division else "")
        for person in parse_professors(page_html, review, context):
            if LIMIT is not None and len(professors) >= LIMIT:
                return
            key = (person["name"], dept["department"], division)
            if key in seen:
                continue
            seen.add(key)
            professors.append(
                {
                    "name": person["name"],
                    "nameEn": None,   # [변경 지시] 영문판 명단 부재 — 추후 논문 저자 정보에서 채움
                    "professorType": dept["professorType"],
                    "department": dept["department"],
                    "division": division,   # 내과학교실 분과(감염 등). 분과 없는 교실은 null
                    "position": person["position"],
                    "specialty": person["specialty"],
                    "phone": person["phone"],
                    "homepageUrl": person["homepageUrl"],
                    # matchedInHospitalList는 크롤이 다 끝난 뒤 resolve_hospital_matches가
                    # 레코드 단위로(겸직·동명이인 구분) 채운다 — 여기서는 이름만으로 단정하지 않는다.
                }
            )

    for dept in departments:
        if LIMIT is not None and len(professors) >= LIMIT:
            print(f"LIMIT={LIMIT} 도달 — 수집 중단 (검증용)")
            break
        page_html = fetch_html(urljoin(LIST_URL_KO, dept["url"]), review, dept["department"])
        if page_html is None:
            continue

        tabs = find_division_tabs(page_html, dept["menuId"])
        if tabs:
            # 분과 구조(내과학교실): 첫 탭은 지금 받은 페이지 그 자체라 다시 요청하지 않는다
            print(f"{dept['department']}: 분과 {len(tabs)}개 ({', '.join(t[2] for t in tabs)})")
            for _, tab_href, tab_title in tabs:
                if LIMIT is not None and len(professors) >= LIMIT:
                    break
                if tab_href == dept["url"]:
                    division_html = page_html
                else:
                    division_html = fetch_html(urljoin(LIST_URL_KO, tab_href), review, f"{dept['department']}({tab_title})")
                if division_html is not None:
                    collect(division_html, dept, tab_title)
        else:
            collect(page_html, dept, None)

        count_here = sum(1 for p in professors if p["department"] == dept["department"])
        print(f"  {dept['professorType']} · {dept['department']}: 누적 {count_here}명")

    # ----- 기존 병원 명단과 비교(diff) — 이 스크립트의 핵심 가치 -----
    # 레코드 단위 매칭: 이름만 보고 단정하지 않고, 겸직/동명이인을 가려낸 뒤 diff를 만든다.
    print("\n동명 레코드 매칭 확정 중 (겸직·동명이인 판별)...")
    resolve_hospital_matches(professors, hospital_by_norm, review)
    diff = build_diff(professors, hospital_by_norm)

    result = {
        "collectedAt": date.today().isoformat(),   # 수집 기준일 (계약 원칙 4)
        "source": {"ko": LIST_URL_KO, "en": None},  # 영문판은 명단이 없어 수집하지 않음 (null)
        "professors": professors,
        "diff": diff,
        "review": review,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)  # ensure_ascii=False: 한글 보존
    print(f"\n저장 완료: {OUTPUT_PATH}")

    # ----- 통계 (완료 기준 — 사람이 바로 검수할 수 있게) -----
    with_name_en = sum(1 for p in professors if p["nameEn"])
    homonym_names = {p["name"] for p in professors if p.get("homonymNote")}
    print(
        f"전체 수집 {len(professors)}명 / 영문명 확보 {with_name_en}명(영문판 부재로 범위 제외)"
        f" / 매칭 불확실 0명(한↔영 매칭 미수행) / 동명이인 구분 {len(homonym_names)}건"
        f" / 신규 {len(diff['newOnly'])}명"
        f" / 병원 명단에만(치과) {len(diff['hospitalOnlyDental'])}명"
        f" / 병원 명단에만(그 외) {len(diff['hospitalOnlyOther'])}명"
    )
    if review:
        print(f"review {len(review)}건 — 산출물의 review 목록을 검수해 주세요.")


if __name__ == "__main__":
    main()
