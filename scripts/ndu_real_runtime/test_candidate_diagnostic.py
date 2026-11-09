"""Contract fixtures only; no real quality, training or ROI benefit evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .candidate_diagnostic import DEVELOPMENT_SCHEMA, episode_diagnostic
from .objective import canonical_sha
from .trajectory import V2_SCHEMA


def episode(
    actions=("PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "STOP"),
    covered=(False, False, True, True),
    text="ACME",
    role="train",
):
    case = {"id": "fixture-case", "source_id": "fixture-source", "role": role}
    packet = {
        "case_id": case["id"],
        "requirements": {"text": True, "image": False},
        "initial_delivery": {"text": None, "image": None},
    }
    rows, steps = [], []
    for index, action in enumerate(actions):
        candidates = [
            {"text": value, "bbox": [0, 0, 10, 10], "origin": "pixel_ocr"}
            for value in (("ACME", "OTHER") if covered[index] else ("ELSE", "OTHER"))
        ]
        meta = [
            1.0,
            0.0,
            0.0,
            0.0,
            float("WRITE_TEXT" in actions[:index]),
            0.0,
            1.0,
            0.0,
            float("PREPARE_ROI" in actions[:index]),
            float("READ_ROI" in actions[:index]),
            0.0,
            0.0,
            0.1,
            index / 8,
            (10 - index) / 10,
            0.0,
        ]
        row = {
            "schema": V2_SCHEMA if role == "train" else DEVELOPMENT_SCHEMA,
            "record_id": f"attempt/{index}",
            "origin_run_id": "attempt",
            "episode_id": case["id"],
            "source_group": case["source_id"],
            "split": role,
            "episode_step": index,
            "source_size": {"width": 100, "height": 100},
            "candidate_metadata": candidates,
            "candidate_features": [[index * 0.01] * 126] * 2,
            "public_metadata": meta,
            "reference_field": "company",
            "expected_text": "ACME",
            "target_boxes": [[0, 0, 10, 10]],
            "before_score": 0.0,
            "after_score": 0.0,
            "duration_seconds": 0.25,
            "execution_status": "completed",
            "action": action,
            "memory_mode": "reset",
            "remaining_seconds": 10 - index,
            "legal_actions": [
                "PREPARE_ROI",
                "READ_ROI",
                "WRITE_TEXT",
                "RENDER_IMAGE",
                "STOP",
            ],
            "utility_profile_sha256": "a" * 64,
            "rubric_sha256": "b" * 64,
            "behavior_control_profile_sha256": "c" * 64,
            "terminal_reason": "actor_stop"
            if action == "STOP"
            else "budget_stop"
            if index + 1 == len(actions)
            else None,
        }
        rows.append(row)
        steps.append(
            {
                "case_id": case["id"],
                "step": index,
                "action": {
                    "action": action,
                    "arguments": {"text": text} if action == "WRITE_TEXT" else {},
                },
                "candidate_metadata": copy.deepcopy(candidates),
                "candidate_features": copy.deepcopy(row["candidate_features"]),
                "public_metadata": copy.deepcopy(meta),
                "observed_action_seconds": 0.25,
            }
        )
    rehash(rows)
    return case, packet, rows, {"steps": steps}


def rehash(rows):
    for index, row in enumerate(rows):
        row["next_candidate_features"] = (
            rows[index + 1]["candidate_features"] if index + 1 < len(rows) else None
        )
        row["next_public_metadata"] = (
            rows[index + 1]["public_metadata"] if index + 1 < len(rows) else None
        )
        row["previous_record_sha256"] = (
            rows[index - 1]["record_sha256"] if index else None
        )
        row["record_sha256"] = canonical_sha(
            {k: v for k, v in row.items() if k != "record_sha256"}
        )


class CandidateDiagnosticTests(unittest.TestCase):
    def test_real_chain_shape_separates_coverage_gain_and_successful_write(self):
        result = episode_diagnostic(*episode())
        self.assertEqual(
            [r["decision"] for r in result["rows"]],
            [
                "prepare_roi",
                "read_roi",
                "write_correct",
                "stop_after_reconstructed_text_success",
            ],
        )
        self.assertEqual(result["roi_reads"][0]["outcome"], "coverage_gained")
        self.assertEqual(
            (
                result["observed_action_seconds"],
                result["roi_reads"][0]["preparation_seconds"],
                result["roi_reads"][0]["read_seconds"],
            ),
            (1.0, 0.25, 0.25),
        )

    def test_missing_candidate_and_wrong_ranking_are_different(self):
        for covered, expected in (
            (False, "write_without_correct_candidate"),
            (True, "ranking_error"),
        ):
            with self.subTest(covered=covered):
                result = episode_diagnostic(
                    *episode(("WRITE_TEXT", "STOP"), (covered, covered), "OTHER")
                )
                self.assertEqual(
                    [r["decision"] for r in result["rows"]],
                    [expected, "stop_with_unmet_reconstructed_text"],
                )
                self.assertFalse(result["reconstructed_text_correct"])

    def test_stop_is_not_assumed_to_be_ranking_or_candidate_failure(self):
        for covered in (False, True):
            result = episode_diagnostic(*episode(("STOP",), (covered,)))
            self.assertEqual(
                result["rows"][0]["decision"], "stop_with_unmet_reconstructed_text"
            )
            self.assertEqual(result["rows"][0]["correct_candidate_count"], int(covered))

    def test_initial_public_commitment_survives_stop(self):
        args = list(episode(("STOP",), (False,)))
        args[1]["initial_delivery"]["text"] = "ACME"
        result = episode_diagnostic(*args)
        self.assertEqual(
            result["rows"][0]["decision"], "stop_after_reconstructed_text_success"
        )

    def test_outside_candidate_write_does_not_establish_ranking_error(self):
        result = episode_diagnostic(
            *episode(("WRITE_TEXT", "STOP"), (True, True), "UNOBSERVED")
        )
        self.assertEqual(result["rows"][0]["decision"], "out_of_candidate_write")
        self.assertEqual(result["rows"][0]["correct_candidate_count"], 1)

    def test_missing_or_conflicting_final_delivery_preserves_uncertainty(self):
        result = episode_diagnostic(*episode())
        self.assertTrue(result["reconstructed_text_correct"])
        self.assertIsNone(result["observed_final_text_correct"])
        self.assertIsNone(result["final_delivery_matches_reconstruction"])
        result = episode_diagnostic(
            *episode(), {"case_id": "fixture-case", "text": "OTHER"}
        )
        self.assertTrue(result["reconstructed_text_correct"])
        self.assertFalse(result["observed_final_text_correct"])
        self.assertFalse(result["final_delivery_matches_reconstruction"])
        self.assertEqual(result["observed_action_seconds"], 1.0)

    def test_roi_unknown_is_not_counted_as_gain(self):
        result = episode_diagnostic(
            *episode(("PREPARE_ROI", "READ_ROI"), (False, False))
        )
        self.assertEqual(result["roi_reads"][0]["outcome"], "successor_unobserved")
        self.assertIsNone(result["roi_reads"][0]["after_covered"])

    def test_roi_loss_and_still_missing_remain_visible(self):
        for covered, outcome in (
            ((True, True, False), "coverage_lost"),
            ((False, False, False), "still_missing"),
            ((True, True, True), "coverage_retained"),
        ):
            result = episode_diagnostic(
                *episode(("PREPARE_ROI", "READ_ROI", "STOP"), covered)
            )
            self.assertEqual(result["roi_reads"][0]["outcome"], outcome)

    def test_repeated_reads_do_not_recharge_preparation(self):
        result = episode_diagnostic(
            *episode(
                ("PREPARE_ROI", "READ_ROI", "READ_ROI", "STOP"),
                (False, False, True, True),
            )
        )
        self.assertEqual(
            [r["preparation_seconds"] for r in result["roi_reads"]], [0.25, 0]
        )
        self.assertEqual(result["observed_action_seconds"], 1.0)

    def test_unused_preparation_and_failed_actions_are_not_free(self):
        args = episode(("PREPARE_ROI", "STOP"), (False, False))
        result = episode_diagnostic(*args)
        self.assertEqual(
            (
                result["unconsumed_preparation_seconds"],
                result["observed_action_seconds"],
            ),
            (0.25, 0.5),
        )
        args[2][0]["execution_status"] = "failed"
        rehash(args[2])
        result = episode_diagnostic(*args)
        self.assertEqual(result["rows"][0]["decision"], "execution_failed")
        self.assertEqual(result["observed_action_seconds"], 0.5)

    def test_every_holdout_role_rejected_before_observation_access(self):
        for role in ("confirmation", "retention_test", "retention_validation"):
            with (
                self.subTest(role=role),
                self.assertRaisesRegex(ValueError, "Only train/development"),
            ):
                episode_diagnostic({"role": role}, {}, [], {})
            with (
                self.subTest(role=role),
                self.assertRaisesRegex(ValueError, "Only train/development"),
            ):
                diagnose(
                    {"schema": "ndu.real.candidate-diagnostic-plan.v1", "roles": [role]}
                )

    def test_development_is_explicit_and_does_not_relabel_training_schema(self):
        args = episode(role="development")
        self.assertTrue(episode_diagnostic(*args)["reconstructed_text_correct"])
        args[2][0]["schema"] = V2_SCHEMA
        rehash(args[2])
        with self.assertRaisesRegex(ValueError, "Role, source"):
            episode_diagnostic(*args)

    def test_modified_source_or_trajectory_or_final_delivery_rejected(self):
        args = episode()
        args[2][1]["source_group"] = "foreign"
        rehash(args[2])
        with self.assertRaisesRegex(ValueError, "Role, source"):
            episode_diagnostic(*args)
        args = episode()
        args[3]["steps"][0]["candidate_metadata"][0]["text"] = "modified"
        with self.assertRaisesRegex(ValueError, "trajectory"):
            episode_diagnostic(*args)
        with self.assertRaisesRegex(ValueError, "Final delivery"):
            episode_diagnostic(*episode(), {"case_id": "other-case", "text": "ACME"})

    def test_chain_mutation_and_nonfinite_cost_rejected(self):
        args = episode()
        args[2][1]["before_score"] = 0.5
        rehash(args[2])
        with self.assertRaisesRegex(ValueError, "chain"):
            episode_diagnostic(*args)
        args = episode()
        args[2][0]["duration_seconds"] = float("nan")
        with self.assertRaises(ValueError):
            episode_diagnostic(*args)


if __name__ == "__main__":
    unittest.main()
