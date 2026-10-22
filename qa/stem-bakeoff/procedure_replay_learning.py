"""Actual Granite forward, private Head SGD, reload, withdrawal and file evaluation."""

from dataclasses import asdict
import gzip
import json
from pathlib import Path
import resource
import time
from unittest.mock import patch

import numpy as np
import torch
from torch.nn import functional as F

from cell_evolution_snapshot import WithdrawalViewV1
from cell_head_training import (HeadCohortV1, HeadTrainingConfigV1, TEMPERATURES,
                                save_head_artifact, train_cell_head)
from feature_bundle import FeatureBundleV1
from native_latent import LightCellHead
from procedure_replay_contracts import canonical, sha
from procedure_replay_data import SPLITS, make_cases
from procedure_replay_evaluation import evaluate_policy, paired_interval
from procedure_replay_owner import ReplayHeadOwner
from procedure_replay_probe import (ROOT, ReplayBM25, replay_labels, require_plan,
                                    write_json, write_lines)
from real_encoder import FrozenRealEncoder


def pooled_bundle(features, sources, identity):
    # Global features are the actual retained Encoder outputs. No token states
    # are invented; the supported Head consumes global_features only.
    missing = torch.ones((len(features), 5), dtype=torch.bool)
    missing[:, 0] = False
    return FeatureBundleV1.from_tensors(global_features=features, identity=identity,
        source_record_digests=tuple(sources), missing_mask=missing)


def encode_queries(cases, plan, snapshot, accepted, target):
    spec = plan["encoder"]
    start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    owner = FrozenRealEncoder(candidate=spec["candidate"], snapshot=snapshot,
        revision=spec["revision"], expected_inventory_sha256=spec["inventory_sha256"],
        operator_accepted_terms=accepted, device="cpu", max_tokens=spec["max_tokens"],
        task=spec["task"], scope_id=spec["scope_id"])
    parts, sources, receipts = [], [], []
    size = spec["batch_size"]
    for offset in range(0, len(cases), size):
        queries = [case.query for case in cases[offset:offset + size]]
        bundle = owner.encode_text([query.text for query in queries],
                                   source_records=[asdict(query) for query in queries])
        parts.append(bundle.read_global())
        sources.extend(bundle.source_record_digests)
        receipts.append({**owner.last_receipt, "query_ids": [query.query_id for query in queries],
                         "original_full_bundle_sha256": bundle.bundle_digest})
        print(json.dumps({"encoded_queries": min(offset + size, len(cases)),
                          "physical_encoder_calls": len(receipts)}), flush=True)
    features = torch.cat(parts).contiguous()
    if features.shape != (len(cases), spec["width"]) or not bool(torch.isfinite(features).all()):
        raise ValueError("actual Encoder output width or values differ")
    with (target / "pooled_features.npz").open("xb") as stream:
        np.savez(stream, pooled=features.numpy())
    manifest = {"feature_identity": asdict(owner.identity), "query_ids": [case.query.query_id for case in cases],
        "source_record_digests": sources, "shape": list(features.shape),
        "feature_bytes_sha256": sha(features.numpy().tobytes()),
        "npz_sha256": sha((target / "pooled_features.npz").read_bytes()),
        "pooled_only_archive": True, "token_states_retained": False,
        "encoder_forward_calls": sum(row["model_forward_calls"] for row in receipts),
        "encoder_examples": sum(row["batch_size"] for row in receipts),
        "encoder_wall_ns_including_load": time.perf_counter_ns() - start,
        "encoder_process_cpu_ns_including_load": time.process_time_ns() - cpu_start,
        "physical_model": owner.accounting, "receipts": receipts}
    write_json(target / "encoder_manifest.json", manifest)
    return features, sources, owner.identity, manifest


def calibrated_probabilities(scores, calibration_labels, calibration_indices):
    tensor = torch.as_tensor(scores, dtype=torch.float64)
    indices = torch.tensor(calibration_indices)
    gold = torch.tensor(calibration_labels)
    temperature = min(TEMPERATURES, key=lambda value: (
        float(F.cross_entropy(tensor[indices] / value, gold)), abs(np.log(value)), value))
    return torch.softmax(tensor / temperature, dim=-1).float(), temperature


def feature_baselines(features, observed_training_labels, train_indices):
    normalized = F.normalize(features, dim=-1)
    training = normalized[train_indices]
    training_labels = torch.tensor(observed_training_labels)
    start = time.perf_counter_ns()
    pairwise = normalized @ training.T
    nearest = torch.stack([pairwise[:, training_labels == label].max(dim=1).values
                           for label in range(4)], dim=1) * 20.0
    nearest_ns = time.perf_counter_ns() - start
    start = time.perf_counter_ns()
    centroids = F.normalize(torch.stack([training[training_labels == label].mean(dim=0)
                                        for label in range(4)]), dim=-1)
    centroid = (normalized @ centroids.T) * 20.0
    centroid_ns = time.perf_counter_ns() - start
    return {"frozen_nearest_neighbor": (nearest, {"batch_selector_ns": nearest_ns,
        "retained_tensor_bytes": training.numel() * 4, "cosine_pairs": len(features) * len(training)}),
        "frozen_nearest_centroid": (centroid, {"batch_selector_ns": centroid_ns,
        "retained_tensor_bytes": centroids.numel() * 4, "cosine_pairs": len(features) * 4})}


def evaluate_arm(cases, probabilities, target, arm, selector_cost=None):
    predictions = probabilities.argmax(dim=1).tolist()
    accepted = (probabilities.max(dim=1).values >= 0.7).tolist()
    result = {}
    for policy in ("forced", "confidence_0.7"):
        choices = {case.query.query_id: (predictions[index] if policy == "forced" or accepted[index] else None)
                   for index, case in enumerate(cases) if case.query.split in ("development", "heldout")}
        evaluation = evaluate_policy(cases, choices, arm=arm, policy=policy, costs=selector_cost)
        write_lines(target / f"{arm}-{policy}.jsonl.gz", evaluation["rows"])
        result[policy] = evaluation
    return result


def learned_sources(cases, sources, target, plan):
    included = {case.query.query_id for case in cases if case.query.split in ("train", "calibration")}
    closure = {source for case, source in zip(cases, sources) if case.query.query_id in included}
    closure.update(case.query.input_sha256 for case in cases if case.query.query_id in included)
    with gzip.open(target / "replay_attempts.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            if row["query_id"] in included:
                closure.add(sha(canonical(row)))
    closure.update(plan["source_code_sha256"].values())
    closure.add(plan["encoder"]["inventory_sha256"])
    closure.add(sha(canonical(plan["contracts"])))
    return sorted(closure)


def withdrawal_probes(directory, owner_pin, bundle, cases, source_rows):
    """Independent scenarios; never roll back the clean evaluation provider."""
    reports = []
    for role in ("train", "calibration", "heldout"):
        index = next(index for index, case in enumerate(cases) if case.query.split == role)
        source = source_rows[index]
        current = [WithdrawalViewV1(bundle.identity.scope_id)]
        provider = lambda: current[0]
        owner = ReplayHeadOwner(directory, owner_pin, bundle.identity, provider)
        current[0] = WithdrawalViewV1(bundle.identity.scope_id, 1, (source,))
        try:
            owner.predict(bundle)
        except ValueError:
            pass
        else:
            raise ValueError("withdrawn source was used")
        reloaded = None
        rejected_at = "load"
        try:
            reloaded = ReplayHeadOwner(directory, owner_pin, bundle.identity, provider)
            rejected_at = "predict"
            reloaded.predict(bundle)
        except ValueError:
            pass
        else:
            raise ValueError("reload bypassed current source withdrawal")
        if owner.forward_calls or (reloaded is not None and reloaded.forward_calls):
            raise ValueError("pre-forward source rejection incurred an unexpected Head call")
        current[0] = WithdrawalViewV1(bundle.identity.scope_id)
        try:
            owner.predict(bundle)
        except ValueError:
            pass
        else:
            raise ValueError("host frontier rollback resurrected an invalidated owner")
        reports.append({"role": role, "source_digest": source, "use_rejected": True,
            "reload_use_rejected": True, "reload_rejected_at": rejected_at,
            "same_owner_rollback_rejected": True, "actual_head_module_calls": owner.forward_calls})
        owner._handle.remove()
        if reloaded is not None:
            reloaded._handle.remove()
    current = [WithdrawalViewV1(bundle.identity.scope_id)]
    owner = ReplayHeadOwner(directory, owner_pin, bundle.identity, lambda: current[0])
    def revoke_during_forward(module, arguments, output):
        current[0] = WithdrawalViewV1(bundle.identity.scope_id, 1, (source,))
    handle = owner.model._head.register_forward_hook(revoke_during_forward)
    try:
        owner.predict(bundle)
    except ValueError:
        pass
    else:
        raise ValueError("source changed during actual forward but output escaped")
    if owner.forward_calls != 1 or not owner.invalidated:
        raise ValueError("mid-forward probe did not execute exactly once and invalidate the owner")
    reports.append({"role": "heldout_during_actual_forward", "source_digest": source,
        "use_rejected": True, "actual_head_module_calls": owner.forward_calls,
        "actual_head_example_calls": owner.example_calls})
    handle.remove()
    owner._handle.remove()
    return reports


def train_and_reload(seed, cohorts, all_bundle, target, plan, source_pins, cases, source_rows):
    config = HeadTrainingConfigV1(task_count=4, mode="linear", steps=200, learning_rate=0.2,
                                  seed=seed, confidence_threshold=0.7)
    counts = {"module_calls": 0, "example_calls": 0}
    original = LightCellHead.forward
    def counted(module, features, state):
        counts["module_calls"] += 1
        counts["example_calls"] += len(features)
        return original(module, features, state)
    start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    # The heldout cohort and its labels are deliberately absent from this call.
    with patch.object(LightCellHead, "forward", counted):
        trained = train_cell_head(cohorts["train"], cohorts["calibration"],
                                  {"development": cohorts["development"]}, config=config)
    training_cost = {**counts, "wall_ns": time.perf_counter_ns() - start,
                     "process_cpu_ns": time.process_time_ns() - cpu_start,
                     "parameter_example_updates": trained.report["trainable_parameter_count"]
                                                  * config.steps * len(cohorts["train"].labels),
                     "resident_parameter_bytes": trained.report["resident_parameter_count"] * 4,
                     "trainable_parameter_bytes": trained.report["trainable_parameter_count"] * 4}
    directory = target / f"head-seed-{seed}"
    saved = save_head_artifact(trained, directory)
    owner_manifest = {"head_manifest_sha256": saved["manifest_sha256"],
        "feature_identity": asdict(all_bundle.identity), "learned_source_digests": source_pins,
        "plan_sha256": sha((target / "plan.json").read_bytes()),
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
    write_json(directory / "replay_owner.json", owner_manifest)
    owner_pin = sha((directory / "replay_owner.json").read_bytes())
    clean_view = WithdrawalViewV1(all_bundle.identity.scope_id)
    provider = lambda: clean_view
    loaded = ReplayHeadOwner(directory, owner_pin, all_bundle.identity, provider)
    start = time.perf_counter_ns()
    prediction = loaded.predict(all_bundle)
    inference_ns = time.perf_counter_ns() - start
    before_reference = dict(counts)
    with patch.object(LightCellHead, "forward", counted):
        reference = trained.predict_task(all_bundle)
    if not torch.equal(prediction["task_probabilities"], reference["task_probabilities"]):
        raise ValueError("reloaded artifact predictions differ from the trained tensors")
    withdrawal = withdrawal_probes(directory, owner_pin, all_bundle, cases, source_rows)
    loaded._handle.remove()
    return prediction["task_probabilities"], {"training": trained.report, "training_cost": training_cost,
        "artifact": saved, "owner_manifest_sha256": owner_pin, "reload_bit_exact": True,
        "loaded_model_module_calls": loaded.forward_calls, "loaded_model_example_calls": loaded.example_calls,
        "reference_parity_extra_module_calls": counts["module_calls"] - before_reference["module_calls"],
        "reference_parity_extra_example_calls": counts["example_calls"] - before_reference["example_calls"],
        "prediction_wall_ns": inference_ns, "withdrawal": withdrawal}


def learn(target, snapshot, accepted, expected_plan_sha256=None):
    target = Path(target)
    plan = require_plan(target, expected_plan_sha256)
    if accepted is not True or not snapshot or not (Path(snapshot) / "model.safetensors").is_file():
        raise ValueError("pinned local Granite weights and existing operator acceptance required")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    cases = make_cases()
    observed_labels = replay_labels(target)
    features, sources, identity, encoder = encode_queries(cases, plan, snapshot, accepted, target)
    indices = {split: [index for index, case in enumerate(cases) if case.query.split == split] for split in SPLITS}
    model_labels = {split: [observed_labels[cases[index].query.query_id] for index in rows]
                    for split, rows in indices.items() if split != "heldout"}
    bundles = {split: pooled_bundle(features[rows], [sources[index] for index in rows], identity)
               for split, rows in indices.items()}
    cohorts = {split: HeadCohortV1(bundles[split], tuple(model_labels[split]),
                   tuple(cases[index].query.source_group_id for index in rows))
               for split, rows in indices.items() if split != "heldout"}
    all_bundle = pooled_bundle(features, sources, identity)
    source_pins = learned_sources(cases, sources, target, plan)
    baseline_scores = feature_baselines(features, model_labels["train"], indices["train"])
    index = ReplayBM25([cases[row].query for row in indices["train"]], {
        cases[row].query.query_id: observed_labels[cases[row].query.query_id] for row in indices["train"]})
    bm25, bm25_costs = [], {}
    for case in cases:
        scores, cost = index.scores(case.query)
        bm25.append(scores)
        bm25_costs[case.query.query_id] = cost
    baseline_scores["bm25_replay"] = (torch.tensor(bm25), {"retained_index_bytes": index.retained_bytes})
    index.db.close()
    arm_results, reports = {}, {}
    for arm, (scores, cost) in baseline_scores.items():
        probabilities, temperature = calibrated_probabilities(scores, model_labels["calibration"], indices["calibration"])
        arm_results[arm] = evaluate_arm(cases, probabilities, target, arm,
                                        bm25_costs if arm == "bm25_replay" else None)
        reports[arm] = {"temperature": temperature, "cost": cost,
                       "evaluation": {key: value["summary"] for key, value in arm_results[arm].items()}}
    for seed in plan["training"]["seeds"]:
        arm = f"head_seed_{seed}"
        probabilities, report = train_and_reload(seed, cohorts, all_bundle, target, plan,
                                                 source_pins, cases, sources)
        arm_results[arm] = evaluate_arm(cases, probabilities, target, arm)
        report["evaluation"] = {key: value["summary"] for key, value in arm_results[arm].items()}
        report["comparisons"] = {baseline: [paired_interval(arm_results[arm]["forced"]["rows"],
            arm_results[baseline]["forced"]["rows"], grouping=grouping)
            for grouping in ("input_family", "template_family")] for baseline in baseline_scores}
        reports[arm] = report
        print(json.dumps({"trained_seed": seed, "heldout": report["evaluation"]["forced"]["heldout"]}), flush=True)
    success = {arm: report["evaluation"]["forced"]["heldout"]["success_rate"] for arm, report in reports.items()}
    improved = all(success[f"head_seed_{seed}"] > max(success[baseline] for baseline in baseline_scores)
                   for seed in plan["training"]["seeds"])
    replay_summary = json.loads((target / "replay_summary.json").read_bytes())
    observe_report = json.loads((target / "observe_report.json").read_bytes())
    main_policy_calls = {policy: sum(value[policy]["summary"][split]["execution_calls"]
        for value in arm_results.values() for split in ("development", "heldout"))
        for policy in ("forced", "confidence_0.7")}
    prior_calls = sum(value["execution_calls"] for value in observe_report["bm25"].values())
    file_execution_accounting = {"oracle_replay": replay_summary["execution_calls"],
        "observe_phase_bm25_forced": prior_calls, "main_evaluation_by_policy": main_policy_calls,
        "total_actual_file_executions": replay_summary["execution_calls"] + prior_calls
                                        + sum(main_policy_calls.values()),
        "unit": "One query/arm/policy selects at most one execution; forced and selective are separate.",
        "mechanism_unit_test_executions_included": False}
    summary = {"schema": "hepta.procedure-replay-result.v1", "plan_sha256": sha((target / "plan.json").read_bytes()),
        "feature_manifest_sha256": sha((target / "encoder_manifest.json").read_bytes()),
        "replay_summary": replay_summary, "file_execution_accounting": file_execution_accounting,
        "encoder": {key: value for key, value in encoder.items() if key != "receipts"},
        "arms": reports, "heldout_forced_success": success,
        "all_seeds_exceed_all_strong_baselines": improved,
        "head_training_steps": 3 * 200, "encoder_training_steps": 0,
        "process_max_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "runtime": {"torch": torch.__version__, "numpy": np.__version__},
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False,
        "boundary": plan["boundary"], "historical_p37_weights_reused": False,
        "statement": "Actual local procedure selection learning and file outcomes on a manually authored "
                     "distribution. No generated programs, runtime execution permission or general-memory claim."}
    write_json(target / "result.json", summary)
    write_lines(target / "source_snapshot.jsonl.gz", [{"path": name, "sha256": digest,
                "utf8": (ROOT / name).read_text()} for name, digest in plan["source_code_sha256"].items()])
    inventory = [{"path": str(path.relative_to(target)), "bytes": path.stat().st_size,
                  "sha256": sha(path.read_bytes())} for path in sorted(target.rglob("*")) if path.is_file()]
    if sum(row["bytes"] for row in inventory) > plan["limits"]["new_evidence_bytes"]:
        raise ValueError("evidence exceeded the preregistered storage budget")
    write_json(target / "inventory.json", inventory)
    return {"heldout_forced_success": success, "all_seeds_exceed_all_strong_baselines": improved,
            "result_sha256": sha((target / "result.json").read_bytes()),
            "retained_evidence_bytes": sum(row["bytes"] for row in inventory)}
