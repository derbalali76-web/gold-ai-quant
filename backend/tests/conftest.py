import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from goldquant.providers.demo import DemoProvider, generate_m1, resample  # noqa: E402


@pytest.fixture(scope="session")
def demo():
    return DemoProvider()


@pytest.fixture(scope="session")
def demo_bars():
    m1 = generate_m1()
    return {tf: resample(m1, tf) for tf in ("M15", "M30", "H1", "H4")}
