#!/usr/bin/env python3
"""Audit recorded experiments without requiring favorable scientific outcomes."""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def invalid(value):
        raise ValueError("Non-finite JSON token: " + value)
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def finite(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, list):
        for item in value:
            finite(item)


def verify(results, source):
    if not __debug__:
        raise RuntimeError("Receipt auditing requires Python assertions; do not use -O or PYTHONOPTIMIZE")
    names = ["pft1", "pft2", "pft2_transport", "pft3", "pft4",
             "pft34_verification", "pft5", "pft5_protocol_checks", "pft6"]
    data = {name: read(results / (name + ".json")) for name in names}
    for value in data.values():
        finite(value)
    checks = {}
    for name, filename in (("pft1", "identifiability.py"),
                           ("pft2", "distributed.py"),
                           ("pft2_transport", "transport.py")):
        assert data[name]["script_sha256"] == sha(source / filename), name
    assert data["pft2_transport"]["dependency_sha256"] == sha(source / "distributed.py")
    for name in ("pft3", "pft4"):
        for filename, expected in data[name]["source_sha256"].items():
            assert sha(source / filename) == expected, filename
    assert data["pft34_verification"]["source_sha256"] == sha(source / "pft34_verify.py")
    assert data["pft6"]["protocol"]["source_sha256"] == sha(source / "costs.py")
    checks["source_hashes_match"] = True

    p1, p2, pt = (data[k] for k in ("pft1", "pft2", "pft2_transport"))
    expected = len(p1["configuration"]["sizes"]) * p1["configuration"]["num_seeds"]
    assert len(p1["records"]) == expected * 15
    assert all(p1["numerical_checks"].values())
    assert len(p2["records"]) == expected and len(pt["records"]) == expected
    assert all(all(row["checks"].values()) for row in p2["records"] + pt["records"])
    checks["identifiability_and_transport_contracts"] = True

    p3, p4 = data["pft3"], data["pft4"]
    cases = len(p3["widths"]) * len(p3["seeds"])
    assert len(p3["rows"]) == cases * 9 and len(p4["rows"]) == cases * 5
    assert not p3["production_qualified"] and not p4["production_qualified"]
    assert p3["gradient_check"]["passed"] and p4["gradient_check"]["passed"]
    for width in p3["widths"]:
        for seed in p3["seeds"]:
            rows = [r for r in p3["rows"] + p4["rows"]
                    if r["width"] == width and r["seed"] == seed]
            assert len({json.dumps(r["data_hashes"], sort_keys=True) for r in rows}) == 1
            assert all(0 <= r["test"]["accuracy"] <= 1 for r in rows)
    v34 = data["pft34_verification"]
    assert len(v34["rows"]) == cases
    assert max(v34["independent_checks"].values()) < 1e-9
    assert all(r["exact_parent_recovered"] for r in v34["rows"])
    checks["matched_data_and_independent_causality_checks"] = True

    p5 = data["pft5"]
    assert p5["real_cross_user_gate"] == "BLOCKED_NO_REAL_CROSS_USER_DATA"
    assert all(r["candidate_frozen_at_utc"] <= r["candidate_hash_verified_at_utc"]
               <= r["B_labels_opened_at_utc"] for r in p5["results"])
    assert all(r["candidate_unchanged"] and r["sample_id_disjoint"]
               and r["exact_XY_content_disjoint"] for r in p5["results"])
    assert data["pft5_protocol_checks"]["all_rejected"]
    freeze_count = 0
    for path in (results / "pft5_final_artifacts").glob("*/frozen/freeze.json"):
        receipt = read(path)
        assert receipt["source_sha256"] == sha(source / "cross_user.py")
        assert receipt["candidate_sha256"] == sha(path.parent / "candidate.npz")
        freeze_count += 1
    if freeze_count:
        assert freeze_count == p5["n_cases"]
    checks["cross_user_isolation_and_scope"] = True

    p6 = data["pft6"]
    candidates, rls_errors = 0, []
    for row in p6["results"]:
        assert row["remote_transfer_s"] is None and not row["actual_hepta_runtime_adoption"]
        assert row["local_end_to_end_s"] > 0
        assert row["unattributed_local_overhead_s"] >= 0
        path = (results / "pft6_final_artifacts" / f"w{row['width']}_s{row['seed']}"
                / row["mode"] / row["method"] / "candidate.npz")
        if path.exists():
            assert sha(path) == row["candidate_sha256"]
            candidates += 1
            if row["method"] == "rls":
                with np.load(path, allow_pickle=False) as z:
                    rls = z["D"].copy()
                with np.load(path.parent.parent / "ridge/candidate.npz", allow_pickle=False) as z:
                    ridge = z["D"].copy()
                error = float(np.linalg.norm(rls - ridge) / max(np.linalg.norm(ridge), 1e-15))
                assert error < 1e-9
                rls_errors.append(error)
    if candidates:
        assert candidates == len(p6["results"])
    checks["cost_accounting_and_ridge_rls_equivalence"] = True
    return {"status": "PASS_RECEIPT_AUDIT_NOT_SCIENTIFIC_ACCEPTANCE",
            "created_utc": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "pft5_frozen_candidates_verified": freeze_count,
            "pft6_candidate_files_verified": candidates,
            "maximum_ridge_rls_parameter_relative_error": max(rls_errors) if rls_errors else None,
            "artifact_presence": "local candidates available" if candidates else
            "published summary-only audit; extract evidence archives to verify candidate bytes",
            "input_sha256": {name + ".json": sha(results / (name + ".json")) for name in names},
            "source_sha256": sha(__file__)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.results.resolve(), Path(__file__).parent)
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
