"""MarkVault core — GUI 없이 동작하는 부분 (collector / renderer / writer)."""
import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor")
# Anki 에 이미 있는 bs4 등을 우선 쓰고, 없을 때만 vendor 사본을 쓴다.
if _VENDOR not in sys.path:
    sys.path.append(_VENDOR)
