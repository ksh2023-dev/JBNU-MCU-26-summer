# scripts/assembler — 최종 조립기 (D단계)

수집 산출물 6종을 병합해 백엔드가 읽는 **`data/output/professors.json`** 을 만든다.
출력 모양의 기준은 **데이터 계약 v6.4**다 (`docs/data-contract-v6.4.md`).

```bash
python scripts/assembler/build_professors.py
```

- 외부 라이브러리 없이 표준 라이브러리만 쓴다 (설치할 것 없음).
- 첫 실행은 병원 프로필 67건 조회(0.5초 간격) 때문에 1~2분 걸리고, 이후에는 캐시를 써서 몇 초면 끝난다.
- 정합 검사에서 위반이 하나라도 나오면 종료 코드 1로 끝난다.

## 입출력

| 구분 | 파일 |
| --- | --- |
| 입력 | `data/output/roster_crawled.json` · `data/input/professor_pages.json` · `data/output/profile_images.json` · `data/output/specialties.json` · `data/output/professors_papers.json` · `data/output/professors_enriched_meta.json` |
| 관리 파일 (커밋) | `data/input/manual_overrides.json` (수동 검수 대장) · `data/input/id_registry.json` (id 대장) |
| 출력 (커밋 안 함) | `data/output/professors.json` · `data/output/professors_extra.json` · `data/output/_cache_hospital_departments.json` |

`professors.json`에는 **계약에 있는 칸만** 담는다. 영문명·초록 등 계약 밖 데이터는
전부 `professors_extra.json`으로 나가므로 백엔드 검증과 충돌하지 않는다.

## 산출물 스키마 (v6.4)

```jsonc
{
  "collectedAt": "2026-08-16",          // 원본 데이터의 수집 기준일 (원칙 4)
  "professors": [
    {
      "id": "P-042",                    // 한 번 부여되면 불변 (프론트 찜이 id로 저장된다)
      "name": "김연동",
      "profileImageUrl": null,
      "professorType": "임상의학",        // 기초의학 | 임상의학 | 의학교육학 | 인문사회의학
      "department": "마취통증의학교실",    // 분과·겸직이 병기될 수 있다
      "specialties": [],                // 없으면 []
      "keywords": [],                   // 영문 MeSH — v6.4에서 화면 미표시(검색 매칭 전용)
      "email": null,
      "homepageUrl": null,
      "latestPaper": {                  // 백엔드 내부 필드(API ③ 정렬용) — 계약 응답에는 안 나간다
        "pmid": "37507223", "publishedAt": "2024-05-07"
      },
      "papers": [                       // 최신 1편 + 인용 상위 2편 = 최대 3편, 없으면 []
        { "title": "...", "journal": "...", "year": 2024,
          "pmid": "37507223", "kciId": null }
      ]
    }
  ]
}
```

**v6.3 → v6.4에서 바뀐 것**

| 변경 | 조립기 처리 |
| --- | --- |
| `labName` 필드 삭제 | 출력하지 않는다 (`EMIT_LABNAME = False`). 수집 가능한 출처가 없어 전원 `null`이었고 화면에서도 제거됐다 |
| `papers[].kciId` 추가 | 전 논문에 칸을 넣는다. **KCI 수집 전이라 값은 전부 `null`** — 프론트가 링크 분기(pmid → PubMed / kciId → KCI)를 미리 구현할 수 있게 하기 위한 것이다 |
| 원칙 1 확장 (`pmid` **또는** `kciId` 필수) | 둘 다 없는 논문은 넣지 않고, 정합 검사에서 0건인지 확인한다 |
| 대상 범위 확정 (0-2장) | 의대 공식 명단 기준 — 아래 "알아 둘 규칙" 참고 |

**`latestPaper`(내부 필드)는 계약에 스키마가 없다.** v6.4는 "내부 선정용이며 응답에 포함되지 않는다"고만
적고 칸을 정의하지 않는다. 그래서 조립기는 기존 모양(`pmid` + `publishedAt`)을 유지하고,
`kciId` 칸을 임의로 만들지 않는다. 최신 논문이 KCI 전용이면 `EMIT_LATEST_PAPER_KCI_ID`가 켜져 있을 때만
`{pmid: null, kciId, publishedAt}`으로 내보내고, 꺼져 있으면 `review.latestPaperKciOnly`에 기록한다
(조용히 빠지지 않게 하기 위한 것 — featured 후보에서 제외된다).

> ⚠️ **백엔드는 아직 v6.3 스키마다** (`backend/app/schemas.py`). 이 산출물로 기동은 되지만
> 응답이 계약과 어긋난다 — 상세 응답에 `labName: null`이 그대로 붙고(`ProfessorDetail.lab_name`이 남아 있음),
> `papers[].kciId`는 `Paper` 모델에 없어 응답에서 빠진다. 백엔드 담당자의 스키마 수정이 필요하다.
> 임시로 `labName`이 꼭 필요하면 `EMIT_LABNAME = True`로 되살릴 수 있다.
> `data/sample/professors.sample.json`도 아직 v6.3(labName 있음·kciId 없음)이라,
> 조립기는 샘플에서 칸 목록을 읽은 뒤 위 개정분을 코드에서 반영한다.

## 산출물 취급

**`data/output/professors.json`은 저장소에 커밋하지 않는다.** 교수 이메일 등 개인정보가 들어 있어서다.
`data/output/`은 `.gitignore`에 등록되어 있어 실수로 `git add` 해도 올라가지 않는다
(그래도 커밋 전 `git status`로 한 번 확인할 것). 공개 저장소 게시 여부는 팀 결정 대기 중이다.
같은 이유로 `professors_extra.json`(초록·근거·전화·직위 포함)도 커밋 대상이 아니다.

그래서 **파일이 필요한 팀원은 아래 둘 중 하나로 구한다.**

**(a) 담당자에게 파일을 받는다** — 저장소가 아닌 별도 채널(팀 메신저·드라이브 등)로 전달받아
`data/output/professors.json`에 놓는다. 받은 파일도 커밋하지 않는다.

**(b) 파이프라인을 직접 돌려 재생성한다**

준비물: Python 3.10+, 그리고 저장소 루트의 `.env`에 OpenAlex API 키 한 줄.
`.env.example`을 복사해 `.env`를 만들고 `OPENALEX_API_KEY=발급받은키`를 채운다.
(키 발급 방법과 주의사항은 [scripts/pubmed_collector/README.md](../pubmed_collector/README.md) 참고.
`.env`도 `.gitignore` 대상이다.)

| 순서 | 실행 | 만들어지는 재료 |
| --- | --- | --- |
| 1 | `python scripts/roster_crawler/crawl_roster.py` | `roster_crawled.json` (main에 있음 — 이 브랜치에서는 `git merge origin/main` 후 사용) |
| 2 | `python scripts/pubmed_collector/build_all.py` | `professors_papers.json` (입력: `data/input/professor_paper_lists.json` — 커밋되어 있음) |
| 3 | `python scripts/profile_image_collector/fetch_image_urls.py` | `profile_images.json` (입력: `data/input/professor_pages.json` — 커밋되어 있음) |
| 4 | `python scripts/assembler/build_professors.py` | `professors.json` · `professors_extra.json` |

> ⚠️ **재료 2종은 아직 저장소만으로 만들 수 없다.** `specialties.json`(전문진료분야 수집)과
> `professors_enriched_meta.json`(C단계 MeSH·영문명 보강)을 만든 스크립트가 커밋되어 있지 않다.
> 이 두 파일은 (a)처럼 담당자에게 받아 `data/output/`에 놓아야 마지막 단계가 돌아간다.
> (두 스크립트를 저장소에 올리면 (b)만으로 전체 재생성이 가능해진다.)

**백엔드 연결은 `DATA_FILE` 환경변수 하나로 한다.** 백엔드 코드는 고치지 않는다 —
`backend/app/config.py`가 `DATA_FILE`을 읽고, 값이 없으면 샘플 데이터를 쓴다.

```powershell
# PowerShell — backend 폴더에서
$env:DATA_FILE="C:\...\JBNU-MCU-26-summer\data\output\professors.json"; uvicorn app.main:app
```

```bash
# macOS · Linux
DATA_FILE=<repo>/data/output/professors.json uvicorn app.main:app
```

## 알아 둘 규칙

- **id는 영원히 불변.** 프론트 찜이 localStorage에 id로 저장되므로, 재실행할 때는 id 대장을
  먼저 읽어 기존 id를 재사용하고 새 교수에게만 다음 번호를 준다. 자세한 규칙은 `data/input/README.md`.
- **소속이 바뀐 교수의 id 승계는 사람이 확인했을 때만 한다.** 이름이 같고 소속만 다르면 같은 사람이
  옮긴 것처럼 보이지만, 퇴직자가 빠지고 같은 이름의 신규 교수가 들어온 경우도 똑같이 보인다.
  그 상태로 id를 물려주면 **예전 찜이 다른 사람을 가리킨다.** 그래서 수동 검수 대장에 그 교수의
  `department` 확정 항목(또는 `field: "idInheritance"` 승계 허용 항목)이 있을 때만 승계하고,
  없으면 새 id를 주고 `review.idInheritanceHeld`에 "승계 보류(사람 확인 필요)"로 남긴다.
- **대상은 의대 공식 명단 기준이다 (2026-08-16 회의 결정).** 치과 계열 29명에 더해, 의대 명단에 없고
  병원 명단에만 있는 교수 67명도 제외한다(`INCLUDE_HOSPITAL_ONLY = False`). 이들은 의대 홈페이지에
  없어 교수 구분의 근거가 없는데 계약상 `professorType`은 값이 필수라, 수록하려면 추정값을 넣어야 했다.
  제외 명단은 삭제하지 않고 `review.excludedHospitalOnly`에 남긴다.
  - `True`로 되돌리면 그 67명이 다시 들어오고, 추정 사실이 `professors_extra.json`의
    `professorTypeInferred: true`와 `review.professorTypeInferred`(전원 목록)에 기록된다.
    이때도 계약 파일에는 계약 밖 칸을 만들지 않는다.
  - 범위에서 빠진 교수를 가리키는 수동 검수 항목은 위반이 아니라
    `review.manualOverridesOutOfScope`로 남는다. 대장 항목은 지우지 않는다.
- **수동 검수 대장이 자동 수집을 이긴다.** 병합이 모두 끝난 뒤 마지막에 적용한다.
- **동명이인은 이름으로 수집된 자료를 물려받지 않는다.** 사진·전문분야·키워드·논문은 전부
  '병원 명단의 이름'을 키로 모은 것이라, 병원 명단에 없는 동명이인에게는 붙이지 않는다.
- **소속은 명단 원문 그대로** 쓴다. 내과·외과는 분과를 함께 적어 `내과학교실(소화기)` 형태가 되고
  (`DEPARTMENT_INCLUDE_DIVISION`), 두 교실에 걸친 교차 겸직 교수는 두 교실을 ` · `로 이어
  `예방의학교실 · 가정의학교실`처럼 적는다(`DEPARTMENT_JOIN_CROSS_APPOINTMENTS`). 한쪽만 적으면
  나머지 교실 기준의 검색·목록에서 빠지기 때문이다. 앞에 오는 것이 전공과 맞물리는 대표 교실이며,
  교수 구분(`professorType`)은 그 대표 교실을 따른다.
- 값을 못 구하면 `null`로 두고 `professors_extra.json`의 `review`에 남긴다. 지어내지 않는다.
  단 `department`는 계약상 값이 있어야 하는 칸이라, 끝내 못 구한 교수는 계약 파일에서 빼고
  `review.droppedNoDepartment`에 기록한다.

## 바꿀 만한 설정 (스크립트 맨 위 상수)

| 상수 | 기본값 | 뜻 |
| --- | --- | --- |
| `EXCLUDE_DENTAL` | `True` | 치과 계열 제외 (제외 명단은 extra에 남긴다) |
| `INCLUDE_HOSPITAL_ONLY` | `False` | 의대 명단에 없는 병원 전용 교수 67명 포함 여부 — **2026-08-16 회의 결정: 의대 공식 명단 기준**이라 제외한다. 이들만 교수 구분을 추정해야 했다. 제외 명단은 `review.excludedHospitalOnly`에 남는다 |
| `MERGE_CROSS_APPOINTMENTS` | `True` | 두 교실에 걸친 사람을 한 명으로 합침 |
| `DEPARTMENT_INCLUDE_DIVISION` | `True` | 소속에 분과 표기 |
| `DEPARTMENT_JOIN_CROSS_APPOINTMENTS` | `True` | 교차 겸직은 두 교실을 `CROSS_APPOINTMENT_SEPARATOR`(` · `)로 이어 표기 |
| `FETCH_HOSPITAL_DEPARTMENT` | `True` | 병원 전용 교수의 진료과를 병원 프로필에서 조회 |
| `USE_DEPARTMENT_CACHE` | `True` | 조회 결과 캐시 사용 |
| `HOSPITAL_ONLY_PROFESSOR_TYPE` | `"임상의학"` | 의대 명단에 없는 병원 교수의 교수 구분(추정) |
| `PAPERS_LIMIT` | `3` | 대표 논문 수 |
| `EMIT_LATEST_PAPER_KCI_ID` | `False` | 최신 논문이 KCI 전용일 때 `latestPaper`를 `kciId`로 내보낼지. 계약 v6.4에 **latestPaper 스키마가 없고** 백엔드 `LatestPaper.pmid`가 필수라 기본값 `False` — 대신 해당 교수를 `review.latestPaperKciOnly`에 남긴다 |
| `EMIT_LABNAME` | `False` | `labName` 칸 출력 여부. v6.4에서 계약 필드 자체가 삭제돼 기본값 `False`. 백엔드가 v6.4 반영 전이라 임시로 필요하면 `True` (값은 항상 `null`) |
