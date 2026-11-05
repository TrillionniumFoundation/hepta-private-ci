"""POSIX-bounded frozen Bellman-to-head experiment; no held-out adaptation."""
import argparse
import copy
import datetime
import gzip
import json
import os
from pathlib import Path
import platform
import resource
import signal
import sys
import time
import traceback
import numpy as np
from scipy.stats import t as student_t
import planning as p
import quadratic as q


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False,
                       default=lambda x: x.tolist() if isinstance(x, np.ndarray) else x.item()) + "\n").encode()


def save(path, value):
    data = json_bytes(value)
    if path.name.endswith(".gz"):
        data = gzip.compress(data, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(data) > 500000:
        parts = []
        for index, offset in enumerate(range(0, len(data), 480000)):
            item = path.with_name(path.name + f".part-{index:03d}"); chunk = data[offset:offset+480000]
            with item.open("xb") as stream:
                stream.write(chunk); stream.flush(); os.fsync(stream.fileno())
            parts.append(dict(name=item.name, bytes=len(chunk), sha256=p.sha(chunk)))
        save(path.with_name(path.name + ".parts.json"), dict(bytes=len(data), sha256=p.sha(data), parts=parts))
    else:
        with path.open("xb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    return p.sha(data)


def read(path):
    if path.exists():
        data = path.read_bytes()
    else:
        manifest = json.loads(path.with_name(path.name + ".parts.json").read_text())
        chunks = [path.with_name(item["name"]).read_bytes() for item in manifest["parts"]]
        assert all(len(b) == m["bytes"] and p.sha(b) == m["sha256"] for b, m in zip(chunks, manifest["parts"]))
        data = b"".join(chunks); assert len(data) == manifest["bytes"] and p.sha(data) == manifest["sha256"]
    return json.loads(gzip.decompress(data) if path.name.endswith(".gz") else data)


def history_paths(root):
    flat = (root / "HISTORY_REGISTRY.json.gz").exists()
    registry = root / "HISTORY_REGISTRY.json.gz" if flat else root / "analytic_belief_compile/HISTORY_REGISTRY.json.gz"
    heads = root / "OLD_CONTINUATION_HEADS.json.gz" if flat else root / "exploratory_belief/OLD_CONTINUATION_HEADS.json.gz"
    worlds = sorted((root if flat else root / "analytic_belief_compile/records").glob("fit_*_*_WORLDS.json.gz"))
    if len(worlds) != 10:
        raise ValueError("all ten previous final-compile world records required")
    return registry, heads, worlds


def model_for(incumbent, theta):
    model = copy.deepcopy(incumbent)
    model["network"]["w2"], model["network"]["b2"] = theta[:, :48].tolist(), theta[:, 48].tolist()
    recovered = copy.deepcopy(model)
    recovered["network"]["w2"] = copy.deepcopy(incumbent["network"]["w2"])
    recovered["network"]["b2"] = copy.deepcopy(incumbent["network"]["b2"])
    assert recovered == incumbent and np.isfinite(theta).all()
    return model


def main(args):
    start, wall = time.process_time(), time.perf_counter(); out = args.output; out.mkdir(exist_ok=False)
    protocol = read(args.protocol); protocol_sha = p.sha(args.protocol.read_bytes())
    assert protocol["status"] == "FROZEN_BEFORE_SCIENTIFIC_RESULTS"
    cpu_limit, wall_limit = protocol["resource_caps"]["single_process_cpu_seconds"], protocol["resource_caps"]["single_process_wall_seconds"]
    def timeout(*unused):
        raise TimeoutError("frozen CPU or wall cap reached")
    signal.signal(signal.SIGALRM, timeout); signal.alarm(wall_limit)
    signal.signal(signal.SIGXCPU, timeout); resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit+5))
    def budget():
        if time.process_time() - start >= cpu_limit or time.perf_counter() - wall >= wall_limit:
            timeout()
    source_paths = {"new/" + x.name: x for x in [Path(__file__), Path(p.__file__), Path(q.__file__)]}
    source_paths["protocol/" + args.protocol.name] = args.protocol
    source_paths.update({"joint/" + x.name: x for x in args.joint.iterdir() if x.suffix == ".py" or x.name in ("joint_protocol.json", "truth_transitions.npz")})
    source_identity = {name: p.sha(x.read_bytes()) for name, x in source_paths.items()}
    save(out / "STARTED.json", dict(protocol_sha256=protocol_sha, sources=source_identity,
         started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), python=sys.version,
         numpy=np.__version__, platform=platform.platform(), resource_caps=protocol["resource_caps"]))
    try:
        ctx = p.load_context(args.joint); mm = ctx.checked_mm
        registry_path, heads_path, old_world_paths = history_paths(args.history)
        history, old_heads = read(registry_path), read(heads_path)
        fields = history["canonical_schedule_fields"]
        def schedule_hash(public):
            return p.sha(p.canonical({k: public[k] for k in fields}).encode())
        known = set()
        for entry in history["entries"]:
            assert schedule_hash(entry["world"]) == entry["schedule_sha256"]
            known.add(entry["schedule_sha256"])
        for path in old_world_paths:
            for public in read(path):
                known.add(schedule_hash(public))
        assert len(known) == 1936
        save(out / "HISTORY_EXCLUSION.json", dict(known_unique_schedules=len(known), schema=ctx.ns["SCHEMA"],
             sources={x.name: p.sha(x.read_bytes()) for x in [registry_path, heads_path, *old_world_paths]},
             not_covered=history["not_covered"], later_feedback_report_read=protocol["source"]["additional_research_read"],
             later_feedback_not_reused="Separate task family; no archived confirmation rows or scores used as targets/selection/holdout"))
        refs = read(args.joint / "INPUT_ACQUISITION.json")
        for item in refs["files"]:
            assert p.sha((args.inputs / item["archive_member"]).read_bytes()) == item["sha256"]
        fits = {}; old_by_fit = {row["fit"]: row for row in old_heads["fits"]}
        for fit in protocol["source"]["fit_ids"]:
            budget(); fit_cpu = time.process_time()
            original = read(args.inputs / f"fit_{fit}/model_renewal/model.json")
            incumbent = copy.deepcopy(original); old = old_by_fit[fit]
            incumbent["network"]["w2"], incumbent["network"]["b2"] = old["network_w2"], old["network_b2"]
            assert p.sha(json_bytes(incumbent)) == old["candidate_model_sha256"]
            A, C = ctx.head(original), ctx.head(incumbent)
            assert np.array_equal(A[3], C[3])
            policy = ctx.NumpyPolicy(incumbent)
            data = read(args.inputs / f"fit_{fit}/data/fit_{fit}_data.json")
            train = ctx.public_unique(data["train"]["rows"]); assert len(train) == 64
            Hs, Ys, Ws, world_records, rows = [], [], [], [], 0
            for public in train:
                budget(); enum_cpu = time.process_time()
                states = p.enumerate_states(ctx, public, True, protocol["training"]["max_full_states_per_world"])
                enumeration_cpu = time.process_time() - enum_cpu
                rows += len(states)
                if rows > protocol["training"]["max_training_rows_per_fit"]:
                    raise OverflowError("frozen TRAIN row cap exceeded")
                compiled, identity, own = p.compile_own(ctx, policy, public, protocol["training"]["max_markov_states_per_world"])
                world = p.WorldPolicy(ctx, public, policy, compiled)
                eligible = sum(any(ctx.legal(public, s)[1:4]) for s in states.values())
                gap, clipped = 0., 0
                for state in states.values():
                    h, bank = world.feature(state); row = compiled["rows"][p.markov_key(state)]
                    gap = max(gap, abs(bank - row["belief"]))
                    probability = float(np.clip(row["belief"], 1e-12, 1-1e-12)); clipped += probability != row["belief"]
                    mask = np.asarray(row["legal"][1:4], dtype=float); count = mask.sum()
                    weights = mask / (len(train) * eligible * count) if count else mask
                    Hs.append(h); Ys.append([*row["q"][1:4], np.log(probability)-np.log1p(-probability)])
                    Ws.append([*weights, 1 / (len(train) * len(states))])
                if gap > 2e-12:
                    raise ArithmeticError("own-law posterior differs from deployed bank7")
                world_records.append(dict(world_id=public["id"], schedule_sha256=schedule_hash(public),
                     full_states=len(states), continuation_eligible_states=eligible, posterior_identity_max=gap,
                     clipped_logit_targets=clipped, enumeration_cpu_seconds=enumeration_cpu,
                     feature_cpu_seconds=world.feature_cpu_seconds, own_bellman=identity))
            H, Y, W = np.asarray(Hs), np.asarray(Ys), np.asarray(Ws)
            del Hs, Ys, Ws
            shared_preparation_cpu = time.process_time() - fit_cpu
            D, G, reports, problems = C.copy(), C.copy(), {}, {}
            for name, selection in (("continuation", slice(0, 3)), ("belief", slice(3, 4))):
                problem = q.prepare(H, Y[:, selection], W[:, selection], C[selection], mm)
                D[selection], direct = q.direct(problem, mm, budget)
                G[selection], gradient = q.pgd(problem, mm, budget)
                reports[name] = dict(direct=direct, gradient=gradient, shared_setup_cpu_seconds=problem["setup_cpu_seconds"],
                                     shared_setup_wall_seconds=problem["setup_wall_seconds"])
                problems[name] = {k: problem[k] for k in ("original", "matrices", "rhs", "values", "radius", "L")}
            rng = np.random.Generator(np.random.PCG64(int(p.sha(p.canonical([protocol_sha, fit, "random-edit"]).encode()), 16)))
            R = C.copy()
            for selection in (slice(0, 3), slice(3, 4)):
                delta = rng.normal(size=C[selection].shape); delta *= np.linalg.norm(D[selection] - C[selection]) / np.linalg.norm(delta)
                R[selection], _, _ = q.stored_point(C[selection], delta, .5 * np.linalg.norm(C[selection]) * (1-1e-8))
            DQ, DB = C.copy(), C.copy(); DQ[:3] = D[:3]; DB[3] = D[3]
            arms = dict(A=A, C=C, P=C, J=C, D=D, G=G, DQ=DQ, DB=DB, R=R)
            identities = {}
            for name in ("A", "C", "D", "G", "DQ", "DB", "R"):
                serialization_start = time.process_time()
                model = model_for(incumbent, arms[name]); path = out / f"models/fit_{fit}_{name}.json.gz"
                identities[name] = dict(model_sha256=p.sha(json_bytes(model)), compressed_sha256=save(path, model))
                loaded = read(path); assert loaded == model
                arms[name] = ctx.head(loaded); assert np.array_equal(arms[name], ctx.head(model))
                identities[name]["serialize_save_load_cpu_seconds"] = time.process_time() - serialization_start
            arms["P"], arms["J"] = arms["C"], arms["C"]
            record = dict(fit=fit, rows=rows, source_model_sha256=old["source_model_sha256"],
                          incumbent_sha256=old["candidate_model_sha256"], models=identities, heads=arms,
                          solvers=reports, problems=problems, training_worlds=world_records,
                          H_sha256=p.sha(H.tobytes()), Y_sha256=p.sha(Y.tobytes()), W_sha256=p.sha(W.tobytes()),
                          source_and_restore_verified=True, shared_data_bellman_feature_preparation_cpu_seconds=shared_preparation_cpu,
                          candidate_cpu_seconds=time.process_time()-fit_cpu)
            save(out / f"fit_{fit}_CANDIDATES.json.gz", record)
            fits[fit] = dict(model=policy, arms=arms, record=record)
            print(json.dumps(dict(stage="candidates_frozen", fit=fit, rows=rows, cpu_seconds=time.process_time()-start)), flush=True)
        save(out / "ALL_CANDIDATES_BEFORE_VALIDATION.json", {str(fit): state["record"]["models"] for fit, state in fits.items()})
        used = set(known)
        def new_worlds(split, count):
            collection = {}
            for fit in fits:
                collection[fit] = {}
                for domain in ("iid", "ood"):
                    seed = int(p.sha(p.canonical([protocol_sha, fit, split, domain, "public-schedule"]).encode()), 16)
                    rng = np.random.Generator(np.random.PCG64(seed)); law = ctx.protocol["ood_domain" if domain == "ood" else "train_domain"]
                    worlds = []
                    for index in range(count):
                        public = dict(schema=ctx.ns["SCHEMA"], id=f"own_bellman_{split}_{domain}_{fit}_{index}", deadline=6,
                            initial_budget=3, target_tick=6, duration=rng.choice(law["durations"], 6).tolist(), drive=rng.choice(law["drives"], 6).tolist(),
                            reliability=rng.choice(law["reliabilities"], 6).tolist(), read_price=rng.choice(law["prices"], 6).tolist(),
                            read_delay=rng.choice(law["delays"], 6).tolist(), prior_distance=float(rng.choice(ctx.protocol["prior_distances"])),
                            latency_price=law["latency_price"], repair_price=law["repair_price"], failure_probability=law["failure_probability"],
                            packets=[f"not_opened_{j}.json" for j in range(6)], packet_sha256=["0"*64]*6)
                        ctx.ns["validate_public"](public); identity = schedule_hash(public)
                        if identity in used:
                            raise ValueError("known/repeated public schedule: stop without resampling")
                        used.add(identity); worlds.append(public)
                    collection[fit][domain] = worlds
                    save(out / f"worlds/{split}_{fit}_{domain}.json.gz", dict(seed=str(seed), worlds=worlds))
            save(out / f"{split.upper()}_DEDUP_BEFORE_SCORING.json", dict(worlds=count*2*len(fits), known_prior=len(known),
                 all_seen_unique=len(used), collisions=0, no_resampling=True, hashes={str(fit): {d: [schedule_hash(x) for x in w] for d, w in ds.items()} for fit, ds in collection.items()}))
            return collection
        def score(split, collection):
            results = {}
            for fit, domains in collection.items():
                results[fit] = {}
                for domain, worlds in domains.items():
                    records = []
                    for public in worlds:
                        budget(); policy = fits[fit]["model"]
                        compiled, identity, _ = p.compile_own(ctx, policy, public, protocol["training"]["max_markov_states_per_world"])
                        truth = ctx.Oracle(public, ctx.law, policy.confusion); arm_results = {}
                        for name, theta in fits[fit]["arms"].items():
                            initialization = time.process_time()
                            world = p.WorldPolicy(ctx, public, policy, compiled if name == "J" else None)
                            setup = time.process_time() - initialization
                            result = p.evaluate(ctx, public, world, theta, name if name in ("P", "J") else "head", truth)
                            result.update(world_feature_cpu_seconds=world.feature_cpu_seconds, arm_initialization_cpu_seconds=setup,
                                          starts_with_empty_feature_cache=True)
                            arm_results[name] = result
                        records.append(dict(world_id=public["id"], schedule_sha256=schedule_hash(public), own_bellman=identity, arms=arm_results))
                    results[fit][domain] = dict(world_count=len(worlds), means={name: float(np.mean([r["arms"][name]["utility"] for r in records])) for name in fits[fit]["arms"]}, records=records)
                    save(out / f"{split}_{fit}_{domain}_RESULTS.json.gz", results[fit][domain])
                    print(json.dumps(dict(stage=split, fit=fit, domain=domain, cpu_seconds=time.process_time()-start)), flush=True)
            return results
        validation = score("validation", new_worlds("validation", protocol["validation_and_test"]["validation_worlds_per_fit_domain"]))
        gates = {}
        for fit, domains in validation.items():
            gates[fit] = {}
            for name in ("D", "G", "R"):
                delta = {d: domains[d]["means"][name]-domains[d]["means"]["C"] for d in ("iid", "ood")}
                numeric = name == "R" or all(fits[fit]["record"]["solvers"][g]["direct" if name == "D" else "gradient"]["converged"] for g in ("continuation", "belief"))
                accepted = bool(numeric and min(delta.values()) >= 0 and np.mean(list(delta.values())) >= .005)
                chosen = fits[fit]["arms"][name if accepted else "C"]
                fits[fit]["arms"][name+"_gated"] = chosen.copy()
                gates[fit][name] = dict(delta=delta, numeric_pass=numeric, accepted=accepted,
                                      rejected_restoration_verified=bool(accepted or np.array_equal(chosen, fits[fit]["arms"]["C"])))
        save(out / "ALL_GATES_BEFORE_TEST.json", gates)
        tests = score("test", new_worlds("test", protocol["validation_and_test"]["test_worlds_per_fit_domain"]))
        summaries, primary = {}, {}
        for domain in ("iid", "ood"):
            summaries[domain] = {}
            for name in fits[next(iter(fits))]["arms"]:
                values = np.array([tests[f][domain]["means"][name] for f in fits])
                differences = values - np.array([tests[f][domain]["means"]["C"] for f in fits])
                half = student_t.ppf(.975, 4) * differences.std(ddof=1) / np.sqrt(5)
                summaries[domain][name] = dict(mean=float(values.mean()), delta=float(differences.mean()), per_fit=values.tolist(),
                    paired_95_descriptive=[float(differences.mean()-half), float(differences.mean()+half)])
                if name in ("D_gated", "J"):
                    half = student_t.ppf(1-.05/8, 4) * differences.std(ddof=1) / np.sqrt(5)
                    interval = [float(differences.mean()-half), float(differences.mean()+half)]
                    primary[name+"_"+domain] = dict(delta=float(differences.mean()), familywise_95_interval=interval, benefit_pass=interval[0] > .005)
        numeric_pass = all(s[method]["converged"] for state in fits.values() for s in state["record"]["solvers"].values() for method in ("direct", "gradient"))
        assert source_identity == {name: p.sha(x.read_bytes()) for name, x in source_paths.items()}
        summary = dict(protocol_sha256=protocol_sha, summary=summaries, primary=primary, gates=gates, all_numeric_pass=numeric_pass,
             weight_efficacy_qualified=numeric_pass and all(primary["D_gated_"+d]["benefit_pass"] for d in ("iid", "ood")),
             structural_efficacy_qualified=all(primary["J_"+d]["benefit_pass"] for d in ("iid", "ood")),
             full_economic_net_value_qualified=False, energy_qualified=False, production_qualified=False,
             cpu_seconds=time.process_time()-start, wall_seconds=time.perf_counter()-wall,
             peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
             arithmetic=ctx.arithmetic_audit, source_unchanged=True, known_history_unique=len(known), final_seen_unique=len(used),
             scope="existing five fits; finite expected task utility; OOD distribution exposed in new validation; no packet execution or global weight-space optimum")
        save(out / "RESULTS.json", summary); print(json.dumps(summary, sort_keys=True), flush=True)
    except BaseException as error:
        save(out / "FAILED.json", dict(type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
             cpu_seconds=time.process_time()-start, wall_seconds=time.perf_counter()-wall, all_partial_records_preserved=True))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("joint", "inputs", "history", "protocol", "output"):
        parser.add_argument("--"+name, required=True, type=Path)
    arguments = parser.parse_args()
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        main(arguments)
