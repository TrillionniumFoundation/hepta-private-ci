"""Synthetic anti-forgery checks for a pinned *actual* 192-choice shadow."""

from copy import deepcopy
from hashlib import sha256
import unittest

from stem_pairwise_pinned_disposition import (
    ARMS, CELLS, PHASES, SHADOWS, SOURCE, STAGES,
    audit_native_pairwise_receipts,
)
from stem_audit_archive import AuditError


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({
        phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES
    })
    all_ids = [q for v in questions.values() for q in v]
    routes = {qid: CELLS[i % 2] for group in questions.values()
              for i, qid in enumerate(group)}
    plan = dict(
        source_commit=SOURCE, questions=questions,
        curriculum_attempted_examples=list(STAGES), arms=list(ARMS),
        cells=list(CELLS), routes=routes,
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
    )
    original, choices, fits, blobs = [], [], [], {}
    old_heads = {}
    for stage in STAGES:
        for arm in SHADOWS:
            for cell in CELLS:
                payload = f"actual-head/{stage}/{arm}/{cell}".encode()
                new = sha256(payload).hexdigest()
                before = old_heads.get((arm, cell), "0" * 64)
                old_heads[arm, cell] = new
                name = f"shadow-{arm}-{cell}-{stage}.json"
                blobs[name] = payload
                fits.append(dict(
                    stage=stage, arm=arm, cell=cell,
                    status="succeeded",
                    role="nonqualifying-native-pairwise-no-reader-shadow",
                    initial_head_sha256=before,
                    final_head_sha256=new,
                    artifact_reload_matched=True, model_file_name=name,
                    model_bytes=len(payload),
                    receipt=dict(
                        checkpoint_pre_sha256=before,
                        checkpoint_post_sha256=new,
                        strictly_train_source_only=True,
                        null_weights_unchanged=True,
                        original_six_arms_unchanged=True,
                        observed_original_reader_calls=0,
                        weak_distractors_not_verified_hard_negatives=True,
                        actual_heldout_task_gain_established=False,
                        heldout_annotations_seen=False,
                        production_accepted=False,
                    ),
                ))
        for phase in PHASES:
            for qid in questions[phase]:
                for arm in ARMS:
                    original.append(dict(
                        stage=stage, phase=phase, question_id=qid, arm=arm,
                        status="succeeded", selected=0,
                        cell=routes[qid], family="source-family-" + qid,
                        pool_digest="pool-" + qid,
                        feature_digest="features-" + qid,
                    ))
                for arm in SHADOWS:
                    choices.append(dict(
                        stage=stage, phase=phase, question_id=qid, arm=arm,
                        status="succeeded", selected=0,
                        original_frozen_selected=0,
                        cell=routes[qid], family="source-family-" + qid,
                        pool_digest="pool-" + qid,
                        frozen_feature_digest="features-" + qid,
                        candidate_count=8, candidate_ids_digest="a" * 64,
                        head_sha256=old_heads[arm, routes[qid]],
                        training_labels_or_test_gold_in_answer=False,
                        actual_reader_calls=0,
                    ))
    by_stage_phase_arm = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in SHADOWS:
                by_stage_phase_arm[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8, source_selection_pairs_observed=8,
                    selection_changed=0,
                    baseline_reader_failed_with_top1=0,
                    frozen_selector_unobserved_or_empty=0,
                    shadow_selection_failed_with_baseline_top1=0,
                    source_label_scored=8, source_label_unresolved_or_failure=0,
                    native_weak_support_gains=0, native_weak_support_regressions=0,
                )
    posthoc = dict(
        schema="hepta.stem-pairwise-native-source-only-shadow.v2",
        total_label_blind_decisions=192, observed_reader_calls=0,
        original_six_arm_policy_attempts_unmodified=True,
        no_reader_calls_or_evaluation_labels_in_shadow_decision_verified=True,
        independently_established_generalization=False,
        semantic_citation_precision=None,
        production_accepted=False,
        by_checkpoint_phase_arm=by_stage_phase_arm,
    )
    metrics = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                metrics[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8, succeeded=8, failed=0,
                    emitted_citation_markers=0, delivered_citation_markers=0,
                    source_accuracy=0.25, diagnostic_f1=0.1,
                )
    report = dict(
        metrics=metrics,
        logical_policy_attempts=576, production_accepted=False,
        reader=dict(actual_failed_attempts=0),
        native_pairwise_shadow_source_only=deepcopy(posthoc),
    )
    return plan, original, fits, choices, posthoc, report, blobs


class PairwiseActualArtifactAuditTests(unittest.TestCase):
    def test_all_576_and_192_counts_are_deterministic_and_nonqualifying(self):
        receipt = audit_native_pairwise_receipts(*fixture())
        self.assertEqual(receipt["shadow_training_fit_attempts"], 12)
        self.assertEqual(receipt["original_policy_attempts"], 576)
        self.assertEqual(receipt["shadow_source_decisions"], 192)
        self.assertEqual(receipt["observed_weak_document_source_counts"]["pairs"], 192)
        self.assertEqual(receipt["observed_weak_document_source_counts"]["weak_label_gains"], 0)
        self.assertFalse(receipt["scale_out_permitted"])
        self.assertFalse(receipt["shadow_reader_answer_quality_measured"])
        self.assertIsNone(receipt["independent_semantic_citation_precision"])

    def test_modified_head_file_or_receipt_is_not_accepted(self):
        for mode in ("bytes", "sha", "null", "labels"):
            data = deepcopy(fixture())
            first = data[2][0]
            if mode == "bytes":
                data[6][first["model_file_name"]] = b"forged head"
            elif mode == "sha":
                first["final_head_sha256"] = "f" * 64
            elif mode == "null":
                first["receipt"]["null_weights_unchanged"] = False
            else:
                first["receipt"]["heldout_annotations_seen"] = True
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_native_pairwise_receipts(*data)

    def test_missing_or_tampered_original_frozen_policy_fails_closed(self):
        for mode in ("missing", "duplicate", "wrong-pool", "feature"):
            data = deepcopy(fixture())
            if mode == "missing":
                data[1].pop()
            elif mode == "duplicate":
                data[1].append(deepcopy(data[1][0]))
            elif mode == "wrong-pool":
                data[1][0]["pool_digest"] = "other pool"
            else:
                data[1][0]["feature_digest"] = "other features"
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_native_pairwise_receipts(*data)

    def test_label_blind_shadow_choice_and_posthoc_gains_are_checked(self):
        for mode in ("head", "rank", "scored", "gain"):
            data = deepcopy(fixture())
            if mode == "head":
                data[3][0]["head_sha256"] = "e" * 64
            elif mode == "rank":
                data[3][0]["selected"] = 1
            elif mode == "scored":
                data[4]["by_checkpoint_phase_arm"]["16/select/pairwise_linear"][
                    "source_label_scored"
                ] = 7
            else:
                data[4]["by_checkpoint_phase_arm"]["16/select/pairwise_linear"][
                    "native_weak_support_gains"
                ] = 1
            with self.subTest(mode=mode), self.assertRaises(AuditError):
                audit_native_pairwise_receipts(*data)

    def test_duplicate_shadow_or_head_checkpoint_fails_closed(self):
        for index in (2, 3):
            data = deepcopy(fixture())
            data[index][-1] = deepcopy(data[index][0])
            with self.subTest(index=index), self.assertRaises(AuditError):
                audit_native_pairwise_receipts(*data)

    def test_cumulative_head_chain_cannot_relabel_independent_training(self):
        data = deepcopy(fixture())
        late = next(x for x in data[2] if x["stage"] == 32
                    and x["arm"] == "pairwise_linear" and x["cell"] == "general")
        late["initial_head_sha256"] = "b" * 64
        late["receipt"]["checkpoint_pre_sha256"] = "b" * 64
        with self.assertRaisesRegex(AuditError, "resumed"):
            audit_native_pairwise_receipts(*data)

    def test_original_policy_no_gain_does_not_admit_a_shifting_prompt(self):
        data = deepcopy(fixture())
        data[5]["production_accepted"] = True
        with self.assertRaises(AuditError):
            audit_native_pairwise_receipts(*data)

    def test_nongold_rank_flip_can_be_recorded_without_claiming_entailment(self):
        data = deepcopy(fixture())
        choice = next(x for x in data[3] if x["stage"] == 48 and x["phase"] == "test"
                      and x["arm"] == "pairwise_gated" and x["question_id"] == "test-0")
        choice["selected"] = 1
        group = data[4]["by_checkpoint_phase_arm"]["48/test/pairwise_gated"]
        group["selection_changed"] = 1
        data[5]["native_pairwise_shadow_source_only"] = deepcopy(data[4])
        result = audit_native_pairwise_receipts(*data)
        self.assertEqual(result["by_stage_phase_arm"]["48/test/pairwise_gated"]
                         ["pairwise_source_rank_changes"], 1)
        self.assertFalse(result["prospective_independent_family_benefit_qualified"])
        self.assertFalse(result["production_accepted"])


if __name__ == "__main__":
    unittest.main()
