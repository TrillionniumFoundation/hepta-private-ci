"""Byte-pinned, read-only audit of three successful native Stem model runs.

Never infer parameter reproducibility from identical Reader answers. Never treat
completion, weak native source labels, or absent citation marks as acceptance.
Uses archived original answers; it performs zero new model inference.
"""
import argparse
import json
import math
from pathlib import Path

from stem_audit_archive import PinnedArchive, require

PINS = {
    "38114107704": (
        "434581a0e2475341253c74dcfa7c609dd8fd6492",
        "d6e53463c33d2750a827b82fc71b114c63c56501",
        "a45c4b397b573662715a45f80bfc118446e41f6ceedf88052188bbfd9d131ca5",
    ),
    "38114504922": (
        "d2c2f97568b6e6d075011cb52acbef9f659837bc",
        "8062b1155b33809aa370f0dd92f820d100a412f2",
        "2728ff0f9ef7eef01cf8a3d8ee99dc16600265ffd7ac5a4740baebe46d874ec5",
    ),
    "38114716982": (
        "675970bb610c70bb0ec30a2dee05c025440510e6",
        "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb",
        "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8",
    ),
}
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank", "prototype", "linear", "gated",
    "lineage_lora_gated", "independent_lora_gated",
)
CELLS = ("general", "temporal")
REGISTRATION = (
    "questions", "dataset_sha256", "arms", "cells", "routes",
    "question_families", "families", "head_rank", "head_optimizer",
    "window_budget", "reader_inventory", "retriever_inventory",
    "ranker_inventory", "generator_config", "generator_template_digest",
    "primary_policy", "source_visibility_policy",
)
MODEL_FIELDS = (
    "status", "selected", "answer", "pool_digest",
)
READER_FIELDS = (
    "generator_identity", "generator_profile", "input_ids_digest",
    "generated_ids_digest", "canonical_request_digest", "delivered_evidence",
)
LATENT_FIELDS = (
    "feature_digest", "encoder_identity", "head_sha256", "selection_geometry",
)


def _index(plan, rows, report):
    require(tuple(plan["arms"]) == ARMS and tuple(plan["cells"]) == CELLS,
            "changed native arm/Cell registration")
    require(tuple(plan["curriculum_attempted_examples"]) == STAGES,
            "changed native checkpoints")
    require(len(plan["questions"]["train"]) == 48 and all(
        len(plan["questions"][phase]) == 8 for phase in PHASES
    ), "changed 80-question curriculum")
    known = [q for group in plan["questions"].values() for q in group]
    require(len(known) == len(set(known)) == 80, "duplicate registered question")
    expected = {
        (stage, phase, qid, arm) for stage in STAGES for phase in PHASES
        for qid in plan["questions"][phase] for arm in ARMS
    }
    indexed = {}
    for row in rows:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        require(key in expected and key not in indexed, "invalid policy question/arm")
        require(row["status"] == "succeeded"
                and isinstance(row.get("answer"), str) and row["answer"].strip(),
                "model answer missing or policy attempt failed")
        require(all(k in row["receipt"] for k in READER_FIELDS),
                "Reader identity/token provenance missing")
        indexed[key] = row
    require(set(indexed) == expected and len(indexed) == 576,
            "incomplete native planned answer census")
    require(report["census"] == {
        "planned": 576, "recorded": 576, "complete": True
    } and report["logical_policy_attempts"] == 576,
            "reported 576-attempt census disagrees")
    reader = report["reader"]
    require(reader["actual_attempts"] == reader["actual_successes"] == 44
            and reader["actual_failed_attempts"] == 0
            and reader["cache_hits"] == 543, "Reader original/cached count drift")
    no_source = report["no_evidence_reader_call_accounting"][
        "isolated_no_evidence_reader"
    ]
    require(no_source["actual_attempts"] == no_source["actual_successes"] == 32
            and no_source["cache_hits"] == no_source["actual_failed_attempts"] == 0,
            "separate no-evidence Reader control incomplete")
    require(len(report["within_head_train_fit"]) == 30, "Head fit receipt count")
    require(report["semantic_citation_precision"] is None
            and report["production_accepted"] is False,
            "historical diagnostic cannot certify citation or production")
    return indexed


def _flatten(value):
    if isinstance(value, list):
        for item in value:
            yield from _flatten(item)
    else:
        require(type(value) in (float, int) and math.isfinite(value),
                "invalid Head numeric tensor")
        yield float(value)


def _head_max_delta(reference, current):
    maximum = 0.0
    for key in reference:
        a, b = json.loads(reference[key]), json.loads(current[key])
        require(set(a["state"]) == set(b["state"]), "Head parameter key drift")
        for tensor in a["state"]:
            x = list(_flatten(a["state"][tensor]))
            y = list(_flatten(b["state"][tensor]))
            require(len(x) == len(y), "Head tensor shape/count drift")
            for before, after in zip(x, y, strict=True):
                diff = abs(after - before)
                require(math.isfinite(diff), "nonfinite Head tensor divergence")
                maximum = max(maximum, diff)
    return maximum


def _load_archive(path, run):
    source, tree, pin = PINS[run]
    zipped = PinnedArchive(path, pin)
    try:
        require(zipped.read("tested-commit.txt").decode().strip() == source,
                "generating source ref mismatch")
        require(zipped.read("tested-tree.txt").decode().strip() == tree,
                "generating tree ref mismatch")
        plan = zipped.json("comparison/preregistered.json")
        require(plan["source_commit"] == source, "preregistered source changed")
        return dict(
            source=source, tree=tree, zip_sha256=zipped.sha256,
            manifest_members=zipped.manifest_entries,
            plan=plan, report=zipped.json("comparison/report.json"),
            predictions=zipped.jsonl("comparison/policy-predictions.jsonl"),
            head_bytes={
                (stage, arm, cell): zipped.read(
                    f"comparison/head-{stage}-{arm}-{cell}.json"
                )
                for stage in STAGES for arm in ARMS for cell in CELLS
            },
        )
    finally:
        zipped.close()


def compare_pinned_runs(payloads):
    require(set(payloads) == set(PINS), "exact three source-pinned runs required")
    baseline = payloads["38114107704"]
    first = _index(baseline["plan"], baseline["predictions"], baseline["report"])
    result = dict(
        schema="hepta.stem-three-complete-runs.research.v1",
        comparison_is_read_only=True,
        actual_new_model_calls=0,
        historical_run_ids=list(PINS),
        attempts_per_run=576,
        run_details={}, comparisons={},
        matched_native_documents_not_independent_entailment=True,
        semantic_citation_precision=None,
        real_future_window_count=0,
        learned_superiority_established=False,
        production_accepted=False,
    )
    for run, item in payloads.items():
        plan, report = item["plan"], item["report"]
        indexed = _index(plan, item["predictions"], report)
        for name in REGISTRATION:
            require(plan[name] == baseline["plan"][name],
                    "Reader/Encoder/curriculum registration drift: " + name)
        changed = {name: 0 for name in (*MODEL_FIELDS, *READER_FIELDS, *LATENT_FIELDS)}
        for key, old in first.items():
            cur = indexed[key]
            for name in MODEL_FIELDS:
                changed[name] += old.get(name) != cur.get(name)
            for name in READER_FIELDS:
                changed[name] += old["receipt"][name] != cur["receipt"][name]
            for name in LATENT_FIELDS:
                changed[name] += old.get(name) != cur.get(name)
        require(all(changed[k] == 0 for k in (*MODEL_FIELDS, *READER_FIELDS)),
                "real native answer, evidence or Reader token drift")
        altered_head_files = sum(
            item["head_bytes"][k] != baseline["head_bytes"][k]
            for k in baseline["head_bytes"]
        )
        greatest_tensor_change = _head_max_delta(
            baseline["head_bytes"], item["head_bytes"]
        )
        result["comparisons"][run] = dict(
            changed_exact_record_fields=changed,
            changed_persisted_head_artifact_count=altered_head_files,
            maximum_absolute_head_tensor_delta=greatest_tensor_change,
            all_576_answer_and_reader_requests_identical=True,
            persistent_training_bitwise_identical=(
                altered_head_files == 0 and changed["feature_digest"] == 0
            ),
        )
        require(sum(m["emitted_citation_markers"]
                    for m in report["metrics"].values()) == 0,
                "new citation evidence must not be silently interpreted")
        require(sum(x["changed_train_top1_rows"]
                    for x in report["within_head_train_fit"]) == 0,
                "real TRAIN source ranking changed; update original claim")
        ceiling = report["retrospective_weak_source_ceiling"]["phases"]
        fit48 = {}
        for arm in ARMS[1:]:
            rows = [q for q in report["within_head_train_fit"]
                    if q["checkpoint"] == 48 and q["arm"] == arm]
            require(len(rows) == 2 and {q["cell"] for q in rows} == set(CELLS),
                    "missing final Head Cell checkpoint")
            fit48[arm] = dict(
                train_rows=sum(q["matched_training_rows"] for q in rows),
                general_train_loss_delta=next(q["mean_weak_loss_delta"]
                    for q in rows if q["cell"] == "general"),
                temporal_train_loss_delta=next(q["mean_weak_loss_delta"]
                    for q in rows if q["cell"] == "temporal"),
                changed_train_source_top1=sum(
                    q["changed_train_top1_rows"] for q in rows
                ),
            )
        bridge = report.get("train_to_heldout_diagnostic")
        # Run 38114107704 predates this observer; do not fabricate its result.
        net_transfer = (
            sum(q["heldout_test_transfer_native_support_net_gain"]
                for key, q in bridge["by_checkpoint_cell_arm"].items()
                if key.startswith("48/"))
            if bridge is not None else None
        )
        result["run_details"][run] = dict(
            generating_commit=item["source"], generating_tree=item["tree"],
            externally_pinned_zip_sha256=item["zip_sha256"],
            verified_sha256_manifest_members=item["manifest_members"],
            actual_policy_plus_oracle_reader_calls=report["reader"]["actual_attempts"],
            exact_reader_cache_hits=report["reader"]["cache_hits"],
            independent_no_evidence_reader_calls=report[
                "no_evidence_reader_call_accounting"
            ]["isolated_no_evidence_reader"]["actual_attempts"],
            total_measured_experiment_seconds=report["elapsed_seconds"],
            process_peak_rss_kib=report["process_peak_rss_kib"],
            candidate_weak_source_retrieval_gap={
                phase: dict(
                    attempted=ceiling[phase]["attempted"],
                    native_support_resolved=ceiling[phase]["native_source_resolved"],
                    support_missing_from_pool=ceiling[phase]["support_missing_from_pool"],
                    support_available_but_frozen_missed=ceiling[phase][
                        "frozen_missed_available_support"
                    ],
                ) for phase in PHASES
            },
            final_head_train_deltas=fit48,
            final_checkpoint_test_transfer_native_support_net_gain=net_transfer,
            training_parameter_differences_are_not_task_benefits=True,
            semantic_citation_precision=None,
            production_accepted=False,
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for run in PINS:
        parser.add_argument("--run-" + run, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare_pinned_runs({
        run: _load_archive(getattr(args, "run_" + run), run)
        for run in PINS
    })
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "schema": report["schema"],
        "runs": {
            run: {
                "manifest_members": v["verified_sha256_manifest_members"],
                "test_missing_native_support": v["candidate_weak_source_retrieval_gap"][
                    "test"
                ]["support_missing_from_pool"],
                "test_transfer_net_gain": v[
                    "final_checkpoint_test_transfer_native_support_net_gain"
                ],
            } for run, v in report["run_details"].items()
        },
        "changed_answers": {
            run: v["changed_exact_record_fields"]["answer"]
            for run, v in report["comparisons"].items()
        },
        "bitwise_training": {
            run: v["persistent_training_bitwise_identical"]
            for run, v in report["comparisons"].items()
        },
        "production_accepted": False,
    }, allow_nan=False))


if __name__ == "__main__":
    main()
