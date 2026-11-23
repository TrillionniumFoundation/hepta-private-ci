"""Replay the original numerical suite against the sealed integrated source."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import numpy as np
import scipy
import torch

from qualification.hcsn_reset_aligned.qualify_common import MODULES
from qualification.hcsn_reset_aligned.test_common_state import TestCommonCandidateState


ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = ROOT / "qualification/hcsn_reset_aligned/COMMON_MANIFEST.json"
INVENTORY = Path(__file__).with_name("MANIFEST.json")
FIELDS = ("active", "upper", "refractory", "events", "discounted_events",
          "discounted_active_time", "discounted_remaining_phase")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def verify_sources(declared):
    actual = {name: digest(ROOT / name) for name in declared}
    if actual != declared:
        raise ValueError("integrated source differs from its frozen inventory")
    return actual


def run(output, label, arguments, timeout):
    with (output / (label + ".stdout")).open("wb") as stdout, (output / (label + ".stderr")).open("wb") as stderr:
        subprocess.run([sys.executable, "-B", *arguments], cwd=ROOT, stdout=stdout,
                       stderr=stderr, timeout=timeout, check=True)


def check_fit(output):
    stdout = (output / "TEST.stdout").read_text().splitlines()
    stderr = (output / "TEST.stderr").read_text()
    if re.findall(r"Ran (\d+) tests", stderr) != ["45"] or "\nOK\n" not in stderr or "skipped=" in stderr:
        raise RuntimeError("the complete original 45-test suite must pass without skips")
    marker = "NATIVE_ALIGNED_EVIDENCE "
    reports = [json.loads(line[len(marker):]) for line in stdout if line.startswith(marker)]
    if len(reports) != 1:
        raise ValueError("expected the original numerical evidence record")
    records = reports[0]["records"]
    fit, = [row for row in records if row["case"] == "synthetic_known_physics_fit"]
    gradcheck, = [row for row in records if row["case"] == "joint_gradcheck"]
    rows = fit["records"]
    if ([row["step"] for row in rows] != list(range(121)) or fit["actual_optimizer_updates"] != 120
            or rows[-1]["relative_mse"] >= 2e-4 or rows[0]["relative_mse"] <= 100 * rows[-1]["relative_mse"]
            or not rows[0]["reset"] < .5 < rows[-1]["reset"] or not gradcheck["passed"]):
        raise ValueError("the original gradient and two-scalar fit requirements failed")
    return rows[0], rows[-1]


def cold_restore(output):
    fixture = TestCommonCandidateState("test_migrated_law_aligned_reset_and_cold_state_obey_dynamic_value")
    fixture.setUp()
    prefix = fixture.model.solve([.07, .137], fixture.active, fixture.content, fixture.phase,
                                 export_state=True, **fixture.controls)
    before = output / "ALIGNED_BEFORE.json.gz"
    after = output / "ALIGNED_AFTER.json.gz"
    before.write_bytes(gzip.compress(prefix["checkpoint"], mtime=0))
    run(output, "RESTORE", ["-m", "qualification.hcsn_reset_aligned.qualify_common",
                            "--restore", str(before), "--output", str(after)], 120)
    actual = json.loads((output / "RESTORE.stdout").read_bytes())
    expected = fixture.model.solve([.07, .137, .417, 1.], fixture.active, fixture.content,
                                   fixture.phase, **fixture.controls)["rows"][-1]
    errors = {name: float(np.max(abs(np.asarray(actual["rows"][-1][name]) - expected[name]))) for name in FIELDS}
    if (not after.is_file() or actual["integration_started_at"] != .137
            or not np.isfinite(list(errors.values())).all() or max(errors.values()) > 4e-9):
        raise ValueError("cold continuation differs from the uninterrupted state")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inventory = json.loads(INVENTORY.read_bytes())
    before = verify_sources(inventory["sources"])
    write(output / "SOURCE_BEFORE.json", before)
    if MODULES != inventory["modules"] or len(set(MODULES)) != 10:
        raise ValueError("original suite roster differs")
    declared_previous = json.loads(PREVIOUS.read_bytes())["sources"]
    differences = sorted(name for name, expected in declared_previous.items() if before.get(name) != expected)
    started = time.perf_counter()
    run(output, "TEST", ["-m", "unittest", *MODULES, "-v"], 600)
    elapsed = time.perf_counter() - started
    initial, final = check_fit(output)
    errors = cold_restore(output)
    after = verify_sources(inventory["sources"])
    write(output / "SOURCE_AFTER.json", after)
    result = dict(status="PASS_BOUNDED_RESEARCH", source_commit=os.environ.get("CANDIDATE_COMMIT"),
                  source_inventory_sha256=digest(INVENTORY), changed_historical_members=differences,
                  tests_passed=45, skips=0, optimizer_updates=120, fit_initial=initial, fit_final=final,
                  loss_goal=2e-4, fit_scope="same-model synthetic reset position and signed mark",
                  cold_restore_errors=errors, cold_restore_started_at=.137,
                  python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                  torch=torch.__version__, test_process_wall_seconds=elapsed,
                  independent_future_tasks=0, complete_c2_replays=0, cell_adoption=False)
    write(output / "RESULT.json", result)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
