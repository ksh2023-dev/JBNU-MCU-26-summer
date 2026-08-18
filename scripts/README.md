# 데이터 수집·조립 파이프라인 (`scripts/`)

교수 데이터는 **서비스 런타임이 아니라 수집 서버에서 미리 만든다.** 수집 서버가 주기적으로
이 폴더의 스크립트들을 돌려 `data/output/professors.json`을 만들고, 백엔드(FastAPI)는 완성된
그 파일만 읽는다. PubMed·OpenAlex·KCI에 장애가 나도 검색 기능은 영향을 받지 않는다
(`docs/data-contract-v6.4.md` 7장).

`run_all.py`는 그 전 단계를 **순서대로 1회** 실행하는 오케스트레이터다.
반복은 cron이 담당하고, 이 스크립트는 한 묶음을 실행하고 끝난다.

## 1. 전체 순서

```
 수집 (외부에서 가져오기)                                   조립 (하나로 합치기)
 ───────────────────────────────────────────────────────   ─────────────────────────
 [1] 교수 명단 크롤    ──▶ roster_crawled.json          ─┐
 [2] 프로필 사진 URL   ──▶ profile_images.json          ─┤
 [3] 전문진료분야      ──▶ specialties.json             ─┼──▶ [7] 최종 조립
 [4] 논문(PubMed)      ──▶ professors_papers.json       ─┤          │
 [5] MeSH·영문명·이메일 ─▶ professors_enriched_meta.json ─┤          ▼
 [6] KCI 논문          ──▶ kci_papers.json              ─┘   professors.json
                                                             professors_extra.json
                                                                    │
                                                                    ▼
                                                        백엔드(FastAPI)가 읽어 API 제공
```

단계 사이에 순서가 중요한 곳:

- **[4] → [5]** — 5단계는 4단계 산출물 `professors_papers.json`을 입력으로 쓴다 (없으면 그냥 죽는다).
- **[1]·[2]·[3]·[4]·[5] → [7]** — 조립기는 이 다섯 산출물을 그대로 열어 합친다.
  하나라도 없으면 트레이스백을 뱉고 죽으므로, run_all.py가 미리 확인해 건너뛴다.
- **[6]은 직전 실행의 `professors.json`** 을 수집 대상 명단으로 쓴다. 즉 6단계는 이번 회차가
  아니라 **지난 회차의 조립 결과**를 기준으로 돈다 (순서가 6 → 7이므로 같은 회차에는 채워지지 않는다).

**선행 산출물이 없으면 그 단계는 `건너뜀(선행 산출물 없음)`으로 자동 제외된다** — 오류가 아니라
'아직 차례가 아닌 것'으로 본다. 산출물이 하나도 없는 새 서버의 첫 회차가 이 경우다.
단, **이번 실행의 앞 단계가 그 파일을 만들 예정이면 있는 것으로 친다.** 예를 들어
`professors_papers.json`이 아직 없어도 같은 실행에서 4단계가 돌 예정이면 5·7단계는 정상 실행된다.
어느 쪽이든 계획표(`--dry-run`)에 사유와 파일 이름이 그대로 찍히므로 실행 전에 확인할 수 있다.

> 새 서버의 첫 회차는 `--include-roster`로 돌리는 것을 권한다. 그러지 않으면 1단계 산출물
> `roster_crawled.json`이 없어 7단계(최종 조립)가 건너뛰어진다.

## 2. 단계별 스크립트

| # | 단계 | 스크립트 | 주기 | 주요 출력 |
| --- | --- | --- | --- | --- |
| 1 | 교수 명단 크롤 | `roster_crawler/crawl_roster.py` | **월 1회** (기본 제외) | `roster_crawled.json` |
| 2 | 프로필 사진 URL | `profile_image_collector/fetch_image_urls.py` | 주 1회 | `profile_images.json` |
| 3 | 전문진료분야 | `specialty_collector/fetch_specialties.py` | 주 1회 | `specialties.json` |
| 4 | 논문 수집(PubMed+OpenAlex) | `pubmed_collector/build_all.py` | 주 1회 | `professors_papers.json` |
| 5 | MeSH·영문명·이메일 보강 | `pubmed_collector/enrich_authors_mesh.py` | 주 1회 | `professors_enriched_meta.json` |
| 6 | KCI 논문 수집 | `kci_collector/fetch_kci.py` | 주 1회 (키 없으면 자동 건너뜀) | `kci_papers.json` |
| 7 | 최종 조립 | `assembler/build_professors.py` | 주 1회 | `professors.json` · `professors_extra.json` |

출력은 모두 `data/output/` 아래에 생기며, 이 폴더는 `.gitignore` 대상이다
(`professors.json`에는 이메일이 들어 있어 **공개 저장소에 커밋하지 않는다** — 계약 7장).

각 단계의 자세한 동작·검증 방법은 스크립트 폴더의 README를 본다.
**아직 다른 브랜치에 있어 이 브랜치에 없는 스크립트는 오류가 아니라 `건너뜀(missing)`으로
처리된다.** 병합되면 자동으로 실행 대상이 된다.

## 3. `run_all.py` 사용법

저장소 루트에서, 가상환경을 활성화한 뒤 실행한다.
하위 스크립트는 `run_all.py`를 실행한 파이썬(`sys.executable`)으로 호출되므로
**가상환경이 그대로 따라간다.**

```powershell
# 기본: 주 1회 묶음 (2~7단계, 명단 크롤 제외)
python scripts/run_all.py

# 월 1회: 명단 크롤까지 포함한 전체
python scripts/run_all.py --include-roster

# 무엇이 돌지 먼저 확인 (실제 실행 없음)
python scripts/run_all.py --dry-run
```

### 옵션

| 옵션 | 뜻 |
| --- | --- |
| `--include-roster` | 1단계(교수 명단 크롤)를 포함한다. 월 1회용이라 기본은 제외 |
| `--only 4,5` | 지정한 단계만 실행. `--only 1`처럼 이름을 직접 적으면 1단계도 실행된다 |
| `--skip 2,3` | 지정한 단계를 건너뛴다 (`--only`와 함께 쓸 수 없다) |
| `--dry-run` | 실제 실행 없이 계획표만 출력. 락도 잡지 않는다 |
| `--continue-on-error` | 단계가 실패해도 다음 단계를 계속 진행 (기본은 즉시 중단) |
| `--env-file PATH` | 쓸 `.env` 경로. 기본은 저장소 루트 `.env`이며, **수집 서버에서 저장소 밖의 다른 `.env`를 쓸 때** 지정한다. 여기서 읽은 값은 각 단계 프로세스의 환경변수로도 전달된다(아래 참고) |
| `--force-unlock` | 남아 있는 락 파일을 강제로 회수하고 실행. 도는 실행이 없는 것이 확실할 때만 |

### 실행 전 사전 점검

1. `OPENALEX_API_KEY`가 있는지 확인한다. **이번 실행에 그 키가 필요한 단계(현재는 4단계)가
   들어 있을 때만** 필수로 보고, 없으면 즉시 중단한다(그 단계가 반드시 실패하므로 수십 분을
   버리기 전에 멈춘다). 그 단계가 없는 실행(예: `--only 2`·`--only 5`)은 키가 없어도 진행한다.
   5단계는 확보한 PMID로 efetch만 다시 부르므로 OpenAlex 키가 필요 없다.
2. `KCI_API_KEY`가 없으면 6단계를 `건너뜀(키없음)`으로 자동 제외한다.
3. 선행 산출물이 필요한 단계(5·6·7)는 그 파일이 있는지 확인해, 없으면
   `건너뜀(선행 산출물 없음)`으로 자동 제외한다 (위 "단계 사이 순서" 참고).
4. 각 단계 스크립트가 실제로 있는지 확인해 계획표로 출력한다. 없는 스크립트는 `건너뜀(missing)`.

건너뛴 단계는 사유가 계획표와 종료 요약에 그대로 남으므로, **안 돈 단계를 성공으로 착각할 일이 없다.**

### `.env` 값이 각 단계에 전달되는 방식

`run_all.py`는 `--env-file`(기본: 루트 `.env`)을 파싱해 **각 단계 프로세스의 환경변수로 넘긴다.**
수집 스크립트들은 원래 저장소 루트 `.env`를 직접 읽기 때문에, 이렇게 넘기지 않으면
`--env-file`로 지정한 파일이 조용히 무시된다.

그래서 각 수집 스크립트의 키 읽기 함수는 **환경변수를 먼저 보고, 없을 때만 루트 `.env`를 읽는다.**

```python
api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
if not api_key and ENV_PATH.exists():
    ...  # 기존 .env 파서
```

- 단독 실행(`python scripts/.../build_all.py`) 시에는 환경변수가 없으므로 지금까지처럼 루트 `.env`를 읽는다.
- `run_all.py` 경유 시에만 지정한 파일이 적용된다. 셸에 같은 이름의 환경변수가 있어도 **파일 값이 이긴다.**
- **새로 추가하는 수집 스크립트도 이 규칙을 따라야 한다.**

### 중복 실행 방지 (락 파일)

- **위치**: `data/output/.run_all.lock` — 시작 시각과 PID가 기록된다.
- 실행 중 락이 있으면 **새 실행을 거부**한다(종료 코드 3). cron 주기보다 실행이 길어질 때
  두 프로세스가 같은 산출물을 동시에 쓰는 사고를 막기 위한 것이다.
- 락은 정상 종료·실패·Ctrl+C·종료 신호 어느 경우에도 해제된다.
- **스테일 락 자동 회수** — 강제 종료(kill -9·전원 차단)로 락만 남은 경우, 기록된 PID가 이미
  죽었으면 **경고를 남기고 자동으로 회수한 뒤 계속 진행한다.** 사람이 손댈 때까지 cron이 매 회차
  조용히 실패하는 상황을 막기 위한 것이다.
- 거부하든 회수하든 **콘솔과 로그 파일 양쪽에 락의 시작 시각·PID·경과 시간을 남긴다.**

```
기존 락 발견: .../data/output/.run_all.lock
       시작 시각 2026-08-18 19:26:11 · PID 21432 · 경과 95분 01초
[경고] 스테일 락 — PID 21432 프로세스가 이미 없습니다(강제 종료·전원 차단 추정). 자동으로 회수하고 진행합니다.
```

- PID가 **아직 살아 있으면** 거부한다. PID 기록이 없거나 손상된 락도 생사를 알 수 없으므로 거부한다
  (도는 실행을 덮치는 쪽이 훨씬 위험하다).
- 그 경우 정말 도는 실행이 없다면 `--force-unlock`으로 회수하거나 락 파일을 직접 지운다.

  ```bash
  python scripts/run_all.py --force-unlock
  ```

### 로그

- 콘솔 출력을 그대로 흘려보내면서 같은 내용을 `data/output/logs/run_YYYYMMDD_HHMMSS.log`에 남긴다
  (폴더 자동 생성, `.gitignore` 대상).
- 사전 점검 실패·락 거부도 로그로 남는다 — cron에서 원인을 찾을 수 있게.
- 단계마다 시작/종료 시각·소요 시간·종료 코드가 찍히고, 끝에 단계별 상태 표와
  최종 `professors.json`의 교수 수·`collectedAt`이 출력된다.

### 종료 코드

| 코드 | 뜻 |
| --- | --- |
| 0 | 전 단계 성공(또는 건너뜀) |
| 1 | 한 단계 이상 실패 |
| 2 | 사전 점검 실패 (`OPENALEX_API_KEY`가 필요한 단계를 실행하는데 키가 없음 · 잘못된 옵션) |
| 3 | 이미 실행 중(락 파일 존재) — 이번 실행은 아무것도 하지 않았다 |
| 130 | 사용자 중단(Ctrl+C) 또는 종료 신호 |

## 4. cron 등록 예시

> 실제 등록은 수집 서버 세팅 단계에서 진행한다 (아래는 양식).
> KCI 인증키가 IP에 묶여 있어 **고정 IP 수집 서버에서만** 동작한다 (계약 7장).

```cron
# 주 1회: 월요일 03:00 — 논문·사진·전문분야·조립
0 3 * * 1  cd /path/to/repo && .venv/bin/python scripts/run_all.py >> data/output/logs/cron.log 2>&1
# 월 1회: 매월 1일 04:00 — 명단 갱신 포함 전체
0 4 1 * *  cd /path/to/repo && .venv/bin/python scripts/run_all.py --include-roster >> data/output/logs/cron.log 2>&1
```

- 두 일정이 겹쳐도 락 파일이 뒤에 시작한 쪽을 거부하므로 산출물이 섞이지 않는다.
- 종료 코드가 0이 아니면 실패다. `cron.log` 끝의 **실행 요약** 표에서 어느 단계인지 확인한다.

## 5. 실패했을 때 확인 순서

1. **로그부터 본다** — `data/output/logs/`에서 가장 최근 `run_*.log`.
   파일 끝의 `===== 실행 요약 =====` 표에 단계별 상태(성공/실패/건너뜀/중단됨)가 있다.
2. **어느 단계인지 확인했으면** 그 단계 폴더의 README에서 증상별 대처를 본다.
   자주 나오는 것:
   - `OPENALEX_API_KEY를 찾지 못했습니다.` → 루트 `.env`에 키 채우기 (`.env.example` 참고)
   - 통신 오류 → 대체로 일시적. 다시 실행하면 이어서 진행된다(아래 resume 표).
3. **락 때문에 거부됐다면** — 로그에 락의 시작 시각·PID·경과 시간이 함께 찍힌다.
   강제 종료로 남은 스테일 락은 **자동으로 회수되므로 손댈 필요가 없다.** 그래도 거부됐다면
   기록된 PID가 살아 있거나(진짜 실행 중) PID 기록이 손상된 경우다.

   ```bash
   cat data/output/.run_all.lock      # started=... / pid=... 확인
   ps -p <pid>                        # (윈도우: tasklist /FI "PID eq <pid>")
   ```

   정말 도는 프로세스가 없다면 회수한다.

   ```bash
   python scripts/run_all.py --force-unlock
   ```

4. **재실행** — 실패한 단계만 다시 돌리려면 `--only`를 쓴다. 예: 4단계만 재시도

   ```bash
   python scripts/run_all.py --only 4
   ```

### 재실행 시 resume 동작

| # | 단계 | 재실행하면 |
| --- | --- | --- |
| 1 | 교수 명단 크롤 | 처음부터 다시 (1~2분) |
| 2 | 프로필 사진 URL | 처음부터 다시 (5~10분) |
| 3 | 전문진료분야 | 처음부터 다시 |
| 4 | 논문 수집 | **이어서 진행** — `professors_papers.json`에 저장된 교수는 건너뛰고, 통신 실패로 저장되지 않은 교수(`review.fetchFailed`)만 자동 재시도. 전부 다시 받으려면 `build_all.py`의 `FORCE_REFRESH = True` |
| 5 | MeSH·영문명·이메일 보강 | 해당 폴더 README 참고 |
| 6 | KCI 논문 수집 | 해당 폴더 README 참고 |
| 7 | 최종 조립 | 처음부터 다시 (앞 산출물을 읽어 합치는 단계라 빠르다) |

각 단계는 별도 프로세스로 돌기 때문에, 한 단계가 죽어도 다른 단계의 산출물은 그대로 남는다.
기본 모드에서는 실패 시 즉시 중단하므로, **뒤 단계가 옛 데이터로 조립되는 일은 없다.**
일부 단계 실패를 감수하고 끝까지 돌리려면 `--continue-on-error`를 쓴다(이 경우에도 종료 코드는 0이 아니다).
