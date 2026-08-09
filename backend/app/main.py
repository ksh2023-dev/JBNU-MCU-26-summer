from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .routers import professors

app = FastAPI(
    title="연수매칭 · 의대 연구 추천 API",
    description="데이터 계약 v4 기반. 응답 모양은 docs/api-spec.md(= 계약 문서)를 따른다.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(professors.router)


@app.get("/health")
def health():
    return {"status": "ok"}
