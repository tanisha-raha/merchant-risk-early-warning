import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from features import load_raw  # noqa: E402

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


@pytest.fixture(scope="session")
def raw():
    """Shared across test modules -- raw data is read-only and loading it
    (~9 CSVs) is not free, so session scope avoids re-reading it per module.
    """
    if not RAW_DIR.exists():
        pytest.skip(f"raw data not found at {RAW_DIR}")
    return load_raw(RAW_DIR)
