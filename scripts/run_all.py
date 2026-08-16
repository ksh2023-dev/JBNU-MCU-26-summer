"""파이프라인 오케스트레이터 — 수집부터 조립까지 전 단계를 순서대로 '1회' 실행한다.

왜 필요한가: cron에 단계별 명령을 따로 걸면 앞 단계가 끝나기 전에 다음 단계가 시작될 수 있다
(논문 수집만 수십 분 걸린다). cron은 이 파일 하나만 부르고, 순서 보장은 여기서 책임진다.
**이 스크립트는 반복하지 않는다.** 반복 주기는 cron의 몫이고, 여기는 1회 실행 묶음이다.

설계 메모
- 각 단계는 별도 프로세스(subprocess)로 부른다. import하지 않는 이유: 수집 스크립트들이
  모듈 최상단에 실행 옵션 상수를 두고 있어 한 프로세스에 섞으면 서로 영향을 준다.
  또 한 단계가 죽어도 나머지 실행에 영향이 없다.
- 하위 스크립트는 현재 인터프리터(sys.executable)로 부른다 — 가상환경을 그대로 따라간다.
- 아직 다른 브랜치에 있는 스크립트는 '오류'가 아니라 '건너뜀(missing)'이다. 병합되면 자동으로
  실행 대상이 된다 (작업지시서 1장).
- 외부 라이브러리 없이 표준 라이브러리만 쓴다 (수집 서버에 추가 설치가 필요 없게).

종료 코드 (cron이 실패를 감지할 수 있어야 한다)
  0   전 단계 성공(또는 건너뜀)
  1   한 단계 이상 실패
  2   사전 점검 실패 (OPENALEX_API_KEY가 필요한 단계를 실행하는데 키가 없음 · 잘못된 옵션)
  3   이미 실행 중 (락 파일 존재) — 이번 실행은 아무것도 하지 않았다
  130 사용자 중단(Ctrl+C) 또는 종료 신호
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import unicodedata
from collections import namedtuple
from datetime import datetime
from pathlib import Path

# 저장소 루트 기준 경로 — 어느 폴더에서 실행해도 같은 곳을 읽고 쓴다
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
LOG_DIR = OUTPUT_DIR / "logs"
LOCK_PATH = OUTPUT_DIR / ".run_all.lock"
FINAL_OUTPUT = OUTPUT_DIR / "professors.json"

EXIT_OK = 0
EXIT_STEP_FAILED = 1
EXIT_PRECHECK = 2
EXIT_LOCKED = 3
EXIT_INTERRUPTED = 130

# 단계 정의 (작업지시서 1장의 표 그대로)
#   default_off       : 기본 실행에서 제외 — 명단 크롤은 월 1회라 --include-roster로만 켠다
#   skip_without_key  : 이 키가 .env에 없으면 자동 건너뜀 (KCI는 인증키가 있어야만 호출 가능)
#   skip_without_file : 이 선행 산출물이 없으면 자동 건너뜀.
#                       KCI 수집기는 7단계 결과인 professors.json을 수집 대상 명단으로 쓰는데
#                       6단계가 7단계보다 앞서므로 늘 '직전 회차'의 결과를 본다. 산출물이 하나도
#                       없는 새 서버의 첫 회차에는 대상 명단이 없어 돌 수 없다 — 오류가 아니라
#                       건너뜀으로 두고, 7단계가 파일을 만들면 다음 회차부터 자동으로 실행된다.
#   needs_openalex    : OPENALEX_API_KEY가 있어야 도는 단계. 이 단계가 이번 실행에 포함될 때만
#                       키를 필수로 검사한다 (사전 점검 참고)
Step = namedtuple(
    "Step",
    "number name script default_off skip_without_key skip_without_file needs_openalex",
    defaults=(False, None, None, False),
)

STEPS = [
    Step(1, "교수 명단 크롤", "scripts/roster_crawler/crawl_roster.py", default_off=True),
    Step(2, "프로필 사진 URL", "scripts/profile_image_collector/fetch_image_urls.py"),
    Step(3, "전문진료분야", "scripts/specialty_collector/fetch_specialties.py"),
    Step(4, "논문 수집(PubMed+OpenAlex)", "scripts/pubmed_collector/build_all.py",
         needs_openalex=True),
    Step(5, "MeSH·영문명·이메일 보강", "scripts/pubmed_collector/enrich_authors_mesh.py",
         needs_openalex=True),
    Step(6, "KCI 논문 수집", "scripts/kci_collector/fetch_kci.py",
         skip_without_key="KCI_API_KEY", skip_without_file="data/output/professors.json"),
    Step(7, "최종 조립", "scripts/assembler/build_professors.py"),
]

STEP_NUMBERS = [s.number for s in STEPS]

# 상태 표기 — 계획표와 종료 요약에서 같은 말을 쓴다
ST_PLANNED = "실행 예정"
ST_OK = "성공"
ST_FAILED = "실패"
ST_SKIP_OPTION = "건너뜀(옵션)"
ST_SKIP_MISSING = "건너뜀(missing)"
ST_SKIP_NOKEY = "건너뜀(키없음)"
ST_SKIP_NO_INPUT = "건너뜀(선행 산출물 없음)"
ST_ABORTED = "중단됨"


# ---------------------------------------------------------------------------
# 출력 도우미 — 콘솔과 로그 파일에 같은 내용을 남긴다
# ---------------------------------------------------------------------------

def _display_width(text):
    """콘솔 표시 폭 — 한글·전각 문자는 두 칸을 차지하므로 표 정렬에 반영한다."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text, width):
    """표 칸 맞춤 — 표시 폭 기준으로 오른쪽을 공백으로 채운다."""
    return text + " " * max(0, width - _display_width(text))


class Logger:
    """콘솔로 흘려보내면서 동시에 로그 파일에도 남긴다 (요구사항 4).

    path가 None이면(=--dry-run) 파일은 만들지 않고 화면에만 출력한다.
    """

    def __init__(self, path):
        self.path = path
        self._fh = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8")

    def write(self, text=""):
        """한 줄 기록 (줄바꿈은 이쪽에서 붙인다)."""
        print(text, flush=True)
        if self._fh:
            self._fh.write(text + "\n")
            self._fh.flush()   # 실행이 길어 중간에 끊겨도 여기까지는 남게 한다

    def write_raw(self, text):
        """하위 스크립트 출력 — 줄바꿈까지 원본 그대로 흘려보낸다."""
        sys.stdout.write(text)
        sys.stdout.flush()
        if self._fh:
            self._fh.write(text)
            self._fh.flush()

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


def _relax_console_encoding():
    """콘솔이 표현하지 못하는 문자가 섞여도 실행이 죽지 않게 한다.

    윈도우 기본 콘솔(cp949)에서는 일부 기호가 인코딩 오류를 내는데, 수십 분짜리 수집이
    출력 한 글자 때문에 멈추면 손해가 크다. 인코딩은 그대로 두고 오류만 대체 문자로 넘긴다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass   # 파이썬 3.6 이하이거나 재설정할 수 없는 스트림 — 그냥 둔다


# ---------------------------------------------------------------------------
# 옵션 처리
# ---------------------------------------------------------------------------

def _step_numbers(text):
    """--only / --skip 값 "4,5"를 단계 번호 집합으로 바꾼다."""
    numbers = set()
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit() or int(chunk) not in STEP_NUMBERS:
            raise argparse.ArgumentTypeError(
                f"단계 번호가 아닙니다: {chunk} (가능한 값: {','.join(map(str, STEP_NUMBERS))})"
            )
        numbers.add(int(chunk))
    if not numbers:
        raise argparse.ArgumentTypeError("단계 번호를 하나 이상 지정하세요 (예: --only 4,5)")
    return numbers


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description="교수 데이터 수집~조립 파이프라인을 순서대로 1회 실행한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="단계 번호: " + " / ".join(f"{s.number}={s.name}" for s in STEPS),
    )
    parser.add_argument(
        "--include-roster", action="store_true",
        help="1단계(교수 명단 크롤) 포함 — 월 1회용이라 기본은 제외",
    )
    parser.add_argument(
        "--only", type=_step_numbers, metavar="N,N",
        help="지정한 단계만 실행 (예: --only 4,5)",
    )
    parser.add_argument(
        "--skip", type=_step_numbers, metavar="N,N",
        help="지정한 단계를 건너뜀 (예: --skip 2,3)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제 실행 없이 계획표만 출력 (락도 잡지 않는다)",
    )
    parser.add_argument(
        "--continue-on-error", action="store_true",
        help="단계가 실패해도 다음 단계를 계속 진행 (기본은 즉시 중단)",
    )
    parser.add_argument(
        "--env-file", metavar="PATH",
        help="사전 점검에 쓸 .env 경로 (기본: 저장소 루트의 .env). 서버 구성·검증용",
    )
    args = parser.parse_args(argv)
    if args.only and args.skip:
        parser.error("--only와 --skip은 함께 쓸 수 없습니다 (실행 대상이 모호해집니다)")
    return args


# ---------------------------------------------------------------------------
# 사전 점검
# ---------------------------------------------------------------------------

def read_env_values(env_path):
    """.env를 훑어 KEY=값 사전을 만든다.

    수집 스크립트들(enrich_citations.read_openalex_api_key 등)이 쓰는 것과 같은 몇 줄짜리
    파서다 — 외부 라이브러리 없이 같은 파일을 같은 방식으로 읽어 해석이 어긋나지 않게 한다.
    """
    values = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:                      # 값이 빈 줄은 '없는 것'으로 본다
            values[key.strip()] = value
    return values


def precheck(logger, env_path, env_values, plan):
    """실행 전 한 번 하는 점검. 통과하면 True, 중단해야 하면 False.

    OPENALEX_API_KEY는 **이번 실행에 그 키가 필요한 단계(4·5)가 들어 있을 때만** 필수로 본다.
    키가 없으면 그 단계는 반드시 실패하므로 수십 분을 버리기 전에 여기서 멈추지만,
    키가 필요 없는 실행(예: --only 2)까지 막을 이유는 없다.
    """
    logger.write(f"사전 점검: {env_path}")
    blocked = [s for s, status, _ in plan if s.needs_openalex and status == ST_PLANNED]
    need_names = ", ".join(f"{s.number}단계({s.name})" for s in blocked)

    if not env_path.exists():
        if blocked:
            logger.write(f"[중단] .env 파일이 없습니다 — {need_names}에 OPENALEX_API_KEY가 필요합니다.")
            logger.write("       저장소 루트의 .env.example을 복사해 .env를 만들고 키를 채워 주세요.")
            return False
        logger.write("  .env 없음 — 이번 실행에는 키가 필요한 단계가 없어 그대로 진행합니다.")
        return True

    if env_values.get("OPENALEX_API_KEY"):
        logger.write("  OPENALEX_API_KEY: 있음")
    elif blocked:
        logger.write(f"[중단] .env에 OPENALEX_API_KEY가 없습니다 — {need_names}가 반드시 실패합니다.")
        logger.write("       openalex.org 무료 계정 → 설정(Settings)에서 키를 복사해 .env에 넣어 주세요.")
        logger.write("         OPENALEX_API_KEY=발급받은키")
        return False
    else:
        logger.write("  OPENALEX_API_KEY: 없음 — 이번 실행에 필요한 단계가 없어 확인하지 않습니다.")

    if env_values.get("KCI_API_KEY"):
        logger.write("  KCI_API_KEY: 있음")
    else:
        logger.write("  KCI_API_KEY: 없음 → 6단계(KCI 논문 수집)는 자동으로 건너뜁니다.")
    return True


def build_plan(args, env_values):
    """단계별로 '실행할지 / 왜 건너뛰는지'를 정한다. 반환: [(Step, 상태, 스크립트 경로)]

    건너뛰는 이유를 계획표와 요약에 그대로 남겨, 안 돈 단계를 성공으로 착각하지 않게 한다.
    """
    plan = []
    for step in STEPS:
        script_path = ROOT / step.script
        status = ST_PLANNED

        # ① 옵션에 의한 선택 — --only에 이름이 적혔으면 기본 제외(월 1회)보다 우선한다
        if args.only is not None:
            if step.number not in args.only:
                status = ST_SKIP_OPTION
        elif args.skip and step.number in args.skip:
            status = ST_SKIP_OPTION
        elif step.default_off and not args.include_roster:
            status = ST_SKIP_OPTION

        # ② 인증키 — 키가 없으면 호출 자체가 불가능하다
        if status == ST_PLANNED and step.skip_without_key and not env_values.get(step.skip_without_key):
            status = ST_SKIP_NOKEY

        # ③ 선행 산출물 — 앞 회차 결과가 있어야 도는 단계 (KCI ← professors.json)
        if status == ST_PLANNED and step.skip_without_file:
            if not (ROOT / step.skip_without_file).exists():
                status = ST_SKIP_NO_INPUT

        # ④ 파일 존재 — 아직 병합되지 않은 스크립트는 오류가 아니라 건너뜀이다
        if status == ST_PLANNED and not script_path.exists():
            status = ST_SKIP_MISSING

        plan.append([step, status, script_path])
    return plan


def print_plan(logger, plan, args):
    """계획표 출력 — 어떤 단계가 왜 도는지/안 도는지를 실행 전에 눈으로 확인한다."""
    name_width = max(_display_width(s.name) for s in STEPS)
    status_width = max(_display_width(st) for _, st, _ in plan)

    logger.write("")
    logger.write("===== 실행 계획 =====")
    logger.write(f"  {_pad('#', 2)} {_pad('단계', name_width)}  {_pad('상태', status_width)}  스크립트")
    for step, status, script_path in plan:
        note = ""
        if status == ST_SKIP_MISSING:
            note = "  <- 다른 브랜치 · 병합되면 자동 실행"
        elif status == ST_SKIP_NO_INPUT:
            note = f"  <- {step.skip_without_file} 없음 · 7단계가 만들면 다음 회차부터 실행"
        logger.write(
            f"  {_pad(str(step.number), 2)} {_pad(step.name, name_width)}  "
            f"{_pad(status, status_width)}  {step.script}{note}"
        )

    planned = [p for p in plan if p[1] == ST_PLANNED]
    missing = [p for p in plan if p[1] == ST_SKIP_MISSING]
    no_input = [p for p in plan if p[1] == ST_SKIP_NO_INPUT]
    logger.write(f"실행 예정 {len(planned)}단계 / 전체 {len(plan)}단계")
    if missing:
        names = ", ".join(f"{s.number}({s.name})" for s, _, _ in missing)
        logger.write(f"[경고] 스크립트를 찾지 못해 건너뜁니다: {names}")
    for step, _, _ in no_input:
        logger.write(
            f"[안내] {step.number}단계({step.name})는 선행 산출물 {step.skip_without_file}이 없어 "
            f"건너뜁니다 — 7단계가 만들면 다음 회차부터 자동으로 실행됩니다."
        )
    logger.write(f"실패 시 동작: {'다음 단계 계속 진행' if args.continue_on_error else '즉시 중단(기본)'}")


# ---------------------------------------------------------------------------
# 중복 실행 방지 (락 파일)
# ---------------------------------------------------------------------------

def acquire_lock(logger):
    """락 파일을 '없을 때만' 만든다(O_EXCL) — 이미 있으면 실행 중으로 보고 거부한다.

    이유: cron 주기보다 실행이 길어지면 두 프로세스가 같은 산출물을 동시에 쓸 수 있다.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        logger.write("")
        logger.write(f"[거부] 이미 실행 중입니다 — 락 파일: {LOCK_PATH}")
        try:
            logger.write("       " + LOCK_PATH.read_text(encoding="utf-8").strip().replace("\n", " / "))
        except OSError:
            pass
        logger.write("       앞 실행이 비정상 종료해 락만 남았다면 이 파일을 지우고 다시 실행하세요.")
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"started={datetime.now():%Y-%m-%d %H:%M:%S}\npid={os.getpid()}\n")
    return True


def release_lock(logger):
    """락 해제 — 정상·비정상(예외·신호) 종료 모두에서 반드시 부른다."""
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.write(f"[경고] 락 파일을 지우지 못했습니다: {exc} — 수동으로 지워 주세요: {LOCK_PATH}")


def install_signal_handlers():
    """종료 신호를 예외로 바꿔 finally(락 해제)가 반드시 돌게 한다.

    기본 동작으로는 SIGTERM(cron·서버 재시작 등)이 프로세스를 즉시 죽여 락 파일이 남는다.
    """
    def _handler(signum, frame):
        raise SystemExit(EXIT_INTERRUPTED)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError):
            pass   # 이 플랫폼에서 못 잡는 신호 — 무시한다


# ---------------------------------------------------------------------------
# 단계 실행
# ---------------------------------------------------------------------------

def run_step(logger, step, script_path):
    """단계 하나를 별도 프로세스로 실행한다. 반환: (종료 코드, 소요 초)"""
    started_at = datetime.now()
    started = time.monotonic()
    logger.write("")
    logger.write(f"----- [{step.number}] {step.name} 시작 {started_at:%Y-%m-%d %H:%M:%S} -----")
    logger.write(f"실행: {sys.executable} -u {step.script}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"   # 하위 스크립트의 한글 출력이 파이프에서 깨지지 않게 고정

    # -u: 하위 스크립트 출력을 버퍼링 없이 받아 진행 상황을 실시간으로 흘려보낸다
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(script_path)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # 오류 메시지도 같은 로그에 순서대로 남긴다
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        # 계획을 세운 뒤 파일이 없어졌거나 실행 권한이 없는 경우 — 통째로 죽지 않고
        # 이 단계만 '실패'로 기록한다 (역추적 불가능한 트레이스백 대신 요약에 남게).
        logger.write(f"[실패] 프로세스를 시작하지 못했습니다: {exc}")
        return 1, time.monotonic() - started
    try:
        for line in proc.stdout:
            logger.write_raw(line)
        code = proc.wait()
    finally:
        # 상위가 중단(Ctrl+C·SIGTERM)돼도 자식은 살아남는다 — 락을 푼 뒤 산출물을 계속
        # 건드리는 상황을 막기 위해 여기서 정리한다.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    elapsed = time.monotonic() - started
    logger.write(
        f"----- [{step.number}] {step.name} 종료 {datetime.now():%Y-%m-%d %H:%M:%S} "
        f"· 소요 {format_elapsed(elapsed)} · 종료 코드 {code} -----"
    )
    return code, elapsed


def format_elapsed(seconds):
    """소요 시간을 사람이 읽는 형태로 (예: 1분 03초)."""
    if seconds is None:
        return "-"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes:
        return f"{minutes}분 {secs:02d}초"
    return f"{secs}초"


def execute(logger, plan, args):
    """계획대로 단계를 순서대로 실행한다. 반환: 실패한 단계가 있으면 True

    plan의 각 항목 상태를 실행 결과로 갱신하고, 소요 시간을 4번째 칸에 덧붙인다.
    """
    for entry in plan:
        entry.append(None)   # 소요 시간 칸

    failed = False
    for entry in plan:
        step, status, script_path, _ = entry
        if status != ST_PLANNED:
            continue
        if failed and not args.continue_on_error:
            entry[1] = ST_ABORTED   # 앞 단계 실패로 아예 시작하지 않았다
            continue

        code, elapsed = run_step(logger, step, script_path)
        entry[3] = elapsed
        if code == 0:
            entry[1] = ST_OK
        else:
            entry[1] = ST_FAILED
            failed = True
            if args.continue_on_error:
                logger.write(f"[경고] {step.number}단계 실패(종료 코드 {code}) — "
                             f"--continue-on-error 지정이라 다음 단계로 계속합니다.")
            else:
                logger.write(f"[중단] {step.number}단계 실패(종료 코드 {code}) — "
                             f"이후 단계를 실행하지 않습니다. 계속하려면 --continue-on-error")
    return failed


# ---------------------------------------------------------------------------
# 종료 요약
# ---------------------------------------------------------------------------

def print_final_output_info(logger):
    """최종 산출물이 있으면 교수 수와 수집 기준일(collectedAt)을 함께 보여 준다."""
    if not FINAL_OUTPUT.exists():
        logger.write(f"최종 산출물 없음: {FINAL_OUTPUT}")
        return
    try:
        with open(FINAL_OUTPUT, encoding="utf-8") as f:
            data = json.load(f)
        professors = data.get("professors", [])
        logger.write(
            f"최종 산출물: {FINAL_OUTPUT} — 교수 {len(professors)}명 · "
            f"collectedAt {data.get('collectedAt')}"
        )
    except (OSError, ValueError) as exc:
        # 조립기가 도중에 죽어 파일이 깨졌을 수 있다 — 요약이 여기서 멈추지는 않게 한다
        logger.write(f"[경고] 최종 산출물을 읽지 못했습니다: {FINAL_OUTPUT} ({exc})")


def print_summary(logger, plan, total_elapsed):
    """단계별 상태 표 + 최종 산출물 정보."""
    name_width = max(_display_width(s.name) for s in STEPS)
    status_width = max(_display_width(entry[1]) for entry in plan)

    logger.write("")
    logger.write("===== 실행 요약 =====")
    logger.write(f"  {_pad('#', 2)} {_pad('단계', name_width)}  {_pad('상태', status_width)}  소요")
    for step, status, _script_path, elapsed in plan:
        logger.write(
            f"  {_pad(str(step.number), 2)} {_pad(step.name, name_width)}  "
            f"{_pad(status, status_width)}  {format_elapsed(elapsed)}"
        )

    counts = {}
    for _, status, _, _ in plan:
        counts[status] = counts.get(status, 0) + 1
    logger.write("합계: " + " · ".join(f"{k} {v}" for k, v in counts.items()))
    logger.write(f"전체 소요: {format_elapsed(total_elapsed)}")
    print_final_output_info(logger)
    if logger.path:
        logger.write(f"로그 파일: {logger.path}")


# ---------------------------------------------------------------------------

def main(argv=None):
    _relax_console_encoding()
    args = parse_args(argv)

    log_path = None
    if not args.dry_run:
        # 사전 점검·락 거부 이유도 로그에 남아야 cron이 실패 원인을 찾을 수 있다
        log_path = LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    logger = Logger(log_path)

    try:
        logger.write(f"===== 파이프라인 실행 {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        logger.write(f"저장소 루트: {ROOT}")
        logger.write(f"파이썬: {sys.executable}")
        if args.dry_run:
            logger.write("모드: --dry-run (실제 실행 없이 계획만 출력)")

        env_path = Path(args.env_file).expanduser().resolve() if args.env_file else ROOT / ".env"
        env_values = read_env_values(env_path)

        # 계획을 먼저 세운다 — 어떤 단계가 실제로 도는지 알아야 어떤 키가 필수인지 판단할 수 있다
        plan = build_plan(args, env_values)
        if not precheck(logger, env_path, env_values, plan):
            return EXIT_PRECHECK
        print_plan(logger, plan, args)

        if args.dry_run:
            logger.write("")
            logger.write("--dry-run: 여기까지가 계획입니다. 실제 실행은 --dry-run 없이 다시 부르세요.")
            return EXIT_OK

        install_signal_handlers()   # 락을 잡기 직전에 — 어떻게 끝나도 락이 남지 않게
        if not acquire_lock(logger):
            return EXIT_LOCKED

        started = time.monotonic()
        try:
            failed = execute(logger, plan, args)
            print_summary(logger, plan, time.monotonic() - started)
        finally:
            release_lock(logger)   # 예외·신호로 빠져나가도 락은 반드시 푼다
        return EXIT_STEP_FAILED if failed else EXIT_OK

    except KeyboardInterrupt:
        logger.write("")
        logger.write("[중단] 사용자 중단(Ctrl+C) — 락은 해제했습니다.")
        return EXIT_INTERRUPTED
    finally:
        logger.close()


if __name__ == "__main__":
    sys.exit(main())
