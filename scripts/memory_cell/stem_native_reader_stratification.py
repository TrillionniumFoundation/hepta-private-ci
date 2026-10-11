"""Match existing frozen Reader answers against its empty-evidence control.

The 32 original final-checkpoint, no-evidence and weak-native-support
receipts were produced BEFORE this read-only stratification. Model weights,
retrieval, serving, optimizer and all raw answers remain unchanged.
"""

from collections import defaultdict
import math

from stem_audit_archive import require

PHASES = ("select", "retention", "test", "transfer")
BUCKETS = (
    "native-support-chosen",
    "native-support-retrieved-not-chosen",
    "native-support-not-retrieved",
    "native-unanswerable",
    "native-support-unresolved",
)


def _bucket(row):
    if row["native_source_unanswerable"]:
        return "native-unanswerable"
    if not row["weak_native_support_resolved"]:
        return "native-support-unresolved"
    if row["native_support_available_in_pool"] is False:
        return "native-support-not-retrieved"
    if row["native_support_available_in_pool"] is True:
        if row["frozen_selected_native_support"] is True:
            return "native-support-chosen"
        if row["frozen_selected_native_support"] is False:
            return "native-support-retrieved-not-chosen"
    raise ValueError("unbound native source coverage category")


def stratify_original_reader(
    plan,
    original_policies,
    native_ceiling,
    original_empty_reader,
    paired_reader_report,
):
    expected = {(phase, qid) for phase in PHASES for qid in plan["questions"][phase]}
    require(
        len(expected) == 32
        and paired_reader_report["matched_pairs"] == 32
        and paired_reader_report["production_accepted"] is False
        and paired_reader_report["same_read_only_reader_weights_and_prompt"] is True
        and paired_reader_report["independent_correct_support_verification"] is False,
        "incomplete matched fixed Reader/source controls",
    )
    frozen = {}
    for row in original_policies:
        if row["stage"] != 48 or row["arm"] != "frozen_rerank":
            continue
        key = row["phase"], row["question_id"]
        require(
            key in expected and key not in frozen, "missing/duplicate frozen Reader"
        )
        frozen[key] = row
    ceiling = {}
    for row in native_ceiling["decisions"]:
        key = row["phase"], row["question_id"]
        require(
            key in expected and key not in ceiling,
            "missing/duplicate native source ceiling",
        )
        ceiling[key] = row
    empty = {}
    for row in original_empty_reader:
        key = row["phase"], row["question_id"]
        require(
            key in expected and key not in empty,
            "missing/duplicate actual empty-evidence Reader call",
        )
        empty[key] = row
    paired = {}
    for row in paired_reader_report["pairs"]:
        key = row["phase"], row["question_id"]
        require(
            key in expected and key not in paired,
            "missing/duplicate frozen-vs-empty matched pair",
        )
        paired[key] = row
    require(
        all(set(x) == expected for x in (frozen, ceiling, empty, paired)),
        "complete original 32-question matched Reader audit required",
    )
    out = defaultdict(list)
    for key in sorted(expected):
        f, n, e, p = frozen[key], ceiling[key], empty[key], paired[key]
        receipt = f.get("receipt")
        er = e.get("receipt")
        original_ok = f["status"] == "succeeded"
        empty_ok = e["status"] == "succeeded"
        require(
            original_ok
            and e["status"] in ("succeeded", "failed")
            and p["frozen_reader_succeeded"] is True
            and p["zero_evidence_reader_succeeded"] is empty_ok
            and f["family"] == e["family"] == n["source_family"] == p["family"]
            and isinstance(receipt, dict)
            and len(receipt["delivered_evidence"]) == 1
            and p["actual_frozen_evidence_count"] == 1
            and p["evidence_exposure"] == "one-evidence",
            "original Reader exposure, family or paired result misbound",
        )
        if empty_ok:
            require(
                isinstance(er, dict)
                and receipt.get("generator_identity") == er.get("generator_identity")
                and receipt.get("generator_profile") == er.get("generator_profile")
                and receipt.get("observable_query") == er.get("observable_query")
                and bool(receipt.get("generator_identity"))
                and bool(receipt.get("generator_profile"))
                and er["delivered_evidence"] == [],
                "empty-Reader source, model, prompt or question drift",
            )
        if p["scored_pair"]:
            require(empty_ok, "failed empty Reader cannot be scored")
            require(
                f.get("status") == "succeeded"
                and isinstance(f.get("receipt"), dict)
                and f["receipt"].get("observable_query", {}).get("identity") == key[1],
                "scored frozen policy has no original pinned Reader question",
            )
            # A paired report must not manufacture a different baseline score.
            # Older synthetic inputs may not carry post-hoc F1; when available,
            # bind it directly to the already saved frozen policy score.
            original_f1 = f.get("diagnostic_answer_f1")
            if original_f1 is not None:
                require(
                    type(original_f1) in (int, float)
                    and math.isfinite(original_f1)
                    and math.isclose(original_f1, p["frozen_reader_f1"], abs_tol=1e-10),
                    "paired Reader original F1 differs from saved original score",
                )
            require(
                p["phase"] == key[0] and p["question_id"] == key[1],
                "wrong-question paired Reader report",
            )

            values = (
                p["frozen_reader_f1"],
                p["zero_evidence_reader_f1"],
                p["diagnostic_answer_f1_delta"],
            )
            require(
                all(type(v) in (float, int) and math.isfinite(v) for v in values)
                and all(0 <= v <= 1 for v in values[:2])
                and -1 <= values[2] <= 1
                and math.isclose(values[0] - values[1], values[2], abs_tol=1e-10),
                "invalid source-conditional Reader F1 delta",
            )
        else:
            require(
                not empty_ok or p["scored_pair"] is False,
                "unscored Reader control falsely marked complete",
            )
            values = (None, None, None)
        out[_bucket(n)].append(
            dict(
                phase=key[0],
                question_id=key[1],
                source_family=n["source_family"],
                paired_f1_delta=values[2],
                original_frozen_f1=values[0],
                zero_evidence_f1=values[1],
            )
        )
    summaries = {}
    for bucket in BUCKETS:
        rows = out[bucket]
        n = len(rows)
        scored = [x for x in rows if x["paired_f1_delta"] is not None]
        observed = len(scored)
        missing = n - observed
        total = math.fsum(x["paired_f1_delta"] for x in scored)
        summaries[bucket] = dict(
            planned_questions=n,
            complete_scored_reader_pairs=observed,
            failed_or_unscorable_reader_pairs=missing,
            original_reader_f1_mean_on_scored=(
                math.fsum(x["original_frozen_f1"] for x in scored) / observed
                if observed
                else None
            ),
            empty_reader_f1_mean_on_scored=(
                math.fsum(x["zero_evidence_f1"] for x in scored) / observed
                if observed
                else None
            ),
            source_exposure_vs_empty_f1_delta_mean_on_scored=(
                total / observed if observed else None
            ),
            all_planned_source_exposure_f1_delta_bounds=(
                [(total - missing) / n, (total + missing) / n] if n else None
            ),
            original_answer_diagnostic_wins_over_empty=sum(
                x["paired_f1_delta"] > 0 for x in scored
            ),
            original_answer_diagnostic_losses_vs_empty=sum(
                x["paired_f1_delta"] < 0 for x in scored
            ),
            independent_source_window_entailment_certified=False,
        )
    return dict(
        schema="hepta.stem-native-conditioned-Reader-capacity.v1",
        planned_original_fixed_reader_questions=len(expected),
        categories=summaries,
        phase_question_census={
            phase: sum(x["phase"] == phase for group in out.values() for x in group)
            for phase in PHASES
        },
        rows=[dict(bucket=bucket, **r) for bucket in BUCKETS for r in out[bucket]],
        reused_existing_original_and_empty_answers=True,
        new_model_calls=0,
        model_weights_or_prompt_changed=False,
        native_document_support_not_verified_window_entailment=True,
        independent_prospective_Reader_capacity_established=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
