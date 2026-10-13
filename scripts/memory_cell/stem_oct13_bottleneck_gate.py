"""Immutable strict Stem bottleneck gate; no model training or gold-score tuning.

Report evidence capacity, training dynamics and qualified task gains as
separate observed quantities. Read-only, research-only and non-promoting.
"""

from collections import Counter
import argparse
import json
from pathlib import Path

SOURCE = "30bf3379c61d7140acf01113e000a100c29ff18b"
TREE = "d42d0457f979986a194edd65173b49fa5a7d98f1"
ZIP_SHA256 = "4d909737769b2c4ee146ec571499276dd911542d5b20b29c9adb1f5a4477a1f9"
ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def assess(plan, raw, report, ceiling, fit, paired, effective):
    """Pure receipt analysis on the original registered questions, never labels."""
    questions = plan["questions"]
    ids = [qid for phase in ("train", *PHASES) for qid in questions[phase]]
    require(plan["source_commit"] == SOURCE
            and plan["source_visibility_policy"] ==
            "strict-as-of-before-index-and-every-Encoder-v1"
            and tuple(plan["arms"]) == ARMS
            and tuple(plan["curriculum_attempted_examples"]) == STAGES
            and len(ids) == len(set(ids)) == 80
            and len(questions["train"]) == 48
            and all(len(questions[p]) == 8 for p in PHASES),
            "original fixed native registration changed")
    expected = {(stage, phase, qid, arm)
                for stage in STAGES for phase in PHASES
                for qid in questions[phase] for arm in ARMS}
    indexed = {}
    for row in raw:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        require(key in expected and key not in indexed
                and row["status"] == "succeeded" and "selected" in row
                and isinstance(row.get("receipt"), dict)
                and row["receipt"].get("production_accepted") is False,
                "lost, duplicate or unqualified original policy output")
        indexed[key] = row
    require(len(raw) == len(indexed) == len(expected) == 576
            and report["logical_policy_attempts"] == 576
            and report["production_accepted"] is False
            and report["semantic_citation_precision"] is None,
            "full original strict matrix not proven")
    paired_out = {}
    for arm in ARMS[1:]:
        counts = Counter()
        for phase in ("test", "transfer"):
            for qid in questions[phase]:
                old = indexed[48, phase, qid, ARMS[0]]
                new = indexed[48, phase, qid, arm]
                require(old["family"] == new["family"]
                        and old["cell"] == new["cell"]
                        and old["pool_digest"] == new["pool_digest"]
                        and old["receipt"]["generator_identity"] == new["receipt"]["generator_identity"]
                        and old["receipt"]["generator_profile"] == new["receipt"]["generator_profile"]
                        and old["receipt"]["observable_query"] == new["receipt"]["observable_query"],
                        "Reader, question, Cell or pool not matched")
                if (old["selected"] == new["selected"]
                        and old["receipt"]["delivered_evidence"] !=
                        new["receipt"]["delivered_evidence"]):
                    raise ValueError("same selected source has unmatched Reader evidence")
                counts["planned_unique_questions"] += 1
                counts["changed_source_top1"] += old["selected"] != new["selected"]
                counts["changed_answer_bytes"] += old["answer"] != new["answer"]
                counts["changed_delivered_source"] += (
                    old["receipt"]["delivered_evidence"] !=
                    new["receipt"]["delivered_evidence"]
                )
        require(counts["planned_unique_questions"] == 16,
                "final checkpoint must have 16 unique test and transfer questions")
        paired_out[arm] = dict(counts, independent_generalization_established=False)
    stage_fit = fit["checkpoints"]
    require(len(stage_fit) == 30, "all five trainable arms x two Cell x three stages required")
    unique = set()
    dynamics = {"general": {}, "temporal": {}}
    for row in stage_fit:
        key = (row["checkpoint"], row["arm"], row["cell"])
        require(key not in unique and key[0] in STAGES and key[1] in ARMS[1:]
                and key[2] in dynamics and row["production_accepted"] is False,
                "duplicate, fabricated or promoted Head fit")
        unique.add(key)
        if key[0] == 48:
            dynamics[key[2]][key[1]] = dict(
                weak_loss_delta=row["mean_weak_loss_delta"],
                weak_source_top1_gains=row["weak_source_top1_gains"],
                weak_candidate_margin_delta=row["mean_positive_over_negative_candidate_margin_delta"],
                matched_training_rows=row["matched_training_rows"],
            )
    require(len(dynamics["general"]) == len(dynamics["temporal"]) == 5,
            "missing final Head fit of a Cell")
    require(ceiling["final_checkpoint"] == 48
            and ceiling["after_all_policy_answers"] is True
            and ceiling["production_accepted"] is False,
            "source ceiling must be post-policy and nonpromoting")
    pool = {}
    for phase in ("test", "transfer"):
        row = ceiling["phases"][phase]
        require(row["attempted"] == 8
                and row["candidate_pool_missing"] == 0
                and row["native_source_resolved"] + row["native_unanswerable"]
                    + row["native_unresolved_support"] == 8
                and row["support_available_within_pool"]
                    == row["frozen_correct_source_choices"]
                    + row["frozen_missed_available_support"]
                and row["native_source_resolved"]
                    == row["support_available_within_pool"]
                    + row["support_missing_from_pool"],
                "weak document support accounting or original pool drift")
        pool[phase] = {key: row[key] for key in (
            "attempted", "native_source_resolved", "native_unanswerable",
            "support_available_within_pool", "support_missing_from_pool",
            "frozen_correct_source_choices", "frozen_missed_available_support",
        )}
    require(effective["independent_question_ids_per_arm"] == 16
            and effective["repeated_question_evaluations_per_arm"] == 48
            and effective["source_family_sampling_independence_certified"] is False,
            "three repeated checkpoints are not 48 independent subjects")
    metrics = report["metrics"]
    require(len(metrics) == 72 and all(x["attempted"] == x["succeeded"] == 8
                                       and x["failed"] == 0 for x in metrics.values()),
            "strict original Reader output census changed")
    citation_markers = sum(x["emitted_citation_markers"] for x in metrics.values())
    require(paired["matched_pairs"] == 32 and paired["production_accepted"] is False,
            "nonlearning Reader baseline missing or promoted")
    return dict(
        schema="hepta.memory-cell.strict-oct13-bottleneck-gate.v1",
        original_source=SOURCE, stage_48_is_primary=True,
        original_policy_attempts=576, original_successes=576,
        unique_test_transfer_questions=16,
        repeated_checkpoints_not_independent_subjects=True,
        effective_independent_source_families_certified=False,
        test_transfer_native_weak_source_coverage=pool,
        combined_weak_answerable_cases=sum(x["native_source_resolved"] for x in pool.values()),
        missing_from_candidate_pool=sum(x["support_missing_from_pool"] for x in pool.values()),
        inside_pool_but_wrong_frozen_top1=sum(x["frozen_missed_available_support"] for x in pool.values()),
        already_selected_weak_native_support=sum(x["frozen_correct_source_choices"] for x in pool.values()),
        fixed_candidate_head_cannot_recover_unretrieved_source=True,
        learned_vs_frozen=paired_out,
        actual_final_head_training_dynamics=dynamics,
        frozen_reader_vs_no_evidence={phase: dict(
            attempted=paired["per_phase"][phase]["attempted"],
            paired_answer_f1_delta_mean=paired["per_phase"][phase]["paired_diagnostic_delta_mean"],
            all_planned_answer_delta_bounds=paired["per_phase"][phase]["all_planned_answer_delta_bounds"],
        ) for phase in ("test", "transfer")},
        original_citation_markers=citation_markers,
        native_document_support_is_not_independent_window_entailment=True,
        pretrained_training_fit_is_not_heldout_gain=True,
        semantic_citation_precision=None,
        measured_new_prospective_independent_window=False,
        additional_cells_or_production_scaleout_qualified=False,
        production_accepted=False,
    )


def audit_zip(path):
    from stem_audit_archive import PinnedArchive, require as archive_require
    archive = PinnedArchive(Path(path), ZIP_SHA256)
    try:
        archive_require(archive.read("tested-commit.txt").decode().strip() == SOURCE,
                        "generating source pin drift")
        archive_require(archive.read("tested-tree.txt").decode().strip() == TREE,
                        "generating tree pin drift")
        result = assess(
            archive.json("comparison/preregistered.json"),
            archive.jsonl("comparison/policy-predictions.jsonl"),
            archive.json("comparison/report.json"),
            archive.json("comparison/post-policy-native-source-ceiling.json"),
            archive.json("comparison/within-head-train-fit.json"),
            archive.json("comparison/reader-paired-no-evidence.json"),
            archive.json("comparison/report.json")["effective_heldout_subjects"],
        )
        result.update(
            original_zip_sha256=archive.sha256,
            verified_internal_manifest_entries=archive.manifest_entries,
            immutable_original_model_source=True,
        )
        return result
    finally:
        archive.close()



LATER_SOURCE = "aa2dd9875b811292566c09b282f74d4a0bf8e7eb"
LATER_TREE = "8a156b8e7684d5fdea8521152b421d686238cb47"
LATER_ZIP_SHA256 = "b4169dc496e5c6097fdfc41c082f123eb325c28e5d7b68485b1801ede1e0726c"
STEM_SOURCE_BYTES = (
    "source/stem_cell.py", "source/stem_cell_trial.py",
    "source/stem_cell_adapter.py", "source/stem_cell_geometry.py",
    "source/stem_head_fit_dynamics.py", "source/stem_cell_temporal.py",
)


def compare_repeatability(original, later):
    """Behavior-level repeatability does NOT imply bitwise training identity."""
    require(original.json("comparison/preregistered.json")["questions"] ==
            later.json("comparison/preregistered.json")["questions"],
            "the two native cohorts are not the same")
    for name in STEM_SOURCE_BYTES:
        require(original.read(name) == later.read(name),
                "core Stem executable source changed: " + name)
    rows = []
    for archive in (original, later):
        rows.append({
            (r["stage"], r["phase"], r["question_id"], r["arm"]): r
            for r in archive.jsonl("comparison/policy-predictions.jsonl")
        })
    require(len(rows[0]) == len(rows[1]) == 576
            and set(rows[0]) == set(rows[1]), "incomplete repeated native census")
    result = Counter()
    for key, a in rows[0].items():
        b = rows[1][key]
        require(a["status"] == b["status"] == "succeeded"
                and a["pool_digest"] == b["pool_digest"]
                and a["family"] == b["family"],
                "repeated native question or candidate pool drift")
        for f in ("generator_identity", "generator_profile",
                  "input_ids_digest", "generated_ids_digest",
                  "canonical_request_digest", "delivered_evidence"):
            require(a["receipt"][f] == b["receipt"][f],
                    "repeated frozen Reader input/output changed: " + f)
        result["compared_policy_attempts"] += 1
        result["changed_top1"] += a["selected"] != b["selected"]
        result["changed_raw_answers"] += a["answer"] != b["answer"]
        result["changed_feature_digests"] += a["feature_digest"] != b["feature_digest"]
        result["changed_head_sha256"] += a["head_sha256"] != b["head_sha256"]
        result["changed_encoder_identity"] += a["encoder_identity"] != b["encoder_identity"]
    head_paths = [name for name in original.files
                  if name.startswith("comparison/head-") and name.endswith(".json")]
    require(len(head_paths) == 36 and set(head_paths) <= later.files,
            "missing persisted Head snapshot")

    def flatten(values):
        if isinstance(values, list):
            for item in values:
                yield from flatten(item)
        else:
            yield values

    numeric = Counter()
    max_abs_delta = 0.0
    for path in sorted(head_paths):
        a = original.json(path)["state"]
        b = later.json(path)["state"]
        require(set(a) == set(b), "Head state tensor keys changed")
        for name in a:
            before, after = list(flatten(a[name])), list(flatten(b[name]))
            require(len(before) == len(after), "Head tensor shape changed")
            for x, y in zip(before, after, strict=True):
                require(type(x) in (int, float) and type(y) in (int, float),
                        "non-numeric Head tensor scalar")
                delta = abs(x - y)
                require(delta < float("inf"), "nonfinite Head tensor difference")
                numeric["compared_float_values"] += 1
                numeric["changed_float_values"] += x != y
                max_abs_delta = max(max_abs_delta, delta)
    adapter_diff = sum(
        original.read("comparison/adapter-" + route + "/adapter.safetensors")
        != later.read("comparison/adapter-" + route + "/adapter.safetensors")
        for route in ("lineage", "independent-general", "independent-temporal")
    )
    return dict(
        schema="hepta.memory-cell.strict-oct13-repeatability.v1",
        earlier_generating_commit=SOURCE,
        later_generating_commit=LATER_SOURCE,
        all_six_core_source_files_byte_identical=True,
        repeated_original_reader_decisions=dict(result),
        repeated_head_weights=dict(numeric),
        maximum_absolute_float_head_difference=max_abs_delta,
        changed_adapter_binary_files=adapter_diff,
        repeated_answers_are_not_independent_test_subjects=True,
        bitwise_training_reproducibility_established=(
            numeric["changed_float_values"] == 0 and adapter_diff == 0
        ),
        unchanged_reader_outcomes_do_not_prove_learning=True,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def audit_later_pair(original_path, later_path):
    from stem_audit_archive import PinnedArchive
    before = PinnedArchive(Path(original_path), ZIP_SHA256)
    try:
        after = PinnedArchive(Path(later_path), LATER_ZIP_SHA256)
        try:
            require(before.read("tested-commit.txt").decode().strip() == SOURCE
                    and before.read("tested-tree.txt").decode().strip() == TREE,
                    "earlier provenance pin changed")
            require(after.read("tested-commit.txt").decode().strip() == LATER_SOURCE
                    and after.read("tested-tree.txt").decode().strip() == LATER_TREE,
                    "later provenance pin changed")
            report = compare_repeatability(before, after)
            report["earlier_zip_sha256"] = before.sha256
            report["later_zip_sha256"] = after.sha256
            report["earlier_manifest_members"] = before.manifest_entries
            report["later_manifest_members"] = after.manifest_entries
            return report
        finally:
            after.close()
    finally:
        before.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--later", type=Path, default=None)
    args = p.parse_args()
    out = audit_zip(args.archive)
    if args.later is not None:
        out["source_unchanged_repeatability"] = audit_later_pair(
            args.archive, args.later
        )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(out, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(out, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
