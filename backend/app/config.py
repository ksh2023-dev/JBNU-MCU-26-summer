import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 지금은 합성 샘플. 실데이터 파이프라인(scripts/)이 완성되면 이 경로만 바꾼다.
DATA_FILE = Path(os.getenv("DATA_FILE", PROJECT_ROOT / "data" / "sample" / "professors.sample.json"))

DEFAULT_MIN_SCORE = float(os.getenv("DEFAULT_MIN_SCORE", "0.3"))

# API ③ 우수 교수 — 선정 기준(수상 등) 확정 전까지 수동 큐레이션 (계약 5장 7번)
FEATURED_IDS = [s for s in os.getenv("FEATURED_IDS", "P-001,P-002,P-005").split(",") if s]

CORS_ORIGINS = [s for s in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if s]
