"""Read-only source-equal analysis of the original complete-macro collection."""

from collections import Counter, defaultdict
from pathlib import Path

from ndu_real_materials import common, evaluator
from ndu_real_runtime import macro_attribution, macro_realization, macro_training_pairs
from ndu_real_runtime.metacontrol_macro_contract import SEQUENCES, digest, sha


def source_mean(rows, field):
    groups = defaultdict(list)
    for row in rows:
        if row.get(field) is not None:
            groups[row["source_id"]].append(float(row[field]))
    return (
        None
        if not groups
        else sum(sum(v) / len(v) for v in groups.values()) / len(groups)
    )


def analyze(
    report, *, collection_root, expected_export_sha256, context, allow_fixtures=False
):
    """Re-admit original files after the pinned full-denominator fitting gate.

    This never executes actors, fits weights, releases sealed roles or fills
    missing outcomes. The source-equal arithmetic describes this finite cohort.
    A complete collection still does not perform an owner evaluation.
    """
    rows, blocked = [], None
    try:
        for split in sorted({p["split"] for p in report["planned"]}):
            rows.extend(
                macro_training_pairs.fit_rows(
                    report,
                    split,
                    expected_export_sha256=expected_export_sha256,
                    context=context,
                )
            )
    except ValueError as error:
        if str(error) != "Incomplete planned collection cannot supply fitting rows":
            raise
        blocked = str(error)
    if not report["planned"]:
        raise ValueError("An analysis needs its original planned denominator")
    summary = {
        "schema": "ctrl.macro-collection-analysis.v1",
        "export_sha256": expected_export_sha256,
        "planned_pairs": report["planned_pairs"],
        "exported_pairs": report["exported_pairs"],
        "unknown_pairs": report["unknown_pairs"],
        "planned_sources": len({p["source_id"] for p in report["planned"]}),
        "planned_by_split": dict(Counter(p["split"] for p in report["planned"])),
        "original_dispositions": report["planned"],
        "analysis_status": "BLOCKED_INCOMPLETE_PLANNED_COLLECTION"
        if blocked
        else "COMPLETE",
        "blocked_reason": blocked,
        "paired_rows": [],
        "metrics": None,
        "full_physical_cost_observed": False,
        "new_source_qualification": False,
        "policy_efficacy_proved": False,
        "decision": "HOLD",
        "owner_evaluation": "not_evaluated",
        "owner_decision": None,
        "scope": "matched collection of forced macros on registered research sources; not prospective six-policy efficacy",
    }
    if blocked:
        return summary
    refreshed = macro_training_pairs.export(
        collection_root,
        expected_plan_sha256=report["plan_sha256"],
        context=context,
        expected_source_sha256=report["converter_source_sha256"],
        allow_fixtures=allow_fixtures,
    )
    if digest(refreshed) != expected_export_sha256:
        raise ValueError("Original collection differs from the admitted export")
    root = Path(collection_root)
    raw_plan = common.read_relative(root, "PLAN.json")
    if sha(raw_plan) != report["plan_sha256"]:
        raise ValueError("Original collection plan changed during analysis")
    plan = common.strict_json(raw_plan)
    planned = {p["decision_id"]: p for p in report["planned"]}
    for row in rows:
        item = planned[row["decision_id"]]
        observed, read_change = {}, None
        for macro in SEQUENCES:
            receipt_pin = row["branches"][macro]["evidence_sha256"]
            receipt = refreshed["receipts"][receipt_pin]
            if digest(receipt) != receipt_pin:
                raise ValueError("Admitted realization receipt changed")
            observed[macro] = receipt["realization"]
            if macro == "READ":
                branch = root / (item["pair_id"] + "-READ")
                trajectory = common.read_relative(branch, "trajectory.json")
                if (
                    sha(trajectory)
                    != observed[macro]["artifact_sha256s"]["trajectory.json"]
                ):
                    raise ValueError("Original selection trajectory changed")
                truth = common.strict_json(
                    common.read_bound(
                        plan["config"]["material_root"],
                        receipt["registered_source"]["reference"],
                    )
                )
                if (
                    truth.get("role") != "train"
                    or truth.get("field") not in ("company", "date", "address", "total")
                    or type(truth.get("expected_text")) is not str
                    or len(truth["expected_text"].encode()) > 8192
                    or evaluator.canonical(truth["expected_text"], truth["field"])
                    is None
                ):
                    raise ValueError(
                        "Posthoc training reference is not an admitted target"
                    )
                prior = observed[macro]["read_attribution"]
                read_change = macro_attribution.read_changes(
                    common.strict_json(trajectory)["steps"],
                    SEQUENCES[macro].index("WRITE_TEXT"),
                    macro,
                    prior["initial_packet_sha256"],
                    prior["finalizer_packet_sha256"],
                    truth,
                )
        result = {
            "pair_id": item["pair_id"],
            "source_id": row["source_id"],
            "split": item["split"],
            "new_recognized_text": read_change["new_recognized_text"],
            "new_reference_matching_candidate": read_change[
                "new_reference_matching_candidate"
            ],
            "within_read_selected_text_changed": read_change["selected_text_changed"],
            "paired_status": "MATCHED",
            "paired_error": None,
        }
        try:
            comparison = macro_realization.compare_realizations(
                observed["STOP"], observed["READ"]
            )
            result.update(
                {
                    k: comparison[k]
                    for k in (
                        "selected_text_changed",
                        "delivered_content_changed",
                        "terminal_quality_changed",
                        "read_minus_stop_quality",
                        "read_minus_stop_observed_latency_cost",
                        "read_minus_stop_observed_latency_net",
                    )
                }
            )
        except ValueError as error:
            result.update(paired_status="UNKNOWN", paired_error=str(error))
        summary["paired_rows"].append(result)
    fields = (
        "new_recognized_text",
        "new_reference_matching_candidate",
        "within_read_selected_text_changed",
        "selected_text_changed",
        "delivered_content_changed",
        "terminal_quality_changed",
        "read_minus_stop_quality",
        "read_minus_stop_observed_latency_cost",
        "read_minus_stop_observed_latency_net",
    )
    summary["metrics"] = {}
    for field in fields:
        known = [r for r in summary["paired_rows"] if r.get(field) is not None]
        summary["metrics"][field] = {
            "known_pairs": len(known),
            "unknown_pairs": len(rows) - len(known),
            "observed_sources": len({r["source_id"] for r in known}),
            "source_equal_mean": source_mean(known, field)
            if len(known) == len(rows)
            else None,
            "observed_subset_source_equal_mean": source_mean(known, field),
        }
    summary["matched_pairs"] = sum(
        r["paired_status"] == "MATCHED" for r in summary["paired_rows"]
    )
    summary["evidence_kinds"] = sorted({r["evidence_kind"] for r in report["planned"]})
    return summary
