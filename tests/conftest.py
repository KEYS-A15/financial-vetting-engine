"""
Stub out pdfplumber before any test imports it.
The cryptography DLL it depends on is blocked by Windows Application Control
in this environment, so we inject a mock module into sys.modules at collection
time. Tests that exercise the real extractor will mock pdfplumber.open anyway.
"""
import sys
from unittest.mock import MagicMock

# Only stub if the real library can't be loaded
try:
    import pdfplumber  # noqa: F401
except Exception:
    sys.modules["pdfplumber"] = MagicMock()
