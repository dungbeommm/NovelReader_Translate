"""API routes for Pixeldrain file exports."""
import os
from fastapi import APIRouter, Header, HTTPException, Body
from pydantic import BaseModel
from storage import pixeldrain_service
from web import runtime

router = APIRouter()


class PixeldrainRequest(BaseModel):
    api_key: str | None = None


@router.get("/api/export/pixeldrain/status")
def pixeldrain_status():
    env_key = os.getenv("PIXELDRAIN_API_KEY", "").strip()
    from storage.cloud_settings import load_key
    return {
        "has_key": bool(pixeldrain_service.get_pixeldrain_api_key()),
        "has_saved_key": bool(load_key()),
        "ok": True,
        "has_env_key": bool(env_key),
        "env_key_masked": "***" if env_key else "",
    }


@router.post("/api/export/pixeldrain/{format}")
def export_to_pixeldrain(
    format: str,
    payload: PixeldrainRequest | None = None,
    x_pixeldrain_key: str | None = Header(default=None, alias="X-Pixeldrain-Key")
):
    format = format.lower().strip()
    if format not in {"txt", "epub", "audio"}:
        raise HTTPException(400, "Định dạng xuất phải là txt, epub hoặc audio")

    api_key = (payload.api_key if payload and payload.api_key else None) or x_pixeldrain_key

    try:
        result = pixeldrain_service.export_book_to_pixeldrain(
            runtime.store, kind=format, api_key=api_key
        )
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Lỗi xuất Pixeldrain: {exc}")


@router.post("/api/export/pixeldrain/file/{filename}")
def export_file_to_pixeldrain(
    filename: str,
    payload: PixeldrainRequest | None = None,
    x_pixeldrain_key: str | None = Header(default=None, alias="X-Pixeldrain-Key")
):
    api_key = (payload.api_key if payload and payload.api_key else None) or x_pixeldrain_key

    try:
        result = pixeldrain_service.export_audio_file_to_pixeldrain(
            runtime.store, filename=filename, api_key=api_key
        )
        return result
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Lỗi upload Pixeldrain: {exc}")
