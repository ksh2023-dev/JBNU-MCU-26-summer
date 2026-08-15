"""C단계 보강(backfill): 이미 확보한 PMID로 efetch만 다시 불러 MeSH·교수 영문명·이메일을 채운다.

흐름: 3단계 산출물(professors_papers.json) 읽기
      → 전체 유니크 PMID를 200개씩 묶어 efetch(XML) 재조회
      → 논문별 MeSH(DescriptorName) + 저자 상세(성/이름/이니셜/소속/이메일) 추출
      → 교수별로 "본인 저자" 판별 (JBNU 소속 + 성씨 로마자 일치 + 여러 논문 빈도 투표)
      → data/output/professors_enriched_meta.json 저장

재수집 금지가 원칙이다. PubMed esearch(제목 검색)·OpenAlex·병원 사이트는 호출하지 않고,
3단계가 이미 신원 보증(교수 본인 프로필의 인용문)으로 확정한 PMID만 다시 읽는다.

본인 저자 판별 (이 스크립트의 핵심):
  ① 후보 수집 — 그 교수의 논문에서 소속에 Jeonbuk/Chonbuk National University가 있는 저자만
  ② 성씨 필터 — 한글 성의 로마자 표기(김=Kim…)와 저자 LastName이 일치하는 후보로 좁힘
  ③ 빈도 투표 — 그 교수의 여러 논문에 걸쳐 가장 일관되게 등장하는 후보를 본인으로 판정
  ④ 확정 조건 — 2편 이상에서 관측 + 1위가 단독일 때만. 1편뿐이거나 후보가 갈리면
     nameEn을 null로 두고 review에 기록한다 (지어내지 않기 — 계약 v6.3 원칙 2)

데이터 계약 v6.3:
- 원칙 2: 확신이 없으면 지어내지 않고 null. 판정 실패는 review에 남겨 사람이 검수한다.
- 원칙 4: 수집 기준일(collectedAt)을 담고, PubMed가 준 표기(영문명·이메일)는 원본 그대로 둔다.
- keywords 최종 확정·MeSH 한글 번역은 이 단계의 범위가 아니다 — 후보 목록까지만 만든다.
"""

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

import requests

# 기존 부품 재사용 (기존 파일은 수정하지 않는다 — 같은 폴더라 바로 import 가능)
import build_all      # call_with_retry: 5xx·네트워크 예외를 5초→15초 간격으로 3회까지 재시도
import fetch_one      # EFETCH_URL

# ===== 실행 옵션 (실행 전 이 부분만 수정하면 됩니다) ============================
LIMIT = None            # 개발·검증용: 입력 교수 목록 앞 N명만 처리 (None이면 전체)
# ==============================================================================

# efetch 한 번에 보낼 PMID 수 — NCBI 권장 상한(200) 그대로. 878편이면 5묶음이다.
BATCH_SIZE = 200

# API 예절: PubMed 호출 사이 0.4초 (키 없이 초당 3회 제한 — 1·3단계와 같은 값)
SLEEP_SECONDS = 0.4

# 본인 판정 확정에 필요한 최소 관측 논문 수 — 1편뿐이면 우연일 수 있어 확정하지 않는다
MIN_PAPERS_FOR_CONFIRM = 2

# keywordsCandidate로 내보낼 MeSH 개수
TOP_KEYWORDS = 10

ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "data" / "output" / "professors_papers.json"
OUTPUT_PATH = ROOT / "data" / "output" / "professors_enriched_meta.json"

# 전북대 소속 표기 — 2020년 교명 변경 전 논문은 Chonbuk으로 실린다. 둘 다 본다.
JBNU_MARKERS = ("jeonbuk national university", "chonbuk national university")

# 한글 성 → 로마자 표기 (작업지시서 표). 표기가 여러 개인 성은 전부 허용한다.
SURNAME_ROMAJA = {
    "김": ["Kim"], "이": ["Lee", "Yi", "Rhee"], "박": ["Park"],
    "정": ["Jung", "Jeong", "Chung"], "최": ["Choi"], "조": ["Cho", "Jo"],
    "강": ["Kang"], "윤": ["Yoon", "Yun"], "임": ["Lim", "Im"], "한": ["Han"],
    "오": ["Oh"], "서": ["Seo", "Suh"], "신": ["Shin"], "황": ["Hwang"],
    "안": ["Ahn", "An"], "송": ["Song"], "전": ["Jeon", "Chun"], "홍": ["Hong"],
    "유": ["Yoo", "Yu", "Ryu"], "진": ["Jin", "Chin"], "문": ["Moon", "Mun"],
    "양": ["Yang"], "손": ["Son", "Sohn"], "배": ["Bae"], "백": ["Baek", "Paik"],
    "허": ["Heo", "Hur"], "남": ["Nam"], "심": ["Shim", "Sim"], "노": ["Noh", "Roh"],
    "하": ["Ha"], "곽": ["Kwak"], "성": ["Sung", "Seong"], "차": ["Cha"],
    "주": ["Joo", "Ju"], "우": ["Woo"], "구": ["Koo", "Gu"], "민": ["Min"],
    "류": ["Ryu", "Yoo"], "채": ["Chae"], "원": ["Won"], "천": ["Cheon"],
    "방": ["Bang"], "공": ["Kong", "Gong"], "현": ["Hyun"], "함": ["Ham"],
    "변": ["Byun"], "염": ["Yeom"], "여": ["Yeo"], "추": ["Choo", "Chu"],
    "도": ["Do"], "소": ["So"], "석": ["Seok"], "선": ["Sun", "Seon"],
    "설": ["Seol"], "마": ["Ma"], "길": ["Gil"], "연": ["Yeon"], "위": ["Wi"],
    "표": ["Pyo"], "명": ["Myung"], "기": ["Ki"], "은": ["Eun"],
    "국": ["Kook", "Guk"], "어": ["Uh"], "경": ["Kyung"], "인": ["In"],
    "두": ["Doo", "Du"],

    # --- 지시서 표에 없어 보강한 성씨 -----------------------------------------
    # 입력 243명 중 이 네 성씨의 교수 9명이 표에 없어 전원 판정 불가가 된다.
    # 새로 지어낸 표기가 아니라 국립국어원 로마자 표기와 관용 표기를 그대로 넣었다.
    "고": ["Ko", "Koh", "Go"], "장": ["Jang", "Chang"],
    "권": ["Kwon", "Kweon"], "왕": ["Wang"],
}

# 두 글자 성 — 이름에서 성을 자를 때 한 글자로 잘리면 안 되므로 먼저 확인한다
TWO_CHAR_SURNAME_ROMAJA = {
    "남궁": ["Namgung", "Namkung"], "선우": ["Sunwoo", "Seonwoo"],
    "황보": ["Hwangbo", "Hwangbu"], "제갈": ["Jegal"], "사공": ["Sagong"],
    "독고": ["Dokgo", "Dokko"],
}

# MeSH 검색 태그(연령·성별·연구설계 등) — 거의 모든 임상 논문에 붙어 빈도 상위를 독차지한다.
# 연구 주제를 나타내지 않으므로 keywordsCandidate에서는 뺀다. 뺀 것도 확인할 수 있게
# 필터 전 목록은 keywordsCandidateAll에 함께 담는다 (최종 keywords 확정은 팀 논의 사항).
MESH_CHECK_TAGS = {
    "humans", "animals", "male", "female", "adult", "aged", "aged, 80 and over",
    "middle aged", "young adult", "adolescent", "child", "child, preschool",
    "infant", "infant, newborn", "mice", "rats", "retrospective studies",
    "prospective studies", "cross-sectional studies", "follow-up studies",
    "reproducibility of results", "treatment outcome", "time factors",
    "cohort studies", "case-control studies", "risk factors", "republic of korea",
    "sensitivity and specificity", "predictive value of tests", "pregnancy",
}

# 소속 문자열 안의 이메일 — PubMed는 "Electronic address: a@b.kr" 형태로 넣어 준다
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


# ---------------------------------------------------------------------------
# efetch — MeSH·저자 상세 추출
# ---------------------------------------------------------------------------

def _fetch_batch(pmids):
    """PMID 묶음 하나를 efetch(XML)로 받아 파싱한 뒤 root 반환. 통신 실패는 그대로 올린다."""
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    resp = requests.get(fetch_one.EFETCH_URL, params=params, timeout=120)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def parse_article(article):
    """PubmedArticle 하나에서 MeSH 목록과 저자 상세를 뽑는다. pmid가 없으면 None (원칙 1)."""
    pmid = (article.findtext("MedlineCitation/PMID") or "").strip()
    if not pmid:
        return None

    # --- MeSH: MeshHeadingList의 DescriptorName. 없는 논문(최신·ahead of print)도 많다 ---
    mesh_terms = []
    for heading in article.findall("MedlineCitation/MeshHeadingList/MeshHeading"):
        name = (heading.findtext("DescriptorName") or "").strip()
        if name:
            mesh_terms.append(name)

    # --- 저자: 성/이름/이니셜/소속. CollectiveName(단체 저자)은 개인이 아니므로 건너뛴다 ---
    authors = []
    for author in article.findall("MedlineCitation/Article/AuthorList/Author"):
        last_name = (author.findtext("LastName") or "").strip()
        if not last_name:
            continue
        fore_name = (author.findtext("ForeName") or "").strip() or None
        initials = (author.findtext("Initials") or "").strip() or None
        affiliations = [
            "".join(a.itertext()).strip()
            for a in author.findall("AffiliationInfo/Affiliation")
            if "".join(a.itertext()).strip()
        ]
        # 이메일은 소속 문자열 안에 섞여 온다. 끝의 마침표는 주소가 아니므로 뗀다.
        emails = []
        for aff in affiliations:
            for hit in EMAIL_RE.findall(aff):
                emails.append(hit.rstrip("."))
        authors.append({
            "lastName": last_name,
            "foreName": fore_name,
            "initials": initials,
            "affiliations": affiliations,
            "email": emails[0] if emails else None,   # 없으면 지어내지 않고 null (원칙 2)
        })

    return {"pmid": pmid, "meshTerms": mesh_terms, "authors": authors}


def fetch_details(pmids):
    """전체 PMID를 BATCH_SIZE씩 묶어 efetch로 재조회한다. 반환: {pmid: {meshTerms, authors}}.

    한 묶음이 재시도까지 실패하면 그 묶음만 건너뛰고 계속한다 — 970편짜리 배치 전체를
    통신 오류 하나로 버리지 않기 위해서다. 건너뛴 PMID는 보강 대상에서 빠지고,
    실패 사실은 호출한 쪽이 통계로 보고한다.
    """
    details = {}
    batches = [pmids[i:i + BATCH_SIZE] for i in range(0, len(pmids), BATCH_SIZE)]
    for index, batch in enumerate(batches, 1):
        time.sleep(SLEEP_SECONDS)
        print(f"[efetch {index}/{len(batches)}] {len(batch)}편 조회 중…")
        try:
            root = build_all.call_with_retry(
                "PubMed 상세 재조회(efetch)", lambda batch=batch: _fetch_batch(batch)
            )
        except requests.exceptions.RequestException as exc:
            print(f"  → 묶음 {index} 실패({build_all._describe_error(exc)}) — 건너뛰고 계속")
            continue
        for article in root.findall("PubmedArticle"):
            parsed = parse_article(article)
            if parsed:
                details[parsed["pmid"]] = parsed
        print(f"  → 누적 {len(details)}편 파싱")
    return details


# ---------------------------------------------------------------------------
# 본인 저자 판별
# ---------------------------------------------------------------------------

def surname_romaja(korean_name):
    """한글 이름에서 성을 떼어 허용 로마자 표기 목록을 돌려준다. 표에 없으면 None."""
    if len(korean_name) >= 3 and korean_name[:2] in TWO_CHAR_SURNAME_ROMAJA:
        return TWO_CHAR_SURNAME_ROMAJA[korean_name[:2]]
    return SURNAME_ROMAJA.get(korean_name[:1])


def is_jbnu(affiliation):
    """소속 문자열이 전북대(Jeonbuk/Chonbuk National University)인지 확인한다."""
    text = affiliation.lower()
    return any(marker in text for marker in JBNU_MARKERS)


def _norm(text):
    """이름 비교용 정규화 — 소문자로 바꾸고 하이픈·공백·마침표를 없앤다.
    ("Sang-Min" / "Sang Min" / "SangMin"을 같은 사람으로 묶기 위한 것)
    """
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _derive_initials(fore_name):
    """이름에서 이니셜을 만든다 — "Sang-Min" → "SM" (인용문 표기 "Oh SM"과 맞춰 보기 위함)."""
    parts = [p for p in re.split(r"[\s\-]+", fore_name or "") if p]
    return "".join(p[0].upper() for p in parts)


def _new_candidate():
    return {
        "pmids": set(),           # 그 교수의 논문 중 이 후보가 JBNU 소속으로 등장한 논문
        "forms": Counter(),       # 관측된 표기 ("Sang-Min Oh")
        "initials": Counter(),    # 관측된 이니셜 ("SM")
        "emails": Counter(),      # JBNU 소속 문자열에서 발견한 이메일
        "affiliations": [],       # 근거로 남길 소속 문자열
        "hasForeName": False,     # 전체 이름(ForeName)이 한 번이라도 관측됐는지
    }


def collect_candidates(name, papers, details):
    """교수 1명의 논문들에서 '본인 후보' 저자를 모은다. 반환: {후보키: 후보정보}.

    후보 조건 (둘 다 만족):
    - 소속에 Jeonbuk/Chonbuk National University가 있다
    - LastName이 그 교수 한글 성의 로마자 표기와 일치한다
    """
    allowed = surname_romaja(name)
    if allowed is None:
        return None   # 성씨 매핑 없음 — 호출한 쪽이 review에 기록한다
    allowed_lower = {r.lower() for r in allowed}

    candidates = {}
    for paper in papers:
        detail = details.get(paper["pmid"])
        if not detail:
            continue
        for author in detail["authors"]:
            if author["lastName"].lower() not in allowed_lower:
                continue
            jbnu_affs = [a for a in author["affiliations"] if is_jbnu(a)]
            if not jbnu_affs:
                continue   # 전북대 소속으로 실린 적 없는 동성(同姓) 저자는 후보가 아니다

            # 후보 키: 성 + 이름(없으면 이니셜). 표기 변형은 정규화로 한 사람에 모인다.
            fore = author["foreName"]
            key = (author["lastName"].lower(), _norm(fore) if fore else _norm(author["initials"]))
            cand = candidates.setdefault(key, _new_candidate())
            cand["pmids"].add(paper["pmid"])
            if fore:
                cand["hasForeName"] = True
                cand["forms"][f"{fore} {author['lastName']}"] += 1
                cand["initials"][author["initials"] or _derive_initials(fore)] += 1
            elif author["initials"]:
                cand["initials"][author["initials"]] += 1
            for aff in jbnu_affs:
                if len(cand["affiliations"]) < 3:
                    cand["affiliations"].append(aff)
                for hit in EMAIL_RE.findall(aff):
                    cand["emails"][hit.rstrip(".")] += 1
    return candidates


def merge_initials_only(candidates):
    """이니셜만 실린 관측을 같은 사람의 전체 이름 후보에 합친다.

    옛 논문은 ForeName 없이 Initials만 오는 경우가 있다. 그대로 두면 같은 사람이
    "Sang-Min Oh"와 "Oh SM" 두 후보로 갈려 빈도 투표가 흩어진다.
    같은 성에서 이니셜이 맞는 전체 이름 후보가 **정확히 하나**일 때만 합친다
    (둘 이상이면 누구인지 알 수 없으므로 합치지 않고 그대로 둔다 — 원칙 2).
    """
    full = {k: c for k, c in candidates.items() if c["hasForeName"]}
    merged = dict(candidates)
    for key, cand in candidates.items():
        if cand["hasForeName"]:
            continue
        last, ini = key
        targets = [
            k for k, c in full.items()
            if k[0] == last and any(_norm(i) == ini for i in c["initials"])
        ]
        if len(targets) != 1:
            continue
        target = merged[targets[0]]
        target["pmids"] |= cand["pmids"]
        target["initials"].update(cand["initials"])
        target["emails"].update(cand["emails"])
        for aff in cand["affiliations"]:
            if len(target["affiliations"]) < 3:
                target["affiliations"].append(aff)
        del merged[key]
    return merged


def decide(name, papers, details):
    """교수 1명의 판정 결과를 만든다. 반환: (결과 dict, review 사유 or None).

    확정 조건: 최다 관측 후보가 2편 이상에서 관측 + 2위와 동점이 아님 + 전체 이름 관측됨.
    하나라도 못 지키면 nameEn을 null로 두고 사유를 돌려준다 (지어내지 않기 — 원칙 2).
    """
    result = {
        "nameEn": None,
        "nameEnVariants": [],
        "keywordsCandidate": [],
        "keywordsCandidateAll": [],
        "email": None,
        "evidence": {},
    }

    # --- keywordsCandidate: 본인 논문들의 MeSH 빈도 상위 (판정 성공 여부와 무관하게 만든다) ---
    mesh_counter = Counter()
    mesh_papers = 0
    for paper in papers:
        detail = details.get(paper["pmid"])
        if not detail or not detail["meshTerms"]:
            continue
        mesh_papers += 1
        mesh_counter.update(detail["meshTerms"])
    # 동점일 때 순서가 흔들리지 않게 (빈도 내림차순, 같으면 이름 오름차순)으로 고정한다
    ordered = sorted(mesh_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    result["keywordsCandidateAll"] = [t for t, _ in ordered[:TOP_KEYWORDS]]
    result["keywordsCandidate"] = [
        t for t, _ in ordered if t.lower() not in MESH_CHECK_TAGS
    ][:TOP_KEYWORDS]
    result["evidence"]["meshPapers"] = mesh_papers          # MeSH가 붙어 있던 논문 수
    result["evidence"]["totalPapers"] = len(papers)

    if not papers:
        return result, "논문 0건 (3단계 미수집)"

    candidates = collect_candidates(name, papers, details)
    if candidates is None:
        return result, "성씨 로마자 매핑 없음"
    candidates = merge_initials_only(candidates)
    if not candidates:
        return result, "JBNU 소속 + 성씨 일치 저자 후보 없음"

    ranked = sorted(candidates.items(), key=lambda kv: (-len(kv[1]["pmids"]), kv[0]))
    top_key, top = ranked[0]
    top_papers = len(top["pmids"])
    runner_up = len(ranked[1][1]["pmids"]) if len(ranked) > 1 else 0

    result["evidence"]["candidateCount"] = len(ranked)
    result["evidence"]["papersObserved"] = top_papers
    result["evidence"]["runnerUpPapers"] = runner_up
    result["evidence"]["affiliationSample"] = top["affiliations"][0] if top["affiliations"] else None
    # 관측된 표기는 확정·미확정과 무관하게 남긴다 — 미확정이어도 사람이 검수할 재료가 된다
    result["nameEnVariants"] = [f for f, _ in top["forms"].most_common()]
    if not result["nameEnVariants"] and top["initials"]:
        result["nameEnVariants"] = [f"{top_key[0].title()} {i}" for i, _ in top["initials"].most_common()]

    if top_papers < MIN_PAPERS_FOR_CONFIRM:
        return result, f"관측 논문 {top_papers}편 — 2편 미만이라 확정하지 않음"
    if top_papers == runner_up:
        return result, f"후보 갈림 — 동률 후보 {top_papers}편씩"
    if not top["hasForeName"]:
        return result, "이니셜 표기만 관측 — 전체 이름을 알 수 없음"

    # 확정: 가장 자주 관측된 표기를 대표형으로 쓴다 (PubMed 원본 그대로 — 원칙 4)
    result["nameEn"] = top["forms"].most_common(1)[0][0]
    result["evidence"]["initials"] = [i for i, _ in top["initials"].most_common()]
    if top["emails"]:
        result["email"] = top["emails"].most_common(1)[0][0]
    return result, None


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def main():
    if not INPUT_PATH.exists():
        print(f"입력 파일이 없습니다: {INPUT_PATH}")
        sys.exit(1)
    with open(INPUT_PATH, encoding="utf-8") as f:
        source = json.load(f)

    items = list(source["professors"].items())
    if LIMIT is not None:
        items = items[:LIMIT]
        print(f"LIMIT={LIMIT}: 입력 앞 {len(items)}명만 처리합니다 (검증용)")

    # 전체 유니크 PMID — 여러 교수가 공저한 논문은 한 번만 조회한다
    pmids = []
    seen = set()
    for _, record in items:
        for paper in record["allPapers"]:
            if paper["pmid"] not in seen:
                seen.add(paper["pmid"])
                pmids.append(paper["pmid"])

    with_papers = sum(1 for _, r in items if r["allPapers"])
    print(f"대상: 교수 {len(items)}명 (논문 보유 {with_papers}명) · 유니크 PMID {len(pmids)}건")

    started = time.monotonic()
    details = fetch_details(pmids)
    print(f"efetch 완료: {len(details)}/{len(pmids)}편 파싱 ({time.monotonic() - started:.0f}초)\n")

    professors = {}
    review = []
    for name, record in items:
        result, reason = decide(name, record["allPapers"], details)
        professors[name] = result
        if reason:
            review.append({
                "professor": name,
                "reason": reason,
                "papers": len(record["allPapers"]),
                "observedVariants": result["nameEnVariants"],
            })
            if record["allPapers"]:   # 논문 0건 82명은 이미 3단계에서 알려진 사실이라 조용히 넘긴다
                print(f"  [미확정] {name}: {reason}")
        else:
            print(f"  [확정] {name}: {result['nameEn']}"
                  f" (관측 {result['evidence']['papersObserved']}편"
                  f"{' · ' + result['email'] if result['email'] else ''})")

    output = {
        "collectedAt": date.today().isoformat(),   # 수집 기준일 (계약 원칙 4)
        "professors": professors,
        "review": review,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)   # ensure_ascii=False: 한글 보존

    print_summary(professors, review, details, len(pmids), time.monotonic() - started)


def print_summary(professors, review, details, requested_pmids, elapsed_seconds):
    """사람이 검수할 수 있게 통계를 요약한다 (지시서 1장 5번)."""
    confirmed = [n for n, r in professors.items() if r["nameEn"]]
    emails = [n for n, r in professors.items() if r["email"]]
    mesh_papers = sum(1 for d in details.values() if d["meshTerms"])
    with_papers = [n for n, r in professors.items() if r["evidence"].get("totalPapers")]

    print("\n===== 보강 결과 =====")
    print(f"nameEn 확정: {len(confirmed)}명 / 미확정(review): {len(review)}명"
          f" (전체 {len(professors)}명 · 논문 보유 {len(with_papers)}명)")
    print(f"email 확보: {len(emails)}명")
    print(f"MeSH 보강: 논문 {mesh_papers}편 (재조회 {len(details)}/{requested_pmids}편 중 MeSH 보유)")

    reasons = Counter(entry["reason"].split(" —")[0].split(" (")[0] for entry in review)
    print("미확정 사유:")
    for reason, count in reasons.most_common():
        print(f"  - {reason}: {count}명")
    print(f"소요: {elapsed_seconds:.0f}초 · 저장 위치: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
