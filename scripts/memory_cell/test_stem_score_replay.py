"""Independent score-vector replay: synthetic tests, no native gold labels."""

from copy import deepcopy
import unittest

from native import digest
from stem_audit_archive import AuditError
from stem_cell_geometry import inspect_selection
from stem_score_replay import replay_one, replay_all


def fixture(*, adapted=False):
    ids = ("A", "B")
    before = [5.0, 0.0]
    encoder = [2.0, 6.0] if adapted else list(before)
    after = [1.0, 7.0]
    arm = "lineage_lora_gated" if adapted else "gated"
    geometry = inspect_selection(
        encoder,
        after,
        ids,
        1,
        original_frozen_scores=before,
        encoder_adapted=adapted,
    )
    record = dict(
        stage=16,
        phase="test",
        question_id="test-1",
        arm=arm,
        cell="general",
        family="source-family-1",
        status="succeeded",
        selected=1,
        pool_digest="sealed-pool",
        feature_digest="c" * 64 if adapted else "b" * 64,
        selection_geometry=geometry,
    )
    vectors = dict(
        schema="hepta.stem-selection-score-vectors.v1",
        stage=16,
        phase="test",
        question_id="test-1",
        arm=arm,
        cell="general",
        source_family="source-family-1",
        candidate_ids=list(ids),
        original_frozen_logits=before,
        post_adapter_encoder_logits=encoder,
        checkpoint_head_logits=after,
        source_pool_sha256="sealed-pool",
        candidate_ids_sha256=digest(ids),
        raw_scores_sha256=geometry["raw_scores_sha256"],
        geometry_sha256=digest(geometry),
        original_feature_sha256="b" * 64,
        checkpoint_feature_sha256="c" * 64 if adapted else "b" * 64,
        selected_index=1,
        encoder_adapted=adapted,
        null_logit=0.0,
        answer_targets_read=False,
        source_excerpts_recorded=False,
        production_accepted=False,
    )
    return record, vectors


class ScoreReplayTests(unittest.TestCase):
    def test_truly_recomputes_original_top1_and_flip_scale(self):
        policy, vectors = fixture()
        found = replay_one(policy, vectors)
        self.assertTrue(found["source_rank_changed"])
        self.assertTrue(found["direction_can_flip"])
        self.assertAlmostEqual(found["scale_infimum"], 5 / 11)
        self.assertFalse(found["source_label_correctness_known_here"])

    def test_three_way_adapted_encoder_is_not_head_only(self):
        policy, vectors = fixture(adapted=True)
        result = replay_one(policy, vectors)
        self.assertFalse(result["original_rank_equals_adapted"])
        self.assertTrue(result["source_rank_changed"])

    def test_independent_math_rejects_forged_scaling_claim_even_if_rehashed(self):
        p, v = fixture()
        p["selection_geometry"]["joint_flip_scale_infimum"] = 0.8
        v["geometry_sha256"] = digest(p["selection_geometry"])
        with self.assertRaisesRegex(AuditError, "source logits"):
            replay_one(p, v)

    def test_modified_logits_with_forged_original_hash_fail_math(self):
        p, v = fixture()
        v["checkpoint_head_logits"][0] = 1.5
        v["raw_scores_sha256"] = digest(
            (
                tuple(v["candidate_ids"]),
                v["original_frozen_logits"],
                v["post_adapter_encoder_logits"],
                v["checkpoint_head_logits"],
            )
        )
        p["selection_geometry"]["raw_scores_sha256"] = v["raw_scores_sha256"]
        v["geometry_sha256"] = digest(p["selection_geometry"])
        with self.assertRaises(AuditError):
            replay_one(p, v)

    def test_refuse_source_scope_identity_digest_and_context_drift(self):
        for field, value in (
            ("question_id", "heldout-other"),
            ("source_family", "other-family"),
            ("candidate_ids_sha256", "bad"),
            ("source_pool_sha256", "different-pool"),
            ("answer_targets_read", True),
            ("source_excerpts_recorded", True),
        ):
            p, v = fixture()
            v[field] = value
            with self.subTest(field=field), self.assertRaises(AuditError):
                replay_one(p, v)

    def test_reader_failure_keeps_score_geometry_if_selection_was_observed(self):
        p, v = fixture()
        p.update(status="failed", error_type="ReaderError")
        x = replay_all([p], [v])
        self.assertEqual(x["audited_pre_reader_rows"], 1)
        self.assertFalse(x["production_accepted"])

    def test_extra_duplicate_and_missing_score_receipts_fail(self):
        p, v = fixture()
        for rows, vectors in (
            ([p], []),
            ([p], [v, deepcopy(v)]),
            ([p, deepcopy(p)], [v]),
        ):
            with self.assertRaises(AuditError):
                replay_all(rows, vectors)

    def test_nonfinite_null_logit_is_not_retained_as_a_valid_receipt(self):
        policy, vectors = fixture()
        vectors["null_logit"] = float("nan")
        with self.assertRaises(AuditError):
            replay_one(policy, vectors)

    def test_crossarm_frozen_source_feature_identity_must_be_the_same(self):
        baseline, row = fixture()
        learned, row2 = fixture(adapted=True)
        learned["arm"] = row2["arm"]
        # Both are explicitly the same original registered question and pool.
        result = replay_all([baseline, learned], [row, row2])
        self.assertEqual(result["unique_observed_questions"], 1)
        self.assertTrue(result["frozen_input_crossarm_checkpoint_identity_verified"])
        bad, bad_vectors = fixture(adapted=True)
        bad_vectors["original_feature_sha256"] = "f" * 64
        with self.assertRaisesRegex(AuditError, "drifted across arms"):
            replay_all([baseline, bad], [row, bad_vectors])

    def test_frozen_control_cannot_hide_learned_logits_as_baseline(self):
        p, v = fixture()
        p["arm"] = v["arm"] = "frozen_rerank"
        with self.assertRaises(AuditError):
            replay_one(p, v)


if __name__ == "__main__":
    unittest.main()
