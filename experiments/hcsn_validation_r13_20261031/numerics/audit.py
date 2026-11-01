"""Frozen recovery-age and complete-state partition audit; retain every attempt."""

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import scipy

from experiments.hcsn_validation_r13_20261031.numerics.age_pde import AgePDE, digest
from experiments.hcsn_validation_r13_20261031.numerics.age_reference import recovery_reference

HERE = Path(__file__).resolve().parent


class Recorder:
    def __init__(self, out):
        self.out, self.rows = out, []
        self.stream = (out / "cases.jsonl").open("x")

    def add(self, group, passed, *, expected_negative=False, **data):
        row = {"group": group, "passed": bool(passed),
               "expected_negative_control": expected_negative, **data}
        if "checks" in row:
            row["checks"] = {key: bool(value) for key, value in row["checks"].items()}
        self.stream.write(json.dumps(row, allow_nan=False) + "\n")
        self.stream.flush()
        self.rows.append(row)

    def raw(self, relative, document):
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as stream:
            json.dump(document, stream, sort_keys=True, allow_nan=False)
        return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size}


def state_equal(left, right):
    return {"active": np.array_equal(left.active, right.active),
            "refractory_queue": np.array_equal(left.queue, right.queue),
            "count": left.count == right.count, "upper_loss": left.upper_loss == right.upper_loss,
            "clock": left.step == right.step and left.time == right.time,
            "queue_cursor": left.cursor == right.cursor,
            "complete_serialized_state": left.checkpoint() == right.checkpoint()}


def corruption_checks(rec, document, expected_identity, case_index):
    for corruption in rec.protocol["checkpoint_rejection_cases"]:
        altered = copy.deepcopy(document)
        payload = altered["payload"]
        identity = expected_identity
        if corruption == "changed_payload_without_hash_update":
            payload["event_count"] += 0.01
        elif corruption == "missing_recovery_queue_with_recomputed_hash":
            del payload["refractory_queue"]
        elif corruption == "wrong_expected_grid_identity":
            identity = "0" * 64
        elif corruption == "inconsistent_physical_time_with_recomputed_hash":
            payload["physical_time"] += payload["identity"]["dt"] / 3
        elif corruption == "negative_probability_with_recomputed_hash":
            payload["active_probability"][0] = -1.0
        else:
            raise ValueError("Unrecognized registered corruption")
        if corruption != "changed_payload_without_hash_update":
            altered["payload_sha256"] = digest(payload)
        try:
            AgePDE.restore(altered, identity)
            refused, message = False, None
        except ValueError as error:
            refused, message = True, str(error)
        rec.add("checkpoint_refusal", refused, case_index=case_index,
                corruption=corruption, reason=message)


def checkpoint_checks(rec, direct, case_index, grid_index, active_edges, age_edges):
    label = f"case_{case_index}_grid_{grid_index}"
    state = AgePDE(direct.case, direct.h, direct.upper, direct.cfl)
    stops = [math.floor(f * state.total_steps) for f in rec.protocol["partition_step_fractions"]]
    split_records, middle = [], None
    for index, stop in enumerate(stops):
        state.advance_to_time(stop * state.dt)
        relative = f"{label}/checkpoint_{index}.json"
        raw = rec.raw(relative, state.checkpoint())
        loaded = json.loads((rec.out / relative).read_text())
        restored = AgePDE.restore(loaded, direct.identity_hash)
        checks = state_equal(state, restored)
        rec.add("checkpoint_roundtrip", all(checks.values()), case_index=case_index,
                grid_index=grid_index, physical_time=state.time, step=state.step,
                checks=checks, raw=raw)
        split_records.append({"step": stop, "time": state.time, **raw})
        if index == 1:
            middle = (relative, loaded)
        state = restored
    state.advance_to_step(state.total_steps)
    checks = state_equal(direct, state)
    rec.add("complete_state_partition", all(checks.values()), case_index=case_index,
            grid_index=grid_index, checks=checks, checkpoints=split_records,
            final=rec.raw(f"{label}/segmented_final.json", state.checkpoint()))
    try:
        unaligned = AgePDE(direct.case, direct.h, direct.upper, direct.cfl)
        unaligned.advance_to_time(unaligned.dt * 0.5)
        refused, message = False, None
    except ValueError as error:
        refused, message = True, str(error)
    rec.add("unaligned_time_refusal", refused, case_index=case_index, grid_index=grid_index,
            reason=message)

    for mode in rec.protocol["negative_controls"]:
        damaged = AgePDE.restore(middle[1], direct.identity_hash)
        pending_mass = float(damaged.queue.sum())
        damaged.queue.fill(0)
        if mode == "collapse_pending_recovery_to_youngest_age_preserving_mass":
            damaged.queue[(damaged.cursor - 1) % damaged.age_steps] = pending_mass
        damaged.advance_to_step(damaged.total_steps)
        active_l1 = float(np.sum(abs(damaged.active - direct.active)))
        age_l1 = float(np.sum(abs(damaged.age_law() - direct.age_law())))
        count_error = float(abs(damaged.count - direct.count))
        discrepancy = active_l1 + age_l1 + count_error
        rec.add("damaged_recovery_negative", discrepancy <= rec.protocol["gates"]["negative_equivalence_atol"],
                expected_negative=True, case_index=case_index, grid_index=grid_index,
                corruption=mode, checkpoint_pending_mass=pending_mass,
                active_l1=active_l1, recovery_l1=age_l1, count_error=count_error,
                discrepancy=discrepancy,
                final_observables=damaged.observables(active_edges, age_edges),
                raw=rec.raw(f"{label}/negative_{mode}.json", damaged.checkpoint()))
        rec.add("damaged_recovery_detected", discrepancy >= rec.protocol["gates"]["negative_detection_l1_min"],
                case_index=case_index, grid_index=grid_index, corruption=mode,
                discrepancy=discrepancy, required_minimum=rec.protocol["gates"]["negative_detection_l1_min"])

    if grid_index == len(rec.protocol["spacings"]) - 1:
        corruption_checks(rec, middle[1], direct.identity_hash, case_index)
        output = rec.out / label / "fresh_process_final.json"
        command = [sys.executable, "-B", str(HERE / "resume.py"), "--checkpoint",
                   str(rec.out / middle[0]), "--expected-identity", direct.identity_hash,
                   "--target-step", str(direct.total_steps), "--out", str(output)]
        with (rec.out / label / "resume.stdout.log").open("x") as stdout:
            with (rec.out / label / "resume.stderr.log").open("x") as stderr:
                result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=60, check=False)
        restored = AgePDE.restore(json.loads(output.read_text()), direct.identity_hash) if result.returncode == 0 else None
        checks = state_equal(direct, restored) if restored is not None else {"process_success": False}
        rec.add("fresh_process_recovery", result.returncode == 0 and all(checks.values()),
                case_index=case_index, grid_index=grid_index, command=command,
                returncode=result.returncode, checks=checks,
                final_sha256=hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None)


def run_checks(rec, protocol):
    gates = protocol["gates"]
    active_edges = np.asarray(protocol["active_bin_edges"])
    for case_index, case in enumerate(protocol["cases"]):
        age_edges = np.asarray(protocol["relative_age_bin_edges"]) * case["refractory"]
        reference = recovery_reference(case, age_edges, active_edges)
        checks = {"upstream_moments": max(abs(v) for v in reference["upstream_moment_difference"]) <= gates["reference_crosscheck_atol"],
                  "age_bins_mass": abs(sum(reference["age_bins"]) - reference["age_moments"][0]) <= gates["reference_crosscheck_atol"],
                  "continuous_mass": abs(reference["continuous_mass"] - 1) <= gates["reference_crosscheck_atol"]}
        rec.add("independent_age_reference", all(checks.values()), case_index=case_index,
                case=case, checks=checks, reference=reference)
        previous_error = None
        for grid_index, spacing in enumerate(protocol["spacings"]):
            state = AgePDE(case, spacing, protocol["upper"], protocol["maximum_diffusive_cfl"])
            state.advance_to_step(state.total_steps)
            measured = state.observables(active_edges, age_edges)
            active_l1 = float(np.sum(abs(np.asarray(measured["active_bins"]) - reference["active_bins"])))
            age_l1 = float(np.sum(abs(np.asarray(measured["age_bins"]) - reference["age_bins"])))
            normalized_moments = abs(np.asarray(measured["age_moments"]) - reference["age_moments"]) / case["refractory"] ** np.arange(3)
            count_error = abs(measured["event_count"] - reference["event_count"])
            metric = active_l1 + age_l1 + float(normalized_moments.max()) + count_error
            checks = {"mass": abs(measured["accounted_mass"] - 1) <= gates["mass_atol"],
                      "positive": measured["minimum_probability"] >= gates["minimum_probability"],
                      "upper_loss": measured["upper_loss"] <= gates["upper_loss_max"],
                      "refinement": previous_error is None or metric <= gates["refinement_factor"] * previous_error}
            if grid_index == len(protocol["spacings"]) - 1:
                checks.update(active_bins=active_l1 <= gates["final_active_bins_l1"],
                              age_bins=age_l1 <= gates["final_age_bins_l1"],
                              age_moments=float(normalized_moments.max()) <= gates["final_normalized_age_moment_atol"],
                              event_count=count_error <= gates["final_count_atol"])
            rec.add("complete_age_successor_pde", all(checks.values()), case_index=case_index,
                    grid_index=grid_index, case=case, spacing=spacing, grid=state.identity,
                    checks=checks, observables=measured, active_bins_l1=active_l1,
                    age_bins_l1=age_l1, normalized_age_moment_errors=normalized_moments.tolist(),
                    count_error=count_error, refinement_metric=metric,
                    previous_refinement_metric=previous_error,
                    raw=rec.raw(f"case_{case_index}_grid_{grid_index}/direct_final.json", state.checkpoint()))
            previous_error = metric
            checkpoint_checks(rec, state, case_index, grid_index, active_edges, age_edges)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=("development", "formal"), default="development")
    parser.add_argument("--frozen-commit", default="")
    args = parser.parse_args()
    if args.stage == "formal" and (len(args.frozen_commit) != 40 or any(c not in "0123456789abcdef" for c in args.frozen_commit)):
        parser.error("Formal run requires the actual pre-execution source commit")
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    paths = [HERE / "PROTOCOL.json"] + sorted(HERE.glob("*.py"))
    paths += [ROOT / "experiments/hcsn_validation_r12_20261031/numerics/dynamics.py",
              ROOT / "experiments/hcsn_regeneration_content_20261031/renewal.py"]
    sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    freeze = {"stage": args.stage, "frozen_commit": args.frozen_commit or None,
              "source_sha256": sources,
              "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "threads": {name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}
    (args.out / "FREEZE.json").write_text(json.dumps(freeze, indent=2) + "\n")
    (args.out / "sources").mkdir()
    for path in paths:
        shutil.copyfile(path, args.out / "sources" / str(path.relative_to(ROOT)).replace("/", "__"))
    cpu, wall = time.process_time(), time.perf_counter()
    rec = Recorder(args.out)
    rec.protocol = protocol
    try:
        run_checks(rec, protocol)
    except Exception as error:
        (args.out / "exception.txt").write_text(traceback.format_exc())
        rec.add("execution_exception", False, error=repr(error))
    rec.stream.close()
    unexpected = [row for row in rec.rows if not row["passed"] and not row["expected_negative_control"]]
    groups = {}
    for row in rec.rows:
        group = groups.setdefault(row["group"], {"rows": 0, "passed": 0})
        group["rows"] += 1
        group["passed"] += row["passed"]
    expected_rows = 2 + 6 * (1 + 4 + 1 + 1 + 4) + 2 * (5 + 1)
    summary = {"schema": "hcsn.r13.age-checkpoint.summary.v1", "stage": args.stage,
               "success": not unexpected and len(rec.rows) == expected_rows,
               "frozen_commit": args.frozen_commit or None, "rows": len(rec.rows),
               "expected_rows": expected_rows, "groups": groups,
               "unexpected_failed_rows": len(unexpected),
               "retained_negative_control_failures": sum(not row["passed"] and row["expected_negative_control"] for row in rec.rows),
               "self_cpu_seconds_excluding_imports": time.process_time() - cpu,
               "waited_descendant_cpu_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
               "wall_seconds_excluding_imports": time.perf_counter() - wall,
               "process_metering": "See launcher wait4 receipt; self and waited-descendant counters must not be added again to that inclusive receipt",
               "not_established": protocol["not_established"]}
    (args.out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "FAILURES.json").write_text(json.dumps([r for r in rec.rows if not r["passed"]], indent=2) + "\n")
    print(json.dumps(summary))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
