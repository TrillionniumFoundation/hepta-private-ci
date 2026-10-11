"""Execute a publisher-source-ID-only frozen Reader capacity diagnostic.

This is a NEW, explicitly privileged post-policy experiment. The original
576 policy answers remain byte-pinned and untouched. Published native document
support IDs (but NEVER reference-answer text) choose one deterministic source
window for the exact original question and same frozen Reader/decoding prompt.
The source may not contain the answer. No independent entailment is certified.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import resource
import time

from native import load, digest
from stem_audit_archive import PinnedArchive, require
from stem_source_only_reference import PHASES, make_publisher_source_cases

SOURCE = "675970bb610c70bb0ec30a2dee05c025440510e6"
TREE = "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb"
ZIP_SHA256 = "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"
READER_INVENTORY = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)


def write(path, record):
    with path.open("x", encoding="utf-8") as out:
        json.dump(
            record, out, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False
        )
        out.write("\n")


def append(path, row):
    with path.open("a", encoding="utf-8") as out:
        out.write(
            json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        )


def pinned_original(archive):
    require(
        archive.read("tested-commit.txt").decode().strip() == SOURCE
        and archive.read("tested-tree.txt").decode().strip() == TREE,
        "not the independently pinned strict-source Reader run",
    )
    plan = archive.json("comparison/preregistered.json")
    require(
        plan["source_commit"] == SOURCE
        and plan["reader_inventory"] == READER_INVENTORY
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1",
        "frozen Reader or registered native protocol drift",
    )
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in plan["questions"][phase]
        for arm in ARMS
    }
    observed = {}
    for row in archive.jsonl("comparison/policy-predictions.jsonl"):
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        require(
            key in expected and key not in observed and row["status"] == "succeeded",
            "not the original complete 576-policy Reader census",
        )
        observed[key] = row
    require(len(observed) == len(expected) == 576, "missing originally sealed answer")
    frozen = {}
    for phase in PHASES:
        for qid in plan["questions"][phase]:
            row = observed[(48, phase, qid, "frozen_rerank")]
            rcpt = row["receipt"]
            require(
                rcpt.get("observable_query", {}).get("identity") == qid
                and rcpt.get("generator_identity")
                and rcpt.get("generator_profile")
                and isinstance(rcpt.get("delivered_evidence"), list)
                and len(rcpt["delivered_evidence"]) == 1,
                "original Reader request or evidence binding invalid",
            )
            frozen[phase, qid] = row
    no_evidence = {}
    for row in archive.jsonl("comparison/reader-no-evidence.jsonl"):
        key = (row["phase"], row["question_id"])
        require(
            key in frozen
            and key not in no_evidence
            and row["status"] in ("succeeded", "failed")
            and row["evidence_count"] == 0,
            "zero-context original Reader control corrupted",
        )
        no_evidence[key] = row
    require(set(no_evidence) == set(frozen), "missing zero-context baseline")
    return plan, frozen, no_evidence


def evaluate(plan, planned, original, empty, observed, targets, native_ceiling):
    """Answer text consumed only AFTER every raw source Reader call completes."""
    from selector_evaluation import diagnose

    expected = {(p, qid) for p in PHASES for qid in plan["questions"][p]}
    if (
        len(planned) != 32
        or len(observed) != 32
        or not isinstance(targets, dict)
        or set(targets) != {qid for _, qid in expected}
    ):
        raise ValueError("incomplete original 32-case capacity comparison")
    cover = {}
    if (
        native_ceiling.get("schema")
        != "hepta.stem-post-policy-native-source-ceiling.v1"
        or native_ceiling.get("production_accepted") is not False
    ):
        raise ValueError("not the original post-policy weak-source ceiling")
    for item in native_ceiling["decisions"]:
        key = (item["phase"], item["question_id"])
        if key not in expected or key in cover:
            raise ValueError("duplicate/unregistered native source coverage record")
        cover[key] = item
    if set(cover) != expected:
        raise ValueError("incomplete original source-coverage stratification")
    report = defaultdict(list)
    buckets = defaultdict(list)
    for (q, evidence, meta), row in zip(planned, observed, strict=True):
        key = (meta["phase"], q.identity)
        if (
            key not in expected
            or key not in original
            or key not in empty
            or row["question_id"] != q.identity
            or row["phase"] != meta["phase"]
            or row["status"] not in ("succeeded", "failed", "unavailable")
            or (meta["status"] == "unavailable" and row["status"] != "unavailable")
            or (meta["status"] == "planned" and row["status"] == "unavailable")
            or row["source_family"] != meta["source_family"]
            or (meta["status"] == "planned" and not evidence)
            or (meta["status"] == "unavailable" and evidence)
        ):
            raise ValueError("source-only Reader cohort identity mismatch")
        b, z = original[key], empty[key]
        c = cover[key]
        if c["source_family"] != row["source_family"] or bool(
            c["native_source_unanswerable"]
        ) != bool(targets[q.identity].unanswerable):
            raise ValueError("original weak-source support category drift")
        if c["native_source_unanswerable"]:
            bucket = "native-unanswerable"
        elif not c["weak_native_support_resolved"]:
            bucket = "native-support-unresolved"
        elif c["native_support_available_in_pool"] is False:
            bucket = "native-support-not-retrieved"
        elif c["native_support_available_in_pool"] is True:
            if c["frozen_selected_native_support"] is True:
                bucket = "native-support-chosen"
            elif c["frozen_selected_native_support"] is False:
                bucket = "native-support-retrieved-not-chosen"
            else:
                raise ValueError("missing original frozen chosen-source category")
        else:
            raise ValueError("unknown original frozen candidate coverage")
        if b["family"] != row["source_family"]:
            raise ValueError("frozen/privileged source-family drift")
        f1, original_f1, zero_f1 = None, None, None
        if row["status"] == "succeeded":
            receipt = row["receipt"]
            frozen_receipt = b["receipt"]
            if (
                receipt["generator_identity"] != frozen_receipt["generator_identity"]
                or receipt["generator_profile"] != frozen_receipt["generator_profile"]
                or receipt.get("observable_query")
                != frozen_receipt.get("observable_query")
                or receipt["delivered_evidence"] != list(evidence)
                or not receipt["delivered_evidence"]
            ):
                raise ValueError("publisher-source Reader model/prompt/source drift")
            f1 = diagnose(row["answer"], targets[q.identity])
            original_f1 = diagnose(b["answer"], targets[q.identity])
            if z["status"] == "succeeded":
                z_receipt = z["receipt"]
                if (
                    z_receipt["generator_identity"] != receipt["generator_identity"]
                    or z_receipt["generator_profile"] != receipt["generator_profile"]
                    or z_receipt["observable_query"] != receipt["observable_query"]
                    or z_receipt["delivered_evidence"] != []
                ):
                    raise ValueError("original no-evidence Reader condition drift")
                zero_f1 = diagnose(z["answer"], targets[q.identity])

        def validated(value):
            if value is not None and (
                type(value) not in (float, int)
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("nonfinite or invalid Reader answer-F1")
            return value

        f1, original_f1, zero_f1 = (validated(x) for x in (f1, original_f1, zero_f1))
        answer = row.get("answer", "")
        emitted_markers = len(re.findall(r"\[E[0-9]+\]", answer))
        comparison = dict(
            question_id=q.identity,
            original_frozen_source_bucket=bucket,
            source_family=meta["source_family"],
            outcome=row["status"],
            published_support_window_was_delivered=(row["status"] == "succeeded"),
            result_answerable=not targets[q.identity].unanswerable,
            frozen_answer_token_f1=original_f1,
            source_only_reader_token_f1=f1,
            zero_evidence_token_f1=zero_f1,
            source_only_minus_frozen_f1=(
                f1 - original_f1 if f1 is not None and original_f1 is not None else None
            ),
            source_only_minus_empty_f1=(
                f1 - zero_f1 if f1 is not None and zero_f1 is not None else None
            ),
            structural_citation_marker_count=emitted_markers,
            citation_entailment_independently_verified=False,
        )
        report[meta["phase"]].append(comparison)
        buckets[bucket].append(comparison)
    per_phase = {}
    for phase in PHASES:
        rows = report[phase]
        if len(rows) != 8:
            raise ValueError("missing preregistered Reader comparison phase")
        diffs = [
            v["source_only_minus_frozen_f1"]
            for v in rows
            if v["source_only_minus_frozen_f1"] is not None
        ]
        n = len(rows)
        missing = n - len(diffs)
        total = math.fsum(diffs)
        per_phase[phase] = dict(
            planned=n,
            model_answers=sum(v["outcome"] == "succeeded" for v in rows),
            unavailable=sum(v["outcome"] == "unavailable" for v in rows),
            model_or_admission_failed=sum(v["outcome"] == "failed" for v in rows),
            matched_answer_f1_pairs=len(diffs),
            unscored_or_unavailable_pairs=missing,
            source_only_minus_frozen_f1_mean=(total / len(diffs) if diffs else None),
            original_planned_f1_delta_bounds=[
                (total - missing) / n,
                (total + missing) / n,
            ],
            structural_marker_count=sum(
                v["structural_citation_marker_count"] for v in rows
            ),
            independent_semantic_reference_precision=None,
        )
    by_bucket = {}
    for bucket, rows in sorted(buckets.items()):
        matched = [
            x["source_only_minus_frozen_f1"]
            for x in rows
            if x["source_only_minus_frozen_f1"] is not None
        ]
        count = len(rows)
        missing = count - len(matched)
        total = math.fsum(matched)
        by_bucket[bucket] = dict(
            planned=count,
            actual_source_only_reader_succeeded=sum(
                x["outcome"] == "succeeded" for x in rows
            ),
            paired_answer_scored=len(matched),
            unsupported_or_unscored=missing,
            conditional_token_f1_gain_mean=(total / len(matched) if matched else None),
            all_planned_token_f1_gain_bounds=[
                (total - missing) / count,
                (total + missing) / count,
            ],
            independently_certified_sufficient_evidence=False,
        )
    return dict(
        schema="hepta.stem-publisher-source-only-reader-evaluation.v2",
        original_source=SOURCE,
        original_artifact_sha256=ZIP_SHA256,
        matched_original_questions=32,
        phase_counts=per_phase,
        by_original_weak_native_source_coverage=by_bucket,
        decisions=[x for phase in PHASES for x in report[phase]],
        pretrained_reader_changed=False,
        original_six_policy_arms_reexecuted=False,
        publisher_source_IDs_are_a_privileged_diagnostic=True,
        source_window_selected_from_question_not_target_answer=True,
        gold_answer_text_not_used_in_source_selection_or_generation=True,
        sufficient_context_independently_reviewed=False,
        prospective_holdout_or_authentic_independence_verified=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )


def run(staged, original_artifact, output):
    from selector_answering import FrozenAnswerGenerator, GENERATION, SYSTEM
    from stem_cell_runtime import ExactReaderCache

    staged, original_artifact, output = (
        Path(staged),
        Path(original_artifact),
        Path(output),
    )
    archive = PinnedArchive(original_artifact, ZIP_SHA256)
    try:
        plan, frozen, empty = pinned_original(archive)
        require(
            plan["generator_config"] == GENERATION
            and plan["generator_template_digest"] == digest(SYSTEM),
            "same frozen Reader prompt and decoding budget required",
        )
        benchmarks = {
            name: load(
                staged / (name + ".json"),
                name,
                plan["dataset_sha256"][name],
                allow_unresolved_evidence=True,
                session_conflicts="retain-versioned",
                invalid_history="quarantine-question",
                empty_turns="preserve",
            )
            for name in ("locomo", "longmemeval")
        }
        queries, source_for = {}, {}
        registered = {qid for phase in PHASES for qid in plan["questions"][phase]}
        for source in benchmarks.values():
            for q in source.questions:
                if q.identity in registered:
                    require(
                        q.identity not in queries,
                        "duplicate native question in publisher source run",
                    )
                    queries[q.identity], source_for[q.identity] = q, source
        require(set(queries) == registered, "unknown native original question")
        planned = make_publisher_source_cases(plan, queries, source_for)
        for q, _, _ in planned:
            original_query = frozen[
                next(
                    phase for phase in PHASES if q.identity in plan["questions"][phase]
                ),
                q.identity,
            ]["receipt"]["observable_query"]
            require(
                original_query == asdict(q),
                "Reader native question bytes differ from original run",
            )
        output.mkdir(parents=True, exist_ok=False)
        write(
            output / "precommitted-plan.json",
            dict(
                original_source=SOURCE,
                original_tree=TREE,
                original_zip_sha256=archive.sha256,
                original_manifest_entries=archive.manifest_entries,
                frozen_reader_inventory=READER_INVENTORY,
                original_question_count=32,
                actual_source_only_model_calls_not_yet_known=True,
                original_policy_answer_bytes_unchanged=True,
                published_support_source_ids_privileged=True,
                standard_answer_text_entered_window_selector=False,
                production_accepted=False,
            ),
        )
        for _, _, metadata in planned:
            append(output / "source-guided-plans.jsonl", metadata)
        start = time.perf_counter()
        generator = FrozenAnswerGenerator(
            staged / "reader", expected_inventory=READER_INVENTORY
        )
        cold = time.perf_counter() - start
        reference = next(iter(frozen.values()))["receipt"]
        require(
            generator.identity == reference["generator_identity"]
            and generator.profile == reference["generator_profile"],
            "new source-only Reader identity/profile mismatched frozen original",
        )
        session = ExactReaderCache(generator)
        observed = []
        for q, evidence, meta in planned:
            row = dict(
                schema="hepta.stem-publisher-source-reader-output.v1",
                phase=meta["phase"],
                question_id=q.identity,
                source_family=meta["source_family"],
                source_plan_sha256=digest(meta),
                role="privileged-source-only-no-answer-span-control",
            )
            if not evidence:
                row.update(status="unavailable", reason=meta["reason"])
            else:
                try:
                    answer, receipt = session.answer(
                        q,
                        evidence,
                        "publisher-source/" + q.identity,
                        revoked=set(),
                    )
                    row.update(status="succeeded", answer=answer, receipt=receipt)
                except Exception as error:
                    row.update(
                        status="failed",
                        error_type=type(error).__name__,
                        error=str(error)[:1024],
                    )
            append(output / "source-guided-raw-reader.jsonl", row)
            observed.append(row)
        if not generator.quarantined:
            generator.verify_frozen()
        target_view = {qid: source_for[qid].targets[qid] for qid in registered}
        # Gold answer strings read ONLY here, after full original and source
        # Reader outcome journals were persisted.
        original_weak_source_ceiling = archive.json(
            "comparison/post-policy-native-source-ceiling.json"
        )
        scored = evaluate(
            plan,
            planned,
            frozen,
            empty,
            observed,
            target_view,
            original_weak_source_ceiling,
        )
        scored.update(
            exact_original_reader_model_identity=generator.identity,
            exact_original_reader_prompt_profile=generator.profile,
            isolated_reader_cost=session.summary(),
            separate_cold_reader_load_seconds=cold,
            process_peak_entire_diagnostic_rss_kib=(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            ),
            metric_not_eligible_for_train_or_hyperparameter_tuning=True,
            original_manifest_entries=archive.manifest_entries,
        )
        write(output / "source-only-reader-report.json", scored)
        if any(row["status"] == "failed" for row in observed):
            raise RuntimeError(
                "incomplete source-only Reader control; failure records retained"
            )
        return scored
    finally:
        archive.close()


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--staged", required=True, type=Path)
    args.add_argument("--original", required=True, type=Path)
    args.add_argument("--output", required=True, type=Path)
    parsed = args.parse_args()
    report = run(parsed.staged, parsed.original, parsed.output)
    print(
        json.dumps(
            dict(
                schema=report["schema"],
                questions=report["matched_original_questions"],
                phases=report["phase_counts"],
                native_source_coverage=report[
                    "by_original_weak_native_source_coverage"
                ],
                production_accepted=report["production_accepted"],
            ),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
