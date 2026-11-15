"""Measured pretrained-Encoder/group-reasoning campaign; research only."""

import argparse
import copy
import json
import platform
import time
from collections import Counter
from pathlib import Path

import torch

from execution_meter import WorkLedger, TRANSFORMER_POLICY_SCHEMA
from group_core import Core
from group_critic import fit_critic, row_features
from group_encoder import FrozenTokenEncoder, acquire, digest_json, file_digest
from group_features import FeatureCache
from group_loop import execute_group, parameter_digest
from group_split import assess_split, freeze_split_policy, selection_manifest_sha256
from group_tasks import compose_tasks, delete_evidence, feedback_vector, make_tasks, verify
from group_training import StaticHead, SplitCore, fit_model, matched_static
from native_ndu_bridge import build_replay, run_native_replay
from paired_execution import PHASES
from transformer_work import PROFILE


def packed(snapshots):
    longest, width = max(s.shape[0] for s in snapshots), snapshots[0].shape[1]
    tokens = torch.zeros(len(snapshots), longest, width)
    mask = torch.zeros(len(snapshots), longest, dtype=torch.bool)
    for i, snapshot in enumerate(snapshots):
        n = snapshot.shape[0]
        tokens[i, :n] = torch.tensor(snapshot.tokens)
        mask[i, :n] = torch.tensor(snapshot.mask)
    return tokens, mask


def critic_rows(model, tasks, snapshots, max_steps):
    """Validation labels are reachable here only, never by inference callbacks."""
    rows = []
    with torch.no_grad():
        for task, snapshot in zip(tasks, snapshots):
            tokens, mask = packed([snapshot])
            state, feedback, steps = None, None, []
            for step in range(1, max_steps + 1):
                state, logits = model.step(tokens, state, feedback, mask)
                guess = logits.argmax(1).item()
                checked = verify(task, guess)
                steps.append((row_features(state, logits, step, max_steps), guess == task.target))
                feedback = torch.tensor([feedback_vector(checked.accepted, checked.feedback)])
            for i in range(max_steps - 1):
                rows.append(dict(features=steps[i][0], stop_success=steps[i][1],
                                 continue_success=steps[i + 1][1], source_group=task.source_group))
    return rows


def summarize(rows):
    times = sorted(r["wall_ns"] for r in rows)
    return dict(n=len(rows), correct=sum(r["success"] for r in rows),
                verifier_calls=sum(r["verifier_calls"] for r in rows),
                steps=sum(r["steps"] for r in rows),
                cpu_ns=sum(r["cpu_ns"] for r in rows), wall_ns=sum(times),
                observed_p50_ns=times[len(times) // 2],
                observed_p95_ns=times[min(len(times) - 1, int(.95 * len(times)))],
                tail_quantiles_are_target_host_certification=False,
                statuses=dict(Counter(r["status"] for r in rows)))


def campaign(snapshot_root, output, *, seed=41, train_count=256, heldout_count=96,
             steps=120, native_binary=None):
    if (type(seed) is not int or seed < 0 or type(train_count) is not int
            or not 8 <= train_count <= 4096 or type(heldout_count) is not int
            or not 6 <= heldout_count <= 512 or type(steps) is not int or not 1 <= steps <= 10000):
        raise ValueError("bounded campaign sizes, seed and training steps required")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    tasks = {s: make_tasks(s, train_count if s == "train" else heldout_count,
                           seed=seed) for s in ("train", "validation", "selection", "test")}
    tasks["long"] = make_tasks("test", heldout_count, seed=seed + 1, longer=True)
    tasks["deleted"] = [delete_evidence(t) for t in tasks["test"]]
    short = [t for t in tasks["test"] if t.depth == 2]
    tasks["composition"] = [compose_tasks(a, b) for a in short for b in short
                             if a.family != b.family][:heldout_count]
    if not tasks["composition"]:
        tasks["composition"] = [compose_tasks(tasks["test"][0], tasks["test"][1])]
    groups = [set(t.source_group for t in tasks[s]) for s in ("train", "validation", "selection", "test", "long")]
    if any(a & b for i, a in enumerate(groups) for b in groups[i + 1:]):
        raise ValueError("source group leaked across campaign partitions")
    protocol = dict(schema="hepta.group.campaign-protocol.v1", seed=seed, steps=steps,
        train_count=train_count, heldout_count=heldout_count, max_depth=4,
        objective="independent-evidence-correct-class", train_splits=["train"],
        critic_splits=["validation_fit", "validation_calibration"],
        selection_splits=["selection"], final_splits=["test", "long", "deleted", "composition"],
        source_sha256={p.name: file_digest(p) for p in sorted(Path(__file__).parent.glob("group*.py"))},
        native_binary_sha256=file_digest(native_binary) if native_binary else None,
        source_groups={s: [t.source_group for t in ts] for s, ts in tasks.items()},
        public_cases={s: [dict(case_id=t.task_id, source_group=t.source_group,
                              family=t.family, text=t.text) for t in ts] for s, ts in tasks.items()},
        cost_prices=dict(cpu_second=.001, wall_second=.001, byte_second=1e-13),
        strict_equal_compute=False, matched_steps_do_not_equal_matched_work=True,
        natural_task_or_multimodal_efficacy=False, production_authorized=False)
    # Persist membership and thresholds before fitting or opening selection outcomes.
    (root / "protocol.json").write_text(json.dumps(protocol, sort_keys=True))
    encoder_started = time.perf_counter_ns(), time.process_time_ns()
    encoder = FrozenTokenEncoder(snapshot_root, max_tokens=256)
    cache = FeatureCache("agent:group-campaign", 1, max_entries=sum(map(len, tasks.values())),
                         max_bytes=512 * 1024 * 1024)
    policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE,
        mode="observe", wall_time_ns=1_800_000_000_000, max_process_rss_bytes=None,
        rapl_zone=None, rapl_max_power_watts=None)
    meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**15))
    features = {}
    for split, cases in tasks.items():
        features[split] = []
        for task in cases:
            identity = encoder.identity(task.text, scope=cache.scope, generation=cache.generation)
            with meter.scope("inference", "encoder"):
                feature = cache.get_or_encode(identity, lambda t=task, i=identity: encoder.encode(t.text, i))
            features[split].append(feature)
    encoder_cost = dict(load_and_encode_wall_ns=time.perf_counter_ns() - encoder_started[0],
        load_and_encode_cpu_ns=time.process_time_ns() - encoder_started[1],
        actual_forward_calls=encoder.calls, logical_feature_requests=sum(map(len, tasks.values())),
        cache_canonical_bytes=cache.nbytes, material=encoder.material,
        loading=encoder.loading, exact_tensor_verification=encoder.tensor_verification,
        observation=meter.report(), physical_shared_work_charged_once=True)
    (root / "encoder.json").write_text(json.dumps(encoder_cost, sort_keys=True))
    x, mask = packed(features["train"])
    y = torch.tensor([t.target for t in tasks["train"]])
    route = torch.tensor([int(t.family != "dependency") for t in tasks["train"]])
    models, training = {}, {}
    core = Core(384, 32, 8)
    wide, geometry = matched_static(core, 384)
    def training_feedback(indices, guesses):
        values = []
        for i, guess in zip(indices, guesses):
            checked = verify(tasks["train"][i], guess)
            values.append(feedback_vector(checked.accepted, checked.feedback))
        return torch.tensor(values, dtype=torch.float32)
    for name, model, depth in (("static", StaticHead(384, 8), 1),
                               ("wide", wide, 1), ("core", core, 4)):
        models[name], training[name] = fit_model(model, x, mask, y,
            steps=steps, seed=seed, max_depth=depth, feedback_fn=training_feedback if depth > 1 else None)
    migration_started = time.perf_counter_ns(), time.process_time_ns()
    split = SplitCore(models["core"])
    migration = dict(wall_seconds=(time.perf_counter_ns() - migration_started[0]) / 1e9,
                     cpu_seconds=(time.process_time_ns() - migration_started[1]) / 1e9)
    models["split"], training["split"] = fit_model(split, x, mask, y, steps=steps,
        seed=seed, max_depth=4, route_targets=route, feedback_fn=training_feedback)
    # Fitting continuation values is separate from task-model training and uses
    # source-disjoint fit/calibration halves of validation only.
    critic_started = time.perf_counter_ns(), time.process_time_ns()
    half = heldout_count // 2
    fit = critic_rows(models["core"], tasks["validation"][:half], features["validation"][:half], 4)
    calibration = critic_rows(models["core"], tasks["validation"][half:], features["validation"][half:], 4)
    for rows, split_name in ((fit, "validation_fit"), (calibration, "validation_calibration")):
        for row in rows:
            row["split"] = split_name
    critic = fit_critic(fit, calibration, cutoff_ns=time.time_ns(), steps=80, seed=seed)
    critic_cost = dict(metadata=critic.metadata,
        rollout_and_fit_wall_ns=time.perf_counter_ns() - critic_started[0],
        rollout_and_fit_cpu_ns=time.process_time_ns() - critic_started[1])
    objective = digest_json({"task": "evidence-correct-class-v1"})
    membership = [dict(before_case_id=t.task_id, after_case_id=t.task_id,
                       source_group=t.source_group, cohort="old" if t.old_task else "new")
                  for t in tasks["selection"]]
    split_policy = freeze_split_policy(subject_id="agent:group-reasoning-research",
        parent_candidate_id=parameter_digest(models["core"]),
        candidate_id=parameter_digest(models["split"]), generation=1,
        objective_sha256=objective, selection_manifest_sha256=selection_manifest_sha256(membership),
        prices=protocol["cost_prices"], cpu_seconds_bound=30, wall_seconds_bound=30)
    (root / "split-policy.json").write_text(json.dumps(split_policy, sort_keys=True))
    rows, traces, summaries = [], {}, {}
    arms = (("static", "static"), ("wide", "wide"), ("fixed", "core"),
            ("adaptive", "core"), ("ndu", "core"), ("no_verifier", "core"),
            ("reset_state", "core"), ("split", "split"))
    def select_split():
        selected = {a: {r["case_id"]: r for r in rows if r["cohort"] == "selection" and r["arm"] == a}
                    for a in ("fixed", "split")}
        pairs = []
        for m in membership:
            before, after = (selected[a][m["before_case_id"]] for a in ("fixed", "split"))
            pairs.append({**m, "split": "selection", "objective_sha256": objective,
                **{f"{label}_success": r["success"] for label, r in (("before", before), ("after", after))},
                **{f"{label}_{unit}_seconds": r[unit + "_ns"] / 1e9
                   for label, r in (("before", before), ("after", after)) for unit in ("cpu", "wall")}})
        extra = max(0, training["split"]["parameter_bytes"] - training["core"]["parameter_bytes"])
        overhead = dict(training_cpu_seconds=training["split"]["cpu_ns"] / 1e9,
            training_wall_seconds=training["split"]["wall_ns"] / 1e9,
            migration_cpu_seconds=migration["cpu_seconds"], migration_wall_seconds=migration["wall_seconds"],
            resident_bytes=extra,
            resident_duration_seconds=sum(r["wall_ns"] for r in selected["split"].values()) / 1e9,
            amortization_observed_count=len(pairs))
        decision = assess_split(split_policy, pairs, overhead,
            preregistered_policy_id=split_policy["policy_id"], independent_source_groups_declared=True)
        decision["chosen_model"] = "split" if decision["decision"] == "retain_candidate" else "core"
        decision["selected_at_ns"] = time.time_ns()
        (root / "split-decision-before-test.json").write_text(json.dumps(decision, sort_keys=True))
        return decision, overhead

    for cohort in ("selection", "test", "long", "deleted", "composition"):
        for arm, model_name in arms:
            if cohort == "selection" and arm not in ("fixed", "split"):
                continue
            current = []
            for task, snapshot in zip(tasks[cohort], features[cohort]):
                start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
                result = execute_group(task, models[model_name], snapshot, critic,
                                       mode="fixed" if arm == "split" else arm)
                candidate = result["candidate"]
                prediction = ord(candidate) - 65 if isinstance(candidate, str) and len(candidate) == 1 else -1
                invalid = result["status"] in {"budget_exhausted", "callback_failed", "resource_budget_stop",
                    "ndu_stop:expired_policy", "ndu_stop:continuation_support_violated"}
                work = result["work_observation"]
                row = dict(cohort=cohort, arm=arm, case_id=task.task_id, source_group=task.source_group,
                    family=task.family, old_task=task.old_task, prediction=prediction,
                    candidate_correct=prediction == task.target, valid_execution=not invalid,
                    success=prediction == task.target and not invalid, status=result["status"],
                    steps=result["workspace_steps"],
                    verifier_calls=sum(t["kind"] == "verify" for t in result["trace"]),
                    wall_ns=time.perf_counter_ns() - start_wall,
                    cpu_ns=time.process_time_ns() - start_cpu,
                    search_formula_work=work["phase_flops"]["search"],
                    feature_sha256=snapshot.digest, model_sha256=result["model_sha256"])
                rows.append(row)
                current.append(row)
                if arm not in traces:
                    traces[arm] = result
            summaries[f"{cohort}.{arm}"] = summarize(current)
            print(json.dumps({"cohort": cohort, "arm": arm, **summaries[f"{cohort}.{arm}"]}), flush=True)
        if cohort == "selection":
            split_decision, overhead = select_split()
    native = None
    if native_binary is not None:
        witness = rows[0]
        request = build_replay(objective_sha256=objective, subject_id="agent:group-reasoning-research",
            generation=1, episode_sha256=digest_json(witness), coefficient_sha256=digest_json(protocol["cost_prices"]),
            units_sha256=digest_json("correctness-minus-cpu-wall-byte-seconds-v1"),
            terminal_outcome_sha256=digest_json({"case": witness["case_id"], "success": witness["success"]}),
            observer_sha256=digest_json("programmatic-independent-final-scorer-v1"),
            terminal=int(witness["success"]), events=[dict(event_sha256=digest_json(witness),
            preference_sha256=digest_json(split_policy), instant=-(protocol["cost_prices"]["cpu_second"]
                * witness["cpu_ns"] + protocol["cost_prices"]["wall_second"] * witness["wall_ns"]) / 1e9,
            discount=1.)])
        native = run_native_replay(request, native_binary)
    encoder.verify_files()
    encoder.tensor_verification = __import__("hf_encoder_kernel").verify_loaded_safetensors(
        torch, encoder.model, encoder.root)
    report = dict(schema="hepta.group.campaign-observation.v1", protocol_sha256=digest_json(protocol),
        seed=seed, runtime=dict(python=platform.python_version(), torch=torch.__version__, host=platform.machine()),
        training=training, wide_parameter_match=geometry, critic=critic_cost, summaries=summaries,
        final_evaluation_started_after_selection=True,
        rejected_split_final_rows_are_diagnostics_only=split_decision["decision"] != "retain_candidate",
        split_selection=split_decision, split_overhead=overhead, native_replay=native,
        lifecycle_wall_ns=time.perf_counter_ns() - started_wall,
        lifecycle_cpu_ns=time.process_time_ns() - started_cpu,
        pretrained_encoder_executed=True, supervised_core_trained=True,
        strict_equal_compute=False, future_natural_task_gain_established=False,
        multimodal_generation_executed=False, native_production_owner_integrated=False,
        full_cost_qualification=False, production_authorized=False)
    for name, value in (("observations.json", rows), ("trace-samples.json", traces), ("report.json", report)):
        (root / name).write_text(json.dumps(value, sort_keys=True, allow_nan=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--train-count", type=int, default=256)
    parser.add_argument("--heldout-count", type=int, default=96)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--native-binary")
    args = parser.parse_args()
    if args.acquire:
        acquire(args.snapshot)
    campaign(args.snapshot, args.output, seed=args.seed, train_count=args.train_count,
             heldout_count=args.heldout_count, steps=args.steps, native_binary=args.native_binary)


if __name__ == "__main__":
    main()
