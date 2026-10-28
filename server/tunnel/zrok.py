"""Common zrok public-share utilities (no background kill/restart side effects)."""
import re

SHARE_HOST = re.compile(r"(?i)\b([a-z0-9-]+\.shares\.zrok\.io)\b")


def extract_share_host(log_text: str) -> str:
    matches = SHARE_HOST.findall(log_text or "")
    return matches[-1].lower() if matches else ""


def public_url(log_text: str) -> str:
    host = extract_share_host(log_text)
    return "https://" + host + "/" if host else ""


def public_share_command(binary: str, backend_url: str = "http://127.0.0.1:8000") -> list[str]:
    return [binary, "share", "public", backend_url, "--headless"]
