"""Reproduce the frozen v2 streaming experiment in a new, isolated repo tree.

No original streaming result is copied. R8 checkpoints and its historical
training-cost receipt are retained because the unchanged audit reads them.
For a fresh checkout, first verify and restore the R8 state_task evidence
bundle using round8_20261031/bundles.py; see the accompanying README.
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
R8 = ROOT / "tools/hcsn/round8_20261031/state_task"
STREAMING = HERE.relative_to(ROOT)
FROZEN = ("filter.py", "audit.py", "protocol.json", "startup.py", "numpy_comparison.py", "AMENDMENT.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def inputs():
    """Check current bytes against the original immutable registrations."""
    prerequisites = [R8 / name for name in ("data.py", "models.py", "replay.py", "protocol.json",
                                            "FREEZE.json", "CONFIRMATION_AMENDMENT.json", "evidence/training.json")]
    restore_hint = (
        "A fresh checkout stores R8 checkpoints/training evidence in volumes. "
        "From the source repo root run:\n"
        "python3 tools/hcsn/round8_20261031/bundles.py verify state_task\n"
        "python3 tools/hcsn/round8_20261031/bundles.py restore state_task\n"
        "See tools/hcsn/round8_20261031/REPRODUCE_ZH.md. "
        "A sparse checkout must also materialize the state_task sources, bundles.py, "
        "bundles/state_task.json and both state_task.tar.gz.part* files. "
        "This reproducer does not unpack or alter the source checkout."
    )
    missing = [str(path.relative_to(ROOT)) for path in prerequisites if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing frozen R8 inputs: " + ", ".join(missing) + "\n" + restore_hint)
    registered = read(HERE / "evidence/v2/REGISTERED.json")
    startup = read(HERE / "evidence/v2/STARTUP_REGISTERED.json")
    numpy = read(HERE / "evidence/v2/NUMPY_REGISTERED.json")
    expected = {HERE / name: sha for name, sha in registered["sources"].items()}
    expected[HERE / "startup.py"] = startup["source_sha256"]
    if startup["filter_sha256"] != registered["sources"]["filter.py"]:
        raise ValueError("startup and quality registrations name different filters")
    for relative, sha in numpy["source_sha256"].items():
        path = ROOT / relative
        if path in expected and expected[path] != sha:
            raise ValueError("NumPy registration conflicts with the quality registration")
        expected[path] = sha
    expected[R8 / "FREEZE.json"] = registered["r8_freeze_sha256"]
    expected[R8 / "CONFIRMATION_AMENDMENT.json"] = registered["r8_amendment_sha256"]
    freeze = read(R8 / "FREEZE.json")["source_and_checkpoint_sha256"]
    dependencies = prerequisites
    checkpoints = sorted((R8 / "evidence/models").glob("*.json"))
    required = {R8 / relative for relative in freeze if relative.startswith("evidence/models/")}
    if set(checkpoints) != required:
        raise ValueError("The complete frozen R8 checkpoint set is required.\n" + restore_hint)
    dependencies += checkpoints
    for path in dependencies:
        relative = str(path.relative_to(R8))
        if relative in freeze:
            expected[path] = freeze[relative]
    for seed, sha in registered["fit_sha256"].items():
        if expected[R8 / f"evidence/models/analytic_filter_{seed}.json"] != sha:
            raise ValueError("R8 fit identity conflicts with the streaming registration")
    for path, sha in expected.items():
        if not path.is_file() or digest(path) != sha:
            raise ValueError(f"frozen source or dependency changed: {path}")
    selected = sorted(set(dependencies + [HERE / name for name in FROZEN]))
    return selected, {
        "registered_quality_sha256": digest(HERE / "evidence/v2/REGISTERED.json"),
        "registered_startup_sha256": digest(HERE / "evidence/v2/STARTUP_REGISTERED.json"),
        "registered_numpy_sha256": digest(HERE / "evidence/v2/NUMPY_REGISTERED.json"),
        "numpy_baseline_commit": numpy["baseline_commit"],
        "frozen_r8_checkpoints": len(checkpoints),
    }


def main(args):
    output = args.output_repo.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output repo must be new: {output}")
    if output.is_relative_to(HERE) or output.is_relative_to(R8):
        raise ValueError("output must be outside the frozen streaming and R8 dependency trees")
    # Preserve a venv's launch path: resolving a python symlink can select the
    # base interpreter and silently lose its installed numerical dependencies.
    interpreter = str(args.python.expanduser().absolute())
    if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError(f"Python executable is unavailable: {interpreter}")
    selected, provenance = inputs()
    # Snapshot existing evidence as well as executable inputs. The child
    # processes must write only in the new tree, including their registrations.
    protected = set(selected) | {p for p in (HERE / "evidence").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    before = {p: digest(p) for p in protected}
    output.mkdir(parents=True, exist_ok=False)
    copied = {}
    for source in selected:
        relative = source.relative_to(ROOT)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if digest(destination) != before[source]:
            raise ValueError(f"copied bytes changed: {relative}")
        copied[str(relative)] = {"sha256": before[source], "bytes": source.stat().st_size}
    commands = ["audit"] if args.checks_only else ["audit", "startup", "numpy_comparison"]
    receipt = {
        "schema": "hepta.r9.streaming.reproduction.v1",
        "source_repo": str(ROOT), "output_repo": str(output),
        "python": interpreter,
        "reproducer_sha256": digest(Path(__file__)), "provenance": provenance,
        "copied_files": copied, "stages": commands,
        "original_streaming_results_copied": False,
        "r8_training_receipt_scope": "Historical cost provenance; no training is rerun or priced as zero.",
        "checks_only_scope": "Unmodified audit.py, including its frozen Torch benchmark; excludes separate startup and current-NumPy cost campaigns.",
    }
    write_new(output / "REPRODUCTION_INPUTS.json", receipt)
    env = os.environ | {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                        "PYTHONPATH": str(output), "PYTHONDONTWRITEBYTECODE": "1"}
    logs = output / "reproduction-logs"
    logs.mkdir()
    results = []
    for stage in commands:
        command = [interpreter, "-m", f"tools.hcsn.round9_20261031.streaming.{stage}"]
        start = time.perf_counter()
        process = subprocess.run(command, cwd=output, env=env, text=True, capture_output=True)
        (logs / f"{stage}.stdout").write_text(process.stdout)
        (logs / f"{stage}.stderr").write_text(process.stderr)
        results.append({"stage": stage, "command": command, "returncode": process.returncode,
                        "wall_seconds": time.perf_counter() - start,
                        "stdout_sha256": digest(logs / f"{stage}.stdout"),
                        "stderr_sha256": digest(logs / f"{stage}.stderr")})
        print(json.dumps(results[-1]), flush=True)
        if process.returncode:
            break
    original_unchanged = all(path.is_file() and digest(path) == sha for path, sha in before.items())
    copied_unchanged = all(digest(output / relative) == row["sha256"] for relative, row in copied.items())
    evidence = output / STREAMING / "evidence/v2"
    generated = {str(path.relative_to(output)): {"sha256": digest(path), "bytes": path.stat().st_size}
                 for path in sorted(evidence.glob("*.json"))}
    passed = len(results) == len(commands) and all(row["returncode"] == 0 for row in results)
    if passed:
        checks = read(evidence / "results.json")["acceptance"]
        passed = all(checks[k] for k in ("numerical_parity", "same_actions", "exact_recovery", "chunking", "malformed_inputs"))
        if not args.checks_only:
            passed = passed and read(evidence / "numpy_comparison.json")["parity_passed"]
    result = {"schema": "hepta.r9.streaming.reproduction-result.v1", "commands": results,
              "original_sources_and_evidence_unchanged": original_unchanged,
              "copied_inputs_unchanged": copied_unchanged, "generated_results": generated,
              "passed": bool(passed and original_unchanged and copied_unchanged),
              "energy_joules": None, "new_scientific_confirmation_samples": 0}
    write_new(output / "REPRODUCTION_RESULT.json", result)
    print(json.dumps({"passed": result["passed"], "output_repo": str(output),
                      "stages_run": [r["stage"] for r in results], "original_unchanged": original_unchanged}), flush=True)
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-repo", type=Path, required=True,
                        help="A new destination repo tree; an existing path is always rejected.")
    parser.add_argument("--checks-only", action="store_true",
                        help="Run the unchanged audit only, without the two additional cost campaigns.")
    parser.add_argument("--python", type=Path, default=Path(sys.executable),
                        help="Python executable with NumPy, SciPy and CPU PyTorch installed; defaults to the current interpreter.")
    args = parser.parse_args()
    raise SystemExit(0 if main(args) else 1)
