"""NovelReader API for downloading a Fanqie novel by book ID."""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.tomato_service import TomatoClient, TomatoError, pipeline
from web.schemas import Config

router = APIRouter()


class TomatoStart(BaseModel):
    book_id: str = Field(min_length=8, max_length=25, pattern=r"^[0-9]+$")
    replace_existing: bool = False
    config: Config = Field(default_factory=Config)



@router.get("/api/tomato/health")
def tomato_health():
    """Troubleshooting endpoint: never return secrets to the browser."""
    configured_url = os.getenv("TOMATO_WEB_URL", "http://127.0.0.1:18423")
    try:
        client = TomatoClient()
        status = client.request("GET", "/api/status")
        return {"connected": True, "url": client.url, "version": status.get("version")}
    except TomatoError as exc:
        return {"connected": False, "url": configured_url, "detail": str(exc)}

@router.get("/api/tomato/status")
def tomato_status():
    return pipeline.snapshot()


@router.post("/api/tomato/start")
def tomato_start(payload: TomatoStart):
    # Keep all inference options from the current NovelReader UI, not from Rust.
    config = payload.config.model_dump(exclude={"reset"})
    config["start_pos"] = None
    config["end_pos"] = None
    config["chapter_ids"] = None
    config["force_retranslate"] = False
    try:
        return pipeline.start(payload.book_id, config, payload.replace_existing)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except TomatoError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/tomato/cancel")
def tomato_cancel():
    if not pipeline.downloading():
        raise HTTPException(409, "Không có tác vụ tải nào đang chạy.")
    try:
        return pipeline.cancel()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
