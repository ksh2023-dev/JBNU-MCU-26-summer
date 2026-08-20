"""build_all.py 인용문 파서·제목 대조 오프라인 단위 테스트.

이 테스트가 고정하는 버그(2026-08-20 리뷰에서 실제 재현):
    구 파서는 앞에서부터 첫 마침표까지를 제목으로 봤다. 그래서 제목 안에 마침표나
    숫자가 있으면("… Records of 2000-2019.") 거기서 잘리고, 그 다음 조각인 학술지명
    "J Korean Med Sci"가 제목 자리로 올라왔다. 그 학술지명으로 PubMed를 검색하니
    제목 안에 학술지명을 담고 있는 남의 논문(정정 공지)이 걸렸고, titles_match()의
    무조건 부분 문자열 허용(a in b or b in a) 때문에 검증까지 통과해 버렸다.
    결과: 이경애·조대선 교수에게 원본 인용문에 없는 논문이 배정됐다.

    아래 두 PMID는 실제 PubMed 제목을 그대로 넣었다. 둘 다 제목 안에
    "J Korean Med Sci"를 문자 그대로 담고 있어서 부분 일치로 통과했던 사례다.
    - 26839493: 실제 산출물(professors_papers.json)에 들어가 있던 오귀속 논문
    - 37750376: 리뷰 당시 같은 검색어로 잡혔던 논문 (relevance 정렬이라 시점에 따라 다름)

실행 (저장소 루트에서):
    python -m unittest discover -s scripts/pubmed_collector -v
"""

import json
import unittest
from pathlib import Path

import build_all


# ---------------------------------------------------------------------------
# 실제 입력 인용문 (data/input/professor_paper_lists.json 원문 그대로)
# ---------------------------------------------------------------------------

# 이경애 교수 — 제목 안의 "2000-2019."에서 잘려 학술지명이 제목이 됐던 인용문
CITATION_LEE = (
    "Treatment Patterns of Type 2 Diabetes Assessed Using a Common Data Model "
    "Based on Electronic Health Records of 2000-2019. J Korean Med Sci. "
    "2021 Sep 13;36(36):e230."
)
TITLE_LEE = (
    "Treatment Patterns of Type 2 Diabetes Assessed Using a Common Data Model "
    "Based on Electronic Health Records of 2000-2019"
)

# 조대선 교수 — 저자 목록과 제목이 마침표 없이 붙어 있어("Choi EH.Hospital-Based")
# 저자 조각으로 통째로 버려지고 학술지명만 남았던 인용문
CITATION_JO = (
    ". Kang D, Yun KW, Lee H, Song ES, Ahn JG, Park SE, Lee T, Cho HK, Lee J, Kim YJ, "
    "Jo DS, Kang HM, Lee JK, Kim CS, Kim DH, Choi JH, Eun BW, Kim NH, Cho EY, Kim YK, "
    "Kim HW, Choi EH.Hospital-Based Surveillance of Pediatric Invasive Pneumococcal "
    "Diseases, 2016-2023 in Korea: Serotype Trends and Vaccination Policy. "
    "J Korean Med Sci. 2025 Oct 20;40(40):e250."
)
TITLE_JO = (
    "Hospital-Based Surveillance of Pediatric Invasive Pneumococcal Diseases, "
    "2016-2023 in Korea: Serotype Trends and Vaccination Policy"
)

# 오귀속으로 붙었던 논문들의 실제 PubMed 제목 (efetch 응답 그대로)
TITLE_PMID_26839493 = (
    "Notice of Retraction: Pak CS, et al. A Phase III, Randomized, Double-Blind, "
    "Matched-Pairs, Active-Controlled Clinical Trial and Preclinical Animal Study to "
    "Compare the Durability, Efficacy and Safety between Polynucleotide Filler and "
    "Hyaluronic Acid Filler in the Correction of Crow's Feet: A New Concept of "
    "Regenerative Filler. J Korean Med Sci 2014; 29(Suppl 3): S201-S209."
)
TITLE_PMID_37750376 = (
    'Retraction: "Two Cases of Herpes Gladiatorum Identified in a Korean '
    'Middle-School Wrestling Team: A Case Report," by Soongang Park and Joon Kee Lee, '
    "J Korean Med Sci 2023 Sep 11;38(36):e288."
)


class 오귀속_재발_방지(unittest.TestCase):
    """리뷰에서 재현된 두 인용문을 고정한다."""

    def test_이경애_인용문에서_학술지명이_아니라_제목을_뽑는다(self):
        title, journal = build_all.parse_citation(CITATION_LEE)
        self.assertEqual(title, TITLE_LEE)
        self.assertEqual(journal, "J Korean Med Sci")

    def test_조대선_인용문에서_학술지명이_아니라_제목을_뽑는다(self):
        title, journal = build_all.parse_citation(CITATION_JO)
        self.assertEqual(title, TITLE_JO)
        self.assertEqual(journal, "J Korean Med Sci")

    def test_학술지명이_제목으로_들어오면_대조에서_거부한다(self):
        # 파서가 어떤 이유로든 학술지명을 제목 자리에 올리면, 그 뒤 단계에서 반드시 막힌다
        for fetched in (TITLE_PMID_26839493, TITLE_PMID_37750376):
            self.assertFalse(
                build_all.titles_match("J Korean Med Sci", fetched, "J Korean Med Sci")
            )
            # journal을 못 넘겨받은 경우에도 길이 문턱 때문에 부분 일치로 통과하지 못한다
            self.assertFalse(build_all.titles_match("J Korean Med Sci", fetched))

    def test_두_교수에게_오귀속_논문이_배정되지_않는다(self):
        # 실제 파이프라인 순서 그대로: 인용문 → (제목, 학술지명) → 수집 논문과 대조
        for citation in (CITATION_LEE, CITATION_JO):
            title, journal = build_all.parse_citation(citation)
            for fetched in (TITLE_PMID_26839493, TITLE_PMID_37750376):
                self.assertFalse(build_all.titles_match(title, fetched, journal))

    def test_같은_인용문의_올바른_논문은_그대로_통과한다(self):
        title, journal = build_all.parse_citation(CITATION_LEE)
        self.assertTrue(
            build_all.titles_match(
                title,
                "Treatment Patterns of Type 2 Diabetes Assessed Using a Common Data Model "
                "Based on Electronic Health Records of 2000-2019.",
                journal,
            )
        )


class 정상_인용문_파싱(unittest.TestCase):
    """기존에 잘 처리되던 인용문 형식들이 깨지지 않았는지 확인한다 (전부 실제 입력 원문)."""

    def test_저자가_앞에_오는_형식(self):
        title, journal = build_all.parse_citation(
            "Lee CS, Hwang JH, Lee JH, Song SK, Cho JH, Lee JH. Appropriate oral "
            "antibiotics for bone and joint infections based on the susceptibility of "
            "clinical Staphylococcus aureus isolates. Korean J Intern Med. 2015;30(2):262-4."
        )
        self.assertEqual(
            title,
            "Appropriate oral antibiotics for bone and joint infections based on the "
            "susceptibility of clinical Staphylococcus aureus isolates",
        )
        self.assertEqual(journal, "Korean J Intern Med")

    def test_저자가_제목_뒤에_오는_형식(self):
        title, journal = build_all.parse_citation(
            "Decompression for Unerupted Primary Mandibular Second Molars Associated with "
            "Physical Barriers: Case Reports. Lee DW, Kim JG, Yang YM. J Clin Pediatr Dent. "
            "2018;42(2):150-154. doi: 10.17796/1053-4628-42.2.12. Epub 2017 Oct 31."
        )
        self.assertEqual(
            title,
            "Decompression for Unerupted Primary Mandibular Second Molars Associated with "
            "Physical Barriers: Case Reports",
        )
        self.assertEqual(journal, "J Clin Pediatr Dent")

    def test_연도가_맨_앞에_오는_형식(self):
        title, journal = build_all.parse_citation(
            "2025, Development of a survey-based stacked ensemble predictive model for "
            "autonomy preferences in patients with periodontal disease, Journal of Dentistry"
        )
        self.assertEqual(
            title,
            "Development of a survey-based stacked ensemble predictive model for "
            "autonomy preferences in patients with periodontal disease",
        )
        self.assertEqual(journal, "Journal of Dentistry")

    def test_괄호_연도가_제목_앞에_오는_형식(self):
        title, _ = build_all.parse_citation(
            "HEO SM, Sung RS, Scannapieco FA, Haase EM. (2011) Genetic relationships between "
            "Candida albicans strains isolated from dental plaque, trachea, and "
            "bronchoalveolar lavage fluid from mechanically ventilated intensive care unit "
            "patients. Journal of Clinical Microbiology, 49(9):3268-73"
        )
        self.assertTrue(title.startswith("Genetic relationships between Candida albicans"), title)
        self.assertNotIn("HEO SM", title)

    def test_제목과_학술지가_마침표만으로_붙어_있는_형식(self):
        title, journal = build_all.parse_citation(
            "Lactobacillus plantarum HAC01 Supplementation Improves Glycemic Control in "
            "Prediabetic Subjects: A Randomized, Double-Blind, Placebo-Controlled "
            "Trial.Nutrients. 2021."
        )
        self.assertEqual(
            title,
            "Lactobacillus plantarum HAC01 Supplementation Improves Glycemic Control in "
            "Prediabetic Subjects: A Randomized, Double-Blind, Placebo-Controlled Trial",
        )
        self.assertEqual(journal, "Nutrients")

    def test_제목_안의_연도는_꼬리로_보지_않는다(self):
        title, _ = build_all.parse_citation(
            "The 2017 Korean National Growth Charts for children and adolescents: "
            "development, improvement, and prospects. 2018"
        )
        self.assertEqual(
            title,
            "The 2017 Korean National Growth Charts for children and adolescents: "
            "development, improvement, and prospects",
        )

    def test_형식이_아니면_제목을_지어내지_않는다(self):
        # 마지막 항목은 이행진 교수 실제 인용문 — 제목 자리에 "Correspondence"밖에 없어
        # 구 파서는 그것을 제목으로 삼아 검색했다. 이제는 지어내지 않고 parseFailed로 넘긴다.
        for citation in (
            "",
            "   ",
            "Correspondence. Lee HJ, Kim JY. Retina. 2018 Feb;38(2):e13-e14.",
        ):
            self.assertIsNone(build_all.parse_citation(citation)[0], citation)


class 저자_표기_형식(unittest.TestCase):
    """제목에 저자 목록이 남으면 검색어가 깨져 논문을 아예 못 찾는다.
    2026-08-20 전체 재실행에서 이 형식들 때문에 실제 논문 35편을 놓쳤다 (전부 실제 입력 원문)."""

    def test_et_al_접두(self):
        title, _ = build_all.parse_citation(
            "Shin YS, Zhang LT, Zhao C, et al. Twelve-week, prospective, open-label, randomized "
            "trial on the effects of an anticholinergic agent or antidiuretic agent as add-on "
            "therapy to an alpha-blocker for lower urinary tract symptoms. Clin Interv Aging. "
            "2014;9:1021-30."
        )
        self.assertTrue(title.startswith("Twelve-week, prospective"), title)
        self.assertNotIn("et al", title)

    def test_전체_이름_저자(self):
        title, _ = build_all.parse_citation(
            "Heung Yong Jin, Kyung Ae Lee ,Jin Zu Wu ,Hong Sun Baek ,Tae Sun Park. "
            "The Neuroprotective benefit from Pioglitazone (PIO) addition on the Alpha lipoic "
            "acid (ALA)-based treatment in experimental diabetic rats. Endocrine. 2014;46(3):585-92."
        )
        self.assertTrue(title.startswith("The Neuroprotective benefit"), title)
        self.assertNotIn("Heung Yong Jin", title)

    def test_학위_표기가_섞인_저자(self):
        title, _ = build_all.parse_citation(
            "Jun Tak Choi, MD, Jeong-Hwan Seo, MD, PhD, Myoung-Hwan Ko, MD, PhD, "
            "Yu Hui Won, MD, PhD. Validation of Korean Version of the London Chest Activity of "
            "Daily Living Scale. Ann Rehabil Med. 2018;42(2):329-335."
        )
        self.assertTrue(title.startswith("Validation of Korean Version"), title)
        self.assertNotIn("MD", title)

    def test_세미콜론_저자_목록(self):
        title, _ = build_all.parse_citation(
            "Lee, S.H.; Choi, C.W. The protective effect of CXC chemokine receptor 2 antagonist "
            "on experimental bronchopulmonary dysplasia induced by intra-amniotic endotoxin. "
            "Int J Mol Sci. 2020;21(15):5306."
        )
        self.assertTrue(title.startswith("The protective effect"), title)
        self.assertNotIn("Lee", title)

    def test_주저자_꼬리표(self):
        title, _ = build_all.parse_citation(
            "<주저자> Increasing incidence of Parkinson's disease in patients with epilepsy: "
            "A Nationwide cohort study. J Neurol Sci 458: 122891"
        )
        self.assertTrue(title.startswith("Increasing incidence"), title)

    def test_성과_이니셜이_붙은_오타(self):
        title, _ = build_all.parse_citation(
            "YoonSJ, Lee KB. Cervical spinal brucellosis with epidural abscess causing neurologic "
            "deficit with negative serologic tests. World Neurosurg. 2012;78(3-4):375.e15-8."
        )
        self.assertTrue(title.startswith("Cervical spinal brucellosis"), title)

    def test_저자가_제목_뒤에_와도_제목을_먹지_않는다(self):
        # 위 오타 보정이 과하게 작동하면 "제목. Lee DW, Kim JG, Yang YM"의 제목까지 저자로 먹는다
        title, _ = build_all.parse_citation(
            "Decompression for Unerupted Primary Mandibular Second Molars Associated with "
            "Physical Barriers: Case Reports. Lee DW, Kim JG, Yang YM. J Clin Pediatr Dent. "
            "2018;42(2):150-154."
        )
        self.assertEqual(
            title,
            "Decompression for Unerupted Primary Mandibular Second Molars Associated with "
            "Physical Barriers: Case Reports",
        )


class 역순_인용_형식(unittest.TestCase):
    """정윤규 교수 인용문 10건은 "학술지명. 연도;권(호):쪽 (제목)" 역순이다.
    일반 파싱에 맡기면 학술지명이 제목이 되어 논문 0편이 된다."""

    def test_괄호_안이_제목이다(self):
        title, journal = build_all.parse_citation(
            "Arch Craniofac Surg. 2018 Dec;19(4):260-263 "
            "(Reconstruction of cutaneous defects of the nasal tip and alar by two different methods)"
        )
        self.assertEqual(
            title, "Reconstruction of cutaneous defects of the nasal tip and alar by two different methods"
        )
        self.assertEqual(journal, "Arch Craniofac Surg")

    def test_반대로_괄호가_학술지명이면_제목으로_보지_않는다(self):
        # 오세웅 교수 인용문 7건은 "제목? (학술지명…)" 으로 정반대다
        title, _ = build_all.parse_citation(
            "How far is the root apex of a unilateral impacted canine from the root apices' arch "
            "form? (American Journal of Orthodontics and Dentofacial Orthopedics)"
        )
        self.assertTrue(title.startswith("How far is the root apex"), title)

    def test_한글_단행본은_역순으로_보지_않는다(self):
        title, _ = build_all.parse_citation(
            "혈액투석 매뉴얼 (The Essentials of Clinical Dialysis, Springer)"
        )
        self.assertNotEqual(title, "The Essentials of Clinical Dialysis, Springer")


class 정정_철회_공지_거부(unittest.TestCase):
    """정정·철회 공지는 원논문 제목을 그대로 품고 있어 부분 일치로 통과해 버린다.
    실제로 원논문 대신 이 레코드가 수집된 사례가 3건 있었다."""

    def test_erratum_레코드는_원논문_인용문에_붙지_않는다(self):
        cited = ("Attitudes of the general public, cancer patients, family caregivers, and "
                 "physicians toward advanced care planning: A nationwide survey before the "
                 "enforcement of the life-sustaining treatment decision-making act")
        erratum = ("Erratum to Attitudes of the General Public, Cancer Patients, Family "
                   "Caregivers, and Physicians Toward Advance Care Planning: A Nationwide Survey "
                   "Before the Enforcement of the Life-Sustaining Treatment Decision-Making Act "
                   "[Journal of Pain and Symptom Management 57 (2019) 774-782].")
        self.assertFalse(build_all.titles_match(cited, erratum))
        # 원논문은 그대로 통과해야 한다
        self.assertTrue(build_all.titles_match(cited, cited + "."))

    def test_corrigendum과_retraction도_거부한다(self):
        cited = ("Prognosis and Clinical Characteristics of Patients with Pancreatic Ductal "
                 "Adenocarcinoma Diagnosed by Endoscopic Ultrasonography but Indeterminate on "
                 "Computed Tomography")
        self.assertFalse(build_all.titles_match(cited, "Corrigendum: " + cited + "."))
        self.assertFalse(build_all.titles_match(cited, "Retraction Note to: " + cited + "."))

    def test_회신과_논평은_거부하지_않는다(self):
        # 교수 본인이 저자일 수 있는 발행 유형이다 (김순철 교수 PMID 31327177)
        cited = ("Is Propofol Good Choice for Procedural Sedation? Evaluation of Propofol in "
                 "Comparison with Other General Anesthetics for Surgery in Children Younger than 3 Years")
        self.assertTrue(build_all.titles_match(cited, "Letter to the Editor: " + cited + "."))


class 제목_대조(unittest.TestCase):
    """titles_match()의 완화·엄격 규칙이 의도대로 동작하는지 확인한다."""

    def test_표기_차이는_유사도로_구제한다(self):
        # 실제 사례: 이창섭 교수 PMID 37792838 (인용문 제목이 논문 제목의 축약형)
        self.assertTrue(
            build_all.titles_match(
                "Malaria-induced splenic infarction",
                "Falciparum Malaria-Induced Splenic Infarction.",
                "Am J Trop Med Hyg",
            )
        )

    def test_학술지명이_붙어_있어도_통과한다(self):
        # 실제 사례: 김소은 교수 PMID 33000095 (학술지명을 못 떼어낸 인용문)
        self.assertTrue(
            build_all.titles_match(
                "Young girl with chest pain, Journal of the American College of "
                "Emergency Physicians Open (JACEP Open)",
                "Young girl with chest pain.",
            )
        )

    def test_인용문이_두_문장이면_문장_단위로도_대조한다(self):
        # 실제 사례: 김순철 교수 PMID 31001938 (인용문 앞에 코멘터리 제목이 붙어 있다)
        self.assertTrue(
            build_all.titles_match(
                "Is Propofol Good Choice for Procedural Sedation? Evaluation of Propofol "
                "in Comparison with Other General Anesthetics for Surgery in Children "
                "Younger than 3 Years",
                "Evaluation of Propofol in Comparison with Other General Anesthetics for "
                "Surgery in Children Younger than 3 Years: a Systematic Review and "
                "Meta-analysis.",
            )
        )

    def test_짧은_조각은_부분_일치만으로는_통과하지_못한다(self):
        # 학술지명 외에도, 흔한 짧은 문구가 남의 논문 제목에 포함되는 경우를 막는다
        self.assertFalse(
            build_all.titles_match(
                "Pediatr Dent",
                "Re: A comparison of pulpal response to freeze-dried bone, "
                "calcium-hydroxide, and zinc oxide-eugenol. Pediatr Dent 1996.",
            )
        )
        self.assertFalse(
            build_all.titles_match(
                "Ann Lab Med", "Reply to the Letter by Bennett JM, Ann Lab Med 2015;35:542-3."
            )
        )

    def test_전혀_다른_논문은_거부한다(self):
        self.assertFalse(
            build_all.titles_match(
                "Non-glucose risk factors in the pathogenesis of diabetic peripheral neuropathy",
                "Vaseline gauze packing for the treatment of acute hemorrhagic rectal ulcer: "
                "Two case reports.",
            )
        )

    def test_빈_값은_거부한다(self):
        self.assertFalse(build_all.titles_match("", "무언가"))
        self.assertFalse(build_all.titles_match("무언가", ""))


class 수동_제외_대장(unittest.TestCase):
    """data/input/manual_exclusions.json — 사람이 전건 대조로 확정한 오귀속 10건.

    산출물에서 직접 지우면 다음 전체 실행에서 되살아나므로 설정 파일에 남긴다.
    아래 10건은 2026-08-21에 원문 인용문과 하나씩 대조해 확정했다.
    """

    # (교수, PMID) — 이 조합은 수집되면 안 된다
    EXCLUDED = [
        ("박진", "40703982"),     # 인용문은 옴 진료지침 Part 1인데 Part 2 논문이 매칭됨
        ("박성희", "9108896"),    # 한글 논문에 약 이름만 겹치는 영문 리뷰 "Donepezil."
        ("김정기", "10226779"),   # 한글 논문에 용어만 겹치는 "Insulin-like growth factor."
        ("이재홍", "38824187"),   # 인용문 J Periodontal & Implant Sci ↔ 레코드 Scientific Reports
        ("양연미", "28215262"),   # 인용문 J Korean Acad Pediatr Dent 2019 ↔ 레코드 Sleep Med 2017
        ("김선준", "9128291"),    # 인용문 J Korean Pediatr Soc 2000 ↔ 레코드 Pediatr Res 1997
        ("김진규", "30628130"),   # 인용문 Perinatology ↔ 레코드 J Paediatr Child Health
        ("서봉직", "26436043"),   # 인용문 J Oral Med Pain 2016 ↔ 레코드 JCDR 2015
        ("김정기", "11606960"),   # 인용문 "in Dry State"(2010) ↔ 레코드 AJODO 2001
        ("전영미", "11606960"),   # (같은 논문, 다른 교수)
    ]

    @classmethod
    def setUpClass(cls):
        cls.table = build_all.load_manual_exclusions()

    def test_열건이_모두_대장에_있다(self):
        for professor, pmid in self.EXCLUDED:
            self.assertTrue(
                build_all.manual_exclusion_reason(self.table, professor, pmid),
                f"{professor} PMID {pmid}가 제외 대장에 없다",
            )

    def test_보류건은_제외하지_않는다(self):
        # 박진 40704002 — 옴 진료지침 Part 1. 2026-08-21 PubMed 저자 목록으로 확인했다:
        # "Park J (Jin), Dept. of Dermatology, Jeonbuk National University Medical School"가
        # 제1저자다. 본인 논문이므로 제외 대장에 들어가면 안 된다.
        self.assertIsNone(build_all.manual_exclusion_reason(self.table, "박진", "40704002"))

    def test_제외는_해당_교수에게만_적용된다(self):
        # 같은 PMID가 다른 교수에게는 정상일 수 있다
        self.assertIsNone(build_all.manual_exclusion_reason(self.table, "홍길동", "11606960"))

    def test_모든_항목에_근거가_있다(self):
        for pmid, entry in self.table.items():
            self.assertTrue(entry["reason"].strip(), f"PMID {pmid}에 근거(reason)가 없다")

    def test_근거_없는_항목은_무시한다(self):
        # load_manual_exclusions는 reason이 빈 항목을 버린다 — 왜 뺐는지 모르는 제외는 두지 않는다
        self.assertNotIn("99999999", self.table)


class 학술지_연도_대조(unittest.TestCase):
    """review.journalMismatch를 만드는 규칙. **채택을 막지 않는다** — 정밀도가 37%라서다.

    아래 '오탐' 사례들은 규칙에 걸리지만 실제로는 정상 논문이다.
    이 규칙을 자동 거부로 바꾸면 이 논문들이 사라진다는 것을 고정해 둔다.
    """

    def test_약어와_전체명을_같은_학술지로_본다(self):
        for cited, record in [
            ("J Korean Med Sci", "Journal of Korean medical science"),
            ("J Clin Neurol", "Journal of clinical neurology (Seoul, Korea)"),
            ("Int J Infect Dis", "International journal of infectious diseases"),
            ("Ann Lab Med", "Annals of laboratory medicine"),
            ("Restor Dent Endod", "Restorative dentistry & endodontics"),
            ("Eye (Lond)", "Eye (London, England)"),
            ("JCN", "Journal of clinical neurology (Seoul, Korea)"),      # 머리글자 약어
            ("JDigDis", "Journal of digestive diseases"),                 # 붙여 쓴 약어
            ("Tumor Biol", "Tumour biology"),                             # 미국/영국 철자
            ("Brain Rresearch", "Brain research"),                        # 원문 오타
        ]:
            self.assertTrue(build_all.journals_match(cited, record), f"{cited} ↔ {record}")

    def test_명백히_다른_학술지는_구분한다(self):
        self.assertFalse(build_all.journals_match("J Korean Acad Pediatr Dent", "Sleep medicine"))
        self.assertFalse(build_all.journals_match("Perinatology", "Journal of paediatrics and child health"))

    def test_학술지명이_아닌_값은_대조하지_않는다(self):
        # 파서가 학술지 자리에 서지 조각을 넣는 경우가 있다 — 이런 값으로 대조하면 무조건 불일치다
        for junk in ("2016 May", "Epub2016Jan8", "Suppl 1", "2025[epub]", "2023 Jan 16(1)", ""):
            self.assertFalse(build_all.is_plausible_journal(junk), junk)
        for real in ("Perinatology", "J Korean Med Sci", "Sleep medicine"):
            self.assertTrue(build_all.is_plausible_journal(real), real)

    def test_연도는_제목이나_쪽번호가_아니라_서지_꼬리에서_읽는다(self):
        # 제목 안의 연도 범위를 읽으면 안 된다
        self.assertEqual(
            build_all.citation_year(
                "Effect of direct-acting antivirals on disease burden of hepatitis C virus "
                "infection in South Korea in 2007-2021: a nationwide study. EClinicalMedicine. 2024;70:102524."
            ),
            2024,
        )
        # 쪽번호를 연도로 읽으면 안 된다 — 여기서 2038은 쪽번호다
        self.assertEqual(
            build_all.citation_year(
                "Prognostic value of preoperative CA19-9 in pancreatic cancer. "
                "Cancers. 2021;13(15):2038."
            ),
            2021,
        )

    def test_오탐_사례는_규칙에_걸리지만_제거_대상이_아니다(self):
        # 학술지 개명 — "Korean J Lab Med"는 2012년에 "Ann Lab Med"로 이름이 바뀌었다
        self.assertFalse(build_all.journals_match("Korean J Lab Med", "Annals of laboratory medicine"))
        # 걸리더라도 채택을 막지 않는다: 이 PMID들은 산출물에 남아 있어야 한다
        state = json.loads(
            (Path(build_all.__file__).resolve().parents[2]
             / "data/output/professors_papers.json").read_text(encoding="utf-8")
        )
        for professor, pmid in [("조용곤", "22779071"), ("석현", "24471041"),
                                ("류한욱", "38660095"), ("정환정", "36732943")]:
            papers = state["professors"].get(professor, {}).get("allPapers") or []
            self.assertIn(pmid, [p["pmid"] for p in papers], f"{professor} {pmid}가 사라졌다")


if __name__ == "__main__":
    unittest.main()
