# scripts/assembler — 최종 조립기 (D단계)

수집 산출물 6종을 병합해 백엔드가 읽는 **`data/output/professors.json`** 을 만든다.
출력 모양의 기준은 `data/sample/professors.sample.json`(= 데이터 계약 v6.3)이다.

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

`professors.json`에는 **샘플과 같은 칸만** 담는다. 영문명·초록 등 계약 밖 데이터는
전부 `professors_extra.json`으로 나가므로 백엔드 검증과 충돌하지 않는다.

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
| 1 | `python scripts/pubmed_collector/build_all.py` | `professors_papers.json` (입력: `data/input/professor_paper_lists.json` — 커밋되어 있음) |
| 2 | `python scripts/profile_image_collector/fetch_image_urls.py` | `profile_images.json` (입력: `data/input/professor_pages.json` — 커밋되어 있음) |
| 3 | `python scripts/assembler/build_professors.py` | `professors.json` · `professors_extra.json` |

> ⚠️ **현재 저장소만으로는 재료 3종을 다시 만들 수 없다.** `roster_crawled.json`(명단 크롤러),
> `specialties.json`(전문진료분야 수집), `professors_enriched_meta.json`(C단계 보강)을 만든 스크립트는
> 아직 커밋되어 있지 않다. 이 세 파일은 (a)처럼 담당자에게 받아 `data/output/`에 놓아야 3번이 돌아간다.
> (해당 스크립트를 저장소에 올리면 (b)만으로 전체 재생성이 가능해진다.)

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
| `MERGE_CROSS_APPOINTMENTS` | `True` | 두 교실에 걸친 사람을 한 명으로 합침 |
| `DEPARTMENT_INCLUDE_DIVISION` | `True` | 소속에 분과 표기 |
| `DEPARTMENT_JOIN_CROSS_APPOINTMENTS` | `True` | 교차 겸직은 두 교실을 `CROSS_APPOINTMENT_SEPARATOR`(` · `)로 이어 표기 |
| `FETCH_HOSPITAL_DEPARTMENT` | `True` | 병원 전용 교수의 진료과를 병원 프로필에서 조회 |
| `USE_DEPARTMENT_CACHE` | `True` | 조회 결과 캐시 사용 |
| `HOSPITAL_ONLY_PROFESSOR_TYPE` | `"임상의학"` | 의대 명단에 없는 병원 교수의 교수 구분(추정) |
| `PAPERS_LIMIT` | `3` | 대표 논문 수 |
