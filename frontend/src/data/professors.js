/**
 * ⚠️ 테스트용 가짜 데이터 (mock)
 *
 * 실제로 존재하는 교수·논문이 아닙니다. 화면을 먼저 만들어 보기 위한 예시 값이며,
 * 이름은 평범한 예시 이름, pmid는 "00000000" 같은 자리표시자입니다.
 * 백엔드가 완성되면 이 파일은 쓰지 않고 api/professorApi.js 안에서 fetch로 교체합니다.
 *
 * 필드 이름은 "데이터 계약 문서 v4"를 그대로 따릅니다.
 *  - 1-1 교수 카드: id, name, profileImageUrl, professorType, department,
 *                  specialties(배열), keywords(배열), matchScore
 *  - 1-2 교수 상세: 위 항목 + labName, email, homepageUrl, papers
 *
 * 값이 없는 필드는 지어내지 않고 null(논문은 빈 배열 [])로 둡니다. (원칙 2)
 */

// 데이터 수집 기준일 (계약 원칙 4). 응답의 collectedAt 으로 내보낸다.
export const COLLECTED_AT = '2026-08-05'

// professorType 에 들어갈 수 있는 값 4가지 (필터 만들 때 사용)
export const PROFESSOR_TYPES = [
  '기초의학',
  '임상의학',
  '의학교육학',
  '인문사회의학',
]

const professors = [
  {
    id: 'P-001',
    name: '홍길동',
    profileImageUrl: null, // 저작권 문제로 사진은 없을 가능성이 높다 → 이니셜 아바타로 대체
    professorType: '임상의학',
    department: '순환기내과',
    specialties: ['심장영상', '심부전'], // 값이 하나여도 반드시 배열
    keywords: ['cardiac imaging', '심장 MRI', 'biomarker', '심근증'],
    labName: null, // 값 없음 → 화면에는 "정보 없음"
    email: 'example1@example.com',
    homepageUrl: null, // 값 없음 → 링크 숨김
    papers: [
      {
        title: '(예시) 심장 MRI를 이용한 예후 예측 연구',
        journal: '(예시 학술지)',
        year: 2022,
        pmid: '00000000', // 자리표시자. 실제 pmid 아님
      },
      {
        title: '(예시) 심부전 환자의 바이오마커 분석',
        journal: '(예시 학술지)',
        year: 2021,
        pmid: '00000001',
      },
    ],
    matchScore: 0.87, // 0~1 사이 실수. 관련도순 정렬에 사용
  },
  {
    id: 'P-002',
    name: '김철수',
    profileImageUrl: null,
    professorType: '기초의학',
    department: '생화학교실',
    specialties: ['단백질구조'],
    keywords: ['protein structure', '효소', 'X-ray crystallography'],
    labName: '(예시) 구조생물학 연구실',
    email: 'example2@example.com',
    homepageUrl: 'https://example.com/lab2',
    papers: [
      {
        title: '(예시) 효소 단백질의 구조 분석',
        journal: '(예시 학술지)',
        year: 2023,
        pmid: '00000002',
      },
    ],
    matchScore: 0.72,
  },
  {
    id: 'P-003',
    name: '이영희',
    profileImageUrl: null,
    professorType: '임상의학',
    department: '영상의학과',
    specialties: ['복부영상', '중재시술'],
    keywords: ['abdominal imaging', 'CT', '중재적 시술'],
    labName: null,
    email: null, // 값 없음 → 화면에는 "정보 없음"
    homepageUrl: null,
    papers: [], // 논문 없음 → "등록된 대표 논문 없음"
    matchScore: 0.55,
  },
  {
    id: 'P-004',
    name: '박민준',
    profileImageUrl: null,
    professorType: '의학교육학',
    department: '의학교육학교실',
    specialties: ['교육과정 개발'],
    keywords: ['medical education', '평가', '시뮬레이션 교육'],
    labName: '(예시) 의학교육 연구실',
    email: 'example4@example.com',
    homepageUrl: null,
    papers: [
      {
        title: '(예시) 시뮬레이션 기반 임상술기 교육의 효과',
        journal: '(예시 학술지)',
        year: 2024,
        pmid: '00000003',
      },
    ],
    matchScore: 0.41,
  },
  {
    id: 'P-005',
    name: '최수빈',
    profileImageUrl: null,
    professorType: '인문사회의학',
    department: '의료윤리학교실',
    specialties: ['의료윤리', '보건정책'],
    keywords: ['medical ethics', '연구윤리', 'health policy'],
    labName: null,
    email: 'example5@example.com',
    homepageUrl: 'https://example.com/lab5',
    papers: [
      {
        title: '(예시) 임상연구에서의 사전동의 절차 검토',
        journal: '(예시 학술지)',
        year: 2020,
        pmid: '00000004',
      },
    ],
    matchScore: 0.28, // 기본 minScore(0.3) 미만 → 검색 결과에서 잘리는지 확인용
  },
]

export default professors
