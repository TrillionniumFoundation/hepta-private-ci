"""Replay the frozen value experiment in a new tree with its exact source set.

The original experiment registered a minimal source tree. A full checkout has
additional round7 Python modules and therefore fails its unchanged glob check.
This helper copies only registered dependencies, verifies every copied byte,
and runs the unchanged verifier, confirmation and audit with fresh outputs.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
VALUE = Path("tools/hcsn/round9_20261031/value")
EVIDENCE = VALUE / "evidence"
OLD = Path("tools/hcsn/round8_20261031/value_calibration/evidence/prepared02")
MANIFEST_SHA256 = "c815af810b722a7d77a01233708dce50b37464ad76f1ce81a3010093ad92997a"
HEAD_NAMES = {f"{mode}_{seed}.json" for mode in ("first_passage", "clocked", "direct") for seed in range(11, 16)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def inputs():
    manifest_path = ROOT / VALUE / "DELIVERY_MANIFEST.json"
    if digest(manifest_path) != MANIFEST_SHA256:
        raise ValueError("The frozen value delivery manifest changed.")
    manifest = read(manifest_path)
    expected = {str(VALUE / "DELIVERY_MANIFEST.json"): MANIFEST_SHA256}

    def add(relative, sha):
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe registered relative path: {relative}")
        relative = str(path)
        if relative in expected and expected[relative] != sha:
            raise ValueError(f"Conflicting frozen identities: {relative}")
        expected[relative] = sha

    for name in ("REGISTERED.json", "AMENDMENT.json", "PROTOCOL.json", "HEADS_FROZEN.json", "TRAIN.json"):
        relative = str(Path("evidence") / name)
        add(VALUE / relative, manifest["files"][relative]["sha256"])
    add(VALUE / "audit/readback.py", manifest["files"]["audit/readback.py"]["sha256"])
    for relative, sha in expected.items():
        if digest(ROOT / relative) != sha:
            raise ValueError(f"Frozen registration changed: {relative}")
    registered = read(ROOT / EVIDENCE / "REGISTERED.json")
    amendment = read(ROOT / EVIDENCE / "AMENDMENT.json")
    frozen = read(ROOT / EVIDENCE / "HEADS_FROZEN.json")
    registration_sha = expected[str(EVIDENCE / "REGISTERED.json")]
    if amendment["registration_sha256"] != registration_sha or frozen["registration_sha256"] != registration_sha:
        raise ValueError("Registration linkage changed.")
    if set(frozen["heads"]) != HEAD_NAMES or set(registered["baseline_heads"]) != HEAD_NAMES:
        raise ValueError("Exactly 15 new and 15 baseline heads are required.")
    add(EVIDENCE / "PROTOCOL.json", registered["protocol_sha256"])
    add(EVIDENCE / "TRAIN.json", frozen["train_sha256"])
    add(OLD / "FREEZE.json", registered["r8_freeze_sha256"])
    for relative, sha in amendment["sources"].items():
        add(relative, sha)
    for relative, sha in registered["checkpoints"].items():
        add(relative, sha)
    for name, sha in registered["baseline_heads"].items():
        add(OLD / name, sha)
    for name, sha in frozen["heads"].items():
        add(EVIDENCE / "heads" / name, sha)
    hint = (
        "From the source checkout run bundles.py verify value_calibration and "
        "bundles.py restore value_calibration under tools/hcsn/round8_20261031; "
        "also materialize the registered round7 sources and fits_primary checkpoints."
    )
    for relative, sha in expected.items():
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"Missing frozen input: {relative}. {hint}")
        if digest(source) != sha:
            raise ValueError(f"Frozen input changed: {relative}")
    return expected


VERIFY = """
import json
import platform
import numpy as np
import scipy
from tools.hcsn.round9_20261031.value import run
from tools.hcsn.round9_20261031.value.head import CostFactoredHead
from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead
design = run.verify_registration()
frozen = json.loads((run.EVIDENCE / 'HEADS_FROZEN.json').read_text())
assert frozen['registration_sha256'] == run.digest(run.EVIDENCE / 'REGISTERED.json')
assert frozen['train_sha256'] == run.digest(run.EVIDENCE / 'TRAIN.json')
loaded = 0
for name, sha in frozen['heads'].items():
    assert run.digest(run.EVIDENCE / 'heads' / name) == sha
    for cls, path in ((CostFactoredHead, run.EVIDENCE / 'heads' / name), (CalibratedHead, run.OLD / name)):
        head = cls.load(path)
        assert all(np.isfinite(value).all() for value in head.record().values())
        assert (head.scale > 0).all()
        assert head.predict(head.center, np.asarray(0.)).shape == (4,)
        loaded += 1
assert loaded == 30
print(json.dumps({'verify_registration': True, 'loaded_new_heads': 15, 'loaded_baseline_heads': 15,
                  'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__,
                  'new_confirmation_samples': 0}))
"""

AUDIT = """
from pathlib import Path
from tools.hcsn.round9_20261031.value.audit import readback
readback.HERE = Path.cwd() / 'audit'
readback.HERE.mkdir(exist_ok=False)
readback.CONFIRMATION = Path.cwd() / 'confirmation'
readback.run()
"""


def main(args):
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise ValueError("--output must be a nonexistent directory outside the source checkout.")
    interpreter = str(args.python.expanduser().absolute())  # Keep the virtualenv launch path.
    if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("--python must name an existing executable; no output has been created.")
    expected = inputs()
    protected = {ROOT / name for name in expected}
    protected |= {p for p in (ROOT / VALUE).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    before = {p: digest(p) for p in protected}
    output.mkdir(parents=True, exist_ok=False)
    for relative, sha in expected.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
        if digest(destination) != sha:
            raise ValueError(f"Copied bytes changed: {relative}")
    write_new(output / "REPRODUCTION_INPUTS.json", {
        "schema": "hepta.r9.value.reproduction-inputs.v1", "source_repo": str(ROOT),
        "output_repo": str(output), "python": interpreter, "reproducer_sha256": digest(Path(__file__)),
        "copied_sha256": expected, "minimal_source_tree_required_by_original_registration": True,
        "original_confirmation_results_copied": False, "original_training_receipt_retained": True,
        "training_rerun": False, "prepare_only": args.prepare_only,
    })
    stages = [("verify", [interpreter, "-c", VERIFY])]
    if not args.prepare_only:
        stages += [("confirm", [interpreter, "-m", "tools.hcsn.round9_20261031.value.run", "confirm",
                               "--output", str(output / "confirmation")]), ("audit", [interpreter, "-c", AUDIT])]
    logs = output / "reproduction-logs"
    logs.mkdir()
    env = os.environ | {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                        "PYTHONPATH": str(output), "PYTHONDONTWRITEBYTECODE": "1"}
    results = []
    for stage, command in stages:
        started = time.perf_counter()
        process = subprocess.run(command, cwd=output, env=env, text=True, capture_output=True)
        (logs / f"{stage}.stdout").write_text(process.stdout)
        (logs / f"{stage}.stderr").write_text(process.stderr)
        results.append({"stage": stage, "returncode": process.returncode,
                        "wall_seconds": time.perf_counter() - started,
                        "stdout_sha256": digest(logs / f"{stage}.stdout"),
                        "stderr_sha256": digest(logs / f"{stage}.stderr")})
        print(json.dumps(results[-1]), flush=True)
        if process.returncode:
            break
    original_unchanged = all(path.is_file() and digest(path) == sha for path, sha in before.items())
    copied_unchanged = all(digest(output / relative) == sha for relative, sha in expected.items())
    passed = len(results) == len(stages) and all(row["returncode"] == 0 for row in results)
    result = {"schema": "hepta.r9.value.reproduction-result.v1", "stages": results,
              "original_sources_and_evidence_unchanged": original_unchanged,
              "copied_inputs_unchanged": copied_unchanged, "prepare_only": args.prepare_only,
              "passed": passed and original_unchanged and copied_unchanged,
              "scope": "Integrity/preparation only" if args.prepare_only else "Replay of the original seeds; not a fresh scientific confirmation",
              "energy_joules": None}
    write_new(output / "REPRODUCTION_RESULT.json", result)
    print(json.dumps({"passed": result["passed"], "output": str(output)}), flush=True)
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New isolated repo/output directory; existing paths are rejected.")
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Python executable with NumPy and SciPy installed.")
    parser.add_argument("--prepare-only", action="store_true", help="Verify exact registrations and load all 30 heads; do not replay episodes.")
    raise SystemExit(0 if main(parser.parse_args()) else 1)
