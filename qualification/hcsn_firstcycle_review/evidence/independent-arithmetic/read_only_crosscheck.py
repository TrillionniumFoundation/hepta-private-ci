"""Read retained bytes and arithmetic only: no core/oracle imports or quadrature."""

import hashlib
import json
from pathlib import Path
import time

import mpmath as mp
import numpy as np


ROOT = Path("/workspace/scratch/c06d659c1e72")
NEW = ROOT / "retained-firstcycle/evidence/attempt001"
OLD = ROOT / "dense-v3-reproduction/qualification/hcsn_dense_reproduction/reference/attempt001"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    started, cpu_started = time.perf_counter(), time.process_time()
    summary = json.loads((NEW / "SUMMARY.json").read_text())
    references = json.loads((NEW / "REFERENCE.json").read_text())
    rows = json.loads((NEW / "ROWS.json").read_text())
    old_receipt = json.loads((OLD / "EXECUTION.json").read_text())
    old_reference = json.loads((OLD / "REFERENCE.stdout").read_text())
    expected = dict(summary["source_sha256_before"])
    expected.update(summary["retained_execution_sources"])
    expected.update(summary["retained_input_sha256"])
    expected.update({str(NEW / name): value for name, value in summary["output_sha256"].items()})
    expected.update({str(OLD / name): value["sha256"] for name, value in old_receipt["files"].items()})
    expected[str(OLD.parent / "phase_reference.py")] = old_receipt["source_sha256_before"]
    watched = sorted({*expected, str(NEW / "SUMMARY.json"), str(OLD / "EXECUTION.json"), str(Path(__file__).resolve())})
    before = {path: sha(path) for path in watched}
    failures = []
    if summary["source_sha256_before"] != summary["source_sha256_after"]:
        failures.append("upstream new reference source-before/source-after mismatch")
    if not summary["retained_inputs_unchanged"]:
        failures.append("upstream retained inputs were reported changed")
    if old_receipt["source_sha256_before"] != old_receipt["source_sha256_after"]:
        failures.append("upstream old reference source-before/source-after mismatch")
    for path, digest in expected.items():
        if before[path] != digest:
            failures.append(f"current saved byte mismatch: {path}")
    comparison = []
    definition_checks = []
    floor_checks = []
    retained_bounds = []
    with mp.workdps(240):
        q, width, delay = map(mp.mpf, (float(.15), float(.025), float(.2)))
        old_binary = {float(r["distance_input_text"]): r for r in old_reference["120_dps"]
                      if r["input_mode"] == "binary64"}
        for row in references:
            reset, horizon = float(row["reset"]), mp.mpf(float(row["time"]))
            r = {key: mp.mpf(value) for key, value in row["120_digits"].items()}
            if row["time"] == .02:
                old_m = mp.mpf(old_binary[reset]["positive_erfc_integral"])
                new_m = r["M"]
                old_scientific = mp.nstr(old_m, 120, min_fixed=0, max_fixed=0)
                new_scientific = mp.nstr(new_m, 120, min_fixed=0, max_fixed=0)
                old_digits = old_scientific.split("e")[0].replace(".", "").lstrip("+-")
                new_digits = new_scientific.split("e")[0].replace(".", "").lstrip("+-")
                prefix = 0
                for a, b in zip(old_digits, new_digits):
                    if a != b:
                        break
                    prefix += 1
                comparison.append({"reset": reset, "time": .02,
                    "new_scaled_pdf_fubini_M_120": row["120_digits"]["M"],
                    "old_positive_erfc_M_120": old_binary[reset]["positive_erfc_integral"],
                    "absolute_difference": mp.nstr(abs(new_m - old_m), 150),
                    "relative_difference": mp.nstr(abs(new_m - old_m) / old_m, 150),
                    "same_rounded_120_significant_digit_string": old_scientific == new_scientific,
                    "common_significant_digit_prefix": prefix,
                    "old_scientific_120": old_scientific, "new_scientific_120": new_scientific})
            released = min(horizon / width, mp.mpf(1))
            unreleased = max(1 - horizon / width, mp.mpf(0))
            zu = -mp.expm1(-q * max(width - horizon, mp.mpf(0))) / (q * width)
            k = -mp.expm1(-q * min(width, horizon)) / (q * width)
            expected_values = {
                "R_unreleased": unreleased, "R_newhit": r["M"],
                "R": unreleased + r["M"], "Pactive": released - r["M"],
                "Z_unreleased": zu, "Z_newhit": mp.exp(-q * (delay - horizon)) * r["H"],
                "Z": zu + mp.exp(-q * (delay - horizon)) * r["H"],
                "A": r["A_release_only"] - r["A_hit_loss"], "K_release": k}
            residuals = {key: abs(r[key] - value) for key, value in expected_values.items()}
            # This tolerance concerns arithmetic consistency of 120-digit
            # printed values; it is not a new candidate/scientific gate.
            arithmetic_allowance = mp.mpf("5e-118")
            for key, residual in residuals.items():
                if residual > arithmetic_allowance * max(1, abs(r[key])):
                    failures.append(f"reference definition {reset}/{float(horizon)}/{key}")
            h_bound = mp.exp(-q * horizon) * r["M"] <= r["H"] <= r["M"]
            if not h_bound:
                failures.append(f"reference H bound {reset}/{float(horizon)}")
            definition_checks.append({"reset": reset, "time": float(horizon),
                "H_lower_bound": mp.nstr(mp.exp(-q * horizon) * r["M"], 150),
                "H_upper_bound": row["120_digits"]["M"], "H_within_bounds": h_bound,
                "absolute_definition_residuals": {key: mp.nstr(value, 150) for key, value in residuals.items()},
                "qA_balance_absolute_residual": mp.nstr(abs(q * r["A"] - (k - r["H"] - mp.exp(-q * horizon) * r["Pactive"])), 150)})
        for row in rows:
            for name, record in row["quantities"].items():
                ref = mp.mpf(record["continuum_reference_120"])
                eligible = abs(ref) >= mp.mpf("1e-12")
                valid = (record["relative_reference_floor"] == 1e-12
                         and record["relative_diagnostic_eligible"] is eligible
                         and ((record["relative_error"] is not None) if eligible
                              else (record["relative_error"] is None)))
                if not valid:
                    failures.append(f"relative floor policy {row['case']}/{row['time']}/{name}")
                floor_checks.append({"case": row["case"], "time": row["time"], "quantity": name,
                                     "eligible": eligible, "policy_matches": valid})
            m, h = (mp.mpf(row["quantities"][key]["retained"]) for key in ("M", "H"))
            lower = mp.exp(-q * mp.mpf(float(row["time"]))) * m
            retained_bounds.append({"case": row["case"], "time": row["time"],
                "H_within_exact_bounds_on_retained_printed_M_H": bool(lower <= h <= m),
                "lower_margin": mp.nstr(h - lower, 100), "upper_margin": mp.nstr(m - h, 100)})
    if len(references) != 12 or len(rows) != 24 or len(comparison) != 2:
        failures.append("expected reference/retained/cross-formula coverage is incomplete")
    after = {path: sha(path) for path in watched}
    if before != after:
        failures.append("source/input changed during this read-only review")
    result = {"identity": "independent-retained-firstcycle-readonly-crosscheck-v1",
        "reviewer": "/root/hcsn_repair/review_transport", "status": "completed" if not failures else "findings",
        "failures": failures, "review_type": "same-session separate-agent arithmetic and byte check; not external custody",
        "new_model_calls": 0, "new_analytic_quadratures": 0, "core_imports": 0,
        "cross_formula_M_comparisons": comparison, "reference_definition_checks": definition_checks,
        "reference_definition_printed_arithmetic_allowance": "5e-118*max(1,abs(value)); not a model or scientific admission threshold",
        "relative_floor": "1e-12 unchanged; only abs(reference)>=floor gets a relative diagnostic",
        "relative_floor_checks": floor_checks, "retained_H_bounds": retained_bounds,
        "retained_H_bound_violation_count": sum(not r["H_within_exact_bounds_on_retained_printed_M_H"] for r in retained_bounds),
        "source_input_sha256_before": before, "source_input_sha256_after": after,
        "all_watched_bytes_unchanged": before == after,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu_started,
        "limits": "Two independent stored M formulas compared at T=.02 only. No new quadrature, candidate replay or rigorous interval proof. Total R/Z/A precision cannot certify their tiny new-hit/loss components, and retained H bounds are diagnostics rather than accuracy guarantees."}
    target = Path(__file__).with_name("REVIEW.json")
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "failures": failures,
                      "M_comparisons": comparison, "floor_checks": len(floor_checks),
                      "retained_H_bound_violations": result["retained_H_bound_violation_count"],
                      "watched_files": len(watched), "all_unchanged": before == after,
                      "review_path": str(target)}), flush=True)


if __name__ == "__main__":
    main()
