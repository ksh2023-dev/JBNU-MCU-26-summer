# 키워드 한글 번역기 (`keyword_translator/`) — 파이프라인 8단계

백엔드 검색은 문자 부분일치라서 한글 질의("심장")가 영문 MeSH 키워드("cardiac imaging")와
만나지 못한다. 이 단계는 5단계가 모은 **영문 키워드에 한글 표기를 붙여** 한글 검색이
잡히게 한다. 번역은 **KOSTOM(보건의료용어표준) 기반 1:1 사전 조회**다 — 생성형 번역이
아니므로 지어낼 수 없고(계약 원칙 2), 사전에 없는 용어는 미번역 목록에 그대로 남긴다.

KCI 논문(6·7단계)은 키워드가 한·영 쌍으로 오므로 번역이 필요 없다. 대신 그 쌍을
**번역 메모리에 수확**해, 사전이 못 잡는 연구 용어를 회차가 돌수록 채워 간다.

## 파일 구성

| 파일 | 역할 |
| --- | --- |
| `translate_keywords.py` | 파이프라인 단계 본체. run_all.py가 8단계로 호출한다 |
| `build_dictionary.py` | KOSTOM 엑셀 → `dictionary.json.gz` 재생성 도구 (KOSTOM 새 버전 때만) |
| `dictionary.json.gz` | 추출된 영→한 사전 (155,875 용어 · 커밋 대상) |
| `translation_memory.json` | KCI 수확분 + 수동 교정 (커밋 대상 · 사전보다 **우선**) |

## 동작 방식

1. `data/output/professors_enriched_meta.json`(5단계 산출물)에서 키 이름에
   `mesh`/`keyword`가 들어간 문자열 배열을 전부 모은다 (5단계 모양 변화에 견디게).
2. `data/output/kci_papers.json`이 있으면 7단계가 논문마다 붙인
   `keywords: {"ko": [...], "en": [...]}`에서 한·영 쌍을 수확해 `translation_memory.json`에
   더한다 (없으면 그냥 넘어간다). ko/en은 대응이 보장되지 않으므로 **두 목록 길이가 같은
   논문만** 같은 순번끼리 쌍으로 삼고, 길이가 다르면 그 논문은 건너뛴다.
   `keywordsRaw`(쪼개기 전 원본)는 수확하지 않는다.
3. 용어마다 **메모리 → 사전** 순서로 찾는다. 표기 차이는 두 가지만 흡수한다:
   - MeSH 도치 표기: `Hypertension, Portal` → `portal hypertension`
   - 복수형: `Biomarkers` → `biomarker`
4. 결과를 `data/output/keywords_ko.json`으로 저장한다.

```json
{
  "collectedAt": "2026-08-21",
  "stats": { "terms": 12, "translated": 9, "untranslated": 3 },
  "translations": {
    "Heart Failure": ["심장기능상실", "심장부전", "심부전"],
    "Hypertension, Portal": ["문맥의 고혈압질환", "문맥 고혈압"]
  },
  "untranslated": ["Gastrointestinal Microbiome"]
}
```

- `translations` 값은 **한글 변형 배열**이다. 영문 동음이의어가 진짜 동의어 여러 개로
  번역되는 경우(stroke = 뇌졸중/발작/박동)를 위해 전부 보관한다 — 검색 재현율에는
  변형이 많을수록 좋다. **첫 번째가 대표 표기**(표준코드가 가장 많이 달린 KOSTOM 행 기준)다.
- 조립기(9단계)가 이 파일을 읽어 교수마다 **`keywordsKo` 필드**에 한글 변형을 채운다
  (2026-08-22 통합 완료 — `assembler/build_professors.py`의 `EMIT_KEYWORDS_KO`).
  영문 원본 `keywords`는 대체하지 않는다. 회의 결정(2026-08-21)대로 화면에는 영문만
  표시된다: 백엔드가 응답 `keywords`에 영문만 담고 `keywordsKo`는 검색 매칭에만 쓴다.

## 미번역 용어를 채우는 법 (사람 검수 루프)

`keywords_ko.json`의 `untranslated` 목록을 보고, 확실한 것만
`translation_memory.json`의 `terms`에 추가한다 (영문 키는 소문자).

```json
{ "terms": { "gastrointestinal microbiome": "장내 미생물총" } }
```

메모리는 사전보다 우선하므로 잘못 뽑힌 대표 표기를 교정하는 데에도 쓸 수 있다.
다음 회차부터 자동 반영된다.

## 사전 재생성 (KOSTOM 새 버전을 받았을 때만)

1. [공공데이터포털](https://www.data.go.kr) 등에서 보건의료용어표준 엑셀을 받아
   `data/KOSTOM/`에 둔다 (24MB라 git에는 올리지 않는다 — `.gitignore` 대상).
2. `python scripts/keyword_translator/build_dictionary.py` 실행 →
   `dictionary.json.gz`가 갱신된다 (표준 라이브러리만 사용, 몇 분 소요). 커밋한다.
3. 파일명이 바뀌면 `build_dictionary.py` 상단 `SOURCE_PATH`를 맞춘다.

## 자주 생기는 문제

| 증상 | 원인과 해결 |
| --- | --- |
| `[중단] 사전이 없습니다` | `dictionary.json.gz`가 없음 → 위 "사전 재생성" 절차 실행 |
| `[중단] 입력 파일이 없습니다` | 5단계를 먼저 실행해야 함 (run_all.py는 자동으로 건너뜀 처리) |
| 적중률이 낮다 | 정상 — 연구 용어는 KOSTOM에 없는 것이 많다. KCI 수확이 쌓이면 오르고, 급하면 미번역 목록을 검수해 메모리에 채운다 |
| KCI 수확 0개 | `kci_papers.json`이 없거나(첫 회차), 7단계(KCI 키워드 수집)가 아직 안 돌았거나, ko/en 길이가 같은 논문이 없음 — 오류가 아니다 |
