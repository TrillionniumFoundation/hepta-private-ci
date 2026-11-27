"""Trace stem-cell failures to their shared stage and quantify actual learning admission.

Only deterministic accounting of immutable prior execution artifacts is performed.
Not an independent performance judge, new policy execution, or gold oracle.
"""

from collections import Counter, defaultdict
import math

from stem_audit_archive import require

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
CELLS = ("general", "temporal")


def diagnose(plan, raw, scored, report, dispositions, feature_failures, adapters):
    """Account for admission, shared errors, Head state and paired predictions."""
    train = plan["questions"]["train"]
    require(len(train) == 48 and len(set(train)) == len(train), "training census drift")
    require(isinstance(dispositions, dict), "training disposition missing")
    skip = dispositions["skipped_training"]
    require(isinstance(skip, list), "missing skipped training array")
    skipped = {}
    for item in skip:
        qid = item["question_id"]
        require(qid in train and qid not in skipped, "invalid or repeated skip")
        require(
            item["reason"] == "unresolved_or_missing_positive_not_abstention",
            "unknown training disposition",
        )
        skipped[qid] = item["reason"]
    admitted = [qid for qid in train if qid not in skipped]
    prefixes = {}
    for n in STAGES:
        prefix = train[:n]
        prefixes[str(n)] = dict(
            attempted=len(prefix),
            admitted=sum(q not in skipped for q in prefix),
            skipped=sum(q in skipped for q in prefix),
            per_cell={
                c: dict(
                    attempted=sum(plan["routes"][q] == c for q in prefix),
                    admitted=sum(
                        plan["routes"][q] == c and q not in skipped for q in prefix
                    ),
                )
                for c in CELLS
            },
        )

    expected_ids = {q for items in plan["questions"].values() for q in items}
    require(
        isinstance(feature_failures, dict) and set(feature_failures) <= expected_ids,
        "unregistered feature failure",
    )
    features_by_phase = {
        phase: sum(q in feature_failures for q in plan["questions"][phase])
        for phase in ("train", "select", "retention", "test", "transfer")
    }
    by_task = defaultdict(dict)
    failure_types, failed_by_arm = Counter(), Counter()
    for row in raw:
        key = (row["stage"], row["phase"], row["question_id"])
        require(row["arm"] not in by_task[key], "duplicate task-arm identity")
        by_task[key][row["arm"]] = row
        if row["status"] == "failed":
            reason = (
                str(row.get("error_type", "unknown"))
                + ": "
                + str(row.get("error", "missing"))
            )
            failure_types[reason[:240]] += 1
            failed_by_arm[row["arm"]] += 1

    shared, specific, partial = [], [], []
    for key, arms in sorted(by_task.items()):
        require(set(arms) == set(ARMS), "incomplete matched task arms")
        failed = tuple(a for a in ARMS if arms[a]["status"] == "failed")
        if not failed:
            continue
        event = dict(
            stage=key[0],
            phase=key[1],
            question_id=key[2],
            failed_arms=list(failed),
            feature_error=feature_failures.get(key[2]),
        )
        if len(failed) == len(ARMS):
            shared.append(event)
        elif failed == ARMS[-2:]:
            specific.append(event)
        else:
            partial.append(event)

    learning = report["learning"]
    require(isinstance(learning, list), "missing learning journal")
    seen, learned = set(), []
    for row in learning:
        identity = (row["stage"], row["arm"], row["cell"])
        require(
            identity not in seen
            and row["stage"] in STAGES
            and row["arm"] in ARMS
            and row["cell"] in CELLS,
            "duplicate or unregistered learning record",
        )
        seen.add(identity)
        if row["status"] == "succeeded":
            receipt = row["receipt"]
            consumed = receipt["consumed_steps"]
            delta = receipt.get("tensor_delta_squared_norm")
            if row["arm"] == "frozen_rerank":
                require(consumed == 0, "frozen baseline was trained")
            elif delta is not None:
                require(
                    type(delta) in (int, float) and math.isfinite(delta) and delta >= 0,
                    "invalid tensor delta",
                )
                require(
                    receipt.get("state_changed") == (delta > 0),
                    "claim of learning contradicts tensor delta",
                )
            learned.append(
                dict(
                    stage=row["stage"],
                    arm=row["arm"],
                    cell=row["cell"],
                    status="succeeded",
                    consumed_updates=consumed,
                    tensor_delta_squared_norm=delta,
                    artifact_bytes=row["artifact_bytes"],
                )
            )
        else:
            require(row["status"] == "failed", "unknown Head fit status")
            learned.append(
                dict(
                    stage=row["stage"],
                    arm=row["arm"],
                    cell=row["cell"],
                    status="failed",
                    error=row.get("error"),
                )
            )

    # A successful decision at each checkpoint must consume exactly the restored
    # Head whose hash the training journal claimed. This checks representation
    # persistence, NOT whether that Head improved answer correctness.
    saved = {
        (row["stage"], row["arm"], row["cell"]): row["after_sha256"]
        for row in learning
        if row["status"] == "succeeded"
    }
    for row in raw:
        if row["status"] != "succeeded":
            continue
        key = (row["stage"], row["arm"], row["cell"])
        require(
            key in saved and row.get("head_sha256") == saved[key],
            "policy output not bound to checkpoint Head",
        )

    original = {(r["stage"], r["phase"], r["question_id"], r["arm"]): r for r in scored}
    paired = {}
    for stage in STAGES:
        for phase in ("select", "retention", "test", "transfer"):
            for arm in ARMS[1:]:
                complete, changed_selection, changed_answer = 0, 0, 0
                source_delta, answer_delta = [], []
                for qid in plan["questions"][phase]:
                    baseline = original[(stage, phase, qid, ARMS[0])]
                    candidate = original[(stage, phase, qid, arm)]
                    if not (baseline["status"] == candidate["status"] == "succeeded"):
                        continue
                    complete += 1
                    changed_selection += baseline["selected"] != candidate["selected"]
                    changed_answer += baseline["answer"] != candidate["answer"]
                    if (
                        baseline["source_choice_correct"] is not None
                        and candidate["source_choice_correct"] is not None
                    ):
                        source_delta.append(
                            candidate["source_choice_correct"]
                            - baseline["source_choice_correct"]
                        )
                    if (
                        baseline["diagnostic_answer_f1"] is not None
                        and candidate["diagnostic_answer_f1"] is not None
                    ):
                        answer_delta.append(
                            candidate["diagnostic_answer_f1"]
                            - baseline["diagnostic_answer_f1"]
                        )
                paired[f"{stage}/{phase}/{arm}"] = dict(
                    planned=len(plan["questions"][phase]),
                    both_succeeded=complete,
                    selected_candidate_changed=changed_selection,
                    original_answer_changed=changed_answer,
                    measured_source_delta_mean=None
                    if not source_delta
                    else math.fsum(source_delta) / len(source_delta),
                    measured_answer_f1_delta_mean=None
                    if not answer_delta
                    else math.fsum(answer_delta) / len(answer_delta),
                    source_scored=len(source_delta),
                    answer_scored=len(answer_delta),
                    independent_superiority_established=False,
                )

    require(
        set(adapters) == {"receipts", "failures"}, "Adapter training inventory missing"
    )
    all_adapters = {**adapters["receipts"], **adapters["failures"]}
    require(
        set(all_adapters) == {"lineage", "independent-general", "independent-temporal"},
        "Adapter attempt inventory incomplete",
    )
    require(
        not (set(adapters["receipts"]) & set(adapters["failures"])),
        "Adapter both failed and succeeded",
    )
    return dict(
        admitted_training_questions=len(admitted),
        skipped_training_questions=len(skipped),
        admitted_prefixes=prefixes,
        feature_failures_by_phase=features_by_phase,
        failed_policy_arms=dict(failed_by_arm),
        failure_reason_counts=dict(failure_types),
        all_six_arms_failed_tasks=shared,
        lora_only_failed_tasks=specific,
        mixed_failed_tasks=partial,
        learning_journal=learned,
        adapter_training_status={
            name: "succeeded" if name in adapters["receipts"] else "failed"
            for name in sorted(all_adapters)
        },
        paired_diagnostics=paired,
        no_new_executions=True,
        semantic_citation_precision=None,
        independent_task_gain_established=False,
    )
