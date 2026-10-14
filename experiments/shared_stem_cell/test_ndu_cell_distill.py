"""Physical optimizer test over toy immutable supplied vectors; NO real Encoder."""
import hashlib
import unittest

import torch
from ndu_cell_distill import DistillError, Row, _digest_model, evaluate_sealed, fit, predict


def data(split, signs, flipped=False):
    time_base = 1 if split == "train" else 1000
    rows = tuple(Row(f"{split}-{i}", f"{split}-source-{i // 2}", time_base + i,
                     (float(v), 0.0), (0.0, 0.0)) for i, v in enumerate(signs))
    labels = {r.case_id: (int(v > 0) ^ int(flipped)) for r, v in zip(rows, signs)}
    return rows, labels


class DistillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def make_candidate(self):
        train, labels = data("train", [-0.95,-0.85,-0.75,-0.65,-0.55,-0.45,-0.35,-0.25,
                                        0.25,0.35,0.45,0.55,0.65,0.75,0.85,0.95])
        candidate = fit(train, labels, teacher_sha256=hashlib.sha256(b"teacher").hexdigest(),
                        feature_dim=2, state_dim=2, rank=2, steps=110, seed=31)
        return train, candidate

    def test_actual_training_on_toy_policies_and_sealed_future_score(self):
        train, candidate = self.make_candidate()
        self.assertNotEqual(candidate.model_sha256, candidate.initial_sha256)
        self.assertGreater(candidate.train_wall_ns, 0)
        self.assertLessEqual(candidate.parameter_count, 16384)
        future, truth = data("future", [-0.9,-0.8,-0.7,-0.6,-0.5,-0.4,
                                         0.4,0.5,0.6,0.7,0.8,0.9])
        seal = predict(candidate, future)
        score = evaluate_sealed(seal, {r.case_id:(r.group_id, truth[r.case_id]) for r in future})
        self.assertGreaterEqual(score["accuracy"], 0.95)
        self.assertFalse(score["independent_outcome_authenticated"])
        self.assertFalse(score["production_accepted"])
        self.assertEqual(candidate.model_sha256, _digest_model(candidate.model))
        self.assertNotIn("targets", str(seal))

    def test_overlapping_group_or_nonfuture_source_refused(self):
        train, candidate = self.make_candidate()
        with self.assertRaisesRegex(DistillError, "future source"):
            predict(candidate, train)
        future, _ = data("future", [-0.1, 0.1])
        collision = (Row("unique", train[0].group_id, 100, (-0.2, 0), (0, 0)), future[1])
        with self.assertRaisesRegex(DistillError, "future source"):
            predict(candidate, collision)

    def test_future_labels_never_enter_fitting_and_tamper_rejected(self):
        _, candidate = self.make_candidate()
        future, truth = data("future", [-0.8,-0.7,0.7,0.8])
        seal = predict(candidate, future)
        tampered = dict(seal, predictions=[dict(seal["predictions"][0],
                     probabilities=[0.9999, 0.0001]), *seal["predictions"][1:]])
        with self.assertRaisesRegex(DistillError, "altered"):
            evaluate_sealed(tampered, {r.case_id:(r.group_id, truth[r.case_id]) for r in future})
        with self.assertRaisesRegex(DistillError, "coverage"):
            evaluate_sealed(seal, {future[0].case_id:(future[0].group_id, 0)})
        with self.assertRaisesRegex(DistillError, "mismatch"):
            evaluate_sealed(seal, {r.case_id:("wrong-group", truth[r.case_id]) for r in future})

    def test_unauthorized_head_mutation_refused(self):
        _, candidate = self.make_candidate()
        with torch.no_grad():
            candidate.model.output.weight.add_(0.1)
        future, _ = data("future", [-0.9, 0.9])
        with self.assertRaisesRegex(DistillError, "mutated"):
            predict(candidate, future)

    def test_no_invented_generalization_or_old_task_retention(self):
        _, candidate = self.make_candidate()
        future, labels = data("future", [-0.9,-0.8,-0.7,-0.6,-0.5,-0.4,
                                          0.4,0.5,0.6,0.7,0.8,0.9], flipped=True)
        seal = predict(candidate, future)
        score = evaluate_sealed(seal, {r.case_id:(r.group_id, labels[r.case_id]) for r in future})
        self.assertLessEqual(score["accuracy"], 0.05)
        self.assertFalse(score["production_accepted"])

    def test_fit_requires_train_only_complete_labels_and_bounded_sgd(self):
        train, targets = data("train", [-1,-.8,-.6,-.4,.4,.6,.8,1])
        kwargs = dict(teacher_sha256=hashlib.sha256(b"teacher").hexdigest(),
                      feature_dim=2, state_dim=2, rank=2, steps=2)
        with self.assertRaisesRegex(DistillError, "complete labels"):
            fit(train, {train[0].case_id:0}, **kwargs)
        with self.assertRaisesRegex(DistillError, "budget"):
            fit(train, targets, **dict(kwargs, steps=10000))
        with self.assertRaisesRegex(DistillError, "feature"):
            fit(tuple([Row(r.case_id, r.group_id, r.observed_at,
                           (float('nan'),0.0), r.state) for r in train]), targets, **kwargs)

class ExactTeacherClosedLoopTests(unittest.TestCase):
    """P3->P4->P6 toy chain, NOT actual Reader or natural-language reasoning."""
    def test_finite_bsde_policy_is_actually_distilled_into_existing_head(self):
        from fractions import Fraction as F
        from ndu_tree_global import Edge, Node, audit_finite_tree, solve

        torch.set_num_threads(1)
        def expert(probability, cost):
            p, c = F(probability), F(cost)
            nodes = {
                "root": Node("or", (), (Edge("stop", "stop"), Edge("observe", "chance", cost=c))),
                "stop": Node("terminal", (), terminal_utility=F("2/5")),
                "chance": Node("chance", (), (
                    Edge("negative", "neg", probability=1-p),
                    Edge("positive", "pos", probability=p))),
                "neg": Node("terminal", ("negative",), terminal_utility=F(0)),
                "pos": Node("terminal", ("positive",), terminal_utility=F(1)),
            }
            solution = solve(nodes, "root")
            assert audit_finite_tree(nodes, "root", solution)["finite_tree_solved"]
            return int(solution.policy["root"] == "observe")

        def cohort(split, probabilities, costs, *, with_labels=True):
            rows, labels = [], {}
            for i, (p, c) in enumerate((p, c) for p in probabilities for c in costs):
                case_id = f"{split}-{i}"
                row = Row(case_id, f"{split}-source-{i}",
                          (1 if split == "train" else 1000) + i,
                          (float(F(p)), float(F(c))), (float(F(p)-F(c)), 0.0))
                rows.append(row)
                if with_labels:
                    labels[case_id] = expert(p, c)
            return tuple(rows), labels

        train, train_labels = cohort("train", ("1/8", "1/4", "3/8", "1/2", "5/8", "3/4", "7/8"),
                                    ("1/20", "3/20", "1/4"))
        candidate = fit(train, train_labels, teacher_sha256=hashlib.sha256(b"exact-public-tree-v1").hexdigest(),
                        feature_dim=2, state_dim=2, rank=2, steps=180, seed=19)
        future_probs = ("1/5", "3/10", "2/5", "1/2", "3/5", "7/10", "4/5")
        future_costs = ("2/25", "9/50", "7/25")
        future, no_labels = cohort("future", future_probs, future_costs, with_labels=False)
        self.assertFalse(no_labels)
        seal = predict(candidate, future)
        # Compute untouched test truths only AFTER prediction sealing.
        future_labels = {r.case_id: expert(p, c) for r, (p, c)
                         in zip(future, ((p, c) for p in future_probs for c in future_costs))}
        self.assertFalse(seal["production_accepted"])
        result = evaluate_sealed(seal, {r.case_id: (r.group_id, future_labels[r.case_id]) for r in future})
        self.assertGreaterEqual(result["accuracy"], 0.90)
        self.assertFalse(result["independent_outcome_authenticated"])
        self.assertFalse(result["production_accepted"])


if __name__ == "__main__":
    unittest.main()
