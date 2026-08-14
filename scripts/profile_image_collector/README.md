# 프로필 사진 URL 수집기

전북대병원 홈페이지의 교수 프로필 페이지(243명)에서 **프로필 사진의 URL만** 모아
`data/output/profile_images.json` 파일로 저장하는 스크립트입니다.

- 이미지 파일을 다운로드하지 않습니다. URL 문자열만 수집합니다.
- 사진이 없거나 기본(placeholder) 이미지인 교수는 `null`로 기록합니다.
  (데이터 계약 `docs/data-contract-v6.3.md` 0장 원칙 2 — 값이 없으면 지어내지 않는다)

## 준비물

- Python 3.8 이상 (팀 개발 환경 기준. 별도 설치 없이 표준 라이브러리만 사용하므로 `pip install` 불필요)
- 입력 파일: `data/input/professor_pages.json` (repo에 이미 포함되어 있음)

## 실행 방법

repo 최상위 폴더에서:

```bash
python scripts/profile_image_collector/fetch_image_urls.py
```

- 다른 폴더에서 실행해도 경로를 스크립트 위치 기준으로 계산하므로 정상 동작합니다.
- 전체 243명 실행 시 호출 사이 0.5초씩 기다리므로 **약 5~10분** 걸립니다.

### 테스트로 조금만 돌려보기 (LIMIT)

`fetch_image_urls.py` 파일 상단의 `LIMIT` 값을 바꾸면 앞에서부터 N명만 처리합니다.

```python
LIMIT = None   # 전체 243명 (기본값)
LIMIT = 10     # 앞 10명만 — 동작 확인용
```

확인이 끝나면 다시 `None`으로 되돌려 주세요.

## 실행 중 화면

- 10명 단위로 진행 상황이 출력됩니다.
- 요청이 실패한 교수는 1회 재시도 후 `null` 처리하고 콘솔에 기록합니다. 전체 실행은 멈추지 않습니다.
- 끝나면 통계가 출력됩니다: `완료: 성공 N / 사진 없음 N / 요청 실패 N`

## 출력 파일

`data/output/profile_images.json` (이 폴더는 `.gitignore` 대상이라 git에 올라가지 않습니다)

```json
{
  "collectedAt": "2026-08-15",
  "source": "https://www.jbuh.co.kr 교수 프로필 페이지",
  "images": {
    "유희철": "https://www.jbuh.co.kr/thumbnail/mdclStf/MS_202506271000151320.PNG",
    "양재도": null
  }
}
```

- `collectedAt` — 실행한 날짜 (`YYYY-MM-DD`)
- `images` — 교수 한글명 → 사진 절대 URL. 사진이 없으면 `null`

## 사진을 어떻게 찾나요?

프로필 페이지의 정적 HTML 안에 교수 사진이 아래 형태로 들어 있습니다 (2026-08-15 사전 확인).

```html
<img src="/thumbnail/mdclStf/MS_2025....PNG" alt="유희철 대표 이미지">
```

같은 페이지에 placeholder(`no-img.png`) · 타 교수 배너 · 사이트 로고 이미지가 섞여 있어서,
**src 경로에 `/thumbnail/mdclStf/`가 있고 + alt에 교수명이 포함된 이미지**만 본인 사진으로 인정합니다.
둘 중 하나라도 어긋나면 안전하게 `null`로 둡니다.

## 참고 사항

- 프로필 사진은 **비영리·내부 테스트 용도** 사용으로 팀장 승인을 받았습니다 (2026-08 작업지시서).
- 수집 결과를 서비스 데이터에 반영할 때는 `profileImageUrl` 필드 규칙(`docs/data-contract-v6.3.md` 1-1장)을 따릅니다.
