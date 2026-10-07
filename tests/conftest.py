"""Test setup: every test runs against a throwaway home folder, never your real config or tapes."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# storage.py reads these at import time, so set them before anything imports uplink
TMP = Path(tempfile.mkdtemp(prefix="uplink-test-"))
os.environ.update(
    HOME=str(TMP / "home"),
    XDG_CONFIG_HOME=str(TMP / "home" / ".config"),
    XDG_DATA_HOME=str(TMP / "home" / ".local" / "share"),
    XDG_CACHE_HOME=str(TMP / "home" / ".cache"),
)
(TMP / "home").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def home():
    """A clean home folder for one test."""
    h = TMP / "home"
    shutil.rmtree(h, ignore_errors=True)
    h.mkdir(parents=True)
    from uplink import storage
    storage.LOAD_PROBLEMS.clear()
    yield h


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)
