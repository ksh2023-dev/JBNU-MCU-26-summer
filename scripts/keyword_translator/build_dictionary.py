"""KOSTOM(보건의료용어표준) 엑셀에서 영→한 용어 사전을 추출한다.

- 입력: data/KOSTOM/보건의료용어표준_V7.0_분야전체.xlsx (영문명·한글명 쌍 컬럼)
- 출력: scripts/keyword_translator/dictionary.json.gz (영문 소문자 → 한글)

파이프라인 단계가 아니라 **사전 재생성 도구**다 — KOSTOM 새 버전을 받았을 때만
다시 돌리면 되고, 매 회차 실행할 필요가 없다. 출력 파일은 저장소에 커밋한다.

거르는 규칙 (키워드 번역용 사전이므로 검사·코드 표기는 뺀다):
- 영문명·한글명 둘 다 있어야 한다. 없는 값을 지어내지 않는다 (계약 원칙 2).
- 콜론(:)이 든 항목 제외 — "A Ab:Pr:Pt:Ser/Plas:Ord" 같은 LOINC 검사 표기.
  MeSH 키워드에는 콜론이 없어 사전만 무겁게 하고 조회될 일이 없다.
- 지나치게 긴 항목(80자 초과 또는 9단어 이상) 제외 — 키워드가 아니라 문장이다.
- 같은 영문명의 한글명이 여러 개면 **전부 보관한다** (영문 동음이의어의 진짜 동의어들 —
  stroke = 뇌졸중/발작/박동). 검색 보강용이라 변형이 많을수록 재현율이 오른다.
  순서는 품질 신호로 정렬한다: 표준코드(UMLS·KCD 등)가 많이 달린 행의 표기가 앞,
  그다음 KCD(질병분류) 보유 → 긴 표기 → 가나다. 첫 번째가 대표 표기다.
  (예: hypertension → 고혈압(코드 4종)이 고압(1종)보다 앞. 코드 없는 오타 표기는 뒤로 밀린다)

표준 라이브러리만 쓴다. xlsx는 zip+XML이라 zipfile·ElementTree로 읽는다.
"""

import gzip
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "data" / "KOSTOM" / "보건의료용어표준_V7.0_분야전체.xlsx"
OUTPUT_PATH = Path(__file__).resolve().parent / "dictionary.json.gz"

EN_HEADER = "영문명"
KO_HEADER = "한글명"
MAX_LENGTH = 80
MAX_WORDS = 8
MAX_VARIANTS = 5   # 영문명 하나에 보관할 한글 변형 상한 (첫 번째가 대표 표기)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HAS_LETTER = re.compile(r"[A-Za-z]")
HAS_HANGUL = re.compile(r"[가-힣]")


def load_shared_strings(archive):
    """sharedStrings.xml — 셀들이 번호로 참조하는 문자열 목록."""
    strings = []
    with archive.open("xl/sharedStrings.xml") as f:
        for _, el in ET.iterparse(f):
            if el.tag == NS + "si":
                strings.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    return strings


def cell_column(ref):
    """셀 참조 "C5" → 열 문자 "C". 빈 셀은 파일에서 생략되므로 위치가 아니라 참조로 읽는다."""
    return "".join(ch for ch in ref if ch.isalpha())


def iter_rows(archive, shared):
    """워크시트 행을 {열 문자: 값} 사전으로 하나씩 낸다 (메모리에 다 올리지 않는다)."""
    with archive.open("xl/worksheets/sheet1.xml") as f:
        for _, el in ET.iterparse(f):
            if el.tag != NS + "row":
                continue
            row = {}
            for c in el.findall(NS + "c"):
                v = c.find(NS + "v")
                if v is None or v.text is None:
                    continue
                value = shared[int(v.text)] if c.get("t") == "s" else v.text
                row[cell_column(c.get("r", ""))] = value
            el.clear()
            yield row


def normalize_en(term):
    """조회 키 — 소문자·공백 정리. translate_keywords.py의 정규화와 반드시 같아야 한다."""
    return " ".join(term.lower().split())


def build():
    if not SOURCE_PATH.exists():
        print(f"[중단] KOSTOM 원본이 없습니다: {SOURCE_PATH}")
        return 1

    archive = zipfile.ZipFile(SOURCE_PATH)
    shared = load_shared_strings(archive)

    rows = iter_rows(archive, shared)
    header = next(rows)
    columns = {name: col for col, name in header.items()}
    if EN_HEADER not in columns or KO_HEADER not in columns:
        print(f"[중단] 헤더에서 {EN_HEADER}/{KO_HEADER} 열을 찾지 못했습니다: {sorted(header.values())}")
        return 1
    en_col, ko_col = columns[EN_HEADER], columns[KO_HEADER]
    kcd_col = columns.get("KCD")
    # 품질 신호로 쓸 표준코드 열 — 식별용 두 열과 영문·한글명을 뺀 나머지 전부
    code_cols = [
        col for name, col in columns.items()
        if name not in (EN_HEADER, KO_HEADER, "용어코드", "개념코드")
    ]

    candidates = {}   # 영문 키 → {한글명: 최고 품질 점수}
    total = skipped_code = skipped_long = skipped_empty = 0
    for row in rows:
        total += 1
        en = (row.get(en_col) or "").strip()
        ko = (row.get(ko_col) or "").strip()
        if not en or not ko or not HAS_LETTER.search(en) or not HAS_HANGUL.search(ko):
            skipped_empty += 1
            continue
        if ":" in en or ":" in ko:
            skipped_code += 1
            continue
        if len(en) > MAX_LENGTH or len(en.split()) > MAX_WORDS:
            skipped_long += 1
            continue

        code_count = sum(1 for col in code_cols if (row.get(col) or "").strip())
        has_kcd = 1 if kcd_col and (row.get(kcd_col) or "").strip() else 0
        quality = (code_count, has_kcd)
        variants = candidates.setdefault(normalize_en(en), {})
        if quality > variants.get(ko, (-1, -1)):
            variants[ko] = quality

    # 변형 정렬: 코드 많은 행 → KCD 보유 → 긴 표기 → 가나다 (결과가 실행마다 같게)
    terms = {}
    conflicts = 0
    for key, variants in candidates.items():
        if len(variants) > 1:
            conflicts += 1
        ranked = sorted(
            variants,
            key=lambda ko: (-variants[ko][0], -variants[ko][1], -len(ko), ko),
        )
        terms[key] = ranked[:MAX_VARIANTS]

    payload = {
        "_meta": {
            "source": SOURCE_PATH.name,
            "generatedAt": date.today().isoformat(),
            "entries": len(terms),
        },
        "terms": terms,
    }
    with gzip.open(OUTPUT_PATH, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    print(f"원본 행 {total:,}개 → 사전 {len(terms):,}개")
    print(f"  제외: 코드 표기(콜론) {skipped_code:,} / 빈 값·비한글 {skipped_empty:,} / 과도하게 긴 항목 {skipped_long:,}")
    print(f"  한글 변형이 여럿인 영문명 {conflicts:,}건 — 전부 보관(최대 {MAX_VARIANTS}개), 코드 많은 표기가 대표")
    print(f"저장: {OUTPUT_PATH} ({size_mb:.1f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
