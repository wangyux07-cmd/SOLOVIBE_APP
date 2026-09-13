"""Canonical FastAPI entry point for the staged V1 redesign.

Stage 0 serves liveness/configuration and an explicit not-ready response.
The old demo entry point is archived in legacy_main.py and is not imported.
"""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from config import configuration_status, cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VERSION = "0.2.0"
STAGE = "baseline"
NOT_READY_MESSAGE = "前后端已连通。当前正在建设 Agent，暂未执行模型、地图或网页查询。"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def non_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


def not_ready() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "AGENT_NOT_IMPLEMENTED",
                "message": NOT_READY_MESSAGE,
                "retryable": False,
            },
            "stage": STAGE,
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(title="SoloVibe API", version=VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.get("/")
    async def root():
        return {"service": "solovibe", "version": VERSION, "stage": STAGE, "docs": "/docs"}

    @app.get("/health", include_in_schema=False)
    @app.get("/api/v1/health")
    async def health():
        return {
            "status": "ok",
            "ready": False,
            "stage": STAGE,
            "version": VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": configuration_status(),
        }

    @app.get("/api/v1/readiness")
    async def readiness():
        return not_ready()

    @app.get("/api/v1/config-status")
    async def config_status():
        return {"services": configuration_status(), "stage": STAGE}

    @app.post("/api/chat")
    async def chat(request: ChatRequest):
        # Replaced by ApplicationService in stage 1; no synthetic response.
        return not_ready()

    @app.post("/api/v1/stream_chat")
    async def stream_chat(request: ChatRequest):
        return not_ready()

    @app.post("/api/v1/threads/{thread_id}/resume")
    async def resume_thread(thread_id: str):
        return not_ready()

    @app.get("/api/v2/wander-plans")
    async def wander_plans():
        return not_ready()

    return app


app = create_app()
