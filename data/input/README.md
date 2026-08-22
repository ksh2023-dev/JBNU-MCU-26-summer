# data/input

입력 데이터 파일의 출처 기록.

- `professor_pages.json`: 전북대병원 홈페이지 교수 프로필 링크 모음. 방민영 수집, 2026-08-14 팀 공유. 원본 파일명 `papers.json`.
- `professor_paper_lists.json`: 교수별 논문 인용문 목록. 교수 본인 프로필 페이지에서 수집했다.
  3단계 PubMed 수집기(`scripts/pubmed_collector/build_all.py`)의 입력이며, **이 파이프라인에서
  "이 논문이 이 교수 것"임을 보증하는 유일한 기준점**이다. 원본이므로 고치지 않는다.

아래 세 파일은 수집물이 아니라 **사람이 관리하는 대장(臺帳)** 이다. 자동 생성물(`data/output/`)과 달리
저장소에 커밋해 함께 관리한다. `manual_overrides.json`·`id_registry.json`은 D단계 조립기
(`scripts/assembler/build_professors.py`)가, `manual_exclusions.json`은 3단계 PubMed 수집기
(`scripts/pubmed_collector/build_all.py`)가 읽는다.

---

## `manual_overrides.json` — 수동 검수 대장

사람이 눈으로 확인해 **확정한 사실**만 적는다. 조립기는 자동 수집·병합을 모두 끝낸 **마지막 단계**에서
이 파일을 적용한다. 즉 여기 적힌 값이 자동 수집값을 항상 덮어쓴다.

```jsonc
{
  "updatedAt": "2026-08-16",
  "overrides": [
    {
      "name": "김연동",                 // 대상 교수 이름 (필수)
      "department": null,              // 대상 지정용. null이면 그 이름의 교수 전원
      "field": "nameEn",               // 고칠 칸 이름
      "value": "Yeon-Dong Kim",        // 확정된 값
      "reason": "...",                 // 왜 이렇게 확정했는지 (근거)
      "confirmedBy": "이지훈",          // 확인한 사람
      "date": "2026-08-16"             // 확인한 날짜
    }
  ]
}
```

- `department` — **동명이인 대상 지정용**. 조립기가 만든 최종 `department` 값과 정확히 같아야 한다
  (예: `"내과학교실(소화기)"`). `null`이면 그 이름을 가진 교수 전원이 대상이며,
  대상이 2명 이상이면 조립기가 적용하지 않고 `review.manualOverridesUnmatched`에 남긴다.
- `field` — 계약 필드(`name` `department` `professorType` `email` `homepageUrl` `labName`
  `profileImageUrl` `specialties` `keywords`)와 계약 밖 내부 필드(`nameEn`) 모두 지정할 수 있다.
  계약 밖 필드는 `professors_extra.json`에만 반영된다.
- `field: "distinctPerson"` — 값을 고치는 게 아니라 **"이 사람은 동명이인과 별개 인물"이라는 확인 사실**을
  적는 특수 항목이다. 조립기는 이 항목을 적용 대신 **검증**에 쓴다.
  대상이 정확히 1명 잡히고 같은 이름의 다른 교수와 id가 다르면 통과, 아니면 `review`에 실패로 남긴다.
- `field: "idInheritance"` (`value: true`) — **"소속이 바뀌었지만 같은 사람이 맞다"는 확인 사실.**
  이 항목이나 위의 `department` 확정 항목이 있어야만 조립기가 기존 id를 승계한다 (아래 id 대장 참고).
- **동명이인이 있는 이름에 `department` 지정 없이 항목을 넣으면 적용하지 않는다.** 정합 검사에서
  "대상이 모호하다"로 잡히며, 값이 실제로 반영됐는지도 매 실행마다 검증한다.
- 적용 결과는 매 실행마다 `professors_extra.json`의 `review.manualOverridesApplied` /
  `review.manualOverridesUnmatched`에 기록된다. 조용히 무시되는 항목은 없다.

## `manual_exclusions.json` — 오귀속 매칭 제외 대장

**전건 대조로 "이 원본 인용문에서 이 PMID를 해당 교수에게 귀속하면 안 된다"고 확인한 매칭**만
적는다. 3단계 수집기가 채택 단계에서 이 파일을 읽어, 적힌 (교수, PMID) 조합을 결과에 넣지 않는다.

**"그 교수의 논문이 아니다"는 뜻이 아니다** — 잘못된 것은 *매칭*이지 논문의 저자 관계가 아니다.
실제로 박진 교수 / PMID 40703982(옴 진료지침 Part 2)는 **본인이 제1저자임이 확인된 논문**이지만,
원본 인용문이 Part 1을 가리키는데 검색이 Part 2를 물어 온 것이라 제외했다. 인용문 목록을 신원
보증 기준점으로 삼는 이 파이프라인에서는, 인용문이 가리키지 않는 논문은 넣지 않는다.

같은 이유로, 공저 논문이라 **같은 PMID가 여러 교수에게 정상 귀속되는 것은 막지 않는다**
(그래서 `professors`로 대상 교수를 지목한다 — 아래 참고).

### 왜 산출물을 직접 고치지 않고 이 파일을 쓰는가

`data/output/professors_papers.json`에서 그 논문을 손으로 지워도 **다음 전체 실행에서 그대로
되살아난다.** 수집기는 매번 인용문을 다시 검색해 채우기 때문이다. 제외를 영구히 남기려면
입력 쪽에 있어야 한다. `manual_overrides.json`이 조립기에 대해 하는 일을, 이 파일이 수집기에
대해 한다.

```jsonc
{
  "updatedAt": "2026-08-21",
  "exclusions": {
    "26436043": {                      // PMID (필수, 키)
      "professors": ["서봉직"],         // 제외할 교수 이름 목록 (필수)
      "reason": "인용문은 …(J Oral Med Pain 2016)인데 매칭된 논문은 …(JCDR 2015)로 학술지·연도가 다르다",
      "verifiedAt": "2026-08-21"       // 사람이 확인한 날짜
    }
  }
}
```

- `professors` — **제외는 여기 적힌 교수에게만 적용된다.** 같은 PMID가 다른 교수에게는 정상일 수
  있기 때문이다(공저 논문). 빈 목록 `[]`이면 모든 교수에서 제외한다.
  한 논문이 여러 교수에게 잘못 붙었으면 이름을 나란히 적는다 — 예: `["김정기", "전영미"]`.
- `reason` — **필수.** 왜 오귀속인지 적는다. 인용문이 밝힌 학술지·연도와 레코드의 그것을 함께
  적어 두면 나중에 판단을 되짚기 쉽다. **`reason`이 비어 있는 항목은 수집기가 적용하지 않고
  건너뛰며 콘솔에 경고를 찍는다** — 왜 뺐는지 모르는 제외는 두지 않는다.
- 적용 결과는 매 실행마다 `professors_papers.json`의 `review.manualExcluded`에 제목·근거와 함께
  남는다. 조용히 사라지는 논문은 없다.

### 항목을 추가하기 전에

**반드시 `professor_paper_lists.json`의 원본 인용문과 대조하고 나서 넣는다.** 제목이 비슷하다는
이유만으로 넣으면 안 된다. 실제로 확인해야 할 것:

1. 인용문이 밝힌 **학술지명·연도**가 수집된 레코드와 같은가
2. 제목이 같은 논문을 가리키는가 (부제 생략·원문 오타·미국식/영국식 철자는 흔하다)
3. 미심쩍으면 PubMed efetch로 **저자 목록**을 받아 그 교수가 저자인지 확인한다
   (2026-08-21에 박진 교수 옴 진료지침 Part 1을 이 방법으로 "본인 논문"으로 확정해 제외하지 않았다)

`review.journalMismatch`(학술지·연도가 어긋난 논문 목록)가 좋은 출발점이지만, **그 목록을 그대로
옮겨 적으면 안 된다.** 학술지 개명(`Korean J Lab Med` → `Ann Lab Med`)·자매지·원문 오타·파싱 실패
때문에 정상 논문이 상당수 섞여 있다. 2026-08-21 측정에서 그 목록의 정밀도는 37%였다.

## `id_registry.json` — 교수 id 대장

교수 `id`는 **한 번 부여되면 영원히 바뀌지 않아야 한다.** 프론트의 찜 목록이 localStorage에
id만 저장하기 때문에, id가 흔들리면 사용자의 찜이 엉뚱한 교수를 가리키거나 사라진다.

```jsonc
{
  "updatedAt": "2026-08-16",
  "nextNumber": 250,                   // 다음에 새로 부여할 번호
  "entries": [
    {
      "id": "P-001",
      "name": "강경표",
      "department": "내과학교실(신장) · 가정의학교실",  // 현재 소속 (바뀌면 갱신된다)
      "firstAssignedAt": "2026-08-16",               // 최초 부여일 — 이후 절대 바뀌지 않는다
      "departmentHistory": [                         // 소속이 바뀐 이력
        { "department": "내과학교실(신장)", "until": "2026-08-16" }
      ]
    }
  ]
}
```

- **키는 `name` + `department`.** 최초 조립 때 가나다순(동명이인은 department순)으로 `P-001`부터 부여했다.
- 재실행 시 조립기는 이 파일을 **먼저 읽어** 기존 id를 재사용하고, 새 교수에게만 `nextNumber`를 이어 준다.
- 소속이 바뀐 경우의 id 승계는 **사람이 확인했을 때만** 한다. 같은 이름의 대장 항목이 하나뿐이고,
  `manual_overrides.json`에 그 교수의 `department` 확정 항목(값이 새 소속과 같음)이나
  `field: "idInheritance"` 항목이 있을 때만 id를 그대로 쓰고 이전 소속을 `departmentHistory`에 남긴다.
  - **근거가 없으면 승계하지 않고 새 번호를 준다.** `review.idInheritanceHeld`에
    "동일 이름·다른 소속 — 승계 보류(사람 확인 필요)"로 남는다.
    이름만 같은 퇴직자와 신규 교수가 교체된 경우에 id를 물려주면 **예전 찜이 다른 사람을 가리키기** 때문이다.
    같은 사람이 맞다고 확인되면 대장에 항목을 추가하고 다시 실행하면 된다.
  - 같은 이름이 여러 명(동명이인)이면 department가 정확히 맞는 항목만 재사용하고,
    못 찾으면 새 번호를 부여한 뒤 `review.idAmbiguous`에 남긴다.
- **항목을 지우지 않는다.** 퇴직·이직 등으로 명단에서 빠진 교수의 항목도 그대로 둔다.
  번호를 재사용하면 예전 찜이 다른 교수를 가리키게 되기 때문이다.
- 이 파일은 조립기가 자동으로 갱신한다. 손으로 고치지 않는다.
