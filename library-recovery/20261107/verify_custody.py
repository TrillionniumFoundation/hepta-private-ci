#!/usr/bin/env python3
"""Verify the preserved source bytes without extracting or executing them."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from verify_source_custody_container import UNRESOLVED, main

if __name__ == "__main__":
    sys.exit(main([UNRESOLVED]))
