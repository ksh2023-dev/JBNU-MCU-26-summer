"""D단계 — 최종 조립기. 수집 산출물을 병합해 데이터 계약 v6.3 모양의 professors.json을 만든다.

입력 (재료 6종)
  data/output/roster_crawled.json            의대 명단 (교수구분·교실·직위·전화·동명이인 메모·diff)
  data/input/professor_pages.json            병원 교수 프로필 URL (= 병원 명단 243명, homepageUrl 재료)
  data/output/profile_images.json            프로필 사진 URL
  data/output/specialties.json               전문진료분야
  data/output/professors_papers.json         대표 논문 3편 · latestPaper · allPapers
  data/output/professors_enriched_meta.json  영문명 · MeSH 키워드 후보 · 이메일

관리 파일 (사람이 관리, 커밋 대상 — 구조 설명은 data/input/README.md)
  data/input/manual_overrides.json           수동 검수 대장 (사람 확정이 자동 수집을 이긴다)
  data/input/id_registry.json                id 대장 (한 번 부여한 id는 영원히 불변)

출력 (data/output/ — .gitignore 대상, 커밋하지 않는다)
  data/output/professors.json                   백엔드가 읽는 최종 파일. 샘플과 같은 칸만 담는다
  data/output/professors_extra.json             계약 밖 내부 데이터 (영문명·초록·근거·제외 명단·review)
  data/output/_cache_hospital_departments.json  병원 프로필에서 읽은 진료과 캐시 (재실행 시 재조회 생략)

계약 0장 4원칙
  1. pmid 없는 논문은 넣지 않는다
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
HOSPITAL_ONLY_PROFESSOR_TYPE = "임상의학"  # 의대 명단에 없는 병원 교수의 교수 구분 (추정 → review 기록)
PAPERS_LIMIT = 3                    # 대표 논문 수 (계약 1-2: 최신 1편 + 인용 상위 2편)

SLEEP_SECONDS = 0.5                 # 서버 예절: 병원 페이지 호출 사이 대기
TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

import json
import sys
import time
import urllib.request
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

OVERRIDES_PATH = ROOT / "data" / "input" / "manual_overrides.json"
REGISTRY_PATH = ROOT / "data" / "input" / "id_registry.json"

SAMPLE_PATH = ROOT / "data" / "sample" / "professors.sample.json"
OUTPUT_PATH = ROOT / "data" / "output" / "professors.json"
EXTRA_PATH = ROOT / "data" / "output" / "professors_extra.json"
CACHE_PATH = ROOT / "data" / "output" / "_cache_hospital_departments.json"

PROFESSOR_TYPES = ("기초의학", "임상의학", "의학교육학", "인문사회의학")

# 계약 밖이지만 수동 검수 대장으로 고칠 수 있는 필드 (professors_extra.json 전용)
EXTRA_ONLY_FIELDS = ("nameEn",)

REVIEW_KEYS = (
    "professorTypeInferred",        # 교수 구분을 추정한 교수 (계약 필드는 오염시키지 않는다)
    "departmentFetchFailed",        # 병원 프로필에서 진료과를 못 읽은 교수
    "droppedNoDepartment",          # 소속을 끝내 확보하지 못해 제외한 교수
    "crossAppointmentMerged",       # 두 교실에 걸친 사람을 한 명으로 합친 기록
    "homonymIsolated",              # 동명이인이라 이름 기반 자료를 물려주지 않은 기록
    "rosterMatchCollision",
    "latestPaperDropped",           # 발행일이 없어 featured 후보에서 뺀 논문
    "latestPaperMissingWithPapers",
    "manualOverridesApplied",
    "manualOverridesUnmatched",
    "idDepartmentChanged",
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
    return {
        # ── 계약 필드 (샘플과 같은 칸·같은 순서) ──
        "id": None,
        "name": name,
        "profileImageUrl": None,
        "professorType": professor_type,
        "department": department,
        "labName": None,           # 출처 없음 → null (계약 4장)
        "specialties": [],
        "keywords": [],
        "email": None,
        "homepageUrl": None,
        "latestPaper": None,       # 백엔드 내부 필드 (API ③ 정렬용, 응답에는 안 나감)
        "papers": [],
        # ── 계약 밖 (professors_extra.json으로 나간다) ──
        "_extra": {
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
    }


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
    record["keywords"] = list(meta_entry.get("keywordsCandidate") or [])   # 영어 MeSH 후보(필터판) 그대로
    record["email"] = meta_entry.get("email") or None
    record["_extra"]["nameEn"] = meta_entry.get("nameEn") or None
    record["_extra"]["nameEnVariants"] = list(meta_entry.get("nameEnVariants") or [])
    record["_extra"]["keywordsCandidateAll"] = list(meta_entry.get("keywordsCandidateAll") or [])
    record["_extra"]["evidence"] = meta_entry.get("evidence")

    paper_entry = sources["papers"].get(name) or {}
    kept = [p for p in (paper_entry.get("papers") or []) if (p.get("pmid") or "").strip()]  # 원칙 1
    record["papers"] = [{"title": p["title"], "journal": p.get("journal"),
                         "year": p.get("year"), "pmid": p["pmid"]} for p in kept[:PAPERS_LIMIT]]
    record["_extra"]["allPapers"] = list(paper_entry.get("allPapers") or [])

    latest = paper_entry.get("latestPaper")
    if latest and (latest.get("pmid") or "").strip() and (latest.get("publishedAt") or "").strip():
        record["latestPaper"] = {"pmid": latest["pmid"], "publishedAt": latest["publishedAt"]}
    elif latest:
        # 발행일이 없으면 API ③의 정렬 근거가 없다 → 후보에서 빠진다 (계약 2장 API ③ · 원칙 2)
        review["latestPaperDropped"].append({
            "name": name, "pmid": latest.get("pmid"),
            "note": "latestPaper에 발행일(publishedAt)이 없어 featured 후보에서 제외",
        })


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

    print(f"[3] 대상 교수 결정: 병원 명단 {len(pages)}명 - 치과 {len(excluded_dental)}명 "
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

def apply_overrides(records, overrides, review):
    """사람이 확정한 값을 마지막에 덮어쓴다. 적용·미적용을 모두 review에 남긴다."""
    for item in overrides.get("overrides") or []:
        field = item.get("field")
        if field == "distinctPerson":
            continue  # 값 변경이 아니라 확인 사실 — id 부여 뒤 verify_distinct_persons()가 검증한다

        name, target_department = item.get("name"), item.get("department")
        targets = [r for r in records if r["name"] == name
                   and (target_department is None or r["department"] == target_department)]
        if len(targets) != 1:
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

def assign_ids(records, review):
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
        if len(candidates) == 1:                    # ② 소속만 바뀐 같은 사람 → id 유지
            entry = candidates[0]
            previous = entry.get("department")
            entry.setdefault("departmentHistory", []).append({"department": previous, "until": today})
            entry["department"] = record["department"]
            by_key[key] = entry
            record["id"] = entry["id"]
            claimed.add(entry["id"])
            moved += 1
            review["idDepartmentChanged"].append({
                "id": entry["id"], "name": record["name"],
                "from": previous, "to": record["department"],
            })
            continue

        if candidates:                              # ③ 동명이인인데 소속이 안 맞음 → 새 번호 + 기록
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
    print(f"[6] id 부여: 재사용 {reused}명 / 소속변경 유지 {moved}명 / 신규 {created}명 "
          f"(대장 누적 {len(entries)}건, 다음 번호 P-{next_number:03d})")
    return {"reused": reused, "moved": moved, "new": created, "registrySize": len(entries)}


# ── 정합 검사 ───────────────────────────────────────────────────────

def check_integrity(contract_records, sources, review, overrides):
    """자체 정합 검사. 위반은 모아서 한 번에 보고한다."""
    problems = []
    allowed = set(load_json(SAMPLE_PATH)["professors"][0].keys())  # 샘플이 곧 계약 모양
    override_values = {(o.get("name"), o.get("field")): o.get("value")
                       for o in (overrides.get("overrides") or [])}

    ids = [r["id"] for r in contract_records]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        problems.append(f"id 중복 {len(duplicated)}건: {duplicated}")

    no_pmid = contract_violation = 0
    for record in contract_records:
        name = record["name"]
        if set(record.keys()) != allowed:
            contract_violation += 1
            problems.append(f"{name}: 계약 밖 칸 또는 누락 — {sorted(set(record) ^ allowed)}")
        if not record["id"] or not record["name"]:
            problems.append(f"{name}: id/name이 비어 있다")
        if record["professorType"] not in PROFESSOR_TYPES:
            problems.append(f"{name}: professorType 허용값 아님 — {record['professorType']!r}")
        if not (record["department"] or "").strip():
            problems.append(f"{name}: department가 비어 있다 (백엔드 스키마가 문자열을 요구한다)")

        # 원칙 2 — 값이 없으면 null. 빈 문자열을 쓰지 않는다
        for field in ("profileImageUrl", "email", "homepageUrl", "labName"):
            if record[field] is not None and not str(record[field]).strip():
                problems.append(f"{name}: {field}가 빈 문자열이다 (null이어야 한다)")

        # 원칙 1 — pmid 없는 논문 0건
        for paper in record["papers"]:
            if not (paper.get("pmid") or "").strip():
                no_pmid += 1
                problems.append(f"{name}: pmid 없는 논문 — {paper.get('title')!r}")
        if len(record["papers"]) > PAPERS_LIMIT:
            problems.append(f"{name}: 대표 논문 {len(record['papers'])}편 (최대 {PAPERS_LIMIT})")

        # latestPaper가 papers와 모순되지 않는지
        latest = record["latestPaper"]
        if latest:
            if not latest.get("pmid") or not latest.get("publishedAt"):
                problems.append(f"{name}: latestPaper의 pmid/publishedAt이 비어 있다")
            elif latest["pmid"] not in {p["pmid"] for p in record["papers"]}:
                problems.append(f"{name}: latestPaper({latest['pmid']})가 대표 논문 목록에 없다")
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

        if set(record["specialties"]) - set((sources["specialties"].get(name) or {}).get("specialties") or []) \
                - set(override_values.get((name, "specialties")) or []):
            problems.append(f"{name}: 원본에 없는 전문분야가 들어 있다")
        if set(record["keywords"]) - set((sources["meta"].get(name) or {}).get("keywordsCandidate") or []) \
                - set(override_values.get((name, "keywords")) or []):
            problems.append(f"{name}: 원본에 없는 키워드가 들어 있다")
        for field, source_value in (("profileImageUrl", sources["images"].get(name)),
                                    ("email", (sources["meta"].get(name) or {}).get("email")),
                                    ("homepageUrl", sources["pages"].get(name))):
            value = record[field]
            if value is not None and value != source_value and value != override_values.get((name, field)):
                problems.append(f"{name}: {field} 값이 원본과 다르다")

    print("[7] 정합 검사")
    print(f"    id 중복                 : {len(duplicated)}건")
    print(f"    pmid 없는 논문           : {no_pmid}건")
    print(f"    계약 밖 칸 사용          : {contract_violation}건")
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
    print(f"    = 병원 명단 대상                          : {hospital_target_count}명")
    print(f"    + 의대 명단 신규(병원 명단에 없는 교수)     : +{new_person_count}명")
    print(f"    - 소속 미확보로 제외                      : -{len(review['droppedNoDepartment'])}명")
    print(f"    = professors.json 수록                   : {len(contract_records)}명")
    print()
    total = len(contract_records) or 1
    print("    필드별 채움율")
    for field in ("profileImageUrl", "professorType", "department", "specialties",
                  "keywords", "email", "homepageUrl", "papers", "latestPaper", "labName"):
        filled = sum(1 for r in contract_records if r[field] not in (None, [], ""))
        note = "  ← 출처 없음(계약 4장: null)" if field == "labName" else ""
        print(f"      {field:<17} {filled:>3}/{total}  ({filled * 100 // total:>3}%){note}")
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

    sources = {
        "roster": roster,
        "pages": pages,
        "images": images_file["images"],
        "specialties": specialties_file["specialties"],
        "papers": papers_file["professors"],
        "meta": meta_file["professors"],
    }
    source_dates = {
        "roster_crawled": roster["collectedAt"],
        "profile_images": images_file["collectedAt"],
        "specialties": specialties_file["collectedAt"],
        "professors_papers": papers_file["collectedAt"],
        "professors_enriched_meta": meta_file["collectedAt"],
    }
    collected_at = max(source_dates.values())  # 원칙 4: 원본 데이터 파일의 기준일

    print(f"[1] 입력 읽기 — 의대 명단 {len(roster['professors'])}건 / 병원 명단 {len(pages)}명 / "
          f"사진 {len(sources['images'])} / 전문분야 {len(sources['specialties'])} / "
          f"논문 {len(sources['papers'])} / 메타 {len(sources['meta'])} / "
          f"수동검수 {len(overrides.get('overrides') or [])}건")
    print(f"    collectedAt = {collected_at} (원본 기준일 {source_dates})")

    review = {key: [] for key in REVIEW_KEYS}

    print("[2] 의대 명단을 사람 단위로 묶는 중...")
    records, excluded_dental, hospital_target_count, new_person_count = build_records(sources, review)
    print(f"[5] 레코드 병합 완료 — {len(records)}명")

    apply_overrides(records, overrides, review)
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

    id_stats = assign_ids(records, review)
    verify_distinct_persons(records, overrides, review)

    contract_records = [{k: v for k, v in r.items() if not k.startswith("_")} for r in records]
    contract_records.sort(key=lambda r: (r["name"], r["department"]))
    problems = check_integrity(contract_records, sources, review, overrides)

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
            "MERGE_CROSS_APPOINTMENTS": MERGE_CROSS_APPOINTMENTS,
            "DEPARTMENT_INCLUDE_DIVISION": DEPARTMENT_INCLUDE_DIVISION,
            "FETCH_HOSPITAL_DEPARTMENT": FETCH_HOSPITAL_DEPARTMENT,
            "HOSPITAL_ONLY_PROFESSOR_TYPE": HOSPITAL_ONLY_PROFESSOR_TYPE,
            "PAPERS_LIMIT": PAPERS_LIMIT,
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
