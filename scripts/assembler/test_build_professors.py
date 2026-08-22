"""build_professors.py 오프라인 단위 테스트.

네트워크·실데이터 없이 순수 함수만 검증한다. 고정하려는 규칙은 두 가지다.

1. **KCI 교수 매칭은 이름이 일치할 때만 허용한다.**
   id가 같아도 이름이 다르거나 **비어 있으면** kciKeywords를 붙이지 않는다.
   값이 없는 쪽이 오히려 더 의심스러운 상황이라 무사통과시키면 남의 논문 키워드가 붙는다.
2. **사전이 아직 없어도 미번역 용어 집계는 남긴다.**
   사전을 만드는 담당자에게 "무엇을 번역해야 하는지"가 가장 필요한 시점이 그때다.

실행 (저장소 루트에서):
    python -m unittest discover -s scripts/assembler -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_professors as bp


def make_record(professor_id="P-001", name="강경표", keywords=()):
    """조립 도중 모양의 최소 레코드 (id 부여까지 끝난 상태)."""
    return {
        "id": professor_id,
        "name": name,
        "keywords": list(keywords),
        "meshTerms": [],
        "keywordsKo": [],
        "kciKeywords": {"ko": [], "en": []},
        "_extra": {"manualFields": []},
    }


def make_kci_entry(name, ko=("당뇨",), en=("Diabetes",)):
    entry = {"papers": [{"kciId": "ART001", "keywords": {"ko": list(ko), "en": list(en)}}]}
    if name is not None:
        entry["name"] = name
    return entry


class KciNameMatchTest(unittest.TestCase):
    """id가 같을 때 이름 처리 — 일치 / 불일치 / 누락."""

    def run_fill(self, kci_name):
        record = make_record()
        review = {key: [] for key in bp.REVIEW_KEYS}
        bp.fill_kci_keywords([record], {"P-001": make_kci_entry(kci_name)}, review)
        return record, review["kciKeywordsUnmatched"]

    def test_name_matches_attaches_keywords(self):
        record, unmatched = self.run_fill("강경표")
        self.assertEqual(record["kciKeywords"], {"ko": ["당뇨"], "en": ["Diabetes"]})
        self.assertEqual(unmatched, [])

    def test_name_differs_is_rejected(self):
        record, unmatched = self.run_fill("다른사람")
        self.assertEqual(record["kciKeywords"], {"ko": [], "en": []})
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["kciName"], "다른사람")

    def test_name_missing_is_rejected(self):
        """이름 누락도 거부한다 — 예전에는 무사통과였다."""
        record, unmatched = self.run_fill(None)
        self.assertEqual(record["kciKeywords"], {"ko": [], "en": []})
        self.assertEqual(len(unmatched), 1)
        self.assertIn("이름이 없어", unmatched[0]["note"])

    def test_empty_name_is_rejected(self):
        record, unmatched = self.run_fill("")
        self.assertEqual(record["kciKeywords"], {"ko": [], "en": []})
        self.assertEqual(len(unmatched), 1)

    def test_id_absent_is_recorded(self):
        record = make_record(professor_id="P-999")
        review = {key: [] for key in bp.REVIEW_KEYS}
        bp.fill_kci_keywords([record], {"P-001": make_kci_entry("강경표")}, review)
        self.assertEqual(record["kciKeywords"], {"ko": [], "en": []})
        self.assertEqual(len(review["kciKeywordsUnmatched"]), 1)


class KeywordsKoTest(unittest.TestCase):
    """한글 사전 읽기 — 사전이 없을 때도 미번역 통계를 만든다."""

    def test_missing_dictionary_still_counts_untranslated(self):
        records = [make_record(keywords=["Heart Failure", "Apoptosis"]),
                   make_record("P-002", "강상율", ["Heart Failure"])]
        stats, missing = bp.fill_keywords_ko(records, None)
        self.assertEqual([r["keywordsKo"] for r in records], [[], []])
        self.assertEqual(stats["filled"], 0)
        self.assertEqual(missing["Heart Failure"], 2)   # 두 교수 모두에게서 집계된다
        self.assertEqual(missing["Apoptosis"], 1)

    def test_dictionary_translates_and_keeps_order(self):
        records = [make_record(keywords=["Heart Failure", "Apoptosis", "Biomarkers"])]
        stats, missing = bp.fill_keywords_ko(records, {"Heart Failure": "심부전",
                                                       "Biomarkers": "생체표지자"})
        self.assertEqual(records[0]["keywordsKo"], ["심부전", "생체표지자"])  # keywords 순서 유지
        self.assertEqual(stats["filled"], 1)
        self.assertEqual(list(missing), ["Apoptosis"])   # 사전에 없는 용어만 미번역

    def test_unknown_term_is_skipped_not_copied(self):
        """사전에 없으면 원문을 그대로 넣지 않는다 (원칙 2)."""
        records = [make_record(keywords=["Apoptosis"])]
        bp.fill_keywords_ko(records, {"Heart Failure": "심부전"})
        self.assertEqual(records[0]["keywordsKo"], [])

    def test_duplicate_translation_appears_once(self):
        records = [make_record(keywords=["Neoplasms", "Cancer"])]
        bp.fill_keywords_ko(records, {"Neoplasms": "암", "Cancer": "암"})
        self.assertEqual(records[0]["keywordsKo"], ["암"])


class KciKeywordOrderTest(unittest.TestCase):
    """집계 정렬 — 등장 빈도 내림차순 → 동률이면 문자열 오름차순."""

    def test_frequency_then_alphabetical(self):
        papers = [{"keywords": {"ko": [], "en": ["B", "C"]}},
                  {"keywords": {"ko": [], "en": ["C", "A"]}},
                  {"keywords": {"ko": [], "en": ["C"]}}]
        self.assertEqual(bp.aggregate_kci_keywords(papers)["en"], ["C", "A", "B"])

    def test_duplicate_inside_one_paper_counts_once(self):
        papers = [{"keywords": {"ko": [], "en": ["A", "A", "A"]}},
                  {"keywords": {"ko": [], "en": ["B"]}},
                  {"keywords": {"ko": [], "en": ["B"]}}]
        self.assertEqual(bp.aggregate_kci_keywords(papers)["en"], ["B", "A"])

    def test_blank_terms_are_dropped(self):
        papers = [{"keywords": {"ko": ["  ", ""], "en": [" Diabetes "]}}]
        result = bp.aggregate_kci_keywords(papers)
        self.assertEqual(result["ko"], [])
        self.assertEqual(result["en"], ["Diabetes"])


class SilentLossTest(unittest.TestCase):
    """값이 없어 빠지는 것들이 review·집계에 남는지 (조용한 손실 방지)."""

    def make_sources(self, papers_entry):
        return {"images": {}, "pages": {}, "specialties": {}, "meta": {},
                "papers": {"강경표": papers_entry}, "kci": {}}

    def fill(self, papers_entry):
        record = make_record()
        record["papers"] = []
        record["latestPaper"] = None
        record["email"] = None
        record["profileImageUrl"] = None
        record["homepageUrl"] = None
        record["specialties"] = []
        record["_extra"]["sources"] = {"inHospitalList": True}
        review = {key: [] for key in bp.REVIEW_KEYS}
        bp.fill_from_sources(record, self.make_sources(papers_entry), review)
        return record, review

    def test_paper_without_identifier_is_recorded(self):
        """pmid·kciId가 둘 다 없는 논문은 빼되 무엇이 빠졌는지 남긴다 (원칙 1)."""
        record, review = self.fill({"papers": [
            {"title": "식별자 없는 논문", "journal": "J", "year": 2020},
            {"title": "정상 논문", "journal": "J", "year": 2021, "pmid": "123"}]})
        self.assertEqual([p["pmid"] for p in record["papers"]], ["123"])
        self.assertEqual(len(review["papersWithoutIdentifier"]), 1)
        self.assertEqual(review["papersWithoutIdentifier"][0]["title"], "식별자 없는 논문")

    def test_latest_paper_without_pmid_is_recorded(self):
        """계약상 latestPaper는 PubMed 전용 — pmid 누락은 상류 이상 신호로 남긴다."""
        record, review = self.fill({
            "papers": [], "allPapers": [{"pmid": "555", "publishedAt": "2020-01-02"}],
            "latestPaper": {"kciId": "ART001", "publishedAt": "2021-03-04"}})
        self.assertEqual(record["latestPaper"], {"pmid": "555", "publishedAt": "2020-01-02"})
        self.assertEqual(len(review["latestPaperDropped"]), 1)
        self.assertIn("pmid가 없다", review["latestPaperDropped"][0]["note"])


class DictionaryLoadTest(unittest.TestCase):
    """사전 읽기 — 값이 빈 항목을 세어 남긴다."""

    def load_with(self, payload):
        import json
        import tempfile
        original = bp.KEYWORD_KO_DICT_PATH
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keyword_ko_dict.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            bp.KEYWORD_KO_DICT_PATH = path
            try:
                return bp.load_keyword_ko_dictionary()
            finally:
                bp.KEYWORD_KO_DICT_PATH = original

    def test_empty_values_are_counted_not_swallowed(self):
        dictionary, warning, empty = self.load_with(
            {"Heart Failure": "심부전", "Humans": "", "Apoptosis": "   "})
        self.assertEqual(dictionary, {"Heart Failure": "심부전"})
        self.assertIsNone(warning)
        self.assertEqual(empty, 2)

    def test_missing_file_is_warning_not_failure(self):
        original = bp.KEYWORD_KO_DICT_PATH
        bp.KEYWORD_KO_DICT_PATH = Path("없는파일_keyword_ko_dict.json")
        try:
            dictionary, warning, empty = bp.load_keyword_ko_dictionary()
        finally:
            bp.KEYWORD_KO_DICT_PATH = original
        self.assertIsNone(dictionary)
        self.assertIn("없어", warning)
        self.assertEqual(empty, 0)


if __name__ == "__main__":
    unittest.main()
