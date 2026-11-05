"""One frozen terminal-anchored policy-improvement experiment; no adaptive reruns."""
import argparse
import copy
import datetime
import gc
import os
from pathlib import Path
import platform
import resource
import signal
import sys
import time
import traceback
from types import SimpleNamespace

import numpy as np
import scipy
from scipy.stats import t as student_t

from artifact_io import EventChain, canonical, identity, json_bytes, read, save, sha, verify_manifest
from task_graph import TrainWorld
from vendor import planning as p
from vendor import quadratic as q


PATH_ARMS = ("E", "G", "EU", "EA")
RAW_ARMS = ("C", "E", "G", "EU", "EA", "M", "R", "P", "J")


def model_for(incumbent, theta):
    model = copy.deepcopy(incumbent)
    model["network"]["w2"], model["network"]["b2"] = theta[:, :48].tolist(), theta[:, 48].tolist()
    recovered = copy.deepcopy(model)
    recovered["network"]["w2"][:3] = copy.deepcopy(incumbent["network"]["w2"][:3])
    recovered["network"]["b2"][:3] = copy.deepcopy(incumbent["network"]["b2"][:3])
    if recovered != incumbent or not np.isfinite(theta).all():
        raise ValueError("candidate modifies protected model fields")
    return model


def load_history(root):
    history_root = root / "inputs/history"
    registry = read(history_root / "HISTORY_REGISTRY.json.gz")
    fields = registry["canonical_schedule_fields"]
    def schedule_hash(public):
        return sha(canonical({key: public[key] for key in fields}).encode())
    known = set()
    for row in registry["entries"]:
        if schedule_hash(row["world"]) != row["schedule_sha256"]:
            raise ValueError("historical schedule-content identity failed")
        known.add(row["schedule_sha256"])
    old_files = sorted(history_root.glob("fit_*_*_WORLDS.json.gz"))
    if len(old_files) != 10:
        raise ValueError("all old schedule files required")
    for path in old_files:
        for world in read(path):
            known.add(schedule_hash(world))
    if len(known) != 1936:
        raise ValueError("old history set does not have its declared size")
    followup_files = sorted((history_root / "followup").glob("*.json.gz"))
    if len(followup_files) != 20:
        raise ValueError("all previous follow-up schedules required")
    for path in followup_files:
        for world in read(path)["worlds"]:
            key = schedule_hash(world)
            if key in known:
                raise ValueError("unexpected duplicate in frozen prior follow-up")
            known.add(key)
    if len(known) != 2416:
        raise ValueError("combined available history size changed")
    return known, schedule_hash, dict(known_unique_schedules=len(known),
        old_unique_schedules=1936, prior_followup_unique_schedules=480,
        canonical_schedule_fields=fields, historical_not_covered=registry["not_covered"],
        external_history_unknown=True, historical_unmeasured_compute_cost="unknown",
        hashes_sha256=sha(canonical(sorted(known)).encode()),
        content_nonoverlap_is_not_statistical_independence=True)


def serialize_model(out, fit, name, incumbent, theta, ctx):
    start = time.process_time()
    model = model_for(incumbent, theta)
    path = out / f"models/fit_{fit}_{name}.json.gz"
    compressed = save(path, model)
    loaded = read(path)
    actual = ctx.head(loaded)
    if loaded != model or not np.array_equal(actual, theta):
        raise ArithmeticError("selected model serialization changed parameters")
    return actual, dict(path=str(path.relative_to(out)), model_sha256=sha(json_bytes(model)),
                        compressed_sha256=compressed,
                        serialize_save_load_cpu_seconds=time.process_time() - start,
                        protected_fields_unchanged=True)


def select_path(out, fit, name, incumbent, C, endpoint, radius, worlds, alphas, budget):
    start = time.process_time()
    records, actual_heads = [], []
    for index, alpha in enumerate(alphas):
        budget()
        theta = C.copy()
        theta[:3], proof, inward = q.stored_point(C[:3], alpha * (endpoint[:3] - C[:3]), radius)
        if alpha == 0. and not np.array_equal(theta, C):
            raise ArithmeticError("zero-edit member is not the incumbent")
        model = model_for(incumbent, theta)
        head_path = out / f"paths/fit_{fit}_{name}_{index}_HEAD.json.gz"
        saved = dict(fit=fit, arm=name, index=index, alpha=alpha, theta=theta,
                     canonical_model_sha256=sha(json_bytes(model)), exact_norm=proof,
                     storage_inward_applied=inward, protected_belief_unchanged=True)
        compressed = save(head_path, saved)
        loaded = read(head_path)
        actual = np.asarray(loaded["theta"], dtype=np.float64)
        if not np.array_equal(actual, theta) or sha(json_bytes(model_for(incumbent, actual))) != saved["canonical_model_sha256"]:
            raise ArithmeticError("finite path serialization identity failed")
        per_world = [dict(world_id=world.public["id"], **world.score(actual)) for world in worlds]
        mean = float(np.mean([row["utility"] for row in per_world]))
        if alpha == 0. and any(row["utility"] != world.report["incumbent_utility"] for row, world in zip(per_world, worlds)):
            raise ArithmeticError("zero-edit TRAIN value differs from exact C reference")
        records.append(dict(index=index, alpha=alpha, head_path=str(head_path.relative_to(out)),
                            head_file_sha256=compressed, canonical_model_sha256=saved["canonical_model_sha256"],
                            mean_train_own_utility=mean, per_world=per_world))
        actual_heads.append(actual)
    best = max(range(len(records)), key=lambda i: records[i]["mean_train_own_utility"])
    selected = actual_heads[best]
    report = dict(arm=name, fixed_alphas=alphas, selected_index=best, selected_alpha=alphas[best],
                  ties="first maximum, hence smallest alpha in the fixed ascending list",
                  candidates=records, inclusive_path_cpu_seconds=time.process_time() - start,
                  selection_law="checkpoint own law only", candidate_count=len(records),
                  finite_set_only=True)
    return selected, report


def main(args):
    start, wall = time.process_time(), time.perf_counter()
    root, out = Path(__file__).resolve().parent, args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol = read(args.protocol)
    protocol_sha = sha(args.protocol.read_bytes())
    if protocol["status"] != "FROZEN_BEFORE_ANY_CANDIDATE_FIT_OR_NEW_HOLDOUT":
        raise ValueError("a frozen protocol is required")
    caps = protocol["resource_caps"]
    def timeout(*_unused):
        raise TimeoutError("fixed CPU/wall resource cap reached; preserve partial run")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(caps["worker_wall_seconds"])
    resource.setrlimit(resource.RLIMIT_CPU, (caps["worker_cpu_seconds"], caps["worker_cpu_seconds"] + 5))
    def budget():
        if time.process_time() - start >= caps["worker_cpu_seconds"] or time.perf_counter() - wall >= caps["worker_wall_seconds"]:
            timeout()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        if rss > caps["peak_rss_target_bytes"]:
            raise MemoryError("fixed measured RSS target exceeded; no subset substitution")
    events = EventChain(out)
    stage = "source_gate"
    save(out / "STARTED.json", dict(protocol_sha256=protocol_sha,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        python=sys.version, numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform(),
        resource_caps=caps, local_freeze_is_not_external_preregistration=True,
        logical_cpu_count=os.cpu_count(), numerical_threads_requested=1))
    try:
        verify_manifest(root, protocol["source_files"])
        input_manifest = read(root / "INPUT_MANIFEST.json")
        verify_manifest(root, input_manifest["files"])
        events.add("source_verified", dict(protocol_sha256=protocol_sha,
                                           source_manifest_sha256=sha(json_bytes(protocol["source_files"]))))
        full_ctx = p.load_context(root / "vendor/frozen_joint")
        # Candidate functions receive this narrow object, which has no truth-law member.
        training_ctx = SimpleNamespace(**{name: getattr(full_ctx, name) for name in
            ("checked_mm", "NumpyPolicy", "Oracle", "initial", "legal", "due_request", "successor",
             "predicted", "outcomes", "policy_value", "head", "deploy")})
        mm = training_ctx.checked_mm
        known, schedule_hash, history_report = load_history(root)
        save(out / "HISTORY_EXCLUSION.json", history_report)
        fits = {}
        stage = "candidate_construction"
        for fit in protocol["fits"]:
            budget()
            fit_start = time.process_time()
            incumbent = read(root / f"inputs/fit_{fit}_C.json.gz")
            C = training_ctx.head(incumbent)
            policy = training_ctx.NumpyPolicy(incumbent)
            train_public = read(root / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
            if len(train_public) != protocol["training"]["worlds_per_fit"]:
                raise ValueError("complete original TRAIN is required")
            if any(schedule_hash(public) not in known for public in train_public):
                raise ValueError("original TRAIN schedule absent from historical exclusion")
            worlds, rows = [], 0
            for public in train_public:
                budget()
                world = TrainWorld(training_ctx, public, policy, C, len(train_public), protocol)
                rows += len(world.states)
                if rows > protocol["state_caps"]["training_rows_per_fit"]:
                    raise OverflowError("fixed complete TRAIN row cap exceeded")
                world.report["schedule_sha256"] = schedule_hash(public)
                worlds.append(world)
            H = np.concatenate([x.H for x in worlds])
            Y = np.concatenate([x.targets for x in worlds])
            raw_Y = np.concatenate([x.raw_targets for x in worlds])
            W = np.concatenate([x.W for x in worlds])
            WU = np.concatenate([x.WU for x in worlds])
            shared_preparation = time.process_time() - fit_start
            problem_records, reports, endpoints = {}, {}, {}
            for name, targets, weights in (("E", Y, W), ("EU", Y, WU), ("EA", raw_Y, W)):
                budget()
                problem = q.prepare(H, targets, weights, C[:3], mm)
                endpoint = C.copy()
                endpoint[:3], direct = q.direct(problem, mm, budget)
                endpoints[name] = endpoint
                reports[name] = direct
                problem_records[name] = {key: problem[key] for key in
                    ("original", "matrices", "rhs", "values", "radius", "L", "setup_cpu_seconds", "setup_wall_seconds")}
                problem_records[name]["C_diagnostics"] = q.diagnostics(problem, C[:3], mm)
                if name == "E":
                    endpoint_g = C.copy()
                    endpoint_g[:3], gradient = q.pgd(problem, mm, budget)
                    endpoints["G"], reports["G"] = endpoint_g, gradient
            selected, paths = {}, {}
            for name in PATH_ARMS:
                selected[name], paths[name] = select_path(out, fit, name, incumbent, C, endpoints[name],
                    problem_records["E" if name == "G" else name]["radius"], worlds,
                    protocol["optimization"]["alphas"], budget)
            arms = dict(C=C, **selected)
            M_model = read(root / f"inputs/fit_{fit}_M.json.gz")
            arms["M"] = training_ctx.head(M_model)
            if model_for(incumbent, arms["M"]) != M_model:
                raise ValueError("old MSE control does not reconstruct its pinned checkpoint")
            identities = {}
            for name in ("C", "E", "G", "EU", "EA", "M"):
                arms[name], identities[name] = serialize_model(out, fit, name, incumbent, arms[name], training_ctx)
            # Random direction matches the finally selected and serialized E, never its unselected endpoint.
            random_seed = int(sha(canonical([protocol_sha, fit, "single-final-E-norm-matched-random"]).encode()), 16)
            rng = np.random.Generator(np.random.PCG64(random_seed))
            selected_norm = float(np.linalg.norm(arms["E"][:3] - C[:3]))
            R = C.copy()
            if selected_norm:
                delta = rng.normal(size=C[:3].shape)
                delta *= selected_norm / np.linalg.norm(delta)
                R[:3], _proof, _inward = q.stored_point(C[:3], delta, problem_records["E"]["radius"])
            arms["R"], identities["R"] = serialize_model(out, fit, "R", incumbent, R, training_ctx)
            random_norm = float(np.linalg.norm(arms["R"][:3] - C[:3]))
            norm_relative_error = abs(random_norm - selected_norm) / selected_norm if selected_norm else 0.
            if norm_relative_error > 1e-10 or (selected_norm == 0. and not np.array_equal(arms["R"], C)):
                raise ArithmeticError("stored random edit does not match final E norm")
            arms["P"], arms["J"] = arms["C"], arms["C"]
            train_controls = {}
            control_start = time.process_time()
            for name in ("C", "M", "R", "P", "J"):
                records = []
                for world in worlds:
                    budget()
                    compiled, planning_record = None, None
                    if name == "J":
                        compiled, planning_record, _own = p.compile_own(training_ctx, policy, world.public,
                            protocol["state_caps"]["markov_per_world"])
                    record = world.score(arms[name], name if name in ("P", "J") else "head", compiled)
                    records.append(dict(world_id=world.public["id"], own_bellman=planning_record, **record))
                train_controls[name] = dict(mean_train_own_utility=float(np.mean([x["utility"] for x in records])),
                                             per_world=records)
            control_cpu = time.process_time() - control_start
            record = dict(fit=fit, complete_train_rows=rows, training_worlds=[x.report for x in worlds],
                models=identities, selected_heads=arms, endpoint_heads=endpoints,
                solvers=reports, problems=problem_records,
                paths=paths, training_controls=train_controls,
                shared_input_state_feature_own_teacher_cpu_seconds=shared_preparation,
                other_TRAIN_control_cpu_seconds=control_cpu,
                candidate_total_cpu_seconds=time.process_time() - fit_start,
                arrays_sha256={name: sha(array.tobytes()) for name, array in
                    (("H", H), ("Y_anchor", Y), ("Y_raw", raw_Y), ("W_mix", W), ("W_uniform", WU))},
                random=dict(seed=str(random_seed), matched_selected_E_norm=selected_norm,
                            actual_R_norm=random_norm, relative_norm_error=norm_relative_error,
                            selected_E_zero_implies_R_zero=bool(selected_norm != 0. or np.array_equal(arms["R"], C)),
                            exact_norm=q.norm_certificate(arms["R"][:3], C[:3], problem_records["E"]["radius"])),
                source_and_protected_fields_verified=True,
                candidate_information="64 original TRAIN public schedules plus checkpoint own law only; no evaluator truth")
            record_path = out / f"fit_{fit}_CANDIDATES.json.gz"
            record_sha = save(record_path, record)
            events.add("fit_candidates_frozen", dict(fit=fit, path=record_path.name, sha256=record_sha))
            fits[fit] = dict(model=policy, incumbent=incumbent, arms=arms, record=record,
                             candidate_file=record_path.name, candidate_sha256=record_sha)
            print(__import__("json").dumps(dict(stage="fit_candidates_frozen", fit=fit, rows=rows,
                 selected_alphas={name: paths[name]["selected_alpha"] for name in PATH_ARMS},
                 cpu_seconds=time.process_time() - start)), flush=True)
            del worlds, world, H, Y, raw_Y, W, WU, problem
            gc.collect()
        candidate_index = {str(fit): dict(file=state["candidate_file"], sha256=state["candidate_sha256"],
                                         models=state["record"]["models"]) for fit, state in fits.items()}
        candidate_index_sha = save(out / "ALL_CANDIDATES_BEFORE_VALIDATION.json", candidate_index)
        events.add("all_candidates_frozen", dict(path="ALL_CANDIDATES_BEFORE_VALIDATION.json", sha256=candidate_index_sha))
        used = set(known)
        def new_worlds(split, count):
            collection = {}
            for fit in protocol["fits"]:
                collection[fit] = {}
                for domain in ("iid", "ood"):
                    seed = int(sha(canonical([protocol_sha, fit, split, domain, "public-schedule"]).encode()), 16)
                    rng = np.random.Generator(np.random.PCG64(seed))
                    law = full_ctx.protocol["ood_domain" if domain == "ood" else "train_domain"]
                    worlds = []
                    for index in range(count):
                        public = dict(schema=full_ctx.ns["SCHEMA"], id=f"anchored_value_{split}_{domain}_{fit}_{index}",
                            deadline=6, initial_budget=3, target_tick=6,
                            duration=rng.choice(law["durations"], 6).tolist(), drive=rng.choice(law["drives"], 6).tolist(),
                            reliability=rng.choice(law["reliabilities"], 6).tolist(), read_price=rng.choice(law["prices"], 6).tolist(),
                            read_delay=rng.choice(law["delays"], 6).tolist(),
                            prior_distance=float(rng.choice(full_ctx.protocol["prior_distances"])),
                            latency_price=law["latency_price"], repair_price=law["repair_price"],
                            failure_probability=law["failure_probability"],
                            packets=[f"not_opened_{j}.json" for j in range(6)], packet_sha256=["0" * 64] * 6)
                        full_ctx.ns["validate_public"](public)
                        key = schedule_hash(public)
                        if key in used:
                            raise ValueError("historical or new schedule duplicate; stop without resampling")
                        used.add(key)
                        worlds.append(public)
                    collection[fit][domain] = worlds
                    save(out / f"worlds/{split}_{fit}_{domain}.json.gz", dict(seed=str(seed), worlds=worlds))
            dedup = dict(worlds=count * 2 * len(fits), known_prior=len(known), all_seen_unique=len(used),
                collisions=0, no_resampling=True,
                hashes={str(fit): {d: [schedule_hash(x) for x in ws] for d, ws in ds.items()} for fit, ds in collection.items()})
            name = split.upper() + "_DEDUP_BEFORE_SCORING.json"
            digest = save(out / name, dedup)
            events.add(split + "_generated", dict(path=name, sha256=digest))
            return collection
        def score(split, collection):
            scoring_start = time.process_time()
            results = {}
            for fit in protocol["fits"]:
                results[fit] = {}
                for domain, worlds in collection[fit].items():
                    records = []
                    for public in worlds:
                        budget()
                        policy = fits[fit]["model"]
                        compiled, planning_record, _own = p.compile_own(full_ctx, policy, public,
                            protocol["state_caps"]["markov_per_world"])
                        # First policy access to truth occurs only after every TRAIN candidate is frozen.
                        truth = full_ctx.Oracle(public, full_ctx.law, policy.confusion)
                        arm_results = {}
                        for name in RAW_ARMS + (("E_gated", "G_gated") if split == "test" else ()):
                            init_start = time.process_time()
                            world = p.WorldPolicy(full_ctx, public, policy, compiled if name == "J" else None)
                            initialization = time.process_time() - init_start
                            result = p.evaluate(full_ctx, public, world, fits[fit]["arms"][name],
                                                name if name in ("P", "J") else "head", truth)
                            result.update(world_feature_cpu_seconds=world.feature_cpu_seconds,
                                          arm_initialization_cpu_seconds=initialization,
                                          starts_with_empty_feature_cache=True)
                            arm_results[name] = result
                        records.append(dict(world_id=public["id"], schedule_sha256=schedule_hash(public),
                                            own_bellman=planning_record, arms=arm_results))
                    names = list(records[0]["arms"])
                    result = dict(world_count=len(worlds),
                        means={name: float(np.mean([r["arms"][name]["utility"] for r in records])) for name in names},
                        records=records)
                    results[fit][domain] = result
                    filename = f"{split}_{fit}_{domain}_RESULTS.json.gz"
                    digest = save(out / filename, result)
                    events.add(split + "_domain_scored", dict(fit=fit, domain=domain, path=filename, sha256=digest))
                    print(__import__("json").dumps(dict(stage=split, fit=fit, domain=domain,
                                                       cpu_seconds=time.process_time() - start)), flush=True)
                    gc.collect()
            return results, time.process_time() - scoring_start
        stage = "validation"
        validation, validation_cpu = score("validation", new_worlds("validation", protocol["holdout"]["validation_per_fit_domain"]))
        gates = {}
        for fit, domains in validation.items():
            gates[fit] = {}
            for name in ("E", "G"):
                differences = {d: domains[d]["means"][name] - domains[d]["means"]["C"] for d in ("iid", "ood")}
                numeric = bool(fits[fit]["record"]["solvers"][name]["converged"])
                accepted = bool(numeric and min(differences.values()) >= 0. and
                                np.mean(list(differences.values())) >= protocol["holdout"]["minimum_validation_mean_gain"])
                chosen = fits[fit]["arms"][name if accepted else "C"].copy()
                actual, model_record = serialize_model(out, fit, name + "_gated", fits[fit]["incumbent"], chosen, full_ctx)
                fits[fit]["arms"][name + "_gated"] = actual
                recovered = None if accepted else bool(
                    model_record["model_sha256"] == fits[fit]["record"]["models"]["C"]["model_sha256"] and
                    model_record["compressed_sha256"] == fits[fit]["record"]["models"]["C"]["compressed_sha256"])
                if recovered is False:
                    raise ArithmeticError("rejected full model was not restored exactly")
                gates[fit][name] = dict(delta=differences, numeric_pass=numeric, accepted=accepted,
                    chosen_model=model_record, rejected_restoration_verified=recovered)
        gate_sha = save(out / "ALL_GATES_BEFORE_TEST.json", gates)
        events.add("all_gates_frozen", dict(path="ALL_GATES_BEFORE_TEST.json", sha256=gate_sha))
        stage = "test"
        tests, test_cpu = score("test", new_worlds("test", protocol["holdout"]["test_per_fit_domain"]))
        summaries, primary = {}, {}
        for domain in ("iid", "ood"):
            summaries[domain] = {}
            for name in RAW_ARMS + ("E_gated", "G_gated"):
                values = np.array([tests[fit][domain]["means"][name] for fit in protocol["fits"]])
                baseline = np.array([tests[fit][domain]["means"]["C"] for fit in protocol["fits"]])
                delta = values - baseline
                half = student_t.ppf(.975, 4) * delta.std(ddof=1) / np.sqrt(5)
                summaries[domain][name] = dict(mean=float(values.mean()), delta=float(delta.mean()),
                    per_fit=values.tolist(), paired_95_descriptive=[float(delta.mean() - half), float(delta.mean() + half)])
                if name == "E_gated":
                    half = student_t.ppf(1 - .05 / (2 * 2), 4) * delta.std(ddof=1) / np.sqrt(5)
                    interval = [float(delta.mean() - half), float(delta.mean() + half)]
                    primary[name + "_" + domain] = dict(delta=float(delta.mean()),
                        familywise_95_conditional_interval=interval,
                        benefit_pass=interval[0] > protocol["inference"]["minimum_lower_bound_gain"])
        verify_manifest(root, protocol["source_files"])
        verify_manifest(root, input_manifest["files"])
        numeric_E = all(fits[fit]["record"]["solvers"]["E"]["converged"] for fit in fits)
        result = dict(protocol_sha256=protocol_sha, summary=summaries, primary=primary, gates=gates,
            all_E_numeric_pass=bool(numeric_E),
            all_other_endpoint_numeric_pass=bool(all(fits[f]["record"]["solvers"][a]["converged"]
                                                     for f in fits for a in ("G", "EU", "EA"))),
            weight_efficacy_qualified=bool(numeric_E and all(r["benefit_pass"] for r in primary.values())),
            statistical_scope="conditional model-assumption confirmation for five pre-existing training fits; not new-fit replication or distribution-free guarantee",
            structural_controls_are_not_weight_gains=True,
            actual_trader_gain_qualified=False, full_weight_global_optimum_qualified=False,
            full_NDU_economic_net_gain_qualified=False,
            primary_family_size=2, reused_training_fit_count=5, new_training_fit_count=0,
            validation_cpu_seconds=validation_cpu, test_cpu_seconds=test_cpu,
            internal_cpu_seconds_before_final_write=time.process_time() - start,
            internal_wall_seconds_before_final_write=time.perf_counter() - wall,
            arithmetic_audit=full_ctx.arithmetic_audit,
            cost_scope="complete outer worker receipt includes imports and final writes; previous research, base training, agent and energy costs unknown/excluded explicitly",
            source_unchanged=True, all_original_failures_retained=True)
        digest = save(out / "RESULTS.json", result)
        events.add("results_frozen", dict(path="RESULTS.json", sha256=digest))
        print(__import__("json").dumps(dict(stage="complete", weight_efficacy_qualified=result["weight_efficacy_qualified"],
                                           primary=primary)), flush=True)
        return 0
    except BaseException as exc:
        save(out / "FAILED.json", dict(stage=stage, exception_type=type(exc).__name__, error=str(exc),
            traceback=traceback.format_exc(), cpu_seconds=time.process_time() - start,
            wall_seconds=time.perf_counter() - wall, protocol_sha256=protocol_sha,
            smaller_sample_or_changed_candidate_retry_allowed=False))
        traceback.print_exc()
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    sys.exit(main(parser.parse_args()))
