"""Compose two retained nonsmooth-surrogate rows; no model or transport work.

The original smooth scope stays FAILED. This checks local sufficient-equation
algebra against the already accepted central trial's recorded step. Agreement
within tolerance does not transfer that candidate's actual-reduction gate to a
new aggregate candidate; no aggregate candidate is evaluated or materialized.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import sys
import time
import traceback
from types import SimpleNamespace

INPUT_PINS = {
    "failed_result": "15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105",
    "accepted_result": "8fff2a2525bb5ba411532e28fee28d549c491372add6feb2b58a9399d89a446e",
    "surrogate_step": "d71efb51f3799669aa41cdc0c4c681712b45949c2fd9d635cf52215f28fc8254",
    "trial_evidence": "2764a0d9cf67d34760f31f5779653bc030bba3f679f99a82e0601323ba21b6e4",
}
DEPENDENCY_PINS = {
    "peer_equations.py": "d1de9fdf0dc15ae3e14572cfca4f405946b330726cf8442b609013f46c72a8fd",
    "profile_io.py": "3c6d4d0d6ad478460e3b422bfb22220406080c48a5ef1d33e2cb3479e43e738f",
}
SURROGATE_RULE = "retained midpoint primitive-VJP surrogate; original fixed FD FAILED; no classical or Clarke Jacobian certification"
TOLERANCES = {"delta_atol": 1e-10, "delta_rtol": 1e-8,
              "statistics_atol": 1e-12, "statistics_rtol": 1e-12}
MAX_BYTES = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pinned(path, expected):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == expected,
            "bounded pinned bytes differ: " + str(path))
    return raw


def execute(args, result):
    pinned(__file__, args.source_sha256)
    peer_root, profile_root = Path(args.peer_module_dir).resolve(), Path(args.profile_module_dir).resolve()
    pinned(peer_root / "peer_equations.py", DEPENDENCY_PINS["peer_equations.py"])
    pinned(profile_root / "profile_io.py", DEPENDENCY_PINS["profile_io.py"])
    raw = {name: pinned(getattr(args, name), expected) for name, expected in INPUT_PINS.items()}
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    sys.path.insert(0, str(peer_root))
    sys.path.insert(0, str(profile_root))
    import numpy as np
    import profile_io
    import peer_equations as peer
    require(Path(peer.__file__).resolve() == peer_root / "peer_equations.py"
            and Path(profile_io.__file__).resolve() == profile_root / "profile_io.py", "wrong dependency import")
    require("torch" not in sys.modules and not any(name == "qualification" or name.startswith("qualification.")
                for name in sys.modules), "model imports are outside this local algebra scope")
    failed, accepted, proposal, evidence = (profile_io.parse(raw[name]) for name in INPUT_PINS)
    require(failed["schema"] == "hepta.smallhcsn.sensitivity-engineering-result.v1"
            and failed["status"] == "FAILED" and failed["finite_difference"]["passed"] is False,
            "original smooth failure must remain a failure")
    require(accepted["schema"] == "hepta.smallhcsn.nonsmooth-single-trial-result.v1"
            and evidence["schema"] == "hepta.smallhcsn.nonsmooth-single-trial-evidence.v1"
            and proposal["schema"] == "hepta.smallhcsn.nonsmooth-surrogate-proposal.v1"
            and accepted["status"] == evidence["status"] == "COMPLETED_SINGLE_TRIAL"
            and accepted["decision"] == evidence["decision"] == "ACCEPTED"
            and accepted["candidate_exported"] is True and accepted["candidate_adopted"] is False,
            "completed accepted nonsmooth trial and existing research export required")
    for retained in (accepted, proposal, evidence):
        require(retained["original_failed_result_sha256"] == INPUT_PINS["failed_result"]
                and retained["original_smooth_status"] == "FAILED"
                and retained["classical_jacobian_admitted"] is False
                and retained["verified_semismooth_method"] is False, "receipt improperly upgrades smooth qualification")
    require(accepted["surrogate_proposal"] == evidence["surrogate_proposal"]
            and accepted["surrogate_proposal"]["sha256"] == INPUT_PINS["surrogate_step"]
            and accepted["surrogate_proposal"]["bytes"] == len(raw["surrogate_step"])
            and accepted["trial_evidence"]["sha256"] == INPUT_PINS["trial_evidence"]
            and accepted["trial_evidence"]["bytes"] == len(raw["trial_evidence"])
            and accepted["protocol_sha256"] == proposal["protocol_sha256"] == evidence["protocol_sha256"]
            and accepted["gate"] == evidence["gate"] and accepted["parent"] == evidence["parent"] == failed["parent"],
            "accepted trial, proposal, parent or actual gate identity differs")
    gate = accepted["gate"]
    require(gate["pred"] > gate["tau"] and gate["ared"] > gate["tau"] and gate["ratio"] >= .1
            and accepted["parent_restored"] is True
            and accepted["parent_state_after_sha256"] == failed["parent"]["state_sha256"],
            "retained actual-reduction or parent-restoration gate did not pass")
    runtime = evidence["runtime"]
    require(platform.python_version() == runtime["python"] and np.__version__ == runtime["numpy"],
            "registered Python/NumPy algebra runtime differs")

    def array_digest(value):
        value = np.ascontiguousarray(value, dtype="<f8")
        return hashlib.sha256(str((value.dtype.str, value.shape)).encode() + value.tobytes()).hexdigest()

    source = failed["linearization"]
    metadata = {key: value for key, value in source.items()
                if key not in ("base_output", "jacobian", "linearization_sha256")}
    base, jacobian = np.asarray(source["base_output"], dtype=np.float64), np.asarray(source["jacobian"], dtype=np.float64)
    require(hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                == source["linearization_sha256"] == accepted["retained_linearization_sha256"]
                == evidence["retained_linearization_sha256"]
            and base.shape == (2,) and jacobian.shape == (2, 6)
            and bool(np.isfinite(base).all() and np.isfinite(jacobian).all())
            and array_digest(base) == source["base_output_sha256"]
            and array_digest(jacobian) == source["jacobian_sha256"]
            and source["parent_state_sha256"] == failed["parent"]["state_sha256"],
            "retained numerical surrogate or metadata differs")
    central = proposal["algebraic_step"]
    require(all(central[key] == source[key] for key in
                ("linearization_sha256", "coordinate_sha256", "parent_state_sha256"))
            and central["ridge"] == proposal["objective"]["ridge"] == 1e-3
            and proposal["objective"] == evidence["objective"]
            and proposal["objective"]["observation_weights"] == [1.0, 1.0]
            and proposal["objective"]["target_offset"] == [1e-4, -1e-4]
            and proposal["objective"]["max_step_norm"] == 1.0
            and central["data_rank"] == 2 and central["data_nullity"] == 4
            and central["solver_numerical_rank"] == 6 and central["ridge_is_data_identification"] is False,
            "central algebraic problem or identification semantics differ")
    targets, expected = np.asarray(proposal["targets"]), np.asarray(central["delta"])
    require(np.array_equal(targets, base + [1e-4, -1e-4]) and expected.shape == (6,)
            and bool(np.isfinite(expected).all()) and array_digest(expected) == central["delta_sha256"],
            "fixed targets or recorded central step differ")
    edit = evidence["coordinate_edit_construction"]
    require(edit["learning_receipt_sha256"] == INPUT_PINS["surrogate_step"]
            and edit["delta_sha256"] == central["delta_sha256"]
            and edit["coordinate_sha256"] == central["coordinate_sha256"]
            and edit["candidate_state_sha256"] == accepted["candidate_export"]["model_state_sha256"],
            "accepted candidate is not bound to this recorded central step")

    # This NEW common identity explicitly says surrogate, preserving the old
    # failed source record separately. No PASSED smooth receipt is invented.
    shared = {key: source[key] for key in peer.SHARED_FIELDS}
    shared["derivative"] = SURROGATE_RULE
    parent = failed["parent"]
    common = {"schema": peer.COMMON_SCHEMA, "round": "v4-nonsmooth-local-equations-01",
              "roster": ["partition_0", "partition_1"], "profile_sha256": parent["profile_sha256"],
              "candidate_sha256": parent["checkpoint_sha256"], "source_binding_sha256": parent["source_binding_sha256"],
              "runtime": runtime, "linearization": shared, "objective": peer.OBJECTIVE, "ridge": 1e-3}
    contributions, local_records = [], []
    for row in range(2):
        batch = {"original_failed_result_sha256": INPUT_PINS["failed_result"],
                 "input_sha256": source["input_sha256"], "initial_margin_sha256": source["initial_margin_sha256"],
                 "source_row": row, "target": targets[row:row+1].tolist(), "weights": [1.0]}
        batch_sha = profile_io.sha(profile_io.canonical(batch))
        local_record = {"schema": "hepta.smallhcsn.retained-surrogate-row.v1",
                        "accepted_result_sha256": INPUT_PINS["accepted_result"],
                        "surrogate_proposal_sha256": INPUT_PINS["surrogate_step"],
                        "source_linearization_sha256": source["linearization_sha256"],
                        "common_sha256": profile_io.sha(profile_io.canonical(common)),
                        "batch": batch, "base_output": base[row:row+1].tolist(), "jacobian": jacobian[row:row+1].tolist()}
        local_metadata = {**shared, "linearization_sha256": profile_io.sha(profile_io.canonical(local_record))}
        local = SimpleNamespace(metadata=local_metadata, base_output=base[row:row+1], jacobian=jacobian[row:row+1])
        contributions.append(peer.contribute(common, local, targets[row:row+1], node=f"partition_{row}",
                                            batch_sha256=batch_sha, observation_weights=[1.0]))
        local_records.append(local_record)
    require(contributions[0]["body"]["local_linearization_sha256"]
            != contributions[1]["body"]["local_linearization_sha256"], "distinct local row identities required")
    right = targets - base
    direct = {"gram": jacobian.T @ jacobian, "moment": jacobian.T @ right, "residual_square": right @ right}
    statistics_errors = {}
    for key, reference in direct.items():
        summed = sum(np.asarray(envelope["body"][key]) for envelope in contributions)
        error = np.abs(summed - reference)
        require(bool(np.all(error <= TOLERANCES["statistics_atol"] + TOLERANCES["statistics_rtol"] * np.abs(reference))),
                "partitioned sufficient statistic differs from the complete retained system: " + key)
        statistics_errors[key] = float(np.max(error))
    result["new_quadratic_solves"] += 1
    aggregate = peer.solve_common(common, contributions)
    actual = np.asarray(aggregate["delta"])
    delta_error = np.abs(actual - expected)
    require(aggregate["ridge_applications"] == 1 and aggregate["ridge"] == 1e-3
            and aggregate["observation_count"] == 2 and aggregate["gram_rank_estimate"] <= 2
            and bool(np.all(delta_error <= TOLERANCES["delta_atol"] + TOLERANCES["delta_rtol"] * np.abs(expected))),
            "single-ridge aggregate differs from retained central augmented-SVD step")
    require("torch" not in sys.modules and not any(name == "qualification" or name.startswith("qualification.")
                for name in sys.modules), "unexpected model import during algebra")
    result.update({"status": "PASSED_LOCAL_SURROGATE_EQUATION_CONSISTENCY",
                   "algebra_runtime": {"python": platform.python_version(), "numpy": np.__version__},
                   "common": common, "local_retained_rows": local_records, "contributions": contributions,
                   "aggregate": aggregate, "statistics_max_abs_errors": statistics_errors,
                   "centralized_delta_max_abs_error": float(delta_error.max()),
                   "retained_central_data_rank": 2, "retained_central_data_nullity": 4,
                   "retained_regularized_solver_rank": 6, "existing_accepted_candidate": accepted["candidate_export"],
                   "retained_actual_reduction_gate": gate,
                   "retained_gate_applies_to": "existing central trial candidate only; aggregate candidate unevaluated"})


def timeout(signum, _frame):
    raise TimeoutError("registered algebra budget expired: signal " + str(signum))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-sha256", "failed-result", "accepted-result", "surrogate-step", "trial-evidence",
                 "peer-module-dir", "profile-module-dir", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = {"schema": "hepta.smallhcsn.nonsmooth-peer-consistency-result.v1", "status": "FAILED",
              "source_sha256": args.source_sha256, "dependency_sha256": DEPENDENCY_PINS,
              "input_sha256": INPUT_PINS, "tolerances": TOLERANCES,
              "scope": "two row partitions of one retained nonsmooth surrogate; local algebra only",
              "original_smooth_status": "FAILED", "classical_jacobian_admitted": False,
              "new_model_imports": False, "new_model_forward_calls": 0, "new_vjp_calls": 0,
              "new_quadratic_solves": 0, "training_updates": 0, "new_multihost_execution": False,
              "real_cross_user_acceptance": False, "aggregate_step_materialized": False,
              "aggregate_step_actual_objective_evaluated": False, "candidate_exported": False,
              "candidate_adopted": False, "existing_accepted_candidate_changed": False,
              "natural_task_benefit_claim": False, "historical_matrix_rerun": False,
              "maximum_wall_seconds": 30, "maximum_cpu_seconds": 30}
    started, cpu = time.perf_counter(), time.process_time()
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(30)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
    try:
        execute(args, result)
    except Exception as error:
        result["error"] = repr(error)
        result["traceback"] = traceback.format_exc()
    finally:
        signal.alarm(0)
        result["wall_s"] = time.perf_counter() - started
        result["cpu_s"] = time.process_time() - cpu
    raw = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"status": result["status"], "result_sha256": hashlib.sha256(raw).hexdigest()}))
    return 0 if result["status"] == "PASSED_LOCAL_SURROGATE_EQUATION_CONSISTENCY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
