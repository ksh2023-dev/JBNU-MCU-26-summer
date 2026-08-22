"""D단계 — 최종 조립기. 수집 산출물을 병합해 데이터 계약 v6.5 모양의 professors.json을 만든다.

v6.5 개정분
  - `keywords`를 만드는 규칙 확정: meshTerms 우선 → 없으면 kciKeywords.en → 둘 다 없으면 []
  - 키워드 원본 보존 필드 신설: `meshTerms`(MeSH 원본) · `kciKeywords`({ko, en} KCI 원본)
    → professors.json 안에 보존하는 내부 필드다 (API 응답에는 keywords 하나만 나간다)
  - `latestPaper` 후보 조건 확정: pmid가 있고 완전한 YYYY-MM-DD 발행일을 가진 PubMed 논문만.
    연도-only·연월-only·KCI 전용은 제외하되, 조건을 만족하는 논문 중 가장 최신을 고른다
  ※ `keywordsKo`(최종 keywords의 한글화)는 다른 팀원의 스크립트가 채운다 — 여기서 만들지 않는다

v6.4 개정분 (2026-08-16 회의)
  - 대상 범위: 의대 공식 명단 기준 (치과 계열·병원 전용 교수 제외) → 0-2장
  - `labName` 필드 삭제 (수집 출처 없음) → EMIT_LABNAME
  - `papers[]`에 `kciId` 추가. 논문은 pmid 또는 kciId 중 하나가 반드시 있어야 한다 (원칙 1)
  ※ 이 코드의 기준은 팀이 확정한 사양(작업지시서)이다. docs/의 계약 문서는 최신 결정이
    아직 반영되지 않았을 수 있으므로, 서로 다르면 확정 사양을 따른다.
    계약 샘플(data/sample/professors.sample.json)도 아직 v6.3이라, 개정분(labName 삭제 ·
    papers[].kciId · meshTerms · kciKeywords)은 샘플에서 읽은 칸 목록에 코드가 명시적으로 반영한다.

입력 (재료 7종)
  data/output/roster_crawled.json            의대 명단 (교수구분·교실·직위·전화·동명이인 메모·diff)
  data/input/professor_pages.json            병원 교수 프로필 URL (= 병원 명단 243명, homepageUrl 재료)
  data/output/profile_images.json            프로필 사진 URL
  data/output/specialties.json               전문진료분야
  data/output/professors_papers.json         대표 논문 3편 · latestPaper · allPapers
  data/output/professors_enriched_meta.json  영문명 · MeSH 키워드 후보 · 이메일
  data/output/kci_papers.json                KCI 논문 (교수 id 기준) — kciKeywords 재료

관리 파일 (사람이 관리, 커밋 대상 — 구조 설명은 data/input/README.md)
  data/input/manual_overrides.json           수동 검수 대장 (사람 확정이 자동 수집을 이긴다)
  data/input/id_registry.json                id 대장 (한 번 부여한 id는 영원히 불변)

출력 (data/output/ — .gitignore 대상, 커밋하지 않는다)
  data/output/professors.json                   백엔드가 읽는 최종 파일. 계약(v6.5) 칸만 담는다
  data/output/professors_extra.json             계약 밖 내부 데이터 (영문명·초록·근거·제외 명단·review)
  data/output/_cache_hospital_departments.json  병원 프로필에서 읽은 진료과 캐시 (재실행 시 재조회 생략)

계약 0장 4원칙
  1. pmid 또는 kciId가 없는 논문은 넣지 않는다 (v6.4 확장)
  2. 값이 없으면 지어내지 말고 null (빈 문자열도 쓰지 않는다)
  3. 근거 없는 점수를 만들지 않는다 (matchScore는 백엔드 소관 — 이 파일에는 없다)
  4. 수집 기준일(collectedAt)을 담고, 이름·이메일·논문 값은 원본 그대로 둔다

실행: python scripts/assembler/build_professors.py
"""

# ── 설정 ────────────────────────────────────────────────────────────
# 회의에서 뒤집힐 수 있는 결정은 전부 이 상수로 모아 둔다.

EXCLUDE_DENTAL = True               # 치과 계열(병원 명단 전용 29명)을 대상에서 제외
MERGE_CROSS_APPOINTMENTS = True     # 한 사람이 두 교실에 걸쳐 있으면(교차 겸직) 한 명으로 합침
DEPARTMENT_INCLUDE_DIVISION = True  # 내과·외과의 분과를 소속에 표기 — "내과학교실(소화기)"
DEPARTMENT_JOIN_CROSS_APPOINTMENTS = True  # 교차 겸직은 두 교실을 함께 표기 — "예방의학교실 · 가정의학교실"
CROSS_APPOINTMENT_SEPARATOR = " · "
FETCH_HOSPITAL_DEPARTMENT = True    # 병원 명단 전용 교수의 진료과를 병원 프로필에서 조회
USE_DEPARTMENT_CACHE = True         # 조회 결과를 캐시에 남겨 재실행 시 재조회하지 않음
# 의대 명단에 없고 병원 명단에만 있는 교수(67명)를 포함할지.
# 2026-08-16 회의 결정: 의대 공식 명단 기준 — 제외한다(False).
# 이들은 의대 홈페이지에 없어 교수 구분의 근거가 없고, 계약상 professorType은 값이 필수라
# 아래 HOSPITAL_ONLY_PROFESSOR_TYPE으로 '추정'해야만 수록할 수 있었다. 근거 없는 값을 넣지 않기로 했다.
# 제외 명단은 삭제하지 않고 review.excludedHospitalOnly에 남긴다 (범위가 다시 바뀔 수 있다).
# True로 되돌리면 추정 사실이 professors_extra.json의 professorTypeInferred 플래그와
# review.professorTypeInferred에 기록되며, 계약 파일에는 계약 밖 칸을 만들지 않는다.
INCLUDE_HOSPITAL_ONLY = False
HOSPITAL_ONLY_PROFESSOR_TYPE = "임상의학"  # 위를 True로 되돌릴 때만 쓰인다 (추정 → extra 플래그 + review)
PAPERS_LIMIT = 3                    # 대표 논문 수 (계약 1-2: 최신 1편 + 인용 상위 2편)

# labName을 출력할지 — v6.4에서 계약 필드 자체가 삭제되어 기본값 False.
# (수집 가능한 출처가 없어 전원 null이었고 화면에서도 제거됐다)
# 백엔드 스키마가 아직 v6.4 반영 전이라면 임시로 True가 필요할 수 있다.
# 참고: backend/app/schemas.py의 lab_name은 기본값 None을 가진 선택 필드라,
# False로 두어 칸을 빼도 백엔드 적재는 실패하지 않는다 (대신 응답에 labName: null이 그대로 붙는다).
EMIT_LABNAME = False

# 키워드 배열의 개수 상한. 계약에는 상한 규정이 없어, MeSH를 만드는 C단계
# (scripts/pubmed_collector/enrich_authors_mesh.py의 TOP_KEYWORDS)와 같은 값으로 맞춘다.
# meshTerms는 이미 상한이 적용된 값을 그대로 받고, kciKeywords에 같은 상한을 적용한다.
KEYWORDS_LIMIT = 10

SLEEP_SECONDS = 0.5                 # 서버 예절: 병원 페이지 호출 사이 대기
TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

import json
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

# 경로는 이 스크립트 위치 기준 → 어느 폴더에서 실행해도 동일하게 동작
ROOT = Path(__file__).resolve().parents[2]

ROSTER_PATH = ROOT / "data" / "output" / "roster_crawled.json"
PAGES_PATH = ROOT / "data" / "input" / "professor_pages.json"
IMAGES_PATH = ROOT / "data" / "output" / "profile_images.json"
SPECIALTIES_PATH = ROOT / "data" / "output" / "specialties.json"
PAPERS_PATH = ROOT / "data" / "output" / "professors_papers.json"
META_PATH = ROOT / "data" / "output" / "professors_enriched_meta.json"
KCI_PATH = ROOT / "data" / "output" / "kci_papers.json"
# 최종 keywords를 한글화할 때 쓰는 사전 { "영문 용어": "한글 번역" }.
# 다른 팀원의 스크립트가 만드는 파일이라 아직 없을 수 있다 → 없으면 경고만 하고 keywordsKo는 []로 둔다.
KEYWORD_KO_DICT_PATH = ROOT / "data" / "output" / "keyword_ko_dict.json"

OVERRIDES_PATH = ROOT / "data" / "input" / "manual_overrides.json"
REGISTRY_PATH = ROOT / "data" / "input" / "id_registry.json"

SAMPLE_PATH = ROOT / "data" / "sample" / "professors.sample.json"
OUTPUT_PATH = ROOT / "data" / "output" / "professors.json"
EXTRA_PATH = ROOT / "data" / "output" / "professors_extra.json"
CACHE_PATH = ROOT / "data" / "output" / "_cache_hospital_departments.json"

PROFESSOR_TYPES = ("기초의학", "임상의학", "의학교육학", "인문사회의학")

# 계약 1-2의 논문 객체 칸 (v6.4 — kciId 추가)
PAPER_FIELDS = ("title", "journal", "year", "pmid", "kciId")

# v6.5에서 professors.json에 보존하는 키워드 원본 필드 (내부 필드 — API 응답에는 안 나간다)
V65_KEYWORD_FIELDS = ("meshTerms", "keywordsKo", "kciKeywords")

# latestPaper 후보의 발행일 형식 — 완전한 YYYY-MM-DD만 인정한다 (계약 v6.5 2장 API ③).
# 연도-only·연월-only는 후보에서 빼고, 없는 날짜를 01-01 같은 값으로 보정하지 않는다 (원칙 2).
FULL_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 계약 밖이지만 수동 검수 대장으로 고칠 수 있는 필드 (professors_extra.json 전용)
EXTRA_ONLY_FIELDS = ("nameEn",)

# 값을 바꾸는 항목이 아니라 '사람이 확인한 사실'을 적는 특수 항목 (따로 검증·소비된다)
ASSERTION_FIELDS = ("distinctPerson", "idInheritance")

REVIEW_KEYS = (
    "professorTypeInferred",        # 교수 구분을 추정한 교수 (계약 필드는 오염시키지 않는다)
    "excludedHospitalOnly",         # INCLUDE_HOSPITAL_ONLY=False로 제외한 병원 전용 교수
    "departmentFetchFailed",        # 병원 프로필에서 진료과를 못 읽은 교수
    "droppedNoDepartment",          # 소속을 끝내 확보하지 못해 제외한 교수
    "crossAppointmentMerged",       # 두 교실에 걸친 사람을 한 명으로 합친 기록
    "homonymIsolated",              # 동명이인이라 이름 기반 자료를 물려주지 않은 기록
    "rosterMatchCollision",
    "latestPaperDropped",           # 발행일·식별자가 없어 featured 후보에서 뺀 논문
    "kciKeywordsUnmatched",         # KCI 산출물에서 그 교수를 찾지 못했거나 이름이 어긋난 경우
    "latestPaperMissingWithPapers",
    "manualOverridesApplied",
    "manualOverridesUnmatched",
    "manualOverridesOutOfScope",    # 대상 교수가 이번 범위에서 빠져 적용되지 않은 확정 항목
    "idDepartmentChanged",
    "idInheritanceHeld",            # 이름은 같은데 소속이 달라 id 승계를 보류한 교수
    "idAmbiguous",
)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# ── 병원 프로필에서 진료과 읽기 ──────────────────────────────────────
# 프로필 페이지 구조 (2026-08-16 실제 HTML 확인):
#   <strong class="mtName">이미린</strong>
#   <span class="mtPart">간담췌이식혈관외과(간담췌외과)</span>
# 같은 페이지에 다른 의료진 목록도 섞여 있으므로
# "대상 교수 이름이 적힌 mtName 다음에 오는 첫 mtPart"만 인정한다.

class DepartmentParser(HTMLParser):
    def __init__(self, professor_name):
        super().__init__()
        self.professor_name = professor_name
        self.department = None
        self._in_name_tag = False
        self._name_matched = False
        self._in_part_tag = False
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class") or ""
        if tag == "strong" and "mtName" in classes:
            self._in_name_tag = True
        elif tag == "span" and "mtPart" in classes and self._name_matched and self.department is None:
            self._in_part_tag = True
            self._buffer = []

    def handle_data(self, data):
        if self._in_name_tag and data.strip() == self.professor_name:
            self._name_matched = True
        if self._in_part_tag:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "strong":
            self._in_name_tag = False
        elif tag == "span" and self._in_part_tag:
            self._in_part_tag = False
            text = " ".join("".join(self._buffer).split())
            if text:
                self.department = text


def fetch_html(url):
    """URL의 HTML을 가져온다. 2회까지 시도하고 실패하면 None (한 명이 실패해도 전체는 계속)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as error:
            print(f"    요청 실패 (시도 {attempt}/2): {error}")
            if attempt == 1:
                time.sleep(SLEEP_SECONDS)
    return None


def fetch_department(name, url):
    """병원 프로필에서 진료과 텍스트를 읽는다. 못 읽으면 None (지어내지 않는다 — 원칙 2)."""
    html = fetch_html(url)
    if html is None:
        return None
    parser = DepartmentParser(name)
    parser.feed(html)
    parser.close()
    return parser.department


def resolve_hospital_departments(names, pages, review):
    """병원 명단 전용 교수의 진료과를 캐시 → 병원 프로필 순으로 확보한다."""
    cached = {}
    if USE_DEPARTMENT_CACHE and CACHE_PATH.exists():
        try:
            cached = load_json(CACHE_PATH).get("departments") or {}
        except Exception as error:
            print(f"    진료과 캐시를 읽지 못해 무시한다: {error}")

    resolved = {n: cached[n] for n in names if cached.get(n)}
    todo = [n for n in names if n not in resolved]
    print(f"[4] 병원 전용 교수 진료과 확보: 대상 {len(names)}명 "
          f"(캐시 재사용 {len(resolved)}명 / 새로 조회 {len(todo)}명)")
    if todo and not FETCH_HOSPITAL_DEPARTMENT:
        print("    FETCH_HOSPITAL_DEPARTMENT=False → 조회하지 않는다")
        todo = []

    for index, name in enumerate(todo, start=1):
        department = fetch_department(name, pages[name])
        if department:
            resolved[name] = department
        else:
            review["departmentFetchFailed"].append({"name": name, "url": pages[name]})
            print(f"    [{index}/{len(todo)}] {name}: 진료과를 읽지 못했다 → null")
        if index % 20 == 0:
            print(f"    진행 {index}/{len(todo)} (확보 {len(resolved)}명)")
        if index < len(todo):
            time.sleep(SLEEP_SECONDS)  # 서버 예절

    if USE_DEPARTMENT_CACHE and resolved:
        save_json(CACHE_PATH, {
            "_comment": "병원 프로필에서 읽은 진료과 캐시. 지워도 다음 실행에서 다시 조회한다.",
            "updatedAt": date.today().isoformat(),
            "departments": dict(sorted(resolved.items())),
        })
    return resolved


# ── 의대 명단을 '사람' 단위로 묶기 ───────────────────────────────────

def group_roster_persons(records, review):
    """의대 명단 레코드를 사람 단위로 묶는다.

    같은 이름이 두 번 나오는 경우는 두 가지다.
      (1) 교차 겸직 — 한 사람이 두 교실에 이름을 올린 경우. 전화번호가 같다.
          예) 김형태: 해부학교실 · 의학교육학교실 (전화·홈페이지·전공 모두 동일)
      (2) 동명이인 — 다른 사람. 예) 이창훈: 소화기 · 혈액·종양 (전화 없음, 전공 다름)
    전화번호가 있고 서로 같으면 (1)로 보고 한 사람으로 합친다. 그 외에는 각각 다른 사람으로 둔다.
    """
    persons = []
    groups = {}
    for index, record in enumerate(records):
        phone = (record.get("phone") or "").strip()
        key = (record["name"], phone) if (MERGE_CROSS_APPOINTMENTS and phone) else ("__단독__", index)
        if key not in groups:
            groups[key] = {"name": record["name"], "records": []}
            persons.append(groups[key])
        groups[key]["records"].append(record)

    for person in persons:
        primary, rule = pick_primary_record(person["records"])
        person["primary"] = primary
        if len(person["records"]) > 1:
            review["crossAppointmentMerged"].append({
                "name": person["name"],
                "chosen": {"department": primary["department"], "professorType": primary["professorType"]},
                "alternates": [{"department": r["department"], "professorType": r["professorType"]}
                               for r in person["records"] if r is not primary],
                "rule": rule,
                "note": "이름·전화가 같아 한 사람으로 합쳤다. 교수 구분은 전공과 맞물리는 교실(chosen)을 "
                        "따르고, 소속은 두 교실을 함께 적었다.",
            })
    return persons


def pick_primary_record(records):
    """교차 겸직으로 묶인 레코드 중 대표(소속·교수구분의 근거)를 고른다.

    기준: 그 사람의 전공(specialty)과 맞물리는 교실을 고른다.
      예) 김종승 — 전공 '이비인후과학' → 의료정보학교실 / 이비인후과학교실 중 후자
    맞물리는 교실이 정확히 하나가 아니면 명단에 먼저 나온 레코드를 쓰고 review에 남긴다.
    """
    if len(records) == 1:
        return records[0], "단일 레코드"

    specialty_blob = " ".join((r.get("specialty") or "") for r in records)
    matched = []
    for record in records:
        core = (record.get("department") or "").replace("교실", "")
        if not core:
            continue
        # '내과학' → '내과'처럼 끝의 '학'을 뗀 형태도 함께 본다 (전공 표기가 '내과, 신장'인 경우)
        if core in specialty_blob or core.rstrip("학") in specialty_blob:
            matched.append(record)
    if len(matched) == 1:
        return matched[0], "전공-교실 일치"
    return records[0], "일치 판정 실패 → 명단 순서 첫 레코드"


def department_label(record):
    """레코드 하나의 소속 표기. 분과가 있으면 함께 적는다 — '내과학교실(소화기)'.

    내과학교실 39명·외과학교실 11명이 전부 같은 이름이 되는 것을 막고,
    동명이인(이창훈)을 소속으로 구분할 수 있게 한다. 값은 모두 명단 원문 그대로다.
    """
    department = record.get("department")
    if not department:
        return None
    division = record.get("division")
    if DEPARTMENT_INCLUDE_DIVISION and division:
        return f"{department}({division})"
    return department


def compose_department(person):
    """사람 한 명의 소속 표기.

    교차 겸직으로 합친 사람은 두 교실을 ' · '로 이어 붙인다. 한쪽만 적으면 나머지 교실에서는
    검색·목록에 보이지 않기 때문이다. 대표(전공과 맞물리는) 교실을 앞에 둔다.
      예) 권근상 → "예방의학교실 · 가정의학교실"
    """
    primary = person["primary"]
    ordered = [primary] + [r for r in person["records"] if r is not primary]
    labels = [label for label in (department_label(r) for r in ordered) if label]
    if not labels:
        return None
    if not DEPARTMENT_JOIN_CROSS_APPOINTMENTS:
        return labels[0]
    return CROSS_APPOINTMENT_SEPARATOR.join(dict.fromkeys(labels))  # 같은 표기는 한 번만


# ── 병합 ────────────────────────────────────────────────────────────

def new_record(name, department, department_source, professor_type, professor_type_inferred,
               in_hospital_list, person):
    """계약 필드 + 계약 밖(_extra) 필드를 가진 작업용 레코드."""
    primary = person["primary"] if person else None
    # ── 계약 필드 (계약 1-2 순서) ──
    record = {
        "id": None,
        "name": name,
        "profileImageUrl": None,
        "professorType": professor_type,
        "department": department,
    }
    if EMIT_LABNAME:
        # v6.4에서 삭제된 칸 — 백엔드가 아직 v6.3이라 필요할 때만 되살린다 (값은 항상 null)
        record["labName"] = None
    record.update({
        "specialties": [],
        # keywords는 meshTerms·kciKeywords가 채워진 뒤 resolve_keywords()가 정한다 (v6.5 선택 규칙)
        "keywords": [],
        "meshTerms": [],                       # MeSH 원본 (내부 필드 — 응답에 나가지 않는다)
        "keywordsKo": [],                      # 최종 keywords의 한글화 결과 (내부 필드 · 한글 검색용)
        "kciKeywords": {"ko": [], "en": []},   # KCI 원본. 객체와 ko/en 두 배열은 항상 존재한다
        "email": None,
        "homepageUrl": None,
        "latestPaper": None,       # 백엔드 내부 필드 (API ③ 정렬용, 응답에는 안 나감)
        "papers": [],
        # ── 계약 밖 (professors_extra.json으로 나간다) ──
        "_extra": {
            # 교수 구분을 의대 명단에서 확인하지 못하고 추정했다는 표시 (계약 파일에는 넣지 않는다)
            "professorTypeInferred": professor_type_inferred,
            "manualFields": [],        # 수동 검수 대장이 확정한 필드 (자동 계산이 덮지 않게)
            "nameEn": None,
            "nameEnVariants": [],
            "keywordsCandidateAll": [],
            "evidence": None,
            "allPapers": [],
            "roster": None if primary is None else {
                "department": primary.get("department"),
                "division": primary.get("division"),
                "position": primary.get("position"),
                "phone": primary.get("phone"),
                "specialty": primary.get("specialty"),
                "homepageUrl": primary.get("homepageUrl"),
                "homonymNote": primary.get("homonymNote"),
                "crossAppointments": [{"department": r.get("department"),
                                       "professorType": r.get("professorType")}
                                      for r in person["records"] if r is not primary],
            },
            "sources": {
                "inHospitalList": in_hospital_list,
                "inRoster": person is not None,
                "departmentSource": department_source,
                "professorTypeInferred": professor_type_inferred,
            },
        },
    })
    return record


def fill_from_sources(record, sources, review):
    """이름으로 조회되는 재료(사진·전문분야·키워드·이메일·홈페이지·논문)를 채운다.

    이 재료들은 모두 '병원 명단의 이름'을 키로 수집된 것이라, 병원 명단에 없는 교수에게는
    적용하지 않는다. 동명이인에게 남의 논문·사진이 붙는 것을 막는 방어선이다 (원칙 2·4).
    """
    if not record["_extra"]["sources"]["inHospitalList"]:
        return
    name = record["name"]

    record["profileImageUrl"] = sources["images"].get(name) or None
    record["homepageUrl"] = sources["pages"].get(name) or None  # 계약 1-2: 임상 교수는 병원 홈페이지
    record["specialties"] = list((sources["specialties"].get(name) or {}).get("specialties") or [])

    meta_entry = sources["meta"].get(name) or {}
    # MeSH 원본. C단계에서 이미 (빈도 내림차순 → 이름 오름차순) 정렬·상한 적용된 값이다
    record["meshTerms"] = list(meta_entry.get("keywordsCandidate") or [])[:KEYWORDS_LIMIT]
    record["email"] = meta_entry.get("email") or None
    record["_extra"]["nameEn"] = meta_entry.get("nameEn") or None
    record["_extra"]["nameEnVariants"] = list(meta_entry.get("nameEnVariants") or [])
    record["_extra"]["keywordsCandidateAll"] = list(meta_entry.get("keywordsCandidateAll") or [])
    record["_extra"]["evidence"] = meta_entry.get("evidence")

    paper_entry = sources["papers"].get(name) or {}
    # 원칙 1 (v6.4) — pmid 또는 kciId 중 하나는 있어야 한다. 둘 다 없으면 넣지 않는다
    kept = [p for p in (paper_entry.get("papers") or [])
            if (p.get("pmid") or "").strip() or (p.get("kciId") or "").strip()]
    record["papers"] = [{"title": p["title"], "journal": p.get("journal"),
                         "year": p.get("year"),
                         "pmid": (p.get("pmid") or "").strip() or None,
                         # v6.4 신설. KCI 수집 전이라 현재는 전부 null이다
                         "kciId": (p.get("kciId") or "").strip() or None}
                        for p in kept[:PAPERS_LIMIT]]
    record["_extra"]["allPapers"] = list(paper_entry.get("allPapers") or [])

    # latestPaper — 계약 v6.5 후보 조건: pmid가 있고 완전한 YYYY-MM-DD 발행일을 가진 PubMed 논문.
    # 최신 논문이 연도-only여서 후보에서 빠지면, 그 아래로 내려가 조건을 만족하는 가장 최신 논문을 고른다.
    # (예전에는 원본 latestPaper 하나만 보고 실패하면 통째로 null이 되어 featured에서 조용히 빠졌다)
    all_papers = paper_entry.get("allPapers") or []
    candidates = [p for p in all_papers
                  if (p.get("pmid") or "").strip()
                  and FULL_DATE_PATTERN.match((p.get("publishedAt") or "").strip())]
    if candidates:
        # 같은 날짜면 pmid로 순서를 고정한다 (재실행해도 같은 결과가 나오도록)
        best = max(candidates, key=lambda p: (p["publishedAt"].strip(), p["pmid"].strip()))
        record["latestPaper"] = {"pmid": best["pmid"].strip(),
                                 "publishedAt": best["publishedAt"].strip()}

    # 후보에서 빠진 논문은 사유와 함께 남긴다 (조용히 버리지 않는다)
    chosen_pmid = (record["latestPaper"] or {}).get("pmid")
    source_latest = paper_entry.get("latestPaper") or {}
    source_pmid = (source_latest.get("pmid") or "").strip() or None
    if source_pmid and source_pmid != chosen_pmid:
        published_at = (source_latest.get("publishedAt") or "").strip()
        review["latestPaperDropped"].append({
            "name": name, "pmid": source_pmid, "publishedAt": published_at or None,
            "note": ("원본 최신 논문의 발행일이 완전한 YYYY-MM-DD가 아니어서 후보에서 제외 — "
                     + (f"대신 {chosen_pmid}({record['latestPaper']['publishedAt']})를 선정"
                        if chosen_pmid else "조건을 만족하는 논문이 없어 latestPaper는 null")),
        })
    elif not candidates and all_papers:
        review["latestPaperDropped"].append({
            "name": name, "pmid": None, "publishedAt": None,
            "note": f"논문 {len(all_papers)}편 모두 pmid+완전한 발행일 조건을 만족하지 않아 "
                    "featured 후보에서 제외 (날짜를 보정하지 않는다 — 원칙 2)",
        })


def aggregate_kci_keywords(papers):
    """KCI 논문들의 keyword를 언어별로 모아 (빈도 내림차순 → 문자열 오름차순)으로 정렬한다.

    MeSH(C단계)와 같은 규칙·같은 상한을 쓴다. 재실행해도 순서가 흔들리지 않는다.
    """
    result = {}
    for language in ("ko", "en"):
        counter = Counter()
        for paper in papers:
            terms = (paper.get("keywords") or {}).get(language) or []
            # 한 논문 안의 중복은 한 번만 센다
            counter.update({t.strip() for t in terms if isinstance(t, str) and t.strip()})
        ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        result[language] = [term for term, _ in ordered[:KEYWORDS_LIMIT]]
    return result


def fill_kci_keywords(records, kci_professors, review):
    """KCI 산출물(교수 id 기준)에서 kciKeywords를 채운다. id 부여가 끝난 뒤 호출한다."""
    for record in records:
        entry = kci_professors.get(record["id"])
        if entry is None:
            if kci_professors:   # KCI 산출물이 아예 없으면(미수집) 굳이 전원 기록하지 않는다
                review["kciKeywordsUnmatched"].append({
                    "id": record["id"], "name": record["name"],
                    "note": "KCI 산출물에 이 id가 없어 kciKeywords를 채우지 못했다 ([]로 둔다)",
                })
            continue
        if entry.get("name") and entry["name"] != record["name"]:
            # id는 같은데 이름이 다르면 남의 논문일 수 있다 → 붙이지 않는다 (원칙 2·4)
            review["kciKeywordsUnmatched"].append({
                "id": record["id"], "name": record["name"], "kciName": entry.get("name"),
                "note": "KCI 산출물의 이름이 달라 kciKeywords를 붙이지 않았다",
            })
            continue
        papers = entry.get("papers") or []
        record["kciKeywords"] = aggregate_kci_keywords(papers)
        record["_extra"]["kciEvidence"] = {
            "papers": len(papers),
            "papersWithKoKeywords": sum(1 for p in papers if (p.get("keywords") or {}).get("ko")),
            "papersWithEnKeywords": sum(1 for p in papers if (p.get("keywords") or {}).get("en")),
            "duplicateOfPubMed": sum(1 for p in papers if p.get("duplicateOf")),
        }


def load_keyword_ko_dictionary():
    """한글 사전을 읽는다. 파일이 없으면 (None, 사유)를 돌려주고 실행은 계속한다."""
    if not KEYWORD_KO_DICT_PATH.exists():
        return None, f"{KEYWORD_KO_DICT_PATH.name}이 없어 keywordsKo를 채우지 못했다 (전원 [])"
    try:
        raw = load_json(KEYWORD_KO_DICT_PATH)
    except Exception as error:
        return None, f"{KEYWORD_KO_DICT_PATH.name}을 읽지 못했다: {error}"
    if not isinstance(raw, dict):
        return None, f"{KEYWORD_KO_DICT_PATH.name}의 형식이 {{영문: 한글}} 객체가 아니다"
    # 값이 비어 있는 항목은 번역이 없는 것으로 본다 (빈 문자열을 넣지 않는다 — 원칙 2)
    return {str(k): str(v).strip() for k, v in raw.items() if str(v or "").strip()}, None


def fill_keywords_ko(records, ko_dictionary):
    """최종 keywords를 사전에서 찾아 keywordsKo를 만든다. 번역하지 않고 사전을 읽기만 한다.

    사전에 없는 용어는 건너뛴다 — 원문을 그대로 넣거나 번역을 지어내지 않는다 (원칙 2).
    순서는 keywords의 순서를 그대로 따른다.
    """
    stats = Counter()
    missing = Counter()
    if ko_dictionary is None:
        return stats, missing
    for record in records:
        if "keywordsKo" in (record["_extra"].get("manualFields") or []):
            stats["manual"] += 1
            continue
        translated = []
        for term in record["keywords"]:
            korean = ko_dictionary.get(term)
            if korean:
                translated.append(korean)
            else:
                missing[term] += 1
        # 같은 한글로 번역된 용어가 겹치면 한 번만 (순서는 처음 등장 순서를 유지)
        record["keywordsKo"] = list(dict.fromkeys(translated))
        stats["filled" if record["keywordsKo"] else "empty"] += 1
        if record["keywords"]:
            record["_extra"]["keywordsKoCoverage"] = {
                "keywords": len(record["keywords"]),
                "translated": len(translated),
                "missing": len(record["keywords"]) - len(translated),
            }
    return stats, missing


def resolve_keywords(records):
    """최종 keywords 선택 (계약 v6.5): meshTerms → kciKeywords.en → []. 부분 병합하지 않는다."""
    counts = Counter()
    for record in records:
        if "keywords" in record["_extra"].get("manualFields") or []:
            counts["manual"] += 1
            continue
        if record["meshTerms"]:
            record["keywords"] = list(record["meshTerms"])
            source = "mesh"
        elif record["kciKeywords"]["en"]:
            record["keywords"] = list(record["kciKeywords"]["en"])
            source = "kci-en"
        else:
            record["keywords"] = []
            source = "none"
        record["_extra"]["keywordsSource"] = source
        counts[source] += 1
    return counts


def build_records(sources, review):
    """대상 교수를 정하고 재료 6종을 한 레코드로 합친다 (id·수동검수 적용 전)."""
    pages = sources["pages"]
    roster = sources["roster"]

    dental = set(roster["diff"].get("hospitalOnlyDental") or [])
    persons = group_roster_persons(roster["professors"], review)

    # 병원 명단에 매칭된 의대 명단 사람 (이름 → 사람)
    matched_by_name = {}
    for person in persons:
        if any(r.get("matchedInHospitalList") for r in person["records"]):
            if person["name"] in matched_by_name:
                review["rosterMatchCollision"].append({
                    "name": person["name"],
                    "note": "병원 명단에 매칭된 의대 명단 사람이 2명 이상 — 먼저 나온 사람을 사용했다",
                })
                continue
            matched_by_name[person["name"]] = person

    hospital_names = [n for n in pages if not (EXCLUDE_DENTAL and n in dental)]
    excluded_dental = [n for n in pages if EXCLUDE_DENTAL and n in dental]
    new_persons = [p for p in persons
                   if not any(r.get("matchedInHospitalList") for r in p["records"])]
    hospital_only = [n for n in hospital_names if n not in matched_by_name]

    if not INCLUDE_HOSPITAL_ONLY:
        # 팀 결정으로 병원 전용 교수를 빼는 경우 — 삭제가 아니라 목록으로 남긴다
        for name in hospital_only:
            review["excludedHospitalOnly"].append({
                "name": name,
                "note": "의대 명단에 없어 교수 구분을 추정해야 하는 교수 — "
                        "INCLUDE_HOSPITAL_ONLY=False로 제외했다",
            })
        hospital_names = [n for n in hospital_names if n not in set(hospital_only)]
        hospital_only = []

    print(f"[3] 대상 교수 결정: 병원 명단 {len(pages)}명 - 치과 {len(excluded_dental)}명 "
          f"- 병원 전용 제외 {len(review['excludedHospitalOnly'])}명 "
          f"+ 의대 신규 {len(new_persons)}명 (의대 명단 사람 {len(persons)}명 기준)")

    fetched = resolve_hospital_departments(hospital_only, pages, review)

    records = []
    for name in hospital_names:                       # (1) 병원 명단 교수
        person = matched_by_name.get(name)
        if person is not None:
            primary = person["primary"]
            record = new_record(name, compose_department(person), "roster",
                                primary["professorType"], False, True, person)
        else:
            department = fetched.get(name)
            record = new_record(name, department, "hospital-page" if department else None,
                                HOSPITAL_ONLY_PROFESSOR_TYPE, True, True, None)
            review["professorTypeInferred"].append({
                "name": name, "value": HOSPITAL_ONLY_PROFESSOR_TYPE,
                "note": "의대 명단에 없는 병원 전용 교수 — 교수 구분을 추정했다 "
                        "(계약 필드는 그대로 두고 여기에만 기록한다)",
            })
        fill_from_sources(record, sources, review)
        records.append(record)

    for person in new_persons:                        # (2) 의대 명단 신규
        primary = person["primary"]
        record = new_record(person["name"], compose_department(person), "roster",
                            primary["professorType"], False, False, person)
        if person["name"] in matched_by_name:
            review["homonymIsolated"].append({
                "name": person["name"], "department": record["department"],
                "note": "동명이인 — 이름으로 수집된 사진·전문분야·키워드·논문은 병원 명단 쪽 교수의 "
                        "것이므로 물려받지 않았다",
                "rosterNote": primary.get("homonymNote"),
            })
        fill_from_sources(record, sources, review)
        records.append(record)

    return records, excluded_dental, len(hospital_names), len(new_persons)


# ── 수동 검수 대장 ──────────────────────────────────────────────────

def apply_overrides(records, overrides, review, out_of_scope):
    """사람이 확정한 값을 마지막에 덮어쓴다. 적용·미적용을 모두 review에 남긴다."""
    for item in overrides.get("overrides") or []:
        field = item.get("field")
        if field in ASSERTION_FIELDS:
            # 값 변경이 아니라 확인 사실 — distinctPerson은 verify_distinct_persons()가,
            # idInheritance는 assign_ids()가 각각 소비한다
            continue

        name, target_department = item.get("name"), item.get("department")
        targets = [r for r in records if r["name"] == name
                   and (target_department is None or r["department"] == target_department)]
        if len(targets) != 1:
            if name in out_of_scope and not any(r["name"] == name for r in records):
                # 대상 교수가 이번 범위에서 빠진 경우 — check_overrides_applied()가
                # review.manualOverridesOutOfScope에 남긴다 (미적용 목록에 중복으로 넣지 않는다)
                continue
            review["manualOverridesUnmatched"].append({
                "override": item, "matched": len(targets),
                "note": "대상이 정확히 1명이 아니어서 적용하지 않았다 (department로 대상을 지정할 것)",
            })
            continue

        record = targets[0]
        if field in EXTRA_ONLY_FIELDS:
            before = record["_extra"].get(field)
            record["_extra"][field] = item.get("value")
        elif field in record and not field.startswith("_"):
            before = record[field]
            record[field] = item.get("value")
        else:
            review["manualOverridesUnmatched"].append({
                "override": item, "matched": len(targets),
                "note": f"알 수 없는 field '{field}' — 적용하지 않았다",
            })
            continue

        record["_extra"].setdefault("manualFields", []).append(field)
        review["manualOverridesApplied"].append({
            "name": name, "department": record["department"], "field": field,
            "before": before, "after": item.get("value"), "confirmedBy": item.get("confirmedBy"),
        })


def verify_distinct_persons(records, overrides, review):
    """'이 사람은 동명이인과 별개 인물'이라는 확인 항목을 검증한다 (id 부여 후)."""
    for item in overrides.get("overrides") or []:
        if item.get("field") != "distinctPerson":
            continue
        name, target_department = item.get("name"), item.get("department")
        targets = [r for r in records if r["name"] == name
                   and (target_department is None or r["department"] == target_department)]
        same_name = [r for r in records if r["name"] == name]
        ok = (len(targets) == 1 and len(same_name) > 1
              and len({r["id"] for r in same_name}) == len(same_name))
        entry = {
            "name": name, "department": target_department, "field": "distinctPerson",
            "matched": len(targets),
            "sameNameRecords": [{"id": r["id"], "department": r["department"]} for r in same_name],
            "result": "확인됨 — 동명이인이 각각 다른 id를 받았다" if ok else "확인 실패",
            "confirmedBy": item.get("confirmedBy"),
        }
        (review["manualOverridesApplied"] if ok else review["manualOverridesUnmatched"]).append(entry)


# ── id 대장 ─────────────────────────────────────────────────────────

def inheritance_basis(record, overrides):
    """소속이 바뀐 교수의 id를 승계해도 되는 근거가 있는지 — 없으면 None.

    이름이 같고 소속만 다르면 '같은 사람이 옮긴 것'처럼 보이지만, 퇴직자가 빠지고 같은 이름의
    신규 교수가 들어온 경우도 똑같이 보인다. 그때 id를 물려주면 예전 찜(localStorage)이
    엉뚱한 사람을 가리키게 된다. 그래서 자동으로 판단하지 않고, 사람이 확인한 근거가 있을 때만 승계한다.
      - manual_overrides에 그 교수의 department 확정 항목이 있고 값이 지금 소속과 같을 때
      - 또는 명시적 승계 허용 항목(field: "idInheritance", value: true)이 있을 때
    """
    for item in overrides.get("overrides") or []:
        if item.get("name") != record["name"]:
            continue
        target = item.get("department")
        if item.get("field") == "department" and item.get("value") == record["department"]:
            return "수동 검수 대장의 department 확정 항목"
        if (item.get("field") == "idInheritance" and item.get("value")
                and target in (None, record["department"])):
            return "수동 검수 대장의 idInheritance 승계 허용 항목"
    return None


def assign_ids(records, review, overrides):
    """id 대장을 읽어 기존 id를 재사용하고, 새 교수에게만 다음 번호를 준다.

    id는 프론트 찜(localStorage)이 붙잡고 있는 유일한 열쇠라 절대 바뀌면 안 된다.
    """
    registry = load_json(REGISTRY_PATH) if REGISTRY_PATH.exists() else {}
    entries = list(registry.get("entries") or [])
    next_number = int(registry.get("nextNumber") or (len(entries) + 1))

    by_key = {(e["name"], e.get("department")): e for e in entries}
    # ②번 규칙(소속 변경)은 '이번 실행 전에 이미 대장에 있던' 항목만 대상으로 한다.
    # 이번 실행에서 새로 만든 항목까지 후보에 넣으면 동명이인 2명이 같은 id를 받는다.
    previous_by_name = {}
    for entry in entries:
        previous_by_name.setdefault(entry["name"], []).append(entry)

    today = date.today().isoformat()
    claimed = set()  # 이번 실행에서 이미 쓴 id — 한 id를 두 사람이 받는 일을 막는다
    reused = moved = created = 0

    # 최초 부여 순서: 가나다순 (동명이인은 소속순)
    for record in sorted(records, key=lambda r: (r["name"], r["department"] or "")):
        key = (record["name"], record["department"])
        entry = by_key.get(key)
        if entry is not None and entry["id"] not in claimed:   # ① 이름+소속이 그대로 → 같은 id
            record["id"] = entry["id"]
            claimed.add(entry["id"])
            reused += 1
            continue

        candidates = [e for e in (previous_by_name.get(record["name"]) or [])
                      if e["id"] not in claimed]
        held = False
        if len(candidates) == 1:
            entry = candidates[0]
            basis = inheritance_basis(record, overrides)
            if basis:                               # ② 사람이 확인한 소속 변경 → id 승계
                previous = entry.get("department")
                entry.setdefault("departmentHistory", []).append(
                    {"department": previous, "until": today})
                entry["department"] = record["department"]
                by_key[key] = entry
                record["id"] = entry["id"]
                claimed.add(entry["id"])
                moved += 1
                review["idDepartmentChanged"].append({
                    "id": entry["id"], "name": record["name"],
                    "from": previous, "to": record["department"], "basis": basis,
                })
                continue
            # 근거가 없으면 승계하지 않는다 — 퇴직자와 신규 동명이인이 교체된 경우
            # 예전 찜이 다른 사람에게 넘어가기 때문이다
            held = True
            review["idInheritanceHeld"].append({
                "name": record["name"], "department": record["department"],
                "existing": {"id": entry["id"], "department": entry.get("department")},
                "note": "동일 이름·다른 소속 — 승계 보류(사람 확인 필요). 새 id를 부여했다.",
                "howTo": "같은 사람이 맞으면 manual_overrides.json에 department 확정 항목이나 "
                         'field: "idInheritance" 항목을 넣고 다시 실행한다.',
            })

        if candidates and not held:                 # ③ 동명이인인데 소속이 안 맞음 → 새 번호 + 기록
            review["idAmbiguous"].append({
                "name": record["name"], "department": record["department"],
                "note": "같은 이름의 대장 항목이 여러 개인데 소속이 일치하지 않아 새 번호를 부여했다",
                "existing": [{"id": c["id"], "department": c.get("department")} for c in candidates],
            })
        new_entry = {"id": f"P-{next_number:03d}", "name": record["name"],
                     "department": record["department"], "firstAssignedAt": today,
                     "departmentHistory": []}
        next_number += 1
        entries.append(new_entry)
        by_key[key] = new_entry
        record["id"] = new_entry["id"]
        claimed.add(new_entry["id"])
        created += 1

    entries.sort(key=lambda e: int(e["id"].split("-")[1]))
    save_json(REGISTRY_PATH, {
        "_comment": "교수 id 대장 — 한 번 부여한 id는 영원히 바꾸지 않는다 (프론트 찜이 id로 저장된다). "
                    "조립기가 자동으로 갱신하므로 손으로 고치지 않는다. 구조 설명은 data/input/README.md 참고.",
        "updatedAt": today,
        "nextNumber": next_number,
        "entries": entries,
    })
    print(f"[6] id 부여: 재사용 {reused}명 / 소속변경 승계 {moved}명 / 신규 {created}명 "
          f"(승계 보류 {len(review['idInheritanceHeld'])}명, 대장 누적 {len(entries)}건, "
          f"다음 번호 P-{next_number:03d})")
    return {"reused": reused, "moved": moved, "new": created, "registrySize": len(entries)}


# ── 정합 검사 ───────────────────────────────────────────────────────

def check_overrides_applied(records, overrides, problems, review, out_of_scope):
    """수동 검수 대장이 '의도한 그 사람'에게 적용됐는지 검증한다.

    동명이인이 있는데 department 지정이 없으면 엉뚱한 사람에게 적용될 수 있으므로,
    대상 지정과 실제 반영값을 모두 확인한다.
    대상 교수가 이번 대상 범위에서 빠진 경우(치과 제외·병원 전용 제외 등)는 위반이 아니라
    review.manualOverridesOutOfScope로 남긴다 — 사람이 확인한 사실 자체는 그대로 유효하다.
    """
    checked = 0
    for item in overrides.get("overrides") or []:
        name, target, field = item.get("name"), item.get("department"), item.get("field")
        same_name = [r for r in records if r["name"] == name]
        targets = [r for r in same_name if target is None or r["department"] == target]

        if not same_name:
            if name in out_of_scope:
                review["manualOverridesOutOfScope"].append({
                    "name": name, "field": field, "value": item.get("value"),
                    "note": "대상 교수가 이번 대상 범위에서 제외돼 적용되지 않았다 "
                            "(대장 항목은 그대로 둔다 — 범위가 바뀌면 다시 적용된다)",
                })
            else:
                problems.append(f"수동검수 {name}/{field}: 그 이름의 교수가 명단에 없다")
            continue
        if len(same_name) > 1 and target is None:
            problems.append(f"수동검수 {name}/{field}: 동명이인 {len(same_name)}명인데 "
                            f"department 지정이 없어 대상이 모호하다")
            continue
        if len(targets) != 1:
            problems.append(f"수동검수 {name}/{field}: 대상이 {len(targets)}명이다 "
                            f"(department={target!r} — 정확히 1명이어야 한다)")
            continue
        if field in ASSERTION_FIELDS:
            continue  # 값 변경이 아님 — verify_distinct_persons()·assign_ids()가 따로 검증한다

        record = targets[0]
        actual = record["_extra"].get(field) if field in EXTRA_ONLY_FIELDS else record.get(field)
        if actual != item.get("value"):
            problems.append(f"수동검수 {name}/{field}: 확정값이 반영되지 않았다 "
                            f"({actual!r} != {item.get('value')!r})")
        checked += 1
    return checked


def check_integrity(contract_records, records, sources, review, overrides, out_of_scope):
    """자체 정합 검사. 위반은 모아서 한 번에 보고한다."""
    problems = []
    # 계약 모양의 기준은 샘플 파일이지만 샘플은 아직 v6.3이다.
    # v6.4(labName 삭제)·v6.5(meshTerms·kciKeywords 보존) 개정분을 여기서 명시적으로 반영한다.
    allowed = set(load_json(SAMPLE_PATH)["professors"][0].keys())
    if not EMIT_LABNAME:
        allowed.discard("labName")
    allowed.update(V65_KEYWORD_FIELDS)
    overrides_checked = check_overrides_applied(records, overrides, problems, review, out_of_scope)

    # 동명이인에게 남의 확정값이 통과되지 않도록 대상 지정(department)까지 키에 넣는다
    override_values = {}
    for item in overrides.get("overrides") or []:
        key = (item.get("name"), item.get("department"), item.get("field"))
        override_values.setdefault(key, []).append(item.get("value"))

    def allowed_override(name, department, field):
        """이 교수에게 실제로 적용될 수 있는 확정값만 돌려준다."""
        values = list(override_values.get((name, department, field)) or [])
        values += list(override_values.get((name, None, field)) or [])  # 이름만 지정한 항목
        return values

    ids = [r["id"] for r in contract_records]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        problems.append(f"id 중복 {len(duplicated)}건: {duplicated}")

    no_identifier = contract_violation = 0
    for record in contract_records:
        name = record["name"]
        if set(record.keys()) != allowed:
            contract_violation += 1
            problems.append(f"{name}: 계약 밖 칸 또는 누락 — {sorted(set(record) ^ allowed)}")
        if "labName" in record and not EMIT_LABNAME:
            problems.append(f"{name}: labName은 v6.4에서 삭제된 칸이다")
        if not record["id"] or not record["name"]:
            problems.append(f"{name}: id/name이 비어 있다")
        if record["professorType"] not in PROFESSOR_TYPES:
            problems.append(f"{name}: professorType 허용값 아님 — {record['professorType']!r}")
        if not (record["department"] or "").strip():
            problems.append(f"{name}: department가 비어 있다 (백엔드 스키마가 문자열을 요구한다)")

        # 원칙 2 — 값이 없으면 null. 빈 문자열을 쓰지 않는다
        for field in ("profileImageUrl", "email", "homepageUrl", "labName"):
            if field in record and record[field] is not None and not str(record[field]).strip():
                problems.append(f"{name}: {field}가 빈 문자열이다 (null이어야 한다)")

        # 원칙 1 (v6.4) — pmid와 kciId가 둘 다 없는 논문 0건
        for paper in record["papers"]:
            if set(paper.keys()) != set(PAPER_FIELDS):
                problems.append(f"{name}: 논문 칸이 계약과 다르다 — "
                                f"{sorted(set(paper) ^ set(PAPER_FIELDS))}")
            if not (paper.get("pmid") or "").strip() and not (paper.get("kciId") or "").strip():
                no_identifier += 1
                problems.append(f"{name}: pmid·kciId가 둘 다 없는 논문 — {paper.get('title')!r}")
        if len(record["papers"]) > PAPERS_LIMIT:
            problems.append(f"{name}: 대표 논문 {len(record['papers'])}편 (최대 {PAPERS_LIMIT})")

        # latestPaper — v6.5 후보 조건(pmid + 완전한 YYYY-MM-DD)과 원본 일치 확인.
        # 대표 논문 3편에 들어 있을 필요는 없다 (최신 논문이 연도-only면 그 아래에서 고르기 때문)
        latest = record["latestPaper"]
        if latest:
            source_all = {p["pmid"]: p for p in ((sources["papers"].get(name) or {}).get("allPapers") or [])
                          if p.get("pmid")}
            if set(latest.keys()) != {"pmid", "publishedAt"}:
                problems.append(f"{name}: latestPaper 칸이 계약과 다르다 — {sorted(latest)}")
            if not latest.get("pmid"):
                problems.append(f"{name}: latestPaper에 pmid가 없다 (KCI 전용은 후보가 될 수 없다)")
            elif not FULL_DATE_PATTERN.match(latest.get("publishedAt") or ""):
                problems.append(f"{name}: latestPaper.publishedAt이 YYYY-MM-DD가 아니다 "
                                f"— {latest.get('publishedAt')!r}")
            else:
                origin = source_all.get(latest["pmid"])
                if origin is None:
                    problems.append(f"{name}: latestPaper({latest['pmid']})가 원본 논문 목록에 없다")
                elif (origin.get("publishedAt") or "").strip() != latest["publishedAt"]:
                    problems.append(f"{name}: latestPaper 발행일이 원본과 다르다 (pmid {latest['pmid']})")
                else:
                    newer = [p for p in source_all.values()
                             if FULL_DATE_PATTERN.match((p.get("publishedAt") or "").strip())
                             and (p["publishedAt"].strip(), p["pmid"]) > (latest["publishedAt"], latest["pmid"])]
                    if newer:
                        problems.append(f"{name}: latestPaper보다 최신인 후보가 {len(newer)}편 남아 있다")
        elif record["papers"]:
            review["latestPaperMissingWithPapers"].append(
                {"id": record["id"], "name": name, "papers": len(record["papers"])})

        # 원칙 4 — 값이 원본 그대로인지 (= 지어낸 값 0건 확인)
        source_papers = {p["pmid"]: p for p in ((sources["papers"].get(name) or {}).get("papers") or [])}
        for paper in record["papers"]:
            origin = source_papers.get(paper["pmid"])
            if origin is None:
                problems.append(f"{name}: 원본에 없는 논문 pmid {paper['pmid']}")
            elif (paper["title"], paper.get("journal"), paper.get("year")) != (
                    origin["title"], origin.get("journal"), origin.get("year")):
                problems.append(f"{name}: 논문 값이 원본과 다르다 (pmid {paper['pmid']})")

        department = record["department"]
        confirmed_specialties = {v for values in allowed_override(name, department, "specialties")
                                 for v in (values or [])}
        if set(record["specialties"]) \
                - set((sources["specialties"].get(name) or {}).get("specialties") or []) \
                - confirmed_specialties:
            problems.append(f"{name}: 원본에 없는 전문분야가 들어 있다")
        # v6.5 — 키워드 원본 필드가 모든 교수에게 존재하고 배열인지
        if not isinstance(record["meshTerms"], list):
            problems.append(f"{name}: meshTerms가 배열이 아니다")
        elif len(record["meshTerms"]) > KEYWORDS_LIMIT:
            problems.append(f"{name}: meshTerms {len(record['meshTerms'])}개 (상한 {KEYWORDS_LIMIT})")
        if not isinstance(record.get("keywordsKo"), list):
            problems.append(f"{name}: keywordsKo가 없거나 배열이 아니다 — {record.get('keywordsKo')!r}")
        elif len(record["keywordsKo"]) > len(record["keywords"]):
            problems.append(f"{name}: keywordsKo({len(record['keywordsKo'])})가 "
                            f"keywords({len(record['keywords'])})보다 많다")
        kci = record["kciKeywords"]
        if not isinstance(kci, dict) or set(kci) != {"ko", "en"}:
            problems.append(f"{name}: kciKeywords 객체가 없거나 ko/en 칸이 어긋난다 — {kci!r}")
        else:
            for language in ("ko", "en"):
                if not isinstance(kci[language], list):
                    problems.append(f"{name}: kciKeywords.{language}가 배열이 아니다")
                elif len(kci[language]) > KEYWORDS_LIMIT:
                    problems.append(f"{name}: kciKeywords.{language} {len(kci[language])}개 "
                                    f"(상한 {KEYWORDS_LIMIT})")

        # 원칙 4 — 키워드도 원본 그대로인지
        if set(record["meshTerms"]) - set((sources["meta"].get(name) or {}).get("keywordsCandidate") or []):
            problems.append(f"{name}: 원본에 없는 MeSH 용어가 들어 있다")
        kci_entry = (sources.get("kci") or {}).get(record["id"]) or {}
        if isinstance(kci, dict):
            for language in ("ko", "en"):
                if not kci.get(language):
                    continue
                source_terms = {t.strip() for paper in (kci_entry.get("papers") or [])
                                for t in ((paper.get("keywords") or {}).get(language) or [])
                                if isinstance(t, str) and t.strip()}
                if set(kci[language]) - source_terms:
                    problems.append(f"{name}: 원본에 없는 KCI 키워드가 들어 있다 ({language})")

        # v6.5 선택 규칙: meshTerms 우선 → kciKeywords.en → []. 부분 병합 금지
        confirmed_keywords = {v for values in allowed_override(name, department, "keywords")
                              for v in (values or [])}
        if not confirmed_keywords:
            if record["meshTerms"]:
                expected = list(record["meshTerms"])
            elif isinstance(kci, dict) and kci.get("en"):
                expected = list(kci["en"])
            else:
                expected = []
            if record["keywords"] != expected:
                problems.append(f"{name}: keywords가 v6.5 선택 규칙과 다르다 "
                                f"(meshTerms {len(record['meshTerms'])}개 · kciKeywords.en "
                                f"{len(kci.get('en') or []) if isinstance(kci, dict) else 0}개)")
        for field, source_value in (("profileImageUrl", sources["images"].get(name)),
                                    ("email", (sources["meta"].get(name) or {}).get("email")),
                                    ("homepageUrl", sources["pages"].get(name))):
            value = record[field]
            if value is not None and value != source_value \
                    and value not in allowed_override(name, department, field):
                problems.append(f"{name}: {field} 값이 원본과 다르다")

    print("[7] 정합 검사")
    print(f"    id 중복                 : {len(duplicated)}건")
    print(f"    식별자(pmid·kciId) 없는 논문: {no_identifier}건")
    print(f"    계약 밖 칸 사용          : {contract_violation}건 "
          f"(labName 출력={EMIT_LABNAME}, papers 칸={list(PAPER_FIELDS)})")
    print(f"    수동검수 대상·반영 확인   : {overrides_checked}건 "
          f"(확인 사실 항목 {len([o for o in (overrides.get('overrides') or []) if o.get('field') in ASSERTION_FIELDS])}건 별도 검증)")
    print(f"    지어낸 값·null 규칙 위반  : "
          f"{len([p for p in problems if '원본' in p or '빈 문자열' in p])}건")
    print(f"    위반 총계               : {len(problems)}건")
    for problem in problems[:20]:
        print(f"      - {problem}")
    if len(problems) > 20:
        print(f"      ... 외 {len(problems) - 20}건")
    return problems


def report(contract_records, review, excluded_dental, hospital_total,
           hospital_target_count, new_person_count, id_stats, problems):
    print()
    print("=" * 78)
    print("[9] 최종 교수 수 합산식")
    print(f"    병원 명단(professor_pages)                : {hospital_total}명")
    print(f"    - 치과 계열 제외 (EXCLUDE_DENTAL={EXCLUDE_DENTAL})     : -{len(excluded_dental)}명")
    print(f"    - 병원 전용 제외 (INCLUDE_HOSPITAL_ONLY={INCLUDE_HOSPITAL_ONLY}) : "
          f"-{len(review['excludedHospitalOnly'])}명")
    print(f"    = 병원 명단 대상                          : {hospital_target_count}명")
    print(f"    + 의대 명단 신규(병원 명단에 없는 교수)     : +{new_person_count}명")
    print(f"    - 소속 미확보로 제외                      : -{len(review['droppedNoDepartment'])}명")
    print(f"    = professors.json 수록                   : {len(contract_records)}명")
    print()
    total = len(contract_records) or 1
    print("    필드별 채움율")
    for field in ("profileImageUrl", "professorType", "department", "specialties",
                  "keywords", "email", "homepageUrl", "papers", "latestPaper", "labName"):
        if not contract_records or field not in contract_records[0]:
            continue  # labName은 v6.4에서 삭제 (EMIT_LABNAME=False면 칸 자체가 없다)
        filled = sum(1 for r in contract_records if r[field] not in (None, [], ""))
        note = "  ← 출처 없음(v6.3 호환용)" if field == "labName" else ""
        print(f"      {field:<17} {filled:>3}/{total}  ({filled * 100 // total:>3}%){note}")
    for field, label in (("meshTerms", "meshTerms"), ("keywordsKo", "keywordsKo"),
                         ("kciKeywords", "kciKeywords.ko/.en")):
        if field in ("meshTerms", "keywordsKo"):
            filled = sum(1 for r in contract_records if r[field])
            print(f"      {label:<17} {filled:>3}/{total}  ({filled * 100 // total:>3}%)")
        else:
            ko = sum(1 for r in contract_records if r["kciKeywords"]["ko"])
            en = sum(1 for r in contract_records if r["kciKeywords"]["en"])
            print(f"      {label:<17} ko {ko:>3}/{total} · en {en:>3}/{total}")
    papers = [p for r in contract_records for p in r["papers"]]
    print(f"      {'papers 식별자':<16} 논문 {len(papers)}편 — "
          f"pmid {sum(1 for p in papers if p.get('pmid'))}편 / "
          f"kciId {sum(1 for p in papers if p.get('kciId'))}편 (KCI 수집 전)")
    print()
    print("    review 요약 (professors_extra.json의 review 참고)")
    for key, items in review.items():
        if items:
            print(f"      {key:<30} {len(items)}건")
    print(f"      {'excludedDental':<30} {len(excluded_dental)}건")
    print()
    print(f"    출력   : {OUTPUT_PATH}")
    print(f"             {EXTRA_PATH}")
    print(f"    id 대장: {REGISTRY_PATH} (누적 {id_stats['registrySize']}건)")
    print(f"    정합 검사: 위반 {len(problems)}건 → {'통과' if not problems else '확인 필요'}")
    print("=" * 78)


# ── 실행 ────────────────────────────────────────────────────────────

def main():
    # 콘솔이 cp949면 '—' 같은 문자에서 UnicodeEncodeError로 죽는다.
    # 인코딩은 그대로 두고 표현 못 하는 글자만 대체해 실행이 멈추지 않게 한다.
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    print("=" * 78)
    print("D단계 최종 조립기 — professors.json 생성")
    print("=" * 78)

    roster = load_json(ROSTER_PATH)
    pages = load_json(PAGES_PATH)
    images_file = load_json(IMAGES_PATH)
    specialties_file = load_json(SPECIALTIES_PATH)
    papers_file = load_json(PAPERS_PATH)
    meta_file = load_json(META_PATH)
    overrides = load_json(OVERRIDES_PATH) if OVERRIDES_PATH.exists() else {"overrides": []}
    kci_file = load_json(KCI_PATH) if KCI_PATH.exists() else None
    kci_professors = (kci_file or {}).get("professors") or {}

    sources = {
        "roster": roster,
        "pages": pages,
        "images": images_file["images"],
        "specialties": specialties_file["specialties"],
        "papers": papers_file["professors"],
        "meta": meta_file["professors"],
        "kci": kci_professors,
    }
    source_dates = {
        "roster_crawled": roster["collectedAt"],
        **({"kci_papers": kci_file["collectedAt"]} if kci_file else {}),
        "profile_images": images_file["collectedAt"],
        "specialties": specialties_file["collectedAt"],
        "professors_papers": papers_file["collectedAt"],
        "professors_enriched_meta": meta_file["collectedAt"],
    }
    collected_at = max(source_dates.values())  # 원칙 4: 원본 데이터 파일의 기준일

    print(f"[1] 입력 읽기 — 의대 명단 {len(roster['professors'])}건 / 병원 명단 {len(pages)}명 / "
          f"사진 {len(sources['images'])} / 전문분야 {len(sources['specialties'])} / "
          f"논문 {len(sources['papers'])} / 메타 {len(sources['meta'])} / "
          f"KCI {len(kci_professors)} / 수동검수 {len(overrides.get('overrides') or [])}건")
    if not kci_professors:
        print(f"    ! KCI 산출물이 없다({KCI_PATH.name}) → kciKeywords는 전부 []로 둔다")
    print(f"    collectedAt = {collected_at} (원본 기준일 {source_dates})")

    review = {key: [] for key in REVIEW_KEYS}

    print("[2] 의대 명단을 사람 단위로 묶는 중...")
    records, excluded_dental, hospital_target_count, new_person_count = build_records(sources, review)
    print(f"[5] 레코드 병합 완료 — {len(records)}명")

    # 이번 대상 범위에서 빠진 교수 — 수동 검수 항목이 여기 걸리면 위반이 아니라 review로 남긴다
    out_of_scope = (set(excluded_dental)
                    | {i["name"] for i in review["excludedHospitalOnly"]})
    apply_overrides(records, overrides, review, out_of_scope)
    print(f"    수동 검수 대장: 적용 {len(review['manualOverridesApplied'])}건 / "
          f"미적용 {len(review['manualOverridesUnmatched'])}건")

    # 소속을 끝내 확보하지 못한 교수는 계약 파일에 넣지 않는다.
    # (계약 1-1의 department는 값이 있어야 하는 칸이라 null을 넣으면 백엔드가 파일을 못 읽는다.
    #  그렇다고 지어낼 수도 없으므로 제외하고 review에 남긴다 — 원칙 2)
    for record in [r for r in records if not (r["department"] or "").strip()]:
        review["droppedNoDepartment"].append({
            "name": record["name"],
            "note": "소속(department)을 확보하지 못해 professors.json에서 제외했다 (지어내지 않는다)",
        })
    records = [r for r in records if (r["department"] or "").strip()]

    id_stats = assign_ids(records, review, overrides)
    verify_distinct_persons(records, overrides, review)

    # KCI 산출물은 교수 id를 키로 쓰므로 id 부여 뒤에 붙인다
    fill_kci_keywords(records, kci_professors, review)
    keyword_sources = resolve_keywords(records)
    print(f"    keywords 선택: MeSH {keyword_sources['mesh']}명 / "
          f"KCI 영문 {keyword_sources['kci-en']}명 / 없음 {keyword_sources['none']}명"
          + (f" / 수동 확정 {keyword_sources['manual']}명" if keyword_sources["manual"] else ""))

    # keywordsKo — 사전을 읽기만 한다 (번역 로직 없음). 사전이 없으면 경고만 하고 계속한다
    ko_dictionary, ko_warning = load_keyword_ko_dictionary()
    if ko_warning:
        print(f"    ! {ko_warning}")
    ko_stats, ko_missing = fill_keywords_ko(records, ko_dictionary)
    if ko_dictionary is not None:
        print(f"    keywordsKo: 사전 {len(ko_dictionary)}개 항목 → 채움 {ko_stats['filled']}명 / "
              f"빈 배열 {ko_stats['empty']}명 / 사전에 없는 용어 {len(ko_missing)}종")

    contract_records = [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]
    contract_records.sort(key=lambda r: (r["name"], r["department"]))
    out_of_scope |= {i["name"] for i in review["droppedNoDepartment"]}
    problems = check_integrity(contract_records, records, sources, review, overrides, out_of_scope)

    print("[8] 출력 저장 중...")
    save_json(OUTPUT_PATH, {
        "_comment": "D단계 조립 결과. 개인정보(이메일 등)를 포함하므로 저장소에 커밋하지 않는다 "
                    "(data/output/은 .gitignore 대상). latestPaper는 백엔드 내부 필드로, "
                    "계약 응답(교수 카드·상세)에는 나가지 않는다.",
        "collectedAt": collected_at,
        "professors": contract_records,
    })

    extra_records = []
    for record in records:
        extra = dict(record["_extra"])
        extra.update({"id": record["id"], "name": record["name"],
                      "department": record["department"], "professorType": record["professorType"]})
        extra_records.append(extra)
    extra_records.sort(key=lambda r: int(r["id"].split("-")[1]))

    save_json(EXTRA_PATH, {
        "_comment": "계약 밖 내부 데이터. 초록 검색 등 후속 구현과 검수에 쓴다. 커밋하지 않는다.",
        "collectedAt": collected_at,
        "sourceCollectedAt": source_dates,
        "settings": {
            "EXCLUDE_DENTAL": EXCLUDE_DENTAL,
            "INCLUDE_HOSPITAL_ONLY": INCLUDE_HOSPITAL_ONLY,
            "MERGE_CROSS_APPOINTMENTS": MERGE_CROSS_APPOINTMENTS,
            "DEPARTMENT_INCLUDE_DIVISION": DEPARTMENT_INCLUDE_DIVISION,
            "FETCH_HOSPITAL_DEPARTMENT": FETCH_HOSPITAL_DEPARTMENT,
            "HOSPITAL_ONLY_PROFESSOR_TYPE": HOSPITAL_ONLY_PROFESSOR_TYPE,
            "PAPERS_LIMIT": PAPERS_LIMIT,
            "KEYWORDS_LIMIT": KEYWORDS_LIMIT,
        },
        "keywordKoDictionary": {
            "path": str(KEYWORD_KO_DICT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "exists": ko_dictionary is not None,
            "warning": ko_warning,
            "entries": len(ko_dictionary) if ko_dictionary is not None else 0,
            "professorsFilled": ko_stats["filled"],
            "professorsEmpty": ko_stats["empty"],
            "missingTermCount": len(ko_missing),
            # 사전을 만드는 담당자가 바로 쓸 수 있도록 자주 쓰이는 미번역 용어를 남긴다
            "missingTermsTop": [{"term": t, "professors": n} for t, n in ko_missing.most_common(50)],
        },
        "excludedDental": {
            "count": len(excluded_dental),
            "reason": "치과 계열은 이번 MVP 대상에서 제외했다 (EXCLUDE_DENTAL=True). "
                      "회의에서 뒤집힐 수 있어 삭제하지 않고 명단을 남긴다.",
            "names": excluded_dental,
        },
        "professors": extra_records,
        "review": review,
        "sourceReviews": {
            "roster_crawled": roster.get("review"),
            "professors_papers": {k: (len(v) if isinstance(v, list) else v)
                                  for k, v in (papers_file.get("review") or {}).items()},
            "professors_enriched_meta": len(meta_file.get("review") or []),
        },
    })

    report(contract_records, review, excluded_dental, len(pages),
           hospital_target_count, new_person_count, id_stats, problems)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
