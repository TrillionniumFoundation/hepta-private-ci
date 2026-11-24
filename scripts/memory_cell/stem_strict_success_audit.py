"""Independent, byte-pinned audit of the completed strict-as-of six-arm run.

No new Reader, Encoder, retrieval or training. Archive integrity and original
model/Reader receipts are verified; native weak-document support is NOT a
semantic entailment judgment or a production adoption certificate.
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path

from stem_audit_archive import PinnedArchive, require

SOURCE = "675970bb610c70bb0ec30a2dee05c025440510e6"
TREE = "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb"
ZIP_SHA256 = "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
CELLS = ("general", "temporal")


def audit_records(plan, raw, scored, report, fit, ceiling, no_evidence, chronology):
    cohorts = plan["questions"]
    registered = [qid for questions in cohorts.values() for qid in questions]
    require(
        plan["source_commit"] == SOURCE
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1"
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["cells"]) == CELLS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and set(cohorts) == {"train", *PHASES}
        and len(cohorts["train"]) == 48
        and all(len(cohorts[phase]) == 8 for phase in PHASES)
        and len(set(registered)) == len(registered) == 80,
        "changed source, model, chronology or native question registration",
    )
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in cohorts[phase]
        for arm in ARMS
    }
    require(
        len(expected) == len(raw) == len(scored) == 576,
        "missing or fabricated original 576-arm execution census",
    )

    def key(row):
        return row["stage"], row["phase"], row["question_id"], row["arm"]

    raw_by_key = {}
    for row in raw:
        k = key(row)
        require(
            k in expected
            and k not in raw_by_key
            and row["status"] == "succeeded"
            and type(row.get("selected")) is int
            and isinstance(row.get("answer"), str)
            and bool(row["answer"].strip())
            and isinstance(row.get("receipt"), dict)
            and row["receipt"]["observable_query"]["identity"] == row["question_id"]
            and row["receipt"]["generator_identity"]
            and row["receipt"]["generator_profile"]
            and len(row["receipt"]["delivered_evidence"]) == 1,
            "missing, altered or detached actual strict Reader prediction",
        )
        raw_by_key[k] = row
    scored_by_key = {}
    for row in scored:
        k = key(row)
        original = raw_by_key.get(k)
        require(
            original is not None
            and k not in scored_by_key
            and all(
                original[f] == row[f]
                for f in (
                    "status",
                    "answer",
                    "selected",
                    "receipt",
                    "pool_digest",
                    "feature_digest",
                    "head_sha256",
                    "encoder_identity",
                    "family",
                    "cell",
                )
            )
            and row["citation_structure"]["semantic_precision"] is None,
            "post-generation native scoring changed original policy answer",
        )
        scored_by_key[k] = row
    require(
        set(raw_by_key) == set(scored_by_key) == expected,
        "a real registered Reader attempt is missing",
    )
    require(
        report["census"] == {"planned": 576, "recorded": 576, "complete": True}
        and report["logical_policy_attempts"] == 576
        and report["semantic_citation_precision"] is None
        and report["production_accepted"] is False,
        "successfully executed experimental data cannot assert production qualification",
    )

    expected_fit = {
        (stage, arm, cell) for stage in STAGES for arm in ARMS[1:] for cell in CELLS
    }
    by_fit = {}
    learning = {(x["stage"], x["arm"], x["cell"]): x for x in report["learning"]}
    require(
        len(learning) == 36
        and all(x["status"] == "succeeded" for x in learning.values()),
        "all 36 original Head/checkpoint sessions are required",
    )
    for row in fit["checkpoints"]:
        k = row["checkpoint"], row["arm"], row["cell"]
        old = learning.get(k)
        require(
            k in expected_fit
            and k not in by_fit
            and old is not None
            and row["schema"] == "hepta.stem-head-within-train-fit.v2"
            and row["previous_head_sha256"] == old["before_sha256"]
            and row["updated_head_sha256"] == old["after_sha256"]
            and row["heldout_annotations_consulted"] is False
            and row["production_accepted"] is False
            and row["independent_generalization_established"] is False
            and len(row["rows"]) == row["matched_training_rows"]
            and row["matched_training_rows"] > 0,
            "unbound fitted Head snapshot or leaked held-out TRAIN diagnosis",
        )
        observed = row["rows"]
        require(
            sum(x["selected_source_changed"] for x in observed)
            == row["changed_train_top1_rows"],
            "trained top1 census drift",
        )
        for label, field in (
            ("before", "original_weak_loss"),
            ("after", "updated_weak_loss"),
        ):
            recalculated = math.fsum(x[field] for x in observed) / len(observed)
            require(
                math.isclose(
                    recalculated, row["mean_weak_loss_" + label], abs_tol=1e-7
                ),
                "saved training loss is not reproducible",
            )
        by_fit[k] = row
    require(set(by_fit) == expected_fit, "all 30 Head before/after fits required")
    fitted = {}
    for stage in STAGES:
        for arm in ARMS[1:]:
            xs = [by_fit[(stage, arm, c)] for c in CELLS]
            n = sum(x["matched_training_rows"] for x in xs)
            fitted[f"{stage}/{arm}"] = dict(
                measured_original_train_rows=n,
                weighted_mean_loss_delta=math.fsum(
                    x["mean_weak_loss_delta"] * x["matched_training_rows"] for x in xs
                )
                / n,
                train_top1_changed=sum(x["changed_train_top1_rows"] for x in xs),
                weak_native_support_top1_gains=sum(
                    x["weak_source_top1_gains"] for x in xs
                ),
                readout_fitting_not_task_generalization=True,
            )

    original_ceiling = {}
    for row in ceiling["decisions"]:
        k = row["phase"], row["question_id"]
        require(
            k not in original_ceiling and k[0] in PHASES and k[1] in cohorts[k[0]],
            "post-policy source-label census drift",
        )
        original_ceiling[k] = row
    require(
        len(original_ceiling) == 32 and ceiling["production_accepted"] is False,
        "32 unique source ceiling rows required",
    )
    require(
        set(ceiling["phases"]) == set(PHASES),
        "missing post-policy source-phase accounting",
    )
    checks = {
        "attempted": lambda row: True,
        "native_source_resolved": lambda row: row["weak_native_support_resolved"],
        "native_unanswerable": lambda row: row["native_source_unanswerable"],
        "native_unresolved_support": lambda row: row["unresolved_native_support"],
        "candidate_pool_missing": lambda row: not row["candidate_pool_available"],
        "support_available_within_pool": lambda row: (
            row["native_support_available_in_pool"] is True
        ),
        "frozen_correct_source_choices": lambda row: (
            row["frozen_selected_native_support"] is True
        ),
        "frozen_missed_available_support": lambda row: (
            row["missed_native_support_within_pool"] is True
        ),
        "frozen_not_chosen_or_unobserved": lambda row: (
            row["frozen_selected_native_support"] is None
        ),
        "frozen_reader_failed": lambda row: (
            not row["frozen_reader_execution_succeeded"]
        ),
    }
    for phase in PHASES:
        subset = [row for (p, _), row in original_ceiling.items() if p == phase]
        for metric, predicate in checks.items():
            require(
                sum(bool(predicate(row)) for row in subset)
                == ceiling["phases"][phase][metric],
                "reported frozen source ceiling differs from its original rows",
            )
        missed = sum(
            row["native_support_available_in_pool"] is False
            for row in subset
            if row["weak_native_support_resolved"] and row["candidate_pool_available"]
        )
        require(
            missed == ceiling["phases"][phase]["support_missing_from_pool"],
            "source retrieval miss count was not rederived",
        )
    for (phase, qid), row in original_ceiling.items():
        original = raw_by_key[(48, phase, qid, "frozen_rerank")]
        require(
            row["frozen_reader_execution_succeeded"] is True
            and row["candidate_pool_available"] is True
            and row["candidate_count"]
            == original["selection_geometry"]["candidate_count"],
            "post-policy source ceiling became detached from frozen execution",
        )
        if (
            row["weak_native_support_resolved"]
            and not row["native_source_unanswerable"]
        ):
            observed = scored_by_key[(48, phase, qid, "frozen_rerank")][
                "source_choice_correct"
            ]
            require(
                type(observed) is int
                and observed in (0, 1)
                and row["frozen_selected_native_support"] is bool(observed),
                "original scored support and independent source ceiling disagree",
            )

    effects, changed_rows = {}, []
    for arm in ARMS[1:]:
        flips = answer_changes = weak_support_gains = weak_support_losses = 0
        test_transfer_flips = 0
        for stage in STAGES:
            for phase in PHASES:
                for qid in cohorts[phase]:
                    first = raw_by_key[(stage, phase, qid, "frozen_rerank")]
                    second = raw_by_key[(stage, phase, qid, arm)]
                    scored_first = scored_by_key[(stage, phase, qid, "frozen_rerank")]
                    scored_second = scored_by_key[(stage, phase, qid, arm)]
                    require(
                        first["pool_digest"] == second["pool_digest"]
                        and first["family"] == second["family"]
                        and first["cell"] == second["cell"]
                        and first["receipt"]["generator_identity"]
                        == second["receipt"]["generator_identity"]
                        and first["receipt"]["generator_profile"]
                        == second["receipt"]["generator_profile"],
                        "frozen matched source pool, Cell or Reader changed",
                    )
                    flipped = first["selected"] != second["selected"]
                    answer_changed = first["answer"] != second["answer"]
                    flips += flipped
                    answer_changes += answer_changed
                    test_transfer_flips += flipped and phase in ("test", "transfer")
                    label = original_ceiling[(phase, qid)]
                    if (
                        label["weak_native_support_resolved"]
                        and not label["native_source_unanswerable"]
                    ):
                        a = scored_first["source_choice_correct"]
                        b = scored_second["source_choice_correct"]
                        require(
                            type(a) is int and type(b) is int,
                            "resolved native source support was not scored",
                        )
                        weak_support_gains += b > a
                        weak_support_losses += b < a
                    if flipped:
                        changed_rows.append(
                            dict(
                                arm=arm,
                                stage=stage,
                                phase=phase,
                                question_id=qid,
                                before_weak_source=scored_first[
                                    "source_choice_correct"
                                ],
                                after_weak_source=scored_second[
                                    "source_choice_correct"
                                ],
                                changed_answer_bytes=answer_changed,
                            )
                        )
        effects[arm] = dict(
            matched_policy_attempts=96,
            changed_selected_source=flips,
            changed_answer_bytes=answer_changes,
            observed_native_document_support_gains=weak_support_gains,
            observed_native_document_support_losses=weak_support_losses,
            test_transfer_top1_changes=test_transfer_flips,
            independent_task_superiority=False,
        )
    reader = report["reader"]
    isolated = report["no_evidence_reader_call_accounting"][
        "isolated_no_evidence_reader"
    ]
    require(
        reader["actual_attempts"] == reader["actual_successes"]
        and reader["actual_failed_attempts"] == 0
        and reader["cache_hits"]
        == sum(x["receipt"]["actual_reader_execution"] is False for x in raw)
        and isolated["actual_successes"] == 32
        and isolated["actual_failed_attempts"] == 0
        and no_evidence["matched_pairs"] == 32,
        "fixed Reader execution/cached calls/isolated controls drifted",
    )
    metric_rows = report["metrics"]
    require(
        len(metric_rows) == 72
        and sum(x["attempted"] for x in metric_rows.values()) == 576,
        "incomplete metrics beyond raw 576-policy rows",
    )
    require(
        chronology["datasets"]["longmemeval"]["unknown"] == 0,
        "unsupported current native timestamp history",
    )
    return dict(
        schema="hepta.stem-strict-native-immutable-audit.v1",
        generating_source=SOURCE,
        generating_tree=TREE,
        original_policy_attempts=576,
        original_policy_succeeded=576,
        learned_vs_frozen=effects,
        changed_source_rows=changed_rows,
        original_measured_head_fit=fitted,
        post_answer_source_ceiling=ceiling["phases"],
        original_reader_actual_executions=reader["actual_attempts"],
        original_reader_cache_hits=reader["cache_hits"],
        isolated_no_evidence_reader_calls=isolated["actual_attempts"],
        emitted_citation_markers=sum(
            x["emitted_citation_markers"] for x in metric_rows.values()
        ),
        native_longmemeval_future_time_pairs=chronology["datasets"]["longmemeval"][
            "future"
        ],
        heldout_family_independence_authenticated=False,
        semantic_citation_precision=None,
        pretrained_task_superiority_established=False,
        new_model_executions_performed=0,
        production_accepted=False,
    )


def audit_archive(path):
    archive = PinnedArchive(path, ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "frozen ZIP generated commit/tree mismatch",
        )
        result = audit_records(
            archive.json("comparison/preregistered.json"),
            archive.jsonl("comparison/policy-predictions.jsonl"),
            archive.json("comparison/scored-policy-attempts.json"),
            archive.json("comparison/report.json"),
            archive.json("comparison/within-head-train-fit.json"),
            archive.json("comparison/post-policy-native-source-ceiling.json"),
            archive.json("comparison/reader-paired-no-evidence.json"),
            archive.json("chronology.json"),
        )
        result.update(
            archive_sha256=archive.sha256,
            verified_member_digests=archive.manifest_entries,
        )
        return result
    finally:
        archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = audit_archive(args.archive)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps(summary, ensure_ascii=False))
