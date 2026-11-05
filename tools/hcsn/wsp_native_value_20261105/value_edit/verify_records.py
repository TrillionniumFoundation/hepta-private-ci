"""Independent record checks and recursive execution; never imports the new graph/worker."""
import argparse
import copy
from fractions import Fraction
import gc
import math
from pathlib import Path
import resource
import signal
import sys
import time

import numpy as np

from artifact_io import canonical, identity, json_bytes, read, save, sha, verify_manifest
from vendor import planning as p


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def head(model):
    return np.c_[np.asarray(model["network"]["w2"]), np.asarray(model["network"]["b2"])]


def rebuild(C_model, theta):
    model = copy.deepcopy(C_model)
    model["network"]["w2"] = theta[:, :48].tolist()
    model["network"]["b2"] = theta[:, 48].tolist()
    return model


def exact_norm(theta, C, radius):
    f = lambda value: Fraction.from_float(float(value))
    delta_squared = sum(((f(a) - f(b)) ** 2 for a, b in zip(theta.flat, C.flat)), Fraction())
    declared = sum((f(x) ** 2 for x in C.flat), Fraction()) / 4
    safe = f(radius) ** 2
    def record(x):
        return dict(numerator=str(x.numerator), denominator=str(x.denominator))
    return dict(actual_squared=record(delta_squared), declared_squared=record(declared),
                safe_squared=record(safe), within_declared=delta_squared <= declared,
                within_safe=delta_squared <= safe)


def stored_point(C, delta, radius):
    candidate = np.asarray(C + delta, dtype=np.float64)
    if not exact_norm(candidate, C, radius)["within_safe"]:
        candidate = C + (candidate - C) * (1 - 1e-12)
    require(exact_norm(candidate, C, radius)["within_safe"], "reconstructed candidate exceeds radius")
    return candidate


def t4_quantile(probability):
    # Closed-form df=4 CDF inversion; independent of worker SciPy statistics.
    lo, hi = 0., 100.
    for _ in range(100):
        x = (lo + hi) / 2
        z = x / math.sqrt(4 + x * x)
        cdf = .5 + .75 * z - .25 * z ** 3
        if cdf < probability:
            lo = x
        else:
            hi = x
    return (lo + hi) / 2


def conditional_interval(differences, probability):
    mean = sum(differences) / 5
    variance = sum((x - mean) ** 2 for x in differences) / 4
    half = t4_quantile(probability) * math.sqrt(variance / 5)
    return mean, [mean - half, mean + half]


def independent_policy_evaluation(ctx, public, model, theta, arm, truth, compiled):
    """Literal head reduction and a separate recursive eight-metric evaluator."""
    features = p.WorldPolicy(ctx, public, model, None)
    names = ("utility", "fees", "reads_requested", "reads_completed", "repairs", "elapsed", "correct", "submitted")
    nodes = 0
    def recurse(state):
        nonlocal nodes
        nodes += 1
        if arm == "J":
            scores = compiled["rows"][p.markov_key(state)]["q"]
        else:
            hidden, analytic = features.feature(state)
            raw = np.sum(theta * hidden[None, :], axis=1)
            probability = float(1 / (1 + np.exp(-np.clip(raw[3], -700, 700))))
            if arm == "P":
                probability = analytic
            scores = [0., float(raw[0]), float(raw[1]), float(raw[2]), 1 - 2 * probability, 2 * probability - 1]
        legal = ctx.legal(public, state)
        action = max((i for i, good in enumerate(legal) if good), key=lambda i: scores[i])
        if action in (0, 4, 5):
            posterior = truth.posterior(state)
            correct = 0. if action == 0 else (posterior if action == 5 else 1 - posterior)
            reward = 0. if action == 0 else 2 * correct - 1
            return dict(zip(names, (reward, 0., 0., 0., 0., 0., correct, float(action != 0))))
        result = {name: 0. for name in names}
        for probability, outcome in ctx.outcomes(public, state, action, truth):
            if not probability:
                continue
            after = ctx.successor(public, state, action, outcome)
            future = recurse(after)
            fee = after["charges"] - state["charges"]
            additions = (-fee, fee, float(action == 2), len(after["history"]) - len(state["history"]),
                         float(action == 3), after["elapsed"] - state["elapsed"], 0., 0.)
            for name, addition in zip(names, additions):
                result[name] += probability * (future[name] + addition)
        return result
    result = recurse(ctx.initial(public))
    return result, nodes


def main(args):
    start, wall = time.process_time(), time.perf_counter()
    root = Path(__file__).resolve().parent
    run = args.run.resolve()
    protocol = read(root / "PROTOCOL_FROZEN.json")
    protocol_sha = sha((root / "PROTOCOL_FROZEN.json").read_bytes())
    def timeout(*_args):
        raise TimeoutError("independent verification resource cap reached")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(1200)
    resource.setrlimit(resource.RLIMIT_CPU, (900, 905))
    verify_manifest(root, protocol["source_files"])
    inputs = read(root / "INPUT_MANIFEST.json")
    verify_manifest(root, inputs["files"])
    require(read(run / "STARTED.json")["protocol_sha256"] == protocol_sha, "run protocol binding")
    require(not (run / "FAILED.json").exists(), "worker has a preserved failure")
    report = dict(protocol_sha256=protocol_sha, verification_source_sha256=sha(Path(__file__).read_bytes()),
                  new_graph_or_worker_imported=False, all_checks_pass=False)
    events, previous = [], None
    for index, path in enumerate(sorted((run / "events").glob("*.json"))):
        event = read(path)
        require(event["sequence"] == index and event["previous_sha256"] == previous, "event chain")
        payload = event["payload"]
        if "path" in payload:
            require(sha((run / payload["path"]).read_bytes()) == payload["sha256"], "event payload identity")
        previous = sha(path.read_bytes())
        events.append(event)
    kinds = [event["kind"] for event in events]
    order = [kinds.index(k) for k in ("all_candidates_frozen", "validation_generated", "all_gates_frozen", "test_generated", "results_frozen")]
    require(order == sorted(order) and len(set(order)) == 5, "candidate/holdout/gate order")
    require(kinds.count("fit_candidates_frozen") == 5, "all five candidate freezes")
    require(max(i for i, k in enumerate(kinds) if k == "fit_candidates_frozen") < order[0], "fit freeze completeness")
    report["event_chain_entries"] = len(events)
    # Independently rebuild the historical exclusion and both fresh content sets.
    registry = read(root / "inputs/history/HISTORY_REGISTRY.json.gz")
    fields = registry["canonical_schedule_fields"]
    schedule_hash = lambda public: sha(canonical({key: public[key] for key in fields}).encode())
    known = set()
    for row in registry["entries"]:
        require(schedule_hash(row["world"]) == row["schedule_sha256"], "old registry content identity")
        known.add(row["schedule_sha256"])
    for path in sorted((root / "inputs/history").glob("fit_*_*_WORLDS.json.gz")):
        known.update(schedule_hash(x) for x in read(path))
    require(len(known) == 1936, "old history cardinality")
    for path in sorted((root / "inputs/history/followup").glob("*.json.gz")):
        for world in read(path)["worlds"]:
            key = schedule_hash(world)
            require(key not in known, "previous follow-up non-overlap")
            known.add(key)
    require(len(known) == 2416, "all available history cardinality")
    require(read(run / "HISTORY_EXCLUSION.json")["hashes_sha256"] == sha(canonical(sorted(known)).encode()), "history-set digest")
    world_records, outcomes = {}, {}
    used = set(known)
    task_protocol = read(root / "vendor/frozen_joint/joint_protocol.json")
    for split in ("validation", "test"):
        count = protocol["holdout"][split + "_per_fit_domain"]
        recorded = read(run / (split.upper() + "_DEDUP_BEFORE_SCORING.json"))
        for fit in protocol["fits"]:
            for domain in ("iid", "ood"):
                stored = read(run / f"worlds/{split}_{fit}_{domain}.json.gz")
                seed = int(sha(canonical([protocol_sha, fit, split, domain, "public-schedule"]).encode()), 16)
                require(stored["seed"] == str(seed), "new world seed")
                rng = np.random.Generator(np.random.PCG64(seed))
                law = task_protocol["ood_domain" if domain == "ood" else "train_domain"]
                require(len(stored["worlds"]) == count, "full holdout world count")
                for index, world in enumerate(stored["worlds"]):
                    drawn = {key: rng.choice(law[source], 6).tolist() for key, source in
                             (("duration", "durations"), ("drive", "drives"), ("reliability", "reliabilities"),
                              ("read_price", "prices"), ("read_delay", "delays"))}
                    drawn["prior_distance"] = float(rng.choice(task_protocol["prior_distances"]))
                    require(all(world[key] == value for key, value in drawn.items()), "regenerated complete schedule")
                    require(all(world[key] == law[key] for key in ("latency_price", "repair_price", "failure_probability")), "fixed public-law fields")
                    key = schedule_hash(world)
                    require(key not in used, "new holdout content collision")
                    used.add(key)
                    require(recorded["hashes"][str(fit)][domain][index] == key, "dedup record identity")
                world_records[split, fit, domain] = stored["worlds"]
                scored = read(run / f"{split}_{fit}_{domain}_RESULTS.json.gz")
                require(scored["world_count"] == count and len(scored["records"]) == count, "complete scored worlds")
                expected_arms = set(protocol["arms"]) - ({"E_gated", "G_gated"} if split == "validation" else set())
                require(set(scored["means"]) == expected_arms, "complete predetermined mean arm set")
                for world, row in zip(stored["worlds"], scored["records"]):
                    require(row["schedule_sha256"] == schedule_hash(world) and row["world_id"] == world["id"], "score/world binding")
                    require(set(row["arms"]) == expected_arms, "complete predetermined world arm set")
                for arm, mean in scored["means"].items():
                    require(mean == float(np.mean([row["arms"][arm]["utility"] for row in scored["records"]])), "world-to-fit aggregation")
                outcomes[split, fit, domain] = scored
        require(recorded["all_seen_unique"] == len(used), "dedup final cardinality")
    report["history_unique_schedules"] = len(known)
    report["new_holdout_unique_schedules"] = len(used) - len(known)
    candidate_index = read(run / "ALL_CANDIDATES_BEFORE_VALIDATION.json")
    candidate_records, models = {}, {}
    path_count = 0
    for fit in protocol["fits"]:
        C_model = read(root / f"inputs/fit_{fit}_C.json.gz")
        C = head(C_model)
        info = candidate_index[str(fit)]
        require(sha((run / info["file"]).read_bytes()) == info["sha256"], "frozen candidate record")
        record = read(run / info["file"])
        candidate_records[fit] = record
        require(info["models"] == record["models"], "all-candidates model index")
        train_worlds = read(root / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
        require(len(record["training_worlds"]) == 64, "all TRAIN world reports")
        for world, data in zip(train_worlds, record["training_worlds"]):
            require(schedule_hash(world) == data["schedule_sha256"], "TRAIN world identity")
        for arm, model_info in record["models"].items():
            path = run / model_info["path"]
            require(sha(path.read_bytes()) == model_info["compressed_sha256"], "model artifact identity")
            model = read(path)
            theta = head(model)
            protected = copy.deepcopy(model)
            protected["network"]["w2"][:3] = C_model["network"]["w2"][:3]
            protected["network"]["b2"][:3] = C_model["network"]["b2"][:3]
            require(protected == C_model and np.isfinite(theta).all(), "protected model fields")
            require(sha(json_bytes(model)) == model_info["model_sha256"], "canonical model identity")
            require(np.array_equal(theta, record["selected_heads"][arm]), "selected head/model correspondence")
            models[fit, arm] = model
        require(models[fit, "C"] == C_model, "unchanged incumbent")
        require(models[fit, "M"] == read(root / f"inputs/fit_{fit}_M.json.gz"), "frozen old MSE control")
        for arm in ("E", "G", "EU", "EA"):
            endpoint = np.asarray(record["endpoint_heads"][arm])
            problem = record["problems"]["E" if arm == "G" else arm]
            solver = record["solvers"][arm]
            require(exact_norm(endpoint[:3], C[:3], problem["radius"]) == solver["certificate"], "endpoint exact norm proof")
            require(solver["certificate"]["within_declared"] and solver["certificate"]["within_safe"], "endpoint within both balls")
            require(solver["converged"] == (-1e-12 <= solver["numerical_fw_gap"] <= 1e-8), "own solver stopping rule")
            delta = endpoint[:3] - C[:3]
            matrices, rhs = np.asarray(problem["matrices"]), np.asarray(problem["rhs"])
            independent_gradient = 2 * np.asarray([np.sum(matrix * d[None, :], axis=1) - b
                                                  for matrix, d, b in zip(matrices, delta, rhs)])
            require(float(np.max(abs(independent_gradient - np.asarray(solver["gradient"])))) < 2e-10,
                    "Gram/data gradient consistency")
            path = record["paths"][arm]
            require(path["fixed_alphas"] == protocol["optimization"]["alphas"], "same fixed path for every fitted arm")
            require(len(path["candidates"]) == 5, "all five candidates in every finite path")
            utilities = []
            for index, candidate in enumerate(path["candidates"]):
                require(candidate["index"] == index and candidate["alpha"] == protocol["optimization"]["alphas"][index],
                        "actual candidate follows predetermined index/alpha")
                path_count += 1
                hp = run / candidate["head_path"]
                require(sha(hp.read_bytes()) == candidate["head_file_sha256"], "stored finite candidate identity")
                stored = read(hp)
                require(stored["fit"] == fit and stored["arm"] == arm and stored["index"] == index and
                        stored["alpha"] == candidate["alpha"], "finite candidate metadata binding")
                actual = np.asarray(stored["theta"])
                expected = C.copy()
                expected[:3] = stored_point(C[:3], candidate["alpha"] * (endpoint[:3] - C[:3]), problem["radius"])
                require(np.array_equal(actual, expected), "actual F64 finite direction member")
                require(exact_norm(actual[:3], C[:3], problem["radius"]) == stored["exact_norm"], "candidate exact norm proof")
                require(sha(json_bytes(rebuild(C_model, actual))) == candidate["canonical_model_sha256"], "candidate full-model identity")
                require(len(candidate["per_world"]) == 64 and
                        [row["world_id"] for row in candidate["per_world"]] == [world["id"] for world in train_worlds],
                        "all ordered TRAIN scores for every alpha")
                mean = float(np.mean([row["utility"] for row in candidate["per_world"]]))
                require(mean == candidate["mean_train_own_utility"], "TRAIN objective aggregation")
                utilities.append(mean)
                if index == 0:
                    require(np.array_equal(actual, C), "no-edit path member")
            best = max(range(5), key=lambda i: utilities[i])
            require(path["selected_index"] == best and path["selected_alpha"] == protocol["optimization"]["alphas"][best], "finite own-utility selection and tie break")
            require(record["models"][arm]["model_sha256"] == path["candidates"][best]["canonical_model_sha256"], "selected model belongs to frozen finite set")
        E, R = head(models[fit, "E"]), head(models[fit, "R"])
        target_norm = float(np.linalg.norm(E[:3] - C[:3]))
        actual_norm = float(np.linalg.norm(R[:3] - C[:3]))
        relative = abs(target_norm - actual_norm) / target_norm if target_norm else 0.
        require(relative <= protocol["optimization"]["random_norm_relative_tolerance"], "random norm match")
        if target_norm == 0:
            require(np.array_equal(R, C), "zero selected edit requires zero random edit")
        seed = int(sha(canonical([protocol_sha, fit, "single-final-E-norm-matched-random"]).encode()), 16)
        require(record["random"]["seed"] == str(seed), "preseeded random direction")
        expected = C.copy()
        if target_norm:
            rng = np.random.Generator(np.random.PCG64(seed))
            delta = rng.normal(size=C[:3].shape)
            delta *= target_norm / np.linalg.norm(delta)
            expected[:3] = stored_point(C[:3], delta, record["problems"]["E"]["radius"])
        require(np.array_equal(expected, R), "single recorded random draw")
    require(path_count == 100, "all 100 stored finite path candidates")
    report["stored_finite_path_candidates_verified"] = path_count
    gates = read(run / "ALL_GATES_BEFORE_TEST.json")
    for fit in protocol["fits"]:
        for arm in ("E", "G"):
            gate = gates[str(fit)][arm]
            delta = {d: outcomes["validation", fit, d]["means"][arm] - outcomes["validation", fit, d]["means"]["C"]
                     for d in ("iid", "ood")}
            numeric = candidate_records[fit]["solvers"][arm]["converged"]
            accepted = bool(numeric and min(delta.values()) >= 0 and np.mean(list(delta.values())) >= .005)
            require(gate["delta"] == delta and gate["accepted"] == accepted, "fixed validation gate")
            chosen = read(run / gate["chosen_model"]["path"])
            reference = models[fit, arm if accepted else "C"]
            require(chosen == reference, "accepted/restored full checkpoint")
            require(gate["rejected_restoration_verified"] is (None if accepted else True), "restoration not claimed when inapplicable")
            if not accepted:
                reference_path = run / candidate_records[fit]["models"]["C"]["path"]
                require((run / gate["chosen_model"]["path"]).read_bytes() == reference_path.read_bytes(), "byte-identical rejected rollback")
            models[fit, arm + "_gated"] = chosen
            for domain in ("iid", "ood"):
                for row in outcomes["test", fit, domain]["records"]:
                    require(row["arms"][arm + "_gated"]["utility"] == row["arms"][arm if accepted else "C"]["utility"], "gated execution equals chosen raw policy")
    result = read(run / "RESULTS.json")
    require(result["protocol_sha256"] == protocol_sha and result["gates"] == gates, "result provenance/gate identity")
    for domain in ("iid", "ood"):
        for arm, summary in result["summary"][domain].items():
            values = [outcomes["test", fit, domain]["means"][arm] for fit in protocol["fits"]]
            differences = [value - outcomes["test", fit, domain]["means"]["C"] for fit, value in zip(protocol["fits"], values)]
            mean, interval = conditional_interval(differences, .975)
            require(values == summary["per_fit"], "statistical unit is the five reused fits")
            require(abs(summary["mean"] - sum(values) / 5) < 2e-14 and abs(summary["delta"] - mean) < 2e-14, "summary mean/difference")
            require(max(abs(a - b) for a, b in zip(interval, summary["paired_95_descriptive"])) < 2e-10, "independent descriptive t4 interval")
            if arm == "E_gated":
                mean, interval = conditional_interval(differences, 1 - .05 / 4)
                primary = result["primary"][arm + "_" + domain]
                require(abs(primary["delta"] - mean) < 2e-14 and
                        max(abs(a - b) for a, b in zip(interval, primary["familywise_95_conditional_interval"])) < 2e-10,
                        "independent Bonferroni-two primary interval")
                require(primary["benefit_pass"] == (interval[0] > .005), "benefit threshold")
    qualification = all(candidate_records[fit]["solvers"]["E"]["converged"] for fit in protocol["fits"]) and all(
        row["benefit_pass"] for row in result["primary"].values())
    require(result["weight_efficacy_qualified"] == qualification, "qualification is not inferred from proxy loss")
    report["records_and_statistics_verified"] = True
    report["independent_t4_primary_critical_value"] = t4_quantile(1 - .05 / 4)
    ctx = p.load_context(root / "vendor/frozen_joint") if args.replay_train or args.replay_holdouts else None
    if args.replay_train:
        replay_start, count, maximum = time.process_time(), 0, 0.
        for fit in protocol["fits"]:
            record = candidate_records[fit]
            policy = ctx.NumpyPolicy(models[fit, "C"])
            worlds = read(root / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
            for wi, public in enumerate(worlds):
                features = p.WorldPolicy(ctx, public, policy, None)
                own = ctx.Oracle(public, p.OwnTableLaw(policy, ctx), policy.confusion)
                for arm in ("E", "G", "EU", "EA"):
                    for candidate in record["paths"][arm]["candidates"]:
                        theta = np.asarray(read(run / candidate["head_path"])["theta"])
                        value, _nodes = ctx.policy_value(public, theta, lambda _public, state: features.feature(state)[0], own)
                        expected = candidate["per_world"][wi]["utility"]
                        maximum = max(maximum, abs(float(value) - expected))
                        require(float(value) == expected, "original recursive executor differs from finite-path TRAIN value")
                        count += 1
                gc.collect()
        require(count == 6400, "all 6400 TRAIN world/path pairs replayed")
        report["train_replay"] = dict(world_candidate_pairs=count, maximum_absolute_utility_difference=maximum,
            exact_float_match=True, cpu_seconds=time.process_time() - replay_start,
            scope="original pinned recursive execution, not the new complete-state DAG implementation")
    if args.replay_holdouts:
        replay_start, count, maximum, maximum_nodes = time.process_time(), 0, 0., 0
        for (split, fit, domain), worlds in world_records.items():
            policy = ctx.NumpyPolicy(models[fit, "C"])
            for public, row in zip(worlds, outcomes[split, fit, domain]["records"]):
                compiled, _identity, _own = p.compile_own(ctx, policy, public, protocol["state_caps"]["markov_per_world"])
                truth = ctx.Oracle(public, ctx.law, policy.confusion)
                for arm, expected in row["arms"].items():
                    theta = head(models[fit, "C" if arm in ("P", "J") else arm])
                    actual, nodes = independent_policy_evaluation(ctx, public, policy, theta, arm, truth, compiled)
                    error = max(abs(value - expected[key]) for key, value in actual.items())
                    maximum = max(maximum, error)
                    maximum_nodes = max(maximum_nodes, abs(nodes - expected["nodes"]))
                    require(error <= 2e-13 and nodes == expected["nodes"], "independent held-out policy execution differs")
                    count += 1
                gc.collect()
        require(count == 4960, "all 4960 held-out world/arm pairs replayed")
        report["holdout_replay"] = dict(world_arm_pairs=count, maximum_absolute_behavior_difference=maximum,
            maximum_visited_node_difference=maximum_nodes, fixed_tolerance=2e-13,
            cpu_seconds=time.process_time() - replay_start,
            scope="separate recursive evaluator and literal stored-head reductions; frozen core/law definitions shared")
    report.update(all_checks_pass=True, weight_efficacy_qualified=qualification,
                  cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall,
                  local_event_chain_is_not_external_timestamp_proof=True)
    save(args.output, report)
    print(__import__("json").dumps(report, sort_keys=True), flush=True)
    signal.alarm(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-train", action="store_true")
    parser.add_argument("--replay-holdouts", action="store_true")
    main(parser.parse_args())
