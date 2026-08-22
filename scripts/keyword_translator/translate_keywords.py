"""영문 키워드(MeSH) → 한글 번역 — 파이프라인 8단계.

- 입력: data/output/professors_enriched_meta.json (5단계 산출물의 영문 MeSH 키워드)
- 사전: scripts/keyword_translator/dictionary.json.gz (KOSTOM에서 추출, build_dictionary.py)
        scripts/keyword_translator/translation_memory.json (있으면 — KCI 수확·수동 교정, 사전보다 우선)
- 출력: data/output/keywords_ko.json (영문 용어 → 한글 변형 목록)

왜 필요한가: 백엔드 검색은 문자 부분일치라 한글 질의("심장")가 영문 키워드("cardiac imaging")와
만나지 못한다. 조립기(9단계)가 이 파일로 keywords에 한글 표기를 함께 넣으면 한글 검색이 잡힌다.
KCI 논문은 키워드가 한·영 쌍으로 오므로 번역이 필요 없고, 그 쌍은 오히려 번역 메모리에
수확해 사전이 못 잡는 용어를 채우는 데 쓴다 (data/output/kci_papers.json이 있을 때).

원칙 (계약 0장):
- 번역을 지어내지 않는다 — 사전·메모리에 없는 용어는 untranslated 목록에 그대로 남긴다.
  (남긴 목록은 사람이 검수해 translation_memory.json에 채우면 다음 회차부터 반영된다)
- 원문 영문 키워드는 어떤 경우에도 대체하지 않는다. 한글은 '추가'다.

5단계 산출물의 정확한 모양이 브랜치마다 다를 수 있어, 키 이름에 mesh/keyword가 들어간
문자열 배열을 구조 전체에서 찾아 모으는 방식으로 읽는다 (모양이 확정되면 좁혀도 된다).
"""

import argparse
import gzip
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

INPUT_PATH = ROOT / "data" / "output" / "professors_enriched_meta.json"
KCI_PATH = ROOT / "data" / "output" / "kci_papers.json"
OUTPUT_PATH = ROOT / "data" / "output" / "keywords_ko.json"
DICTIONARY_PATH = HERE / "dictionary.json.gz"
MEMORY_PATH = HERE / "translation_memory.json"

# 이 이름이 들어간 키 밑의 문자열 배열을 번역 대상으로 모은다
KEYWORD_KEY_MARKERS = ("mesh", "keyword")
HAS_HANGUL = re.compile(r"[가-힣]")


def normalize(term):
    """조회 키 — build_dictionary.normalize_en과 반드시 같은 규칙."""
    return " ".join(term.lower().split())


def load_dictionary():
    with gzip.open(DICTIONARY_PATH, "rt", encoding="utf-8") as f:
        return json.load(f)["terms"]


def load_memory():
    """번역 메모리 — KCI 수확분과 사람이 채운 교정. 값은 문자열 또는 배열을 허용한다."""
    if not MEMORY_PATH.exists():
        return {}
    memory = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    return {
        normalize(en): [ko] if isinstance(ko, str) else list(ko)
        for en, ko in memory.get("terms", {}).items()
    }


def collect_english_terms(node, found):
    """구조 전체를 훑어 mesh/keyword 키 밑의 영문 문자열을 모은다 (등장 순서 유지)."""
    if isinstance(node, dict):
        for key, value in node.items():
            key_l = key.lower()
            if any(marker in key_l for marker in KEYWORD_KEY_MARKERS):
                for item in value if isinstance(value, list) else [value]:
                    if isinstance(item, str) and item.strip() and not HAS_HANGUL.search(item):
                        found.setdefault(item.strip(), None)
            else:
                collect_english_terms(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_english_terms(item, found)


def harvest_kci_pairs(memory):
    """KCI 산출물에서 한·영 키워드 쌍을 수확해 메모리에 더한다. 반환: 새로 배운 용어 수.

    7단계(fetch_kci_keywords.py)가 논문마다 붙이는 실제 모양을 읽는다:
        paper["keywords"] = {"ko": [...], "en": [...]}

    주의 — ko/en은 KCI의 '언어 구분 없는 한 목록'을 한글 포함 여부로 가른 것이라
    서로 정렬·대응이 보장되지 않는다 (언어별 중복 제거로 길이가 어긋날 수도 있다).
    그래서 **두 목록의 길이가 같을 때만** 같은 순번끼리 쌍으로 인정한다
    (저자들이 번역쌍을 같은 순서로 나열하는 관행에 기댄 추정 — 길이가 다르면
    잘못 짝지을 위험이 커서 그 논문은 통째로 건너뛴다. 지어내지 않는다, 원칙 2).
    keywordsRaw(쪼개기 전 원본 보존용)는 수확 대상이 아니다.
    모양이 다르거나 파일이 없으면 조용히 0 — 수확은 보너스이지 이 단계의 성패가 아니다.
    """
    if not KCI_PATH.exists():
        return 0

    try:
        data = json.loads(KCI_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[경고] KCI 산출물을 읽지 못해 수확을 건너뜁니다: {exc}")
        return 0

    learned = 0

    def visit(node):
        nonlocal learned
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key == "keywords"
                    and isinstance(value, dict)
                    and isinstance(value.get("ko"), list)
                    and isinstance(value.get("en"), list)
                ):
                    ko_list, en_list = value["ko"], value["en"]
                    if (
                        ko_list and len(ko_list) == len(en_list)
                        and all(isinstance(x, str) for x in ko_list + en_list)
                    ):
                        for en, ko in zip(en_list, ko_list):
                            en_key, ko = normalize(en), ko.strip()
                            if en_key and ko and HAS_HANGUL.search(ko) and en_key not in memory:
                                memory[en_key] = [ko]
                                learned += 1
                    continue   # keywords 밑으로 더 내려갈 것 없음
                if key == "keywordsRaw":
                    continue   # 쪼개기 전 원본 — 쌍 근거가 더 약하므로 쓰지 않는다
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(data)
    return learned


def save_memory(memory, learned):
    """수확분을 메모리 파일에 반영한다 (커밋 대상 — 회차를 거듭할수록 사전이 자란다)."""
    if learned == 0:
        return
    payload = {
        "_comment": "번역 메모리 — KCI 수확분과 수동 교정. 사전(dictionary.json.gz)보다 우선한다.",
        "terms": {en: (ko[0] if len(ko) == 1 else ko) for en, ko in sorted(memory.items())},
    }
    MEMORY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def lookup(term, memory, dictionary):
    """메모리 → 사전 → (MeSH 도치 표기·단수형 보정) 순서로 찾는다. 없으면 None."""
    key = normalize(term)
    candidates = [key]
    if "," in key:
        # MeSH 도치 표기: "heart failure, diastolic" → "diastolic heart failure"
        head, _, tail = key.partition(",")
        candidates.append(f"{tail.strip()} {head.strip()}".strip())
    for cand in list(candidates):
        # 복수형 보정: biomarkers → biomarker (마지막 단어만, 지어내는 것이 아니라 표기 차이 흡수)
        if cand.endswith("es"):
            candidates.append(cand[:-2])
        if cand.endswith("s"):
            candidates.append(cand[:-1])

    for cand in candidates:
        if cand in memory:
            return memory[cand]
    for cand in candidates:
        if cand in dictionary:
            return dictionary[cand]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="영문 키워드를 KOSTOM 사전으로 한글 번역한다.")
    parser.add_argument("--input", metavar="PATH", help=f"입력 파일 (기본: {INPUT_PATH})")
    args = parser.parse_args(argv)
    input_path = Path(args.input) if args.input else INPUT_PATH

    if not DICTIONARY_PATH.exists():
        print(f"[중단] 사전이 없습니다: {DICTIONARY_PATH}")
        print("       data/KOSTOM 원본을 받은 뒤 build_dictionary.py를 먼저 실행하세요.")
        return 1
    if not input_path.exists():
        print(f"[중단] 입력 파일이 없습니다: {input_path}")
        print("       5단계(enrich_authors_mesh.py)를 먼저 실행하세요.")
        return 1

    dictionary = load_dictionary()
    memory = load_memory()
    learned = harvest_kci_pairs(memory)
    save_memory(memory, learned)
    print(f"사전 {len(dictionary):,}개 · 메모리 {len(memory):,}개 (이번 KCI 수확 {learned:,}개)")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    found = {}
    collect_english_terms(data, found)
    terms = list(found)
    print(f"번역 대상 영문 키워드 {len(terms):,}개 (중복 제거)")

    translations = {}
    untranslated = []
    for term in terms:
        result = lookup(term, memory, dictionary)
        if result:
            translations[term] = result
        else:
            untranslated.append(term)   # 지어내지 않고 남긴다 (원칙 2)

    payload = {
        "collectedAt": data.get("collectedAt") or date.today().isoformat(),
        "source": "KOSTOM V7.0 + translation_memory",
        "stats": {
            "terms": len(terms),
            "translated": len(translations),
            "untranslated": len(untranslated),
        },
        "translations": translations,   # 값은 한글 변형 배열 — 첫 번째가 대표 표기
        "untranslated": sorted(untranslated),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    ratio = len(translations) / len(terms) * 100 if terms else 0.0
    print(f"번역 {len(translations):,}개 / 미번역 {len(untranslated):,}개 (적중률 {ratio:.0f}%)")
    print(f"저장: {OUTPUT_PATH}")
    if untranslated:
        print("미번역 용어는 출력 파일 untranslated에 남겼습니다 — 검수 후 "
              "translation_memory.json에 채우면 다음 회차부터 반영됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
