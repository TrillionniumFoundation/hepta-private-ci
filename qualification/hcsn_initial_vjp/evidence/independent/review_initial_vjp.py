"""Read retained initial-amplitude VJP arrays; never import the candidate."""

import argparse
import ast
import hashlib
import io
import json
import math
import tarfile
import time
from collections import Counter
from pathlib import Path

import numpy as np


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identify(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def load_arrays(source):
    with np.load(source, allow_pickle=False) as stored:
        result = {name: stored[name].copy() for name in stored.files}
    require(
        all(
            value.dtype == np.float64 and np.isfinite(value).all()
            for value in result.values()
        ),
        "finite FP64 arrays",
    )
    return result


def apply_map(operator, amplitudes):
    result = np.empty((*operator.shape[:2], amplitudes.shape[1]))
    for t, state, channel in np.ndindex(result.shape):
        result[t, state, channel] = math.fsum(
            float(operator[t, state, direction]) * float(amplitudes[direction, channel])
            for direction in range(operator.shape[2])
        )
    return result


def apply_transpose(operator, cotangent):
    result = np.empty((operator.shape[2], cotangent.shape[2]))
    for direction, channel in np.ndindex(result.shape):
        result[direction, channel] = math.fsum(
            float(operator[t, state, direction]) * float(cotangent[t, state, channel])
            for t, state in np.ndindex(operator.shape[:2])
        )
    return result


def normalized_chain(raw_gradients, raw_inputs):
    count = len(raw_inputs[0])
    logits = np.linspace(-0.4, 0.5, count + len(raw_inputs[2]))
    weights = np.exp(logits - logits.max())
    weights /= weights.sum()
    marks = raw_inputs[1] / raw_inputs[0][:, None]
    phase_marks = raw_inputs[3] / raw_inputs[2][:, None]
    probability_cotangent = np.r_[
        raw_gradients[0] + (raw_gradients[1] * marks).sum(1),
        raw_gradients[2] + (raw_gradients[3] * phase_marks).sum(1),
    ]
    logits_gradient = weights * (
        probability_cotangent - np.dot(weights, probability_cotangent)
    )
    return (
        logits_gradient,
        weights[:count, None] * raw_gradients[1],
        weights[count:, None] * raw_gradients[3],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    package = args.root / "qualification/hcsn_initial_vjp"
    evidence = package / "evidence"
    native = evidence / "native002/recovered-originals"
    original = json.loads((evidence / "numpy001/RESULT.json").read_bytes())
    actual = json.loads((native / "native-result/RESULT.json").read_bytes())
    manifest = json.loads((native / "SOURCE.json").read_bytes())
    formatting = json.loads((evidence / "FORMAT.json").read_bytes())
    paths = [
        path
        for base in (evidence / "numpy001", native)
        for path in base.rglob("*")
        if path.is_file()
    ]
    before = {str(path): digest(path) for path in paths}
    tested = {}
    with tarfile.open(native / "BUNDLE.tar.gz", "r:gz") as archive:
        for member in archive:
            require(member.isfile() and member.name not in tested, "bundle member")
            tested[member.name] = archive.extractfile(member).read()
    require(len(manifest["source_sha256"]) == 13, "source count")
    require(
        manifest["source_sha256"]
        == actual["source_sha256_before"]
        == actual["source_sha256_after"],
        "native source guards",
    )
    format_rows = []
    for name, expected in manifest["source_sha256"].items():
        require(hashlib.sha256(tested[name]).hexdigest() == expected, "tested source")
        current = (args.root / name).read_bytes()
        mapping = formatting["sources"][name]
        require(
            hashlib.sha256(current).hexdigest() == mapping["published_sha256"],
            "published source",
        )
        require(
            ast.dump(ast.parse(current), include_attributes=False)
            == ast.dump(ast.parse(tested[name]), include_attributes=False),
            "source AST",
        )
        format_rows.append(
            {
                "path": name,
                "tested_sha256": expected,
                "published_sha256": mapping["published_sha256"],
                "ast_equal": True,
            }
        )
    for name, expected in original["source_sha256"].items():
        relative = Path(name).relative_to(args.root).as_posix()
        require(
            hashlib.sha256(tested[relative]).hexdigest() == expected,
            "NumPy tested source",
        )
    expected_bytes = tested["EXPECTED.npz"]
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()
    require(
        expected_sha
        == original["arrays_sha256"]
        == actual["expected_arrays_sha256"]
        == manifest["expected_arrays_sha256"],
        "expected array lineage",
    )
    require(digest(evidence / "numpy001/ARRAYS.npz") == expected_sha, "NumPy arrays")
    require(
        digest(native / "native-result/ARRAYS.npz") == actual["arrays_sha256"],
        "native arrays",
    )
    arrays = load_arrays(io.BytesIO(expected_bytes))
    outputs = load_arrays(native / "native-result/ARRAYS.npz")
    require(len(arrays) == 98 and len(outputs) == 15, "array roster")
    calls = json.loads((native / "native-result/CALLS.json").read_bytes())
    require(calls == actual["calls"] and len(calls) == 39, "call receipts")
    require(
        sum(row["basis_forward_calls"] for row in calls)
        == 39
        == actual["api_forward_calls"]
        == actual["basis_ode_forward_calls"],
        "basis calls",
    )
    require(
        actual["native_uniform_oracle_forward_calls"] == 2
        and actual["optimizer_updates"] == original["optimizer_updates"] == 0,
        "execution scope",
    )
    result = {
        "schema": "hcsn-independent-initial-amplitude-vjp-review-v1",
        "passed": True,
        "source_commit": actual["source_commit"],
        "inspector_source": identify(Path(__file__)),
        "source_format_checks": format_rows,
        "numpy_arrays": identify(evidence / "numpy001/ARRAYS.npz"),
        "native_arrays": identify(native / "native-result/ARRAYS.npz"),
        "native_bundle": identify(native / "BUNDLE.tar.gz"),
        "geometries": [],
    }
    total_coordinates = 0
    raw_vjp_coordinates = 0
    for geometry, count in (("uniform", 7), ("graded", 12)):
        operator = arrays[geometry + "_operator"]
        cotangent = arrays[geometry + "_cotangent"]
        inputs = [arrays[f"{geometry}_input{index}"] for index in range(4)]
        amplitudes = np.vstack(
            [np.c_[inputs[0], inputs[1]], np.c_[inputs[2], inputs[3]]]
        )
        require(operator.shape == (4, count + 5, count + 2), "operator shape")
        mapped = apply_map(operator, amplitudes)
        vjp = apply_transpose(operator, cotangent)
        np.testing.assert_allclose(
            mapped, arrays[geometry + "_primal_map"], atol=5e-15, rtol=5e-15
        )
        np.testing.assert_allclose(
            vjp, arrays[geometry + "_vjp"], atol=5e-15, rtol=5e-15
        )
        stored_vjp = arrays[geometry + "_vjp"]
        gradients = [outputs[f"{geometry}_gradient{index}"] for index in range(4)]
        wanted = [vjp[:count, 0], vjp[:count, 1:], vjp[count:, 0], vjp[count:, 1:]]
        raw_error = max(
            float(np.max(abs(left - right))) for left, right in zip(gradients, wanted)
        )
        require(raw_error < 2e-7, "all four native VJP blocks")
        raw_vjp_coordinates += sum(value.size for value in gradients)
        own_report = next(
            row for row in original["reports"] if row["geometry"] == geometry
        )
        native_report = next(
            row for row in actual["results"] if row["geometry"] == geometry
        )
        direct_error = float(
            np.max(
                abs(
                    arrays[geometry + "_primal_map"]
                    - arrays[geometry + "_primal_direct"]
                )
            )
        )
        require(direct_error == own_report["maximum_primal_error"], "primal report")
        native_primal_error = float(
            np.max(
                abs(outputs[geometry + "_output"] - arrays[geometry + "_primal_direct"])
            )
        )
        require(
            native_primal_error == native_report["primal_maximum_error"],
            "native primal report",
        )
        stored_wanted = [
            stored_vjp[:count, 0],
            stored_vjp[:count, 1:],
            stored_vjp[count:, 0],
            stored_vjp[count:, 1:],
        ]
        native_stored_error = max(
            float(np.max(abs(a - b))) for a, b in zip(gradients, stored_wanted)
        )
        require(
            native_stored_error == native_report["full_vjp_maximum_error"],
            "native full VJP report",
        )
        all_cases, stability = [], []
        for direction in range(5):
            prefix = f"{geometry}_direction{direction}"
            delta = arrays[prefix]
            jvp = apply_map(operator, delta)
            np.testing.assert_allclose(
                jvp, arrays[prefix + "_jvp"], atol=5e-15, rtol=5e-15
            )
            differences = []
            for label, step in (("coarse", 2e-4), ("fine", 1e-4)):
                fd = (
                    arrays[f"{prefix}_{label}_high"] - arrays[f"{prefix}_{label}_low"]
                ) / (2 * step)
                require(
                    np.array_equal(fd, arrays[f"{prefix}_{label}_fd"]), "FD recompute"
                )
                original_jvp = arrays[prefix + "_jvp"]
                ratio = abs(original_jvp - fd) / (2e-7 + 2e-5 * abs(fd))
                values = {
                    "direction": direction,
                    "step": step,
                    "coordinates": fd.size,
                    "maximum_absolute_error": float(np.max(abs(original_jvp - fd))),
                    "maximum_gate_ratio": float(np.max(ratio)),
                    "gate_failures": int(np.count_nonzero(ratio > 1)),
                    "projected_vjp": float(np.sum(stored_vjp * delta)),
                    "projected_fd": float(np.sum(fd * cotangent)),
                }
                require(
                    values
                    == next(
                        row
                        for row in own_report["cases"]
                        if row["direction"] == direction and row["step"] == step
                    ),
                    "exact FD report",
                )
                all_cases.append(values)
                total_coordinates += fd.size
                differences.append(fd)
            stable = abs(differences[0] - differences[1]) / (
                3e-7 + 3e-5 * abs(differences[1])
            )
            require(not np.any(stable > 1), "FD stability")
            stability.append(float(stable.max()))
        entry = {
            "geometry": geometry,
            "intervals": count,
            "operator_scalars": operator.size,
            "input_vjp_coordinates": sum(value.size for value in gradients),
            "fsum_vjp_vs_stored_maximum_error": float(np.max(abs(vjp - stored_vjp))),
            "native_full_four_block_vjp_vs_fsum_maximum_error": raw_error,
            "native_primal_vs_direct_maximum_error": native_primal_error,
            "native_reported_vjp_error": native_report["full_vjp_maximum_error"],
            "directional_fd_cases_exact": all_cases,
            "maximum_stability_ratio": max(stability),
            "native_raw_gradcheck_reported": native_report["raw_gradcheck"],
        }
        if geometry == "uniform":
            oracle = [outputs[f"uniform_oracle_gradient{index}"] for index in range(4)]
            oracle_error = max(
                float(np.max(abs(a - b))) for a, b in zip(gradients, oracle)
            )
            require(
                oracle_error == native_report["uniform_native_graph_vjp_maximum_error"],
                "uniform oracle VJP",
            )
            implied = normalized_chain(gradients, inputs)
            implied_oracle = normalized_chain(oracle, inputs)
            implied_error = max(
                float(np.max(abs(a - b))) for a, b in zip(implied, implied_oracle)
            )
            require(
                abs(
                    implied_error
                    - native_report["normalized_native_graph_vjp_maximum_error"]
                )
                < 5e-15,
                "normalized implied scalar",
            )
            oracle_output_error = float(
                np.max(
                    abs(outputs["uniform_output"] - outputs["uniform_oracle_output"])
                )
            )
            np.testing.assert_allclose(
                outputs["uniform_output"],
                outputs["uniform_oracle_output"],
                atol=3e-9,
                rtol=3e-8,
            )
            entry.update(
                {
                    "native_uniform_oracle_raw_vjp_maximum_error": oracle_error,
                    "native_uniform_oracle_output_maximum_error": oracle_output_error,
                    "normalized_chain_implied_maximum_error": implied_error,
                    "normalized_chain_reported_native_maximum_error": native_report[
                        "normalized_native_graph_vjp_maximum_error"
                    ],
                    "normalized_native_gradient_arrays_archived": False,
                    "normalized_chain_scope": "Analytic softmax/content chain reconstructed from constant raw linear VJPs; native individual normalized gradients are not archived, only its actual gradcheck/assert flags and scalar maximum.",
                    "all_four_normal_and_data_mutation_guards_reported": native_report[
                        "normal_and_unsafe_guards_all_four_inputs"
                    ],
                    "old_physical_api_tensor_prior_refusal_reported": native_report[
                        "old_physical_only_rejects_trainable_prior"
                    ],
                }
            )
        result["geometries"].append(entry)
    require(
        total_coordinates == 3480 and raw_vjp_coordinates == 69, "coordinate accounting"
    )
    require(
        all(digest(Path(path)) == expected for path, expected in before.items()),
        "review altered originals",
    )
    result.update(
        {
            "directional_fd_output_comparisons": total_coordinates,
            "raw_native_input_vjp_coordinates": raw_vjp_coordinates,
            "preexisting_numpy_candidate_flows": 44,
            "preexisting_native_basis_flows": 39,
            "preexisting_native_uniform_torch_oracles": 2,
            "native_call_labels": dict(Counter(row["label"] for row in calls)),
            "new_ode_kernel_torch_optimizer_calls": 0,
            "source_originals_unchanged_files": len(before),
            "limitations": [
                "Two small-grid fixed-physics/support fixtures only; N<=32,K<=8,C<=4, map<=7400 scalars and up to three basis forwards per API call.",
                "This differentiates the computed finite basis operator. It is not a scalable n512 adjoint or full-network/filtering/migration/physical-parameter/support gradient.",
                "Raw input domain is bounded nonnegative unnormalized probability amplitudes and independent signed contents; gradients are ambient linear-extension VJPs. Normalization and probability-times-marks binding belong to a live client chain.",
                "Directional FD probes and fast-mode gradchecks are not exhaustive elementwise Jacobian checks. All 69 coordinates of the chosen raw VJPs are independently compared.",
                "Native mutation counterexamples were executed on the uniform fixture; implementation is shared across both exact supported model types.",
                "The NumPy development run was source-guarded but not precommitted. The native run used the separately precommitted source manifest.",
            ],
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - wall,
        }
    )
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "passed": True,
                "path": str(args.output),
                "sha256": digest(args.output),
                "fd_comparisons": total_coordinates,
                "raw_vjp_coordinates": raw_vjp_coordinates,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
