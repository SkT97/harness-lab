"""Test package for harness-lab.

Bootstrap: make the in-repo package importable without installing it, so that
`python -m unittest discover -s <repo>/public-export/harness-lab/tests` works
with nothing but the standard library.
"""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
