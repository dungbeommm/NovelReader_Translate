"""Entry point: python -m uvicorn main:app --host 127.0.0.1 --port 8000."""
from web.application import create_app
from web import runtime

app = create_app()
