"""Original sharded Reader results must never be reordered or selectively scored."""

import copy
import math
import unittest

from stage1_reader_pair import verify_frozen_shard_attempts


ARMS = ["empty", "retrieved1", "reviewed_minimal", "reviewed_without_premise1"]


def fixture():
    plan = {"cases": []}
    raw = []
    scored = []
    identity = {"model_digest": "immutable-reader"}
    for index in range(2):
        case = {
            "question": {"identity": f"case-{index}"},
            "family": f"family-{index}",
            "phase": "capability",
            "conditions": {},
        }
        for arm in ARMS:
            missing = index == 1 and arm.startswith("reviewed_")
            evidence = (
                {"status": "unavailable", "reason": "missing external review"}
                if missing
                else {
                    "token_limit": 1024,
                    "delivered_evidence": (
                        [] if arm == "empty" else [{"label": "E1", "excerpt": "source"}]
                    ),
                }
            )
            case["conditions"][arm] = evidence
            row = {
                "question_id": case["question"]["identity"],
                "arm": arm,
                "family": case["family"],
                "phase": "capability",
                "status": "unavailable" if missing else "succeeded",
            }
            if missing:
                row["reason"] = "missing external review"
            else:
                row.update(
                    answer="original model output",
                    receipt={
                        "reader_identity": identity["model_digest"],
                        "trainable_parameters": 0,
                        "answer_postprocessed": False,
                        "delivered_evidence": evidence["delivered_evidence"],
                        "input_tokens": 120,
                        "generated_tokens": 5,
                        "seconds": 1.0,
                        "input_ids_digest": "a" * 64,
                        "generated_ids_digest": "b" * 64,
                    },
                )
            raw.append(copy.deepcopy(row))
            scored.append(
                copy.deepcopy(row)
                | {
                    "f1": 0.5 if not missing else None,
                    "exact_match": 0.0 if not missing else None,
                    "target_unanswerable": False if not missing else None,
                }
            )
        plan["cases"].append(case)
    return plan, ARMS, identity, raw, scored


class ShardIntegrityTests(unittest.TestCase):
    def test_complete_unmodified_journal(self):
        report = verify_frozen_shard_attempts(*fixture())
        self.assertEqual(
            (report["planned"], report["succeeded"], report["unavailable"]),
            (8, 6, 2),
        )
        self.assertFalse(report["production_accepted"])

    def test_reordering_both_journals_does_not_change_registration(self):
        args = list(fixture())
        for records in args[3:]:
            records[0], records[1] = records[1], records[0]
        with self.assertRaisesRegex(ValueError, "slot order"):
            verify_frozen_shard_attempts(*args)

    def test_modified_answer_rejected(self):
        args = list(fixture())
        args[4][0]["answer"] = "posthoc rewritten"
        with self.assertRaisesRegex(ValueError, "raw/scored answer"):
            verify_frozen_shard_attempts(*args)

    def test_unavailable_review_cannot_be_fabricated(self):
        args = list(fixture())
        for records in args[3:]:
            records[6]["status"] = "succeeded"
        with self.assertRaisesRegex(ValueError, "unavailable oracle"):
            verify_frozen_shard_attempts(*args)

    def test_changed_delivered_source_rejected(self):
        args = list(fixture())
        for records in args[3:]:
            records[1]["receipt"]["delivered_evidence"] = []
        with self.assertRaisesRegex(ValueError, "actual delivered source"):
            verify_frozen_shard_attempts(*args)

    def test_cost_cannot_be_negative_nan_or_over_budget(self):
        for name, invalid in (
            ("seconds", -1),
            ("seconds", math.nan),
            ("input_tokens", 1025),
            ("generated_tokens", 65),
        ):
            args = list(fixture())
            for records in args[3:]:
                records[0]["receipt"][name] = invalid
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "resource receipt"),
            ):
                verify_frozen_shard_attempts(*args)

    def test_missing_generation_token_identity_rejected(self):
        args = list(fixture())
        for records in args[3:]:
            records[0]["receipt"].pop("generated_ids_digest")
        with self.assertRaisesRegex(ValueError, "token digest"):
            verify_frozen_shard_attempts(*args)

    def test_bad_model_identity_rejected(self):
        args = list(fixture())
        for records in args[3:]:
            records[0]["receipt"]["reader_identity"] = "other-model"
        with self.assertRaisesRegex(ValueError, "reader weights"):
            verify_frozen_shard_attempts(*args)


if __name__ == "__main__":
    unittest.main()
