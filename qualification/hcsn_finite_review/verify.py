"""Read retained finite arrays and arithmetic; zero model or kernel executions."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np


def verify(root):
    report = json.loads((root / "SUMMARY.json").read_bytes())
    if (report["status"] != "EXPOSED_POST_FAILURE_DIAGNOSTIC_COMPLETE_HOLD_NO_GO"
            or report["original_positions"] != 14336 or len(report["files"]) != 4
            or report["new_prospective_gate_created"] is not False
            or report["finite_domain_qualified"] is not False
            or report["rare_phase_relative_precision_qualified"] is not False
            or report["relative_reference_floor"] != 1e-12
            or report["source_sha256_before"] != report["source_sha256_after"]
            or report["input_sha256_before"] != report["input_sha256_after"]):
        raise ValueError("retained complete diagnostic boundary/identity differs")
    with zipfile.ZipFile(root / "SOURCE_SNAPSHOT.zip") as archive:
        if set(archive.namelist()) != set(report["source_sha256_before"]):
            raise ValueError("executing-source snapshot coverage differs")
        for name, expected in report["source_sha256_before"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError("executing-source snapshot bytes differ")
    base_ids, seen, rows = None, set(), 0
    for file in report["files"]:
        if Path(file["path"]).name != file["path"]:
            raise ValueError("retained filename escapes evidence root")
        raw = (root / file["path"]).read_bytes()
        if (len(raw) != file["bytes"] or len(raw) >= 2**20
                or hashlib.sha256(raw).hexdigest() != file["sha256"]):
            raise ValueError("retained complete array identity differs")
        n = 256 if "n256" in file["path"] else 512
        law = "posterior" if "posterior" in file["path"] else "prior"
        if (n, law) in seen:
            raise ValueError("duplicate grid/law coverage")
        seen.add((n, law))
        with np.load(root / file["path"], allow_pickle=False) as arrays:
            actual, reference = arrays["candidate_M_H_R_A"], arrays["continuum_M_H_R_A"]
            if (actual.shape != (14336, 4) or reference.shape != actual.shape
                    or not np.isfinite(actual).all() or not np.isfinite(reference).all()):
                raise ValueError("full finite numerical arrays required")
            id_names = ("arm_index", "visit_index", "update_index", "position", "origin_line",
                        "episode_id", "model_sha256", "origin_line_sha256", "dt", "reset")
            ids = {name: arrays[name].copy() for name in id_names}
            if any(len(value) != 14336 for value in ids.values()):
                raise ValueError("full per-row identities required")
            if base_ids is None:
                base_ids = ids
                names = arrays["arm_names"].tolist()
                if set(names) != {f"seed{s}-{a}" for s in (11, 23, 37)
                                  for a in ("c0_b0", "c0_b1", "c1_b0", "c1_b1")}:
                    raise ValueError("original roster differs")
                for i, name in enumerate(names):
                    indices = arrays["visit_index"][arrays["arm_index"] == i]
                    expected = 1184 if name.startswith("seed23-") else 1200
                    if not np.array_equal(indices, np.arange(expected)):
                        raise ValueError("original per-arm retained coverage differs")
            elif any(not np.array_equal(value, base_ids[name]) for name, value in ids.items()):
                raise ValueError("grid/law visit identities differ")
            error = abs(actual-reference)
            expected = next(r for r in report["reports"] if r["intervals"] == n and r["law"] == law)
            metrics = {"maximum_absolute_error_M_H_R_A": np.max(error, axis=0).tolist(),
                       "mean_absolute_error_M_H_R_A": np.mean(error, axis=0).tolist(),
                       "maximum_relative_error_where_reference_at_least_1e-12": []}
            for j in range(4):
                mask = reference[:, j] >= 1e-12
                metrics["maximum_relative_error_where_reference_at_least_1e-12"].append(
                    float(np.max(error[mask, j]/reference[mask, j])) if mask.any() else None)
            if any(value != expected[name] for name, value in metrics.items()):
                raise ValueError("retained summary arithmetic differs")
            rows += len(actual)
    return {"status": "RETAINED_ARITHMETIC_CONSISTENCY_PASS",
            "arrays": 4, "grid_law_rows": rows, "original_positions": 14336,
            "new_kernel_or_model_executions": 0, "scientific_admission": "HOLD_NO_GO"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), sort_keys=True))


if __name__ == "__main__":
    main()
