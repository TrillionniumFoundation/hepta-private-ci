"""Real frozen-Encoder pairwise-ranking SHADOW; six policy arms untouched.

A separately initialized linear and gated Head use admitted TRAIN-only weak
document-source positives and unlabeled window distractors. Fit checkpoints
16/32/48 persist/reload their own Head tensors. Test/transfer selections are
sealed BEFORE any held-out annotation is read. No Reader or Encoder call is made.
"""

import math
import time
from pathlib import Path

import torch

from native import digest
from stem_cell import StemHead, sha256
from stem_pairwise_shadow import fit_pairwise_shadow

STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")
SHADOWS = (("pairwise_linear", "linear"), ("pairwise_gated", "gated"))


def _top1(scores, ids):
    if len(scores) != len(ids):
        raise ValueError("shadow candidate score length drift")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in scores):
        raise ValueError("nonfinite shadow candidate score")
    return min(range(len(ids)), key=lambda i: (-scores[i], ids[i])) if ids else None


def native_pairwise_shadow(
    questions,
    training_rows,
    features,
    cut,
    routes,
    output,
    *,
    steps=128,
    margin=1.0,
    lr=0.03,
):
    """Compute 192 frozen-Encoder-based SHADOW choices with no held-out targets.

    A broken shadow row retains a failed receipt and cannot change any of the
    original 576 fixed Reader answers or the experimental acceptance flag.
    """
    train = tuple(q.identity for q in questions["train"])
    evaluation = {
        phase: tuple(q.identity for q in questions[phase]) for phase in PHASES
    }
    all_ids = train + tuple(q for phase in PHASES for q in evaluation[phase])
    if (
        set(questions) != {"train", *PHASES}
        or len(train) != 48
        or len(set(train)) != 48
        or any(len(evaluation[p]) != 8 for p in PHASES)
        or len(all_ids) != len(set(all_ids))
        or len(all_ids) != 80
        or set(routes) != set(all_ids)
        or set(features) != set(all_ids)
        or any(routes[q] not in CELLS for q in all_ids)
        or not isinstance(output, Path)
        or not output.is_dir()
        or type(steps) is not int
        or steps != 128
        or type(margin) not in (int, float)
        or margin != 1.0
        or type(lr) not in (int, float)
        or lr != 0.03
        or set(cut.question_ids) != set(train)
    ):
        raise ValueError("shadow protocol, training cut, or model budget drift")
    encoded = {features[q].encoder_identity for q in all_ids}
    dimensions = {features[q].paired.shape[1] for q in all_ids}
    if len(encoded) != 1 or len(dimensions) != 1:
        raise ValueError("mixed original frozen Encoder representations")
    encoder_identity = next(iter(encoded))
    dimension = next(iter(dimensions))
    for qid in all_ids:
        f = features[qid]
        f.validate(dimension)
        if f.question_id != qid:
            raise ValueError("frozen Feature identity mismatch")

    admitted = {}
    for row in training_rows:
        qid = row.features.question_id
        if (
            qid not in train
            or qid in admitted
            or row.features.seal() != features[qid].seal()
            or row.features.encoder_identity != encoder_identity
            or row.features.family not in cut.families
        ):
            raise ValueError("held-out or changed TRAIN weak source supervision")
        admitted[qid] = row
    if not admitted or len(admitted) > len(train):
        raise ValueError("missing bounded TRAIN weak-supervision rows")

    heads = {
        (arm, cell): StemHead(dimension, encoder_identity, kind=kind)
        for arm, kind in SHADOWS
        for cell in CELLS
    }
    fits, decisions = [], []
    for stage in STAGES:
        for arm, kind in SHADOWS:
            for cell in CELLS:
                head = heads[(arm, cell)]
                current = tuple(
                    admitted[q]
                    for q in train[:stage]
                    if q in admitted and routes[q] == cell
                )
                row = dict(
                    stage=stage,
                    arm=arm,
                    cell=cell,
                    status="failed",
                    initial_head_sha256=sha256(head.export()),
                    training_rows=len(current),
                    trained_question_ids_digest=digest(
                        tuple(q.features.question_id for q in current)
                    ),
                    role="nonqualifying-native-pairwise-no-reader-shadow",
                )
                clock = time.perf_counter()
                try:
                    fit = fit_pairwise_shadow(
                        head,
                        current,
                        cut,
                        revoked=set(),
                        steps=steps,
                        lr=lr,
                        margin=margin,
                    )
                    payload = head.export()
                    model_path = output / f"shadow-{arm}-{cell}-{stage}.json"
                    with model_path.open("xb") as stream:
                        stream.write(payload)
                    loaded = StemHead.restore(
                        payload,
                        expected_sha256=sha256(payload),
                        encoder_identity=encoder_identity,
                        allowed_roots=set(cut.allowed_roots),
                        revoked=set(),
                    )
                    if loaded.export() != payload:
                        raise ValueError("shadow Head artifact-only reload mismatch")
                    heads[(arm, cell)] = loaded
                    row.update(
                        status="succeeded",
                        receipt=fit,
                        final_head_sha256=sha256(payload),
                        model_file_name=model_path.name,
                        model_bytes=len(payload),
                        artifact_reload_matched=True,
                    )
                except Exception as exc:
                    row.update(error_type=type(exc).__name__, error=str(exc)[:1024])
                row["inclusive_attempt_seconds"] = time.perf_counter() - clock
                fits.append(row)
        failed = {
            (f["arm"], f["cell"]): f["error_type"] + ": " + f["error"]
            for f in fits
            if f["stage"] == stage and f["status"] != "succeeded"
        }
        for phase in PHASES:
            for qid in evaluation[phase]:
                f = features[qid]
                cell = routes[qid]
                for arm, _ in SHADOWS:
                    item = dict(
                        stage=stage,
                        phase=phase,
                        question_id=qid,
                        arm=arm,
                        cell=cell,
                        family=f.family,
                        status="failed",
                        pool_digest=f.pool_digest,
                        frozen_feature_digest=f.seal(),
                        candidate_ids_digest=digest(f.candidate_ids),
                        candidate_count=len(f.candidate_ids),
                        training_labels_or_test_gold_in_answer=False,
                        actual_reader_calls=0,
                    )
                    try:
                        if (arm, cell) in failed:
                            raise ValueError(failed[(arm, cell)])
                        head = heads[(arm, cell)]
                        with torch.no_grad():
                            logits = head(f).tolist()
                        n = len(f.candidate_ids)
                        if len(logits) != n + 1:
                            raise ValueError(
                                "shadow Head output includes wrong null class"
                            )
                        base = [float(x) for x in f.frozen_scores.tolist()]
                        candidate = [float(x) for x in logits[:n]]
                        item.update(
                            status="succeeded",
                            selected=_top1(candidate, f.candidate_ids),
                            original_frozen_selected=_top1(base, f.candidate_ids),
                            frozen_scores_digest=digest(base),
                            candidate_scores_digest=digest(candidate),
                            head_sha256=sha256(head.export()),
                        )
                    except Exception as exc:
                        item.update(
                            error_type=type(exc).__name__, error=str(exc)[:1024]
                        )
                    decisions.append(item)
    if len(fits) != 12 or len(decisions) != 192:
        raise ValueError("incomplete original pairwise-shadow experiment census")
    return fits, decisions


def review_pairwise_shadow(
    questions, fits, decisions, frozen_predictions, pools, targets, *, support_indices
):
    """Post-policy weak-document source-score accounting, no Reader execution."""
    expected = {
        (stage, phase, q.identity, arm)
        for stage in STAGES
        for phase in PHASES
        for q in questions[phase]
        for arm, _ in SHADOWS
    }
    indexed = {}
    for row in decisions:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        if key not in expected or key in indexed:
            raise ValueError("duplicate or unknown label-free shadow choice")
        indexed[key] = row
    if len(indexed) != len(expected) or len(expected) != 192:
        raise ValueError("missing exact source-only shadow decision")
    expected_fits = {
        (stage, arm, cell) for stage in STAGES for arm, _ in SHADOWS for cell in CELLS
    }
    seen_fits, fitted = set(), {}
    for fit in fits:
        key = (fit["stage"], fit["arm"], fit["cell"])
        if (
            key not in expected_fits
            or key in seen_fits
            or fit["status"] not in ("succeeded", "failed")
            or fit["role"] != "nonqualifying-native-pairwise-no-reader-shadow"
            or (
                fit["status"] == "succeeded"
                and (
                    fit["receipt"]["strictly_train_source_only"] is not True
                    or fit["receipt"]["observed_original_reader_calls"] != 0
                    or fit["artifact_reload_matched"] is not True
                )
            )
        ):
            raise ValueError("incomplete, unbound or falsely successful shadow fit")
        seen_fits.add(key)
        fitted[key] = fit
    if seen_fits != expected_fits:
        raise ValueError("missing actual native shadow fit")
    result = {}
    for stage in STAGES:
        for arm, _ in SHADOWS:
            for phase in PHASES:
                records = [
                    indexed[(stage, phase, q.identity, arm)] for q in questions[phase]
                ]
                gains = regressions = changed = scored = uncertain = 0
                observed_source_pairs = baseline_reader_failed_with_top1 = 0
                shadow_failed = baseline_unselected = unsupported_gold = 0
                for row in records:
                    qid = row["question_id"]
                    base = frozen_predictions[(stage, phase, qid)]
                    if base["status"] not in ("succeeded", "failed") or row[
                        "status"
                    ] not in ("succeeded", "failed"):
                        raise ValueError("unknown baseline or shadow execution status")
                    if (
                        row.get("cell") != base.get("cell")
                        or row.get("family") != base.get("family")
                        or row.get("cell") not in CELLS
                        or row.get("training_labels_or_test_gold_in_answer")
                        is not False
                        or row.get("actual_reader_calls") != 0
                    ):
                        raise ValueError(
                            "shadow source-family, Cell route or zero-Reader contract drift"
                        )
                    if row["status"] == "succeeded":
                        fit = fitted[(stage, arm, row["cell"])]
                        if fit["status"] != "succeeded" or row.get(
                            "head_sha256"
                        ) != fit.get("final_head_sha256"):
                            raise ValueError(
                                "Shadow decision Head differs from saved fitted checkpoint"
                            )
                    # Reader generation may fail after the original selector
                    # has already committed a top-1. Never discard that
                    # observed SOURCE decision because generation failed.
                    selected = base.get("selected")
                    if selected is None:
                        baseline_unselected += 1
                        uncertain += 1
                        continue
                    target = targets[qid]
                    pool = pools.get(qid)
                    if (
                        pool is None
                        or not callable(getattr(pool, "seal", None))
                        or pool.seal() != row["pool_digest"]
                        or digest(tuple(w.identity() for w in pool.windows))
                        != row["candidate_ids_digest"]
                    ):
                        raise ValueError(
                            "shadow source windows differ from sealed original candidate pool"
                        )
                    if type(selected) is not int or not 0 <= selected < len(
                        pool.windows
                    ):
                        raise ValueError("detached frozen top-1 in source-only audit")
                    if base.get("pool_digest") != row["pool_digest"]:
                        raise ValueError("original/shadow candidate pool drift")
                    if row["status"] == "failed":
                        shadow_failed += 1
                        uncertain += 1
                        continue
                    shadow_selected = row.get("selected")
                    if (
                        type(shadow_selected) is not int
                        or not 0 <= shadow_selected < len(pool.windows)
                        or row["original_frozen_selected"] != selected
                    ):
                        raise ValueError("shadow original frozen ranker winner drift")
                    observed_source_pairs += 1
                    if base["status"] == "failed":
                        baseline_reader_failed_with_top1 += 1
                    changed += int(shadow_selected != selected)
                    if (
                        target.unanswerable
                        or target.unresolved_evidence
                        or not target.evidence
                    ):
                        unsupported_gold += 1
                        uncertain += 1
                        continue
                    support = set(support_indices(pool, target))
                    scored += 1
                    a, b = selected in support, shadow_selected in support
                    gains += int(b and not a)
                    regressions += int(a and not b)
                if scored + uncertain != len(records):
                    raise ValueError("shadow post-policy scored denominator drift")
                result[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=len(records),
                    source_selection_pairs_observed=observed_source_pairs,
                    baseline_reader_failed_with_top1=baseline_reader_failed_with_top1,
                    frozen_selector_unobserved_or_empty=baseline_unselected,
                    shadow_selection_failed_with_baseline_top1=shadow_failed,
                    native_support_unresolved_or_unanswerable=unsupported_gold,
                    selection_changed=changed,
                    source_label_scored=scored,
                    source_label_unresolved_or_failure=uncertain,
                    native_weak_support_gains=gains,
                    native_weak_support_regressions=regressions,
                    reader_failure_never_erases_pre_read_source_selection=True,
                    shadow_answers_never_generated=True,
                    original_reader_answer_reused_as_shadow=False,
                    semantic_citation_precision=None,
                )
    return dict(
        schema="hepta.stem-pairwise-native-source-only-shadow.v2",
        fits=fits,
        original_six_arm_policy_attempts_unmodified=True,
        total_label_blind_decisions=len(decisions),
        observed_reader_calls=0,
        weak_negative_documents_not_independent_entailment=True,
        actual_window_identities_and_digest_verified=True,
        original_source_family_and_cell_route_verified=True,
        shadow_head_sha_matched_to_persistent_fit=True,
        no_reader_calls_or_evaluation_labels_in_shadow_decision_verified=True,
        failed_reader_source_choices_retained_when_observed=True,
        by_checkpoint_phase_arm=result,
        production_accepted=False,
        independently_established_generalization=False,
    )
