"""Retain one exact-source run, including portable original cold-state bytes."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import scipy

from .test_model import fixture, initial
from .test_state import CONTROLS, FIELDS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    out = args.output
    if args.restore is not None:
        result = fixture().solve([0.6, 1.0], checkpoint=gzip.decompress(args.restore.read_bytes()),
                                 export_state=True, **CONTROLS)
        out.write_bytes(gzip.compress(result.pop("checkpoint"), mtime=0))
        print(json.dumps(result, default=lambda a: a.tolist(), allow_nan=False))
        return
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    paths = sorted(Path(__file__).parent.glob("*.py")) + [
        root / "qualification/hcsn_boundary_audit/spatial_generator.py",
        root / "qualification/hcsn_boundary_audit/refractory_transport.py"]
    def identities():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = identities()
    command = [sys.executable, "-B", "-m", "unittest", "qualification.hcsn_joint_dde.test_model",
               "qualification.hcsn_joint_dde.test_graded", "qualification.hcsn_joint_dde.test_migration_binding",
               "qualification.hcsn_joint_dde.test_state", "-v"]
    tests = subprocess.run(command, capture_output=True, timeout=120)
    (out / "TEST.stdout").write_bytes(tests.stdout)
    (out / "TEST.stderr").write_bytes(tests.stderr)
    if tests.returncode or b"Ran 28 tests" not in tests.stderr or b"skipped" in tests.stderr:
        raise RuntimeError("all 28 declared tests must run and pass without skips")
    model = fixture()
    p, content = initial(model)
    prefix = model.solve([0.173, 0.417], p, content, export_state=True, **CONTROLS)
    before_path, after_path = out / "BEFORE.json.gz", out / "AFTER.json.gz"
    before_path.write_bytes(gzip.compress(prefix["checkpoint"], mtime=0))
    worker = subprocess.run([sys.executable, "-B", "-m", "qualification.hcsn_joint_dde.qualify_state",
                             "--restore", str(before_path), "--output", str(after_path)],
                            capture_output=True, timeout=60)
    (out / "RESTORE.stdout").write_bytes(worker.stdout)
    (out / "RESTORE.stderr").write_bytes(worker.stderr)
    worker.check_returncode()
    actual = json.loads(worker.stdout)
    reference = model.solve([0.173, 0.417, 0.6, 1.0], p, content, **CONTROLS)
    errors = {field: float(np.max(np.abs(np.asarray(actual["rows"][-1][field]) - reference["rows"][-1][field])))
              for field in FIELDS}
    after = identities()
    if before != after or max(errors.values()) > 3e-9 or actual["integration_started_at"] != 0.417:
        raise RuntimeError("source mutation or actual history continuation mismatch")
    result = {"status": "PASS_RESEARCH_ONLY", "source_before": before, "source_after": after,
              "tests_passed": 28, "skipped": 0, "cold_process_restore": True,
              "resume_clock": 0.417, "maximum_absolute_errors": errors, "controls": CONTROLS,
              "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
              "checkpoints": {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in (before_path, after_path)},
              "optimizer_calls": 0, "complete_c2_replays": 0, "cell_adoption": False}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
