"""Audit retained Torch journals using only NumPy contractions and file reads."""

import argparse
import hashlib
import io
import json
import math
import tarfile
import time
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identify(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def npz(raw):
    with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
        values = {name: stored[name].copy() for name in stored.files}
    require(all(value.dtype == np.float64 and np.isfinite(value).all()
                for value in values.values()), "finite FP64 retained arrays")
    return values


def flatten(values):
    return np.concatenate([value.ravel() for value in values])


def blocks(vjp, count):
    return (vjp[:count, 0], vjp[:count, 1:], vjp[count:, 0], vjp[count:, 1:])


def transpose(operator, cotangent):
    result = np.empty((operator.shape[2], cotangent.shape[2]))
    for direction, channel in np.ndindex(result.shape):
        result[direction, channel] = math.fsum(
            float(operator[t, state, direction]) * float(cotangent[t, state, channel])
            for t, state in np.ndindex(operator.shape[:2]))
    return result


def apply(operator, amplitudes):
    result = np.empty((*operator.shape[:2], amplitudes.shape[1]))
    for t, state, channel in np.ndindex(result.shape):
        result[t, state, channel] = math.fsum(
            float(operator[t, state, direction]) * float(amplitudes[direction, channel])
            for direction in range(operator.shape[2]))
    return result


def contraction(left, right):
    return math.fsum(float(a) * float(b) for a, b in zip(left.ravel(), right.ravel()))


def mixed(actual, expected, absolute, relative):
    error = abs(actual - expected)
    ratio = error / (absolute + relative * abs(expected))
    return float(error.max()), float(ratio.max()), int(np.count_nonzero(ratio > 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--frozen-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    archive = args.recovery / "original.zip"
    archive_raw = archive.read_bytes()
    require(len(archive_raw) == 254226 and sha(archive_raw) ==
            "8bca916a6f5dc7b346905268d005fab838805b475e39df738cb5a053b8ffe9d8", "original ZIP identity")
    payloads = {}
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as zipped:
        require(len(zipped.infolist()) == 6 and zipped.testzip() is None, "six CRC-checked members")
        for member in zipped.infolist():
            require(not member.is_dir() and member.filename not in payloads and
                    not member.filename.startswith("/") and ".." not in Path(member.filename).parts, "ZIP member")
            raw = zipped.read(member)
            require((args.recovery / member.filename).read_bytes() == raw, "loose original differs")
            payloads[member.filename] = raw
    result = json.loads(payloads["adjoint-torch/native/RESULT.json"])
    wrapper = json.loads(payloads["adjoint-torch/WRAPPER-COST.json"])
    source = json.loads(payloads["adjoint-torch-source.json"])
    frozen_raw = args.frozen_source.read_bytes()
    frozen = json.loads(frozen_raw)
    head = "975a169df5f3a1dd51b81ddd51b0a338592a0e0f"
    require(result["status"] == "PASS" and result["error"] is None and wrapper["exit_code"] == 0, "successful original result")
    require(source["source_commit"] == result["source_commit"] == wrapper["source_commit"] == head, "exact source head")
    require(source["prefrozen_inventory_sha256"] == sha(frozen_raw), "prefrozen inventory identity")
    require(source["source_sha256"] == frozen["source_sha256"] ==
            result["source_before"] == result["source_after"] and
            len(result["source_before"]) == 10 and result["source_unchanged"] is True, "ten source bindings")
    raw_arrays = payloads["adjoint-torch/native/ARRAYS.npz"]
    require(sha(raw_arrays) == result["arrays_sha256"], "native array identity")
    data = npz(raw_arrays)
    require(len(data) == 888, "native array roster")
    old_raw = args.baseline.read_bytes()
    require(sha(old_raw) == "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e", "old independent baseline archive")
    with tarfile.open(fileobj=io.BytesIO(old_raw), mode="r:gz") as old_archive:
        members = [member for member in old_archive if member.name.endswith("numpy001/ARRAYS.npz")]
        require(len(members) == 1, "one original baseline array")
        old_array_raw = old_archive.extractfile(members[0]).read()
    require(sha(old_array_raw) == "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305", "old arrays identity")
    old = npz(old_array_raw)
    forward, backward = result["forward_journal"], result["backward_journal"]
    calls = result["calls"]
    require(len(forward) == calls["model_forward_calls"] == 166 and
            len(backward) == calls["adjoint_calls"] == 10 and
            calls["backward_attempts"] == 32 and calls["guard_rejections"] == 20 and
            calls["forward_basis_calls"] == calls["optimizer_updates"] == 0, "call denominator")
    checks = []
    for row in result["checks"]:
        if "maximum_absolute_error" not in row:
            require(row["passed"] is True and row["fast_mode"] is False, "actual all-coordinate gradcheck flag")
            continue
        actual, expected = data[row["name"] + "_actual"], data[row["name"] + "_expected"]
        require(actual.shape == expected.shape and actual.size == row["coordinates"], "comparison shape")
        maximum, ratio, failures = mixed(actual, expected, row["absolute_gate"], row["relative_gate"])
        require(maximum == row["maximum_absolute_error"] and ratio == row["maximum_mixed_gate_ratio"] and
                failures == row["failures"] == 0, "all original comparison metrics exact")
        checks.append({**row, "independently_recomputed": True})
    require(sum(row["coordinates"] for row in checks) == 555, "numeric comparison denominator")
    forwards = []
    recorded_scalars = 0
    identities = {}
    for index, row in enumerate(forward):
        inputs = [data[f"forward_{index}_input{j}"] for j in range(4)]
        value = data[f"forward_{index}_output"]
        n = len(inputs[0])
        geometry = {7: "uniform", 12: "graded"}[n]
        require([x.shape for x in inputs] == [(n,), (n, 2), (2,), (2, 2)] and
                value.shape == (4, n + 5, 3), "forward journal schema")
        require((inputs[0] >= 0).all() and (inputs[2] >= 0).all(), "nonnegative probability amplitudes")
        amplitudes = np.vstack([np.c_[inputs[0], inputs[1]], np.c_[inputs[2], inputs[3]]])
        predicted = apply(old[geometry + "_operator"], amplitudes)
        maximum, ratio, failures = mixed(value, predicted, 1e-8, 2e-7)
        require(failures == 0 and row["internal_steps"] <= 4096, "forward journal vs retained linear operator")
        identities.setdefault(geometry, row["problem_identity"])
        require(identities[geometry] == row["problem_identity"], "fixed problem identity")
        objective_error = None
        if "objective" in row:
            independent = contraction(value, old[geometry + "_cotangent"])
            objective_error = abs(independent - row["objective"])
            require(objective_error < 2e-13, "Torch scalar objective binding")
        recorded_scalars += sum(x.size for x in inputs) + value.size
        forwards.append({"index": index, "label": row["label"], "geometry": geometry,
                         "maximum_absolute_operator_error": maximum, "maximum_mixed_gate_ratio": ratio,
                         "objective_fsum_error": objective_error})
    backward_rows = []
    for index, row in enumerate(backward):
        cotangent, vjp = data[f"backward_{index}_cotangent"], data[f"backward_{index}_vjp"]
        geometry = "uniform" if row["label"].startswith("uniform") else "graded"
        count = 7 if geometry == "uniform" else 12
        require(cotangent.shape == (4, count + 5, 3) and vjp.shape == (count + 2, 3), "backward journal schema")
        expected = transpose(old[geometry + "_operator"], cotangent)
        maximum, ratio, failures = mixed(vjp, expected, 3e-7, 3e-5)
        require(failures == 0 and row["problem_identity"] == identities[geometry] and
                not row["label"].startswith("guard"), "every live cotangent consumes the correct adjoint")
        stat = row["statistics"]
        require(stat["internal_steps"] <= 4096 and stat["rhs_evaluations"] <= 100000 and
                stat["stored_scalars"] <= 1000000 and stat["maximum_current_jacobian_nonzeros"] <= 10000,
                "reverse per-call budgets")
        recorded_scalars += cotangent.size + vjp.size
        backward_rows.append({"index": index, "label": row["label"],
                              "cotangent_zero": bool(np.count_nonzero(cotangent) == 0),
                              "maximum_absolute_old_operator_error": maximum,
                              "maximum_mixed_gate_ratio": ratio})
    geometry_rows = []
    total_pairs = 0
    for geometry, count in (("uniform", 7), ("graded", 12)):
        operator, cotangent = old[geometry + "_operator"], old[geometry + "_cotangent"]
        inputs = [old[f"{geometry}_input{j}"] for j in range(4)]
        raw_reference = np.einsum("tsd,tsc->dc", operator, cotangent)
        reference = flatten(blocks(raw_reference, count))
        independent = flatten(blocks(transpose(operator, cotangent), count))
        np.testing.assert_allclose(independent, reference, atol=5e-15, rtol=5e-15)
        require(np.array_equal(reference, data[geometry + "_raw_vjp_expected"]), "raw G transpose reference")
        require(np.array_equal(data[geometry + "_primal_expected"], old[geometry + "_primal_direct"]), "independent primal reference")
        base_forward = [i for i, row in enumerate(forward) if row["label"] == geometry + "_baseline"]
        base_backward = [i for i, row in enumerate(backward) if row["label"] == geometry + "_baseline"]
        require(len(base_forward) == len(base_backward) == 1, "one baseline forward/backward")
        require(np.array_equal(data[geometry + "_primal_actual"], data[f"forward_{base_forward[0]}_output"]), "baseline output journal")
        require(np.array_equal(data[geometry + "_raw_vjp_actual"],
                               flatten(blocks(data[f"backward_{base_backward[0]}_vjp"], count))), "baseline gradient journal")
        baseline = flatten(inputs)
        high, low = np.full(len(baseline), np.nan), np.full(len(baseline), np.nan)
        seen = Counter()
        for index, row in enumerate(forward):
            if row["label"] != geometry + "_gradcheck":
                continue
            current = [data[f"forward_{index}_input{j}"] for j in range(4)]
            delta = flatten(current) - baseline
            positions = np.flatnonzero(abs(delta) > 2e-5)
            if len(positions) == 0:
                require(np.array_equal(flatten(current), baseline), "unperturbed gradcheck call")
                continue
            require(len(positions) == 1, "single actual coordinate perturbation")
            selected = int(positions[0])
            require(abs(abs(delta[selected]) - 2e-4) < 1e-12, "actual perturbation EPS")
            target = high if delta[selected] > 0 else low
            require(not np.isfinite(target[selected]) or target[selected] == row["objective"], "duplicate FD objective")
            target[selected] = row["objective"]
            seen[selected, int(delta[selected] > 0)] += 1
        require(np.isfinite(high).all() and np.isfinite(low).all() and
                np.array_equal(high, data[geometry + "_gradcheck_high"]) and
                np.array_equal(low, data[geometry + "_gradcheck_low"]), "all69 FD pairs are actual journal values")
        fd = (high - low) / (2 * 2e-4)
        actual = data[geometry + "_raw_vjp_actual"]
        require(np.array_equal(fd, data[geometry + "_retained_coordinate_fd_actual"]) and
                np.array_equal(actual, data[geometry + "_retained_coordinate_fd_expected"]), "coordinate FD comparison binding")
        total_pairs += len(baseline)
        normalized = [i for i, row in enumerate(forward) if row["label"] == geometry + "_normalized_client"]
        normalized_back = [i for i, row in enumerate(backward) if row["label"] == geometry + "_normalized_client"]
        require(len(normalized) == len(normalized_back) == 1, "one normalized client")
        p = data[geometry + "_normalized_probabilities"]
        marks = data[geometry + "_normalized_conditional_marks"]
        require(p.shape == (count + 2,) and (p > 0).all() and abs(math.fsum(p) - 1) < 5e-16, "joint softmax probabilities")
        normalized_inputs = [p[:count], p[:count, None] * marks[:count], p[count:], p[count:, None] * marks[count:]]
        for j, expected in enumerate(normalized_inputs):
            require(np.array_equal(expected, data[f"forward_{normalized[0]}_input{j}"]), "live probability/mark input binding")
        def chain(vjp):
            effective = vjp[:, 0] + np.sum(vjp[:, 1:] * marks, axis=1)
            return p * (effective - np.sum(p * effective)), p[:, None] * vjp[:, 1:]
        reference_logits, reference_marks = chain(raw_reference)
        require(np.array_equal(reference_logits, data[geometry + "_normalized_logits_expected"]) and
                np.array_equal(reference_marks, data[geometry + "_normalized_marks_expected"]), "normalized reference vectors")
        actual_logits, actual_marks = chain(data[f"backward_{normalized_back[0]}_vjp"])
        logits_error = float(np.max(abs(actual_logits - data[geometry + "_normalized_logits_actual"])))
        marks_error = float(np.max(abs(actual_marks - data[geometry + "_normalized_marks_actual"])))
        require(logits_error < 1e-14 and marks_error < 1e-14, "full normalized vectors consume actual adjoint")
        geometry_rows.append({"geometry": geometry, "raw_vjp_coordinates": len(baseline),
                              "actual_fd_coordinate_pairs": len(baseline), "retained_high_low_scalar_objectives": 2 * len(baseline),
                              "maximum_raw_vjp_fsum_error": float(np.max(abs(actual - independent))),
                              "maximum_fd_absolute_error": float(np.max(abs(fd - actual))),
                              "zero_fd_count": int(np.count_nonzero(fd == 0)),
                              "normalized_logits_chain_error": logits_error, "normalized_marks_chain_error": marks_error,
                              "normalized_gradient_coordinates": actual_logits.size + actual_marks.size})
    require(total_pairs == 69, "69 coordinate pairs,138 scalar objectives")
    tensor_expected = {(kind, index) for kind in ("normal", "unsafe_data", "unsafe_storage_replace") for index in range(4)}
    metadata_expected = {"times", "supports", "reset", "delay", "discount", "mu", "sigma", "endpoint"}
    tensor_guards = {(g["kind"], g["input"]) for g in result["guards"] if g["kind"] != "metadata"}
    metadata_guards = {g["field"] for g in result["guards"] if g["kind"] == "metadata"}
    require(tensor_guards == tensor_expected and metadata_guards == metadata_expected and
            len(result["guards"]) == 20 and all(g["rejected"] is True and g["adjoint_calls"] == 0 for g in result["guards"]), "twenty actual zero-adjoint guard rejections")
    require(recorded_scalars == result["recorded_array_scalars"] == 37071 and recorded_scalars <= 1000000, "recorded payload accounting")
    require(calls["metadata_checks"] == 2 * len(forward) + calls["backward_attempts"] - 12 == 352, "metadata-check accounting")
    require(calls["backward_attempts"] - calls["adjoint_calls"] - calls["guard_rejections"] == 2, "undefined no-adjoint attempts")
    stderr = payloads["adjoint-torch/native.stderr"].decode()
    require(len(payloads["adjoint-torch/native.stderr"]) == 190 and
            "RuntimeWarning: invalid value encountered in subtract" in stderr, "retained warning disclosure")
    report = {"schema": "hcsn-continuous-adjoint-torch-independent-review-v1", "passed": True,
              "source_head": head, "run_id": 43217764472, "job_id": 131181247635,
              "artifact_id": 13943834079, "original_zip": identify(archive),
              "frozen_source": identify(args.frozen_source), "baseline_archive": identify(args.baseline),
              "inspector_source": identify(Path(__file__)), "source_hashes_equal_count": 10,
              "all888_arrays_finite": True, "numeric_scalar_comparisons": 555,
              "all_original_metric_fields_recomputed_exactly": True, "checks": checks,
              "geometries": geometry_rows, "all_forward_journal_comparisons": forwards,
              "all_backward_journal_comparisons": backward_rows, "calls": calls,
              "forward_labels": dict(Counter(row["label"] for row in forward)),
              "backward_labels": dict(Counter(row["label"] for row in backward)),
              "recorded_payload_recomputed": recorded_scalars,
              "cost": {"validation_wall_seconds": result["validation_wall_seconds"],
                  "validation_cpu_seconds": result["validation_cpu_seconds"], "wrapper": wrapper,
                  "validation_excludes_imports_and_source_admission": True},
              "stderr_warning": {"bytes": 190, "sha256": sha(payloads["adjoint-torch/native.stderr"]), "verbatim": stderr,
                  "warning_reproduced_by_this_audit": False, "benign_cause_not_proven": True},
              "prior_red_scope": {"source_head": "bc1b94039dea52c5426b99ba617f7a2f59742377",
                  "run_id": 43216185145, "job_id": 131175904511, "reported_model_forward_calls": 1,
                  "reported_adjoint_calls": 0, "independently_reaudited_in_this_receipt": False,
                  "scope": "Separate preserved original API-error execution, not erased or included in this GREEN denominator."},
              "limits": ["Chosen scalar-loss VJPs and all69 ambient input-coordinate finite differences on uniformN7/gradedN12 only; not an exhaustive output Jacobian or broad physics/initial-law certificate.",
                  "Continuous finite-DDE custom adjoint, not adaptive-BDF instruction reverse; physics/support/delay/migration fixed and first order only.",
                  "All20 mutation controls use the uniform fixture and shared bridge; arbitrary hostile Python ledger tampering is not attested.",
                  "Mixed absolute-plus-relative gates do not establish rare-tail pure relative accuracy.",
                  "Forward4096-step check is post-solve and payload1m is not a process RSS ceiling.",
                  "No optimizer/Adam/restore, full-network, n512, task advantage, energy or adoption qualification."],
              "review_new_candidate_imports_torch_ode_adjoint_expm_static_optimizer_calls": 0,
              "review_wall_seconds": time.perf_counter() - wall, "review_cpu_seconds": time.process_time() - cpu}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "output": str(args.output), "sha256": sha(args.output.read_bytes()),
                      "fd_coordinate_pairs": 69, "high_low_objectives": 138, "numeric_comparisons": 555,
                      "new_model_kernel_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
