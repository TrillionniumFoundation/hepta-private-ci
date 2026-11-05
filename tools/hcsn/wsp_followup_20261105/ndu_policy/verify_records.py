"""Independent stored-norm, quadratic, gate and df=4 interval reconstruction.

Does not rerun model features, Bellman compilation or environment trajectories.
Its Student-t critical values use the closed df=4 CDF, not the experiment's
SciPy stats/variance routines. Full data provenance requires the frozen replay.
"""
import argparse
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import numpy as np


def read(path):
    if path.exists():
        payload = path.read_bytes()
    else:
        manifest = json.loads(path.with_name(path.name+".parts.json").read_text()); chunks = []
        for item in manifest["parts"]:
            chunk = path.with_name(item["name"]).read_bytes()
            assert len(chunk) == item["bytes"] and hashlib.sha256(chunk).hexdigest() == item["sha256"]
            chunks.append(chunk)
        payload = b"".join(chunks)
        assert len(payload) == manifest["bytes"] and hashlib.sha256(payload).hexdigest() == manifest["sha256"]
    return json.loads(gzip.decompress(payload) if path.name.endswith(".gz") else payload)


def critical_df4(probability):
    low, high = 0., 1.
    for _ in range(100):
        z = (low + high) / 2
        if .5 + .75*z - .25*z**3 < probability:
            low = z
        else:
            high = z
    z = (low + high) / 2
    return 2*z / math.sqrt(1-z*z)


def squared(values):
    return sum((Fraction.from_float(float(x))**2 for x in np.ravel(values)), Fraction(0))


def verify(root, protocol_path, history_root):
    protocol, results = read(protocol_path), read(root / "RESULTS.json")
    identity = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    assert identity == results["protocol_sha256"] == read(root / "STARTED.json")["protocol_sha256"]
    source = read(root / "STARTED.json")["sources"]
    for filename in ("planning.py", "quadratic.py", "run_experiment.py"):
        assert source["new/"+filename] == protocol["source"]["new_code_sha256"][filename]
    gates, fitted = read(root / "ALL_GATES_BEFORE_TEST.json"), {}
    catalog = read(root / "ALL_CANDIDATES_BEFORE_VALIDATION.json")
    numeric_results = []
    flat = (history_root / "HISTORY_REGISTRY.json.gz").exists()
    registry_path = history_root / "HISTORY_REGISTRY.json.gz" if flat else history_root / "analytic_belief_compile/HISTORY_REGISTRY.json.gz"
    heads_path = history_root / "OLD_CONTINUATION_HEADS.json.gz" if flat else history_root / "exploratory_belief/OLD_CONTINUATION_HEADS.json.gz"
    historical_worlds = sorted((history_root if flat else history_root / "analytic_belief_compile/records").glob("fit_*_*_WORLDS.json.gz"))
    assert len(historical_worlds) == 10
    source_hashes = {x.name: hashlib.sha256(x.read_bytes()).hexdigest() for x in (registry_path, heads_path, *historical_worlds)}
    assert source_hashes == protocol["source"]["history_inputs_sha256"] == read(root / "HISTORY_EXCLUSION.json")["sources"]
    history = read(registry_path); fields = history["canonical_schedule_fields"]
    def schedule_hash(world):
        encoded = json.dumps({k: world[k] for k in fields}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()
    known = set()
    for entry in history["entries"]:
        assert schedule_hash(entry["world"]) == entry["schedule_sha256"]
        known.add(entry["schedule_sha256"])
    for filename in historical_worlds:
        known.update(schedule_hash(world) for world in read(filename))
    assert len(known) == 1936
    seen = set(known)
    for split, count in (("validation", 16), ("test", 32)):
        receipt = read(root / (split.upper()+"_DEDUP_BEFORE_SCORING.json"))
        for fit in protocol["source"]["fit_ids"]:
            for domain in ("iid", "ood"):
                payload = read(root / f"worlds/{split}_{fit}_{domain}.json.gz")
                expected_seed = int(hashlib.sha256(json.dumps([identity, fit, split, domain, "public-schedule"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(), 16)
                assert payload["seed"] == str(expected_seed) and len(payload["worlds"]) == count
                hashes = [schedule_hash(world) for world in payload["worlds"]]
                assert hashes == receipt["hashes"][str(fit)][domain]
                rows = read(root / f"{split}_{fit}_{domain}_RESULTS.json.gz")["records"]
                assert len(rows) == count
                for world, digest, row in zip(payload["worlds"], hashes, rows):
                    assert digest not in seen and digest == row["schedule_sha256"] and world["id"] == row["world_id"]
                    seen.add(digest)
        assert receipt["collisions"] == 0 and receipt["all_seen_unique"] == len(seen)
    maximum_gradient_error, maximum_objective_difference_error = 0., 0.
    for fit in protocol["source"]["fit_ids"]:
        record = read(root / f"fit_{fit}_CANDIDATES.json.gz"); heads = {k: np.asarray(v) for k, v in record["heads"].items()}
        assert catalog[str(fit)] == record["models"]
        fitted[fit] = heads
        incumbent = read(root / f"models/fit_{fit}_C.json.gz")
        for name in ("A", "C", "D", "G", "DQ", "DB", "R"):
            model = read(root / f"models/fit_{fit}_{name}.json.gz")
            raw = (json.dumps(model, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()
            assert hashlib.sha256(raw).hexdigest() == record["models"][name]["model_sha256"]
            theta = np.c_[np.asarray(model["network"]["w2"]), np.asarray(model["network"]["b2"])]
            assert np.array_equal(theta, heads[name])
            model["network"]["w2"] = incumbent["network"]["w2"]
            model["network"]["b2"] = incumbent["network"]["b2"]
            assert model == incumbent
        for group, selection in (("continuation", slice(0, 3)), ("belief", slice(3, 4))):
            problem = record["problems"][group]; original = heads["C"][selection]
            matrices, rhs, radius = np.asarray(problem["matrices"]), np.asarray(problem["rhs"]), problem["radius"]
            assert np.array_equal(original, np.asarray(problem["original"]))
            bound = squared(original)/4; safe = Fraction.from_float(radius)**2; assert safe <= bound
            objectives = {}
            for name in ("D", "G", "R", "DQ", "DB"):
                actual = sum(((Fraction.from_float(float(x))-Fraction.from_float(float(y)))**2
                              for x, y in zip(heads[name][selection].flat, original.flat)), Fraction(0))
                assert actual <= bound and actual <= safe
                if name not in ("D", "G"):
                    continue
                delta = heads[name][selection] - original
                gradient = 2*np.array([matrix @ d - g for matrix, d, g in zip(matrices, delta, rhs)])
                saved = record["solvers"][group]["direct" if name == "D" else "gradient"]
                error = float(np.max(abs(gradient-np.asarray(saved["gradient"])))); maximum_gradient_error = max(maximum_gradient_error, error)
                assert error <= 2e-10
                gap = float(np.sum(gradient*delta) + radius*np.linalg.norm(gradient))
                assert abs(gap-saved["numerical_fw_gap"]) <= 2e-10
                assert saved["converged"] == (-1e-12 <= saved["numerical_fw_gap"] <= 1e-8)
                numeric_results.append(saved["converged"])
                objectives[name] = math.fsum(float(d @ a @ d - 2*g @ d) for a, d, g in zip(matrices, delta, rhs))
            saved = record["solvers"][group]
            error = abs((objectives["D"]-objectives["G"])-(saved["direct"]["objective"]-saved["gradient"]["objective"]))
            maximum_objective_difference_error = max(maximum_objective_difference_error, error); assert error <= 2e-10
        for name in ("D", "G", "R"):
            differences = []
            for domain in ("iid", "ood"):
                validation = read(root / f"validation_{fit}_{domain}_RESULTS.json.gz")
                difference = math.fsum(r["arms"][name]["utility"]-r["arms"]["C"]["utility"] for r in validation["records"])/validation["world_count"]
                assert abs(difference-gates[str(fit)][name]["delta"][domain]) < 2e-13; differences.append(difference)
            selected = gates[str(fit)][name]
            expected_numeric = name == "R" or all(record["solvers"][g]["direct" if name == "D" else "gradient"]["converged"] for g in ("continuation", "belief"))
            assert selected["numeric_pass"] == expected_numeric
            assert selected["accepted"] == (selected["numeric_pass"] and min(differences) >= 0 and statistics.mean(differences) >= .005)
    maximum_interval_difference = 0.
    for domain in ("iid", "ood"):
        for name in ("D_gated", "J"):
            differences = []
            for fit in protocol["source"]["fit_ids"]:
                data = read(root / f"test_{fit}_{domain}_RESULTS.json.gz")
                for row in data["records"]:
                    for candidate in ("D", "G", "R"):
                        actual = candidate if gates[str(fit)][candidate]["accepted"] else "C"
                        assert row["arms"][candidate+"_gated"]["utility"] == row["arms"][actual]["utility"]
                differences.append(math.fsum(r["arms"][name]["utility"]-r["arms"]["C"]["utility"] for r in data["records"])/data["world_count"])
            mean = statistics.mean(differences); half = critical_df4(1-.05/8)*statistics.stdev(differences)/math.sqrt(5)
            interval = [mean-half, mean+half]; saved = results["primary"][name+"_"+domain]
            error = max(abs(a-b) for a, b in zip(interval, saved["familywise_95_interval"]))
            maximum_interval_difference = max(maximum_interval_difference, error); assert error < 2e-12
            assert saved["benefit_pass"] == (interval[0] > .005)
    assert not results["full_economic_net_value_qualified"] and not results["production_qualified"]
    assert results["all_numeric_pass"] == all(numeric_results)
    assert results["weight_efficacy_qualified"] == (all(numeric_results) and all(results["primary"]["D_gated_"+d]["benefit_pass"] for d in ("iid", "ood")))
    assert results["structural_efficacy_qualified"] == all(results["primary"]["J_"+d]["benefit_pass"] for d in ("iid", "ood"))
    assert results["known_history_unique"] == len(known) and results["final_seen_unique"] == len(seen)
    return dict(schema="hepta-own-bellman-independent-record-verification-v1", passed=True,
                max_gradient_linf=maximum_gradient_error, max_quadratic_objective_difference_error=maximum_objective_difference_error,
                max_primary_interval_difference=maximum_interval_difference, critical_df4_bonferroni4=critical_df4(1-.05/8),
                fixed_parameter_norms_exact=True, gated_restoration_utilities_exact=True,
                known_history_unique=len(known), new_schedules=len(seen)-len(known), known_and_internal_schedule_collisions=0,
                historical_scope=history["not_covered"], candidate_and_qualification_bindings_verified=True,
                no_model_feature_Bellman_or_trajectory_reexecution=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("run", type=Path); parser.add_argument("protocol", type=Path)
    parser.add_argument("--history", required=True, type=Path)
    args = parser.parse_args(); print(json.dumps(verify(args.run, args.protocol, args.history), sort_keys=True))
