"""Independent exact arithmetic over published TRAIN witness rows, no model run."""
from fractions import Fraction
import datetime
import json
import math
import time

from recalculate_frozen_records import ROOT, PKG, RUN, FITS, READS, raw, read, sha, rational, fraction_record


def main():
    start, wall = time.process_time(), time.perf_counter()
    base = PKG / "train_margin_certificate"
    manifest = read(base / "PACKAGE_SHA256.json")
    expected = {entry["path"] for entry in manifest["files"]} | {"PACKAGE_SHA256.json"}
    actual = {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}
    assert expected == actual
    for entry in manifest["files"]:
        data = raw(base / entry["path"])
        assert len(data) == entry["bytes"] and sha(data) == entry["sha256"]
    protocol = read(base / "PROTOCOL_FROZEN.json")
    assert protocol["fits"] == FITS
    records = []
    for fit in FITS:
        model_path = RUN / f"models/fit_{fit}_C.json.gz"
        assert sha(raw(model_path)) == protocol["files"]["science"][f"execution_r1/run/models/fit_{fit}_C.json.gz"]
        model = read(model_path)
        heads = [list(row) + [bias] for row, bias in zip(model["network"]["w2"][:3], model["network"]["b2"][:3])]
        center = [rational(value) for row in heads for value in row]
        radius_squared = sum((v*v for v in center), Fraction()) / 4
        report = read(base / f"execution_r1/run/producer/fit_{fit}_RESULT.json.gz")
        witness = read(base / f"execution_r1/run/producer/fit_{fit}_WITNESS.json.gz")
        reconstruction = read(base / f"execution_r1/run/producer/fit_{fit}_RECONSTRUCTION.json.gz")
        candidate = read(RUN / f"fit_{fit}_CANDIDATES.json.gz")
        for key in ["H_sha256", "Y_sha256", "W_sha256", "rows"]:
            assert reconstruction[key] == candidate[key] == protocol["expected"][str(fit)][key]
        assert reconstruction["world_count"] == 64 and reconstruction["all_original_identities_exact"]
        assert report["rows"] == reconstruction["rows"] and report["constraints"] == reconstruction["constraints"]
        upper = math.isqrt(radius_squared.numerator // radius_squared.denominator)
        if upper*upper < radius_squared:
            upper += 1
        assert upper*upper >= radius_squared
        assert 49*max(abs(c)+upper for c in center) < 2**1000
        u, subnormal = Fraction(1, 2**53), Fraction(1, 2**1074)
        gamma = 98*u/(1-98*u)
        per_head_error = [gamma*(sum((abs(x) for x in center[a*49:(a+1)*49]), Fraction())+49*upper) + 98*subnormal/(1-98*u) for a in range(3)]
        vector = [Fraction() for _ in range(147)]
        roundoff = Fraction()
        identities = set()
        for row in witness:
            y = rational(row["multiplier"])
            a, b = row["target_action"]-1, row["competitor_action"]-1
            assert y > 0 and a in range(3) and b in range(3) and a != b
            identity = (row["world_index"], row["state_index"], a, b)
            assert identity not in identities
            identities.add(identity)
            h = [rational(value) for value in row["hidden"]]
            assert len(h) == 49 and h[-1] == 1 and all(abs(x) <= 1 for x in h)
            assert row["legal"][a+1] and row["legal"][b+1]
            assert row["teacher_q"][a+1] >= row["teacher_q"][b+1]
            for j, value in enumerate(h):
                weighted = y*value
                vector[a*49+j] += weighted
                vector[b*49+j] -= weighted
            roundoff += y*(per_head_error[a]+per_head_error[b])
        dual_rhs = -sum((a*b for a, b in zip(vector, center)), Fraction())
        norm_squared = sum((x*x for x in vector), Fraction())
        right = radius_squared*norm_squared
        proof = report["exact_certificate"]
        assert fraction_record(proof["radius_squared"]) == radius_squared
        assert fraction_record(proof["radius_upper"]) == upper
        assert [fraction_record(x) for row in proof["dual_vector"] for x in row] == vector
        assert fraction_record(proof["dual_vector_squared_norm"]) == norm_squared
        assert [fraction_record(x) for x in proof["per_head_F64_absolute_error_bound"]] == per_head_error
        assert fraction_record(proof["weighted_F64_error_bound"]) == roundoff
        assert len(witness) == proof["rows"] == proof["nonzero_multipliers"] == report["search"]["nonzero_multipliers"]
        flags, ratios = {}, {}
        for label, left in [("ideal_real", dual_rhs), ("F64_necessary_relaxation", dual_rhs-roundoff)]:
            saved = proof[label]
            passes = left > 0 and left*left > right
            assert fraction_record(saved["d"]) == left and saved["d_positive"] == (left > 0)
            assert fraction_record(saved["left_squared"]) == left*left
            assert fraction_record(saved["right_squared"]) == right
            assert saved["strict_separation"] == passes and passes
            flags[label] = passes
            ratios[label] = float(left*left/right)
        mean_row = [sum((center[a*49+j] for a in range(3)), Fraction())/3 for j in range(49)]
        equal_distance = sum(((center[a*49+j]-mean_row[j])**2 for a in range(3) for j in range(49)), Fraction())
        assert fraction_record(report["equal_head"]["distance_squared"]) == equal_distance
        assert fraction_record(report["equal_head"]["radius_squared"]) == radius_squared
        assert not report["equal_head"]["weak_system_feasible"] and equal_distance > radius_squared
        assert not report["equal_head"]["first_argmax_realization_qualified"]
        assert report["status"] == "F64_NECESSARY_SYSTEM_INFEASIBLE"
        assert not report["search"]["solver_success"] and report["search"]["iterations"] == 3000
        assert not report["exact_alias_incompatible"]
        records.append({"fit": fit, "rows": report["rows"], "necessary_constraints": report["constraints"], "nonzero_witness_rows": len(witness), "exact_separation": flags, "descriptive_squared_separation_ratio": ratios, "search_success": False, "search_iterations": 3000, "feature_and_Q_reexecution_by_this_audit": False})
        print(json.dumps(records[-1]), flush=True)
    result = {
        "schema": "hepta.pr4823.independent-archived-margin-math.v1", "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "passed": True, "certificate_files_complete_and_hashed": len(expected), "fits": records,
        "TRAIN_full_rows": sum(x["rows"] for x in records),
        "necessary_constraints": sum(x["necessary_constraints"] for x in records),
        "nonzero_witness_rows": sum(x["nonzero_witness_rows"] for x in records),
        "scope": "Exact rational separation of the recorded necessary zero-margin continuation subsystem within the declared 147-parameter ball, conditional on fixed stored feature/teacher rows and stated binary64 semantics. All original artifact bytes and binding digests checked; no new hidden/Bellman/trajectory execution.",
        "does_not_prove": ["positive task-value loss lower bound", "absence of all beneficial weight edits", "global full-network impossibility", "new holdout or independent statistical confirmation", "production or external runtime qualification"],
        "search_nonconvergence_retained": True, "new_model_or_candidate_created": False,
        "audit_cpu_seconds": time.process_time()-start, "audit_wall_seconds": time.perf_counter()-wall,
        "input_identities": READS,
    }
    (ROOT / "independent-margin-math.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps({k:result[k] for k in ["passed", "certificate_files_complete_and_hashed", "TRAIN_full_rows", "necessary_constraints", "nonzero_witness_rows", "audit_cpu_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
