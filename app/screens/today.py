"""Page launcher."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib

import app.components.charts as charts
import app.components.clock as clock
from app.views import today

importlib.reload(charts)
importlib.reload(clock)
importlib.reload(today)
today.render()
