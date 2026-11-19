"""Run the one-shot visit-897 source-migration N128 VJP admission."""

import argparse
import copy
import hashlib
import json
import platform
import resource
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import scipy
import torch
from qualification.hcsn_graded.spatial import GradedSpatialGenerator

from .source_flow import (
    MIGRATION_SHA256,
    N128_JSON_SHA256,
    N128_NPZ_SHA256,
    SELECTED,
    SELECTED_SHA256,
    CallBudget,
    _source_to_amplitudes,
    exact_fraction_transpose,
    freeze_source_migration,
    require_digest,
    sha,
    source_flow,
    validate_n128_payload,
    validate_selected_payload,
)

IDENTITY = (
    "hcsn-original-visit897-source-migration-vjp-n128-numerical-successor-20261112-c06d"
)
UNIQUE_EXECUTION_KEY = (
    "hcsn-original-visit897-source-migration-vjp-n128-numerical-successor-"
    "20261112-c06d-001"
)
FD_SCALES = (2e-4, 1e-4)
ABSOLUTE_TOLERANCE = 2e-8
RELATIVE_TOLERANCE = 1e-3
RELATIVE_FLOOR = 1e-10
TRANSPOSE_TOLERANCE = 5e-13


def _hash_sources(paths):
    return {name: sha(name) for name in paths}


def _objective():
    index = np.arange(133 * 5, dtype=np.float64).reshape(1, 133, 5) + 1
    value = (np.sin(index * 0.173) + 0.25 * np.cos(index * 0.071)) / 665
    if not np.all(np.isfinite(value)) or not np.any(value):
        raise ArithmeticError("fixed output cotangent differs")
    return value


def _pattern(length, multiplier, offset=0):
    index = np.arange(length, dtype=np.float64) + 1 + offset
    value = np.sin(index * multiplier) + 0.5 * np.cos(index * (multiplier + 0.11))
    return value / max(1.0, float(np.max(abs(value))))


def _directions(probability, content):
    directions = []
    for index, multiplier in enumerate((0.19, 0.31, 0.47, 0.73)):
        directions.append(
            {
                "name": f"normalized-logit-{index}",
                "space": "normalized",
                "dp": _pattern(25, multiplier),
                "dc": np.zeros((25, 4)),
            }
        )
    for index, multiplier in enumerate((0.23, 0.59)):
        directions.append(
            {
                "name": f"raw-signed-content-{index}",
                "space": "raw",
                "dp": np.zeros(25),
                "dc": np.outer(
                    _pattern(25, multiplier), _pattern(4, multiplier + 0.17)
                ),
            }
        )
    for index, multiplier in enumerate((0.37, 0.67)):
        pattern = _pattern(25, multiplier)
        directions.append(
            {
                "name": f"raw-mixed-{index}",
                "space": "raw",
                "dp": probability * pattern,
                "dc": content * pattern[:, None]
                + np.outer(
                    probability * _pattern(25, multiplier + 0.09),
                    _pattern(4, multiplier + 0.21),
                ),
            }
        )
    directions.extend(
        [
            {
                "name": "raw-homogeneous-probability",
                "space": "raw",
                "dp": probability.copy(),
                "dc": np.zeros((25, 4)),
            },
            {
                "name": "raw-homogeneous-content",
                "space": "raw",
                "dp": np.zeros(25),
                "dc": content.copy(),
            },
        ]
    )
    if len(directions) != 10:
        raise AssertionError("the fixed ten-direction denominator differs")
    return directions


def _loss(snapshot, budget, probability, content, cotangent):
    output = source_flow(snapshot, probability, content, budget=budget)
    return output, (output * torch.from_numpy(cotangent)).sum()


def _negative_guards(snapshot, selected, n128_metadata):
    results = []

    def reject(name, operation):
        try:
            operation()
        except (ValueError, RuntimeError) as exc:
            results.append(
                {
                    "name": name,
                    "rejected": True,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
        else:
            raise AssertionError(f"negative guard accepted: {name}")

    wrong_visit = copy.deepcopy(selected)
    wrong_visit["selection"]["visit_index"] = 898
    reject("wrong_visit", lambda: validate_selected_payload(wrong_visit))
    wrong_arm = copy.deepcopy(selected)
    wrong_arm["selection"]["arm"] = "c0_b0"
    reject("wrong_arm", lambda: validate_selected_payload(wrong_arm))
    reject(
        "selected_bytes_hash_mismatch",
        lambda: require_digest("0" * 64, SELECTED_SHA256, "selected-law"),
    )
    reject(
        "migration_bytes_hash_mismatch",
        lambda: require_digest("f" * 64, MIGRATION_SHA256, "migration-source"),
    )
    uniform = np.linspace(0.0, 8.0, 129)
    reject(
        "uniform_node_substitution",
        lambda: validate_n128_payload(
            n128_metadata,
            np.zeros(129),
            np.zeros((129, 4)),
            uniform,
            snapshot.model.spatial,
        ),
    )
    reject(
        "n512_node_substitution",
        lambda: validate_n128_payload(
            n128_metadata,
            np.zeros(513),
            np.zeros((513, 4)),
            np.linspace(0.0, 8.0, 513),
            GradedSpatialGenerator(512, 8.0, -0.11999999999999998, 0.35, 6.0),
        ),
    )
    mutable_lift = snapshot.lift_float.copy()
    mutable_snapshot = replace(snapshot, lift_float=mutable_lift)
    zero_budget = CallBudget(IDENTITY)
    reject("mutable_lift_cache", lambda: mutable_snapshot.check(zero_budget))
    lower_lift = snapshot.lift_float.copy()
    lower_lift[0, 0] = 1e-6
    lower_lift.setflags(write=False)
    lower_snapshot = replace(snapshot, lift_float=lower_lift)
    reject(
        "nonzero_lower_atom",
        lambda: _source_to_amplitudes(
            lower_snapshot, snapshot.source_probability, snapshot.source_content
        ),
    )
    p = torch.from_numpy(snapshot.source_probability.copy())
    c = torch.from_numpy(snapshot.source_content.copy())
    reject(
        "trainable_delay_request",
        lambda: source_flow(
            snapshot,
            p,
            c,
            budget=zero_budget,
            trainable_metadata={"delay": True},
        ),
    )
    reject(
        "trainable_support_request",
        lambda: source_flow(
            snapshot,
            p,
            c,
            budget=zero_budget,
            trainable_metadata={"support": True},
        ),
    )
    reject(
        "trainable_physics_request",
        lambda: source_flow(
            snapshot,
            p,
            c,
            budget=zero_budget,
            trainable_metadata={"physics": True},
        ),
    )
    scaled = _source_to_amplitudes(
        snapshot,
        1.25 * snapshot.source_probability,
        1.25 * snapshot.source_content,
    )
    mass = float(scaled[0].sum() + scaled[2].sum())
    if mass != 1.25:
        raise AssertionError("raw source path silently normalized")
    results.append(
        {"name": "raw_path_not_silently_normalized", "rejected": True, "mass": mass}
    )
    if (
        zero_budget.forward_calls
        or zero_budget.adjoint_calls
        or zero_budget.optimizer_updates
    ):
        raise AssertionError("negative guards performed numerical work")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    source = json.loads(args.source.read_text())
    inventory = json.loads(
        Path(
            "qualification/hcsn_source_migration_vjp_n128_numerical_successor/SOURCE.json"
        ).read_text()
    )
    before = _hash_sources(source["source_sha256"])
    if (
        source["request_identity"] != IDENTITY
        or source["unique_execution_key"] != UNIQUE_EXECUTION_KEY
        or source["source_sha256"] != inventory["source_sha256"]
        or before != source["source_sha256"]
        or source.get("parent_static_clear") != inventory.get("parent_static_clear")
    ):
        raise ValueError("prefrozen source inventory differs")
    static_clear = inventory.get("parent_static_clear", {})
    if static_clear != {
        "artifact_id": 13967801304,
        "artifact_sha256": (
            "dce818e9bdf8eff3db295d47ded5e297a46e5a529c2fbb77aa31f9df8da6b322"
        ),
        "checks_failed": 0,
        "checks_passed": 34,
        "head": "859d0f75119b792c035af54c9872b5fb7636eca6",
        "job_id": 131361931939,
        "run_id": 43269501620,
        "status": "CLEAR_SOURCE_TREE_STATIC_ONLY",
    }:
        raise ValueError("authoritative #6265 static CLEAR differs")
    selected = json.loads(SELECTED.read_text())
    n128_path = Path(
        "qualification/hcsn_source_migration_vjp_n128/inputs/seed37-c0_b1-step24-pos1-n128.json"
    )
    n128_metadata = json.loads(n128_path.read_text())
    require_digest(sha(SELECTED), SELECTED_SHA256, "#6223-selected-law")
    require_digest(sha(n128_path), N128_JSON_SHA256, "#6234-N128-metadata")
    require_digest(
        sha(n128_path.with_suffix(".npz")), N128_NPZ_SHA256, "#6234-N128-arrays"
    )
    snapshot = freeze_source_migration()
    guards = _negative_guards(snapshot, selected, n128_metadata)
    budget = CallBudget(IDENTITY)
    budget.validate()
    cotangent = _objective()
    probability = snapshot.source_probability.copy()
    content = snapshot.source_content.copy()
    logits = np.log(probability)
    marks = snapshot.source_marks.copy()
    directions = _directions(probability, content)
    records = []
    error = None
    try:
        raw_p = torch.tensor(probability, dtype=torch.float64, requires_grad=True)
        raw_c = torch.tensor(content, dtype=torch.float64, requires_grad=True)
        raw_output, raw_loss = _loss(snapshot, budget, raw_p, raw_c, cotangent)
        raw_loss.backward()
        raw_grad = (
            raw_p.grad.detach().numpy().copy(),
            raw_c.grad.detach().numpy().copy(),
        )

        norm_z = torch.tensor(logits, dtype=torch.float64, requires_grad=True)
        norm_m = torch.tensor(marks, dtype=torch.float64, requires_grad=True)
        norm_p = torch.softmax(norm_z, dim=0)
        norm_c = norm_p[:, None] * norm_m
        norm_output, norm_loss = _loss(snapshot, budget, norm_p, norm_c, cotangent)
        norm_loss.backward()
        normalized_grad = (
            norm_z.grad.detach().numpy().copy(),
            norm_m.grad.detach().numpy().copy(),
        )

        amplitude_vjp = np.asarray(
            budget.adjoint_records[0]["amplitude_vjp"], dtype=np.float64
        )
        fraction_p, fraction_c = exact_fraction_transpose(snapshot, amplitude_vjp)
        transpose_errors = np.r_[
            abs(fraction_p - raw_grad[0]).ravel(),
            abs(fraction_c - raw_grad[1]).ravel(),
        ]
        if (
            transpose_errors.shape != (125,)
            or np.max(transpose_errors) > TRANSPOSE_TOLERANCE
        ):
            raise ArithmeticError(
                "all-coordinate exact migration transpose gate failed"
            )

        for direction in directions:
            if direction["space"] == "raw":
                analytic = float(
                    np.vdot(raw_grad[0], direction["dp"])
                    + np.vdot(raw_grad[1], direction["dc"])
                )
            else:
                analytic = float(
                    np.vdot(normalized_grad[0], direction["dp"])
                    + np.vdot(normalized_grad[1], direction["dc"])
                )
            estimates = []
            for scale in FD_SCALES:
                losses = []
                for sign in (-1.0, 1.0):
                    if direction["space"] == "raw":
                        p_value = probability + sign * scale * direction["dp"]
                        c_value = content + sign * scale * direction["dc"]
                    else:
                        z_value = logits + sign * scale * direction["dp"]
                        m_value = marks + sign * scale * direction["dc"]
                        shifted = np.exp(z_value - np.max(z_value))
                        p_value = shifted / shifted.sum()
                        c_value = p_value[:, None] * m_value
                    if np.min(p_value) < 0:
                        raise ArithmeticError(
                            "fixed FD direction left the probability cone"
                        )
                    _, loss = _loss(
                        snapshot,
                        budget,
                        torch.from_numpy(p_value.copy()),
                        torch.from_numpy(c_value.copy()),
                        cotangent,
                    )
                    losses.append(float(loss))
                estimates.append((losses[1] - losses[0]) / (2 * scale))
            fine = estimates[1]
            absolute_error = abs(analytic - fine)
            threshold = ABSOLUTE_TOLERANCE + RELATIVE_TOLERANCE * abs(fine)
            eligible = abs(fine) >= RELATIVE_FLOOR
            relative_error = absolute_error / abs(fine) if eligible else None
            passed = absolute_error <= threshold
            record = {
                "name": direction["name"],
                "space": direction["space"],
                "analytic": analytic,
                "coarse_fd": estimates[0],
                "fine_fd": fine,
                "absolute_error": absolute_error,
                "gate": threshold,
                "relative_eligible": eligible,
                "relative_error": relative_error,
                "passed": passed,
            }
            records.append(record)
            if not passed:
                raise ArithmeticError(f"directional gate failed: {direction['name']}")
        budget.validate()
        if (
            budget.forward_calls != 42
            or budget.adjoint_calls != 2
            or budget.backward_attempts != 2
            or budget.optimizer_updates != 0
            or len(records) != 10
            or len(guards) != 12
        ):
            raise ArithmeticError("the exact denominator/call ledger differs")
        status = "PASS_LIMITED_N128_ONE_LAW"
    except Exception as exc:  # noqa: BLE001 - persist every RED before stopping.
        error = {"type": type(exc).__name__, "message": str(exc)}
        status = "RED_STOP_NO_READMISSION"
    finally:
        after = _hash_sources(source["source_sha256"])
        result = {
            "identity": IDENTITY,
            "unique_execution_key": UNIQUE_EXECUTION_KEY,
            "source": source,
            "source_before": before,
            "source_after": after,
            "source_unchanged": before == after,
            "status": status,
            "error": error,
            "scope": {
                "intervals": 128,
                "source_laws": 1,
                "source_visit": 897,
                "arm": "c0_b1",
                "query_time": 0.02,
                "delay": 0.2,
                "first_cycle_only": True,
                "fullprior_domain_qualified": False,
                "migration_domain_qualified": False,
                "delay_or_support_ad_qualified": False,
                "fullnetwork_qualified": False,
                "finite_domain_qualified": False,
                "global_hold": True,
            },
            "calls": {
                "forwards": budget.forward_calls,
                "adjoints": budget.adjoint_calls,
                "backward_attempts": budget.backward_attempts,
                "optimizer_updates": budget.optimizer_updates,
                "metadata_checks": budget.metadata_checks,
            },
            "negative_guards": guards,
            "directional_checks": records,
            "raw_loss": float(raw_loss) if "raw_loss" in locals() else None,
            "normalized_loss": float(norm_loss) if "norm_loss" in locals() else None,
            "raw_output": np.asarray(raw_output.detach()).tolist()
            if "raw_output" in locals()
            else None,
            "normalized_output": np.asarray(norm_output.detach()).tolist()
            if "norm_output" in locals()
            else None,
            "raw_gradient_probability": raw_grad[0].tolist()
            if "raw_grad" in locals()
            else None,
            "raw_gradient_content": raw_grad[1].tolist()
            if "raw_grad" in locals()
            else None,
            "normalized_gradient_logits": normalized_grad[0].tolist()
            if "normalized_grad" in locals()
            else None,
            "normalized_gradient_marks": normalized_grad[1].tolist()
            if "normalized_grad" in locals()
            else None,
            "transpose_coordinate_absolute_errors": transpose_errors.tolist()
            if "transpose_errors" in locals()
            else None,
            "objective_sha256": hashlib.sha256(cotangent.tobytes()).hexdigest(),
            "forward_records": budget.forward_records,
            "adjoint_records": budget.adjoint_records,
            "runtime": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "torch": torch.__version__,
            },
            "costs": {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                "maximum_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
        }
        (args.output / "RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        np.savez_compressed(
            args.output / "RAW.npz",
            cotangent=cotangent,
            probability=probability,
            content=content,
            raw_gradient_probability=raw_grad[0]
            if "raw_grad" in locals()
            else np.array([]),
            raw_gradient_content=raw_grad[1]
            if "raw_grad" in locals()
            else np.array([]),
            normalized_gradient_logits=normalized_grad[0]
            if "normalized_grad" in locals()
            else np.array([]),
            normalized_gradient_marks=normalized_grad[1]
            if "normalized_grad" in locals()
            else np.array([]),
            amplitude_vjp=amplitude_vjp
            if "amplitude_vjp" in locals()
            else np.array([]),
        )
    print(json.dumps(result, sort_keys=True))
    if error is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
