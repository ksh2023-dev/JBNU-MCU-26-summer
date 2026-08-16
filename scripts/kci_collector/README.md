# KCI 논문 수집기 (`fetch_kci.py`)

KCI(한국학술지인용색인) Open API로 **국내 학술지 논문**을 교수별로 수집해
`data/output/kci_papers.json`으로 저장하는 스크립트입니다.

PubMed 수집(3단계)에서 국내 논문은 `pmid`가 없어 담지 못했습니다 —
계약 v6.4에서 `kciId`가 도입되어(원칙 1: **pmid 또는 kciId 필수**) 이 단계로 보완합니다.

- 대상: `data/output/professors.json`에 수록된 교수 전원 (계약 0-2 = 의대 공식 명단 기준, 182명)
- 수집 항목: `kciId` · 제목(원어/영문) · 학술지 · 연도 · `doi` · `url` · **KCI 피인용수** · 초록(원어/영문)
- 부수 수집: 본인 저자 항목의 **영문명 · ORCID** (영문명 미확정 교수 보완, 동명이인 검증용)
- 산출물의 키는 **교수 id**(`P-012`)입니다. 이름을 키로 쓰면 동명이인이 한 칸에 뭉개지므로,
  레코드 안에 `name`을 함께 두어 사람이 읽을 수 있게 합니다.
- **이 단계는 KCI 산출물 생성까지입니다.** PubMed 논문과의 병합은 다음(조립) 단계이며,
  여기서는 `duplicateOf`에 "같은 논문으로 보이는 pmid"만 표시합니다.

> ⚠️ **인증키 발급 대기 중(2026-08-16)** — 구현과 오프라인 단위 테스트까지만 마쳤고
> **실제 응답으로는 아직 검증하지 못했습니다.** 키가 생기면 아래 "실제 응답에서 확인할 것"을
> 먼저 대조해 주세요.

## 원칙 (계약 0-1)

| 원칙 | 이 스크립트에서 |
| --- | --- |
| 1. pmid 또는 kciId 필수 | `article-id`가 없는 응답 항목은 버립니다 |
| 2. 없는 값은 지어내지 않는다 | 피인용수·초록·DOI가 없으면 `0`/`""`이 아니라 `null`. **소속이 전북대로 확인되지 않은 논문은 채택하지 않고** `review.affiliationUnmatched`에 남깁니다 |
| 2. 불확실하면 합치지 않는다 | 중복 판별이 애매하면 별개로 두고 `review.duplicateAmbiguous`에 남깁니다 |
| 4. 수집 기준일 기록 | `collectedAt`에 실행일을 담고, 제목·학술지·연도는 KCI 원본 그대로 둡니다 |

### 본인 논문 판별 — 왜 소속을 보는가

KCI 검색은 **이름(`author`)** 으로 합니다. 이름만으로는 동명이인·타 기관 저자의 논문이 섞여 오므로,
응답 안에서 **교수와 같은 이름인 저자의 소속에 `전북대`가 들어 있을 때만** 채택합니다.
PubMed 수집에서 오귀속을 막았던 기준과 같습니다 — 근거가 없으면 넣지 않습니다.

| 상황 | 처리 | `review.affiliationUnmatched`의 `reason` |
| --- | --- | --- |
| 같은 이름 저자의 소속에 `전북대` 포함 | **채택** | — |
| 같은 이름 저자의 소속이 다른 기관 | 제외 | `타 기관` |
| 같은 이름 저자의 소속이 비어 있음 | 제외 | `소속 정보 없음` |
| 응답에 같은 이름의 저자가 없음 | 제외 | `동명 저자 없음` |

### 동명이인 — 자동 배정하지 않는다

대상 명단에 **같은 이름의 교수가 둘 이상이면**(현재 `이창훈` P-176/P-177) 검색 결과를
**어느 쪽에도 배정하지 않습니다.** KCI 검색은 이름 기준이고 둘 다 전북대 소속이라
소속으로도 가를 수 없기 때문입니다 — 근거가 없으면 채우지 않습니다(원칙 2).

- 같은 이름의 교수 **전원**이 `papers: []` 인 레코드를 받습니다
  (`stats.homonymUnassigned`에 보류한 편수가 남아, "결과 없음"과 구분됩니다)
- `authorInfo`도 비웁니다 — 영문명·ORCID 역시 누구 것인지 알 수 없습니다
- 후보 논문은 **각 논문의 저자 ORCID·소속·영문명과 함께** `review.homonymUnassigned`에 남깁니다.
  사람이 이걸 보고 수동 검수 대장에서 배정합니다 (ORCID가 사실상 유일한 판별 단서입니다)
- 검색은 이름당 한 번만 합니다 (같은 이름이면 결과가 같으므로)

## 실행 방법 (저장소 루트에서, 가상환경 활성화 후)

### 1. 인증키 발급 → `.env` 설정

1. `open.kci.go.kr` → Open API 신청 (활용 목적·**서비스 IP** 기재) → 승인 후 인증키 확인
2. 저장소 루트 `.env`에 한 줄 추가 (양식: `.env.example`)

   ```
   KCI_API_KEY=발급받은키
   ```

- 키가 없으면 스크립트가 위 절차를 안내하고 **바로 멈춥니다**(exit 1). 호출은 하지 않습니다.
- **인증키는 신청 시 등록한 IP에서만 동작합니다.** Vercel·GitHub Actions처럼 IP가 유동인 곳에서는
  쓸 수 없고, 고정 IP 수집 서버에서 실행해야 합니다 (계약 v6.4 7장).

### 2. LIMIT 검증 — 전체 실행 전에

`fetch_kci.py` 상단의 실행 옵션을 바꿉니다.

```python
LIMIT = 2       # 대상 명단 앞 2명만 처리 (None이면 전체 182명)
```

```bash
python scripts/kci_collector/fetch_kci.py
```

첫 실행에서는 **결과 한 건을 눈으로 확인**해 주세요 — 아래 "실제 응답에서 확인할 것" 표가 검수 항목입니다.

### 3. 전체 실행

`LIMIT = None`으로 되돌리고 같은 명령을 실행합니다.
교수 1명당 최소 0.5초(+ 페이지 수만큼)를 쉬므로 182명이면 대략 2~5분 걸립니다.
결과는 `data/output/kci_papers.json` (`data/output/`은 커밋 제외 폴더입니다).

### 4. 재개(resume) · 다시 수집

- 교수 1명이 끝날 때마다 즉시 저장합니다. 중간에 끊기면 **다시 실행**하면 됩니다 —
  이미 저장된 교수는 건너뜁니다.
- 통신 실패로 `review.fetchFailed`에 기록된 교수는 **저장되지 않으므로** 재실행 시 자동으로 다시 시도됩니다.
- 처음부터 다시 모으려면 `FORCE_REFRESH = True`로 두고 실행합니다.

### 5. 단위 테스트 (키 없이 가능)

```bash
python -m unittest discover -s scripts/kci_collector -v
```

표본 XML은 활용가이드의 필드 이름을 본떠 만든 것이며 **실제 응답이 아닙니다.**
통과해도 실제 응답 파싱이 보장되지는 않습니다 — 구조가 그 모양일 때의 동작까지만 고정합니다.

## 산출물 — `data/output/kci_papers.json`

```json
{
  "collectedAt": "2026-08-16",
  "professors": {
    "P-012": {
      "name": "황주희",
      "papers": [
        { "kciId": "ART002712345", "title": "국내 심부전 …", "titleEn": "Prognostic Factors …",
          "journal": "대한내과학회지", "year": 2021, "doi": "10.3904/…", "url": "https://www.kci.go.kr/…",
          "citedByCountKci": 4, "abstract": "…", "abstractEn": "…", "duplicateOf": "38123456" }
      ],
      "authorInfo": {
        "nameEn": "Joo-Hee Hwang", "orcid": "0000-0002-…",
        "nameEnVariants": ["Joo-Hee Hwang", "Joo Hee Hwang"],
        "orcidCandidates": [{ "value": "0000-0002-…", "count": 7 }]
      },
      "stats": { "found": 12, "adopted": 9, "affiliationUnmatched": 3, "homonymUnassigned": 0 }
    },
    "P-176": {
      "name": "이창훈",
      "papers": [],
      "authorInfo": { "nameEn": null, "orcid": null, "nameEnVariants": [], "orcidCandidates": [] },
      "stats": { "found": 8, "adopted": 0, "affiliationUnmatched": 2, "homonymUnassigned": 6 }
    }
  },
  "review": { "affiliationUnmatched": [], "homonymUnassigned": [], "duplicateAmbiguous": [],
              "fetchFailed": [], "noResult": [] }
}
```

| 칸 | 뜻 |
| --- | --- |
| 최상위 키 | **교수 id** (`professors.json`의 `id`). 레코드 안의 `name`은 사람이 읽기 위한 것 |
| `papers[].duplicateOf` | 같은 논문으로 판별된 PubMed `pmid` (아니면 `null`). **합치지는 않습니다** |
| `authorInfo.nameEn` / `orcid` | 대표값(관측된 값 중 최빈값). 하나도 없으면 `null` |
| `authorInfo.nameEnVariants` | 관측된 영문명 표기 **전부** (많이 나온 순) — 표기 흔들림을 사람이 볼 수 있게 |
| `authorInfo.orcidCandidates` | `{value, count}` 목록. **2개 이상이면 동명이인이 섞였다는 신호**입니다 |
| `stats.found` / `adopted` / `affiliationUnmatched` | 검색 결과 / 채택 / 소속 미확인 제외 |
| `stats.homonymUnassigned` | 동명이인이라 배정을 보류한 편수. `papers`가 빈 이유가 "결과 없음"인지 "배정 보류"인지 구분합니다 |

### `review` 읽는 법

모든 기록에 `professor`(이름)가 있고, 단독 교수의 기록에는 `professorId`도 함께 들어갑니다
(동명이인은 어느 id인지 정할 수 없어 `professorId`가 `null`입니다).

| 목록 | 모양 | 뜻·할 일 |
| --- | --- | --- |
| `affiliationUnmatched` | `{professorId, professor, kciId, title, reason, affiliations}` | 소속이 확인 안 돼 뺀 논문. `affiliations`는 응답의 소속 표기 원본 — 본인 논문인데 빠졌다면 소속 표기를 확인 |
| `homonymUnassigned` | `{professor, professorIds, reason, candidates[]}` | **동명이인이라 배정하지 않은 후보 논문.** `candidates[]`는 논문 정보 + `author{nameEn, orcid, affiliation}` — 사람이 ORCID로 확인해 수동 배정 |
| `duplicateAmbiguous` | `{professorId, professor, kciId, title, year, reason, candidatePmids}` | 같은 논문일 수 있으나 확정 못 한 건. 사람이 확인해 조립 단계에 반영 |
| `fetchFailed` | `{professorId, professor, stage, error}` | 통신 실패. 다시 실행하면 자동 재시도 |
| `noResult` | `{professorId, professor}` | KCI 검색 결과가 0건. 국내 논문이 없거나 이름 검색이 안 걸린 것 |

### 중복 판별 규칙 (계약 v6.4 1-2)

같은 교수의 PubMed 논문(`professors_papers.json`의 `allPapers`)과만 대조합니다 —
다른 교수의 논문과 합치면 오귀속이 됩니다.

1. **DOI 일치** (`https://doi.org/`·대소문자 차이는 무시) → `duplicateOf`에 pmid
2. DOI가 없으면 **정규화 제목 + 연도 일치** (영문 제목 우선 — PubMed 제목이 영문이므로)
3. 후보가 여럿 / 제목은 같은데 연도가 다름 / 제목이 닮기만 함 → **애매**로 두고 `review`에 기록

> ⚠️ 현재 `professors_papers.json`에는 **DOI 칸이 없습니다**(PubMed 3단계가 수집하지 않음).
> 그래서 실제로는 1번 규칙이 동작하지 않고 **2번(제목+연도)만으로 판별**됩니다 — 계약 1-2 ②로
> 정상 동작이며, 이 스크립트는 현재 상태 그대로 둡니다(실행 시작 시 로그로 알려 줍니다).
> **PubMed 수집에 `doi`가 추가되면 1순위 규칙(DOI 일치)이 켜져 판별 정확도가 올라갑니다.**
> 이 코드는 `doi` 칸이 생기면 수정 없이 그대로 1번 규칙을 쓰며, PubMed 쪽 보완은 **별도 PR**입니다.

## 실제 응답에서 확인할 것 (키 발급 후 첫 실행)

파싱은 태그 위치를 고정하지 않고 **이름으로 자손을 찾는 방식**이라 중첩 구조가 달라도 견디지만,
**태그·속성 이름 자체가 다르면 값이 조용히 `null`이 됩니다.** 아래를 눈으로 대조해 주세요.

| 확인 항목 | 다르면 고칠 곳 |
| --- | --- |
| `kciId`가 `ART…`로 채워지는가 (`articleInfo@article-id`) | `parse_article` — 없으면 그 논문을 통째로 버리므로 가장 중요 |
| 저자 소속이 `이름(소속기관)` 형태로 오는가 | `parse_author`(괄호·속성·하위 요소 순으로 찾음) |
| 소속이 **영문**(`Jeonbuk/Chonbuk National University`)으로만 오는 논문이 있는가 | `AFFILIATION_KEYWORDS`에 영문 표기 추가 |
| 피인용수가 `citation-count@kci`인가, 요소 텍스트인가 | 둘 다 지원 — 이름이 다르면 `parse_article` 수정 |
| 초록·제목의 `lang` 값이 `original`/`english`인가 | `_LANG_ALIASES` |
| 결과 0건 응답과 오류 응답의 모양 | `parse_response`(태그에 `error`가 있어야 오류로 인식) |
| 전체 건수(`total`) 태그가 있는가 | 없으면 "받은 건수 < 100"으로 마지막 쪽을 판단합니다 (동작에는 지장 없음) |
| `displayCount=100` · `page` 파라미터 이름이 맞는가 | `fetch_page` |

## 자주 생기는 문제

| 증상 | 원인과 해결 |
| --- | --- |
| `KCI_API_KEY를 찾지 못했습니다` | `.env`에 키가 없음 → 위 1번 절차 |
| `KCI가 오류 응답을 돌려줬습니다: …` 후 중단 | 인증키·IP·파라미터 문제. 모든 교수에서 같은 오류가 나므로 여기서 멈춥니다. 키를 고치고 다시 실행하면 완료분은 건너뜁니다 |
| 채택 0편인데 검색 결과는 많음 | 소속 표기가 예상과 다름 → `review.affiliationUnmatched`의 `affiliations`를 확인 후 `AFFILIATION_KEYWORDS` 조정 |
| `… 20쪽까지만 수집했습니다` | 한 이름의 결과가 2,000건 초과 → `MAX_PAGES` 조정 검토 |
| 영문명·ORCID가 여러 개라는 경고 | 동명이인이 섞였을 가능성 → `authorInfo.orcidCandidates`와 해당 교수 논문 검수 |
| `papers`가 비었는데 `stats.found`는 큼 | `stats.homonymUnassigned`가 0보다 크면 **동명이인 배정 보류**, 0이면 소속 불일치로 전부 제외된 것 |

## 알려진 한계

- **동명이인**: KCI 검색은 이름 기준이라 같은 이름의 두 교수를 자동으로 가를 수 없습니다.
  그래서 **자동 배정을 하지 않고** 후보를 `review.homonymUnassigned`로 넘깁니다(위 "동명이인" 절).
  배정은 사람이 ORCID·소속을 보고 수동 검수 대장에서 결정합니다 —
  **그 전까지 해당 교수들의 `papers`는 빈 배열로 남습니다.**
- `affiliation` 검색 파라미터는 이름·표기 규칙을 확인하지 못해 기본값 `USE_AFFILIATION_PARAM = False`입니다.
  본인 판별은 응답 안의 소속으로 하므로 꺼 두어도 오귀속은 생기지 않습니다.
- KCI 검색은 **저자 이름 기준**이라 3단계의 `review.notFound`(963건, 제목 기준 실패)와 1:1로 대응하지 않습니다.
  겹치는 논문은 `duplicateOf`로, 새로 들어오는 논문은 그대로 채택됩니다.
