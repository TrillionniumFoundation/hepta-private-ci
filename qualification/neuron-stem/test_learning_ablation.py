"""Offline Cell learning proof tests. No weights, access grants or NDU claims."""
import unittest

from statistical_gate import qualify


REV = "a" * 40


def sample_fixture(two_tasks=False):
    rows, base, frozen, trained = [], [], [], []
    tasks = ("decision", "value") if two_tasks else ("decision",)
    for task in tasks:
        for split, count, time in (("train", 2, 1), ("calibration", 3, 2),
                                   ("test", 5, 3), ("future", 40, 4), ("ood", 3, 5)):
            for i in range(count):
                case = f"{task}/{split}/{i}"
                rows.append({
                    "case_id": case, "group_id": case, "scope_id": task,
                    "task_id": task, "split": split, "language": "zh",
                    "state": f"state {case}", "question": "Does test item qualify?",
                    "options": ["yes", "no"], "label": 0,
                    "event_time": f"2026-01-0{time}T00:00:00Z",
                })
                if split == "train":
                    continue
                properties = {
                    "case_id": case, "scope_id": task,
                    "model_revision": REV, "encoder_digest": "encoder",
                    "runtime_generation": 1, "status": "Succeeded",
                }
                base.append({
                    **properties, "model_id": "no-change",
                    "head_digest": "original", "probabilities": [.2, .8],
                })
                frozen.append({
                    **properties, "model_id": "jina-v5/frozen-head",
                    "head_digest": "initialized-not-trained",
                    "probabilities": [.3, .7],
                })
                trained.append({
                    **properties, "model_id": "jina-v5",
                    "head_digest": "learned-trained-weights",
                    "probabilities": [.99, .01],
                })
    return rows, base, frozen, trained


class LearningGateTests(unittest.TestCase):
    def test_requires_both_frozen_and_nochange(self):
        rows, base, frozen, trained = sample_fixture()
        only_nochange = qualify(rows, base, trained, replicates=1000)
        self.assertTrue(only_nochange["offline_quality_gate_passed"])
        self.assertFalse(only_nochange["cell_learning_gate_passed"])
        self.assertFalse(only_nochange["matched_frozen_head_present"])
        both = qualify(rows, base, trained, frozen_head=frozen, replicates=1000)
        self.assertTrue(both["offline_quality_gate_passed"])
        self.assertTrue(both["cell_learning_gate_passed"])
        self.assertTrue(both["matched_frozen_head_present"])
        self.assertFalse(both["production_promotion_permitted"])
        self.assertFalse(both["ndu_independent_signature_verified"])
        self.assertEqual(both["frozen_head_evaluation"]["future"]["independent_groups"], 40)
        self.assertEqual(both["frozen_head_predictions_sha256"] is not None, True)

    def test_frozen_revision_and_feature_binding_fail_closed(self):
        rows, base, frozen, trained = sample_fixture()
        invalid = [dict(p) for p in frozen]
        invalid[0]["encoder_digest"] = "different-encoder"
        with self.assertRaisesRegex(ValueError, "bound to candidate"):
            qualify(rows, base, trained, frozen_head=invalid, replicates=1000)
        invalid = [dict(p) for p in frozen]
        invalid[0]["head_digest"] = "learned-trained-weights"
        with self.assertRaisesRegex(ValueError, "identical"):
            qualify(rows, base, trained, frozen_head=invalid, replicates=1000)

    def test_task_scoping_requires_full_data_audit(self):
        rows, base, frozen, trained = sample_fixture(two_tasks=True)
        result = qualify(rows, base, trained, frozen_head=frozen,
                         task_id="value", replicates=1000)
        self.assertEqual(result["selected_task_id"], "value")
        self.assertEqual(result["dataset"]["tasks"], 1)
        self.assertTrue(result["cell_learning_gate_passed"])
        with self.assertRaisesRegex(ValueError, "no source rows"):
            qualify(rows, base, trained, task_id="not-a-task", replicates=1000)
        tampered = [dict(row) for row in rows]
        tampered[-1]["case_id"] = tampered[0]["case_id"]
        with self.assertRaisesRegex(ValueError, "duplicate case"):
            qualify(tampered, base, trained, task_id="value", replicates=1000)

    def test_no_learning_is_not_cell_learning(self):
        rows, base, frozen, trained = sample_fixture()
        # Use a genuinely better-than-no-change frozen Head, so the candidate
        # can pass the baseline quality gate without gaining anything from
        # training. Previously frozen predicted the wrong label and the
        # asserted positive accuracy gain was mathematically impossible.
        frozen = [{**p, "probabilities": [.99, .01]} for p in frozen]
        fake_learning = [
            {**p, "probabilities": f["probabilities"]} for p, f in zip(trained, frozen)
        ]
        observed = qualify(rows, base, fake_learning, frozen_head=frozen, replicates=1000)
        self.assertTrue(observed["offline_quality_gate_passed"])
        self.assertFalse(observed["cell_learning_gate_passed"])
        self.assertFalse(observed["production_promotion_permitted"])


if __name__ == "__main__":
    unittest.main()
