/**
 * professors.js — 교수 카드 mock(가짜) 데이터
 *
 * ============================================================
 *  ※ 주의: 아래 데이터는 전부 UI/기능 테스트용 가상 데이터입니다.
 *     - 실존 인물이 아니며, 전북대학교 의과대학 교수 정보가 아닙니다.
 *     - 이름은 실제 사람으로 오해되지 않도록 '가상교수A' ~ '가상교수G' 형식만 사용합니다.
 *       (사람 이름처럼 보이는 값을 절대 넣지 않습니다)
 *     - 소속/전문분야/키워드도 화면 확인을 위해 임의로 만든 예시입니다.
 *     - 실제 데이터는 백엔드 API가 완성되면 그대로 교체됩니다.
 *     - 실제 교수 이름, 이메일, 논문 정보는 절대 이 파일에 넣지 않습니다.
 * ============================================================
 *
 * 데이터 모양은 「데이터 계약 문서 v4」의 1-1. 교수 카드와 동일합니다.
 * 배열의 원소 1개 = 교수 카드 1장.
 *
 * 필드 설명 (계약 문서에 정의된 8개 필드만 사용):
 *   id              내부 식별자. 화면에는 표시하지 않음
 *   profileImageUrl 프로필 사진 주소. 없으면 null → 화면은 이니셜 아바타로 대체
 *   professorType   교수 구분. 기초의학 | 임상의학 | 의학교육학 | 인문사회의학 4종류만 사용
 *   department      소속교실 또는 진료과
 *   specialties     전문 분야 "배열". 1개여도 배열, 없으면 빈 배열 []
 *   keywords        키워드 "배열" 전체. 카드에는 프론트가 앞 3~4개만 보여줌
 *   matchScore      0~1 사이 실수. 관련도순 정렬과 minScore 컷에 사용
 *
 * 계약에 따라 email / isFavorite / favoriteDate 는 카드에 넣지 않습니다.
 *   - email 은 교수 상세에서만 표시
 *   - 찜 여부는 id 를 localStorage 와 대조해 프론트가 직접 판단
 */

/** 이 파일이 가짜 데이터임을 코드에서 확인할 수 있게 하는 표시 */
export const IS_MOCK_DATA = true

/**
 * 데이터 수집 기준일 (계약 문서의 collectedAt).
 * 실제 백엔드는 수집 날짜를 응답에 담아 보내지만,
 * mock 단계에서는 고정값을 사용합니다.
 */
export const MOCK_COLLECTED_AT = '2026-08-05'

/**
 * 가상 교수 카드 목록 (7명)
 *
 * 화면에서 확인해야 하는 여러 경우를 일부러 섞어 두었습니다.
 *   - professorType 4종류가 모두 포함
 *   - profileImageUrl 이 null 인 경우 5명 / 값이 있는 경우 2명
 *     (값이 있는 주소는 example.com 이라 실제로는 불러와지지 않습니다.
 *      → 이미지 로드 실패 시 이니셜 아바타로 되돌리는 처리도 테스트할 수 있습니다)
 *   - specialties 가 0개 / 1개 / 2개 / 3개 / 4개인 경우
 *   - keywords 가 0개 / 2개 / 3개 / 4개 / 6개 / 7개인 경우
 *   - matchScore 가 전부 다르고, 0.3 미만인 경우도 1명 포함
 *     (minScore 로 걸러지는지 확인용)
 */
export const professors = [
  {
    id: 'P-001',
    name: '가상교수A',
    profileImageUrl: null,
    professorType: '임상의학',
    department: '순환기내과',
    specialties: ['심장영상', '심부전'],
    keywords: [
      'cardiac imaging',
      '심장 MRI',
      'biomarker',
      'heart failure',
      'echocardiography',
      '예후 예측',
    ],
    matchScore: 0.92,
  },
  {
    id: 'P-002',
    name: '가상교수B',
    // 사진 주소가 있는 경우 (실제로 열리지 않는 예시용 주소)
    profileImageUrl: 'https://example.com/mock/professor-002.jpg',
    professorType: '기초의학',
    department: '해부학교실',
    // 전문 분야가 1개여도 반드시 배열로 담습니다
    specialties: ['신경해부학'],
    keywords: ['neuroanatomy', '뇌지도', '연결체'],
    matchScore: 0.85,
  },
  {
    id: 'P-003',
    name: '가상교수C',
    profileImageUrl: null,
    professorType: '의학교육학',
    department: '의학교육학교실',
    specialties: ['의학교육평가', '시뮬레이션 교육', '교육과정 개발'],
    keywords: ['OSCE', '의학교육', '시뮬레이션', '역량기반교육'],
    matchScore: 0.78,
  },
  {
    id: 'P-004',
    name: '가상교수D',
    profileImageUrl: null,
    professorType: '인문사회의학',
    department: '의료인문학교실',
    // 전문 분야 정보가 없는 경우 → null 이 아니라 빈 배열
    specialties: [],
    keywords: ['의료윤리', '환자 자율성'],
    matchScore: 0.66,
  },
  {
    id: 'P-005',
    name: '가상교수E',
    profileImageUrl: 'https://example.com/mock/professor-005.jpg',
    professorType: '임상의학',
    department: '소아청소년과',
    specialties: ['소아감염', '백신'],
    // 키워드가 없는 경우 → 빈 배열
    keywords: [],
    matchScore: 0.54,
  },
  {
    id: 'P-006',
    name: '가상교수F',
    profileImageUrl: null,
    professorType: '기초의학',
    department: '생화학교실',
    specialties: ['단백질체학', '대사질환', '분자생물학', '암 대사'],
    // 키워드가 많은 경우 → 카드에서 앞 3~4개만 자르는 처리를 확인할 수 있습니다
    keywords: [
      'proteomics',
      '대사체',
      '암 대사',
      'mass spectrometry',
      '단백질 상호작용',
      '질량분석',
      '생물정보학',
    ],
    matchScore: 0.41,
  },
  {
    id: 'P-007',
    name: '가상교수G',
    profileImageUrl: null,
    professorType: '인문사회의학',
    department: '예방의학교실',
    specialties: ['보건정책'],
    keywords: ['health policy', '보건통계', '코호트 연구', '의료정책'],
    // 기본 minScore(0.3)보다 낮아서 검색 결과에서 제외되는지 확인하는 데이터
    matchScore: 0.28,
  },
]

/**
 * 우수 교수(API ③) 화면을 그려보기 위한 mock fixture 목록입니다.
 *
 * ※ 선정 기준이 아니라, 그냥 손으로 골라 적어 둔 id 목록입니다.
 *   - 실제 우수 교수 선정 기준(최근 수상 등)은 아직 정해지지 않았습니다.
 *     (데이터 계약 문서 5장 7번 — 백엔드·데이터팀 확정 대기)
 *   - 그래서 matchScore 같은 값으로 "계산"하지 않습니다.
 *     계산해서 뽑으면 마치 그것이 확정된 선정 기준인 것처럼 보이기 때문입니다.
 *   - 실제 기준이 정해지면 이 목록은 백엔드 응답으로 통째로 대체됩니다.
 */
export const MOCK_FEATURED_PROFESSOR_IDS = ['P-003', 'P-005', 'P-002', 'P-007']

export default professors
