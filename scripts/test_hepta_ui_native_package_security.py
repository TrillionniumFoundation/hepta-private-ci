"""Discover app-owned package tests in the six-subject Python evidence lane."""
import importlib.util
from pathlib import Path
import sys

PATH = Path(__file__).resolve().parents[1] / "apps/hepta-native/tools/tests/test_package_security.py"
SPEC = importlib.util.spec_from_file_location("_hepta_native_package_security", PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("native package security tests cannot be loaded")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
PackageSecurityTests = MODULE.PackageSecurityTests
