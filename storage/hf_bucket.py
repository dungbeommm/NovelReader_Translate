"""Hugging Face Storage Bucket adapter.

The adapter is deliberately disabled when no credentials are configured.  It
never silently substitutes a dataset repository or a local fake remote.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class HFConfig:
    token: str | None
    bucket_id: str | None
    username: str | None = None

    @property
    def qualified_bucket_id(self) -> str | None:
        if not self.bucket_id:
            return None
        if "/" in self.bucket_id or not self.username:
            return self.bucket_id
        return f"{self.username}/{self.bucket_id}"

    @property
    def configured(self) -> bool:
        return bool(self.token and self.qualified_bucket_id)


def load_config() -> HFConfig:
    """Load secrets from env or a user-owned private JSON file.

    The private file is never uploaded and its contents are never returned by
    the API.  Environment variables remain the preferred MoLab secret source.
    """
    values = {
        "token": os.getenv("HF_TOKEN", "").strip(),
        "bucket_id": os.getenv("HF_BUCKET_ID", "").strip(),
        "username": os.getenv("HF_USERNAME", "").strip(),
    }
    private_path = Path(os.getenv("NOVELREADER_PRIVATE_CONFIG", "~/.config/novelreader/private.json")).expanduser()
    if private_path.is_file():
        try:
            private = json.loads(private_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            private = {}
        for key in values:
            if not values[key] and isinstance(private.get(key), str):
                values[key] = private[key].strip()
    return HFConfig(**values)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HFBucketStorage:
    """Thin, testable wrapper around the official bucket functions."""

    def __init__(self, config: HFConfig | None = None):
        self.config = config or load_config()

    def _require(self) -> tuple[str, str]:
        if not self.config.configured:
            raise RuntimeError("Hugging Face Storage chưa được cấu hình: cần HF_TOKEN và HF_BUCKET_ID.")
        return self.config.qualified_bucket_id, self.config.token  # type: ignore[return-value]

    def connect(self, *, create: bool = False) -> dict:
        bucket_id, token = self._require()
        from huggingface_hub import HfApi, create_bucket

        if create:
            create_bucket(bucket_id, private=True, exist_ok=True, token=token)
        who = HfApi(token=token).whoami()
        return {"connected": True, "bucket_id": bucket_id, "username": who.get("name") or who.get("user")}

    def list_files(self, prefix: str = "") -> list[dict]:
        bucket_id, token = self._require()
        from huggingface_hub import HfApi

        rows = []
        for item in HfApi(token=token).list_repo_tree(bucket_id, path_in_repo=prefix or None, recursive=True, repo_type="bucket"):
            path = getattr(item, "path", None)
            if path is None or getattr(item, "type", "file") == "directory":
                continue
            rows.append({"path": path, "size": getattr(item, "size", None), "sha256": getattr(item, "lfs", None)})
        return rows

    def upload_file(self, local_path: Path, remote_path: str, *, verify: bool = True) -> dict:
        bucket_id, token = self._require()
        local_path = Path(local_path)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        from huggingface_hub import batch_bucket_files

        batch_bucket_files(bucket_id, add=[(local_path, remote_path)], token=token)
        result = {"path": remote_path, "size": local_path.stat().st_size}
        if verify:
            result["sha256"] = sha256_file(local_path)
        return result

    def upload_many(self, files: Iterable[tuple[Path, str]]) -> list[dict]:
        bucket_id, token = self._require()
        prepared = [(Path(local), remote) for local, remote in files]
        if not prepared:
            return []
        from huggingface_hub import batch_bucket_files

        batch_bucket_files(bucket_id, add=[(local, remote) for local, remote in prepared], token=token)
        return [{"path": remote, "size": local.stat().st_size, "sha256": sha256_file(local)} for local, remote in prepared]

    def download_file(self, remote_path: str, local_path: Path) -> Path:
        bucket_id, token = self._require()
        from huggingface_hub import download_bucket_files

        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        download_bucket_files(bucket_id, files=[(remote_path, local_path)], token=token)
        return local_path

    def delete_file(self, remote_path: str) -> None:
        bucket_id, token = self._require()
        from huggingface_hub import batch_bucket_files

        batch_bucket_files(bucket_id, delete=[remote_path], token=token)

    def sync_directory(self, local_dir: Path, remote_prefix: str, *, download: bool = False) -> dict:
        bucket_id, token = self._require()
        from huggingface_hub import sync_bucket

        local_dir = Path(local_dir)
        if download:
            sync_bucket(f"hf://buckets/{bucket_id}/{remote_prefix.strip('/')}", str(local_dir), token=token)
        else:
            sync_bucket(str(local_dir), f"hf://buckets/{bucket_id}/{remote_prefix.strip('/')}", token=token)
        return {"ok": True, "remote_prefix": remote_prefix, "download": download}

