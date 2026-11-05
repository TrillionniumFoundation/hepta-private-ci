"""Audit archived bytes and arithmetic only; imports no experiment implementation.

No model, environment, teacher, optimizer, training, or native runtime executes.
All inputs are fixed published records. Stored quadratic/margin rows remain
conditional on their recorded feature provenance, explicitly reported below.
"""
from pathlib import Path
from fractions import Fraction
import copy
import datetime
import gzip
import hashlib
import json
import math
import statistics
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "package"
RUN = PKG / "ndu_policy/execution_r1/run"
FITS = [11, 23, 37, 53, 71]
DOMAINS = ["iid", "ood"]
READS = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def no_nonfinite(value):
    raise ValueError("nonfinite JSON value: " + value)


def raw(path):
    data = path.read_bytes()
    READS[str(path.relative_to(ROOT))] = {
        "bytes": len(data), "sha256": sha(data),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }
    return data


def read(path):
    if path.exists():
        data = raw(path)
    else:
        parts = read(path.with_name(path.name + ".parts.json"))
        pieces = []
        for entry in parts["parts"]:
            piece = raw(path.with_name(entry["name"]))
            assert len(piece) == entry["bytes"] and sha(piece) == entry["sha256"]
            pieces.append(piece)
        data = b"".join(pieces)
        assert len(data) == parts["bytes"] and sha(data) == parts["sha256"]
    if path.name.endswith(".gz"):
        data = gzip.decompress(data)  # gzip trailer length and CRC checked.
    return json.loads(data, object_pairs_hook=no_duplicates, parse_constant=no_nonfinite)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def critical_df4(probability):
    # Integral of the df=4 Student density after z=t/sqrt(t*t+4).
    low, high = 0.0, 20.0
    for _ in range(100):
        t = (low + high) / 2
        z = t / math.sqrt(t * t + 4)
        cdf = 0.5 + 0.75 * z - 0.25 * z**3
        if cdf < probability:
            low = t
        else:
            high = t
    return (low + high) / 2


def rational(value):
    assert not isinstance(value, bool) and math.isfinite(value)
    return Fraction.from_float(float(value))


def fraction_record(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def main():
    begin, wall = time.process_time(), time.perf_counter()
    observed = datetime.datetime.now(datetime.timezone.utc).isoformat()
    protocol = read(PKG / "ndu_policy/PROTOCOL_FROZEN.json")
    started, result = read(RUN / "STARTED.json"), read(RUN / "RESULTS.json")
    protocol_sha = sha(raw(PKG / "ndu_policy/PROTOCOL_FROZEN.json"))
    assert started["protocol_sha256"] == result["protocol_sha256"] == protocol_sha
    assert protocol["source"]["fit_ids"] == FITS
    for key, digest in started["sources"].items():
        group, name = key.split("/", 1)
        location = ROOT / "legacy/joint" / name if group == "joint" else PKG / "ndu_policy" / name
        assert sha(raw(location)) == digest, key
    history = read(ROOT / "legacy/analytic_belief_compile/HISTORY_REGISTRY.json.gz")
    fields = history["canonical_schedule_fields"]
    schedule_hash = lambda w: sha(canonical({key: w[key] for key in fields}))
    known = set()
    for row in history["entries"]:
        assert schedule_hash(row["world"]) == row["schedule_sha256"]
        known.add(row["schedule_sha256"])
    history_files = [ROOT / "legacy/analytic_belief_compile/HISTORY_REGISTRY.json.gz",
                     ROOT / "legacy/exploratory_belief/OLD_CONTINUATION_HEADS.json.gz"]
    history_files += sorted((ROOT / "legacy/analytic_belief_compile/records").glob("*.json.gz"))
    assert len(history_files) == 12
    assert {p.name: sha(raw(p)) for p in history_files} == protocol["source"]["history_inputs_sha256"]
    for file in history_files[2:]:
        known.update(schedule_hash(world) for world in read(file))
    assert len(known) == result["known_history_unique"] == 1936
    old_heads = read(history_files[1])
    seen, datasets, mean_errors = set(known), {}, []
    for split, count in [("validation", 16), ("test", 32)]:
        dedup = read(RUN / (split.upper() + "_DEDUP_BEFORE_SCORING.json"))
        for fit in FITS:
            for domain in DOMAINS:
                worlds = read(RUN / f"worlds/{split}_{fit}_{domain}.json.gz")
                data = read(RUN / f"{split}_{fit}_{domain}_RESULTS.json.gz")
                seed = int(sha(canonical([protocol_sha, fit, split, domain, "public-schedule"])), 16)
                assert worlds["seed"] == str(seed)
                assert len(worlds["worlds"]) == len(data["records"]) == data["world_count"] == count
                hashes = [schedule_hash(world) for world in worlds["worlds"]]
                assert hashes == dedup["hashes"][str(fit)][domain]
                for world, digest, record in zip(worlds["worlds"], hashes, data["records"]):
                    assert digest not in seen and digest == record["schedule_sha256"]
                    assert world["id"] == record["world_id"]
                    seen.add(digest)
                for arm, saved in data["means"].items():
                    actual = math.fsum(row["arms"][arm]["utility"] for row in data["records"]) / count
                    mean_errors.append(abs(actual - saved))
                    assert abs(actual - saved) < 2e-14
                datasets[(split, fit, domain)] = data
        assert dedup["collisions"] == 0 and dedup["all_seen_unique"] == len(seen)
    assert len(seen) == result["final_seen_unique"] == 2416
    candidates, norm_checks, numeric, costs, gate_rows = {}, [], [], [], []
    gates = read(RUN / "ALL_GATES_BEFORE_TEST.json")
    assert gates == result["gates"]
    catalog = read(RUN / "ALL_CANDIDATES_BEFORE_VALIDATION.json")
    gradient_errors, objective_errors = [], []
    for fit in FITS:
        c = read(RUN / f"fit_{fit}_CANDIDATES.json.gz")
        candidates[fit] = c
        assert c["models"] == catalog[str(fit)]
        models, heads = {}, {key: np.array(value, dtype=np.float64) for key, value in c["heads"].items()}
        incumbent = read(RUN / f"models/fit_{fit}_C.json.gz")
        for arm in ["A", "C", "D", "G", "DQ", "DB", "R"]:
            model_file = RUN / f"models/fit_{fit}_{arm}.json.gz"
            model = read(model_file)
            assert sha(raw(model_file)) == c["models"][arm]["compressed_sha256"]
            encoded = (json.dumps(model, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
            assert sha(encoded) == c["models"][arm]["model_sha256"]
            assert np.array_equal(np.c_[model["network"]["w2"], model["network"]["b2"]], heads[arm])
            restored = copy.deepcopy(model)
            restored["network"]["w2"] = incumbent["network"]["w2"]
            restored["network"]["b2"] = incumbent["network"]["b2"]
            assert restored == incumbent
            models[arm] = model
        assert c["incumbent_sha256"] == c["models"]["C"]["model_sha256"]
        # These are the old published heads, not a new solution recovered by re-fitting.
        old = {record["fit"]: record for record in old_heads["fits"]}[fit]
        assert c["source_model_sha256"] == old["source_model_sha256"]
        assert c["incumbent_sha256"] == old["candidate_model_sha256"]
        assert np.array_equal(heads["C"], np.c_[old["network_w2"], old["network_b2"]])
        assert np.array_equal(heads["DQ"][:3], heads["D"][:3]) and np.array_equal(heads["DQ"][3], heads["C"][3])
        assert np.array_equal(heads["DB"][:3], heads["C"][:3]) and np.array_equal(heads["DB"][3], heads["D"][3])
        shared = c["shared_data_bellman_feature_preparation_cpu_seconds"] + sum(s["shared_setup_cpu_seconds"] for s in c["solvers"].values())
        cost = {"fit": fit, "shared_construction_cpu_seconds": shared, "rows": c["rows"]}
        for group, selection in [("continuation", slice(0, 3)), ("belief", slice(3, 4))]:
            p = c["problems"][group]
            origin = heads["C"][selection]
            assert np.array_equal(origin, np.array(p["original"]))
            bound = sum((rational(x)**2 for x in origin.flat), Fraction()) / 4
            safe = rational(p["radius"])**2
            assert safe <= bound
            objectives = {}
            for arm in ["D", "G", "R", "DQ", "DB"]:
                distance = sum(((rational(a) - rational(b))**2 for a, b in zip(heads[arm][selection].flat, origin.flat)), Fraction())
                assert distance <= safe <= bound
                norm_checks.append({"fit": fit, "group": group, "arm": arm, "exact_stored_norm_within_safe_and_declared": True})
                if arm not in ["D", "G"]:
                    continue
                delta = heads[arm][selection] - origin
                matrix, rhs = np.array(p["matrices"]), np.array(p["rhs"])
                gradient = 2 * np.array([a @ d - r for a, d, r in zip(matrix, delta, rhs)])
                saved = c["solvers"][group]["direct" if arm == "D" else "gradient"]
                gradient_errors.append(float(np.max(np.abs(gradient - saved["gradient"]))))
                gap = float(np.sum(delta * gradient) + p["radius"] * np.linalg.norm(gradient))
                assert abs(gap - saved["numerical_fw_gap"]) < 2e-10
                assert saved["converged"] == (-1e-12 <= saved["numerical_fw_gap"] <= 1e-8)
                numeric.append(saved["converged"])
                objectives[arm] = math.fsum(float(d @ a @ d - 2 * r @ d) for a, d, r in zip(matrix, delta, rhs))
            saved = c["solvers"][group]
            objective_errors.append(abs(objectives["D"] - objectives["G"] - saved["direct"]["objective"] + saved["gradient"]["objective"]))
        for method, arm in [("direct", "D"), ("gradient", "G")]:
            solve = sum(s[method]["cpu_seconds"] for s in c["solvers"].values())
            cost[arm] = {"solver_cpu_seconds": solve, "inclusive_cpu_seconds": shared + solve + c["models"][arm]["serialize_save_load_cpu_seconds"]}
        costs.append(cost)
        for arm in ["D", "G", "R"]:
            delta = {domain: math.fsum(r["arms"][arm]["utility"] - r["arms"]["C"]["utility"] for r in datasets[("validation", fit, domain)]["records"]) / 16 for domain in DOMAINS}
            numerical = arm == "R" or all(c["solvers"][g]["direct" if arm == "D" else "gradient"]["converged"] for g in ["continuation", "belief"])
            accepted = numerical and min(delta.values()) >= 0 and statistics.mean(delta.values()) >= .005
            saved = gates[str(fit)][arm]
            assert saved["accepted"] == accepted and saved["numeric_pass"] == numerical
            assert all(abs(delta[d] - saved["delta"][d]) < 2e-13 for d in DOMAINS)
            assert not accepted and saved["rejected_restoration_verified"]
            gate_rows.append({"fit": fit, "arm": arm, "delta": delta, "accepted": accepted})
    assert max(gradient_errors) < 2e-10 and max(objective_errors) < 2e-10
    assert all(numeric) == result["all_numeric_pass"]
    resource_fields = {"arm_initialization_cpu_seconds", "cpu_seconds", "wall_seconds", "policy_cpu_seconds", "world_feature_cpu_seconds"}
    restored_rows = 0
    for fit in FITS:
        for domain in DOMAINS:
            for row in datasets[("test", fit, domain)]["records"]:
                expected = {k: v for k, v in row["arms"]["C"].items() if k not in resource_fields}
                for arm in ["D_gated", "G_gated", "R_gated"]:
                    assert {k: v for k, v in row["arms"][arm].items() if k not in resource_fields} == expected
                    restored_rows += 1
    critical = critical_df4(1 - .05 / 8)
    contrasts, auxiliary = {}, {}
    for domain in DOMAINS:
        for arm in ["J", "D_gated", "D", "G", "R", "P", "DQ", "DB", "A"]:
            diffs = [math.fsum(row["arms"][arm]["utility"] - row["arms"]["C"]["utility"] for row in datasets[("test", fit, domain)]["records"]) / 32 for fit in FITS]
            mean = statistics.mean(diffs)
            interval = [mean - critical * statistics.stdev(diffs) / math.sqrt(5), mean + critical * statistics.stdev(diffs) / math.sqrt(5)]
            item = {"per_fit": dict(zip(map(str, FITS), diffs)), "mean": mean}
            if arm in ["J", "D_gated"]:
                saved = result["primary"][arm + "_" + domain]
                assert abs(mean - saved["delta"]) < 2e-13
                assert max(abs(a-b) for a,b in zip(interval, saved["familywise_95_interval"])) < 2e-12
                assert saved["benefit_pass"] == (interval[0] > .005)
                item.update(familywise_95_interval=interval, benefit_pass=interval[0] > .005)
                contrasts[arm + "_" + domain] = item
            else:
                auxiliary[arm + "_" + domain] = item
    assert result["structural_efficacy_qualified"] and not result["weight_efficacy_qualified"]
    assert not any(result[k] for k in ["energy_qualified", "full_economic_net_value_qualified", "production_qualified"])
    cold = [row["own_bellman"] for fit in FITS for domain in DOMAINS for row in datasets[("test", fit, domain)]["records"]]
    aggregates = {arm: {key: math.fsum(row[arm][key] for row in costs) for key in ["solver_cpu_seconds", "inclusive_cpu_seconds"]} for arm in ["D", "G"]}
    output = {
        "schema": "hepta.pr4823.independent-archived-record-arithmetic.v1", "observed_at": observed,
        "source_ref": "9f2d00f79bfe7abc334e51f52a0d16f685656e5d", "passed": True,
        "no_experiment_source_imported": True, "model_or_environment_executed": False,
        "training_or_optimization_executed": False, "new_scientific_sample": False,
        "history": {"known_prior": len(known), "new_validation": 160, "new_test": 320, "all_unique": len(seen), "unknown_history": history["not_covered"]},
        "primary_unit": "5 existing fit pairs, df=4, two-sided Bonferroni family=4", "critical": critical,
        "primary": contrasts, "descriptive_raw_contrasts": auxiliary, "validation_gates": gate_rows,
        "accepted_candidates": 0, "restored_TEST_semantic_arm_records_equal_C": restored_rows,
        "resource_fields_excluded_from_semantic_equality": sorted(resource_fields),
        "model_hashes_verified": 35, "unchanged_non_head_model_fields_verified": True,
        "incumbent_matches_published_C": True, "original_A_archive_bytes_reacquired": False,
        "original_A_identity_scope": "source raw digest agrees with pinned prior-head/input receipts; normalized saved A has its own separately verified digest; no equality of those byte formats asserted",
        "exact_norm_checks": norm_checks,
        "max_saved_mean_error": max(mean_errors), "max_quadratic_gradient_error": max(gradient_errors),
        "max_quadratic_objective_difference_error": max(objective_errors),
        "costs_by_fit": costs, "costs_aggregate": aggregates,
        "inclusive_G_over_D": aggregates["G"]["inclusive_cpu_seconds"] / aggregates["D"]["inclusive_cpu_seconds"],
        "cost_scope": "shared construction charged separately to each alternative; columns cannot be added; excludes validation/startup; no equal-quality speedup",
        "J_TEST_cold": {"worlds": len(cold), "cpu_seconds": math.fsum(x["full_cold_preparation_cpu_seconds"] for x in cold), "states": sum(x["compilation"]["states"] for x in cold), "uncompressed_row_bytes": sum(x["table_bytes"] for x in cold)},
        "TRAIN_recorded_rows": sum(c["rows"] for c in candidates.values()),
        "TRAIN_recorded_worlds": sum(len(c["training_worlds"]) for c in candidates.values()),
        "boundary": ["Feature/quadratic/trajectory values are archived; this audit does not reexecute their provenance.", "Source ordering and recorded times agree with protocol-before-experiment; no separately timestamped pre-result Git publication is established.", "OOD distribution was exposed during VAL; schedule uniqueness is not proof of statistical independence.", "No change to original B18 D-B/HOLD."],
        "audit_cpu_seconds": time.process_time()-begin, "audit_wall_seconds": time.perf_counter()-wall,
        "input_identities": READS,
    }
    (ROOT / "independent-record-arithmetic.json").write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({k: output[k] for k in ["passed", "primary", "accepted_candidates", "restored_TEST_semantic_arm_records_equal_C", "costs_aggregate", "inclusive_G_over_D", "J_TEST_cold"]}, indent=2))


if __name__ == "__main__":
    main()
