"""Strict-as-of native stem reproducibility across two byte-pinned CI runs.

Read-only; no model execution, training, evaluation-target mutation, or
independent semantic citation adjudication. The second run only added a
label-free zero-offset null-choice diagnostic; it cannot alter policy answers.
"""

import argparse
from collections import Counter
import json
from pathlib import Path

EARLIER = (
    "675970bb610c70bb0ec30a2dee05c025440510e6",
    "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb",
    "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8",
    130,
)
LATER = (
    "95a20c4287bd6e9ab3fefd95774a2d9c8212d73f",
    "79500aab7bb63503dbd568381d00bdc81c8b9a93",
    "a3322c5dec5f0d2a7453e90a97095e746e206a01c102749b458e3ed816573cc6",
    133,
)
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
TIMED_ROW_FIELDS = {"head_seconds", "inclusive_attempt_seconds"}
TIMED_READER_FIELDS = {"generation_seconds", "incremental_generation_seconds"}


def require(condition, label):
    if not condition:
        raise ValueError(label)


def _key(row):
    return row["stage"], row["phase"], row["question_id"], row["arm"]


def compare_plan(old, new):
    """Only the generating SHA and new post-policy null probe may differ."""
    require(
        set(new) == set(old) | {"null_diagnostic"},
        "unregistered experimental configuration field changed",
    )
    require(
        old.get("source_commit") == EARLIER[0] and new.get("source_commit") == LATER[0],
        "unbound original generating source",
    )
    require(
        all(old[k] == new[k] for k in old if k != "source_commit"),
        "frozen dataset/model/cohort/Reader/curriculum config drift",
    )
    require(
        tuple(old["arms"]) == ARMS
        and tuple(old["curriculum_attempted_examples"]) == STAGES
        and all(len(old["questions"][phase]) == 8 for phase in PHASES)
        and len(old["questions"]["train"]) == 48,
        "original 80-task native curriculum changed",
    )
    require(
        "null" in new["null_diagnostic"].lower(),
        "new observation was not the declared null-only diagnostic",
    )


def compare_policy_pair(before, after):
    """Reject answer, source, input, weight, and caching changes; ignore clocks."""
    require(
        before["status"] == after["status"] == "succeeded",
        "not a complete original matched policy answer",
    )
    require(
        set(after) - set(before) == {"null_counterfactual"}
        and not (set(before) - set(after)),
        "unregistered policy observation or deleted original field",
    )
    require(
        all(
            before[field] == after[field]
            for field in before
            if field not in TIMED_ROW_FIELDS | {"receipt"}
        ),
        "original source choice, answer, Encoder/Head or pool changed",
    )
    original, current = before["receipt"], after["receipt"]
    require(
        set(original) == set(current)
        and all(
            original[field] == current[field]
            for field in original
            if field not in TIMED_READER_FIELDS
        ),
        "Reader input, model/prompt, generated tokens or cache reuse changed",
    )
    require(
        original["generator_parameter_updates"] == 0
        and original["semantic_citation_precision"] is None
        and original["production_accepted"] is False
        and len(original["delivered_evidence"]) == 1,
        "experimental Reader must remain frozen and source-bound",
    )
    null = after["null_counterfactual"]
    require(
        null["schema"] == "hepta.stem-label-free-null-counterfactual.v1"
        and null["observed_forced_top1_index"] == after["selected"]
        and null["original_forced_top1_unchanged"] is True
        and null["actual_reader_answer_not_recomputed"] is True
        and null["posthoc_labels_used_to_select_cutoff"] is False,
        "supplementary null observation modified actual policy answer",
    )


def _indexed(attempts, plan):
    expected = {
        (stage, phase, q, arm)
        for stage in STAGES
        for phase in PHASES
        for q in plan["questions"][phase]
        for arm in ARMS
    }
    observed = {}
    for row in attempts:
        k = _key(row)
        require(
            k in expected and k not in observed,
            "duplicate or unregistered original policy attempt",
        )
        observed[k] = row
    require(
        len(attempts) == 576 and set(observed) == expected,
        "incomplete original 576-case policy census",
    )
    return observed


def compare_adapters(original, current):
    require(
        set(original) == set(current) == {"receipts", "failures"}
        and original["failures"] == current["failures"] == {},
        "adapter train session unexpectedly failed",
    )
    require(
        set(original["receipts"])
        == set(current["receipts"])
        == {"lineage", "independent-general", "independent-temporal"},
        "missing source-bound LoRA receipt",
    )
    changed_allowed = {"reload_and_probe_seconds", "seconds", "admission_digest"}
    for key in original["receipts"]:
        a, b = original["receipts"][key], current["receipts"][key]
        require(
            set(a) == set(b)
            and all(a[k] == b[k] for k in a if k not in changed_allowed),
            "LoRA base-weight, actual source examples or fitted tensor changed",
        )
    return {
        key: len(row["prepared_questions"]) for key, row in current["receipts"].items()
    }


def audit_two_archives(a, b):
    """Inputs must be fully SHA-256-verified PinnedArchive instances."""
    for archive, (source, tree, _, members) in ((a, EARLIER), (b, LATER)):
        require(
            archive.read("tested-commit.txt").decode().strip() == source
            and archive.read("tested-tree.txt").decode().strip() == tree
            and archive.manifest_entries == members,
            "external generating commit/tree or manifest cardinality drift",
        )
    plan_a, plan_b = (
        a.json("comparison/preregistered.json"),
        b.json("comparison/preregistered.json"),
    )
    compare_plan(plan_a, plan_b)
    raw_a, raw_b = (
        _indexed(a.jsonl("comparison/policy-predictions.jsonl"), plan_a),
        _indexed(b.jsonl("comparison/policy-predictions.jsonl"), plan_b),
    )
    for k, old in raw_a.items():
        compare_policy_pair(old, raw_b[k])

    head_paths = {
        path
        for path in a.files
        if path.startswith("comparison/head-") and path.endswith(".json")
    }
    require(
        len(head_paths) == 36
        and head_paths.issubset(b.files)
        and all(a.read(name) == b.read(name) for name in head_paths),
        "persisted frozen/learned Head checkpoint bytes changed",
    )
    adapter_paths = {
        f"comparison/adapter-{n}/adapter.safetensors"
        for n in ("lineage", "independent-general", "independent-temporal")
    }
    require(
        adapter_paths.issubset(a.files)
        and adapter_paths.issubset(b.files)
        and all(a.read(f) == b.read(f) for f in adapter_paths),
        "stored differentiated LoRA tensor bytes changed",
    )
    static = (
        "comparison/training-dispositions.json",
        "comparison/feature-failures.json",
        "comparison/source-admission.json",
        "comparison/within-head-train-fit.json",
        "comparison/post-policy-native-source-ceiling.json",
        "comparison/reader-no-evidence-report.json",
        "comparison/reader-paired-no-evidence.json",
        "comparison/adapter-pair-opportunities.json",
    )
    require(
        all(a.read(path) == b.read(path) for path in static),
        "TRAIN, original source admission or fixed-Reader evidence changed",
    )
    counts = compare_adapters(
        a.json("comparison/adapter-training.json"),
        b.json("comparison/adapter-training.json"),
    )
    old_report, new_report = (
        a.json("comparison/report.json"),
        b.json("comparison/report.json"),
    )
    require(
        old_report["production_accepted"] is False
        and new_report["production_accepted"] is False
        and old_report["semantic_citation_precision"] is None
        and new_report["semantic_citation_precision"] is None
        and old_report["logical_policy_attempts"] == 576
        and new_report["logical_policy_attempts"] == 576,
        "experimental result improperly promoted to semantic or production success",
    )
    for metric in (
        "actual_attempts",
        "actual_successes",
        "actual_failed_attempts",
        "cache_hits",
    ):
        require(
            old_report["reader"][metric] == new_report["reader"][metric],
            "real frozen Reader invocation/cache count changed",
        )
    require(
        new_report["zero_offset_null_counterfactual"]["production_accepted"] is False
        and new_report["zero_offset_null_counterfactual"][
            "original_policy_counts_preserved"
        ]
        == 576,
        "new null diagnostic falsely changed Reader/policy output",
    )
    changes = Counter()
    paired_count = Counter()
    for stage in STAGES:
        for phase in PHASES:
            for qid in plan_a["questions"][phase]:
                frozen = raw_a[(stage, phase, qid, ARMS[0])]
                for arm in ARMS[1:]:
                    comparison = raw_a[(stage, phase, qid, arm)]
                    paired_count[arm] += 1
                    changes[arm] += frozen["selected"] != comparison["selected"]
    return dict(
        schema="hepta.stem-strict-two-run-repeatability.v1",
        run_sources=[EARLIER[0], LATER[0]],
        artifact_sha256=[a.sha256, b.sha256],
        verified_manifests=[a.manifest_entries, b.manifest_entries],
        exact_matched_source_and_answer_rows=len(raw_a),
        exact_reader_input_output_and_cache_receipts=len(raw_a),
        identical_head_checkpoints=len(head_paths),
        identical_lora_adapter_tensors=len(adapter_paths),
        unchanged_original_training_and_source_retrieval=True,
        only_new_instrumentation="label-free zero-offset null counterfactual",
        learned_per_arm={
            arm: dict(matched=paired_count[arm], changed_source=changes[arm])
            for arm in ARMS[1:]
        },
        matched_reader_actual_executions=new_report["reader"]["actual_attempts"],
        matched_reader_cache_hits=new_report["reader"]["cache_hits"],
        observed_unique_adapter_pairs=counts,
        no_new_model_executions_performed=True,
        answer_quality_or_semantic_citation_improvement_proven=False,
        production_accepted=False,
    )


def audit_pinned_paths(earlier, later):
    from stem_audit_archive import PinnedArchive

    a, b = PinnedArchive(Path(earlier), EARLIER[2]), None
    try:
        b = PinnedArchive(Path(later), LATER[2])
        return audit_two_archives(a, b)
    finally:
        a.close()
        if b is not None:
            b.close()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--earlier", type=Path, required=True)
    cli.add_argument("--later", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    result = audit_pinned_paths(args.earlier, args.later)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
