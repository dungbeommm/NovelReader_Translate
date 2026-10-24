"""Isolate output roots for every test, including legacy fixtures."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_OUTPUT_TEXT', str(tmp_path/'output_text'))
    monkeypatch.setenv('NOVEL_OUTPUT_AUDIO', str(tmp_path/'output_audio'))
