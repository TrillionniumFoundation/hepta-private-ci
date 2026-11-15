"""Inspect Git-bound adjoint artifacts without importing any candidate module."""

import argparse
import ast
import hashlib
import io
import json
import math
import tarfile
import time
from pathlib import Path

import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identify(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def archive_bytes(path):
    data = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            require(member.isfile() and member.name not in data, "archive member")
            data[member.name] = archive.extractfile(member).read()
    return data


def arrays(raw):
    with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
        result = {name: stored[name].copy() for name in stored.files}
    require(
        all(
            value.dtype == np.float64 and np.isfinite(value).all()
            for value in result.values()
        ),
        "finite FP64 arrays",
    )
    return result


def pair(left, right):
    return math.fsum(float(a) * float(b) for a, b in zip(left.ravel(), right.ravel()))


def coefficients(geometry, count):
    if geometry == "uniform":
        nodes = np.arange(count + 1) * (2.0 / count)
        down = np.full(
            count - 1, 0.5**2 / (2 * (2.0 / count) ** 2) + 0.12 / (2 * (2.0 / count))
        )
        up = np.full(
            count - 1, 0.5**2 / (2 * (2.0 / count) ** 2) - 0.12 / (2 * (2.0 / count))
        )
    else:
        nodes = 2.0 * np.expm1(3.0 * np.linspace(0, 1, count + 1)) / math.expm1(3.0)
        gaps = np.diff(nodes)
        left, right = gaps[:-1], gaps[1:]
        down = (0.5**2 + 0.12 * right) / (left * (left + right))
        up = (0.5**2 - 0.12 * left) / (right * (left + right))
    matrix = np.diag(-(down + up))
    matrix[np.arange(count - 2), np.arange(1, count - 1)] = up[:-1]
    matrix[np.arange(1, count - 1), np.arange(count - 2)] = down[1:]
    lower, upper = np.zeros(count - 1), np.zeros(count - 1)
    lower[0], upper[-1] = down[0], up[-1]
    index = int(np.searchsorted(nodes, 0.53, side="right")) - 1
    fraction = (0.53 - nodes[index]) / (nodes[index + 1] - nodes[index])
    reset = np.zeros(count + 1)
    reset[index], reset[index + 1] = 1 - fraction, fraction
    return matrix, lower, upper, reset[1:-1]


def phase_weight(left, right, q):
    if left == right:
        return math.exp(-q * left)
    return math.exp(-q * left) * -math.expm1(-q * (right - left)) / (q * (right - left))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter(), time.process_time()
    folder = args.folder
    current_path = folder / "GIT-LOCAL001-ORIGINALS.tar.gz"
    baseline_path = folder / "GIT-BASELINE-ORIGINALS.tar.gz"
    current = archive_bytes(current_path)
    baseline = archive_bytes(baseline_path)
    require(
        len(current) == 15
        and sha(current_path.read_bytes())
        == "b25571b3acbfd52e6a85d81d54acc0b48a731c0b31bed6a1ac3d6d69a86ff736",
        "Git current archive",
    )
    require(
        sha(baseline_path.read_bytes())
        == "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e",
        "Git baseline archive",
    )
    prefix = "qualification/hcsn_initial_adjoint/"
    result = json.loads(current[prefix + "evidence/local001/RESULT.json"])
    expected = json.loads(current[prefix + "EXPECTED.json"])
    start = json.loads(current[prefix + "evidence/LOCAL001-START.json"])
    require(
        result["status"] == "PASS" and result["error"] is None, "actual terminal result"
    )
    require(
        result["source_before"] == result["source_after"] == expected["source_sha256"],
        "source maps",
    )
    require(len(result["source_before"]) == 9, "source count")
    require(
        sha(current[prefix + "EXPECTED.json"])
        == result["expected_inventory_sha256"]
        == start["source_inventory_sha256"],
        "source inventory",
    )
    require(
        start["source_commit"] == "caba5a3f3a77d0a6eb7d54b5a906ae3bbb4fb772",
        "prefrozen source",
    )
    for name, digest in result["source_before"].items():
        require(sha(current[name]) == digest, "tested source bytes")
    formatting = json.loads((folder / "GIT-FORMAT.json").read_bytes())
    for name, row in formatting["files"].items():
        published = (folder / (Path(name).stem + ".published.py")).read_bytes()
        require(
            sha(current[name]) == row["tested_sha256"]
            and sha(published) == row["published_sha256"],
            "format hashes",
        )
        require(
            ast.dump(ast.parse(current[name]), include_attributes=False)
            == ast.dump(ast.parse(published), include_attributes=False),
            "format AST",
        )
    raw = current[prefix + "evidence/local001/ARRAYS.npz"]
    old_raw = next(
        value
        for name, value in baseline.items()
        if name.endswith("numpy001/ARRAYS.npz")
    )
    require(
        sha(raw) == result["arrays_sha256"]
        and sha(old_raw) == result["baseline_arrays_sha256"],
        "raw array identities",
    )
    data, old = arrays(raw), arrays(old_raw)
    compared = []
    for row in result["cases"]:
        if "coordinates" not in row:
            continue
        name = row["name"]
        actual, reference = data[name + "_actual"], data[name + "_expected"]
        require(
            actual.shape == reference.shape and actual.size == row["coordinates"],
            "comparison shape",
        )
        error = abs(actual - reference)
        ratio = error / (row["absolute_gate"] + row["relative_gate"] * abs(reference))
        require(
            float(error.max()) == row["maximum_absolute_error"]
            and float(ratio.max()) == row["maximum_mixed_gate_ratio"]
            and int(np.count_nonzero(ratio > 1)) == row["gate_failures"] == 0,
            "exact comparison metrics",
        )
        compared.append(
            {
                "name": name,
                "coordinates": actual.size,
                "absolute_gate": row["absolute_gate"],
                "relative_gate": row["relative_gate"],
                "maximum_absolute_error": float(error.max()),
                "maximum_mixed_gate_ratio": float(ratio.max()),
                "failures": 0,
            }
        )
    require(
        sum(row["coordinates"] for row in compared) == 345, "comparison denominator"
    )
    geometry_rows = []
    for geometry, count in (("uniform", 7), ("graded", 12)):
        n, size, q, delay, terminal = count - 1, count + 5, 0.15, 0.21, 0.53
        cot = old[geometry + "_cotangent"]
        operator = old[geometry + "_operator"]
        vjp = data[geometry + "_baseline_vjp"]
        require(
            np.array_equal(data[geometry + "_baseline_cotangent"], cot),
            "retained cotangent",
        )
        exact_reference = np.einsum("tsd,tsc->dc", operator, cot)
        require(
            np.array_equal(data[geometry + "_old_basis_vjp_expected"], exact_reference)
            and np.array_equal(data[geometry + "_old_basis_vjp_actual"], vjp),
            "old basis binding",
        )
        independent = np.empty_like(exact_reference)
        for direction, channel in np.ndindex(independent.shape):
            independent[direction, channel] = math.fsum(
                float(operator[t, state, direction]) * float(cot[t, state, channel])
                for t, state in np.ndindex(operator.shape[:2])
            )
        np.testing.assert_allclose(independent, exact_reference, atol=5e-15, rtol=5e-15)
        for direction in range(5):
            delta = old[f"{geometry}_direction{direction}"]
            actual_projection = pair(vjp, delta)
            for label, step in (("coarse", 2e-4), ("fine", 1e-4)):
                base = f"{geometry}_direction{direction}_{label}"
                fd = (old[base + "_high"] - old[base + "_low"]) / (2 * step)
                require(np.array_equal(fd, old[base + "_fd"]), "old FD arithmetic")
                name = f"{geometry}_old_{direction}_{label}_projected_fd"
                require(
                    float(data[name + "_actual"][0]) == actual_projection
                    and float(data[name + "_expected"][0]) == pair(fd, cot),
                    "FD projection binding",
                )
        require(
            np.array_equal(
                data[geometry + "_time_tightening_actual"],
                data[geometry + "_tight_vjp"],
            )
            and np.array_equal(data[geometry + "_time_tightening_expected"], vjp),
            "tightening binding",
        )
        mass_cot = np.zeros((1, size, 1))
        mass_cot[0, : n + 2, 0] = 1
        require(
            np.array_equal(mass_cot, data[geometry + "_mass_cotangent"])
            and np.array_equal(
                data[geometry + "_mass_identity_expected"], np.ones((count + 2, 1))
            )
            and np.array_equal(
                data[geometry + "_mass_identity_actual"], data[geometry + "_mass_vjp"]
            ),
            "mass identity",
        )
        matrix, lower, upper, reset = coefficients(geometry, count)
        continuation = data[geometry + "_bellman_cotangent"][0, :, 0]
        factor = math.exp(-q * terminal)
        values = continuation[:n] / factor
        reset_value = continuation[n + 5] / factor
        alpha, reward = continuation[n + 4], continuation[n + 3]
        wanted = np.r_[
            values,
            alpha / q,
            phase_weight(0.035, 0.113, q) * reset_value,
            math.exp(-q * 0.071) * reset_value,
        ][:, None]
        np.testing.assert_allclose(
            wanted,
            data[geometry + "_bellman_identity_expected"],
            atol=1e-13,
            rtol=1e-13,
        )
        residual = (
            q * values
            - matrix @ values
            - (
                alpha
                + lower * (reward + math.exp(-q * delay) * reset_value)
                + upper * alpha / q
            )
        )
        require(
            float(np.max(abs(residual))) < 2e-11
            and abs(reset @ values - reset_value) < 1e-12,
            "analytic Bellman coefficient residual",
        )
        zero_cot = data[geometry + "_atom_zero_cotangent"][0]
        zero_expected = np.vstack([zero_cot[: n + 1], reset @ zero_cot[:n]])
        np.testing.assert_allclose(
            zero_expected,
            data[geometry + "_atom_zero_sides_expected"],
            atol=1e-14,
            rtol=1e-14,
        )
        atom_response = data[geometry + "_atom_reference_response"]
        np.testing.assert_allclose(atom_response[0, n + 1], 1, atol=0, rtol=0)
        np.testing.assert_allclose(
            atom_response[0, n + 5], math.exp(-q * 0.071), atol=1e-15, rtol=1e-15
        )
        atom_at_release = np.zeros(size)
        atom_at_release[:n] = reset
        np.testing.assert_allclose(
            atom_response[1], atom_at_release, atol=1e-14, rtol=1e-14
        )
        for stem, response in (
            ("atom", atom_response),
            ("uniform", data[geometry + "_uniform_reference_response"]),
        ):
            full_stem = geometry + (
                "_atom_front" if stem == "atom" else "_uniform_front"
            )
            phase_cot = data[full_stem + "_cotangent"]
            phase_reference = np.array(
                [
                    pair(response, phase_cot[:, :, channel])
                    for channel in range(phase_cot.shape[2])
                ]
            )
            np.testing.assert_allclose(
                phase_reference,
                data[full_stem + "_pairing_expected"],
                atol=2e-14,
                rtol=2e-14,
            )
            require(
                np.array_equal(
                    data[full_stem + "_pairing_actual"], data[full_stem + "_vjp"][-1]
                ),
                "phase pairing actual binding",
            )
            np.testing.assert_allclose(
                response[:, :n].sum(1) + response[:, n] + response[:, n + 1],
                1,
                atol=2e-13,
                rtol=2e-13,
            )
            np.testing.assert_allclose(
                response[-1, n + 1], response[-1, n + 2], atol=1e-14, rtol=1e-14
            )
            absolute_time = 0.071 + delay if stem == "atom" else 0.113
            np.testing.assert_allclose(
                response[-1, n + 5],
                math.exp(q * (absolute_time - delay)) * response[-1, n + 3],
                atol=1e-14,
                rtol=1e-14,
            )
        uniform_response = data[geometry + "_uniform_reference_response"]
        np.testing.assert_allclose(
            uniform_response[0, n + 5],
            phase_weight(0.035, 0.113, q),
            atol=1e-14,
            rtol=1e-14,
        )
        np.testing.assert_allclose(
            uniform_response[1, n + 5],
            math.exp(q * 0.035) * phase_weight(0.035, 0.113, q),
            atol=1e-14,
            rtol=1e-14,
        )
        upper_expected = -math.expm1(-q * terminal) / q
        require(
            float(data[geometry + "_upper_occupation_expected"][0]) == upper_expected
            and np.array_equal(
                data[geometry + "_upper_occupation_actual"],
                data[geometry + "_upper_vjp"][n],
            ),
            "upper occupation",
        )
        geometry_rows.append(
            {
                "geometry": geometry,
                "intervals": count,
                "old_vjp_coordinates": independent.size,
                "fsum_old_reference_error": float(
                    np.max(abs(independent - exact_reference))
                ),
                "adjoint_vs_fsum_old_vjp_error": float(np.max(abs(vjp - independent))),
                "old_fd_projection_comparisons": 10,
                "bellman_resolvent_residual_without_new_solve": float(
                    np.max(abs(residual))
                ),
                "reset_value_residual": float(abs(reset @ values - reset_value)),
                "phase_side_and_weight_identities_checked": True,
            }
        )
    scalar_delay = 1 + 0.7 * (0.3 - 0.2)
    scalar_clock = 0.6 * -math.expm1(-(0.8 + 0.9) * 0.3) / (0.8 + 0.9)
    require(
        float(data["scalar_delay_expected"][0, 0]) == scalar_delay
        and float(data["scalar_clock_expected"][0]) == scalar_clock,
        "closed scalar references",
    )
    statistics = [row for row in result["cases"] if "statistics" in row]
    require(
        len(statistics) == 18
        and sum(row["statistics"]["internal_steps"] == 0 for row in statistics) == 2,
        "adjoint call accounting",
    )
    for row in statistics:
        stat = row["statistics"]
        require(
            stat["internal_steps"] <= 4096
            and stat["rhs_evaluations"] <= 100000
            and stat["stored_scalars"] <= 1000000
            and stat["maximum_current_jacobian_nonzeros"] <= 10000
            and stat.get("quadrature_evaluations", 0) <= 250000,
            "per-call budget",
        )
    require(
        result["calls"]
        == {
            "adjoint_calls": 18,
            "zero_horizon_adjoint_calls": 2,
            "static_perpetual_solves": 2,
            "independent_matrix_exponentials": 196,
            "forward_basis_calls": 0,
            "forward_dde_calls": 0,
            "torch_calls": 0,
            "optimizer_updates": 0,
        },
        "actual stage counters",
    )
    report = {
        "schema": "hcsn-independent-initial-adjoint-review-v1",
        "passed": True,
        "git_head": "06856b0bba5c26c8aa72dc15a4f2a6e34e253bc5",
        "tested_source_commit": start["source_commit"],
        "git_archives": [identify(current_path), identify(baseline_path)],
        "inspector_source": identify(Path(__file__)),
        "source_count": 9,
        "format_full_ast_equal_files": 2,
        "comparisons": compared,
        "compared_scalar_count": 345,
        "geometries": geometry_rows,
        "call_denominator": {
            "full_amplitude_api_calls": 16,
            "scalar_reverse_engine_calls": 2,
            "zero_horizon_calls_included": 2,
            "independent_expm_per_geometry": "2 atom-front (including duration0) +32+64 uniform quadrature =98",
            "independent_expm_total": 196,
            "static_perpetual_total": 2,
            "new_forward_dde_basis_torch_optimizer_in_original_stage": 0,
        },
        "resource_observations": {
            "maximum_per_call_steps": max(
                row["statistics"]["internal_steps"] for row in statistics
            ),
            "maximum_per_call_rhs": max(
                row["statistics"]["rhs_evaluations"] for row in statistics
            ),
            "maximum_per_call_stored_scalars": max(
                row["statistics"]["stored_scalars"] for row in statistics
            ),
            "maximum_current_jacobian_nonzeros": max(
                row["statistics"]["maximum_current_jacobian_nonzeros"]
                for row in statistics
            ),
            "sum_steps": sum(row["statistics"]["internal_steps"] for row in statistics),
            "sum_rhs": sum(row["statistics"]["rhs_evaluations"] for row in statistics),
            "reported_stage_wall_seconds": result["wall_seconds"],
            "reported_stage_cpu_seconds": result["cpu_seconds"],
            "reported_process_peak_rss_kib": result["maximum_rss_kib"],
        },
        "limits": [
            "Snapshot-corruption rejection logic is present but no recorded call exercises that negative control; only mutation of live caller metadata was actually exercised.",
            "Reference matrix exponentials and static solves were not re-executed. Their frozen source/counters, saved arrays and independent algebraic identities were inspected.",
            "These are 345 retained scalar comparisons, including20 projections of old FD data; not a new3480-coordinate FD run.",
            "Continuous finite-DDE initial VJP on two fixed small meshes only; adaptive-BDF program reverse, Torch adapter/guards, broad domains, physical/support/migration gradients and n512 remain unqualified.",
            "The coefficient budget bounds a declared stored payload, not process RSS or complete solver complexity. All caps are per call.",
            "Mixed absolute-relative gates do not qualify rare-tail pure relative precision.",
        ],
        "review_new_candidate_imports_ode_adjoint_expm_static_torch_optimizer_calls": 0,
        "review_cpu_seconds": time.process_time() - cpu,
        "review_wall_seconds": time.perf_counter() - wall,
    }
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "passed": True,
                "path": str(args.output),
                "sha256": sha(args.output.read_bytes()),
                "comparisons": 345,
                "new_model_kernel_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
