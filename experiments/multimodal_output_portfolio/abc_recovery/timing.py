"""Serial resident costs on the complete prospectively registered timing census.

Run only after training/collection has stopped. The caller loads and caches all
models/heads and separately records that load cost and enclosing process cost.
Per-request clocks belong to resident_episode; offline scoring and row writes
are outside those clocks but inside this benchmark's process accounting.
"""

from collections import Counter
import itertools
import json
import os
from pathlib import Path
import random
import time
import traceback

import numpy as np
import torch

from ..v6.data import Observation, Target
from ..v6.neural import parameter_hash
from ..v6.observer import METRIC_DIGEST, observe_tensors
from ..v7.data import VIEWS, make_batch
from ..v7.snapshot import Snapshot
from ..v7.sources import digest
from .base_recovery import file_sha, write_json
from .control import Feedback, PLANS, PROFILES
from .episodes import resident_episode
from .route import PlanCritic
from .statistics import cost_summary, crossed_bootstrap
from .trees import _source_identity, stable_seed


CORE = ("fixed", "tuned_static", "feedback")
EXTRA = ("risk_neutral_feedback", "allocation_only_feedback", "draft_masked_feedback",
         "modality_local_feedback", "one_shot_route", "independent_random_stream_MPC",
         "semantic_couple_fixed", "shared_state_clamp_semantic_couple", "encoder_initial_only_fixed")
TIMING_VIEWS = ("clean", "noise", "conflict_untrusted")
ARMS = ("sft_continuation", "output_mean", "output_ndu")
SEEDS = (17, 29, 43, 59, 71)
VIEW_PROFILES = {"registered_three": TIMING_VIEWS, "supplementary_all": VIEWS}


def _jobs(seeds, arms, cases, views, scenarios, rounds):
    """Pure schedule helper; reduced arguments are for synthetic tests only."""
    jobs = []
    for seed, arm in itertools.product(seeds, arms):
        policies = CORE + EXTRA if arm == "output_ndu" else CORE
        for policy, case, view, scenario, timing_round in itertools.product(policies, cases, views, range(scenarios), range(rounds)):
            jobs.append(dict(zip(("seed", "arm", "policy", "case", "view", "scenario", "round"),
                                 (seed, arm, policy, case, view, scenario, timing_round))))
    random.Random(stable_seed("timing-order")).shuffle(jobs)
    return jobs


def _prepare_inputs(corpus, views):
    # Do not generate a smaller batch: make_batch samples batch-shaped noise.
    return {view: make_batch(corpus, "development", 128,
                            stable_seed("observation", "development", 608), view=view, offset=608)
            for view in views}


def _amendment_pins(view_profile, protocol):
    paths = [Path(__file__).with_name("protocol-amendment-001.json")]
    supplementary = Path(__file__).with_name("protocol-amendment-002.json")
    if view_profile == "supplementary_all":
        amendment = json.loads(supplementary.read_text())
        expected = {"view_profile": "supplementary_all", "views": list(VIEWS), "source_pair_start": 608,
                    "source_pairs": 8, "training_seeds": list(SEEDS), "scenarios": 2, "rounds": 2,
                    "conditions_per_seed": 18, "jobs": 23040, "primary_three_view_census_retained": True,
                    "additional_independent_sources": 0, "separate_output_directory": True}
        if (amendment.get("base_protocol_sha256") != file_sha(Path(__file__).with_name("protocol.json"))
                or any(amendment.get("timing_extension", {}).get(k) != v for k, v in expected.items())
                or tuple(protocol["views"]) != VIEWS):
            raise ValueError("Supplementary timing requires the frozen amendment-002 census")
    if supplementary.is_file():
        paths.append(supplementary)
    return {path.name: file_sha(path) for path in paths}


def _identities(models, bundles, observers):
    def head(model):
        attributes = {key: getattr(model, key) for key in
                      ("input_dim", "gamma", "remaining", "seed", "hidden_dim", "action_cost") if hasattr(model, key)}
        return {"parameter_sha256": parameter_hash(model), "config": attributes,
                "training": model.training, "requires_grad": any(p.requires_grad for p in model.parameters())}
    def feedback(policy):
        return {"name": policy.name, "profile": policy.profile,
                "heads": [head(policy.critic.one_step_model), head(policy.critic.two_step_model)]}
    result = {"models": {}, "policies": {}, "observers": {name: head(model) for name, model in observers.items()}}
    for key in sorted(models):
        label, snapshot, bundle = f"{key[0]}/{key[1]}", models[key], bundles[key]
        result["models"][label] = {"snapshot_sha256": snapshot.fingerprint,
                                  "live_parameter_sha256": parameter_hash(snapshot._model),
                                  "configuration": snapshot._model.config, "training": snapshot._model.training}
        result["policies"][label] = digest({"feedback": feedback(bundle["feedback"]),
            "profiles": {name: feedback(policy) for name, policy in bundle["profiles"].items()},
            "route": None if bundle["route"] is None else head(bundle["route"]),
            "static_plan": list(bundle["static"]["plan"])})
    # Detach mutable config dictionaries from live objects before later checks.
    return json.loads(json.dumps(result, sort_keys=True, allow_nan=False))


def _validate(models, bundles, observers, protocol):
    evaluation = protocol["roles"]["evaluation"]
    if (evaluation != {"role": "development", "pair_start": 608, "pair_count": 128}
            or tuple(protocol["training_seeds"]) != SEEDS or tuple(protocol["training"]["arms"]) != ARMS
            or protocol["threads"] != 2 or protocol["statistics"]["bootstrap_replicates"] != 4000
            or protocol["utility"]["risk_aversion"] != 2. or protocol["utility"]["continuation_action_penalty"] != .002
            or protocol["continuation_budget"] != 2 or tuple(protocol["views"]) != VIEWS):
        raise ValueError("Timing requires the unchanged frozen evaluation/seed/arm/thread census")
    expected = set(itertools.product(SEEDS, ARMS))
    if set(models) != expected or set(bundles) != expected or set(observers) != {"primary", "secondary"}:
        raise ValueError("The complete cached model, policy and dual-observer census is required")
    modules = list(observers.values())
    for key, snapshot in models.items():
        if type(snapshot) is not Snapshot:
            raise TypeError("Resident models must be registered Snapshots")
        snapshot.verify_integrity()
        modules.append(snapshot._model)
        bundle = bundles[key]
        policies = [bundle["feedback"], *bundle["profiles"].values()]
        if (bundle["feedback"].name != "feedback" or tuple(bundle["static"]["plan"]) not in PLANS
                or set(bundle["profiles"]) - set(PROFILES)
                or any(policy.name != name for name, policy in bundle["profiles"].items())):
            raise ValueError("Invalid frozen feedback/static profile")
        if key[1] == "output_ndu" and (not set(PROFILES).difference({"feedback"}).issubset(bundle["profiles"])
                                      or not isinstance(bundle["route"], PlanCritic)):
            raise ValueError("NDU timing requires every registered ablation and route")
        for policy in policies:
            heads = (policy.critic.one_step_model, policy.critic.two_step_model)
            if (not isinstance(policy, Feedback) or policy.profile != PROFILES[policy.name]
                    or any(h.gamma != policy.profile["gamma"] or h.input_dim != 673 for h in heads)):
                raise ValueError("Unregistered feedback profile")
            modules.extend(heads)
        if bundle["route"] is not None:
            modules.append(bundle["route"])
    if any(m.training or any(p.requires_grad or p.device.type != "cpu" for p in m.parameters()) for m in modules):
        raise ValueError("All resident models, heads and observers must be frozen CPU eval modules")


@torch.inference_mode()
def _resident_job(job, model, bundle, observation, target, observers, archive_path):
    """A real failing invocation remains a row; scoring failure is unobserved."""
    if len(observation.pixels) != 1 or len(target.pixels) != 1:
        raise ValueError("Resident timing requires batch one")
    key = (job["seed"], job["case"], job["view"], job["scenario"])
    policy = bundle["profiles"].get(job["policy"], bundle["feedback"])
    row = {**job, "actual_stream_key": key, "planning_seed": stable_seed("planning", job["seed"]),
           "archive": str(archive_path), "raw": None, "path": None, "work": {},
           "work_complete": False, "planner_counters_are_subsets_not_additional_work": True}
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        episode = resident_episode(model, observation, policy_name=job["policy"], actual_stream_key=key,
            archive_path=archive_path, feedback=policy, route=bundle["route"],
            static_plan=bundle["static"]["plan"], planning_seed=row["planning_seed"])
    except Exception as error:
        row.update({"wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
                    "status": "generation_failed", "exception": type(error).__name__,
                    "error": str(error), "traceback": traceback.format_exc(), "required_output_complete": False})
        ledger = getattr(error, "ledger", ())
        partial = Counter()
        for entry in ledger:
            partial.update(entry.get("work", {}))
        row.update({"work": dict(partial), "failure_ledger": ledger, "score_origin": "registered_generation_failure_penalty",
                    "observer_scores": {name: {"joint_loss": 1., "utility": -1., "joint_fact_correct": False,
                                               "required_output_complete": False} for name in observers},
                    "offline_scoring_wall_ns": 0, "offline_scoring_cpu_ns": 0})
        return row
    row.update({key: episode[key] for key in ("wall_ns", "cpu_ns", "path", "work", "raw")})
    row.update({"status": "completed", "work_complete": True,
                "required_output_complete": bool(episode["raw"][0]["required_output_complete"]),
                "score_origin": "decoded_actual_output_offline_observer", "observer_scores": {}, "scoring_errors": {}})
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    for name, observer in observers.items():
        try:
            score = observe_tensors(observer, episode["pixels"], episode["captions"], target.pixels, target.labels)[0]
            score["joint_fact_correct"] = bool(score["caption_valid"] and all(score[k] == 0 for k in
                ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
            score["required_output_complete"] = row["required_output_complete"]
            if not all(np.isfinite(score[k]) for k in ("joint_loss", "utility")):
                raise ValueError("Non-finite observer outcome")
            row["observer_scores"][name] = score
        except Exception as error:
            row["status"] = "offline_scoring_failed"
            row["observer_scores"][name] = None
            row["scoring_errors"][name] = {"exception": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()}
    row.update({"offline_scoring_wall_ns": time.perf_counter_ns() - wall,
                "offline_scoring_cpu_ns": time.process_time_ns() - cpu})
    return row


def _summaries(rows, views):
    shape = (len(SEEDS), 8, len(views), 2, 2)
    conditions = [(arm, policy) for arm in ARMS for policy in (CORE + EXTRA if arm == "output_ndu" else CORE)]
    cubes = {condition: {name: np.full(shape, np.nan) for name in ("wall_ms", "cpu_ms")} for condition in conditions}
    seen, replay, repeated_differences = set(), {}, []
    counts = {condition: Counter() for condition in conditions}
    completion = Counter()
    quality = {condition: {name: [] for name in ("primary", "secondary")} for condition in conditions}
    for row in rows:
        condition = row["arm"], row["policy"]
        index = SEEDS.index(row["seed"]), row["case"] - 608, views.index(row["view"]), row["scenario"], row["round"]
        identity = condition, index
        if identity in seen or any(not 0 <= i < n for i, n in zip(index, shape)):
            raise ValueError("Duplicate or out-of-census timing row")
        seen.add(identity)
        for name in ("wall", "cpu"):
            cubes[condition][name + "_ms"][index] = row[name + "_ns"] / 1e6
        counts[condition][row["status"]] += 1
        completion[condition] += bool(row["required_output_complete"])
        for name in quality[condition]:
            quality[condition][name].append(row["observer_scores"][name])
        if row["raw"] is not None:
            replay_key = (condition, *index[:-1])
            actual = tuple(row["raw"][0][k] for k in ("image_sha256", "text_sha256"))
            if replay_key in replay and replay[replay_key] != actual:
                repeated_differences.append({"arm_policy": condition, "seed_source_view_scenario_indices": index[:-1]})
            replay[replay_key] = actual
    if len(seen) != len(conditions) * int(np.prod(shape)) or any(not np.isfinite(a).all() for values in cubes.values() for a in values.values()):
        raise ValueError("Incomplete finite balanced timing census")
    plan = crossed_bootstrap(len(SEEDS), 8, replicates=4000)
    report, contrasts = {}, {}
    for condition in conditions:
        label = "/".join(condition)
        report[label] = {"cost": {name: cost_summary(array, unit="ms", bootstrap=plan) for name, array in cubes[condition].items()},
                         "statuses": dict(counts[condition]), "physical_required_output_complete_rate": completion[condition] / sum(counts[condition].values()),
                         "quality_including_explicit_generation_failure_penalties": {}}
        for name, scores in quality[condition].items():
            missing = sum(score is None for score in scores)
            report[label]["quality_including_explicit_generation_failure_penalties"][name] = {
                "unobserved": missing, "means": None if missing else {metric: float(np.mean([s[metric] for s in scores]))
                for metric in ("utility", "joint_loss", "joint_fact_correct", "required_output_complete")}}
        reference = (condition[0], "fixed")
        if condition[1] != "fixed":
            contrasts[label + " minus " + "/".join(reference)] = {name: cost_summary(array, reference=cubes[reference][name], unit="ms", bootstrap=plan)
                for name, array in cubes[condition].items()}
    contrasts["output_ndu/fixed minus output_mean/fixed"] = {name: cost_summary(array, reference=cubes[("output_mean", "fixed")][name], unit="ms", bootstrap=plan)
        for name, array in cubes[("output_ndu", "fixed")].items()}
    return report, contrasts, repeated_differences


@torch.inference_mode()
def benchmark_resident(models, bundles, corpus_dev, observers, outdir, protocol, *, view_profile="registered_three"):
    """Run the frozen 8640-job primary or 23040-job supplementary census serially.

    No warm-up, first-round or outlier deletion. Timing rounds repeat the same
    draws and remain paired within eight independent source groups and five
    trained seeds. Thread count is fixed to two; caller ensures no concurrent
    training/collection. Loaded-resident and enclosing-process costs are separate.
    Supplementary all-view timing needs amendment-002 and a distinct output
    directory. It reuses the same eight sources and overlapping random streams;
    it cannot be pooled with the primary run as additional independent evidence.
    """
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if view_profile not in VIEW_PROFILES:
        raise ValueError("Unknown frozen timing view profile")
    views = VIEW_PROFILES[view_profile]
    _validate(models, bundles, observers, protocol)
    amendments = _amendment_pins(view_profile, protocol)
    torch.set_num_threads(2)
    identities = _identities(models, bundles, observers)
    source = _source_identity(corpus_dev, "development", 608, 128)
    inputs = _prepare_inputs(corpus_dev, views)
    area = Path(__file__).resolve().parent.parent
    pins = {str(p.relative_to(area)): file_sha(p) for folder, names in (
        ("abc_recovery", ("timing", "episodes", "runtime", "emission", "media", "planning", "route", "critic", "control", "statistics", "trees")),
        ("v6", ("data", "neural", "observer")), ("v7", ("data", "model", "snapshot", "sources"))) for p in (area / folder / (n + ".py") for n in names)}
    jobs = _jobs(SEEDS, ARMS, range(608, 616), views, 2, 2)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    registration = {"schema": "hepta.abc.resident-timing-registration.v1", "protocol_sha256": digest(protocol),
        "protocol_amendment_file_sha256": amendments, "view_profile": view_profile, "timing_views": list(views),
        "is_supplementary": view_profile == "supplementary_all", "additional_independent_source_groups": 0,
        "primary_and_supplement_must_not_be_pooled_as_independent_runs": True,
        "identities": identities, "source_identity": source, "code_sha256": pins, "metric_sha256": METRIC_DIGEST,
        "jobs": jobs, "job_count": len(jobs), "order_sha256": digest(jobs), "order_seed": stable_seed("timing-order"),
        "rng_recipe": {"observation": "make_batch(development,128,stable_seed('observation','development',608),view,offset=608), then first8",
            "actual": "stable_seed('actual-resident',training_seed,global_case,view,scenario,committed_nonstop_path)",
            "excluded_from_actual_key": ["arm", "policy", "round"], "planning_seed": "stable_seed('planning',training_seed)",
            "planning_innovations": "independent planning namespace + public_digest + planning_seed + action + sample",
            "order": "one python.Random(stable_seed('timing-order')).shuffle over the full job list"},
        "source_groups": 8, "training_seeds": 5, "scenarios_per_source_view": 2, "paired_replay_rounds": 2,
        "all_models_heads_already_resident": True, "loading_cost_included": False, "caller_must_report_loading_cost": True, "threads": 2,
        "parallel_execution": False, "caller_must_stop_training_and_collection": True, "outlier_deletion": False,
        "generation_failure_policy": {"joint_loss": 1., "utility": -1., "joint_fact_correct": False,
                                      "required_output_complete": False, "explicit_penalty_not_observer_measurement": True},
        "offline_scoring_failure_policy": "observer score null/unobserved; preserve completed output; fail evaluation-integrity gate",
        "planner_subset_counters_must_not_be_added_to_raw_totals": True}
    write_json(outdir / "registration.json", registration)
    rows = []
    with (outdir / "rows.jsonl").open("x", encoding="utf-8") as stream:
        for position, job in enumerate(jobs):
            batch, i = inputs[job["view"]], job["case"] - 608
            observation = Observation(*(getattr(batch.observation, name)[i:i + 1] for name in ("pixels", "mask", "text_tokens")))
            target = Target(*(getattr(batch.target, name)[i:i + 1] for name in ("pixels", "text_tokens", "labels")))
            archive = outdir / "media" / f"{position:05d}.zip"
            key = job["seed"], job["arm"]
            row = _resident_job(job, models[key]._model, bundles[key], observation, target, observers, archive)
            row.update({"order_index": position, "source_ids": batch.source_ids[i],
                        "archive": str(archive.relative_to(outdir)), "archive_sha256": file_sha(archive) if archive.is_file() else None})
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            rows.append(row)
    after = _identities(models, bundles, observers)
    integrity_errors = []
    for snapshot in models.values():
        try:
            snapshot.verify_integrity()
        except Exception as error:
            integrity_errors.append(str(error))
    unchanged = (identities == after and not integrity_errors and source == _source_identity(corpus_dev, "development", 608, 128)
                 and pins == {name: file_sha(area / name) for name in pins}
                 and amendments == _amendment_pins(view_profile, protocol))
    conditions, contrasts, replay_errors = _summaries(rows, views)
    failures = Counter(row["status"] for row in rows)
    report = {"schema": "hepta.abc.resident-timing-report.v1", "complete_census": len(rows) == len(jobs),
        "view_profile": view_profile, "timing_views": list(views), "is_supplementary": view_profile == "supplementary_all",
        "additional_independent_source_groups": 0, "primary_and_supplement_must_not_be_pooled_as_independent_runs": True,
        "rows": len(rows), "source_groups": 8, "training_seeds": 5, "statuses": dict(failures),
        "conditions": conditions, "paired_cost_differences": contrasts, "identities_before": identities,
        "identities_after": after, "identities_unchanged": unchanged, "integrity_errors": integrity_errors,
        "identical_round_replay_errors": replay_errors, "evaluation_integrity_gate": unchanged and not replay_errors and not failures["offline_scoring_failed"],
        "generation_failure_scores_are_explicit_penalties_not_observer_measurements": True,
        "offline_scoring_failures_are_unobserved_not_semantic_failures": True,
        "cost_scope": "resident_episode encoder through closed ZIP reopen; prepared public input tensors and loaded models; scoring/metadata outside per-request clock",
        "rounds_are_correlated_replays_not_new_independent_generation_scenarios": True,
        "timing_source_quality_is_not_full_evaluation_quality": True, "training_or_loading_cost_mixed_into_inference": False,
        "planner_counters_are_subsets_not_additional_work": True, "registration_sha256": file_sha(outdir / "registration.json"),
        "rows_sha256": file_sha(outdir / "rows.jsonl"), "offline_scoring_total_wall_ns": sum(r["offline_scoring_wall_ns"] for r in rows),
        "offline_scoring_total_cpu_ns": sum(r["offline_scoring_cpu_ns"] for r in rows),
        "elapsed_total_wall_ns": time.perf_counter_ns() - wall, "elapsed_total_cpu_ns": time.process_time_ns() - cpu,
        "elapsed_scope": "benchmark entry through scoring, row fsync, integrity and analysis; final summary serialization and caller-resident loading belong to enclosing process cost"}
    write_json(outdir / "summary.json", report)
    return report
