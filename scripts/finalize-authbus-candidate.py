#!/usr/bin/env python3
"""Attach operational code and exact-candidate checks BEFORE qualification."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    file = ROOT / path
    text = file.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one reviewed patch anchor")
    file.write_text(text.replace(old, new))


replace("codex-rs/hepta-authbus/src/lib.rs", "mod issuer_registry;", "mod issuer_registry;\nmod metrics;")
replace("scripts/authbus-exact-head-evidence.py",
        '"inventory", "inventory_tests", "receipt_tests",',
        '"inventory", "inventory_tests", "implementation_map", "operations_contract", "receipt_tests",')
replace("scripts/authbus-exact-head-evidence.py",
        '        "inventory_tests": [sys.executable, "scripts/test-authbus-closed-world.py"],',
        '        "inventory_tests": [sys.executable, "scripts/test-authbus-closed-world.py"],\n        "implementation_map": [sys.executable, "scripts/generate-authbus-implementation-map.py", "--check"],\n        "operations_contract": [sys.executable, "scripts/test-authbus-operations.py"],')
replace("scripts/authbus-exact-head-evidence.py", "import json\n", "import json\nimport math\n")
replace("scripts/authbus-exact-head-evidence.py",
        '                or row["elapsed_seconds"] < 0):',
        '                or not math.isfinite(row["elapsed_seconds"])\n                or row["elapsed_seconds"] < 0):')
replace("scripts/authbus-exact-head-evidence.py",
        '    if args.step_timeout <= 0:',
        '    if not math.isfinite(args.step_timeout) or args.step_timeout <= 0:')
