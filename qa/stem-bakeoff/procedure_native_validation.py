"""Read the frozen procedural experiment without importing or executing its code."""

from collections import defaultdict
import gzip
import io
import json
from pathlib import Path
import re
import struct

from procedure_native_format import canonical, npz_tensors, require, sha, verify_weights


CLASSES = ("latest_by_id", "group_totals", "threshold_filter", "stable_score_sort")
SEEDS = (7, 17, 29)


def directory_reader(root):
    root = Path(root).resolve(strict=True)
    def read(name):
        path = root / name
        require(not path.is_symlink() and path.is_file()
                and path.resolve().is_relative_to(root) and path.stat().st_size <= 16 * 1024 * 1024,
                "bounded evidence member required: " + name)
        return path.read_bytes()
    return read


def compressed_rows(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(16 * 1024 * 1024 + 1)
    require(len(expanded) <= 16 * 1024 * 1024, "expanded evidence budget")
    return [json.loads(line) for line in expanded.splitlines()]


def load_frozen_run(read, expected_plan_sha256, expected_result_sha256):
    plan_raw, result_raw = read("plan.json"), read("result.json")
    require(sha(plan_raw) == expected_plan_sha256 and sha(result_raw) == expected_result_sha256,
            "independently retained plan/result pins")
    plan, result = json.loads(plan_raw), json.loads(result_raw)
    require(plan["schema"] == "hepta.procedure-replay-plan.v1"
            and result["schema"] == "hepta.procedure-replay-result.v1"
            and result["plan_sha256"] == expected_plan_sha256
            and tuple(plan["training"]["seeds"]) == SEEDS
            and tuple(contract["id"] for contract in plan["contracts"]) == CLASSES,
            "dedicated procedural plan or class contract order")
    require(all(value["authority"] == "DENY_ALL" and value["mode"] == "SHADOW_ONLY"
                and value["production_activation_allowed"] is False for value in (plan, result)),
            "research-only posture")
    source_snapshot = read("source_snapshot.jsonl.gz")
    source_rows = compressed_rows(source_snapshot)
    require(len(source_rows) == len(plan["source_code_sha256"])
            and {row["path"]: sha(row["utf8"].encode()) for row in source_rows} == plan["source_code_sha256"]
            and all(sha(row["utf8"].encode()) == row["sha256"] for row in source_rows),
            "complete frozen source snapshot")
    queries = compressed_rows(read("queries.jsonl.gz"))
    goals = json.loads(read("scorer_goals.json"))
    require(len(queries) == 192 and len({query["query_id"] for query in queries}) == 192
            and set(goals) == {query["query_id"] for query in queries}
            and all(goal in CLASSES for goal in goals.values()), "frozen query inventory")
    require(sha(canonical([{"query": query, "goal": goals[query["query_id"]]} for query in queries]))
            == plan["case_specification_sha256"], "query/goal specification differs from plan")
    by_id = {query["query_id"]: query for query in queries}
    seen_templates, seen_inputs = set(), set()
    for split, census in plan["partition_census"].items():
        selected = [query for query in queries if query["split"] == split]
        templates, families = ({query[key] for query in selected} for key in ("template_family", "input_family"))
        require(len(selected) == census["queries"] and len(templates) == census["template_families"]
                and len(families) == census["input_file_families"]
                and not templates & seen_templates and not families & seen_inputs,
                "template/source partition overlap or census")
        seen_templates |= templates
        seen_inputs |= families
    for query in queries:
        require(re.fullmatch(r"file-family-[0-9]{2}-[0-3]", query["input_family"]) is not None,
                "bounded input family")
        require(sha(read("inputs/" + query["input_family"] + ".json")) == query["input_sha256"],
                "frozen procedure input bytes changed")
    encoder_raw = read("encoder_manifest.json")
    require(sha(encoder_raw) == result["feature_manifest_sha256"], "Encoder manifest pin")
    encoder = json.loads(encoder_raw)
    require(encoder["query_ids"] == [query["query_id"] for query in queries]
            and encoder["shape"] == [192, 384]
            and encoder["source_record_digests"] == [sha(canonical({"text": query["text"], "record": query}))
                                                      for query in queries],
            "ordered actual query/source-record binding")
    require(encoder["feature_identity"] == result["encoder"]["feature_identity"]
            and encoder["feature_identity"]["purpose"] == "research"
            and encoder["feature_identity"]["checkpoint_revision"] == plan["encoder"]["revision"]
            and encoder["feature_identity"]["scope_id"] == plan["encoder"]["scope_id"],
            "Encoder identity or scope")
    require(sum(row["model_forward_calls"] for row in encoder["receipts"]) == 24
            and sum(row["batch_size"] for row in encoder["receipts"]) == 192
            and [query_id for row in encoder["receipts"] for query_id in row["query_ids"]] == encoder["query_ids"]
            and all(row["checkpoint_inventory_sha256"] == plan["encoder"]["inventory_sha256"]
                    and row["trainable_parameter_count"] == 0 for row in encoder["receipts"]),
            "recorded real Encoder forward receipts")
    features_raw = read("pooled_features.npz")
    require(sha(features_raw) == encoder["npz_sha256"], "pooled NPZ pin")
    features = npz_tensors(features_raw, {"pooled": (192, 384)})["pooled"]
    require(sha(features) == encoder["feature_bytes_sha256"], "actual feature-byte pin")
    replay_raw = read("replay_attempts.jsonl.gz")
    require(sha(replay_raw) == result["replay_summary"]["replay_sha256"], "observed replay pin")
    attempts = compressed_rows(replay_raw)
    grouped = defaultdict(list)
    for row in attempts:
        require(row["query_id"] in by_id and row["execution"]["execution_calls"] == 1,
                "actual replay accounting")
        grouped[row["query_id"]].append(row)
    require(set(grouped) == set(by_id) and all(len(rows) == 4
            and {row["choice"] for row in rows} == {0, 1, 2, 3}
            and sum(row["observation"]["success"] for row in rows) == 1 for rows in grouped.values()),
            "unique observed labels for all queries")
    observed_labels = {key: next(row["choice"] for row in rows if row["observation"]["success"])
                       for key, rows in grouped.items()}
    require(all(CLASSES[label] == goals[key] for key, label in observed_labels.items()),
            "observed outcome/class contract mismatch")
    learned_ids = {query["query_id"] for query in queries if query["split"] in ("train", "calibration")}
    learning_sources = {source for query, source in zip(queries, encoder["source_record_digests"])
                        if query["query_id"] in learned_ids}
    learning_sources.update(query["input_sha256"] for query in queries if query["query_id"] in learned_ids)
    learning_sources.update(sha(canonical(row)) for row in attempts if row["query_id"] in learned_ids)
    learning_sources.update(plan["source_code_sha256"].values())
    learning_sources.update((plan["encoder"]["inventory_sha256"], sha(canonical(plan["contracts"]))))
    closure = sorted(learning_sources)
    heads = {}
    for seed in SEEDS:
        arm = result["arms"][f"head_seed_{seed}"]
        manifest_raw = read(f"head-seed-{seed}/manifest.json")
        owner_raw = read(f"head-seed-{seed}/replay_owner.json")
        weights = read(f"head-seed-{seed}/weights.npz")
        require(sha(manifest_raw) == arm["artifact"]["manifest_sha256"]
                and sha(weights) == arm["artifact"]["weights_file_sha256"]
                and sha(owner_raw) == arm["owner_manifest_sha256"] and arm["reload_bit_exact"] is True,
                "retained artifact/reload/owner pins")
        manifest, owner = json.loads(manifest_raw), json.loads(owner_raw)
        report = manifest["report"]
        require(owner["learned_source_digests"] == closure and owner["plan_sha256"] == expected_plan_sha256
                and owner["head_manifest_sha256"] == sha(manifest_raw)
                and owner["feature_identity"] == report["feature_identity"] == encoder["feature_identity"]
                and owner["authority"] == "DENY_ALL" and owner["mode"] == "SHADOW_ONLY",
                "complete learning ancestor closure and owner binding")
        require(manifest["schema"] == "hepta.cell-head-artifact.v1"
                and manifest["weights_file"] == "weights.npz" and manifest["weights_file_sha256"] == sha(weights)
                and report == arm["training"] and "evolution" not in report
                and report["schema"] == "hepta.trained-cell-task-head.v1"
                and report["authority"] == "DENY_ALL" and report["mode"] == "SHADOW_ONLY"
                and report["production_activation_allowed"] is False
                and report["encoder_training_steps"] == 0 and report["source_groups_disjoint"] is True
                and report["local_state_training"] == "zero_state_only"
                and report["calibration_target"] == "task_logits_only"
                and report["config"]["seed"] == seed and report["optimizer_steps"] == 200
                and all(report["config"][key] == plan["training"][key]
                        for key in ("mode", "steps", "learning_rate", "task_count",
                                    "confidence_threshold", "adapter_rank", "state_width"))
                and report["temperature"] == 0.25
                and report["initial_tensor_sha256"] != report["trained_tensor_sha256"]
                and report["changed_parameter_names"] == ["task_head.weight", "task_head.bias"],
                "original trained linear research profile")
        datasets = {}
        for split in ("train", "calibration", "development"):
            rows = [index for index, query in enumerate(queries) if query["split"] == split]
            cohort = report["splits"][split]
            require(cohort["source_record_digests"] == [encoder["source_record_digests"][index] for index in rows]
                    and cohort["source_group_sha256"] == sha(canonical([queries[index]["source_group_id"] for index in rows]))
                    and cohort["labels_sha256"] == sha(b"".join(struct.pack("<q", observed_labels[queries[index]["query_id"]])
                                                                for index in rows)),
                    "trained cohort differs from actual replay/Encoder sources")
            datasets[split] = sha(canonical({key: cohort[key] for key in (
                "bundle_digests", "labels_sha256", "source_group_sha256", "source_record_digests")}))
        tensors = verify_weights(weights, report)
        heads[seed] = {"original_manifest": manifest_raw, "manifest": manifest, "weights": weights,
                       "owner": owner, "owner_bytes": owner_raw, "datasets": datasets, "tensors": tensors}
    return {"plan": plan, "result": result, "queries": queries, "observed_labels": observed_labels,
            "encoder": encoder, "encoder_manifest_sha256": sha(encoder_raw), "features": features,
            "learning_ancestor_digests": closure, "heads": heads, "plan_sha256": expected_plan_sha256,
            "result_sha256": expected_result_sha256, "source_snapshot_sha256": sha(source_snapshot),
            "replay_sha256": sha(replay_raw)}
