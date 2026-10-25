import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MYOWNROBOT_HOME", tempfile.mkdtemp(prefix="mor_home_"))


def synth(n=6000, seed=1, start="2024-01-01", spread=0.3, base=2000.0, vol=1.0, freq="15min"):
    rng = np.random.default_rng(seed)
    ret = rng.standard_normal(n) * vol
    c = base + np.cumsum(ret)
    o = np.concatenate([[base], c[:-1]]) + rng.standard_normal(n) * 0.05
    hi = np.maximum(o, c) + np.abs(rng.standard_normal(n)) * vol * 0.5
    lo = np.minimum(o, c) - np.abs(rng.standard_normal(n)) * vol * 0.5
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": rng.random(n) * 100 + 10,
                         "spread": np.full(n, spread)}, index=idx)


@pytest.fixture
def df():
    return synth()


@pytest.fixture
def db(tmp_path):
    from mor.db import Database
    d = Database(tmp_path / "t.db")
    yield d
    d.close()
