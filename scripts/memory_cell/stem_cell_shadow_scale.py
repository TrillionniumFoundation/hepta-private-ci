"""Train-only fixed-grid residual-scale SHADOW diagnostic.

It does not modify the six policy arms, their Reader, the original training
objective or any held-out label. Weak native source support is not entailment.
"""

from collections import defaultdict
import hashlib
import json
import math

from sessions import source_id

ARMS = frozenset(
    ("prototype", "linear", "gated", "lineage_lora_gated", "independent_lora_gated")
)
CELLS = frozenset(("general", "temporal"))
STAGES = frozenset((16, 32, 48))
GRID = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)


def _pin(value):
    data = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def choose_shadow(ids, original, learned, scale):
    """Label-free forced-top1 candidate; never call the Reader."""
    if (
        not isinstance(ids, (tuple, list))
        or not 0 <= len(ids) <= 64
        or len(ids) != len(original)
        or len(ids) != len(learned)
        or len(set(ids)) != len(ids)
        or any(not isinstance(x, str) or not x for x in ids)
        or type(scale) not in (int, float)
        or not math.isfinite(scale)
        or not 0 <= scale <= max(GRID)
        or any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in (*original, *learned)
        )
    ):
        raise ValueError("unbound candidate scores or invalid preregistered scale")
    if not ids:
        return None
    mixed = [
        base + scale * (after - base)
        for base, after in zip(original, learned, strict=True)
    ]
    if not all(math.isfinite(score) for score in mixed):
        raise ValueError("overflow in bounded shadow scaling")
    return min(range(len(ids)), key=lambda i: (-mixed[i], ids[i]))


def calibrate_shadow_scale(rows, *, arm, cell, stage, admitted_ids):
    """TRAIN-only equal-family-macro weak-source accuracy; tie favors zero."""
    if (
        arm not in ARMS
        or cell not in CELLS
        or stage not in STAGES
        or not isinstance(admitted_ids, (set, frozenset))
        or not 1 <= len(rows) <= 48
    ):
        raise ValueError("invalid registered train-only shadow calibration")
    seen, eligible, excluded = set(), [], 0
    for row in rows:
        qid = row["question_id"]
        family = row["family"]
        ids = row["candidate_ids"]
        positives = row["positive_indices"]
        original, learned = row["frozen_logits"], row["head_logits"]
        choose_shadow(ids, original, learned, 0)
        choose_shadow(ids, original, learned, 1)
        if (
            not isinstance(qid, str)
            or not qid
            or qid not in admitted_ids
            or qid in seen
            or not isinstance(family, str)
            or not family
            or not isinstance(positives, (list, tuple))
            or len(set(positives)) != len(positives)
            or any(type(i) is not int or not 0 <= i < len(ids) for i in positives)
        ):
            raise ValueError("shadow train row not admitted or candidate pool drift")
        seen.add(qid)
        if 0 < len(positives) < len(ids):
            eligible.append(row)
        else:
            excluded += 1
    scores = {}
    for scale in GRID:
        per_family = defaultdict(list)
        for row in eligible:
            index = choose_shadow(
                row["candidate_ids"],
                row["frozen_logits"],
                row["head_logits"],
                scale,
            )
            per_family[row["family"]].append(int(index in row["positive_indices"]))
        scores[str(scale)] = (
            math.fsum(math.fsum(v) / len(v) for v in per_family.values())
            / len(per_family)
            if per_family
            else None
        )
    if eligible:
        high = max(scores[str(v)] for v in GRID)
        chosen = min(scale for scale in GRID if scores[str(scale)] == high)
    else:
        chosen = 0.0
    return dict(
        schema="hepta.stem-train-only-shadow-scale.v1",
        arm=arm,
        cell=cell,
        stage=stage,
        scale_grid=GRID,
        chosen_scale=chosen,
        admitted_train_question_count=len(seen),
        positive_negative_eligible_train_count=len(eligible),
        ineligible_null_or_no_competing_support_count=excluded,
        equal_family_weighted_train_source_accuracy_by_scale=scores,
        distinct_weak_train_source_families=len({row["family"] for row in eligible}),
        train_question_set_sha256=_pin(sorted(seen)),
        winner_chosen_from_train_only=True,
        all_test_and_transfer_answers_and_labels_unseen=True,
        fixed_Reader_policy_untouched=True,
        no_new_reader_call=True,
        selection_scale_is_not_semantic_confidence=True,
        production_accepted=False,
    )


def verify_shadow_source_receipts(shadow_rows, calibrations, pools):
    """Audit prediction provenance BEFORE accessing any held-out target.

    A changed source ID is meaningful only if its two chosen indices come
    from the same original sealed pool, with the exact checkpoint Head SHA
    and TRAIN-chosen scale. Preserve every failed attempt in the denominator.
    """
    if len(calibrations) != 30 or len(shadow_rows) != 480:
        raise ValueError("incomplete original shadow calibration/choice census")
    calibration = {}
    for row in calibrations:
        key = row["stage"], row["arm"], row["cell"]
        if (
            key in calibration
            or key[0] not in STAGES
            or key[1] not in ARMS
            or key[2] not in CELLS
            or row["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("duplicated or unregistered TRAIN scale checkpoint")
        if row["status"] == "succeeded":
            info = row["receipt"]
            if (
                info["winner_chosen_from_train_only"] is not True
                or info["all_test_and_transfer_answers_and_labels_unseen"] is not True
                or info["stage"] != key[0]
                or info["arm"] != key[1]
                or info["cell"] != key[2]
                or info["chosen_scale"] not in GRID
                or not isinstance(row["checkpoint_head_sha256"], str)
                or len(row["checkpoint_head_sha256"]) != 64
            ):
                raise ValueError("unbound or contaminated TRAIN scale")
        calibration[key] = row
    if len(calibration) != 30:
        raise ValueError("missing TRAIN scale checkpoint")

    seen, succeeded = set(), 0
    for row in shadow_rows:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        cell = row["cell"]
        calib = calibration.get((key[0], key[3], cell))
        if (
            key in seen
            or key[0] not in STAGES
            or key[1] not in ("select", "retention", "test", "transfer")
            or key[3] not in ARMS
            or cell not in CELLS
            or row["status"] not in ("succeeded", "failed")
            or calib is None
        ):
            raise ValueError("unregistered, duplicate or uncalibrated shadow choice")
        seen.add(key)
        if row["status"] != "succeeded":
            continue
        if calib["status"] != "succeeded":
            raise ValueError("successful shadow selected with failed TRAIN calibration")
        pool = pools.get(key[2])
        if pool is None:
            raise ValueError("successful shadow choice has no source pool")
        candidates = pool.windows
        winner, frozen = row["selected_index"], row["frozen_index"]
        if (
            not candidates
            or type(winner) is not int
            or type(frozen) is not int
            or not 0 <= winner < len(candidates)
            or not 0 <= frozen < len(candidates)
            or row["chosen_scale"] != calib["receipt"]["chosen_scale"]
            or row["head_sha256"] != calib["checkpoint_head_sha256"]
            or row["original_pool_digest"] != pool.seal()
            or row["candidate_identity_sha256"]
            != _pin(tuple(w.identity() for w in candidates))
            or row["selected_source_id"] != candidates[winner].source_id
            or row["frozen_selected_source_id"] != candidates[frozen].source_id
            or type(row["changed_frozen_top1"]) is not bool
            or row["changed_frozen_top1"] != (winner != frozen)
            or row["native_targets_unread"] is not True
            or row["actual_reader_executions"] != 0
        ):
            raise ValueError("shadow source choice/pool/head/scale receipt drift")
        succeeded += 1
    return dict(
        schema="hepta.stem-shadow-provenance-audit.v1",
        planned_shadow_calibrations=30,
        planned_shadow_source_choices=480,
        source_choices_verified=succeeded,
        failed_source_choices=480 - succeeded,
        no_gold_target_read=True,
        no_additional_reader_call=True,
        production_accepted=False,
    )


def summarize_shadow_heldout(shadow_rows, phase_questions, registered_routes, targets):
    """Inspect weak source labels only after all official choices are sealed."""
    phases = ("select", "retention", "test", "transfer")
    expected = {
        (stage, phase, qid, arm)
        for stage in (16, 32, 48)
        for phase in phases
        for qid in phase_questions[phase]
        for arm in ARMS
    }
    if (
        any(len(phase_questions[p]) != 8 for p in phases)
        or len(expected) != 480
        or set(targets) != {qid for phase in phases for qid in phase_questions[phase]}
    ):
        raise ValueError("shadow 480-choice preregistration incomplete")
    seen, grouped = set(), defaultdict(list)
    for row in shadow_rows:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        if (
            key not in expected
            or key in seen
            or registered_routes[key[2]] != row["cell"]
            or row["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("duplicate, wrong-route or unregistered shadow choice")
        seen.add(key)
        target = targets[key[2]]
        if target.unanswerable:
            cls = "native-unanswerable"
        elif target.unresolved_evidence or not target.evidence:
            cls = "native-support-unresolved"
        else:
            cls = "answerable-native-source"
        support, baseline_support = None, None
        if cls == "answerable-native-source" and row["status"] == "succeeded":
            choice, baseline = (
                row["selected_source_id"],
                row["frozen_selected_source_id"],
            )
            if (
                not isinstance(choice, str)
                or not choice
                or not isinstance(baseline, str)
                or not baseline
            ):
                raise ValueError("unbound original and shadow source identities")
            original_sources = {source_id(s) for s in target.evidence}
            support = int(source_id(choice) in original_sources)
            baseline_support = int(source_id(baseline) in original_sources)
        grouped[(row["stage"], row["arm"], row["cell"], row["phase"])].append(
            dict(
                status=row["status"],
                category=cls,
                scored_support=support,
                baseline_support=baseline_support,
                changed_top1=row.get("changed_frozen_top1"),
            )
        )
    if seen != expected:
        raise ValueError("missing planned source-only shadow decisions")
    out = {}
    for key, rows in sorted(grouped.items()):
        out["/".join(map(str, key))] = dict(
            planned=len(rows),
            successful_choices=sum(x["status"] == "succeeded" for x in rows),
            failed_choices=sum(x["status"] == "failed" for x in rows),
            answerable_source_labeled=sum(
                x["category"] == "answerable-native-source" for x in rows
            ),
            native_unanswerable=sum(
                x["category"] == "native-unanswerable" for x in rows
            ),
            native_support_unresolved=sum(
                x["category"] == "native-support-unresolved" for x in rows
            ),
            source_scored=sum(x["scored_support"] is not None for x in rows),
            native_weak_source_correct=sum(x["scored_support"] == 1 for x in rows),
            frozen_weak_source_correct=sum(x["baseline_support"] == 1 for x in rows),
            shadow_weak_source_gains=sum(
                x["baseline_support"] == 0 and x["scored_support"] == 1 for x in rows
            ),
            shadow_weak_source_regressions=sum(
                x["baseline_support"] == 1 and x["scored_support"] == 0 for x in rows
            ),
            changed_source_top1=sum(x["changed_top1"] is True for x in rows),
            semantic_entailment_judged=False,
            reader_called_for_shadow=False,
        )
    return dict(
        schema="hepta.stem-shadow-weak-source-ceiling.v1",
        planned_shadow_choices=480,
        results=out,
        labels_opened_only_after_all_model_decisions=True,
        not_an_independent_source_sufficiency_oracle=True,
        production_accepted=False,
    )
