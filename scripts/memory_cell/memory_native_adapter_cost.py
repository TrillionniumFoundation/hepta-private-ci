#!/usr/bin/env python3
"""Reconcile saved LoRA tensors, original training time and zero measured gain.

Research-only: no model inference, optimizer, serving activation or TCO estimate.
Original ZIPs and their internal manifests are verified independently first.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import zipfile

from memory_parametric_behavior_audit import (
    ARCHIVES,
    MODEL_SHA,
    audit as answer_audit,
    digest,
    require,
    strict_json,
    verified_archive,
)


def positive(value, label):
    require(
        type(value) in (int, float)
        and math.isfinite(value)
        and 0 < value < 1_000_000_000,
        "nonpositive or unbounded " + label,
    )
    return value


def verify_adapter(z, prefix: str, original: dict) -> int:
    """Bind the original trained candidate to actual saved tensor/config bytes."""
    manifest_path = prefix + "/lineage.json"
    model_path = prefix + "/adapter_model.safetensors"
    config_path = prefix + "/adapter_config.json"
    source = strict_json(z.read(manifest_path))
    cfg = strict_json(z.read(config_path))
    training = original["training"]
    receipt = training["artifact_reload"]
    require(
        source.get("schema") == "hepta.memory-lora-candidate.v2"
        and source.get("base_identity") == MODEL_SHA
        and source.get("production_accepted") is False
        and source.get("model_install_authority") is False
        and source.get("scope") == receipt["scope"]
        and source.get("roots") == receipt["roots"] == training["roots"]
        and source.get("training")
        == {k: v for k, v in training.items() if k != "artifact_reload"}
        and digest(z.read(manifest_path)) == receipt["manifest_sha256"]
        and digest(z.read(config_path)) == source["config_sha256"]
        and digest(z.read(model_path)) == source["adapter_sha256"]
        and cfg.get("peft_type") == "LORA"
        and cfg.get("r") == 4
        and cfg.get("inference_mode") is True
        and set(cfg.get("target_modules", [])) == {"q_proj", "v_proj"},
        "trained parameter lineage/config/tensor bytes mismatch",
    )
    return z.getinfo(model_path).file_size


def measure_benchmark(path: Path, benchmark: str, *, proof=None) -> dict:
    """Read independently pinned model outputs and per-query adapter lineage."""
    original = verified_archive(path, benchmark) if proof is None else proof
    require(
        original["archived_zip_sha256"] == ARCHIVES[benchmark][0],
        "wrong benchmark proof",
    )
    learned = original["results"]["rag_lora"]
    param_only = original["results"]["parametric_only"]
    require(
        set(learned) == set(param_only) and len(learned) == 16,
        "incomplete paired original trained query census",
    )
    seconds = 0.0
    tokens = steps = storage = 0
    adapter_sizes = []
    delta_norms = []
    training_roots = Counter()
    with zipfile.ZipFile(path) as z:
        lineage_dirs = {
            name.rsplit("/", 1)[0]
            for name in z.namelist()
            if name.startswith(benchmark + "/lora-") and name.endswith("/lineage.json")
        }
        require(
            len(lineage_dirs) == 16, "incomplete independently saved adapter census"
        )
        lineage_index = {}
        for prefix in lineage_dirs:
            value = digest(z.read(prefix + "/lineage.json"))
            require(value not in lineage_index, "duplicate saved parameter lineage")
            lineage_index[value] = prefix
        used = set()
        for case_id in sorted(learned):
            row, reference = learned[case_id], param_only[case_id]
            training = row.get("training")
            require(
                isinstance(training, dict) and training == reference.get("training"),
                "two parameter arms disagree on original training receipt",
            )
            require(
                training.get("base_unchanged") is True
                and training.get("artifact_reload", {}).get("base_unchanged") is True
                and training.get("artifact_reload", {}).get("model_install_authority")
                is False
                and training.get("steps") == 4
                and training.get("trainable_parameters") == 230400
                and training.get("optimizer_tensor_bytes") == 1843680
                and isinstance(training.get("losses"), list)
                and len(training["losses"]) == 4
                and all(
                    type(v) in (int, float) and math.isfinite(v)
                    for v in training["losses"]
                ),
                "invalid original four-step candidate training receipt",
            )
            delta_norms.append(
                positive(training["adapter_delta_squared_norm"], "parameter delta")
            )
            seconds += positive(training["train_seconds"], "observed training seconds")
            tokens += positive(training["tokens"], "original training tokens")
            steps += training["steps"]
            receipt = training["artifact_reload"]["manifest_sha256"]
            require(
                receipt in lineage_index and receipt not in used,
                "missing or reused trained adapter lineage",
            )
            used.add(receipt)
            nbytes = verify_adapter(z, lineage_index[receipt], row)
            adapter_sizes.append(nbytes)
            storage += nbytes
            for root in training["roots"]:
                training_roots[root] += 1
        require(
            len(used) == len(lineage_dirs) == 16,
            "orphan or missing saved parameter adapter",
        )
        require(
            all(v == adapter_sizes[0] for v in adapter_sizes),
            "original parameter artifact layout drift",
        )
    return dict(
        benchmark=benchmark,
        actual_training_tasks=16,
        actual_optimizer_steps=steps,
        input_training_tokens=tokens,
        measured_training_elapsed_seconds_sum=seconds,
        saved_adapter_tensor_count=16,
        saved_adapter_tensor_bytes=storage,
        saved_tensor_bytes_per_adapter=adapter_sizes[0],
        trainable_parameters_per_adapter=230400,
        optimizer_state_bytes_per_training_instance=1843680,
        max_trainable_delta_norm_squared=max(delta_norms),
        min_trainable_delta_norm_squared=min(delta_norms),
        original_training_root_proxies=len(training_roots),
        observed_training_time_is_sum_not_wall_clock=True,
        optimizer_state_bytes_are_not_necessarily_simultaneous_residency=True,
        saved_tensor_bytes_exclude_index_and_raw_source_storage=True,
        production_qualified=False,
    )


def audit(paths: dict[str, Path]) -> dict:
    require(set(paths) == set(ARCHIVES), "exact original source archives required")
    # The original answer-only audit verifies the entire archive and 64 matched
    # parameter comparisons first; never use an unsourced success claim.
    answer = answer_audit(paths)
    require(
        answer["paired_parametric_comparisons"] == 64
        and answer["paired_parametric_answers_changed"] == 1,
        "historical answer-delta census drift",
    )
    pairs = [
        answer["per_benchmark"][benchmark]["comparisons"][contrast]
        for benchmark in ARCHIVES
        for contrast in ("no_memory_vs_parametric_only", "rag_vs_rag_lora")
    ]
    scored_wins = sum(item["f1_wins"] for item in pairs)
    scored_pairs = sum(item["paired_f1_scored"] for item in pairs)
    unscored_pairs = sum(item["paired_f1_unscored"] for item in pairs)
    require(
        scored_wins == 0 and scored_pairs == 56 and unscored_pairs == 8,
        "historical diagnostic answer benefit census drift",
    )
    result = {key: measure_benchmark(paths[key], key) for key in ARCHIVES}
    seconds = sum(v["measured_training_elapsed_seconds_sum"] for v in result.values())
    storage = sum(v["saved_adapter_tensor_bytes"] for v in result.values())
    return dict(
        schema="hepta.memory.original-native-parameter-resource-nopromotion.v1",
        original_model_calls=answer["original_real_model_calls"],
        original_github_run_id=answer["original_github_run_id"],
        original_generating_source=answer["generating_source_sha"],
        original_archive_sha256={k: ARCHIVES[k][0] for k in ARCHIVES},
        benchmark_resources=result,
        trained_adapter_instances=32,
        original_optimizer_steps=sum(
            v["actual_optimizer_steps"] for v in result.values()
        ),
        measured_training_seconds_sum=seconds,
        original_training_tokens=sum(
            v["input_training_tokens"] for v in result.values()
        ),
        original_saved_adapter_tensor_bytes=storage,
        paired_original_parameter_results=64,
        original_parameter_answer_strings_identical=answer[
            "paired_parametric_answers_exactly_identical"
        ],
        original_parameter_answer_strings_changed=answer[
            "paired_parametric_answers_changed"
        ],
        original_parameter_f1_scored_pairs=scored_pairs,
        original_parameter_f1_unscored_pairs=unscored_pairs,
        scored_f1_positive_parameter_wins=scored_wins,
        cost_per_incremental_scored_win=None,
        actual_production_total_cost=None,
        missing_cost_terms=[
            "raw_source_retention",
            "indexing",
            "maintenance",
            "revocation",
            "rollback",
            "recovery",
            "storage_duration",
            "cross_node_communication",
        ],
        complete_total_cost_benefit_established=False,
        independent_future_source_families=0,
        independent_human_semantic_citation_review=False,
        new_model_calls=0,
        training_executed_by_this_auditor=False,
        learned_parameter_promotion_allowed=False,
        production_qualified=False,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--locomo", type=Path, required=True)
    p.add_argument("--longmemeval", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    output = audit({"locomo": args.locomo, "longmemeval": args.longmemeval})
    require(
        not args.output.exists() and not args.output.is_symlink(),
        "refuse overwriting immutable resource receipt",
    )
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(
            output, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        f.write("\n")
    print(
        json.dumps(
            dict(
                training_tasks=32,
                train_seconds=output["measured_training_seconds_sum"],
                saved_parameter_bytes=output["original_saved_adapter_tensor_bytes"],
                production_qualified=False,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
