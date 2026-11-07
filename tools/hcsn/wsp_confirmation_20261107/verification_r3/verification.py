"""Independent record checks and complete confirmation replay.

No import from this stage's run, evaluate, candidates or guard modules. The
previous frozen verifier supplies exact stored-vector norms, literal-head
recursive execution and the closed-form df=4 CDF. Task transitions, checkpoint
features, checked arithmetic and J compilation remain shared upstream code.
MYOPIC is reconstructed here by sequential filtering without an own-law q().
Local hashes and event ordering are not external preregistration evidence.

Compatibility revision: the frozen producer stores TRAIN world_id but does
not emit schedule_sha256 in TrainWorld reports. This separate post-execution
verifier binds the complete frozen TRAIN input bytes and ordered world IDs,
checks canonical schedule membership, and requires all 6400 TRAIN replays.
It never changes the frozen worker, records, numerical gates or thresholds.
"""
import argparse
import copy
import datetime
import gc
import math
from pathlib import Path
import resource
import signal
import sqlite3
import sys
import time
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parent.parent  # Original frozen experiment root.
REPO = ROOT.parents[2]
UPSTREAM = ROOT.parent / "wsp_native_value_20261105/value_edit"
sys.path.insert(0, str(UPSTREAM))
from artifact_io import canonical, identity, json_bytes, read, save, sha
from vendor import planning as p
import verify_records as old

FITS = (11, 23, 37, 53, 71)
ARMS = ("C", "L", "E", "R", "A", "G", "EG", "J", "MYOPIC")
PATH_ARMS = ("E", "G", "A", "EG")
METRICS = ("utility", "fees", "reads_requested", "reads_completed", "repairs", "elapsed", "correct", "submitted")
TOLERANCE = 2e-13
require = old.require


def digest(value):
    return sha(canonical(value).encode())


def close(actual, expected, message, tolerance=TOLERANCE):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    require(a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
            and np.max(np.abs(a - b), initial=0.) <= tolerance, message)


def contained(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "artifact path escapes its declared root")
    return path


def verify_sources(protocol):
    files = protocol["source_files"]
    required = {str(path.relative_to(REPO)) for path in ROOT.glob("*.py")}
    required.update(str(path.relative_to(REPO)) for path in UPSTREAM.glob("*.py"))
    inputs = read(UPSTREAM / "INPUT_MANIFEST.json")["files"]
    required.update(str((UPSTREAM / name).relative_to(REPO)) for name in inputs)
    required.update(str(path.relative_to(REPO)) for path in (UPSTREAM / "execution_r1/run/worlds").glob("*.json.gz"))
    require(required.issubset(files), "frozen source/input manifest is incomplete")
    for name, expected in files.items():
        require(identity(contained(REPO, name)) == expected, "frozen source/input changed: " + name)
    for name, expected in inputs.items():
        require(identity(contained(UPSTREAM, name)) == expected, "upstream input manifest mismatch")
    require(identity(UPSTREAM / "PROTOCOL_FROZEN.json")["sha256"] == protocol["upstream_protocol_sha256"],
            "upstream protocol identity")
    require(set(protocol["fixed_external_objective"]) == {"joint_task.py", "joint_law.py", "joint_protocol.json", "truth_transitions.npz"},
            "complete fixed external objective")
    for name, expected in protocol["fixed_external_objective"].items():
        require(identity(contained(UPSTREAM / "vendor/frozen_joint", name)) == expected, "external objective changed")


def verify_checkpoint(model, recorded):
    require(model["schema"] == "joint-policy-v1" and model["family"] == "renewal", "checkpoint class")
    require(recorded["canonical_checkpoint_sha256"] == digest(model), "canonical checkpoint identity")
    for name, shape in (("w1", (48, 85)), ("b1", (48,)), ("w2", (4, 48)), ("b2", (4,))):
        tensor = np.asarray(model["network"][name], dtype="<f8")
        require(tensor.shape == shape and np.isfinite(tensor).all(), "tensor shape/finiteness")
        require(recorded["tensor_map"][name] == dict(shape=list(shape), dtype="IEEE754-F64-LE",
                layout="row-major", sha256=sha(tensor.tobytes())), "tensor byte identity")
    protected = copy.deepcopy(model)
    protected["network"]["w2"][:3], protected["network"]["b2"][:3] = [], []
    require(recorded["protected_model_sha256"] == digest(protected), "protected tensor identity")
    for field, value in (("core_sha256", model["core"]), ("generator_sha256", model["core"]["generators"]),
                         ("transition_tables_sha256", model["core"]["tables"]),
                         ("representation_sha256", {k: model[k] for k in
                          ("coordinates", "confusion", "bank_semantics", "target", "public_dimensions")})):
        require(recorded[field] == digest(value), "checkpoint dependency identity: " + field)
    require(recorded["parameter_count"] == model["parameter_count"], "parameter count binding")
    require(recorded["tensor_roles"] == {"w2[0:3],b2[0:3]": "WAIT,READ,REPAIR continuation",
            "w2[3],b2[3]": "protected Belief logit"}, "semantic row map")


def historical_schedules(run):
    registry = read(UPSTREAM / "inputs/history/HISTORY_REGISTRY.json.gz")
    fields = registry["canonical_schedule_fields"]
    fingerprint = lambda world: digest({key: world[key] for key in fields})
    known = set()
    for row in registry["entries"]:
        require(fingerprint(row["world"]) == row["schedule_sha256"], "old registry identity")
        known.add(row["schedule_sha256"])
    files = sorted((UPSTREAM / "inputs/history").glob("fit_*_*_WORLDS.json.gz"))
    require(len(files) == 10, "all ten historical world files")
    for path in files:
        known.update(fingerprint(world) for world in read(path))
    require(len(known) == 1936, "original history cardinality")
    for folder, expected_size in (("inputs/history/followup", 2416), ("execution_r1/run/worlds", 2896)):
        files = sorted((UPSTREAM / folder).glob("*.json.gz"))
        require(len(files) == 20, "complete exposed history: " + folder)
        for path in files:
            for world in read(path)["worlds"]:
                key = fingerprint(world)
                require(key not in known, "unexpected duplicate in frozen historical holdouts")
                known.add(key)
        require(len(known) == expected_size, "combined known history cardinality")
    report = read(run / "HISTORY_EXCLUSION.json")
    require(report["known_unique_schedules"] == len(known) and report["hashes_sha256"] == digest(sorted(known)),
            "complete historical exclusion set digest")
    require(report["canonical_schedule_fields"] == fields and report["external_history_unknown"] is True,
            "historical coverage qualification")
    return known, fingerprint


def event_order(run, protocol):
    previous, events, times = None, [], []
    for index, path in enumerate(sorted((run / "events").glob("*.json"))):
        event = read(path)
        require(event["sequence"] == index and event["previous_sha256"] == previous, "local hash-chain order")
        payload = event["payload"]
        if "path" in payload:
            require(identity(contained(run, payload["path"]))["sha256"] == payload["sha256"], "event payload digest")
        previous = identity(path)["sha256"]
        times.append(datetime.datetime.fromisoformat(event["utc"]))
        events.append(event)
    expected = ["all_candidates_frozen", "evaluator_seed_generated", "cohort_consumed_before_scoring", "results_frozen"]
    require([row["kind"] for row in events] == expected, "freeze/seed/consume/results event order")
    require(times == sorted(times) and datetime.datetime.fromisoformat(protocol["frozen_utc"]) <= times[0],
            "local protocol/event chronology")
    require(events[2]["payload"]["worlds"] == 320 and events[2]["payload"]["planned_arm_evaluations"] == 2880,
            "precommitted complete denominator")
    return events


def candidates(run, protocol, protocol_sha, fingerprint, known):
    index = read(run / "ALL_CANDIDATES_FROZEN.json")
    require(set(index) == set(map(str, FITS)), "all five frozen fits")
    models, records, path_heads, count = {}, {}, {}, 0
    for fit in FITS:
        path = run / f"fit_{fit}_CANDIDATES.json.gz"
        require(identity(path) == index[str(fit)], "candidate index/file binding")
        record, base = read(path), read(UPSTREAM / f"inputs/fit_{fit}_C.json.gz")
        records[fit], C = record, old.head(base)
        verify_checkpoint(base, protocol["models"][str(fit)])
        require(record["checkpoint_identity"] == protocol["models"][str(fit)], "candidate checkpoint binding")
        require(record["fit"] == fit and record["worlds"] == 64, "candidate fit and TRAIN count")
        require(set(record["models"]) == set(ARMS) == set(record["heads"]), "complete fixed model arm set")
        radius = .5 * float(np.linalg.norm(C[:3])) * (1 - 1e-8)
        require(record["radius"] == radius and 0 < record["rows"] <= protocol["state_caps"]["training_rows_per_fit"],
                "original inward radius and full TRAIN row cap")
        train_path = UPSTREAM / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz"
        require(identity(train_path) == protocol["source_files"][str(train_path.relative_to(REPO))],
                "complete frozen TRAIN input file identity")
        worlds = read(train_path)
        require(len(worlds) == len(record["training_worlds"]) == 64, "all original TRAIN worlds")
        for world, data in zip(worlds, record["training_worlds"]):
            require(data["world_id"] == world["id"] and fingerprint(world) in known,
                    "TRAIN report order and independently reconstructed known schedule")
        for arm, info in record["models"].items():
            path = contained(run, info["path"])
            require(identity(path)["sha256"] == info["compressed_sha256"], "stored model digest")
            model, theta = read(path), np.asarray(record["heads"][arm], dtype=float)
            require(theta.shape == (4, 49) and np.isfinite(theta).all() and np.array_equal(theta, old.head(model)),
                    "stored head/model identity")
            protected = copy.deepcopy(model)
            protected["network"]["w2"][:3], protected["network"]["b2"][:3] = base["network"]["w2"][:3], base["network"]["b2"][:3]
            require(digest(protected) == digest(base), "protected model bytes/fields changed")
            require(info["model_sha256"] == sha(json_bytes(model)), "canonical saved model digest")
            proof = old.exact_norm(theta[:3], C[:3], radius)
            require(proof["within_safe"] and proof["within_declared"], "stored candidate exceeds exact budget")
            if arm in ("C", "L", "J", "MYOPIC"):
                require(digest(model) == digest(base), "program/execution control changed checkpoint")
            models[fit, arm] = model
        require(set(record["paths"]) == set(PATH_ARMS) == set(record["endpoint_heads"]), "four fixed fitted paths")
        for arm in PATH_ARMS:
            endpoint, path = np.asarray(record["endpoint_heads"][arm]), record["paths"][arm]
            require(endpoint.shape == (4, 49) and np.isfinite(endpoint).all(), "finite endpoint head shape")
            proof = old.exact_norm(endpoint[:3], C[:3], radius)
            require(proof == record["solvers"][arm]["certificate" if arm in ("E", "G") else "exact_norm"], "endpoint exact norm")
            require(proof["within_safe"] and proof["within_declared"] and np.array_equal(endpoint[3], C[3]), "endpoint constraints")
            if arm in ("E", "G"):
                solver = record["solvers"][arm]
                require(solver["converged"] is True and -1e-12 <= solver["numerical_fw_gap"] <= 1e-8, "own solver convergence")
            if arm == "A":
                require(-1e-11 <= record["solvers"][arm]["restricted_FW_gap"] <= 1e-8, "restricted A convergence")
            require(path["fixed_alphas"] == protocol["optimization"]["alphas"] and len(path["candidates"]) == 5,
                    "complete five-alpha path")
            utilities = []
            for i, row in enumerate(path["candidates"]):
                alpha = protocol["optimization"]["alphas"][i]
                require(row["index"] == i and row["alpha"] == alpha, "fixed alpha order")
                hp = contained(run, row["head_path"])
                require(identity(hp)["sha256"] == row["head_file_sha256"], "finite path head digest")
                saved = read(hp)
                require((saved["fit"], saved["arm"], saved["index"], saved["alpha"]) == (fit, arm, i, alpha), "path metadata")
                actual, expected = np.asarray(saved["theta"]), C.copy()
                expected[:3] = old.stored_point(C[:3], alpha * (endpoint[:3] - C[:3]), radius)
                require(np.array_equal(actual, expected), "stored F64 alpha interpolation")
                require(old.exact_norm(actual[:3], C[:3], radius) == saved["exact_norm"], "finite path exact norm")
                require(sha(json_bytes(old.rebuild(base, actual))) == row["canonical_model_sha256"] == saved["canonical_model_sha256"],
                        "finite full-model identity")
                per_world = row["per_world"]
                require(len(per_world) == 64 and [w["world_id"] for w in per_world] == [w["id"] for w in worlds], "TRAIN score denominator/order")
                mean = float(np.mean([w["utility"] for w in per_world]))
                require(math.isfinite(mean) and mean == row["mean_train_own_utility"], "TRAIN path mean")
                utilities.append(mean)
                path_heads[fit, arm, i] = actual
                count += 1
            best = max(range(5), key=lambda i: utilities[i])
            require(path["selected_index"] == best and path["selected_alpha"] == protocol["optimization"]["alphas"][best], "TRAIN-only best alpha/tie-break")
            require(record["models"][arm]["model_sha256"] == path["candidates"][best]["canonical_model_sha256"], "selected finite candidate")
        E, R = old.head(models[fit, "E"]), old.head(models[fit, "R"])
        effective = (E[:3] - C[:3]).ravel()
        rng = np.random.Generator(np.random.PCG64(int(digest([protocol_sha, fit, "dual-norm"]), 16)))
        drawn = rng.permutation(effective) * rng.choice(np.array([-1., 1.]), len(effective))
        expected = old.stored_point(C[:3], drawn.reshape(3, 49), radius)
        require(np.array_equal(R[:3], expected), "single preseeded signed-permutation random control")
        require(old.exact_norm(R[:3], C[:3], radius) == record["random_exact_norm"], "random exact norm proof")
        for kind, order in (("L2", 2), ("Linf", np.inf)):
            norms = [float(np.linalg.norm((theta[:3] - C[:3]).ravel(), ord=order)) for theta in (E, R)]
            require(norms == record["random_norms"][kind] and math.isclose(*norms, rel_tol=1e-10, abs_tol=1e-15), "stored dual-norm match")
    require(count == 100, "all 100 frozen finite path candidates")
    return models, records, path_heads


def samples_and_scores(run, protocol, known, fingerprint, cohort_sha):
    seed = read(run / "EVALUATOR_SEED.json")
    require(seed["candidate_cohort_sha256"] == cohort_sha and seed["generated_after_candidate_freeze"] is True
            and seed["independent_authority_verified"] is False, "evaluator seed/cohort binding")
    require(len(seed["seed"]) == 64 and set(seed["seed"]) <= set("0123456789abcdef"), "256-bit recorded evaluator seed")
    samples, scores, used = read(run / "CONFIRMATION_SAMPLES.json.gz"), {}, set(known)
    require(len(samples) == 320 and len(list((run / "scores").glob("*.json.gz"))) == 320, "complete 320-world denominator")
    task = read(UPSTREAM / "vendor/frozen_joint/joint_protocol.json")
    at = 0
    for fit in FITS:
        for domain in ("iid", "ood"):
            rng = np.random.Generator(np.random.PCG64(int(digest([seed["seed"], fit, domain]), 16)))
            law = task["ood_domain" if domain == "ood" else "train_domain"]
            for i in range(32):
                sample, at = samples[at], at + 1
                world = sample["public"]
                require((sample["fit"], sample["domain"], sample["index"]) == (fit, domain, i), "confirmation sample order")
                for key, source in (("duration", "durations"), ("drive", "drives"), ("reliability", "reliabilities"), ("read_price", "prices"), ("read_delay", "delays")):
                    require(world[key] == rng.choice(law[source], 6).tolist(), "independent seed-to-schedule regeneration")
                require(world["prior_distance"] == float(rng.choice(task["prior_distances"])), "regenerated prior")
                require(all(world[k] == law[k] for k in ("latency_price", "repair_price", "failure_probability")), "fixed domain law")
                require(world["id"] == f"wsp_confirm_{fit}_{domain}_{i}" and world["deadline"] == world["target_tick"] == 6
                        and world["initial_budget"] == 3 and world["schema"] == "joint-current-at-due-fixed-deadline-v1", "public task identity")
                require(world["packets"] == [f"not_opened_{j}.json" for j in range(6)] and world["packet_sha256"] == ["0" * 64] * 6, "simulated packet scope")
                key = fingerprint(world)
                require(key == sample["sha256"] and key not in used, "historical or within-cohort content collision")
                used.add(key)
                row = read(run / f"scores/{fit}_{domain}_{i:03}.json.gz")
                require(row["sample"] == {k: v for k, v in sample.items() if k != "public"} and set(row["arms"]) == set(ARMS), "score identity and nine-arm denominator")
                scores[fit, domain, i] = row["arms"]
    return samples, scores


def ledger_snapshot(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        return {table: list(db.execute(f"SELECT * FROM {table} ORDER BY {order}")) for table, order in
                (("runs", "protocol"), ("samples", "fingerprint"), ("attempts", "run,sample,fit,arm"))}


def ledger_records(snapshot, protocol_sha, cohort_sha, known, samples, scores):
    runs = [row for row in snapshot["runs"] if row[0] == protocol_sha]
    require(len(runs) == 1 and runs[0][1:3] == (cohort_sha, "CONSUMED"), "consumed ledger cohort binding")
    owners = dict(snapshot["samples"])
    require(known.issubset(owners) and {key for key, owner in owners.items() if owner == protocol_sha} == {s["sha256"] for s in samples}, "ledger history and reserved cohort")
    expected = {(s["sha256"], s["fit"], s["domain"], arm): scores[s["fit"], s["domain"], s["index"]][arm] for s in samples for arm in ARMS}
    rows = [row for row in snapshot["attempts"] if row[0] == protocol_sha]
    require(len(rows) == len(expected) == 2880, "complete durable attempt denominator")
    for _run, sample, fit, domain, arm, state, result, cpu, wall in rows:
        key = (sample, fit, domain, arm)
        require(key in expected and state == "COMPLETE" and result == digest(expected[key]), "ledger result/raw-score identity")
        require(all(isinstance(x, (int, float)) and math.isfinite(x) and x >= 0 for x in (cpu, wall)), "measured durable attempt costs")
        del expected[key]
    require(not expected, "no missing or duplicate ledger attempts")


def summaries(protocol, result, scores):
    primary = {row["contrast"]: row for row in result["primary_contrasts"]}
    require(len(result["primary_contrasts"]) == len(primary) == 2 and set(primary) == {"E-C iid", "E-C ood"}, "complete primary family")
    require(set(result["summary"]) == {"iid", "ood"}, "both evaluation domains")
    for domain in ("iid", "ood"):
        require(set(result["summary"][domain]) == set(ARMS), "all nine summary arms")
        baseline = [float(np.mean([scores[f, domain, i]["C"]["utility"] for i in range(32)])) for f in FITS]
        for arm in ARMS:
            summary = result["summary"][domain][arm]
            values = [float(np.mean([scores[f, domain, i][arm]["utility"] for i in range(32)])) for f in FITS]
            differences = [x - b for x, b in zip(values, baseline)]
            mean, interval = old.conditional_interval(differences, .975)
            require(values == summary["per_fit"], "paired statistical unit remains five reused fits")
            close([summary["mean"], summary["delta_C"]], [sum(values) / 5, mean], "summary aggregation")
            close(summary["descriptive_interval"], interval, "independent closed-form descriptive t4 interval", 2e-10)
            rows = [scores[f, domain, i][arm] for f in FITS for i in range(32)]
            for row in rows:
                require(all(math.isfinite(row[key]) for key in METRICS) and isinstance(row["nodes"], int) and row["nodes"] > 0, "finite eight-metric raw record")
                close(row["utility"], 2 * row["correct"] - row["submitted"] - row["fees"], "reward/fee accounting")
                require(row["energy_joules"] is None and row["program_control"] == (arm in ("J", "MYOPIC")), "cost/program scope")
                close(row["posterior_probability_mse"], row["posterior_squared"] / row["decision_mass"], "calibration normalization")
            latency = [r["policy_initialization_cpu_seconds"] + r["policy_cpu_seconds"]
                + (r["planning"]["full_cold_preparation_cpu_seconds"] if r["planning"] else 0.) for r in rows]
            for key, expected in (("mean_posterior_probability_mse", np.mean([r["posterior_probability_mse"] for r in rows])),
                                  ("world_utility_p05_descriptive", np.quantile([r["utility"] for r in rows], .05)),
                                  ("cold_policy_cpu_mean", np.mean(latency)), ("cold_policy_cpu_p95", np.quantile(latency, .95)),
                                  ("full_evaluator_and_preservation_cpu", np.sum([r["full_arm_cpu_seconds"] for r in rows]))):
                close(summary[key], expected, "secondary summary aggregation: " + key)
            if arm == "E":
                mean, interval = old.conditional_interval(differences, 1 - .05 / 4)
                row = primary["E-C " + domain]
                require(row["n_fits"] == 5, "primary independent unit count")
                close(row["delta"], mean, "primary delta")
                close(row["familywise_interval"], interval, "independent Bonferroni-two t4 interval", 2e-10)
    benefit = all(row["familywise_interval"][0] > .005 for row in primary.values())
    gate = result["quality_gate"]
    require(gate["contrast_contract_valid"] is True and gate["task_benefit_pass"] == benefit and gate["complete_quality_pass"] is False
            and gate["full_cost_qualified"] is False and gate["production_eligible"] is False, "quality/cost gate cannot claim unmeasured retention")
    require(gate["unmeasured_costs"] == protocol["unmeasured_costs"] and result["production_eligible"] is False
            and result["live_market_gain_qualified"] is False and result["new_training_fits"] == 0, "explicit research-only qualification")
    require(all(result["costs"][key] is None for key in ("agent_input_tokens", "agent_output_tokens", "energy_joules")),
            "unmeasured whole-experiment costs remain unknown")


class MyopicReplay:
    """Sequential checkpoint-table filtering; no Oracle or Bellman-value method."""
    def __init__(self, ctx, public, model):
        self.ctx, self.public, self.law = ctx, public, p.OwnTableLaw(model, ctx)
        self.transitions = [self.law.transition(dt, drive) for dt, drive in zip(public["duration"], public["drive"])]
        self.emissions = [self.law.emission(r, model.confusion) for r in public["reliability"]]

    def mass(self, state, target):
        observed = {item["observation_tick"]: item["observation"] for item in state["history"]}
        require(state["tick"] <= target <= 6 and all(1 <= tick <= state["tick"] for tick in observed), "causal MYOPIC observation history")
        mass = self.law.initial_mass(self.public["prior_distance"])
        for tick in range(target):
            mass = self.ctx.checked_mm(mass, self.transitions[tick])
            if tick + 1 in observed:
                mass = mass * self.emissions[tick][:, observed[tick + 1]]
                require(mass.sum() > 0, "possible stored-law observation")
                mass = mass / mass.sum()
        return mass

    def posterior(self, state):
        return float(self.mass(state, 6)[self.law.positive].sum())

    def scores(self, state):
        posterior = self.posterior(state)
        scores = [0., 0., 0., 0., 1 - 2 * posterior, 2 * posterior - 1]
        for action in (1, 2, 3):
            if not self.ctx.legal(self.public, state)[action]:
                continue
            due = self.ctx.due_request(self.public, state, action)
            outcomes = [(1., None)]
            if due is not None:
                mass = self.ctx.checked_mm(self.mass(state, state["tick"]), self.transitions[state["tick"]])
                predictive = self.ctx.checked_mm(mass, self.emissions[due - 1])
                failure = self.public["failure_probability"]
                outcomes = [(failure, dict(failure=True, observation_tick=due))] + [
                    ((1 - failure) * float(predictive[y]), dict(observation=y, observation_tick=due)) for y in (0, 1)]
            for probability, outcome in outcomes:
                if probability:
                    after = self.ctx.successor(self.public, state, action, outcome)
                    scores[action] += probability * (abs(2 * self.posterior(after) - 1) - (after["charges"] - state["charges"]))
        return scores

    def evaluate(self, truth):
        nodes = 0
        def recurse(state):
            nonlocal nodes
            nodes += 1
            scores = self.scores(state)
            action = max((i for i, allowed in enumerate(self.ctx.legal(self.public, state)) if allowed), key=lambda i: scores[i])
            if action in (0, 4, 5):
                posterior = truth.posterior(state)
                correct = 0. if action == 0 else (posterior if action == 5 else 1 - posterior)
                return [0. if action == 0 else 2 * correct - 1, 0., 0., 0., 0., 0., correct, float(action != 0)]
            total = [0.] * 8
            for probability, outcome in self.ctx.outcomes(self.public, state, action, truth):
                if not probability:
                    continue
                after = self.ctx.successor(self.public, state, action, outcome)
                future, fee = recurse(after), after["charges"] - state["charges"]
                additions = [-fee, fee, float(action == 2), len(after["history"]) - len(state["history"]),
                             float(action == 3), after["elapsed"] - state["elapsed"], 0., 0.]
                total = [x + probability * (y + z) for x, y, z in zip(total, future, additions)]
            return total
        return dict(zip(METRICS, recurse(self.ctx.initial(self.public)))), nodes


def replay(ctx, protocol, samples, scores, models, budget):
    count, maximum, started = 0, 0., time.process_time()
    for sample in samples:
        budget()
        fit, public = sample["fit"], sample["public"]
        policy = ctx.NumpyPolicy(models[fit, "C"])
        compiled, preparation, _ = p.compile_own(ctx, policy, public, protocol["state_caps"]["markov_per_world"])
        truth = ctx.Oracle(public, ctx.law, policy.confusion)
        expected = scores[fit, sample["domain"], sample["index"]]
        require(preparation["table_sha256"] == expected["J"]["planning"]["table_sha256"], "recompiled own-law J table identity")
        for arm in ARMS:
            if arm == "MYOPIC":
                actual, nodes = MyopicReplay(ctx, public, policy).evaluate(truth)
            else:
                actual, nodes = old.independent_policy_evaluation(ctx, public, policy, old.head(models[fit, arm]), arm, truth, compiled)
            error = max(abs(actual[key] - expected[arm][key]) for key in METRICS)
            require(error <= TOLERANCE and nodes == expected[arm]["nodes"], "independent eight-metric/node replay: " + str((fit, sample["domain"], sample["index"], arm)))
            maximum, count = max(maximum, error), count + 1
        require(all(expected["C"][key] == expected["L"][key] for key in METRICS + ("nodes",)), "literal execution fidelity")
        gc.collect()
    require(count == 2880, "all 2880 confirmation arm executions replayed")
    return dict(world_arm_pairs=count, raw_metrics=list(METRICS), maximum_absolute_metric_difference=maximum,
                exact_nodes=True, fixed_tolerance=TOLERANCE, cpu_seconds=time.process_time() - started)


def replay_train(ctx, records, models, path_heads, budget):
    count, maximum = 0, 0.
    for fit in FITS:
        policy = ctx.NumpyPolicy(models[fit, "C"])
        for wi, public in enumerate(read(UPSTREAM / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")):
            budget()
            features = p.WorldPolicy(ctx, public, policy, None)
            own = ctx.Oracle(public, p.OwnTableLaw(policy, ctx), policy.confusion)
            for arm in PATH_ARMS:
                for i, candidate in enumerate(records[fit]["paths"][arm]["candidates"]):
                    value, _nodes = ctx.policy_value(public, path_heads[fit, arm, i], lambda _p, state: features.feature(state)[0], own)
                    expected = candidate["per_world"][wi]
                    error = abs(value - expected["utility"])
                    require(error <= TOLERANCE, "independent TRAIN path utility")
                    maximum, count = max(maximum, error), count + 1
            gc.collect()
    require(count == 6400, "all 6400 TRAIN world/path executions")
    return dict(world_path_pairs=count, maximum_absolute_utility_difference=maximum,
                node_counts_not_compared="TRAIN producer memoizes DAG states; replay visits the recursive tree")


def main(args):
    start, wall = time.process_time(), time.perf_counter()
    run, protocol = args.run.resolve(), read(args.protocol)
    protocol_sha = identity(args.protocol)["sha256"]
    report = dict(schema="hepta-wsp-confirmation-independent-verification-v1", protocol_sha256=protocol_sha,
                  verification_source_sha256=identity(Path(__file__))["sha256"], all_checks_pass=False,
                  original_frozen_verification_source_sha256=identity(ROOT / "verification.py")["sha256"],
                  verifier_revision=dict(kind="post_execution_schema_compatibility_v1",
                      reason="Original TrainWorld reports contain world_id, not schedule_sha256",
                      replacement_checks=["frozen complete TRAIN input file hash", "ordered world_id binding",
                          "canonical TRAIN schedule membership in the reconstructed known history",
                          "mandatory full 6400 TRAIN world/path recursive utility replay"],
                      worker_or_records_modified=False, numeric_gates_or_thresholds_changed=False,
                      original_frozen_source_map_still_verified=True),
                  new_worker_evaluator_or_candidates_imported=False,
                  shared_upstream=["artifact_io.py", "verify_records.py", "vendor/planning.py", "vendor/frozen_joint"],
                  local_event_chain_is_not_external_timestamp_proof=True, independent_data_authority_verified=False)
    def budget(*_unused):
        caps = protocol["resources"]
        if time.process_time() - start > caps["verifier_cpu_seconds"] or time.perf_counter() - wall > caps["verifier_wall_seconds"]:
            raise TimeoutError("independent verifier resource cap; preserve failed verification cost")
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024) > caps["rss_limit_bytes"]:
            raise MemoryError("independent verifier RSS cap")
    def timeout(*_unused):
        raise TimeoutError("independent verifier CPU/wall cap")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(protocol["resources"]["verifier_wall_seconds"])
    cpu_cap = protocol["resources"]["verifier_cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_cap, cpu_cap + 5))
    try:
        require(args.replay_train, "compatibility revision requires --replay-train for all 6400 TRAIN combinations")
        require(protocol["status"] == "FROZEN_BEFORE_CANDIDATES_AND_CONFIRMATION" and tuple(protocol["fits"]) == FITS
                and tuple(protocol["arms"]) == ARMS and protocol["confirmation"]["worlds_per_fit_domain"] == 32
                and protocol["confirmation"]["domains"] == ["iid", "ood"]
                and protocol["optimization"]["alphas"] == [0., .25, .5, .75, 1.], "fixed protocol dimensions")
        verify_sources(protocol)
        snapshot = {path: identity(path) for path in run.rglob("*.json*") if path.is_file()}
        ledger_before = ledger_snapshot(args.ledger)
        require(not (run / "FAILED.json").exists(), "worker has a preserved failure")
        started = read(run / "STARTED.json")
        require(started["protocol_sha256"] == protocol_sha and started["source_commit"] == protocol["source_commit"], "run source/protocol identity")
        require(started["numeric_threads"] == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}, "worker numeric thread contract")
        events = event_order(run, protocol)
        known, fingerprint = historical_schedules(run)
        cohort_sha = identity(run / "ALL_CANDIDATES_FROZEN.json")["sha256"]
        models, records, path_heads = candidates(run, protocol, protocol_sha, fingerprint, known)
        samples, scores = samples_and_scores(run, protocol, known, fingerprint, cohort_sha)
        ledger_records(ledger_before, protocol_sha, cohort_sha, known, samples, scores)
        result = read(run / "RESULTS.json")
        require(result["protocol_sha256"] == protocol_sha and result["cohort_sha256"] == cohort_sha
                and result["ledger_counts"] == {"COMPLETE": 2880} and result["new_worlds"] == 320 and result["reused_fits"] == 5,
                "result/cohort/complete denominator binding")
        require(result["historical_TEST_used_for_search"] is False and result["source_unchanged"] is True, "recorded search/source scope")
        summaries(protocol, result, scores)
        ctx = p.load_context(UPSTREAM / "vendor/frozen_joint")
        report["confirmation_replay"] = replay(ctx, protocol, samples, scores, models, budget)
        report["train_replay"] = replay_train(ctx, records, models, path_heads, budget)
        verify_sources(protocol)
        require(identity(args.protocol)["sha256"] == protocol_sha, "protocol changed during verification")
        require(all(identity(path) == expected for path, expected in snapshot.items()), "raw artifact changed during verification")
        require(ledger_snapshot(args.ledger) == ledger_before, "ledger records changed during read-only verification")
        report.update(all_checks_pass=True, raw_records_and_statistics_verified=True, event_chain_entries=len(events),
                      historical_unique_schedules=len(known), new_unique_schedules=len(samples),
                      stored_finite_path_candidates_verified=100, independent_t4_primary_critical_value=old.t4_quantile(.9875),
                      ledger_snapshot_sha256=digest(ledger_before), source_and_raw_records_unchanged=True,
                      production_eligible=False, unmeasured_costs=protocol["unmeasured_costs"])
    except BaseException as error:
        report.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
    finally:
        signal.alarm(0)
    report.update(cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall,
                  energy_joules=None, verifier_cost_is_additional_to_worker=True)
    save(args.output, report)
    print(canonical(report), flush=True)
    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-train", action="store_true", help="also replay all 6400 TRAIN path/world executions")
    sys.exit(main(parser.parse_args()))
