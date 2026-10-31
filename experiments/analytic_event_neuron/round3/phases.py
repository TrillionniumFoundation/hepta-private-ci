"""Frozen entry points for feedback, runtime and calibration confirmation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from ..run import digest, write_json
from . import freeze


def execute(run_dir, phase):
    root = Path(run_dir)
    frozen = freeze.verify(root)
    protocol = json.loads((freeze.PROJECT / "PROTOCOL.json").read_text())
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    index_path = root / (phase.upper() + "_INDEX.json")
    index = json.loads(index_path.read_text()) if index_path.exists() else {
        "schema": "hepta.analytic-event.round3.phase-index.v1", "phase": phase,
        "source_commit": frozen["source_commit"], "created_utc": datetime.now(timezone.utc).isoformat(),
        "scopes": [], "complete": False}
    if index["source_commit"] != frozen["source_commit"] or index["phase"] != phase:
        raise ValueError("Mismatched phase index")
    binary, receipt = root / "native" / "analytic_event", root / "native" / "BUILD_RECEIPT.json"
    if phase == "calibration":
        from .calibration_study import evaluate_study
        if index["scopes"]:
            raise ValueError("Calibration is a single immutable confirmation run")
        result = evaluate_study(root / "calibration_prepared", protocol["calibration"],
                                freeze_path=root / "FREEZE.json", output=root / "calibration_confirmation")
        index["scopes"].append({"result": "calibration_confirmation/RESULTS.json",
                                "sha256": digest(root / "calibration_confirmation" / "RESULTS.json")})
    else:
        from .feedback_study import confirm_seed
        from .feedback_audit import audit_seed
        from .runtime_feedback_study import qualify_seed
        registration = protocol["feedback" if phase == "feedback" else "runtime"]
        recorded = [entry["seed"] for entry in index["scopes"]]
        if len(recorded) != len(set(recorded)) or not set(recorded).issubset(registration["seeds"]):
            raise ValueError("Duplicated or unregistered phase seed")
        for seed in registration["seeds"]:
            freeze.verify(root)
            output = root / (phase + "_confirmation") / f"seed_{seed}"
            previous = [entry for entry in index["scopes"] if entry["seed"] == seed]
            if previous:
                for path, sha in previous[0]["files_sha256"].items():
                    if digest(root / path) != sha:
                        raise ValueError("Completed phase bytes changed: " + path)
                continue
            if output.exists():
                raise ValueError("Unindexed phase attempt retained: " + str(output))
            prepared = root / "feedback_prepared" / f"seed_{seed}"
            model_key = str((prepared / "MODELS.json").relative_to(root))
            expected = frozen["artifacts_sha256"][model_key]
            before = time.perf_counter_ns()
            if phase == "feedback":
                result = confirm_seed(seed, prepared, output, binary, receipt, expected,
                    n=registration["confirmation_rows"], data_offset=registration["data_offset"])
                reviewed = audit_seed(output, prepared, binary, receipt)
                write_json(output / "AUDIT.json", reviewed)
                if not reviewed["passed"]:
                    raise ValueError("Feedback replay audit failed")
            elif phase == "runtime":
                result = qualify_seed(seed, prepared, output, binary, receipt, expected,
                    n=registration["unique_histories_per_seed"], data_offset=registration["data_offset"])
                if not result["passed"]:
                    raise ValueError("Runtime qualification failed")
            else:
                raise ValueError("Unknown confirmation phase")
            freeze.verify(root)
            index["scopes"].append({"seed": seed, "wall_ns": time.perf_counter_ns() - before,
                "files_sha256": {str(p.relative_to(root)): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}})
            write_json(index_path, index)
            print(json.dumps({"phase": phase, "seed": seed, "completed": True}), flush=True)
    freeze.verify(root)
    index.update(complete=True, wall_ns=time.perf_counter_ns() - started,
                 parent_cpu_ns=time.process_time_ns() - cpu)
    write_json(index_path, index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("feedback", "runtime", "calibration"))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    execute(args.run_dir, args.phase)
