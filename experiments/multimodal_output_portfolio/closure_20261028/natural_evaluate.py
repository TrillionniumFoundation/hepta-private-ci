"""Physical evaluation and source-cluster inference for the frozen natural study."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from ..unified_20261028.profile import aggregate, digest
from .control_actor import MomentActor
from .natural_episode import save
from .natural_train import load_checkpoint


def source_summary(rows, profile):
    rows = list(rows)
    if not rows or any(row["profile_sha256"] != profile.digest for row in rows):
        raise ValueError("A complete single-profile evaluation cohort is required")
    sources, contexts, owners = defaultdict(list), defaultdict(list), {}
    for row in rows:
        source, context = row["source_id"], row["context_id"]
        if context in owners and owners[context] != source:
            raise ValueError("Context IDs cannot cross original-source clusters")
        owners[context] = source
        sources[source].append(row)
        contexts[context].append(row["net_return"])
    context_counts = {source: len({row["context_id"] for row in items}) for source, items in sources.items()}
    weights = {context: 1/(len(sources)*context_counts[owners[context]]) for context in contexts}
    policies={row["complete_policy_sha256"] for row in rows}
    if len(policies)!=1:raise ValueError("One arm cannot pool different complete policy identities")
    report = aggregate(profile, contexts, context_weights=weights)
    report["complete_policy_sha256"]=next(iter(policies))
    def mean(extract):
        return float(np.mean([np.mean([extract(row) for row in items]) for items in sources.values()]))
    report.update(original_video_sources=len(sources), actual_episodes=len(rows),
                  actual_cpu_seconds=sum(row["cpu_seconds"] for row in rows),
                  actual_emissions=sum(len(row["emissions"]) for row in rows),
                  actual_native_kernels=sum(row["native_execution"]["measurements"]["actual_original_kernel_executions"] for row in rows),
                  source_mean_cpu_seconds=mean(lambda row: row["cpu_seconds"]),
                  source_mean_complete_cost=mean(lambda row: sum(c["amount"] for c in row["complete_costs"])),
                  source_mean_gross_utility=mean(lambda row: row["outcome"]["delivered_utility"]),
                  source_mean_joint_reconstruction=mean(lambda row: row["terminal_observer"].get("joint_reconstruction", 0.)),
                  source_mean_joint_semantic_correctness=mean(lambda row: float(row["terminal_observer"].get("semantic", {}).get("joint_caption_action_sound", False))),
                  failed_terminal_episodes=sum(row["terminal_kind"] == "failed" for row in rows),
                  actual_retries=sum(row["executed_action"] == "swap" for row in rows),
                  cpu_admission_threshold_exceeded=sum(row["cpu_admission_threshold_exceeded"] for row in rows),
                  training_seeds_pooled_as_environment_draws=False,
                  future_moment_certificate=False)
    report["source_mean_reconstruction_quality"] = {
        kind: mean(lambda row: row["terminal_observer"].get("reconstruction", {}).get("qualities", {}).get(kind, 0.))
        for kind in ("text", "image", "audio", "video")}
    return report


def _source_vectors(rows, gamma):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_id"]].append(row)
    return {source: {"moment": float(np.mean([math.exp(-gamma*r["net_return"]) for r in items])),
                     "reconstruction": float(np.mean([r["terminal_observer"].get("joint_reconstruction", 0.) for r in items]))}
            for source, items in grouped.items()}


def paired_comparison(left, right, profile, *, bootstrap=4096, seed=291031):
    if any(row["profile_sha256"] != profile.digest for row in list(left)+list(right)):
        raise ValueError("Paired comparison requires actual executions of the evaluation profile")
    if profile.gamma != 2.:
        raise ValueError("Registered qualification comparisons use the common gamma=2 profile")
    a, b = _source_vectors(left, profile.gamma), _source_vectors(right, profile.gamma)
    if set(a) != set(b):
        raise ValueError("Paired comparison needs the identical original-source cohort")
    names = sorted(a)
    am, bm = np.asarray([a[k]["moment"] for k in names]), np.asarray([b[k]["moment"] for k in names])
    ar, br = np.asarray([a[k]["reconstruction"] for k in names]), np.asarray([b[k]["reconstruction"] for k in names])
    indices = np.random.default_rng(seed).integers(0, len(names), (bootstrap, len(names)))
    differences = (-np.log(am[indices].mean(1)) + np.log(bm[indices].mean(1))) / profile.gamma
    reconstruction = (ar[indices]-br[indices]).mean(1)
    interval = np.quantile(differences, [.025,.975]).tolist()
    retention = np.quantile(reconstruction, [.025,.975]).tolist()
    return {"source_count": len(names), "ce_difference": float((-np.log(am.mean())+np.log(bm.mean()))/profile.gamma),
            "paired_source_bootstrap_interval_95": interval,
            "reconstruction_difference": float((ar-br).mean()),
            "paired_source_reconstruction_interval_95": retention,
            "empirical_superiority_lower_above_zero": interval[0] > 0,
            "reconstruction_noninferiority_margin_0_01": retention[0] >= -.01,
            "bootstrap_resamples": bootstrap, "bootstrap_seed": seed,
            "inference_scope": "original-video exchangeability assumption; no participant independence or strict future NDU tail certificate"}


def selected_policy_calibration(rows, profile):
    grouped = defaultdict(list)
    complete_policies={row["complete_policy_sha256"] for row in rows}
    if len(complete_policies)!=1:
        raise ValueError("Selected-policy calibration cannot pool different generator/actor/observer laws")
    for row in rows:
        if row["profile_sha256"] != profile.digest:
            raise ValueError("Selected-policy calibration profile mismatch")
        grouped[row["source_id"]].append(row)
    if len(grouped) != 64 or any(len(items) != 2 for items in grouped.values()):
        raise ValueError("Exact frozen64-source two-draw selected-policy calibration required")
    actual, predicted = [], []
    for source in sorted(grouped):
        items = grouped[source]
        actual.append(np.mean([math.exp(-profile.gamma*r["net_return"]) for r in items]))
        predicted.append(np.mean([r["decision"]["predicted_complete_moments"][r["selected_action"]] for r in items]))
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    ce_actual, ce_predicted = -np.log(actual.mean())/profile.gamma, -np.log(predicted.mean())/profile.gamma
    indices = np.random.default_rng(291031).integers(0,64,(4096,64))
    differences = (-np.log(predicted[indices].mean(1))+np.log(actual[indices].mean(1)))/profile.gamma
    return {"schema": "hepta.closure.selected-policy-calibration.v1", "profile_sha256": profile.digest,
            "source_count": 64, "actual_episodes": len(rows),
            "complete_policy_sha256":next(iter(complete_policies)),
            "source_uniform_actual_moment": float(actual.mean()), "source_uniform_predicted_moment": float(predicted.mean()),
            "actual_population_ce": float(ce_actual), "predicted_population_ce": float(ce_predicted),
            "predicted_minus_actual_ce": float(ce_predicted-ce_actual),
            "source_bootstrap_bias_interval_95": np.quantile(differences,[.025,.975]).tolist(),
            "passed_descriptive_bias_point_gate": abs(float(ce_predicted-ce_actual)) <= .05,
            "complete_actual_actor_and_CPU_cost_inside_exponential": True,
            "exp_of_conditional_mean_return_used": False,
            "strict_future_moment_certificate": False,
            "reason_no_certificate": "complete physical CPU has no enforced future upper bound or proved exponential-tail envelope",
            "policy_or_checkpoint_changes_after_this_calibration_permitted": False}


def evaluate_grid(*, runner, configurations, source_rows, draws, phase, output, seed):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    models, states, actors = {}, {}, {}
    for arm, config in configurations.items():
        models[arm], states[arm] = load_checkpoint(config["checkpoint"])
        models[arm].eval().requires_grad_(True)
        actors[arm] = MomentActor.from_dict(json.loads(Path(config["actor"]).read_text())) if config.get("actor") else None
    namespace = hashlib.sha256((str(output.resolve())+runner.profile.digest).encode()).hexdigest()[:16]
    rows = {arm: [] for arm in configurations}
    schedule = []
    # Same context/seed across actual arms gives a paired comparison, not extra
    # independent evidence. Every arm still physically runs and pays its cost.
    order_rng = np.random.default_rng(seed+7)
    for source_index, (directory, event) in enumerate(source_rows):
        order = list(configurations);order_rng.shuffle(order)
        for arm in order:
            for draw in range(draws):
                actual_seed = seed+source_index*101+draw
                case = f"{namespace}-{phase}-{source_index:03d}-{draw}-{arm}"
                config = configurations[arm]
                logp, _, receipt = runner.complete(model=models[arm], checkpoint=config["checkpoint"],
                    event_directory=directory, seed=actual_seed, route=config["route"], actor=actors[arm],
                    output=output, case=case, forced_action=config.get("forced_action"))
                del logp
                receipt.update(arm=arm, phase=phase, original_event_id=event["event_id"],
                               current_parameter_sha256=states[arm]["parameter_sha256"],
                               trained_under_profile_sha256=config.get("trained_under_profile_sha256"),
                               evaluation_profile_sha256=runner.profile.digest,
                               physical_outputs_retained=True)
                save(output/case/"EPISODE.json",receipt)
                rows[arm].append(receipt)
                schedule.append({"case":case,"arm":arm,"source_id":receipt["source_id"],"draw":draw,"seed":actual_seed})
        if (source_index+1)%8==0:
            print(json.dumps({"phase":phase,"completed_sources":source_index+1,"sources":len(source_rows),"actual_episodes":len(schedule)}),flush=True)
    summaries = {arm: source_summary(items, runner.profile) for arm, items in rows.items()}
    save(output/"SCHEDULE.json",schedule)
    save(output/"SUMMARY.json",{"schema":"hepta.closure.natural-grid-result.v1","phase":phase,
         "profile_sha256":runner.profile.digest,"configurations":configurations,"arms":summaries,
         "schedule_sha256":digest(schedule),"all_actual_media_retained":True})
    return rows, summaries
