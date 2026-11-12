"""Audit frozen first-cycle DDE receipts against independent analytic references.

No spatial model, DDE solver, adapter, training or checkpoint is imported/run.
The frozen phase fixture is not a new whole-law or long-horizon qualification.
"""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import platform
import resource
import time
import mpmath as mp
import numpy as np
from . import analytic_reference

CASES = (
    ("new-near800-atol14-001", 0.32, "8770697d4f0a533319b03286f59cf27a964332e1982c5074891d991e26f6f722"),
    ("new-near800-atol16-001", 0.32, "fea8c54eae15065d7e959e64a90fef7d64be510fd9b905b0fd4b867dfb4e3fa2"),
    ("new-near800-atol18-001", 0.32, "8c9daf9d14eef1eff60906a252ca0aa9632b267665f2f4edce10b27c4a5ffaba"),
    ("new-near960-atol18-001", 0.32725, "6afdbbcaf7ae4a76676e6abc3b2d19ba170b4075f685a3e2f8dc0ebbca954705"),
)
FLOOR = 1e-12


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binary(value):
    return mp.mpf(float(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persisted-source-commit", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__).resolve(), Path(inspect.getfile(analytic_reference)).resolve()]
    before = {str(p): digest(p) for p in sources}
    started, cpu = time.perf_counter(), time.process_time()
    inputs, original_sources, refs, output_rows = {}, {}, {}, []
    descriptors = {}
    for identity, reset, expected in CASES:
        folder = args.repository_root / "qualification/hcsn_dense_reproduction/evidence" / identity
        raw_path, summary_path = folder / "RAW.npz", folder / "SUMMARY.json"
        if digest(raw_path) != expected:
            raise ValueError("retained original byte identity changed")
        inputs[str(raw_path)] = digest(raw_path)
        inputs[str(summary_path)] = digest(summary_path)
        summary = json.loads(summary_path.read_text())
        if (summary["reset"] != reset or not summary["source_unchanged"]
                or summary["source_sha256_before"] != summary["source_sha256_after"]):
            raise ValueError("retained fixture/source descriptor changed")
        for old_path, old_digest in summary["source_sha256_before"].items():
            relative = "qualification/" + old_path.split("/qualification/", 1)[1]
            path = args.repository_root / relative
            if digest(path) != old_digest:
                raise ValueError("published retained execution source changed")
            original_sources[str(path)] = old_digest
        descriptors[identity] = {"profile": summary["profile"], "reset": reset,
                                "rtol": summary["rtol"], "atol": summary["atol"],
                                "retained_wall_seconds": summary["wall_seconds"]}
        with np.load(raw_path, allow_pickle=False) as archive:
            data = {key: archive[key].copy() for key in archive.files}
        if not np.array_equal(data["time"], [0.001, 0.003, 0.02, 0.04, 0.08, 0.16]):
            raise ValueError("fixed retained observation schedule changed")
        for i, t in enumerate(data["time"]):
            key = (reset, float(t))
            if key not in refs:
                low = analytic_reference.reference(reset, float(t), 80)
                high = analytic_reference.reference(reset, float(t), 120)
                refs[key] = (low, high)
            low, high = refs[key]
            with mp.workdps(120):
                values = {
                    "M": binary(data["dde_events"][i, 0]),
                    "H": binary(data["dde_discounted_events"][i, 0]),
                    "R": binary(data["dde_refractory"][i, 0]),
                    "A": binary(data["dde_discounted_active_time"][i, 0]),
                    "Z": binary(data["dde_discounted_remaining_phase"][i, 0]),
                    "Pactive": binary(data["dde_active"][i, :, 0].sum() + data["dde_upper"][i, 0]),
                }
                r = {name: mp.mpf(value) for name, value in high.items()}
                q, delay, width, time_value = map(binary, (0.15, 0.2, 0.025, t))
                unreleased = max(mp.mpf(0), 1 - time_value / width)
                released_discount = -mp.expm1(-q * min(time_value, width)) / (q * width)
                phase_initial = -mp.expm1(-q * max(width - time_value, 0)) / (q * width)
                # These differences diagnose precision; subtraction does not
                # restore information absent from the stored FP64 state.
                values["Z_newhit"] = values["Z"] - phase_initial
                values["A_hit_loss"] = r["A_release_only"] - values["A"]
                constraints = {
                    "R_minus_unreleased_minus_M": values["R"] - unreleased - values["M"],
                    "Pactive_plus_M_minus_released": values["Pactive"] + values["M"] - (1 - unreleased),
                    "discounted_active_balance": q * values["A"] - released_discount + values["H"] + mp.exp(-q * time_value) * values["Pactive"],
                    "Z_minus_initial_minus_discounted_H": values["Z"] - phase_initial - mp.exp(-q * (delay - time_value)) * values["H"],
                }
                quantities = {}
                for name, actual in values.items():
                    reference = r[name]
                    error = abs(actual - reference)
                    eligible = abs(reference) >= binary(FLOOR)
                    low_value = mp.mpf(low[name])
                    quantities[name] = {
                        "retained": mp.nstr(actual, 40),
                        "continuum_reference_120": high[name],
                        "absolute_error": mp.nstr(error, 40),
                        "relative_reference_floor": FLOOR,
                        "relative_diagnostic_eligible": bool(eligible),
                        "relative_error": mp.nstr(error / abs(reference), 40) if eligible else None,
                        "reference_80_vs_120_relative": mp.nstr(abs(low_value - reference) / abs(reference), 40) if reference else "0",
                    }
                linearity = {}
                for field in ("active", "upper", "refractory", "events", "discounted_events",
                              "discounted_active_time", "discounted_remaining_phase"):
                    value = data["dde_" + field][i]
                    linearity[field] = float(np.max(np.abs(value[..., 1] + 0.7 * value[..., 0])))
                output_rows.append({
                    "case": identity, "time": float(t), "reset": reset,
                    "quantities": quantities,
                    "retained_identity_residuals": {k: mp.nstr(v, 40) for k, v in constraints.items()},
                    "Z_balance_absolute_over_reference_newhit": mp.nstr(abs(constraints["Z_minus_initial_minus_discounted_H"]) / r["Z_newhit"], 40)
                        if r["Z_newhit"] >= binary(FLOOR) else None,
                    "signed_mark_linearity_absolute": linearity,
                })
    after = {str(p): digest(p) for p in sources}
    unchanged = all(digest(p) == h for p, h in inputs.items())
    if before != after or not unchanged:
        raise RuntimeError("new source or retained input changed during read-only audit")
    refs_output = [{"reset": key[0], "time": key[1], "80_digits": lo, "120_digits": hi}
                   for key, (lo, hi) in refs.items()]
    (args.output / "REFERENCE.json").write_text(json.dumps(refs_output, indent=2) + "\n")
    (args.output / "ROWS.json").write_text(json.dumps(output_rows, indent=2) + "\n")
    result = {
        "schema": "retained-firstcycle-independent-math-v1",
        "status": "HOLD_NO_GO", "all_closed": False, "prospective_gate": False,
        "retained_source_head": "49db2c4ae2b10077d261896979f8df9e53f69822",
        "persisted_source_commit": args.persisted_source_commit,
        "retained_runs": len(CASES), "retained_query_rows": len(output_rows),
        "unique_continuum_reference_cases": len(refs),
        "oracle_precisions": [80, 120], "fixture_descriptors": descriptors,
        "new_model_calls": 0, "new_dde_runs": 0, "new_spatial_rollouts": 0,
        "new_training_calls": 0, "mesh_changes": 0,
        "source_sha256_before": before, "source_sha256_after": after,
        "retained_execution_sources": original_sources,
        "retained_input_sha256": inputs, "retained_inputs_unchanged": unchanged,
        "output_sha256": {name: digest(args.output / name) for name in ("REFERENCE.json", "ROWS.json")},
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "versions": {"python": platform.python_version(), "mpmath": mp.__version__, "numpy": np.__version__},
        "scope": "Independent constant-physics continuum first-cycle M/H/R/A and remaining-phase moment, compared to already-retained synthetic fixture states. No new trajectory.",
        "limits": ["post-failure exposed development diagnostic; no new pass gate",
                   "fixed phase U[0,.025], two resets, T<=.16<delay, fixed physics only",
                   "no relative qualification below unchanged1e-12 reference floor",
                   "total R/Z/A precision cannot establish rare-component precision",
                   "80/120-digit numerical agreement is not an interval proof",
                   "no long-horizon delayed renewal, whole old-state filtering or gradients"],
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("retained_runs", "retained_query_rows",
                                            "unique_continuum_reference_cases", "wall_seconds",
                                            "new_model_calls", "status")}))


if __name__ == "__main__":
    main()
