"""Publish and enforce the attempt terminal without changing its result."""

import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "RUN_OUTPUT"


def _read(name):
    return json.loads((OUTPUT / name).read_text())


def publish():
    run = _read("RUN.json")
    audit = _read("AUDIT.json")
    exit_status = int((OUTPUT / "EXECUTION_EXIT_STATUS").read_text().strip())
    passed = (
        exit_status == 0
        and run["result"] == "EXACT"
        and audit["status"] == "EXACT"
        and audit["coordinates_compared"] == 68105
        and audit["mismatches"] == 0
    )
    terminal = {
        "identity": "hcsn-n256-authentic-boundary-attempt002-20261121-c06d",
        "status": "PASS_BOUNDARY_ASSEMBLY_ONLY" if passed else "RED",
        "execution_exit_status": exit_status,
        "run_result": run["result"],
        "audit_status": audit["status"],
        "coordinates_compared": audit.get("coordinates_compared"),
        "mismatches": audit.get("mismatches"),
        "boundary_assembly_qualified": passed,
        "dynamic_propagation_qualified": False,
        "sparse_kernel_qualified": False,
        "c2_full_replay_completed_fits": 0,
        "hpca_update": "NoUpdate",
        "production_adoption": False,
        "all_closed": False,
    }
    (OUTPUT / "TERMINAL.json").write_text(
        json.dumps(terminal, allow_nan=False, indent=2, sort_keys=True) + "\n"
    )
    return terminal


def enforce():
    terminal = _read("TERMINAL.json")
    return 0 if terminal["status"] == "PASS_BOUNDARY_ASSEMBLY_ONLY" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--enforce"]:
        raise SystemExit(enforce())
    if sys.argv[1:]:
        raise SystemExit("unexpected arguments")
    print(json.dumps(publish(), sort_keys=True))
