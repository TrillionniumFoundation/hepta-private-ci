#!/usr/bin/env python3
"""Verify the public delivery; optionally run the retained numerical verifiers.

This does not fetch private inputs, launch model inference, or qualify efficacy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true",
                        help="Run bundled numerical checks; needs NumPy and SciPy.")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    assert manifest["schema"] == "hepta-wsp-public-delivery-v1"
    records = manifest["files"]
    for name, expected in records.items():
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts, name
        path = ROOT / relative
        assert path.is_file() and not path.is_symlink(), name
        data = path.read_bytes()
        assert len(data) == expected["bytes"], name
        assert hashlib.sha256(data).hexdigest() == expected["sha256"], name
    actual = {
        str(path.relative_to(ROOT)) for path in ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and path.suffix != ".pyc" and path != ROOT / "MANIFEST.json"
    }
    assert actual == set(records), {
        "unlisted": sorted(actual - set(records)),
        "missing": sorted(set(records) - actual),
    }
    checks = []
    if args.deep:
        commands = [
            [sys.executable, str(ROOT / "joint/verify_delivery.py")],
            [sys.executable, str(ROOT / "joint/verify_truth_tables.py")],
            [sys.executable, str(ROOT / "exploratory_belief/verify_followup.py"),
             "--study-root", str(ROOT / "joint")],
            [sys.executable, str(ROOT / "ndu_value_grid/verify_value_grid.py"),
             "--study-root", str(ROOT / "joint"),
             "--old-heads", str(ROOT / "exploratory_belief/OLD_CONTINUATION_HEADS.json.gz")],
            [sys.executable, str(ROOT / "analytic_belief/verify_analytic_belief.py"),
             "--study-root", str(ROOT / "joint"),
             "--old-heads", str(ROOT / "exploratory_belief/OLD_CONTINUATION_HEADS.json.gz")],
            [sys.executable, str(ROOT / "analytic_belief/verify_seed_overlap.py"),
             "--study-root", str(ROOT / "joint")],
            [sys.executable, str(ROOT / "analytic_belief_compile/verify_belief_compile_records.py"),
             "--study-root", str(ROOT / "joint"),
             "--analytic-root", str(ROOT / "analytic_belief")],
            [sys.executable, str(ROOT / "analytic_belief_compile/verify_belief_solver_records.py"),
             "--study-root", str(ROOT / "joint"),
             "--analytic-root", str(ROOT / "analytic_belief")],
            [sys.executable, "-m", "unittest", "discover", "-s",
             str(ROOT / "pocket4"), "-p", "test_finite_readout_capacity_certificate.py"],
        ]
        for command in commands:
            completed = subprocess.run(command, cwd=ROOT, check=True,
                                       text=True, capture_output=True)
            checks.append({"script": command[1:], "exit_code": completed.returncode,
                           "stdout": completed.stdout, "stderr": completed.stderr})
    print(json.dumps({
        "verified_files": len(records), "numerical_checks": checks,
        "private_trader_inputs_included": False,
        "new_efficacy_run_performed": False,
        "scope": "delivery integrity and optional retained public evidence checks",
    }, indent=2))


if __name__ == "__main__":
    main()
