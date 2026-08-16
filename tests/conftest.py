import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def mandate_dict():
    with (ROOT / "mandate.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def md(mandate_dict):
    """Fresh deep copy per test so tests can mutate freely."""
    return copy.deepcopy(mandate_dict)
