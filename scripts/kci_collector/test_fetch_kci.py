"""fetch_kci.py 오프라인 단위 테스트 (지시서 3장).

인증키가 아직 없어 실제 호출을 못 하므로, **네트워크 없이** 검증할 수 있는 부분을 고정한다.
표본 XML은 활용가이드에 적힌 필드 이름(article-id / article-title / author@english /
author@orc-id / citation-count 등)을 본떠 만든 것이며 실제 응답을 받아 만든 것이 아니다.
따라서 이 테스트가 통과한다고 실제 응답 파싱이 보장되지는 않는다 —
"구조가 이 모양이면 이렇게 동작한다"까지가 이 테스트의 범위다.

실행 (저장소 루트에서):
    python -m unittest discover -s scripts/kci_collector -v
"""

import unittest
from pathlib import Path

import fetch_kci


# ---------------------------------------------------------------------------
# 표본 XML — 가이드에 적힌 필드 이름을 본뜬 것 (실제 응답 아님)
# ---------------------------------------------------------------------------

# 정상 응답: 3편
#  ① 본인(전북대) 논문 — 모든 칸이 채워진 형태. DOI가 PubMed 논문과 같다
#  ② 동명이인(타 기관) 논문 — 채택되면 안 된다
#  ③ 소속이 비어 있는 논문 — 채택되면 안 된다
SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <outputData>
    <result>
      <total>3</total>
      <page>1</page>
      <displayCount>100</displayCount>
    </result>
    <record>
      <journalInfo>
        <journal-name lang="original">대한내과학회지</journal-name>
        <journal-name lang="english">The Korean Journal of Medicine</journal-name>
        <pub-year>2021</pub-year>
      </journalInfo>
      <articleInfo article-id="ART002712345">
        <article-title lang="original">국내 심부전 환자의 예후 인자 분석</article-title>
        <article-title lang="english">Prognostic Factors in Korean Heart Failure Patients</article-title>
        <author-group>
          <author english="Joo-Hee Hwang" orc-id="0000-0002-1234-5678">황주희(전북대학교 의과대학)</author>
          <author english="Gil-Dong Hong">홍길동(서울대학교)</author>
        </author-group>
        <abstract-group>
          <abstract lang="original">국내 심부전 환자를 대상으로 예후 인자를 분석하였다.</abstract>
          <abstract lang="english">We analyzed prognostic factors in Korean patients.</abstract>
        </abstract-group>
        <citation-count kci="4"/>
        <doi>10.3904/kjm.2021.96.1.1</doi>
        <url>https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002712345</url>
      </articleInfo>
    </record>
    <record>
      <journalInfo>
        <journal-name>다른학회지</journal-name>
        <pub-year>2019</pub-year>
      </journalInfo>
      <articleInfo article-id="ART002700001">
        <article-title lang="original">타 기관 동명이인의 논문</article-title>
        <author-group>
          <author english="Joo Hee Hwang">황주희(부산대학교)</author>
        </author-group>
        <citation-count kci="1"/>
      </articleInfo>
    </record>
    <record>
      <journalInfo>
        <journal-name>소속없는학회지</journal-name>
        <pub-year>2018</pub-year>
      </journalInfo>
      <articleInfo article-id="ART002700002">
        <article-title lang="original">소속 표기가 없는 논문</article-title>
        <author-group>
          <author>황주희</author>
        </author-group>
      </articleInfo>
    </record>
  </outputData>
</MetaData>
"""

# 표기가 다른 응답 — 파서가 구조 차이를 견디는지 확인한다.
# (lang 속성 없음 · citation-count가 요소 텍스트 · 소속이 속성 · orcid 표기 차이 · record 없이 articleInfo만)
SAMPLE_XML_VARIANT = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <articleInfo article-id="ART002799999">
    <article-title>표기가 다른 논문</article-title>
    <journal-name>변형학회지</journal-name>
    <pub-year>2020-03</pub-year>
    <author english="Joo-Hee Hwang" orcid="0000-0002-1234-5678" affiliation="전북대학교병원">황 주희</author>
    <citation-count>12</citation-count>
  </articleInfo>
</MetaData>
"""

SAMPLE_XML_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><outputData><result><total>0</total></result></outputData></MetaData>
"""

# record 하나에 논문이 여러 편 들어 있는 구조 — 첫 편만 남고 나머지가 사라지면 안 된다
SAMPLE_XML_MULTI_IN_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><outputData><record>
  <journalInfo><journal-name>학회지</journal-name><pub-year>2021</pub-year></journalInfo>
  <articleInfo article-id="ART001"><article-title>첫째 논문</article-title></articleInfo>
  <articleInfo article-id="ART002"><article-title>둘째 논문</article-title></articleInfo>
</record></outputData></MetaData>
"""

# 논문을 감싼 태그 이름이 가이드와 다른 구조 — article-id를 단서로 찾아낸다
SAMPLE_XML_ODD_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><item article-id="ART009"><article-title>제목</article-title></item></MetaData>
"""

SAMPLE_XML_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><error>인증키가 유효하지 않습니다.</error></MetaData>
"""


def parse(xml_text):
    return fetch_kci.parse_response(xml_text.encode("utf-8"))


class ParsingTest(unittest.TestCase):
    """① kciId·제목·저자·소속·ORCID·피인용수 파싱"""

    def setUp(self):
        self.articles, self.total = parse(SAMPLE_XML)

    def test_기본_필드(self):
        self.assertEqual(self.total, 3)
        self.assertEqual(len(self.articles), 3)
        paper = self.articles[0]
        self.assertEqual(paper["kciId"], "ART002712345")
        self.assertEqual(paper["title"], "국내 심부전 환자의 예후 인자 분석")
        self.assertEqual(paper["titleEn"], "Prognostic Factors in Korean Heart Failure Patients")
        self.assertEqual(paper["journal"], "대한내과학회지")   # 원어 우선
        self.assertEqual(paper["year"], 2021)
        self.assertEqual(paper["doi"], "10.3904/kjm.2021.96.1.1")
        self.assertIn("ART002712345", paper["url"])
        self.assertEqual(paper["citedByCountKci"], 4)         # 속성(kci="4")
        self.assertEqual(paper["abstract"], "국내 심부전 환자를 대상으로 예후 인자를 분석하였다.")
        self.assertEqual(paper["abstractEn"], "We analyzed prognostic factors in Korean patients.")

    def test_저자_소속_영문명_orcid(self):
        authors = self.articles[0]["authors"]
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0]["name"], "황주희")
        self.assertEqual(authors[0]["affiliation"], "전북대학교 의과대학")
        self.assertEqual(authors[0]["nameEn"], "Joo-Hee Hwang")
        self.assertEqual(authors[0]["orcid"], "0000-0002-1234-5678")
        self.assertEqual(authors[1]["affiliation"], "서울대학교")
        self.assertIsNone(authors[1]["orcid"])               # 없는 값은 null (원칙 2)

    def test_없는_값은_null(self):
        """피인용수·초록·DOI가 없으면 0이나 빈 문자열이 아니라 None이어야 한다 (원칙 2)."""
        paper = self.articles[2]
        self.assertIsNone(paper["citedByCountKci"])
        self.assertIsNone(paper["abstract"])
        self.assertIsNone(paper["doi"])
        self.assertIsNone(paper["titleEn"])

    def test_표기가_달라도_파싱(self):
        """lang 속성 없음·요소형 피인용수·속성형 소속·record 없는 구조도 읽는다."""
        articles, total = parse(SAMPLE_XML_VARIANT)
        self.assertIsNone(total)
        self.assertEqual(len(articles), 1)
        paper = articles[0]
        self.assertEqual(paper["kciId"], "ART002799999")
        self.assertEqual(paper["title"], "표기가 다른 논문")     # lang 없으면 원어로 본다
        self.assertEqual(paper["year"], 2020)                   # "2020-03"에서 연도만
        self.assertEqual(paper["citedByCountKci"], 12)          # 요소 텍스트
        self.assertEqual(paper["authors"][0]["affiliation"], "전북대학교병원")
        self.assertEqual(paper["authors"][0]["orcid"], "0000-0002-1234-5678")  # orcid 표기

    def test_결과_0건과_오류_구분(self):
        articles, total = parse(SAMPLE_XML_EMPTY)
        self.assertEqual(articles, [])
        self.assertEqual(total, 0)
        with self.assertRaises(fetch_kci.KciApiError):
            parse(SAMPLE_XML_ERROR)

    def test_record에_논문이_여럿이어도_다_읽는다(self):
        """구조가 달라도 논문이 조용히 사라지지 않아야 한다 (학술지·연도는 빌 수 있음)."""
        articles, _ = parse(SAMPLE_XML_MULTI_IN_RECORD)
        self.assertEqual([a["kciId"] for a in articles], ["ART001", "ART002"])
        self.assertEqual([a["title"] for a in articles], ["첫째 논문", "둘째 논문"])

    def test_컨테이너_태그가_달라도_찾는다(self):
        articles, _ = parse(SAMPLE_XML_ODD_CONTAINER)
        self.assertEqual([a["kciId"] for a in articles], ["ART009"])

    def test_kciId_없는_항목은_버린다(self):
        """식별자 없는 논문은 계약 원칙 1에 따라 수집 대상이 아니다."""
        xml = SAMPLE_XML.replace(' article-id="ART002712345"', "")
        articles, _ = parse(xml)
        self.assertEqual([a["kciId"] for a in articles], ["ART002700001", "ART002700002"])


class AffiliationTest(unittest.TestCase):
    """② 소속에 전북대가 없는 저자의 논문이 채택되지 않고 review에 기록되는지"""

    def setUp(self):
        articles, _ = parse(SAMPLE_XML)
        self.record, self.unmatched, _ = fetch_kci.build_professor_record(
            "황주희", articles, None, "P-012"
        )

    def test_전북대_논문만_채택(self):
        self.assertEqual([p["kciId"] for p in self.record["papers"]], ["ART002712345"])
        self.assertEqual(
            self.record["stats"],
            {"found": 3, "adopted": 1, "affiliationUnmatched": 2, "homonymUnassigned": 0},
        )

    def test_레코드에_이름이_함께_있다(self):
        """키는 교수 id지만 사람이 읽을 수 있게 name을 레코드 안에 둔다."""
        self.assertEqual(self.record["name"], "황주희")

    def test_제외된_논문은_review에_사유와_함께(self):
        by_id = {entry["kciId"]: entry for entry in self.unmatched}
        self.assertEqual(set(by_id), {"ART002700001", "ART002700002"})
        self.assertEqual(by_id["ART002700001"]["reason"], "타 기관")
        self.assertEqual(by_id["ART002700001"]["affiliations"], ["부산대학교"])  # 검수용 원본 표기
        self.assertEqual(by_id["ART002700002"]["reason"], "소속 정보 없음")
        self.assertEqual(by_id["ART002700001"]["professor"], "황주희")
        self.assertEqual(by_id["ART002700001"]["professorId"], "P-012")

    def test_동명_저자가_없으면_채택하지_않는다(self):
        """다른 사람 이름으로 같은 응답을 처리하면 한 편도 채택되지 않아야 한다."""
        articles, _ = parse(SAMPLE_XML)
        record, unmatched, _ = fetch_kci.build_professor_record("김철수", articles, None)
        self.assertEqual(record["papers"], [])
        self.assertEqual({e["reason"] for e in unmatched}, {"동명 저자 없음"})

    def test_이름_공백_차이_흡수(self):
        """'황 주희'(응답)와 '황주희'(명단)를 같은 사람으로 본다."""
        articles, _ = parse(SAMPLE_XML_VARIANT)
        record, _, _ = fetch_kci.build_professor_record("황주희", articles, None)
        self.assertEqual([p["kciId"] for p in record["papers"]], ["ART002799999"])

    def test_영문_소속만_있으면_채택하지_않는다(self):
        """현재 판정 키워드는 한글 '전북대' 하나 — 영문 표기는 걸러진다(확인 필요 지점)."""
        xml = SAMPLE_XML.replace("황주희(전북대학교 의과대학)", "황주희(Jeonbuk National University)")
        articles, _ = parse(xml)
        record, unmatched, _ = fetch_kci.build_professor_record("황주희", articles, None)
        self.assertEqual(record["papers"], [])
        self.assertEqual(unmatched[0]["reason"], "타 기관")


class AuthorInfoTest(unittest.TestCase):
    """부수 수집(영문명·ORCID) — 대표값 + 관측된 변형 보존 (지시서 2-3-e)"""

    def test_대표값과_변형_목록(self):
        articles, _ = parse(SAMPLE_XML)
        record, _, _ = fetch_kci.build_professor_record("황주희", articles, None)
        self.assertEqual(
            record["authorInfo"],
            {
                "nameEn": "Joo-Hee Hwang",
                "orcid": "0000-0002-1234-5678",
                "nameEnVariants": ["Joo-Hee Hwang"],
                "orcidCandidates": [{"value": "0000-0002-1234-5678", "count": 1}],
            },
        )

    def test_표기가_갈리면_최빈값을_대표로_두고_전부_보존(self):
        adopted = [
            {"paper": {}, "author": {"nameEn": "Joo-Hee Hwang", "orcid": "0000-0002-1234-5678"}},
            {"paper": {}, "author": {"nameEn": "Joo Hee Hwang", "orcid": "0000-0002-1234-5678"}},
            {"paper": {}, "author": {"nameEn": "Joo-Hee Hwang", "orcid": "0000-0003-9999-9999"}},
        ]
        info = fetch_kci.build_author_info(adopted)
        self.assertEqual(info["nameEn"], "Joo-Hee Hwang")
        self.assertEqual(info["nameEnVariants"], ["Joo-Hee Hwang", "Joo Hee Hwang"])  # 많이 나온 순
        self.assertEqual(
            info["orcidCandidates"],
            [{"value": "0000-0002-1234-5678", "count": 2}, {"value": "0000-0003-9999-9999", "count": 1}],
        )

    def test_값이_없으면_null과_빈_목록(self):
        info = fetch_kci.build_author_info([{"paper": {}, "author": {"nameEn": None, "orcid": None}}])
        self.assertEqual(
            info,
            {"nameEn": None, "orcid": None, "nameEnVariants": [], "orcidCandidates": []},
        )


class HomonymTest(unittest.TestCase):
    """동명이인 — 어느 쪽에도 배정하지 않고 후보를 검수 목록으로 넘긴다"""

    def setUp(self):
        articles, _ = parse(SAMPLE_XML)
        self.records, self.unmatched, _, self.entry = fetch_kci.build_homonym_records(
            "황주희", ["P-176", "P-177"], articles, None
        )

    def test_양쪽_모두_빈_papers(self):
        self.assertEqual(set(self.records), {"P-176", "P-177"})
        for professor_id, record in self.records.items():
            self.assertEqual(record["papers"], [], f"{professor_id}에 논문이 배정되면 안 된다")
            self.assertEqual(record["name"], "황주희")

    def test_stats에_미배정_수가_남는다(self):
        """papers가 빈 이유가 '결과 없음'인지 '배정 보류'인지 구분할 수 있어야 한다."""
        self.assertEqual(
            self.records["P-176"]["stats"],
            {"found": 3, "adopted": 0, "affiliationUnmatched": 2, "homonymUnassigned": 1},
        )

    def test_authorInfo도_비운다(self):
        """영문명·ORCID도 어느 쪽 것인지 알 수 없다 — 근거 없이 채우지 않는다."""
        self.assertEqual(
            self.records["P-176"]["authorInfo"],
            {"nameEn": None, "orcid": None, "nameEnVariants": [], "orcidCandidates": []},
        )

    def test_후보_논문과_저자_근거를_review에_기록(self):
        self.assertEqual(self.entry["professor"], "황주희")
        self.assertEqual(self.entry["professorIds"], ["P-176", "P-177"])
        self.assertIn("자동 배정하지 않음", self.entry["reason"])
        self.assertEqual(len(self.entry["candidates"]), 1)
        candidate = self.entry["candidates"][0]
        self.assertEqual(candidate["kciId"], "ART002712345")
        self.assertEqual(candidate["title"], "국내 심부전 환자의 예후 인자 분석")
        self.assertEqual(candidate["year"], 2021)
        # 사람이 두 교수를 가를 수 있는 유일한 단서 — ORCID·소속·영문명
        self.assertEqual(
            candidate["author"],
            {"nameEn": "Joo-Hee Hwang", "orcid": "0000-0002-1234-5678",
             "affiliation": "전북대학교 의과대학"},
        )

    def test_소속_불일치는_그대로_기록되고_id는_비운다(self):
        self.assertEqual(len(self.unmatched), 2)
        self.assertTrue(all(entry["professorId"] is None for entry in self.unmatched))
        self.assertTrue(all(entry["professor"] == "황주희" for entry in self.unmatched))

    def test_채택_후보가_없으면_검수_기록도_없다(self):
        """전부 타 기관이면 배정할 것 자체가 없다 — 빈 검수 기록을 만들지 않는다."""
        xml = SAMPLE_XML.replace("황주희(전북대학교 의과대학)", "황주희(부산대학교)")
        articles, _ = parse(xml)
        records, _, _, entry = fetch_kci.build_homonym_records("황주희", ["P-176", "P-177"], articles, None)
        self.assertIsNone(entry)
        self.assertEqual(records["P-176"]["stats"]["homonymUnassigned"], 0)


class DuplicateTest(unittest.TestCase):
    """③ DOI 일치 / 제목+연도 일치로 중복이 판별되는지, 애매하면 review로 가는지"""

    def _index(self, papers):
        data = {"professors": {"황주희": {"allPapers": papers}}}
        return fetch_kci.build_pubmed_index(data)["황주희"]

    def test_DOI_일치(self):
        index = self._index([
            {"pmid": "33851541", "title": "Something completely different", "year": 2021,
             "doi": "https://doi.org/10.3904/KJM.2021.96.1.1"},   # 대소문자·URL 접두 차이
        ])
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, index)
        self.assertEqual(record["papers"][0]["duplicateOf"], "33851541")
        self.assertEqual(ambiguous, [])

    def test_제목_연도_일치(self):
        """DOI가 없으면 정규화 제목 + 연도로 판별한다 (영문 제목 우선 — PubMed가 영문)."""
        index = self._index([
            {"pmid": "33851541", "year": 2021,
             "title": "Prognostic factors in Korean heart-failure patients."},  # 대소문자·구두점 차이
        ])
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, index)
        self.assertEqual(record["papers"][0]["duplicateOf"], "33851541")
        self.assertEqual(ambiguous, [])

    def test_연도가_다르면_애매(self):
        index = self._index([
            {"pmid": "33851541", "year": 2020,
             "title": "Prognostic Factors in Korean Heart Failure Patients"},
        ])
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, index)
        self.assertIsNone(record["papers"][0]["duplicateOf"])   # 합치지 않는다 (원칙 2)
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0]["reason"], "제목은 같고 연도가 다름")
        self.assertEqual(ambiguous[0]["candidatePmids"], ["33851541"])

    def test_후보가_여럿이면_애매(self):
        index = self._index([
            {"pmid": "1", "year": 2021, "title": "Prognostic Factors in Korean Heart Failure Patients"},
            {"pmid": "2", "year": 2021, "title": "Prognostic factors in Korean heart failure patients"},
        ])
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, index)
        self.assertIsNone(record["papers"][0]["duplicateOf"])
        self.assertEqual(ambiguous[0]["reason"], "제목·연도가 같은 PubMed 논문이 여럿")
        self.assertEqual(ambiguous[0]["candidatePmids"], ["1", "2"])

    def test_비슷하기만_하면_애매(self):
        index = self._index([
            {"pmid": "33851541", "year": 2021,
             "title": "Prognostic Factors in Korean Heart Failure Patients Under 60"},
        ])
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, index)
        self.assertIsNone(record["papers"][0]["duplicateOf"])
        self.assertEqual(ambiguous[0]["reason"], "제목이 비슷하나 완전히 같지는 않음")

    def test_관계없는_논문은_중복_아님(self):
        index = self._index([{"pmid": "1", "year": 2015, "title": "A totally unrelated study"}])
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, index)
        self.assertIsNone(record["papers"][0]["duplicateOf"])
        self.assertEqual(ambiguous, [])

    def test_PubMed_기록이_없는_교수(self):
        """3단계에서 논문 0건이던 교수도 그냥 수집된다 (중복 판별만 건너뜀)."""
        articles, _ = parse(SAMPLE_XML)
        record, _, ambiguous = fetch_kci.build_professor_record("황주희", articles, None)
        self.assertIsNone(record["papers"][0]["duplicateOf"])
        self.assertEqual(ambiguous, [])


class ApiKeyTest(unittest.TestCase):
    """④ 키가 없을 때 안내 후 중단하는지"""

    def _env(self, text):
        path = Path(self.tmp) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = self._tmpdir.name
        self.addCleanup(self._tmpdir.cleanup)

    def test_env_파일_자체가_없으면_중단(self):
        with self.assertRaises(SystemExit) as ctx:
            fetch_kci.read_kci_api_key(Path(self.tmp) / "없는파일.env")
        self.assertIn("KCI_API_KEY", str(ctx.exception))
        self.assertIn("open.kci.go.kr", str(ctx.exception))   # 발급 절차 안내 포함

    def test_다른_키만_있으면_중단(self):
        env = self._env("OPENALEX_API_KEY=abc\n")
        with self.assertRaises(SystemExit):
            fetch_kci.read_kci_api_key(env)

    def test_빈_값이면_중단(self):
        env = self._env("KCI_API_KEY=\n")
        with self.assertRaises(SystemExit):
            fetch_kci.read_kci_api_key(env)

    def test_키가_있으면_읽는다(self):
        env = self._env('# 주석\nOPENALEX_API_KEY=abc\nKCI_API_KEY="my-kci-key"\n')
        self.assertEqual(fetch_kci.read_kci_api_key(env), "my-kci-key")


class RetryTest(unittest.TestCase):
    """재시도 정책 — 5xx는 다시 시도하고 4xx는 즉시 포기한다 (지시서 2-5)."""

    def setUp(self):
        # 테스트가 실제로 5초·15초를 기다리지 않게 대기 시간을 0으로 바꾼다
        original = fetch_kci.RETRY_WAITS
        fetch_kci.RETRY_WAITS = [0, 0]
        self.addCleanup(lambda: setattr(fetch_kci, "RETRY_WAITS", original))

    def _http_error(self, status):
        import requests
        response = requests.Response()
        response.status_code = status
        return requests.exceptions.HTTPError(response=response)

    def test_5xx는_3회까지_시도(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise self._http_error(503)
            return "ok"

        self.assertEqual(fetch_kci.call_with_retry("테스트", flaky), "ok")
        self.assertEqual(len(calls), 3)

    def test_4xx는_즉시_포기(self):
        import requests
        calls = []

        def bad_request():
            calls.append(1)
            raise self._http_error(400)

        with self.assertRaises(requests.exceptions.HTTPError):
            fetch_kci.call_with_retry("테스트", bad_request)
        self.assertEqual(len(calls), 1)

    def test_XML_파싱_실패도_재시도(self):
        """응답이 중간에 끊기면 XML이 깨져 들어온다 — 일시 오류로 보고 다시 시도한다."""
        calls = []

        def broken():
            calls.append(1)
            if len(calls) < 2:
                parse("<MetaData><record>")   # ParseError
            return "ok"

        self.assertEqual(fetch_kci.call_with_retry("테스트", broken), "ok")
        self.assertEqual(len(calls), 2)


class PagingTest(unittest.TestCase):
    """페이지 순회 — 마지막 쪽 판단과 kciId 중복 제거 (네트워크는 대역으로 대체)."""

    def setUp(self):
        original_sleep = fetch_kci.time.sleep
        fetch_kci.time.sleep = lambda seconds: None
        self.addCleanup(lambda: setattr(fetch_kci.time, "sleep", original_sleep))
        self.original_fetch_page = fetch_kci.fetch_page
        self.addCleanup(lambda: setattr(fetch_kci, "fetch_page", self.original_fetch_page))

    def _article(self, kci_id):
        return {"kciId": kci_id, "authors": []}

    def test_마지막_쪽까지_순회하고_중복_제거(self):
        pages = {
            1: ([self._article(f"ART{i:03d}") for i in range(fetch_kci.DISPLAY_COUNT)], 150),
            2: ([self._article("ART099")] + [self._article(f"ART{i:03d}") for i in range(100, 149)], 150),
        }
        requested = []

        def fake_page(api_key, name, page):
            requested.append(page)
            return pages[page]

        fetch_kci.fetch_page = fake_page
        articles = fetch_kci.fetch_articles("key", "황주희")
        self.assertEqual(requested, [1, 2])           # 2쪽이 100건 미만 → 거기서 멈춘다
        self.assertEqual(len(articles), 149)          # 쪽 경계 중복(ART099) 1건 제거
        self.assertEqual(len({a["kciId"] for a in articles}), 149)

    def test_결과가_없으면_한_쪽만_요청(self):
        requested = []

        def fake_page(api_key, name, page):
            requested.append(page)
            return [], 0

        fetch_kci.fetch_page = fake_page
        self.assertEqual(fetch_kci.fetch_articles("key", "황주희"), [])
        self.assertEqual(requested, [1])


if __name__ == "__main__":
    unittest.main()
