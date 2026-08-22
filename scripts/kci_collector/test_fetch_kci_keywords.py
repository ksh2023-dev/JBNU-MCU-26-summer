"""fetch_kci_keywords.py 오프라인 단위 테스트 (#35 리뷰 대응).

표본 XML은 2026-08-21 실제 articleDetail 응답 구조 그대로다(내용만 축약·치환).
핵심 구조 — referenceInfo는 articleInfo의 **형제**라, 파싱 범위를 articleInfo로 좁히지 않으면
참고문헌의 keyword/title/author가 논문 값으로 둔갑한다.

    MetaData > outputData > record > articleInfo (article-id · keyword-group · author …)
                                   > referenceInfo (참고문헌 수십 건)

네트워크를 쓰지 않는다. 실행 (저장소 루트에서):
    python -m unittest discover -s scripts/kci_collector -v
"""

import unittest

import fetch_kci
import fetch_kci_keywords as fkw


def detail_xml(article_id='article-id="ART000000001"',
               keywords=("Diabetes mellitus", "당뇨병"),
               with_reference=True, repeat_article=1):
    """실제 응답 구조를 본뜬 articleDetail XML. article_id 부분은 통째로 갈아끼울 수 있다."""
    keyword_nodes = "".join(f"<keyword><![CDATA[{k}]]></keyword>" for k in keywords)
    reference = """
      <referenceInfo>
        <reference>
          <keyword-group><keyword><![CDATA[참고문헌에 딸린 키워드]]></keyword></keyword-group>
          <article-title>참고문헌 제목</article-title>
          <article-language>영어</article-language>
          <author><name>참고문헌저자</name><name-eng>Reference Author</name-eng>
            <institution>다른대학교</institution></author>
        </reference>
      </referenceInfo>""" if with_reference else ""
    article = f"""
      <articleInfo {article_id}>
        <article-categories>의약학 &gt; 내과학</article-categories>
        <article-language>한국어</article-language>
        <keyword-group>{keyword_nodes}</keyword-group>
        <author author-division="1" author-part="제1" orc-id="0000-0002-1234-5678">
          <name>황주희</name><name-eng>Joo-Hee Hwang</name-eng>
          <institution>전북대학교 의과대학</institution>
        </author>
      </articleInfo>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <inputData><key>MASKED</key><apiCode>articleDetail</apiCode></inputData>
  <outputData>
    <record>{article * repeat_article}{reference}
    </record>
  </outputData>
</MetaData>""".encode("utf-8")


class ArticleIdTest(unittest.TestCase):
    """① article-id 일치 / 불일치 / 누락 — 누락을 통과시키면 남의 상세가 얹힌다."""

    def test_일치하면_정상_파싱(self):
        detail = fkw.parse_detail(detail_xml(), "ART000000001")
        self.assertEqual(detail["keywords"], {"ko": ["당뇨병"], "en": ["Diabetes mellitus"]})

    def test_불일치하면_거부(self):
        with self.assertRaises(fetch_kci.KciUnexpectedResponseError) as ctx:
            fkw.parse_detail(detail_xml(article_id='article-id="ART999999999"'), "ART000000001")
        self.assertIn("ART999999999", str(ctx.exception))

    def test_누락되면_거부(self):
        """식별자가 없는 것은 '확인 못 함'이지 '맞음'이 아니다 (fetch_kci와 같은 기준)."""
        with self.assertRaises(fetch_kci.KciUnexpectedResponseError) as ctx:
            fkw.parse_detail(detail_xml(article_id=""), "ART000000001")
        self.assertIn("article-id", str(ctx.exception))

    def test_거부는_재시도_대상(self):
        """기존 재시도 경로를 그대로 탄다 — 일시적 형식 이상이면 다시 시도할 값어치가 있다."""
        self.assertTrue(issubclass(fetch_kci.KciUnexpectedResponseError,
                                   fetch_kci.RETRYABLE_ERRORS))

    def test_인증키는_로그에_남지_않는다(self):
        xml = detail_xml(article_id="").replace(b"<key>MASKED</key>", b"<key>SECRET123</key>")
        with self.assertRaises(fetch_kci.KciUnexpectedResponseError) as ctx:
            fkw.parse_detail(xml, "ART000000001")
        self.assertNotIn("SECRET123", str(ctx.exception))


class ArticleInfoCountTest(unittest.TestCase):
    """③ articleInfo 개수 — 상세 조회는 논문 1편을 묻는 것이다 (0개 / 1개 / 2개 이상)."""

    def test_한_개면_정상(self):
        detail = fkw.parse_detail(detail_xml(repeat_article=1), "ART000000001")
        self.assertEqual(detail["articleLanguage"], "한국어")

    def test_두_개_이상이면_거부(self):
        """첫 번째를 말없이 집으면 어느 논문의 상세인지 알 수 없다 — 형식 변경 신호로 본다."""
        with self.assertRaises(fetch_kci.KciUnexpectedResponseError) as ctx:
            fkw.parse_detail(detail_xml(repeat_article=2), "ART000000001")
        self.assertIn("articleInfo가 2개", str(ctx.exception))

    def test_0개이고_No_Data면_기존대로_None(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?><MetaData><outputData>'
               "<result><resultMsg>No Data</resultMsg></result>"
               "</outputData></MetaData>").encode("utf-8")
        self.assertIsNone(fkw.parse_detail(xml, "ART000000001"))

    def test_0개이고_근거도_없으면_기존대로_거부(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               "<SomethingElse><data /></SomethingElse>").encode("utf-8")
        with self.assertRaises(fetch_kci.KciUnexpectedResponseError):
            fkw.parse_detail(xml, "ART000000001")


class ReferenceInfoTest(unittest.TestCase):
    """② referenceInfo(참고문헌)의 값이 논문 값으로 섞이지 않는지 — 파싱 범위 한정."""

    def setUp(self):
        self.detail = fkw.parse_detail(detail_xml(), "ART000000001")

    def test_참고문헌_키워드가_섞이지_않는다(self):
        everything = self.detail["keywords"]["ko"] + self.detail["keywords"]["en"]
        self.assertNotIn("참고문헌에 딸린 키워드", everything)
        self.assertEqual(len(everything), 2)

    def test_참고문헌_저자가_섞이지_않는다(self):
        names = [a["name"] for a in self.detail["authors"]]
        self.assertEqual(names, ["황주희"])
        self.assertNotIn("참고문헌저자", names)

    def test_참고문헌_언어가_섞이지_않는다(self):
        self.assertEqual(self.detail["articleLanguage"], "한국어")

    def test_참고문헌이_없어도_같은_결과(self):
        without = fkw.parse_detail(detail_xml(with_reference=False), "ART000000001")
        self.assertEqual(without["keywords"], self.detail["keywords"])
        self.assertEqual(without["authors"], self.detail["authors"])


class SplitTest(unittest.TestCase):
    """③ 뭉친 키워드 분리 — 구분자·예외 목록"""

    def test_가운뎃점_계열_전부(self):
        for separator in ("·", ";", "∙", "•", "․"):
            with self.subTest(separator):
                packed = f"Pediatric epilepsy{separator} Surgery{separator} Cognitive function."
                self.assertEqual(
                    fkw.split_packed(packed),
                    ["Pediatric epilepsy", "Surgery", "Cognitive function"],
                )

    def test_공백_둔_슬래시만_구분자(self):
        self.assertEqual(
            fkw.split_packed("Free tissue flaps / Head and neck neoplasms / Microsurgery"),
            ["Free tissue flaps", "Head and neck neoplasms", "Microsurgery"],
        )

    def test_공백_없는_슬래시는_낱말_안(self):
        """'db/db mice'·'LC-MS/MS'를 쪼개면 오히려 망가진다."""
        for text in ("db/db mice", "LC-MS/MS", "Th1/Th2 imbalance", "과잉행동/충동성"):
            with self.subTest(text):
                self.assertEqual(fkw.split_packed(text), [text])

    def test_구분자가_없으면_손대지_않는다(self):
        """끝마침표까지 정리하면 뭉치지 않은 키워드 수백 개가 함께 바뀐다."""
        self.assertEqual(fkw.split_packed("Acute kidney injury."), ["Acute kidney injury."])

    def test_SPLIT_EXCLUSIONS는_쪼개지_않는다(self):
        for text in fkw.SPLIT_EXCLUSIONS:
            with self.subTest(text[:40]):
                self.assertEqual(fkw.split_packed(text), [text])

    def test_한글_영문_분리(self):
        result = fkw.split_keywords(["Diabetes mellitus", "당뇨병", "K-MMSE 검사", "HbA1c"])
        self.assertEqual(result["ko"], ["당뇨병", "K-MMSE 검사"])
        self.assertEqual(result["en"], ["Diabetes mellitus", "HbA1c"])


class SanitizeTest(unittest.TestCase):
    """④ upstream 오염 정제 — 자동으로 손대는 두 가지만"""

    def test_구두점만_있는_값은_버린다(self):
        for text in (".", ",", " . ", "·", "-"):
            with self.subTest(text):
                self.assertIsNone(fkw.sanitize_keyword(text))

    def test_한자_키워드는_살린다(self):
        """守令·月暈은 정상 키워드다. 라틴/한글만 글자로 보면 지워진다 (실측 18건)."""
        for text in ("守令", "兼官", "月暈", "南原縣"):
            with self.subTest(text):
                self.assertEqual(fkw.sanitize_keyword(text), text)

    def test_Keywords_접두사만_뗀다(self):
        cases = {
            "Keywords : Breast neoplasms": "Breast neoplasms",
            ".Keywords: Hepatitis A": "Hepatitis A",
            "Keywords: Diabetes mellitus": "Diabetes mellitus",
            "Key words : Rare Diseases": "Rare Diseases",
            "Key Words : Cerebral venous thrombosis": "Cerebral venous thrombosis",
            "Key word : self-sufficiency program": "self-sufficiency program",
        }
        for before, after in cases.items():
            with self.subTest(before):
                self.assertEqual(fkw.sanitize_keyword(before), after)

    def test_콜론이_없으면_접두사로_보지_않는다(self):
        """'Keyword extraction'을 자르면 안 된다 — 콜론을 반드시 요구하는 이유."""
        for text in ("Keyword extraction", "Keywords", "Key word spotting"):
            with self.subTest(text):
                self.assertEqual(fkw.sanitize_keyword(text), text)

    def test_정제가_파싱_결과에_반영된다(self):
        detail = fkw.parse_detail(
            detail_xml(keywords=("Keywords : Breast neoplasms", ".", "당뇨병")), "ART000000001")
        self.assertEqual(detail["keywords"], {"ko": ["당뇨병"], "en": ["Breast neoplasms"]})

    def test_원본은_keywordsRaw에_그대로(self):
        """정제 전 값을 되돌릴 수 있어야 한다 — raw에는 손대지 않는다."""
        detail = fkw.parse_detail(
            detail_xml(keywords=("Keywords : Breast neoplasms", ".")), "ART000000001")
        self.assertEqual(detail["keywordsRaw"]["en"], ["Keywords : Breast neoplasms", "."])


class SuspectTest(unittest.TestCase):
    """④ 나머지 오염은 지우지 않고 기록만 한다"""

    def test_의심_값을_찾아낸다(self):
        keywords = {
            "ko": ["Corticobasal degeneration접수일: 2007년 1월 18일", "당뇨병"],
            "en": ["merchin@kunsan.ac.kr", "Diabetes mellitus", "Kim JH et al. 1998"],
        }
        found = {s["value"]: s["reasons"] for s in fkw.detect_suspects(keywords)}
        self.assertIn("접수·게재일", found["Corticobasal degeneration접수일: 2007년 1월 18일"])
        self.assertIn("이메일", found["merchin@kunsan.ac.kr"])
        self.assertIn("참고문헌·본문 조각", found["Kim JH et al. 1998"])
        self.assertNotIn("당뇨병", found)          # 정상 키워드는 걸리지 않는다
        self.assertNotIn("Diabetes mellitus", found)

    def test_의심_값을_지우지는_않는다(self):
        """기록만 한다 — 판단은 사람 몫이다."""
        polluted = "Corticobasal degeneration접수일: 2007년 1월 18일"
        detail = fkw.parse_detail(detail_xml(keywords=(polluted,)), "ART000000001")
        self.assertIn(polluted, detail["keywords"]["ko"])

    def test_정상_키워드는_오탐하지_않는다(self):
        """'Revised version of …'가 '접수·게재일'로 걸리면 안 된다 (콜론 요구)."""
        keywords = {"ko": [],
                    "en": ["Revised version of the Korean Spinal Cord Independence Measure"]}
        self.assertEqual(fkw.detect_suspects(keywords), [])


class KeywordFixTest(unittest.TestCase):
    """⑤ KEYWORD_FIXES — 현재 원본이 등록된 지문과 같을 때만 적용"""

    def setUp(self):
        self.raw = {"ko": [], "en": ["Temperament. Address for correspondence", "M.D."]}
        self.keywords = {"ko": [], "en": ["Temperament. Address for correspondence", "M.D."]}
        self.kci_id = "ART_TEST_FIX"
        fkw.KEYWORD_FIXES[self.kci_id] = {
            "rawFingerprint": fkw.raw_fingerprint(self.raw),
            "keep": {"en": ["Temperament"]},
            "reason": "테스트용",
        }
        self.addCleanup(lambda: fkw.KEYWORD_FIXES.pop(self.kci_id, None))

    def test_지문이_같으면_적용(self):
        result, stale = fkw.apply_keyword_fix(self.kci_id, self.keywords, self.raw)
        self.assertEqual(result["en"], ["Temperament"])
        self.assertIsNone(stale)

    def test_지문이_다르면_적용하지_않고_review에_남긴다(self):
        """KCI가 키워드를 정상으로 고쳤을 수 있다 — 영구히 덮어쓰면 안 된다."""
        fixed_upstream = {"ko": [], "en": ["Temperament", "Endophenotype"]}
        result, stale = fkw.apply_keyword_fix(self.kci_id, fixed_upstream, fixed_upstream)
        self.assertEqual(result, fixed_upstream)          # 손대지 않는다
        self.assertIsNotNone(stale)
        self.assertEqual(stale["kciId"], self.kci_id)
        self.assertEqual(stale["expectedFingerprint"],
                         fkw.KEYWORD_FIXES[self.kci_id]["rawFingerprint"])
        self.assertEqual(stale["currentFingerprint"], fkw.raw_fingerprint(fixed_upstream))
        self.assertEqual(stale["currentRaw"], fixed_upstream)

    def test_clearAll도_지문을_본다(self):
        fkw.KEYWORD_FIXES[self.kci_id] = {
            "rawFingerprint": "sha256:0000000000000000",
            "clearAll": True,
            "reason": "테스트용",
        }
        result, stale = fkw.apply_keyword_fix(self.kci_id, self.keywords, self.raw)
        self.assertEqual(result, self.keywords)           # 비우지 않는다
        self.assertIsNotNone(stale)

    def test_지목되지_않은_논문은_그대로(self):
        result, stale = fkw.apply_keyword_fix("ART_NOT_LISTED", self.keywords, self.raw)
        self.assertEqual(result, self.keywords)
        self.assertIsNone(stale)

    def test_실제_목록은_모두_지문을_갖는다(self):
        """지문 없는 fix는 항상 stale로 빠져 아무 일도 하지 않는다."""
        for kci_id, fix in fkw.KEYWORD_FIXES.items():
            if kci_id == self.kci_id:
                continue
            with self.subTest(kci_id):
                self.assertTrue(fix.get("rawFingerprint", "").startswith("sha256:"))
                self.assertIn("reason", fix)


class RecordFixesTest(unittest.TestCase):
    """② 사람이 등록한 개입이 조용히 무효가 되지 않는지 — review에 반드시 남는다."""

    def setUp(self):
        self.kci_id = "ART_TEST_MISSING"
        fkw.KEYWORD_FIXES[self.kci_id] = {
            "rawFingerprint": "sha256:0000000000000000",
            "clearAll": True,
            "reason": "테스트용 — 캐시에 없는 논문",
        }
        self.addCleanup(lambda: fkw.KEYWORD_FIXES.pop(self.kci_id, None))

    def test_캐시에_없는_대상은_keywordFixMissing에_남는다(self):
        state = {"professors": {}}
        _, _, missing, _ = fkw.record_keyword_fixes(state, {})
        ids = [m["kciId"] for m in missing]
        self.assertIn(self.kci_id, ids)
        entry = next(m for m in missing if m["kciId"] == self.kci_id)
        self.assertIn("적용되지 않았습니다", entry["reason"])
        self.assertEqual(entry["fixReason"], "테스트용 — 캐시에 없는 논문")
        self.assertEqual(state["review"]["keywordFixMissing"], missing)

    def test_캐시에_있으면_missing이_아니다(self):
        raw = {"ko": [], "en": ["오염된 값"]}
        details = {self.kci_id: {
            "keywords": {"ko": [], "en": []},
            "keywordsRaw": raw,
            "keywordFixStale": {"kciId": self.kci_id, "reason": "테스트"},
            "articleCategories": [], "articleLanguage": None, "authors": [],
        }}
        _, stale, missing, _ = fkw.record_keyword_fixes({"professors": {}}, details)
        # 실제 KEYWORD_FIXES 항목들은 이 대역 캐시에 없으니 당연히 missing이다.
        # 확인할 것은 "캐시에 있는 대상은 missing이 아니라 stale로 간다"는 것.
        self.assertNotIn(self.kci_id, [m["kciId"] for m in missing])
        self.assertEqual([x["kciId"] for x in stale], [self.kci_id])

    def test_세_목록이_항상_review에_들어간다(self):
        state = {"professors": {}}
        fkw.record_keyword_fixes(state, {})
        for key in ("keywordFixes", "keywordFixStale", "keywordFixMissing", "keywordSuspect"):
            self.assertIn(key, state["review"])


class ReprocessTest(unittest.TestCase):
    """⑥ 캐시 재처리 — API 재호출 없이 현재 규칙을 다시 적용"""

    def test_옛_캐시에_새_규칙이_적용된다(self):
        cached = {
            "keywords": {"ko": ["당뇨병"], "en": ["Keywords : Breast neoplasms", "."]},
            "articleCategories": [], "articleLanguage": "한국어", "authors": [],
        }
        rebuilt = fkw.reprocess_detail("ART000000001", cached)
        self.assertEqual(rebuilt["keywords"], {"ko": ["당뇨병"], "en": ["Breast neoplasms"]})
        self.assertEqual(rebuilt["keywordsRaw"]["en"], ["Keywords : Breast neoplasms", "."])

    def test_이미_정상인_항목은_그대로(self):
        cached = {
            "keywords": {"ko": ["당뇨병"], "en": ["Diabetes mellitus"]},
            "articleCategories": [], "articleLanguage": "한국어", "authors": [],
        }
        rebuilt = fkw.reprocess_detail("ART000000001", cached)
        self.assertEqual(rebuilt["keywords"], cached["keywords"])
        self.assertNotIn("keywordsRaw", rebuilt)

    def test_두_번_돌려도_같은_결과(self):
        cached = {
            "keywords": {"ko": [], "en": ["Keywords : Breast neoplasms", "."]},
            "articleCategories": [], "articleLanguage": "영어", "authors": [],
        }
        once = fkw.reprocess_detail("ART000000001", cached)
        twice = fkw.reprocess_detail("ART000000001", once)
        self.assertEqual(once, twice)
