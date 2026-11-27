import unittest
import numpy as np
import credit
import build_data


class DelayedCreditTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "epochs": 2,
            "delay_steps": 3,
            "learning_rate": 0.2,
            "decay": 0.95,
            "head_norm_limit": 8.0,
        }

    def test_full_vocabulary_gradient_agrees_with_finite_difference(self):
        logits = np.array([0.7, -0.3, 1.2, -0.8, 0.1])
        base = [logits[0], logits[1], np.logaddexp.reduce(logits[2:])]
        for delta in (-2.0, 0.15, 3.0):
            for target in (0, 1):

                def nll(d):
                    z = logits.copy()
                    z[0] += d
                    z[1] -= d
                    return np.logaddexp.reduce(z) - z[target]

                fd = (nll(delta + 1e-5) - nll(delta - 1e-5)) / 2e-5
                derivative = credit.expectation(base, delta) - (
                    1 if target == 0 else -1
                )
                self.assertAlmostEqual(fd, derivative, places=9)

    def test_routing_changes_updates_without_changing_external_feedback(self):
        packet = {
            "action_id": "a",
            "sequence": 0,
            "available": 3,
            "features": np.eye(2),
            "expectations": [0.1, -0.2],
        }
        feedback = {"action_id": "a", "vector": [1, -1]}
        results = {
            arm: credit.update(np.zeros((2, 2)), packet, feedback, arm, self.plan, 3)
            for arm in credit.ARMS
        }
        self.assertEqual(
            {tuple(r[1]["teacher_input"]) for r in results.values()}, {(1, -1)}
        )
        self.assertGreater(results["routed"][0][0, 0], 0)
        self.assertLess(results["shuffled"][0][0, 0], 0)
        np.testing.assert_array_equal(results["no_eligibility"][0], np.zeros((2, 2)))
        self.assertEqual(results["scalar"][1]["teacher_routed"], [0.0, 0.0])

    def test_feedback_cannot_arrive_early_or_target_another_action(self):
        packet = {
            "action_id": "a",
            "sequence": 0,
            "available": 3,
            "features": np.eye(2),
            "expectations": [0.0, 0.0],
        }
        for now, target in ((2, "a"), (3, "other"), (4, "a")):
            with self.assertRaises(ValueError):
                credit.update(
                    np.zeros((2, 2)),
                    packet,
                    {"action_id": target, "vector": [1, -1]},
                    "routed",
                    self.plan,
                    now,
                )

    def test_seed_pairing_and_complete_delay_drain_are_reproducible(self):
        rng = np.random.default_rng(72)
        f = rng.normal(size=(32, 2, 5))
        f /= np.linalg.norm(f, axis=-1, keepdims=True)
        base = rng.normal(size=(32, 2, 3))
        y = rng.choice((-1, 1), size=(32, 2))
        runs = {
            arm: credit.train(f, base, y, 11, arm, self.plan) for arm in credit.ARMS
        }
        self.assertEqual(len({x[2] for x in runs.values()}), 1)
        for weights, receipts, _ in runs.values():
            self.assertEqual(len(receipts), 64)
            self.assertTrue(
                all(r["sequence"] - r["action_sequence"] == 3 for r in receipts)
            )
            self.assertTrue(np.isfinite(weights).all())
        np.testing.assert_array_equal(runs["no_eligibility"][0], np.zeros((2, 5)))
        again = credit.train(f, base, y, 11, "routed", self.plan)
        np.testing.assert_array_equal(runs["routed"][0], again[0])
        self.assertEqual(runs["routed"][1:], again[1:])

    def test_all_invalid_and_failed_outputs_stay_in_denominator(self):
        rows = [
            {"id": "a", "status": "completed", "text": "Yes."},
            {"id": "b", "status": "completed", "text": "Yes, because blue"},
            {"id": "c", "status": "failed", "text": "No"},
        ]
        self.assertEqual(
            credit.score(rows, {"a": "yes", "b": "yes", "c": "no"}),
            {"n": 3, "valid": 1, "correct": 1, "accuracy_including_invalid": 1 / 3},
        )
        with self.assertRaises(ValueError):
            credit.score(rows + rows[:1], {"a": "yes", "b": "yes", "c": "no"})
        self.assertEqual(
            credit.generation_counts(rows),
            {
                "generation_attempts": 3,
                "completed_generations": 2,
                "failed_generations": 1,
                "actual_generations": 2,
            },
        )
        with self.assertRaises(ValueError):
            credit.generation_counts([{"status": "unknown"}])

    def test_template_audit_rejects_label_confounded_prompts(self):
        tasks, labels = [], {}
        for group in (0, 1):
            for template, prefix in (
                ("assigned", "The "),
                ("read-fact", "Read this fact:"),
            ):
                for label in ("yes", "no"):
                    key = f"{group}-{template}-{label}"
                    tasks.append(
                        {
                            "id": key,
                            "split": "content",
                            "group": group,
                            "template_id": template,
                            "question": prefix + key,
                        }
                    )
                    labels[key] = label
        build_data.audit_templates(tasks, labels)
        # Reproduce the old parity confound: YES uses one template, NO the other.
        for row in tasks:
            yes = labels[row["id"]] == "yes"
            row["template_id"] = "read-fact" if yes else "assigned"
            row["question"] = ("Read this fact:" if yes else "The ") + row["id"]
        with self.assertRaisesRegex(ValueError, "confounded"):
            build_data.audit_templates(tasks, labels)


if __name__ == "__main__":
    unittest.main()
