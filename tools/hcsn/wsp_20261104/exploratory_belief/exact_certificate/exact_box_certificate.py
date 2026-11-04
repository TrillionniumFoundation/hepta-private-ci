#!/usr/bin/env python3
"""Exact rational check of the two existing fit71 finite IEEE box certificates.

Only the original construct() and ACTIONS are loaded from the pinned source AST.
No optimizer is imported or called, no weights are refitted, and no data beyond
three specified frozen audit inputs is read. Python >=3.10 and NumPy suffice.

Build:  python exact_box_certificate.py build [--source-dir DIRECTORY]
Verify: python exact_box_certificate.py verify [--source-dir DIRECTORY]
Verify without --source-dir needs only this script, the JSON, and the NPZ.
"""
from __future__ import annotations

import argparse
import ast
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from fractions import Fraction
import hashlib
import json
from math import gcd, isqrt
from pathlib import Path
import platform
import sys
from typing import Iterable

import numpy as np

PINNED_SOURCES = {
    "train_policy_feasibility.py": "2390ca702cd7b740dbe49f58a15bf1d6630ca1b59c431e530f9c686ca1561933",
    "fixtures/train_linear_geometry.npz": "2928beeceabd3c6b48cda7d1b5df2de4ddbbaecc2ebedb23d2a8ce75df1816d5",
    "records/train_policy_feasibility.json": "6de08a16f53d2ecea5cd896732c9769acca94705333e844dde16f00d947159c6",
}
D = 147
PREFIXES = (("margin0", 0.0), ("margin0p001", 0.001))
EVIDENCE_NAME = "fit71_ieee_box_evidence.npz"
REPORT_NAME = "exact_certificate.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def source_hashes(source: Path) -> dict[str, str]:
    hashes = {name: sha256_file(source / name) for name in PINNED_SOURCES}
    require(hashes == PINNED_SOURCES, "Pinned source hash mismatch")
    return hashes


def array_provenance(a: np.ndarray) -> dict:
    a = np.ascontiguousarray(a)
    return {"shape": list(a.shape), "dtype": a.dtype.str,
            "encoding": "C-order bytes; dtype and shape are recorded separately",
            "sha256": sha256_bytes(a.tobytes(order="C"))}


def exact_float(value: float) -> Fraction:
    return Fraction.from_float(float(value))


def fraction_record(q: Fraction) -> dict:
    # These are directed 25-significant-digit bounds, not approximate signs.
    with localcontext() as ctx:
        ctx.prec = 25
        ctx.rounding = ROUND_FLOOR
        lower = Decimal(q.numerator) / Decimal(q.denominator)
    with localcontext() as ctx:
        ctx.prec = 25
        ctx.rounding = ROUND_CEILING
        upper = Decimal(q.numerator) / Decimal(q.denominator)
    require(Fraction(lower) <= q <= Fraction(upper), "Bad directed interval")
    return {"numerator": str(q.numerator), "denominator": str(q.denominator),
            "decimal_lower": str(lower), "decimal_upper": str(upper),
            "nearest_binary64_display": float(q)}


def sqrt_decimal_interval(q: Fraction, places: int = 30) -> dict:
    require(q >= 0, "Negative square norm")
    scale = 10 ** places
    floor_scaled = isqrt((q.numerator * scale * scale) // q.denominator)
    lo = Fraction(floor_scaled, scale)
    hi = lo if lo * lo == q else Fraction(floor_scaled + 1, scale)
    require(lo * lo <= q <= hi * hi, "Bad square-root interval")
    with localcontext() as ctx:
        ctx.prec = 100
        lower = str(Decimal(lo.numerator) / Decimal(lo.denominator))
        upper = str(Decimal(hi.numerator) / Decimal(hi.denominator))
    return {"decimal_lower": lower, "decimal_upper": upper,
            "method": "integer isqrt at 30 decimal places; exact squared endpoint checks"}


def dyadic_dot(pairs: Iterable[tuple[float, float]]) -> Fraction:
    """Independent integer accumulation of float ratios, with one final reduction."""
    products = []
    for a, b in pairs:
        an, ad = float(a).as_integer_ratio()
        bn, bd = float(b).as_integer_ratio()
        den = ad * bd
        require(den > 0 and den & (den - 1) == 0, "Non-dyadic denominator")
        products.append((an * bn, den.bit_length() - 1))
    if not products:
        return Fraction(0)
    exp = max(e for _, e in products)
    num = sum(n << (exp - e) for n, e in products)
    den = 1 << exp
    divisor = gcd(abs(num), den)
    num, den = num // divisor, den // divisor
    return Fraction(num, den)


def arithmetic_self_checks() -> dict:
    subnormal = float.fromhex("0x0.0000000000001p-1022")
    examples = [([(2.0**53, 1.0), (1.0, 1.0), (-2.0**53, 1.0)], Fraction(1)),
                ([(subnormal, 1.0)], Fraction(1, 2**1074)),
                ([(0.1, 0.2), (-0.1, 0.2)], Fraction(0)),
                ([(-0.0, 17.0)], Fraction(0))]
    for pairs, expected in examples:
        direct = sum((exact_float(a) * exact_float(b) for a, b in pairs), Fraction())
        require(direct == dyadic_dot(pairs) == expected, "Arithmetic self-check failed")
    return {"passed": True, "cases": ["catastrophic float cancellation", "smallest binary64 subnormal",
                                       "signed cancellation", "negative zero"]}


def load_pinned_construct(source: Path):
    tree = ast.parse((source / "train_policy_feasibility.py").read_text())
    actions = next(node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "ACTIONS" for t in node.targets))
    construct = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == "construct")
    namespace = {"np": np}
    # Deliberately exclude all imports, solver helpers, and the main function.
    exec(compile(ast.Module(body=[actions, construct], type_ignores=[]),
                 "<hash-pinned original construct>", "exec"), namespace)
    return namespace["construct"], namespace["ACTIONS"], sha256_bytes(ast.get_source_segment(
        (source / "train_policy_feasibility.py").read_text(), construct).encode("utf-8"))


def reconstruct(source: Path):
    source_hashes(source)
    original = json.loads((source / "records/train_policy_feasibility.json").read_text())
    require(original["source_geometry_sha256"] == PINNED_SOURCES["fixtures/train_linear_geometry.npz"],
            "Original geometry provenance mismatch")
    fit = next(v for v in original["fits"] if v["fit"] == 71)
    construct, actions, construct_sha = load_pinned_construct(source)
    with np.load(source / "fixtures/train_linear_geometry.npz", allow_pickle=False) as data:
        x, oracle, mask, theta = [data["fit71_" + k] for k in ("x", "y", "mask", "theta")]
    rho = float(fit["rho_l2"])
    computed_rho = 0.5 * float(np.linalg.norm(theta[:3]))
    require(rho.hex() == computed_rho.hex(), "Stored and recomputed original radius differ")
    require(x.shape == (344, 49) and theta.shape == (4, 49), "Unexpected fit71 input geometry")
    arrays, cases = {}, []
    for prefix, expected_margin in PREFIXES:
        case = next(c for c in fit["cases"] if c["margin"] == expected_margin)
        margin = float(case["margin"])
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            A, b, ids, skipped, witnesses = construct(x, oracle, mask, theta, margin)
        require(len(b) == case["constraints"] == 1185, "Constraint-count mismatch")
        require(skipped == case["oracle_tie_rows_skipped"], "Oracle-tie selection differs")
        require(not witnesses and not case["immutable_contradictions"], "Unexpected fixed contradiction")
        A_box = np.asarray(np.vstack([A, np.eye(D), -np.eye(D)]), dtype="<f8")
        b_box = np.asarray(np.r_[b, np.full(2 * D, rho)], dtype="<f8")
        stored = case["trust_box_outer_bound"]["numeric_farkas_certificate"]
        support = stored["support"]
        indices = [int(item["constraint"]) for item in support]
        require(len(set(indices)) == len(indices), "Duplicate stored support index")
        certificate_y = np.zeros(len(b_box), dtype="<f8")
        annotated = []
        for item in support:
            i, w = int(item["constraint"]), float(item["weight"])
            require(0 <= i < len(b_box) and np.isfinite(w) and w > 1e-12, "Invalid stored support entry")
            certificate_y[i] = w
            if i < len(b):
                annotation = {"kind": "oracle_action_inequality", **ids[i]}
            elif i < len(b) + D:
                annotation = {"kind": "positive_identity_box_row", "coordinate": i - len(b)}
            else:
                annotation = {"kind": "negative_identity_box_row", "coordinate": i - len(b) - D}
            annotated.append({"constraint": i, "weight": w, "weight_hex": w.hex(),
                              "weight_exact": fraction_record(exact_float(w)), "constraint_metadata": annotation})
        arrays.update({prefix + "__A_box": A_box, prefix + "__b_box": b_box,
                       prefix + "__certificate_y": certificate_y,
                       prefix + "__rho": np.asarray(rho, dtype="<f8"),
                       prefix + "__margin": np.asarray(margin, dtype="<f8"),
                       prefix + "__oracle_constraint_count": np.asarray(len(b), dtype="<i8"),
                       prefix + "__oracle_train_row": np.asarray([i["row"] for i in ids], dtype="<i8"),
                       prefix + "__oracle_action_index": np.asarray([actions.index(i["oracle_action"]) for i in ids], dtype="<i8"),
                       prefix + "__other_action_index": np.asarray([actions.index(i["other_action"]) for i in ids], dtype="<i8"),
                       prefix + "__tie_rows_skipped": np.asarray(skipped, dtype="<i8")})
        cases.append({"prefix": prefix, "margin": margin, "margin_hex": margin.hex(),
                      "source_sparse_support": annotated,
                      "source_numerical_certificate_summary": {k: v for k, v in stored.items() if k != "support"}})
    provenance = {"input_sha256": dict(PINNED_SOURCES),
                  "source_construct_utf8_sha256": construct_sha,
                  "original_numpy_version": original["numpy"],
                  "original_scipy_version": original["scipy"],
                  "fit71_input_arrays": {k: array_provenance(v) for k, v in zip(
                      ("x", "y", "mask", "theta"), (x, oracle, mask, theta))},
                  "source_report_radius_hex": rho.hex(), "recomputed_radius_hex": computed_rho.hex(),
                  "radius_reproduction_bit_exact": True,
                  "coefficient_generation": "Hash-pinned original construct() AST; NumPy reductions and exp; then freeze all resulting binary64 values in evidence NPZ",
                  "weight_generation": "Original JSON sparse support only, parsed as binary64; every missing weight is exactly zero; no normalization or optimization"}
    return arrays, cases, provenance


def calculate(arrays: dict[str, np.ndarray], prefix: str) -> dict:
    A, b, y = [arrays[prefix + "__" + key] for key in ("A_box", "b_box", "certificate_y")]
    rho = float(arrays[prefix + "__rho"])
    n = int(arrays[prefix + "__oracle_constraint_count"])
    require(A.shape == (n + 2 * D, D) and b.shape == y.shape == (n + 2 * D,), "Evidence shape mismatch")
    require(all(np.isfinite(v).all() for v in (A, b, y)), "Nonfinite evidence")
    require(np.array_equal(A[n:n+D], np.eye(D)) and np.array_equal(A[n+D:], -np.eye(D)), "Wrong box rows")
    require(np.array_equal(b[n:], np.full(2 * D, rho)), "Wrong box bounds")
    require(rho > 0, "Nonpositive box radius")
    support = np.flatnonzero(y != 0).tolist()
    weights = [exact_float(v) for v in y]
    require(all(w >= 0 for w in weights), "Negative exact dual weight")
    residual = [sum((exact_float(A[i, j]) * weights[i] for i in support), Fraction()) for j in range(D)]
    bty = sum((exact_float(b[i]) * weights[i] for i in support), Fraction())
    require(bty == dyadic_dot((b[i], y[i]) for i in support), "Independent b-dot-y check failed")
    for j in range(D):
        require(residual[j] == dyadic_dot((A[i, j], y[i]) for i in support),
                f"Independent residual coordinate {j} check failed")
    rho_exact = exact_float(rho)
    residual_l1 = sum(map(abs, residual), Fraction())
    penalty = rho_exact * residual_l1
    bound = bty + penalty
    y_l2_squared = sum((w * w for w in weights), Fraction())
    require(bound < 0, "Stored witness does not prove this bounded system infeasible")
    return {"oracle_constraint_count": n, "box_constraint_count": 2 * D,
            "total_constraint_count": len(b), "dimension": D,
            "rho": fraction_record(rho_exact), "rho_hex": rho.hex(),
            "weight_checks": {"all_exactly_nonnegative": True, "minimum": fraction_record(min(weights)),
                              "support_count": len(support), "zero_count": len(y) - len(support),
                              "l1_norm": fraction_record(sum(map(abs, weights), Fraction())),
                              "linf_norm": fraction_record(max(map(abs, weights))),
                              "l2_norm_squared": fraction_record(y_l2_squared),
                              "l2_norm_interval": sqrt_decimal_interval(y_l2_squared)},
            "A_transpose_y": [fraction_record(v) for v in residual],
            "A_transpose_y_nonzero_components": sum(v != 0 for v in residual),
            "A_transpose_y_l1_norm": fraction_record(residual_l1),
            "A_transpose_y_linf_norm": fraction_record(max(map(abs, residual))),
            "b_dot_y": fraction_record(bty),
            "rho_times_residual_l1": fraction_record(penalty),
            "certificate_upper_bound": fraction_record(bound),
            "exactly_negative_upper_bound": True,
            "conclusion": "The serialized finite IEEE coefficient system has no real solution inside the stated closed box.",
            "independent_integer_dyadic_verification": {"b_dot_y_matches": True, "residual_components_matched": D}}


def verify(directory: Path, source: Path | None = None) -> dict:
    report = json.loads((directory / REPORT_NAME).read_text())
    require(sha256_file(directory / EVIDENCE_NAME) == report["evidence_npz_sha256"], "Evidence archive hash mismatch")
    require(sha256_file(Path(__file__)) == report["generator_script_sha256"], "Generator script hash mismatch")
    with np.load(directory / EVIDENCE_NAME, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    manifest = {key: array_provenance(value) for key, value in sorted(arrays.items())}
    require(manifest == report["array_manifest"], "Evidence array hash mismatch")
    self_checks = arithmetic_self_checks()
    for case in report["cases"]:
        prefix = case["prefix"]
        reconstructed_y = np.zeros_like(arrays[prefix + "__certificate_y"])
        for item in case["source_sparse_support"]:
            require(float(item["weight"]).hex() == item["weight_hex"], "Stored weight hex mismatch")
            require(fraction_record(exact_float(item["weight"])) == item["weight_exact"], "Stored weight rational mismatch")
            reconstructed_y[item["constraint"]] = float(item["weight"])
        require(np.array_equal(reconstructed_y, arrays[prefix + "__certificate_y"]), "Sparse weight reconstruction mismatch")
        require(calculate(arrays, prefix) == case["exact_check"], "Exact arithmetic report mismatch")
    source_status = "not requested; standalone evidence verification completed"
    if source is not None:
        rebuilt_arrays, rebuilt_cases, rebuilt_provenance = reconstruct(source)
        require(rebuilt_provenance == report["source_provenance"], "Source provenance mismatch")
        require(set(rebuilt_arrays) == set(arrays), "Reconstructed array set differs")
        for key in arrays:
            require(array_provenance(arrays[key]) == array_provenance(rebuilt_arrays[key]),
                    f"Source coefficient reconstruction differs: {key}")
        for actual, rebuilt in zip(report["cases"], rebuilt_cases):
            require({k: v for k, v in actual.items() if k != "exact_check"} == rebuilt, "Source certificate support differs")
        source_hashes(source)
        source_status = "all three pinned source hashes matched; every evidence array reproduced bit for bit; original sparse supports matched"
    return {"verified": True, "fit": 71, "margins": [c["margin"] for c in report["cases"]],
            "exactly_infeasible_cases": len(report["cases"]), "source_verification": source_status,
            "arithmetic_self_checks": self_checks, "optimizer_called": False}


def build(directory: Path, source: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    arrays, cases, provenance = reconstruct(source)
    for case in cases:
        case["exact_check"] = calculate(arrays, case["prefix"])
    with (directory / (EVIDENCE_NAME + ".tmp")).open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    (directory / (EVIDENCE_NAME + ".tmp")).replace(directory / EVIDENCE_NAME)
    report = {"schema": "hepta-fit71-exact-ieee-box-certificate-v1", "fit": 71,
              "scope": "Finite TRAIN-state inequalities reconstructed from pinned stored IEEE fixtures; frozen features and belief; exactly 147 continuation deltas within the original componentwise box",
              "not_claimed": ["exact source real arithmetic before IEEE coefficient construction", "continuous-state or continuous-law impossibility", "global model expressivity impossibility", "unrestricted continuation-head infeasibility", "holdout efficacy", "infeasibility after changing belief"],
              "theorem": "For A delta <= b, y >= 0, and |delta_j| <= rho, write r=A^T y and c=b^T y. Then -rho*||r||_1 <= r^T delta <= c. Therefore c+rho*||r||_1 < 0 is a contradiction. This permits nonzero r and requires no exact Farkas stationarity.",
              "box_row_order": "1185 oracle inequalities, 147 +I upper bounds, 147 -I lower bounds",
              "oracle_tie_tolerance": 1e-10, "oracle_tie_rows_skipped": 11,
              "coefficient_semantics": "Each serialized binary64 coefficient is interpreted as its exact Fraction.from_float rational; real unknown deltas may vary over the entire closed box",
              "radius_semantics": "Exact binary64 radius stored in original JSON, bit-identical here to 0.5*float(np.linalg.norm(theta[:3])); no assertion that the rounded radius equals an unrounded real Euclidean norm",
              "source_provenance": provenance,
              "generator_script_sha256": sha256_file(Path(__file__)),
              "runtime": {"python": platform.python_version(), "numpy": np.__version__, "byteorder": sys.byteorder},
              "evidence_file": EVIDENCE_NAME, "evidence_npz_sha256": sha256_file(directory / EVIDENCE_NAME),
              "array_manifest": {k: array_provenance(v) for k, v in sorted(arrays.items())},
              "verification": {"arithmetic_self_checks": arithmetic_self_checks(),
                               "all_dot_products_crosschecked_using_integer_dyadic_accumulation": True,
                               "source_hashes_unchanged_at_build_end": source_hashes(source) == PINNED_SOURCES},
              "work_performed": {"optimizer_calls": 0, "new_model_candidates": 0, "training_runs": 0, "holdout_reads": 0},
              "cases": cases}
    (directory / REPORT_NAME).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    result = verify(directory, source)
    lines = ["# fit71: exact finite IEEE box infeasibility certificates", "",
             "Both original stored sparse witnesses certify infeasibility after exact rational evaluation and a conservative correction for their nonzero stationarity residuals. No LP was solved, no candidate was generated, and no training or holdout evaluation was run.", "",
             "## Result", "",
             "| Margin | Stored positive weights | Exact-residual L1 (approx.) | b^T y (approx.) | Conservative upper bound |", "|---:|---:|---:|---:|---:|"]
    for c in cases:
        q = c["exact_check"]
        lines.append(f"| {c['margin']} | {q['weight_checks']['support_count']} | {q['A_transpose_y_l1_norm']['nearest_binary64_display']:.16g} | {q['b_dot_y']['nearest_binary64_display']:.16g} | <= {q['certificate_upper_bound']['decimal_upper']} |")
    lines += ["", "The last column is rounded upward using Decimal ROUND_CEILING; it remains strictly negative. Exact numerators and denominators, all 147 residual coordinates, exact weight norms, and interval displays are in `exact_certificate.json`.", "",
              "The original box radius is the exact binary64 value `" + provenance["source_report_radius_hex"] + "` (approximately 0.6276000738520313). There are 1,185 oracle inequalities plus 294 explicit box inequalities, with 147 real unknowns. Eleven oracle-tie rows are excluded under the original tolerance. Missing support weights are exactly zero; the retained weights are not renormalized.", "",
              "## Proof", "",
              "Let the saved coefficient system be A delta <= b, with explicit box constraints |delta_j| <= rho. For the saved nonnegative witness y, define r=A^T y and c=b^T y. Any feasible delta would satisfy", "",
              "    -rho * sum_j |r_j| <= r^T delta = y^T A delta <= y^T b = c.", "",
              "The exact calculation gives c + rho * sum_j |r_j| < 0 in both cases, which is a contradiction. The proof does not require A^T y to vanish. Every multiply and sum in this check uses Fraction.from_float, and every dot product is independently recomputed by aligned integer arithmetic on dyadic float ratios.", "",
              "## Exact negative bounds", ""]
    for c in cases:
        bnd = c["exact_check"]["certificate_upper_bound"]
        lines += [f"Margin {c['margin']}:", "", f"`{bnd['numerator']} / {bnd['denominator']}`", ""]
    lines += ["## Provenance and scope", "",
              "The pinned original `construct()` is extracted from its AST; optimizer helpers and the main program are never executed or imported. It reconstructs the finite binary64 coefficients from the pinned TRAIN fixture. The resulting coefficients are frozen in `fit71_ieee_box_evidence.npz`, and this certificate is exact for those serialized values. The original source did not supply a separately archived A,b matrix; equality to its mathematical real-arithmetic construction is not asserted.", "",
              "The three source-file SHA-256 values and every evidence array's SHA-256, shape, and dtype are recorded in JSON. Source reconstruction reproduced every stored evidence array bit for bit in this runtime (NumPy " + np.__version__ + "), including the original stored radius. The source folder remains unchanged.", "",
              "This proves infeasibility for these two finite coefficient systems and this closed componentwise box, with features, belief, and fixed STOP/SUBMIT scores frozen. It also rules out any smaller domain contained in this exact box. It does not prove unrestricted-head, changed-belief, continuous-law, or global-model impossibility, nor any holdout claim. The rounded binary64 radius is the domain definition; it is not identified with an unrounded real Euclidean norm.", "",
              "## Reproduction", "",
              "Requirements: Python >=3.10 and NumPy. The recorded generation runtime uses NumPy " + np.__version__ + ". A future platform can verify the saved coefficients without rerunning NumPy coefficient construction.", "",
              "```bash", "python exact_box_certificate.py verify", "python exact_box_certificate.py verify --source-dir ../../hepta_private_ci_delivery", "python exact_box_certificate.py build --source-dir ../../hepta_private_ci_delivery", "```", "",
              "`verify` checks the generator hash, NPZ hash, every numeric array hash, exact sparse-weight reconstruction, all exact certificate values, the independent integer dot products, and cancellation/subnormal arithmetic checks. Supplying `--source-dir` additionally checks the three pinned original hashes and reproduces every numeric array. `build` overwrites only this certificate directory's generated outputs.", ""]
    (directory / "README.md").write_text("\n".join(lines))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "build":
        source = args.source_dir or Path(__file__).resolve().parents[2] / "hepta_private_ci_delivery"
        result = build(args.directory, source)
    else:
        result = verify(args.directory, args.source_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
