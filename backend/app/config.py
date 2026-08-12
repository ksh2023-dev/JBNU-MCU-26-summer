import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 지금은 합성 샘플. 실데이터 파이프라인(scripts/)이 완성되면 이 경로만 바꾼다.
DATA_FILE = Path(os.getenv("DATA_FILE", PROJECT_ROOT / "data" / "sample" / "professors.sample.json"))

DEFAULT_MIN_SCORE = float(os.getenv("DEFAULT_MIN_SCORE", "0.3"))

# API ③ 최근 연구 활동 교수 — 최근 논문 발행일 기준 상위 N명 (v6 계약: 카드 3~5개)
FEATURED_COUNT = int(os.getenv("FEATURED_COUNT", "3"))

CORS_ORIGINS = [s for s in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if s]
