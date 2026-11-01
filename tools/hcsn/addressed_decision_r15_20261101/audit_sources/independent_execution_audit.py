
import os, sys, time, json, hashlib, gzip, math, traceback
from pathlib import Path
from datetime import datetime, timezone

BASE = Path("tools/hcsn/addressed_decision_r15_20261101").resolve()
OUT = BASE / "results" / "INDEPENDENT_EXECUTION_AUDIT.json"
MD = BASE / "results" / "INDEPENDENT_EXECUTION_AUDIT.md"
if OUT.exists() or MD.exists():
    raise RuntimeError("Independent audit artifacts already exist; preserve them")
outer_start = time.process_time()
pid = os.fork()
if pid == 0:
    started = time.process_time()
    wall = time.perf_counter()
    try:
        import numpy as np
        from scipy.linalg import expm
        from tools.hcsn.addressed_decision_r15_20261101.law import Law
        from tools.hcsn.addressed_decision_r15_20261101.numerics_study import make_memoryless

        def canonical(x):
            return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)
        def sha(path):
            h = hashlib.sha256()
            with Path(path).open("rb") as f:
                for b in iter(lambda: f.read(1048576), b""):
                    h.update(b)
            return h.hexdigest()
        def read(path):
            path = Path(path)
            with (gzip.open(path, "rt") if path.suffix == ".gz" else path.open()) as f:
                return json.load(f)

        counts = {}
        failures = []
        count_failures = 0
        max_errors = {}
        def check(ok, kind, where="", detail=None):
            global count_failures
            counts[kind] = counts.get(kind, 0) + 1
            if not bool(ok):
                count_failures += 1
                if len(failures) < 40:
                    failures.append(dict(check=kind, where=str(where), detail=detail))
        def close(x, y, kind, where="", atol=1e-12):
            error = abs(float(x) - float(y))
            max_errors[kind] = max(max_errors.get(kind, 0.), error)
            check(math.isfinite(float(x)) and math.isfinite(float(y)) and error <= atol,
                  kind, where, dict(observed=float(x), recomputed=float(y), difference=error))
        def assert_checkpoint(cp, memory, where):
            body = dict(cp)
            checksum = body.pop("sha256", None)
            check(checksum == hashlib.sha256(canonical(body).encode()).hexdigest(),
                  "saved_checkpoint_self_hash", where)
            expected = memory.checkpoint()
            check(cp == expected, "independent_checkpoint_reconstruction", where)
        class MatrixModel:
            def __init__(self, law):
                self.identity = law.identity
                self.Q = np.array(law.Q)
                self.prior = np.array(law.prior)
                self.reward = np.array(law.reward)
                self.E = {"read": np.array(law.E_read), "refresh": np.array(law.E_refresh)}
                self.cache = {}
                self.reward_cache = {}
            def transition(self, dt):
                dt = float(dt)
                if dt not in self.cache:
                    self.cache[dt] = expm(dt * self.Q)
                return self.cache[dt]
            def deadline_reward(self, dt):
                dt = float(dt)
                if dt not in self.reward_cache:
                    self.reward_cache[dt] = self.transition(dt) @ self.reward
                return self.reward_cache[dt]
        class IndependentMemory:
            def __init__(self, model, initial, projection):
                self.model, self.projection = model, projection
                self.p = np.tile(model.prior, (4, 1))
                self.clock = 0.
                self.operations = dict(propagations=0, observations=0, writes=0)
                for key, value in enumerate(initial):
                    self.write(key, value)
            def project(self, p):
                if self.projection == "full":
                    return p.copy()
                joint = p.reshape(*p.shape[:-1], 10, 4)
                phase, content = joint.sum(-1), joint.sum(-2)
                if self.projection == "mean":
                    average = phase @ np.arange(10)
                    lower = np.minimum(np.floor(average).astype(int), 8)
                    fraction = average - lower
                    phase = np.eye(10)[lower] * (1 - fraction)[..., None]
                    phase += np.eye(10)[lower + 1] * fraction[..., None]
                return (phase[..., :, None] * content[..., None, :]).reshape(p.shape)
            def write(self, key, value):
                phase = self.p[key].reshape(10, 4).sum(axis=1)
                joint = np.zeros((10, 4))
                joint[:, value] = phase
                self.p[key] = joint.ravel()
                self.operations["writes"] += 1
            def advance(self, dt):
                if dt:
                    self.p = self.project(self.p @ self.model.transition(float(dt)))
                    self.clock += float(dt)
                    self.operations["propagations"] += 4
            def observe(self, key, token, quality):
                raw = self.p[key] * self.model.E[quality][:, token]
                mass = float(raw.sum())
                if mass > 0:
                    self.p[key] = self.project(raw / mass)
                    self.operations["observations"] += 1
                return mass
            def answer(self, key, dt):
                return int(np.argmax(self.p[key] @ self.model.deadline_reward(dt)))
            def checkpoint(self):
                body = dict(schema="hcsn-r15-addressed-state-v1", model=self.model.identity,
                            clock=self.clock, beliefs=self.p.tolist(), projection=self.projection,
                            method="expm", operations=self.operations.copy())
                body["sha256"] = hashlib.sha256(canonical(body).encode()).hexdigest()
                return body

        run = BASE / "run_02"
        source = read(BASE / "SOURCE_MANIFEST.json")
        supplement = read(BASE / "SUPPLEMENT_MANIFEST.json")
        protocol = read(BASE / "PROTOCOL.json")
        spec = read(BASE / "SUPPLEMENT_PROTOCOL.json")
        pub = read(run / "SUPPLEMENT_PUBLICATION.json")
        frozen = read(run / "FREEZE.json")
        old_frozen = read(BASE / "run_01/FREEZE.json")
        old_pub = read(BASE / "run_01/FREEZE_PUBLICATION.json")
        launch = read(run / "supervisor/confirm_launch.json")
        summary = read(run / "supervisor/confirm_summary.json")
        roots = BASE.parents[2]
        def check_sources():
            for n, expected in source["files"].items():
                check(sha(roots / n) == expected, "original_source_hash", n)
            for n, expected in supplement["files"].items():
                check(sha(BASE / n) == expected, "supplement_source_hash", n)
        check_sources()
        for n, expected in pub["remote_blob_shas"].items():
            b = (roots / n).read_bytes()
            got = hashlib.sha1(b"blob " + str(len(b)).encode() + b"\x00" + b).hexdigest()
            check(got == expected, "publication_receipt_git_blob", n)
        check(summary["receipts"] == 16 and summary["failed"] == [], "complete_supervisor")
        check(old_pub["freeze_commit"] == spec["original_model_freeze_commit"],
              "original_freeze_commit")
        check(sha(BASE / "run_01/FREEZE.json") == old_pub["freeze_sha256"] ==
              frozen["original_freeze_sha256"], "original_freeze_bytes")
        check(frozen["training"] == old_frozen["training"] and
              frozen["selections"] == old_frozen["selections"], "unchanged_frozen_models_and_selection")
        check(pub["remote_readback_verified"] is True and old_pub["remote_readback_verified"] is True,
              "publication_verified_flags")
        check(sha(run / "FREEZE.json") == pub["freeze_sha256"], "supplement_freeze_bytes")
        check(sha(BASE / "SUPPLEMENT_MANIFEST.json") == pub["supplement_manifest_sha256"] ==
              frozen["supplement_manifest_sha256"], "supplement_manifest_identity")
        check(sha(BASE / "SOURCE_MANIFEST.json") == spec["original_source_manifest_sha256"],
              "original_manifest_identity")
        check(launch["commit"] == pub["supplement_commit"] and launch["development"] is False,
              "launch_identity")
        check(pub["verified_at"] < launch["opened_at"], "publication_before_launch")
        expected_jobs = [(seed, domain) for seed in spec["fit_seeds"] for domain in ("iid", "ood")]
        check([list(j) for j in expected_jobs] == launch["jobs"], "exact_registered_jobs")
        files = sorted((run / "confirmation").glob("*.json.gz"))
        check(len(files) == 16 and {f.name for f in files} ==
              {f"{seed}_{domain}.json.gz" for seed, domain in expected_jobs}, "exact_result_files")
        complete_arms = ("A", "B", "C", "D", "hmm_same_matrix", "free_value",
                         "factorized_value", "memoryless_value", "learned_state_confidence",
                         "learned_stop_value", "learned_value_risk", "learned_ordinary_dual")
        all_arms = set(complete_arms) | {"mean_value"}
        train = {}
        models = {}
        for seed in spec["fit_seeds"]:
            path = BASE / "run_01/training" / f"{seed}.json.gz"
            check(sha(path) == frozen["training"][path.name], "frozen_training_file", seed)
            t = read(path)
            check(t["seed"] == seed and t["development"] is False and
                  t["source_commit"] == spec["original_source_commit"] and
                  t["source_manifest_sha256"] == spec["original_source_manifest_sha256"],
                  "frozen_training_provenance", seed)
            train[seed] = t
            payloads = t["calibration"]["models"]
            check(payloads["hx"]["payload"] == payloads["hmm_same_matrix"]["payload"],
                  "same_matrix_model_payload", seed)
            hx = Law.from_payload(payloads["hx"]["payload"])
            free = Law.from_payload(payloads["free"]["payload"])
            memoryless = make_memoryless(hx)
            selected = hx if t["ordinary_selected"] == "hmm_same_matrix" else free
            laws = {name: hx for name in all_arms}
            laws.update(A=selected, B=selected, free_value=free, memoryless_value=memoryless)
            cache = {law.identity: MatrixModel(law) for law in laws.values()}
            models[seed] = {name: cache[law.identity] for name, law in laws.items()}
        world_law = Law(theta=tuple(protocol["world_theta"]))
        unique_worlds = set()
        unique_left_sensitive_observations = set()
        left_sensitive_targets = 0
        writes_changed = 0
        raw_query_count = 0
        valid_query_count = 0
        observed_token_count = 0
        checkpoint_query_count = 0
        action_counts = {"READ": 0, "REFRESH": 0, "WAIT": 0}
        by_worker = []
        progress_proofs = {}
        result_hashes = {}
        mean_failures = []
        seen_jobs = set()
        receipts_cpu = 0.

        def seed_hash(*parts):
            return int.from_bytes(hashlib.blake2b(
                json.dumps(parts, separators=(",", ":"), allow_nan=False).encode(),
                digest_size=16).digest(), "big")
        def scale_for(seed, query):
            return (.5, 1., 2., 4.)[
                hashlib.sha256(f"r15-price:{seed}:{query}".encode()).digest()[0] % 4]
        def state_at(tape, key, when, side):
            path = tape["paths"][key]
            i = max(0, int(np.searchsorted(path["times"], when, side=side)) - 1)
            return path["states"][i]
        def emission(state, quality):
            if quality == "refresh":
                e = np.full(4, .01)
                e[state % 4] = .97
                return e
            if state // 4 >= 8:
                return np.array([0., 0., 0., 0., 1.])
            e = np.array([.1, .1, .1, .1, 0.])
            e[state % 4] = .7
            return e
        def expected_token(tape, key, query, step, quality, side=None):
            starts = [0.] + tape["deadlines"][:-1]
            when = float(tape["deadlines"][query] if step == 3 else
                         starts[query] + step * tape["dts"][query])
            state = state_at(tape, key, when, side or ("left" if step == 3 else "right"))
            noise = seed_hash("r15-emission", tape["seed"], tape["domain"], int(key),
                              when.hex(), quality, int(query), int(step))
            u = min(float(((noise >> 64) + .5) / 2 ** 64), np.nextafter(1., 0.))
            return int(np.searchsorted(np.cumsum(emission(state, quality)), u, side="right"))

        def validate_tape(tape, fit_seed, domain, index):
            global left_sensitive_targets, writes_changed
            label = f"{fit_seed}:{domain}:{index}"
            expected_seed = 4 * 10**12 + fit_seed * 10**5 + (10000 if domain == "ood" else 0) + index
            check(tape["seed"] == expected_seed and tape["domain"] == domain, "world_seed_namespace", label)
            check(tape["fingerprint"] not in unique_worlds, "unique_world_fingerprint", label)
            unique_worlds.add(tape["fingerprint"])
            dts = tape["dts"]; starts = [0.] + tape["deadlines"][:-1]
            check(len(dts) == len(tape["query_keys"]) == len(tape["deadlines"]) ==
                  len(tape["public_events"]) == 6, "world_six_queries", label)
            check(sorted(tape["initial_values"]) == [0, 1, 2, 3] and
                  sorted(tape["query_keys"][:4]) == [0, 1, 2, 3], "initial_and_query_address_coverage", label)
            check(all(dt in protocol[f"{domain}_dt"] for dt in dts), "registered_time_grid", label)
            check(np.allclose(tape["deadlines"], np.cumsum(3 * np.asarray(dts)), rtol=0, atol=0),
                  "deadline_schedule", label)
            metadata = dict(schema="hcsn-r15-world-tape-v1", law=world_law.identity,
                            seed=tape["seed"], domain=domain, initial_values=tape["initial_values"],
                            query_keys=tape["query_keys"], dts=dts, deadlines=tape["deadlines"],
                            events=tape["public_events"],
                            paths=[(v["times"], v["states"]) for v in tape["paths"]])
            check(hashlib.sha256(canonical(metadata).encode()).hexdigest() == tape["fingerprint"],
                  "world_fingerprint_reconstruction", label)
            forced = {key: {} for key in range(4)}
            for q, events in enumerate(tape["public_events"]):
                ws = [e for e in events if e["kind"] == "WRITE"]
                ds = [e for e in events if e["kind"] == "DISTRACTOR"]
                check(len(ws) == int(q in (2, 4)) and len(ds) == 1 and
                      len(events) == len(ws) + 1, "typed_event_pattern", label)
                for ev in events:
                    check(ev["time"] == starts[q] and 0 <= ev["key"] < 4 and
                          0 <= ev["value"] < 4, "public_event_metadata", label)
                check(ds[0]["key"] != tape["query_keys"][q] and
                      (not ws or ds[0]["key"] != ws[0]["key"]), "distractor_distinct_address", label)
                for ev in ws:
                    forced[ev["key"]][ev["time"]] = ev["value"]
                    before = state_at(tape, ev["key"], ev["time"], "left")
                    after = state_at(tape, ev["key"], ev["time"], "right")
                    check(before // 4 == after // 4 and after % 4 == ev["value"],
                          "write_preserves_latent_phase", label)
                    writes_changed += int(before % 4 != after % 4)
                key, deadline = tape["query_keys"][q], tape["deadlines"][q]
                left_sensitive_targets += int(state_at(tape, key, deadline, "left") % 4 !=
                                              state_at(tape, key, deadline, "right") % 4)
            for key, path in enumerate(tape["paths"]):
                ts, ss = path["times"], path["states"]
                check(len(ts) == len(ss) and len(ts) > 0 and ts[0] == 0 and
                      all(ts[j] < ts[j+1] for j in range(len(ts)-1)) and
                      ts[-1] <= tape["deadlines"][-1] and all(0 <= s < 40 for s in ss),
                      "path_shape_order_range", label)
                check(ss[0] % 4 == tape["initial_values"][key] and
                      world_law.phase_prior[ss[0] // 4] > 0, "initial_latent_state_support", label)
                check(all(t in ts for t in forced[key]), "writes_present_in_world_path", label)
                for j in range(1, len(ts)):
                    if ts[j] in forced[key]:
                        ok = ss[j] // 4 == ss[j-1] // 4 and ss[j] % 4 == forced[key][ts[j]]
                    else:
                        ok = world_law.Q[ss[j-1], ss[j]] > 0 and ss[j-1] != ss[j]
                    check(ok, "path_transition_support", label)

        def validate_episode(ep, tape, model, arm, fit_seed, index):
            global raw_query_count, valid_query_count, observed_token_count, checkpoint_query_count
            loc = f"{fit_seed}:{tape['domain']}:{index}:{arm}"
            check(ep["seed"] == tape["seed"] and ep["world"] == tape["fingerprint"],
                  "episode_pairing", loc)
            invalid = ep["status"] == "invalid_support"
            check(ep["status"] == "completed" or (arm == "mean_value" and invalid),
                  "declared_episode_status", loc)
            if arm != "mean_value":
                check(not invalid, "twelve_arms_complete", loc)
            proj = "mean" if arm == "mean_value" else ("factorized" if arm == "factorized_value" else "full")
            policy = "fixed" if arm in ("A", "C") else ("learned" if arm.startswith("learned_") else "value")
            check(ep["projection"] == proj and ep["policy"] == policy, "declared_arm_configuration", loc)
            check(math.isfinite(ep["cpu_seconds"]) and ep["cpu_seconds"] >= 0, "episode_cpu_finite", loc)
            if not invalid:
                check(ep["method"] == "expm" and ep["state_bytes"] == 1280, "method_and_belief_storage", loc)
                expected_pattern = train[fit_seed]["light_pattern"] if arm in ("A", "C") else "read"
                check(ep["pattern"] == expected_pattern, "frozen_fixed_pattern", loc)
            memory = IndependentMemory(model, tape["initial_values"], proj)
            queries = ep["failure"]["completed_queries"] if invalid else ep["queries"]
            check(len(queries) == (ep["failure"]["query"] if invalid else 6), "query_record_count", loc)
            starts = [0.] + tape["deadlines"][:-1]
            episode_fees, episode_rewards = [], []
            own_action_counts = {"READ": 0, "REFRESH": 0, "WAIT": 0}

            def begin_query(q):
                close(memory.clock, starts[q], "all_address_query_start_clock", loc, 1e-10)
                for event in tape["public_events"][q]:
                    if event["kind"] == "WRITE":
                        memory.write(event["key"], event["value"])

            def apply_actions(q, actions):
                global observed_token_count
                key, dt = tape["query_keys"][q], tape["dts"][q]
                scale = scale_for(tape["seed"], q)
                elapsed, fee = 0, 0.
                for a in actions:
                    action = a["action"]
                    check(action in own_action_counts, "legal_recorded_action", loc)
                    if action not in own_action_counts:
                        raise ValueError(f"Unknown action in raw evidence: {loc}")
                    slots = 2 if action == "REFRESH" else 1
                    elapsed += slots
                    check(elapsed <= 3 and a["step"] == elapsed, "action_step_duration", loc)
                    close(a["time"], starts[q] + elapsed * dt, "action_completion_time", loc, 1e-10)
                    memory.advance(slots * dt)
                    fee += .003 * slots * dt
                    if action != "WAIT":
                        quality = action.lower()
                        token = expected_token(tape, key, q, elapsed, quality)
                        check(a["token"] == token, "independent_emission_token", loc)
                        observed_token_count += 1
                        if elapsed == 3 and token != expected_token(tape, key, q, elapsed, quality, "right"):
                            unique_left_sensitive_observations.add((tape["seed"], q, key, quality))
                        mass = memory.observe(key, a["token"], quality)
                        check(mass > 0, "completed_observation_positive_support", loc)
                        fee += (.025 if action == "READ" else .07) * scale
                    else:
                        check(a["token"] is None, "wait_has_no_observation", loc)
                    own_action_counts[action] += 1
                    action_counts[action] += 1
                return elapsed, fee

            for q, record in enumerate(queries):
                raw_query_count += 1
                if arm != "mean_value":
                    valid_query_count += 1
                begin_query(q)
                if not invalid and index == 0:
                    assert_checkpoint(ep["states"][q], memory, loc + f":prefix{q}")
                key, dt = tape["query_keys"][q], tape["dts"][q]
                check(record["query"] == q and record["key"] == key and
                      record["dt"] == dt and record["deadline"] == tape["deadlines"][q] and
                      record["events"] == tape["public_events"][q], "query_public_metadata", loc)
                close(record["price_scale"], scale_for(tape["seed"], q), "public_price_key", loc, 0)
                done, fee = apply_actions(q, record["actions"])
                if policy == "learned":
                    check(len(record["actions"]) <= 1 and all(a["action"] != "WAIT" for a in record["actions"]),
                          "learned_one_action_scope", loc)
                if policy == "fixed":
                    check(not record["actions"] and train[fit_seed]["light_pattern"] == "stop",
                          "actual_frozen_stop_pattern", loc)
                check(record["answer"] == memory.answer(key, (3-done) * dt),
                      "causal_deadline_answer_reconstruction", loc)
                close(record["submitted_after"], done * dt, "submission_elapsed_duration", loc)
                memory.advance((3-done) * dt)
                close(memory.clock, tape["deadlines"][q], "all_address_deadline_clock", loc, 1e-10)
                expected_target = state_at(tape, key, tape["deadlines"][q], "left") % 4
                check(record["target"] == expected_target, "independent_left_limit_target", loc)
                reward = int(record["answer"] == expected_target)
                check(record["reward"] == reward, "query_correctness_reconstruction", loc)
                close(record["fee"], fee, "query_fee_reconstruction", loc)
                close(record["utility"], reward-fee, "query_utility_reconstruction", loc)
                check(record["checkpoint_sha256"] == memory.checkpoint()["sha256"],
                      "all_address_query_checkpoint_hash", loc)
                checkpoint_query_count += 1
                episode_fees.append(fee); episode_rewards.append(reward)

            if invalid:
                f = ep["failure"]; q = f["query"]
                check(all(ep[k] is None for k in ("utility", "reward", "fee", "all_queries_correct")),
                      "invalid_support_null_outcomes", loc)
                check(proj == "mean" and 0 <= q < 6 and f["quality"] in ("read", "refresh"),
                      "mean_failure_scope", loc)
                begin_query(q)
                done, fee = apply_actions(q, f["current_query_prior_actions"])
                key, dt, quality = tape["query_keys"][q], tape["dts"][q], f["quality"]
                slots = 1 if quality == "read" else 2
                done += slots
                check(f["key"] == key and done <= 3 and f["completed_step"] == done,
                      "failed_action_duration", loc)
                memory.advance(slots * dt)
                fee += .003 * slots * dt
                close(f["clock"], memory.clock, "failed_action_clock", loc, 1e-10)
                check(f["token"] == expected_token(tape, key, q, done, quality),
                      "failed_observation_is_real_keyed_token", loc)
                expected_mass = float((memory.p[key] * model.E[quality][:, f["token"]]).sum())
                check(expected_mass == 0. and f["observation_likelihood"] == 0.,
                      "independent_exact_zero_support", loc)
                assert_checkpoint(f["checkpoint"], memory, loc + ":failure")
                close(f["current_query_fee_before_failed_observation"], fee,
                      "failure_active_and_prior_fee", loc)
                observation_fee = (.025 if quality == "read" else .07) * scale_for(tape["seed"], q)
                close(f["failed_observation_fee"], observation_fee, "failure_observation_fee", loc)
                close(f["current_query_total_incurred_fee"], fee + observation_fee,
                      "failure_current_query_incurred_fee", loc)
                check('planner.py", line 54, in observe' in f["traceback"] and
                      "ValueError: Impossible observation" in f["traceback"],
                      "failure_exception_origin_receipt", loc)
                observed_token_count += 1
                action_counts[quality.upper()] += 1
                mean_failures.append(dict(fit_seed=fit_seed, domain=tape["domain"], index=index,
                                         episode_seed=tape["seed"], query=q, token=f["token"],
                                         quality=quality, likelihood=expected_mass,
                                         checkpoint=f["checkpoint"]["sha256"],
                                         current_query_incurred_fee=fee+observation_fee,
                                         total_incurred_fee=sum(episode_fees)+fee+observation_fee,
                                         cpu_seconds=ep["cpu_seconds"]))
            else:
                close(ep["fee"], np.mean(episode_fees), "episode_fee_aggregation", loc)
                close(ep["reward"], np.mean(episode_rewards), "episode_reward_aggregation", loc)
                close(ep["utility"], np.mean(np.asarray(episode_rewards)-np.asarray(episode_fees)),
                      "episode_utility_aggregation", loc)
                check(ep["all_queries_correct"] is bool(all(episode_rewards)),
                      "all_queries_correct_reconstruction", loc)
                for singular, plural in (("READ", "reads"), ("REFRESH", "refreshes"), ("WAIT", "waits")):
                    check(ep[plural] == own_action_counts[singular], "episode_action_count", loc)
                check((index == 0 and len(ep["states"]) == 6) or (index != 0 and ep["states"] is None),
                      "declared_state_capture_scope", loc)

        for path in files:
            d = read(path)
            seed, domain = d["seed"], d["domain"]
            job = (seed, domain); seen_jobs.add(job)
            label = f"{seed}_{domain}"
            result_hashes[path.name] = sha(path)
            claim = read(run / "claims" / f"confirm_{label}.json")
            receipt = read(run / "supervisor" / f"confirm_{label}.json")
            check(job in expected_jobs and d["count"] == 128 and d["development"] is False,
                  "worker_registered_design", label)
            check(d["source_commit"] == spec["original_source_commit"] and
                  d["supplement_commit"] == d["freeze_commit"] == pub["supplement_commit"] and
                  d["freeze_sha256"] == pub["freeze_sha256"] and
                  d["supplement_manifest_sha256"] == pub["supplement_manifest_sha256"],
                  "worker_frozen_provenance", label)
            check(claim["seed"] == seed and claim["domain"] == domain and
                  claim["development"] is False and claim["supplement_commit"] == pub["supplement_commit"] and
                  claim["freeze_sha256"] == pub["freeze_sha256"], "claim_provenance", label)
            check(pub["verified_at"] < launch["opened_at"] < claim["opened_at"] ==
                  d["opened_at"] < d["completed_at"] < receipt["completed_at"],
                  "publication_claim_completion_chronology", label)
            check(receipt["exit_code"] == 0 and receipt["seed"] == seed and receipt["domain"] == domain,
                  "successful_worker_receipt", label)
            receipts_cpu += receipt["total_cpu_seconds"]
            close(receipt["total_cpu_seconds"], receipt["user_cpu_seconds"]+receipt["system_cpu_seconds"],
                  "worker_wait4_cpu_identity", label)
            check(receipt["total_cpu_seconds"] >= d["worker_cpu_seconds"],
                  "worker_cpu_encloses_inner_function", label)
            check(len(d["world_tapes"]) == 128 and set(d["arms"]) == all_arms,
                  "worker_world_and_arm_coverage", label)
            for name, item in d["arms"].items():
                check(len(item["episodes"]) == 128, "all_13_arm_attempt_counts", label+":"+name)
                check(item["model_identity"] == models[seed][name].identity,
                      "arm_frozen_model_identity", label+":"+name)
                close(item["cpu_seconds"], sum(e["cpu_seconds"] for e in item["episodes"]),
                      "arm_all_attempt_cpu_sum", label+":"+name, 1e-10)
                for timing in ("preparation_cpu", "checkpoint_io_cpu", "checkpoint_io_wall"):
                    check(math.isfinite(item[timing]) and item[timing] >= 0,
                          "arm_timing_nonnegative", label+":"+name)
            journal_path = run / "progress" / f"{label}.jsonl"
            regenerated = hashlib.sha256()
            journal_bytes = 0
            with journal_path.open("rb") as journal:
                for index, tape in enumerate(d["world_tapes"]):
                    validate_tape(tape, seed, domain, index)
                    check(d["arms"]["D"]["episodes"][index]["queries"] ==
                          d["arms"]["hmm_same_matrix"]["episodes"][index]["queries"],
                          "same_matrix_HMM_complete_query_trace", label+f":{index}")
                    for name, item in d["arms"].items():
                        validate_episode(item["episodes"][index], tape, models[seed][name], name, seed, index)
                    expected = (canonical(dict(index=index, world=tape,
                        arms={name:item["episodes"][index] for name,item in d["arms"].items()}))+"\n").encode()
                    actual = journal.readline()
                    check(actual == expected, "progress_line_byte_identity", label+f":{index}")
                    regenerated.update(expected); journal_bytes += len(expected)
                check(journal.read() == b"", "progress_no_extra_records", label)
            disk_digest = sha(journal_path)
            check(regenerated.hexdigest() == disk_digest == d["progress_journal_sha256"],
                  "progress_reconstructed_hash_identity", label)
            progress_proofs[label] = dict(lines=128, bytes=journal_bytes,
                sha256=disk_digest, reconstructed_sha256=regenerated.hexdigest(),
                source_confirmation=path.name, source_confirmation_sha256=result_hashes[path.name])
            for name, item in d["arms"].items():
                first = item["episodes"][0]
                cpfile = run / "checkpoints" / f"{label}_{name}.json"
                if first["status"] == "completed":
                    check(cpfile.exists() and read(cpfile) == first["states"][-1],
                          "disk_checkpoint_matches_archived_prefix", label+":"+name)
            failures_here = sum(e["status"]=="invalid_support" for e in d["arms"]["mean_value"]["episodes"])
            by_worker.append(dict(seed=seed,domain=domain,worlds=128,complete_valid_arm_episodes=128*12,
                                  mean_attempts=128,mean_completed=128-failures_here,
                                  mean_invalid_support=failures_here,
                                  first_claim=claim["opened_at"],completed_at=d["completed_at"],
                                  worker_cpu_seconds=receipt["total_cpu_seconds"]))
            print("Audited", label, "mean_invalid_support", failures_here, "running_mismatches", count_failures, flush=True)

        check(seen_jobs == set(expected_jobs), "all_registered_seed_domain_pairs")
        close(receipts_cpu, summary["child_cpu_seconds"], "all_worker_cpu_summary", atol=1e-9)
        check(len(unique_worlds) == 2048 and valid_query_count == 147456,
              "full_new_confirmation_cardinality")
        check_sources()
        previous_summary = read(BASE / "run_01/supervisor/confirm_summary.json")
        result = dict(schema="hcsn-r15-independent-execution-audit-v1",
            passed=count_failures==0, mismatch_count=count_failures, first_mismatches=failures,
            audited_at=datetime.now(timezone.utc).isoformat(),
            original_confirmation_performance_used=False,
            effect_estimates_or_p_values_recomputed=False,
            evidence_scope="Supplemental namespace4 raw traces; original run only frozen training/model-reference identities and supervisor cost metadata",
            identities=dict(original_source_commit=spec["original_source_commit"],
                original_model_freeze_commit=spec["original_model_freeze_commit"],
                supplement_commit=pub["supplement_commit"],
                original_source_manifest_sha256=sha(BASE/"SOURCE_MANIFEST.json"),
                supplement_manifest_sha256=sha(BASE/"SUPPLEMENT_MANIFEST.json"),
                original_freeze_sha256=sha(BASE/"run_01/FREEZE.json"),
                supplemental_freeze_sha256=sha(run/"FREEZE.json"),
                confirmation_archive_sha256=result_hashes),
            chronology=dict(publication_readback=pub["verified_at"],launch=launch["opened_at"],
                first_claim=min(x["first_claim"] for x in by_worker),
                last_result_completion=max(x["completed_at"] for x in by_worker)),
            coverage=dict(workers=16,worlds=len(unique_worlds),valid_arms=12,
                valid_arm_episodes=16*128*12,valid_arm_queries=valid_query_count,
                all_arm_attempts=16*128*13,completed_and_prefix_queries_checked=raw_query_count,
                observation_tokens_checked=observed_token_count,
                query_checkpoint_hashes_recomputed=checkpoint_query_count,
                same_HMM_complete_episode_trace_pairs=counts.get("same_matrix_HMM_complete_query_trace",0),
                mean_attempts=2048,mean_invalid_support=len(mean_failures),
                actions_checked=action_counts,changed_public_writes=writes_changed,
                unique_world_query_targets_changed_by_right_limit=left_sensitive_targets,
                unique_actual_observations_changed_by_right_limit=len(unique_left_sensitive_observations)),
            workers=by_worker,mean_support_failures=mean_failures,
            mean_failure_interpretation="Only this two-neighbor phase-index mean projection; no survivor-only performance estimate or claim about all point-state models",
            checks=counts,maximum_numeric_absolute_errors=max_errors,
            progress_archive_equivalence=dict(passed=counts.get("progress_line_byte_identity",0)==2048 and
                not any(f["check"].startswith("progress") for f in failures),
                complete_lines=2048,total_bytes=sum(v["bytes"] for v in progress_proofs.values()),
                canonical_format="json.dumps(dict(index=i,world=world_tapes[i],arms={name:arm['episodes'][i] for name,arm in arms.items()}),sort_keys=True,separators=(',',':'),allow_nan=False)+'\\n', UTF-8",
                per_worker=progress_proofs,
                archive_conclusion="Every local progress byte can be regenerated from complete confirmation archives; local progress remains preserved"),
            resource_accounting=dict(supplemental_confirmation_child_cpu_seconds=summary["child_cpu_seconds"],
                supplemental_supervisor_cpu_seconds=summary["supervisor_cpu_seconds"],
                original_confirmation_child_cpu_seconds=previous_summary["child_cpu_seconds"],
                original_confirmation_failures=len(previous_summary["failed"]),
                original_confirmation_receipts=previous_summary["receipts"],
                interpretation="Independent audit costs are separate research expense; old confirmation performance is excluded, its failed/successful process cost retained"),
            independent_recomputation=dict(targets="Own left-bisect of scorer-owned saved paths; no Episode.target call",
                tokens="Own emission table and keyed blake2b draw; no Episode.observe call",
                state="Own four-address WRITE/advance/project/observe/checkpoint replay using SciPy expm on frozen model matrices; no BeliefMemory/run_episode/Planner calls",
                memoryless="Declared memoryless Q reconstructed with frozen helper; not an independent continuous financial solver",
                actions="Checks actual selected actions, duration, costs, tokens and causal submission; does not re-prove controller optimality or Python process security",
                world_paths="Fingerprint, phase-preserving writes and generator-edge support checked; not an independent statistical test of latent holding-time sampling"),
            audit_inner_cpu_seconds=time.process_time()-started,
            audit_inner_wall_seconds=time.perf_counter()-wall)
        with OUT.open("x") as f:
            json.dump(result,f,sort_keys=True,indent=2,allow_nan=False)
            f.write("\n");f.flush();os.fsync(f.fileno())
        sys.stdout.flush()
        os._exit(0)
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(2)
_, status, usage = os.wait4(pid,0)
exit_code = os.waitstatus_to_exitcode(status)
if exit_code or not OUT.exists():
    print(json.dumps(dict(audit_process_failed=True,exit_code=exit_code,
        user_cpu_seconds=usage.ru_utime,system_cpu_seconds=usage.ru_stime)))
    sys.exit(exit_code or 3)
result=json.loads(OUT.read_text())
result["audit_process_receipt"]=dict(exit_code=exit_code,user_cpu_seconds=usage.ru_utime,
    system_cpu_seconds=usage.ru_stime,total_cpu_seconds=usage.ru_utime+usage.ru_stime,
    peak_rss_kib=usage.ru_maxrss,
    scope="Forked audit child including scientific-library imports, raw-file reads, all checks and first JSON write; excludes outer interpreter startup and final receipt/Markdown write")
result["audit_parent_cpu_before_final_writes_seconds"]=time.process_time()-outer_start
with OUT.open("w") as f:
    json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write("\n");f.flush();os.fsync(f.fileno())
print(json.dumps(dict(passed=result["passed"],mismatch_count=result["mismatch_count"],
    coverage=result["coverage"],first_mismatches=result["first_mismatches"],
    progress_bytes=result["progress_archive_equivalence"]["total_bytes"],
    audit_cpu_seconds=result["audit_process_receipt"]["total_cpu_seconds"])),flush=True)
