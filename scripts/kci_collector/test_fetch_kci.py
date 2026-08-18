"""fetch_kci.py 오프라인 단위 테스트 (지시서 3장).

표본 XML은 **2026-08-18 실제 KCI 응답을 받아 그 구조 그대로** 만든 것이다
(교수명·논문 정보만 바꿔 축약). 실측으로 확인한 실제 구조는 다음과 같다:

    MetaData > inputData(key·apiCode·author·page·displayCount 에코)
             > outputData > result > total
                          > record > journalInfo(journal-name·publisher-name·pub-year·…)
                                   > articleInfo@article-id
                                       > title-group > article-title lang=original|foreign|english
                                       > author-group > author@english@orc-id  "이름(소속기관)"
                                       > abstract-group > abstract lang=original|english
                                       > doi(전체 URL 또는 빈 값) · uci · url
                                       > citation-count@kci@wos (텍스트에도 같은 수)

주의(실측): **오류에도 HTTP 200이 오고 error 태그는 없다.** 결과 0건과 오류가 모두
result/resultMsg 한 칸으로 오므로("No Data" vs "등록되지 않은 key 입니다.") 이를 가르는
테스트를 반드시 유지해야 한다 — 이 구분이 깨지면 인증키 오류가 '논문 0건'으로 삼켜진다.

실행 (저장소 루트에서):
    python -m unittest discover -s scripts/kci_collector -v
"""

import json
import re
import unittest
from pathlib import Path

import fetch_kci


# ---------------------------------------------------------------------------
# 표본 XML — 2026-08-18 실제 응답 구조 그대로 (내용만 축약·치환)
# ---------------------------------------------------------------------------

# 정상 응답: 4편
#  ① 본인(전북대) 논문 — 실제 응답의 모든 칸을 갖춘 형태. doi가 URL로 오는 것도 실측 그대로
#  ② 동명이인(타 기관) 논문 — 채택되면 안 된다
#  ③ 소속이 비어 있는 논문 — 채택되면 안 된다 (실측: 315명 중 12명이 괄호 없는 표기였다)
#  ④ 소속이 영문으로만 오는 본인 논문 — 실측으로 확인된 형태. 채택되어야 한다
SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <inputData>
    <key>MASKED</key>
    <apiCode>articleSearch</apiCode>
    <author>황주희</author>
    <page>1</page>
    <displayCount>100</displayCount>
  </inputData>
  <outputData>
    <result>
      <total>4</total>
    </result>
    <record>
      <journalInfo>
        <journal-name>대한내과학회지</journal-name>
        <publisher-name>대한내과학회</publisher-name>
        <pub-year>2021</pub-year>
        <pub-mon>03</pub-mon>
        <volume>96</volume>
        <issue>1</issue>
      </journalInfo>
      <articleInfo article-id="ART002712345">
        <article-categories>내과학</article-categories>
        <article-regularity>Y</article-regularity>
        <title-group>
          <article-title lang="original"><![CDATA[국내 심부전 환자의 예후 인자 분석]]></article-title>
          <article-title lang="foreign"><![CDATA[Prognostic Factors in Korean Heart Failure Patients]]></article-title>
          <article-title lang="english"><![CDATA[Prognostic Factors in Korean Heart Failure Patients]]></article-title>
        </title-group>
        <author-group>
          <author english="Joo-Hee Hwang" orc-id="0000-0002-1234-5678">황주희(전북대학교 의과대학)</author>
          <author english="Gil-Dong Hong">홍길동(서울대학교)</author>
        </author-group>
        <abstract-group>
          <abstract lang="original"><![CDATA[국내 심부전 환자를 대상으로 예후 인자를 분석하였다.]]></abstract>
          <abstract lang="english"><![CDATA[We analyzed prognostic factors in Korean patients.]]></abstract>
        </abstract-group>
        <fpage>1</fpage>
        <lpage>9</lpage>
        <doi>http://dx.doi.org/10.3904/kjm.2021.96.1.1</doi>
        <uci></uci>
        <citation-count kci="4" wos="0">4</citation-count>
        <url>https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002712345</url>
        <verified>Y</verified>
      </articleInfo>
    </record>
    <record>
      <journalInfo>
        <journal-name>다른학회지</journal-name>
        <pub-year>2019</pub-year>
      </journalInfo>
      <articleInfo article-id="ART002700001">
        <title-group>
          <article-title lang="original"><![CDATA[타 기관 동명이인의 논문]]></article-title>
        </title-group>
        <author-group>
          <author english="Joo Hee Hwang">황주희(부산대학교)</author>
        </author-group>
        <doi></doi>
        <citation-count kci="1" wos="0">1</citation-count>
      </articleInfo>
    </record>
    <record>
      <journalInfo>
        <journal-name>소속없는학회지</journal-name>
        <pub-year>2018</pub-year>
      </journalInfo>
      <articleInfo article-id="ART002700002">
        <title-group>
          <article-title lang="original"><![CDATA[소속 표기가 없는 논문]]></article-title>
        </title-group>
        <author-group>
          <author>황주희</author>
        </author-group>
        <citation-count kci="0" wos="0">0</citation-count>
      </articleInfo>
    </record>
    <record>
      <journalInfo>
        <journal-name>The Korean Journal of Physiology and Pharmacology</journal-name>
        <pub-year>2016</pub-year>
      </journalInfo>
      <articleInfo article-id="ART002700003">
        <title-group>
          <article-title lang="original"><![CDATA[영문 소속으로만 오는 본인 논문]]></article-title>
        </title-group>
        <author-group>
          <author english="Joo-Hee Hwang">황주희(Center for Clinical Pharmacology, Jeonbuk National University Hospital, Jeonju 54907, Korea)</author>
        </author-group>
        <citation-count kci="2" wos="1">2</citation-count>
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

# 결과 0건 — 실측 그대로. total이 없고 resultMsg "No Data"만 온다 (HTTP 200)
SAMPLE_XML_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <inputData><key>MASKED</key><apiCode>articleSearch</apiCode><author>가나다라마바사</author></inputData>
  <outputData><result><resultMsg>No Data</resultMsg></result></outputData>
</MetaData>
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

# 인증키 오류 — 실측 그대로. HTTP 200 · error 태그 없음 · 0건과 같은 자리(resultMsg)에 온다
SAMPLE_XML_BAD_KEY = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <inputData><key>0000000000</key><apiCode>articleSearch</apiCode><author>강경표</author></inputData>
  <outputData><result><resultMsg>등록되지 않은 key 입니다.</resultMsg></result></outputData>
</MetaData>
"""

# 잘못된 apiCode — 실측 그대로
SAMPLE_XML_BAD_APICODE = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <inputData><key>MASKED</key><apiCode>noSuchCode</apiCode></inputData>
  <outputData><result><resultMsg>등록되지 않은 서비스</resultMsg></result></outputData>
</MetaData>
"""


def parse(xml_text):
    return fetch_kci.parse_response(xml_text.encode("utf-8"))


class ParsingTest(unittest.TestCase):
    """① kciId·제목·저자·소속·ORCID·피인용수 파싱"""

    def setUp(self):
        self.articles, self.total = parse(SAMPLE_XML)

    def test_기본_필드(self):
        self.assertEqual(self.total, 4)
        self.assertEqual(len(self.articles), 4)
        paper = self.articles[0]
        self.assertEqual(paper["kciId"], "ART002712345")
        self.assertEqual(paper["title"], "국내 심부전 환자의 예후 인자 분석")   # CDATA도 그대로 읽는다
        self.assertEqual(paper["titleEn"], "Prognostic Factors in Korean Heart Failure Patients")
        self.assertEqual(paper["journal"], "대한내과학회지")   # journal-name에는 lang 속성이 없다
        self.assertEqual(paper["year"], 2021)
        # doi는 실제로 전체 URL로 온다 — 원본 그대로 두고(원칙 4) 비교할 때만 정규화한다
        self.assertEqual(paper["doi"], "http://dx.doi.org/10.3904/kjm.2021.96.1.1")
        self.assertEqual(fetch_kci.normalize_doi(paper["doi"]), "10.3904/kjm.2021.96.1.1")
        self.assertIn("ART002712345", paper["url"])
        # citation-count는 kci·wos 속성과 텍스트를 함께 가진다 — kci 속성을 쓴다
        self.assertEqual(paper["citedByCountKci"], 4)
        self.assertEqual(paper["abstract"], "국내 심부전 환자를 대상으로 예후 인자를 분석하였다.")
        self.assertEqual(paper["abstractEn"], "We analyzed prognostic factors in Korean patients.")

    def test_lang_foreign은_영문_제목으로_쓰지_않는다(self):
        """실측 lang 값은 original·foreign·english 세 가지 — english만 titleEn으로 쓴다."""
        xml = SAMPLE_XML.replace('<article-title lang="english"><![CDATA[Prognostic Factors in '
                                 'Korean Heart Failure Patients]]></article-title>', "")
        articles, _ = parse(xml)
        self.assertIsNone(articles[0]["titleEn"])
        self.assertEqual(articles[0]["title"], "국내 심부전 환자의 예후 인자 분석")

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
        """초록·DOI가 없으면 빈 문자열이 아니라 None이어야 한다 (원칙 2).

        실측: doi는 빈 요소(<doi></doi>)로 오는 경우가 절반쯤 된다 (강경표 69편 중 34편).
        """
        paper = self.articles[2]
        self.assertIsNone(paper["abstract"])
        self.assertIsNone(paper["doi"])          # <doi></doi> 빈 요소
        self.assertIsNone(paper["titleEn"])
        self.assertEqual(paper["citedByCountKci"], 0)   # kci="0"은 '0회 인용'이라는 값이다

    def test_피인용수_0과_미상은_다르다(self):
        """kci="0"은 0회 인용(값 있음), citation-count 자체가 없으면 미상(None)."""
        xml = SAMPLE_XML.replace('<citation-count kci="0" wos="0">0</citation-count>', "")
        articles, _ = parse(xml)
        self.assertEqual(articles[0]["citedByCountKci"], 4)
        self.assertIsNone(articles[2]["citedByCountKci"])

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
        """실측 핵심: 오류도 HTTP 200 + resultMsg로 온다. 0건과 오류를 반드시 갈라야 한다.

        이 구분이 깨지면 인증키가 틀렸을 때 182명 전원이 '논문 0건'으로 조용히 저장된다.
        """
        articles, total = parse(SAMPLE_XML_EMPTY)   # resultMsg "No Data"
        self.assertEqual(articles, [])
        self.assertIsNone(total)                    # 0건 응답에는 total 자체가 없다

        with self.assertRaises(fetch_kci.KciApiError) as ctx:
            parse(SAMPLE_XML_BAD_KEY)
        self.assertIn("등록되지 않은 key", str(ctx.exception))

        with self.assertRaises(fetch_kci.KciApiError):
            parse(SAMPLE_XML_BAD_APICODE)

    def test_모르는_문구는_오류로_본다(self):
        """알 수 없는 resultMsg는 0건이 아니라 오류로 취급한다 (조용히 삼키지 않는다)."""
        xml = SAMPLE_XML_BAD_KEY.replace("등록되지 않은 key 입니다.", "일일 허용량 초과")
        with self.assertRaises(fetch_kci.KciApiError):
            parse(xml)

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
        self.assertEqual(
            [a["kciId"] for a in articles], ["ART002700001", "ART002700002", "ART002700003"]
        )


class AffiliationTest(unittest.TestCase):
    """② 소속에 전북대가 없는 저자의 논문이 채택되지 않고 review에 기록되는지"""

    def setUp(self):
        articles, _ = parse(SAMPLE_XML)
        self.record, self.unmatched, _ = fetch_kci.build_professor_record(
            "황주희", articles, None, "P-012"
        )

    def test_전북대_논문만_채택(self):
        # ① 한글 소속 · ④ 영문 소속 → 채택 / ② 타 기관 · ③ 소속 없음 → 제외
        self.assertEqual(
            [p["kciId"] for p in self.record["papers"]], ["ART002712345", "ART002700003"]
        )
        self.assertEqual(
            self.record["stats"],
            {"found": 4, "adopted": 2, "affiliationUnmatched": 2, "homonymUnassigned": 0},
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

    def test_영문_소속도_채택한다(self):
        """실측 반영 — 소속이 영문으로만 오는 논문이 실제로 있어 키워드를 확장했다.

        확장 전에는 이런 논문이 '타 기관'으로 빠졌다 (곽용근 13편 중 1편, 강경표 22편 중 1편).
        """
        for affiliation in (
            "Center for Clinical Pharmacology, Jeonbuk National University Hospital, Jeonju",
            "Department of Internal Medicine, Chonbuk National University Medical School",
            "Jeonbuk National Univ.",
            "JEONBUK NATIONAL UNIVERSITY HOSPITAL",   # 대소문자 무관
            # KCI가 긴 영문 소속을 150자에서 자른다 — "…Jeonbuk National Unive"로 끝나기도 한다
            "Department of Radiology, Research Institute of Clinical Medicine of Jeonbuk "
            "National UniversityBiomedical Research Institute of Jeonbuk National Unive",
            # 잘림이 기관명 한가운데 떨어진 실측 사례 (신진용 ART002727150)
            "Department of Plastic and Reconstructive Surgery, "
            "Research Institute of Clinical Medicine of Jeonbuk",
        ):
            self.assertTrue(fetch_kci.is_jbnu(affiliation), affiliation)

    def test_한글_약칭도_채택한다(self):
        """실측: 의학 논문은 '전북의대'로 줄여 쓰는 경우가 많다 (제외 목록에서 45편 발견)."""
        for affiliation in ("전북의대", "전북의대 내과학", "전북의대 산부인과",
                            "전북의학전문대학원", "전북대학교병원", "전북대학병원"):
            self.assertTrue(fetch_kci.is_jbnu(affiliation), affiliation)

    def test_전북_지역_다른_기관은_채택하지_않는다(self):
        """'jeonbuk'·'전북'만으로 판정하면 전북대와 무관한 기관까지 걸린다 — 그러면 안 된다.

        아래는 모두 실제 응답의 제외 목록에 있던 표기다.
        """
        for affiliation in ("전주대학교", "전주예수병원", "전주교육대학교", "전북농업기술원",
                            "전주기전대학", "전북보건환경연구원", "전주비전대학교", "전북테크노파크",
                            "전북특별자치도 감염병관리지원단", "원광대학교", "원광의대",
                            "Jeonbuk Institute of Automotive Technology",
                            "Jeonbuk Internet Addiction Center,Korea",
                            "Jeonbuk A.R.E.S. Medicinal Resources Research Institute",
                            "Jeonju University"):
            self.assertFalse(fetch_kci.is_jbnu(affiliation), affiliation)


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
            {"found": 4, "adopted": 0, "affiliationUnmatched": 2, "homonymUnassigned": 2},
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
        self.assertEqual(len(self.entry["candidates"]), 2)   # 한글 소속 ① + 영문 소속 ④
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
        xml = re.sub(r"황주희\(Center for[^)]*\)", "황주희(부산대학교)", xml)
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


class SaveStateTest(unittest.TestCase):
    """산출물 저장 — 윈도우에서 파일이 잠겨 있어도 실행이 죽지 않아야 한다.

    실측(2026-08-18): 진행 상황을 보려고 산출물을 읽는 것만으로 os.replace가
    PermissionError를 내며 40분짜리 실행이 중단됐다.
    """

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.output = Path(self._tmpdir.name) / "kci_papers.json"

        original_output = fetch_kci.OUTPUT_PATH
        original_wait = fetch_kci.SAVE_RETRY_WAIT
        fetch_kci.OUTPUT_PATH = self.output
        fetch_kci.SAVE_RETRY_WAIT = 0            # 테스트가 실제로 기다리지 않게
        self.addCleanup(lambda: setattr(fetch_kci, "OUTPUT_PATH", original_output))
        self.addCleanup(lambda: setattr(fetch_kci, "SAVE_RETRY_WAIT", original_wait))

        self.original_replace = fetch_kci.os.replace
        self.addCleanup(lambda: setattr(fetch_kci.os, "replace", self.original_replace))

    def _state(self):
        return {"collectedAt": None, "professors": {"P-001": {"name": "강경표"}},
                "review": {key: [] for key in fetch_kci.REVIEW_KEYS}}

    def test_잠깐_잠겨_있으면_다시_시도해_저장한다(self):
        calls = []

        def flaky_replace(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "액세스가 거부되었습니다")
            return self.original_replace(src, dst)

        fetch_kci.os.replace = flaky_replace
        fetch_kci.save_state(self._state())
        self.assertEqual(len(calls), 3)
        saved = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(saved["professors"]["P-001"]["name"], "강경표")

    def test_계속_잠겨_있어도_예외로_죽지_않는다(self):
        """수집한 결과를 버리지 않도록 임시 파일을 남기고 계속 진행한다."""
        def always_locked(src, dst):
            raise PermissionError(5, "액세스가 거부되었습니다")

        fetch_kci.os.replace = always_locked
        fetch_kci.save_state(self._state())          # 예외가 올라오면 안 된다
        tmp = self.output.with_suffix(".json.tmp")
        self.assertTrue(tmp.exists())                 # 결과는 임시 파일에 남아 있다
        self.assertEqual(
            json.loads(tmp.read_text(encoding="utf-8"))["professors"]["P-001"]["name"], "강경표"
        )


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
