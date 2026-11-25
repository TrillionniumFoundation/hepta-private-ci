"""Independent NumPy recomputation of all projected-kernel saved arrays.

Never imports Torch or the model. Physical diagnostics beyond the saved final
state remain explicitly attributed to the original execution, not replayed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


FIELDS = {"logits", "features", "parameter_vjp", "input_vjp", "state_density",
          "state_boundary", "state_drift", "state_cost", "state_message"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def audit(root, source, output):
    started, cpu = time.perf_counter(), time.process_time()
    protocol, execution = read(root/"PROTOCOL.json"), read(root/"EXECUTION.json")
    if protocol["schema"] != "hcsn-bounded-joint-projection-v1":
        raise ValueError("unexpected projection protocol")
    expected_cases = [[n, 12, 8] for n in (8, 32, 64)]+[[n, 2048, 1] for n in (8, 32, 64)]+[[64, 512, 1]]
    if protocol["cases"] != expected_cases:
        raise ValueError("changed original seven-case roster")
    for name, sha in protocol["source_hashes"].items():
        if digest(source/name) != sha:
            raise ValueError("changed numerical source: "+name)
    if len(execution["cases"]) != len(expected_cases):
        raise ValueError("incomplete terminal process roster")
    records, arrays, byte_count, report_error = [], 0, 0, 0.
    for spec in expected_cases:
        n, length, batch = spec
        folder = root/f"n{n}-t{length}-b{batch}-native32"
        row = read(folder/"RESULT.json")
        if (row["case"] != folder.name or [row["neurons"], row["length"], row["batch"]] != spec
                or row["precision"] != "native32"):
            raise ValueError("case header differs from frozen roster")
        success, failures = set(row["implementations"]), set(row["failures"])
        if success & failures or success|failures != {"normalized", "projected", "fp64_reference"}:
            raise ValueError("missing, duplicate or unknown implementation")
        if set(row["raw_files"]) != {name+".npz" for name in success}:
            raise ValueError("raw array roster differs from success records")
        loaded = {}
        for filename, sha in row["raw_files"].items():
            path = folder/filename
            if digest(path) != sha:
                raise ValueError("raw array SHA mismatch")
            with np.load(path, allow_pickle=False) as data:
                if set(data.files) != FIELDS:
                    raise ValueError("incomplete raw state/VJP fields")
                values = {name: data[name].copy() for name in data.files}
            if any(a.dtype != np.float64 or not np.isfinite(a).all() for a in values.values()):
                raise ValueError("nonfinite or unsupported saved array")
            loaded[filename[:-4]] = values
            arrays += len(values); byte_count += path.stat().st_size
        cases = {}
        for name in ("normalized", "projected"):
            entry = {"executed": name in success, "gate_pass": False}
            if name in failures:
                entry["failure"] = row["failures"][name]
            if name in loaded and "fp64_reference" in loaded:
                differences, rejected = {}, []
                for field in sorted(FIELDS):
                    actual, expected = loaded[name][field], loaded["fp64_reference"][field]
                    if actual.shape != expected.shape:
                        raise ValueError("reference/candidate shape mismatch")
                    delta = actual-expected
                    diff = {"max_abs": float(np.abs(delta).max()),
                            "relative_l2": float(np.linalg.norm(delta.ravel())/max(1e-12, np.linalg.norm(expected.ravel())))}
                    differences[field] = diff
                    reported = row["comparisons"][name+"_vs_fp64"][field]
                    report_error = max(report_error, *(abs(diff[k]-reported[k]) for k in diff))
                    if diff["max_abs"] > 5e-4:
                        rejected.append(field+":absolute")
                    if field.endswith("vjp") and diff["relative_l2"] > .002:
                        rejected.append(field+":relative")
                diagnostic = row["implementations"][name]["diagnostics"]
                final_mass = float(np.abs(loaded[name]["state_density"][..., 0, :].sum(-1)-1).max())
                if diagnostic["mass_error"] > 3e-5 or final_mass > 3e-5:
                    rejected.append("probability_mass")
                if name == "projected":
                    if diagnostic["projection_steps"] != length or diagnostic["raw_local_mass_defect_max"] > 2e-6:
                        rejected.append("projection_local_admission")
                    for key in ("probability_correction_l1_sum_of_step_maxima", "signed_correction_l1_sum_of_step_maxima"):
                        if not np.isfinite(diagnostic[key]) or diagnostic[key] < 0:
                            raise ValueError("invalid original correction accounting")
                entry.update(differences=differences, rejected=rejected, gate_pass=not rejected,
                             independently_recomputed_final_mass_defect=final_mass,
                             original_execution_diagnostics=diagnostic)
            cases[name] = entry
        records.append({"case": folder.name, "result_sha256": digest(folder/"RESULT.json"),
                        "raw_sha256": row["raw_files"], "implementations": cases})
    if report_error > 1e-12:
        raise ValueError("original numerical differences do not reproduce")
    result = {"schema": "hcsn-projection-independent-array-audit-v1", "cases": records,
        "protocol_sha256": digest(root/"PROTOCOL.json"), "source_hashes": protocol["source_hashes"],
        "case_count": len(records), "npz_count": sum(len(r["raw_sha256"]) for r in records),
        "arrays": arrays, "bytes": byte_count, "maximum_report_difference": report_error,
        "passes": {name: sum(r["implementations"][name]["gate_pass"] for r in records)
                   for name in ("normalized", "projected")},
        "wall_seconds": time.perf_counter()-started, "cpu_seconds": time.process_time()-cpu,
        "scope": "independent saved-array and final-state recomputation; per-step defects/cumulative corrections originate from recorded execution; no model replay or task-quality claim"}
    output.mkdir(parents=True, exist_ok=False)
    with (output/"AUDIT.json").open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False); handle.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.source, args.out)
    print(json.dumps({k: result[k] for k in ("case_count", "npz_count", "arrays", "bytes", "passes", "maximum_report_difference")}))
