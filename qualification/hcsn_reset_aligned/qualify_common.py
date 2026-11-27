"""One source execution of migration, gradients, healthy fit and cold state."""

import argparse
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time

import numpy as np
import scipy

from qualification.hcsn_joint_dde.model import JointModel
from .mesh import ResetAlignedSpatial
from .test_common_state import TestCommonCandidateState


MODULES = [
    "qualification.hcsn_joint_dde.test_model",
    "qualification.hcsn_joint_dde.test_graded",
    "qualification.hcsn_joint_dde.test_migration_binding",
    "qualification.hcsn_joint_dde.test_state",
    "qualification.hcsn_reset_aligned.test_model",
    "qualification.hcsn_reset_aligned.test_torch",
    "qualification.hcsn_reset_aligned.test_perpetual",
    "qualification.hcsn_reset_aligned.test_first_hit",
    "qualification.hcsn_reset_aligned.test_readouts_torch",
    "qualification.hcsn_reset_aligned.test_common_state",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.restore is not None:
        raw = gzip.decompress(args.restore.read_bytes())
        physics = json.loads(raw)["payload"]["binding"]["physics"].copy()
        spatial = ResetAlignedSpatial(**physics.pop("spatial"))
        model = JointModel(spatial=spatial, **physics)
        result = model.solve([.417, 1.], checkpoint=raw, export_state=True,
                             rtol=2e-11, atol=2e-13, max_step=.01)
        args.output.write_bytes(gzip.compress(result.pop("checkpoint"), mtime=0))
        print(json.dumps(result, default=lambda x: x.tolist(), allow_nan=False))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    source = sorted((root / "qualification/hcsn_joint_dde").glob("*.py"))
    source += sorted(Path(__file__).parent.glob("*.py"))
    source += [root / "qualification/hcsn_boundary_audit" / name for name in
               ("spatial_generator.py", "refractory_transport.py")]
    def identities():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source}
    before = identities()
    (args.output / "SOURCE_BEFORE.json").write_text(json.dumps(before, indent=2)+"\n")
    declared = json.loads((Path(__file__).parent / "COMMON_MANIFEST.json").read_text())["sources"]
    if before != declared:
        raise RuntimeError("candidate source differs from its frozen common manifest")
    command = [sys.executable, "-B", "-m", "unittest", *MODULES, "-v"]
    started, initial_usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    with (args.output / "TEST.stdout").open("wb") as stdout, (args.output / "TEST.stderr").open("wb") as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=600)
    elapsed = time.perf_counter()-started
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    after = identities()
    (args.output / "SOURCE_AFTER.json").write_text(json.dumps(after, indent=2)+"\n")
    stdout, stderr = [(args.output / name).read_text() for name in ("TEST.stdout", "TEST.stderr")]
    counts = re.findall(r"Ran (\d+) tests", stderr)
    if completed.returncode or counts != ["45"] or "skipped=" in stderr or before != after:
        raise RuntimeError("common candidate requires 45 unskipped checks on unchanged source")
    line = next(line for line in stdout.splitlines() if line.startswith("NATIVE_ALIGNED_EVIDENCE "))
    native = json.loads(line.split(" ", 1)[1])
    fit, = [record for record in native["records"] if record["case"] == "synthetic_known_physics_fit"]
    initial_fit, final_fit = fit["records"][0], fit["records"][-1]
    if (fit["actual_optimizer_updates"] != 120 or final_fit["relative_mse"] >= 2e-4
            or initial_fit["reset"] >= .5 or final_fit["reset"] <= .5):
        raise RuntimeError("declared optimizer adequacy target failed")
    fixture = TestCommonCandidateState("test_migrated_law_aligned_reset_and_cold_state_obey_dynamic_value")
    fixture.setUp()
    prefix = fixture.model.solve([.07, .137], fixture.active, fixture.content, fixture.phase,
                                  export_state=True, **fixture.controls)
    before_file, after_file = args.output / "ALIGNED_BEFORE.json.gz", args.output / "ALIGNED_AFTER.json.gz"
    before_file.write_bytes(gzip.compress(prefix["checkpoint"], mtime=0))
    restore_started = time.perf_counter()
    restore = subprocess.run([sys.executable, "-B", "-m", "qualification.hcsn_reset_aligned.qualify_common",
                              "--restore", str(before_file), "--output", str(after_file)],
                             capture_output=True, timeout=120)
    restore_elapsed = time.perf_counter()-restore_started
    (args.output / "RESTORE.stdout").write_bytes(restore.stdout)
    (args.output / "RESTORE.stderr").write_bytes(restore.stderr)
    restore.check_returncode()
    actual = json.loads(restore.stdout)
    expected = fixture.model.solve([.07, .137, .417, 1.], fixture.active, fixture.content,
                                    fixture.phase, **fixture.controls)["rows"][-1]
    fields = ("active", "upper", "refractory", "events", "discounted_events",
              "discounted_active_time", "discounted_remaining_phase")
    errors = {name: float(np.max(abs(np.asarray(actual["rows"][-1][name])-expected[name]))) for name in fields}
    if max(errors.values()) > 4e-9 or actual["integration_started_at"] != .137 or before != identities():
        raise RuntimeError("common cold-state continuation or source guard failed")
    report = {"status": "PASS_BOUNDED_RESEARCH", "source": before, "tests_passed": 45,
              "skips": 0, "optimizer_updates": 120, "fit_initial": initial_fit, "fit_final": final_fit,
              "loss_goal": 2e-4, "fit_scope": "same-model two-scalar synthetic diagnostic",
              "cold_restore_started_at": .137, "cold_restore_errors": errors,
              "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
              "torch": version("torch"),
              "cold_restore_process_wall_seconds_including_imports": restore_elapsed,
              "test_process_cost": {"wall_seconds": elapsed,
                  "user_cpu_seconds": usage.ru_utime-initial_usage.ru_utime,
                  "system_cpu_seconds": usage.ru_stime-initial_usage.ru_stime,
                  "children_max_rss_kib_linux": usage.ru_maxrss},
              "independent_future_tasks": 0, "complete_c2_replays": 0, "cell_adoption": False}
    (args.output / "RESULT.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
