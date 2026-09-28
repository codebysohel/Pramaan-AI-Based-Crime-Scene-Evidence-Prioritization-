import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own database, ledger and case folder."""
    monkeypatch.setenv("PRAMAAN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRAMAAN_LLM_PROVIDER", "none")
    monkeypatch.setenv("PRAMAAN_PROTECTED_TERMS", str(tmp_path / "protected.sha256"))
    yield tmp_path
