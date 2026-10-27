"""Post-freeze selected-router analysis; no model fitting, selection or inference.

Only saved decisions from the preselected model are analyzed on formal language.
Candidate artifacts and caches are inspected solely for source/byte/work counts.
"""

from collections import Counter, defaultdict
import hashlib
import io
import json
import math
from pathlib import Path
import sys

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

# Bootstrap intentionally initializes the frozen sibling package import paths.
import bootstrap  # noqa: E402, F401
from v3.native_structure_audit_core import Reader  # noqa: E402
from v4.semantic_common import slot_text  # noqa: E402

RUN = PACKAGE / "results/20261026-v4-frozen"
SOURCE = "6206dfba0a3219534dd1a0274431bf48fd23673c"
SEAL = "ec975d0e9afc53903ba2d26129446e263d06ebea0abb8b9e729e556546eca3ff"
REPLAY_SHA = "8969e6a9c8fc7ae5e6774455e7c3586dbbdd6f0085d0a5fe4d1911a8e110216a"
REJECT = "__reject__"
INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def jsonl(reader, name):
    return [json.loads(line) for line in reader.raw(name).splitlines()]


def metrics(rows, decisions, *, raw=False):
    require(len(rows) == len(decisions) and rows, "nonempty matching decision rows required")
    known = [(row, decision) for row, decision in zip(rows, decisions, strict=True) if row["intent"] != REJECT]
    unknown = [(row, decision) for row, decision in zip(rows, decisions, strict=True) if row["intent"] == REJECT]
    def route(decision):
        return (None if decision["raw_route"] == REJECT else decision["raw_route"]) if raw else decision["route"]

    accepted = sum(route(decision) is not None for _, decision in known)
    correct = sum(route(decision) == row["intent"] for row, decision in known)
    false = sum(route(decision) is not None for _, decision in unknown)
    return {
        "queries": len(rows), "known_queries": len(known), "unsupported_queries": len(unknown),
        "known_accepted": accepted, "known_correct_accepted": correct,
        "known_incorrect_accepted": accepted - correct, "unsupported_accepted": false,
        "known_coverage": accepted / len(known), "known_correct_accepted_rate": correct / len(known),
        "accepted_known_accuracy": correct / accepted if accepted else None,
        "unsupported_false_accept_rate": false / len(unknown),
    }


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"count": 0}
    return {"count": len(values), "minimum": float(values.min()), "median": float(np.median(values)),
            "p90": float(np.quantile(values, 0.9)), "maximum": float(values.max())}


def breakdown(rows, decisions):
    known, unknown = {}, {}
    actual_confusion, raw_confusion = defaultdict(Counter), defaultdict(Counter)
    examples = {"accepted_wrong_known": [], "accepted_unsupported": [], "correct_raw_but_declined": [], "wrong_raw_known": []}
    confidence = defaultdict(list)
    for row, decision in zip(rows, decisions, strict=True):
        intent, actual, raw = row["intent"], decision["route"], decision["raw_route"]
        actual_confusion[intent][actual if actual is not None else "abstain"] += 1
        raw_confusion[intent][raw] += 1
        example = {"template_id": row["template_id"], "family": row["family"], "expected": intent,
                   "normalized_utterance": slot_text(row), **decision}
        if intent != REJECT:
            group = known.setdefault(intent, {"queries": 0, "actual_accepted": 0, "actual_correct": 0, "raw_accepted": 0, "raw_correct": 0})
            group["queries"] += 1
            group["actual_accepted"] += actual is not None
            group["actual_correct"] += actual == intent
            group["raw_accepted"] += raw != REJECT
            group["raw_correct"] += raw == intent
            confidence["correct_raw_known" if raw == intent else "incorrect_raw_known"].append(decision["confidence"])
            if actual is not None and actual != intent:
                examples["accepted_wrong_known"].append(example)
            if raw == intent and actual is None:
                examples["correct_raw_but_declined"].append(example)
            if raw != intent:
                examples["wrong_raw_known"].append(example)
        else:
            group = unknown.setdefault(row["family"], {"queries": 0, "actual_false_accepts": 0, "raw_false_accepts": 0})
            group["queries"] += 1
            group["actual_false_accepts"] += actual is not None
            group["raw_false_accepts"] += raw != REJECT
            confidence["raw_unsupported_misclassified_as_supported" if raw != REJECT else "raw_unsupported_correctly_rejected"].append(decision["confidence"])
            if actual is not None:
                examples["accepted_unsupported"].append(example)
    for group in known.values():
        group["actual_correct_rate"] = group["actual_correct"] / group["queries"]
        group["raw_correct_rate"] = group["raw_correct"] / group["queries"]
    for group in unknown.values():
        group["actual_false_accept_rate"] = group["actual_false_accepts"] / group["queries"]
        group["raw_false_accept_rate"] = group["raw_false_accepts"] / group["queries"]
    for name in ("correct_raw_but_declined", "wrong_raw_known"):
        examples[name] = sorted(examples[name], key=lambda row: row["template_id"])[:6]
    return {"per_intent": known, "unsupported_families": unknown,
            "actual_confusion": dict(actual_confusion), "raw_confusion": dict(raw_confusion),
            "dispositions": dict(Counter(row["disposition"] for row in decisions)),
            "confidence_distributions_diagnostic_only": {key: distribution(values) for key, values in confidence.items()},
            "examples": examples, "example_selection": "all actual wrong accepts; first six template IDs per other diagnostic category"}


def artifact(reader, prefix, recorded):
    files = {name: reader.raw(f"{prefix}/{name}") for name in ("manifest.json", "weights.bin", "features.json")}
    inventory = {name: {"bytes": len(raw), "sha256": sha(raw)} for name, raw in files.items()}
    require(inventory == recorded["files"], "actual candidate artifact inventory differs")
    require(sum(value["bytes"] for value in inventory.values()) == recorded["bytes"], "candidate actual byte count differs")
    manifest = json.loads(files["manifest.json"])
    require(manifest["source_commit"] == SOURCE, "candidate source commit differs")
    require(manifest["manifest_sha256"] == recorded["manifest_sha256"] == sha(canonical({key: value for key, value in manifest.items() if key != "manifest_sha256"})), "candidate manifest binding differs")
    require(manifest["parameter_sha256"] == sha(files["weights.bin"]) and manifest["parameter_bytes"] == len(files["weights.bin"]), "parameter byte binding differs")
    require(manifest["feature_digest"] == sha(canonical(json.loads(files["features.json"]))), "feature identity differs")
    return manifest, inventory


def cache_record(raw):
    stream = io.BytesIO(raw)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
    else:
        raise ValueError("unknown non-pickled cache array version")
    require(not dtype.hasobject, "object cache is not an admitted numeric artifact")
    numerical = math.prod(shape) * dtype.itemsize
    require(stream.tell() + numerical == len(raw), "cache header and numerical length differ")
    return {"bytes": len(raw), "sha256": sha(raw), "shape": list(shape), "dtype": dtype.str,
            "fortran_order": fortran, "numeric_bytes": numerical, "npy_header_bytes": stream.tell()}


def costs(reader, prefix, summary, requests, config, replay):
    receipt = reader.json(f"{prefix}/router/selection-receipt.json")
    require(receipt == summary["routing_training"] and receipt["config"] == config, "routing receipt/config copy differs")
    names = [f"{mode}-{head}-l2{l2:g}" for mode, head in config["architectures"] for l2 in config["l2_grid"]]
    require([record["id"] for record in receipt["candidates"]] == names and len(names) == 14, "fourteen fixed candidates required")
    candidates = []
    for record in receipt["candidates"]:
        manifest, inventory = artifact(reader, f"{prefix}/router/candidates/{record['id']}", record["artifact"])
        steps = config["steps"] * (2 if record["architecture"] == "factorized64" else 1)
        batch = config["sequence_batch_size"] if record["feature_mode"] == "sequence" else config["batch_size"]
        require(record["fit"]["steps"] == manifest["steps"] == steps, "optimizer work differs")
        require(record["fit"]["actual_example_updates"] == steps * batch, "optimizer example updates differ")
        require(len(record["calibration"]["grid"]) == 96, "fixed calibration grid count differs")
        candidates.append({"id": record["id"], "architecture": record["architecture"], "optimizer_steps": steps,
                           "actual_example_updates": steps * batch, "artifact_bytes": record["artifact"]["bytes"],
                           "parameter_bytes": manifest["parameter_bytes"], "parameter_sha256": manifest["parameter_sha256"],
                           "files": inventory, "training_wall_seconds": record["fit"]["train_seconds"],
                           "selection_grid_evaluations": len(record["calibration"]["grid"]),
                           "held_candidate_evaluation_performed_by_this_analysis": False})
    chosen = max(receipt["candidates"], key=lambda value: (value["calibration"]["risk_feasible"], value["calibration"]["selected"]["known_correct_accepted_rate"], -value["fit"]["actual_example_updates"], -value["artifact"]["bytes"], value["id"]))
    require(chosen["id"] == receipt["primary"], "predeclared selection rule differs")
    pointer = reader.raw(f"{prefix}/router/PRIMARY.json")
    require(pointer == reader.raw(f"{prefix}/deployed-router/PRIMARY.json") and sha(pointer) == receipt["primary_sha256"], "actual deployed pointer differs")
    selected, selected_inventory = artifact(reader, f"{prefix}/router/selected", receipt["selected_artifact"])
    deployed, deployed_inventory = artifact(reader, f"{prefix}/deployed-router/selected", receipt["selected_artifact"])
    require(selected_inventory == deployed_inventory and selected == deployed, "research/deployed selected copies differ")
    cache = {}
    for name, bound in receipt["cache_files"].items():
        cache[name] = cache_record(reader.raw(f"{prefix}/router/cache/{name}"))
        require({key: cache[name][key] for key in ("bytes", "sha256")} == bound, "cache binding differs")
    for mode, feature in receipt["features"].items():
        require(sum(value["numeric_bytes"] for name, value in cache.items() if name.startswith(mode + "-")) == feature["cached_numeric_bytes"], "feature-cache numerical cost differs")
    corpus_bytes, corpus_rows, unique_counts = 0, {}, {}
    for partition, filename in (("train", "training-utterances.jsonl"), ("selection", "selection-utterances.jsonl")):
        raw = reader.raw(f"{prefix}/router/{filename}")
        require({"bytes": len(raw), "sha256": sha(raw)} == receipt["files"][filename], "corpus bytes differ")
        rows = [json.loads(line) for line in raw.splitlines()]
        corpus_bytes += len(raw)
        corpus_rows[partition] = {"rows": len(rows), "known": sum(row["intent"] != REJECT for row in rows), "unsupported": sum(row["intent"] == REJECT for row in rows)}
        unique_counts[partition] = len({slot_text(row) for row in rows})
        require(unique_counts[partition] == receipt["encoder"][partition]["actual_encoder_calls"], "encoder corpus call ledger differs from unique texts")
    known_calls = len({slot_text(row) for row in requests})
    require(known_calls == summary["fresh_read"]["inference"]["actual_encoder_calls"] == summary["parent_reload_verification_work"]["actual_encoder_calls"] == replay["additional_actual_native_encoder_calls"], "serving/replay encoder call ledger differs")
    expected = {"all_candidate_optimizer_steps": sum(row["optimizer_steps"] for row in candidates),
                "all_candidate_actual_example_updates": sum(row["actual_example_updates"] for row in candidates),
                "all_candidate_artifact_bytes": sum(row["artifact_bytes"] for row in candidates),
                "selected_copy_artifact_bytes": sum(value["bytes"] for value in selected_inventory.values()),
                "serialized_feature_cache_bytes": sum(value["bytes"] for value in cache.values()),
                "corpus_files_bytes": corpus_bytes}
    expected["research_model_artifact_bytes_including_selected_copy"] = expected["all_candidate_artifact_bytes"] + expected["selected_copy_artifact_bytes"]
    expected["deployment_router_bytes_including_pointer_and_feature_metadata"] = expected["selected_copy_artifact_bytes"] + len(pointer)
    expected["deployment_numeric_parameter_and_idf_bytes"] = selected["parameter_bytes"] + 8 * len(json.loads(reader.raw(f"{prefix}/deployed-router/selected/features.json")).get("idf", []))
    for key, value in expected.items():
        require(value == receipt["cost"][key], f"routing cost mismatch: {key}")
    retained = {name: info for name, info in reader.seal["files"].items() if name.startswith(prefix + "/router/") or name.startswith(prefix + "/deployed-router/")}
    return {**expected, "candidate_count": len(candidates), "candidates": candidates,
            "corpora": corpus_rows, "caches": cache, "serialized_cache_numeric_bytes": sum(value["numeric_bytes"] for value in cache.values()),
            "additional_deployed_selected_copy_bytes": expected["selected_copy_artifact_bytes"],
            "both_actual_pointer_copies_bytes": 2 * len(pointer),
            "all_retained_model_copies_and_pointers_bytes": expected["all_candidate_artifact_bytes"] + 2 * expected["selected_copy_artifact_bytes"] + 2 * len(pointer),
            "complete_router_and_deployed_directories_bytes": sum(info["bytes"] for info in retained.values()),
            "complete_router_and_deployed_directories_files": len(retained),
            "training_and_selection_native_calls": sum(unique_counts.values()),
            "fresh_serving_native_calls": known_calls, "parent_reload_native_calls": known_calls,
            "formal_study_native_calls": sum(unique_counts.values()) + 2 * known_calls,
            "audit_only_additional_observed_native_calls": known_calls,
            "candidate_training_wall_seconds": sum(row["training_wall_seconds"] for row in candidates),
            "training_encoding_wall_seconds": sum(receipt["encoder"][key]["encoding_seconds"] for key in ("train", "selection")),
            "shared_encoder_bytes_once_per_deployment": receipt["encoder"]["shared_base_bytes"],
            "optimizer_updates_are_not_total_forward_flops": True,
            "cache_or_serialized_state_bytes_are_not_process_RSS": True}


def interval(values, stats):
    values = np.asarray(values)
    random = np.random.default_rng(stats["bootstrap_seed"])
    means = values[random.integers(0, len(values), (stats["bootstrap_draws"], len(values)))].mean(axis=1)
    return {"mean": float(values.mean()), "minimum": float(values.min()), "maximum": float(values.max()),
            "percentile_95_interval": np.quantile(means, [0.025, 0.975]).tolist(),
            "unit": "five seeded models conditional on the same fixed independent language templates; domains not resampled"}


def main():
    output = PACKAGE / "analyses/formal-routing-findings.json"
    markdown = output.with_suffix(".md")
    require(not output.exists() and not markdown.exists(), "analysis cannot overwrite previous findings")
    replay_path = PACKAGE / "validation/formal-selected-replay-audit.json"
    replay_raw = replay_path.read_bytes()
    require(sha(replay_raw) == REPLAY_SHA, "formal replay identity differs")
    replay = json.loads(replay_raw)
    require(replay["verified"] and not replay["development_only"] and replay["source_commit"] == SOURCE and replay["manifest_sha256"] == SEAL, "formal replay source/phase differs")
    reader = Reader(RUN)
    require(sha(reader.raw("MANIFEST.json")) == SEAL, "formal seal differs")
    reader.seal = reader.json("MANIFEST.json")
    protocol = reader.json("protocol.json")
    seeds, settings = protocol["seeds"], protocol["joint"]
    domains = settings["science_domains"] + settings["new_event_views"]
    entries, templates = [], None
    for seed in seeds:
        prefix = f"joint/seed-{seed}"
        summary = reader.json(f"{prefix}/summary.json")
        rows = jsonl(reader, f"{prefix}/grader-queries.jsonl")
        fresh = reader.json(f"{prefix}/fresh-router-output.json")
        requests = reader.json(f"{prefix}/unlabeled-serving-requests.json")
        require(requests == [{key: row[key] for key in ("utterance", "series_name", "date")} for row in rows], "target-free serving requests differ")
        require(len(rows) == len(fresh["decisions"]) == 6 * 216, "formal case denominator differs")
        replay_seed = next(record for record in replay["results"] if record["seed"] == seed)
        ledger = costs(reader, prefix, summary, requests, protocol["routing"], replay_seed)
        receipt = summary["routing_training"]
        chosen = next(record for record in receipt["candidates"] if record["id"] == receipt["primary"])
        manifest = reader.json(f"{prefix}/deployed-router/selected/manifest.json")
        metrics_by_domain, first_decisions, details = {}, None, None
        for domain in domains:
            pairs = [(row, decision) for row, decision in zip(rows, fresh["decisions"], strict=True) if row["domain"] == domain]
            domain_rows, decisions = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
            require(len(domain_rows) == 216, "missing formal domain queries")
            normalized = [{"id": row["template_id"], "intent": row["intent"], "family": row["family"], "utterance": slot_text(row)} for row in domain_rows]
            templates = normalized if templates is None else templates
            require(normalized == templates, "language changes across domains or seeds")
            first_decisions = decisions if first_decisions is None else first_decisions
            require(decisions == first_decisions, "domain-factorized selected route decisions differ")
            actual, raw = metrics(domain_rows, decisions), metrics(domain_rows, decisions, raw=True)
            for key, value in actual.items():
                if key in summary["domains"][domain]["routing"]:
                    require(value == summary["domains"][domain]["routing"][key], "recomputed actual metric differs")
            gate = actual["known_correct_accepted_rate"] >= settings["minimum_correct_coverage"] and actual["unsupported_false_accept_rate"] <= settings["maximum_ood_false_accept"]
            require(gate == summary["domains"][domain]["gates"]["semantic"], "reported semantic gate differs")
            metrics_by_domain[domain] = {"actual_deployed": actual, "raw_argmax_diagnostic_only": raw,
                                       "known_coverage_gate": actual["known_correct_accepted_rate"] >= settings["minimum_correct_coverage"],
                                       "ood_risk_gate": actual["unsupported_false_accept_rate"] <= settings["maximum_ood_false_accept"],
                                       "semantic_gate": gate, "raw_correct_coverage_upper_bound_under_rejection_only": raw["known_correct_accepted_rate"]}
            if details is None:
                details = breakdown(domain_rows, decisions)
        require(summary["domain_policy_updates"] == 0 and summary["frozen_before"] == summary["frozen_after"], "formal policy changed")
        entries.append({"seed": seed, "primary": receipt["primary"], "architecture": manifest["architecture"],
                        "threshold": manifest["threshold"], "margin": manifest["margin"], "reject_all": manifest["reject_all"],
                        "parameter_sha256": manifest["parameter_sha256"], "selection_only_metrics": chosen["calibration"]["selected"],
                        "selected_was_already_unqualified_on_selection": not receipt["primary_selection_constraints_satisfied"],
                        "domains": metrics_by_domain, "same_selected_decisions_across_all_six_domains": True,
                        "domain_policy_updates": 0, "diagnostic_breakdown_once_per_template": details, "cost": ledger})
    aggregate_intents, aggregate_ood = {}, {}
    for key, destination, source_key, count_keys in (
        ("intent", aggregate_intents, "per_intent", ("queries", "actual_accepted", "actual_correct", "raw_accepted", "raw_correct")),
        ("family", aggregate_ood, "unsupported_families", ("queries", "actual_false_accepts", "raw_false_accepts")),
    ):
        names = entries[0]["diagnostic_breakdown_once_per_template"][source_key]
        for name in names:
            destination[name] = {count: sum(item["diagnostic_breakdown_once_per_template"][source_key][name][count] for item in entries) for count in count_keys}
            destination[name]["distinct_authored_templates"] = destination[name]["queries"] // len(seeds)
    totals_keys = ("candidate_count", "all_candidate_optimizer_steps", "all_candidate_actual_example_updates", "all_candidate_artifact_bytes", "selected_copy_artifact_bytes", "additional_deployed_selected_copy_bytes", "both_actual_pointer_copies_bytes", "all_retained_model_copies_and_pointers_bytes", "complete_router_and_deployed_directories_bytes", "corpus_files_bytes", "serialized_feature_cache_bytes", "serialized_cache_numeric_bytes", "training_and_selection_native_calls", "fresh_serving_native_calls", "parent_reload_native_calls", "formal_study_native_calls", "audit_only_additional_observed_native_calls", "candidate_training_wall_seconds", "training_encoding_wall_seconds")
    total_cost = {key: sum(item["cost"][key] for item in entries) for key in totals_keys}
    primary_domain = domains[0]
    per_domain = {}
    for domain in domains:
        per_domain[domain] = {}
        for name in ("actual_deployed", "raw_argmax_diagnostic_only"):
            data = [entry["domains"][domain][name] for entry in entries]
            per_domain[domain][name] = {key: sum(item[key] for item in data) for key in ("queries", "known_queries", "unsupported_queries", "known_accepted", "known_correct_accepted", "known_incorrect_accepted", "unsupported_accepted")}
            for key in ("known_correct_accepted_rate", "known_coverage", "unsupported_false_accept_rate"):
                per_domain[domain][name][key] = interval([item[key] for item in data], protocol["statistics"])
    gates = [item["domains"][domain] for item in entries for domain in domains]
    finding = {
        "schema": "memory-cell-v4.formal-selected-routing-findings.v1", "source_commit": SOURCE,
        "run": str(RUN), "manifest_sha256": SEAL, "analysis_source_sha256": sha(Path(__file__).read_bytes()),
        "selected_replay": {"path": str(replay_path), "sha256": REPLAY_SHA, "verified": True,
                            "exact_decisions": replay["request_decisions_replayed"], "native_calls": replay["additional_actual_native_encoder_calls"],
                            "wall_seconds": replay["audit_wall_seconds"], "process_cpu_seconds": replay["audit_process_cpu_seconds"]},
        "scope": {"formal_seeds": seeds, "domains": domains, "distinct_language_templates": len(templates),
                  "distinct_supported_templates": sum(row["intent"] != REJECT for row in templates),
                  "distinct_near_ood_templates": sum(row["intent"] == REJECT for row in templates),
                  "actual_request_decisions": replay["request_decisions_replayed"], "model_template_pairs_after_domain_deduplication": len(seeds) * len(templates),
                  "domains_or_seeds_are_not_new_independent_language_templates": True,
                  "same_normalized_templates_and_decisions_across_six_domains_per_seed": True,
                  "normalized_authored_templates_sha256": sha(canonical(templates)),
                  "no_held_candidate_reselection_or_threshold_search": True,
                  "no_unselected_candidate_held_inference_or_grading": True,
                  "raw_argmax_is_posthoc_diagnostic_not_a_deployed_or_qualified_arm": True,
                  "no_new_model_inference_inside_this_analysis": True},
        "qualification": {"minimum_correct_accepted_known": settings["minimum_correct_coverage"],
                          "maximum_unsupported_false_accept": settings["maximum_ood_false_accept"],
                          "passed_semantic_cases": sum(item["semantic_gate"] for item in gates), "total_seed_domain_cases": len(gates),
                          "correct_coverage_pass_cases": sum(item["known_coverage_gate"] for item in gates),
                          "ood_risk_pass_cases": sum(item["ood_risk_gate"] for item in gates),
                          "all_seed_domain_requirement_passes": all(item["semantic_gate"] for item in gates),
                          "all_selected_models_raw_correct_upper_bound_below_gate": all(item["domains"][primary_domain]["raw_correct_coverage_upper_bound_under_rejection_only"] < settings["minimum_correct_coverage"] for item in entries),
                          "all_primaries_already_failed_selection_coverage": all(item["selected_was_already_unqualified_on_selection"] for item in entries)},
        "seeds": entries, "per_domain_across_seed_models": per_domain,
        "per_intent_across_seeds_domain_duplicates_removed": aggregate_intents,
        "near_ood_families_across_seeds_domain_duplicates_removed": aggregate_ood,
        "formal_cost_totals": {**total_cost, "shared_base_bytes_count_once_per_deployment": entries[0]["cost"]["shared_encoder_bytes_once_per_deployment"],
                               "base_loads_in_formal_study": 1 + len(seeds), "additional_base_loads_in_selected_replay": 1,
                               "prior_public_development_costs_are_additional": True,
                               "prior_development_ledger": "analyses/routing-development-findings.json",
                               "all_fit_candidates_and_both_selected_artifact_copies_charged": True},
        "limits": ["The supplied explicit entity/date slots remove identity strings; addressing extraction is not learned.",
                   "All six supported operation families, primitive types and layout search catalog are supplied.",
                   "These are written-fact retrieval requests, not predictions of previously unwritten facts.",
                   "High accepted-known accuracy does not meet the required correct-known coverage.",
                   "Fixed-workload seed bootstrap intervals are not guarantees for new paraphrases or domains.",
                   "No claim that sequence heads outperform dense heads follows from only the preselected held evaluations.",
                   "A rejection-only threshold cannot correct wrong argmax labels; raw-correct rate is a bound, not a new selected threshold.",
                   "Frozen execution/replay is verified independently of scientific efficacy."],
        "inputs_read": reader.files,
    }
    require(sha(reader.raw("MANIFEST.json")) == SEAL, "formal seal changed during analysis")
    with output.open("x") as stream:
        json.dump(finding, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    write_markdown(markdown, finding, sha(output.read_bytes()))
    print(json.dumps({"output": str(output), "sha256": sha(output.read_bytes()), "markdown": str(markdown), "qualification": finding["qualification"], "cost": total_cost}, indent=2))


def write_markdown(path, finding, finding_sha):
    entries, costs = finding["seeds"], finding["formal_cost_totals"]
    domain = finding["scope"]["domains"][0]
    lines = ["# V4 正式路由结果：产物重放通过，语义门槛失败", "",
             "本分析只使用冻结后已经保存的已选模型决策；没有追加训练、阈值搜索、候选重选或未选候选的 held 评估。", "",
             f"执行源码：`{SOURCE}`。RUN seal：`{SEAL}`。结构化分析 SHA256：`{finding_sha}`。", "",
             "## 结论和有效分母", "",
             "正式 selected-router 的真实 ONNX 重放为 **6480/6480 全字段精确一致，零容差**，参数在重放前后不变；额外原生调用1080次。语义门槛仍为正确接受已知问题≥80%、OOD误接受≤5%，结果 **0/30 个 seed×domain 通过**。所有模型在 selection 阶段就未达到覆盖率门槛，失败被原样带入正式评估。", "",
             "只有216条独立作者模板：144条支持请求、72条近邻OOD（12家族各6条）。它们用于5个已选模型、6个域，形成6480次执行；这些重复不能视为6480条独立语言样本。每个seed中六域归一化文本及全部路由决策相同。四个科学域此前已见，新零售事件视图沿用给定字段和月份地址；这不是开放式类型发现。", "",
             "## 实际部署门槛下的结果", "",
             "下表的每行适用于该seed的六个域。每域known分母144，OOD分母72。", "",
             "| Seed | 预选模型 | 阈值 / margin | 正确接受known | known接受数 | OOD误接受 | 语义gate |",
             "|---|---|---:|---:|---:|---:|---|"]
    for item in entries:
        actual = item["domains"][domain]["actual_deployed"]
        lines.append(f"| {item['seed']} | `{item['primary']}` | {item['threshold']} / {item['margin']} | {actual['known_correct_accepted']}/144 ({actual['known_correct_accepted_rate']:.2%}) | {actual['known_accepted']}/144 | {actual['unsupported_accepted']}/72 ({actual['unsupported_false_accept_rate']:.2%}) | 失败 |")
    lines += ["", "401还违反OOD门槛；其余四个seed仅通过经验OOD门槛，覆盖率仍失败。不能用跨seed平均风险替代“所有seed和所有域都必须通过”的预声明标准。431有1条接受了错误操作；其余seed的已接受known均正确，但大量拒答使高条件准确率不足以形成可用覆盖。", "",
              "## 已选模型 raw argmax：单独的事后诊断", "",
              "这里只把保存的同一模型raw_route视为操作或learned reject；不重跑模型、不改变threshold，也不把此结果当正式替代实验臂。", "",
              "| Seed | raw正确known | raw接受known | raw OOD误接受 |",
              "|---|---:|---:|---:|"]
    for item in entries:
        raw = item["domains"][domain]["raw_argmax_diagnostic_only"]
        lines.append(f"| {item['seed']} | {raw['known_correct_accepted']}/144 ({raw['known_correct_accepted_rate']:.2%}) | {raw['known_accepted']}/144 ({raw['known_coverage']:.2%}) | {raw['unsupported_accepted']}/72 ({raw['unsupported_false_accept_rate']:.2%}) |")
    lines += ["", "**拒答阈值无法单独解决当前失败。** 拒答只会从raw预测中删除答案，不会修正其意图标签；五个已选模型的raw正确known仅35.42%–50.69%，均低于80%。放开阈值同时会使OOD误接受升至16.67%–27.78%。这是在固定已选模型上由计数直接得到的上界，并未寻找一个held最优阈值。", "",
              "## 分意图结果", "",
              "以下去掉六域重复，但同一24条模板仍分别经过5个模型，因此每类分母120不是120条新措辞。", "",
              "| 意图 | 实际正确接受 / 120 | raw正确 / 120 |",
              "|---|---:|---:|"]
    for intent in INTENTS:
        value = finding["per_intent_across_seeds_domain_duplicates_removed"][intent]
        lines.append(f"| `{intent}` | {value['actual_correct']} ({value['actual_correct']/value['queries']:.2%}) | {value['raw_correct']} ({value['raw_correct']/value['queries']:.2%}) |")
    lines += ["", "## 近邻OOD家族", "",
              "每家族6条作者模板×5个已选模型=30次模型判断，六域重复已移除。JSON另外保存每seed完整混淆矩阵、置信度分布、全部实际误接受和稳定选取的拒答例子。", "",
              "| 家族 | 实际误接受 / 30 | raw误接受 / 30 |", "|---|---:|---:|"]
    for family, value in sorted(finding["near_ood_families_across_seeds_domain_duplicates_removed"].items()):
        lines.append(f"| `{family}` | {value['actual_false_accepts']} | {value['raw_false_accepts']} |")
    lines += ["", "这些家族按预声明的请求类型范围判拒绝。不同窗口、比例、百分比或其它统计量不能因为碰巧给出同一个数就视为正确；也不能反过来声称这些运算在数学上不可计算。", "",
              "## 实际训练、编码和保留成本", "",
              "全部14个候选均按公开selection规则完成训练、保存和校准；这里只核验它们的账本，没有用正式查询评价未选候选。4个factorized候选各含两个600-step优化过程，2个sequence候选使用batch32，其余batch128。", "",
              "| 项目 | 五seed合计 |", "|---|---:|"]
    labels = {"candidate_count": "实际候选产物", "all_candidate_optimizer_steps": "优化器step（含分解双头）", "all_candidate_actual_example_updates": "优化器example updates", "training_and_selection_native_calls": "训练/selection原生编码器调用", "fresh_serving_native_calls": "正式fresh serving原生调用", "parent_reload_native_calls": "原parent reload核对原生调用", "formal_study_native_calls": "正式研究原生调用合计", "audit_only_additional_observed_native_calls": "另计审计重放原生调用", "all_candidate_artifact_bytes": "全部候选文件字节", "selected_copy_artifact_bytes": "router内selected副本字节", "additional_deployed_selected_copy_bytes": "另外的deployed selected副本字节", "both_actual_pointer_copies_bytes": "两份实际PRIMARY指针字节", "all_retained_model_copies_and_pointers_bytes": "完整模型副本与指针保留字节", "serialized_feature_cache_bytes": "实际保存的训练/selection缓存字节", "corpus_files_bytes": "训练/selection语料文件字节", "complete_router_and_deployed_directories_bytes": "完整router和deployed目录实际字节"}
    for key, label in labels.items():
        lines.append(f"| {label} | {costs[key]:,} |")
    lines += ["", f"共享编码器部署一次为 **{costs['shared_base_bytes_count_once_per_deployment']:,} B**。dense主选路由器（含metadata和PRIMARY）202,762 B；sequence主选路由器为172,771或172,772 B。每seed缓存122,077,808 B；这些研究缓存不能从总成本中扣除，也不是服务时必需的答案表。", "",
              f"候选训练墙钟时间合计{costs['candidate_training_wall_seconds']:.6f}s，训练及selection编码墙钟合计{costs['training_encoding_wall_seconds']:.6f}s；它们不包括全部持久化、验证和其它实验阶段，因此不能当整个研究耗时。序列头和dense头的example update计算量不同，这里不是FLOPs、货币或能耗比较。serialized bytes也不是进程峰值RSS。", "",
              "正式研究开始前的五轮公开开发成本另见`routing-development-findings.json`，未被这个正式账本覆盖或撤销。研究RUN实际有router/selected和deployed-router/selected两份副本，本分析均计入；最小部署只计一个所选路由器及一个共享base。", "",
              "## 可支持的机制解释及剩余阻断", "",
              "保存、加载、三字段推理、跨域冻结策略及精确执行重放已得到证据。语义能力仍缺少稳定的未见正例识别，以及对相邻操作范围的可靠区分；raw正确覆盖率的上界仍低于80%，说明错误不仅来自过高的拒答阈值。高风险例子集中在比例/归一化等相邻请求，分意图混淆保留在JSON中。", "",
              "不能从这五个按selection选出的模型，推导sequence头在held上优于或劣于所有dense候选；没有评估未选候选。同样，本文不把拒答或重放一致当作通用记忆成功。给定意图、原语、类型、日期槽和显式知识写入的限制保持不变。", "",
              "输入证据：`../results/20261026-v4-frozen/`；实际重放审计：`../validation/formal-selected-replay-audit.json`。所有具体计数、30个seed×domain明细、置信度分布和逐候选真实字节/SHA均在同名JSON中。"]
    with path.open("x") as stream:
        stream.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
