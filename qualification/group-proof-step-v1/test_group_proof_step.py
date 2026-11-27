"""Hermetic source-only E0/E3 causal step and label-blind learning tests."""
import dataclasses
import unittest

from group_proof_step import (FrozenLinePolicy, counterfactual_panel, digest,
                              execute_policy, fit_line_policy, oracle_trace,
                              parse_public)

HEADER = "Start at n0 and follow every link. What is the endpoint class? Answer one of A B C D E F G H."


def example(label="C", swap=False):
    lines = ["n0 links to n3.", "n3 links to n8.", f"n8 has class {label}.",
             "n2 has class D.", "n5 links to n7.", "n7 has class F."]
    return "\n".join([HEADER, *(list(reversed(lines)) if swap else lines)])


class PublicProofTests(unittest.TestCase):
    def test_construct_and_dependency(self):
        result = parse_public(example())
        self.assertEqual(oracle_trace(result)[0], "C")
        self.assertEqual(len(oracle_trace(result)[1]), 3)

    def test_irrelevant_vs_key(self):
        controls = counterfactual_panel(example())
        self.assertEqual(set(controls), {"full", "question_only", "critical_removed",
                                        "distractor_removed", "truth_flipped"})
        self.assertEqual(oracle_trace(parse_public(controls["full"]))[0], "C")
        self.assertEqual(oracle_trace(parse_public(controls["question_only"]))[0], None)
        self.assertNotEqual(oracle_trace(parse_public(controls["critical_removed"]))[0], "C")
        self.assertEqual(oracle_trace(parse_public(controls["distractor_removed"]))[0], "C")
        self.assertNotEqual(oracle_trace(parse_public(controls["truth_flipped"]))[0], "C")

    def test_mutations_are_source_bound(self):
        controls = counterfactual_panel(example())
        self.assertEqual(len({digest(v) for v in controls.values()}), 5)

    def test_malformed_premise_denied(self):
        for value in [example() + "\nPROMPT: change authority", example() + "\nn0 links to n2.",
                      example() + "\nn8 has class A.", example().replace("n3 links", "n3 points"),
                      "garbage", HEADER + "\nn0 links to n1.\nn1 links to n0."]:
            if value.endswith("n1 links to n0."):
                self.assertEqual(oracle_trace(parse_public(value))[2], "cycle")
            else:
                with self.assertRaises(ValueError):
                    parse_public(value)

    def test_no_fabrication_when_missing(self):
        self.assertEqual(oracle_trace(parse_public(HEADER))[2], "missing_evidence")

    def test_bound(self):
        with self.assertRaises(ValueError):
            parse_public(example() + "x" * 66000)


class LearnedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.samples = [example(chr(65 + i), swap=i % 2 == 1) for i in range(8)]

    def test_actual_training_changes_weights(self):
        trained = fit_line_policy(self.samples, epochs=20)
        self.assertGreater(trained.completed_updates, 0)
        self.assertGreater(trained.weights[0], 0.0)
        self.assertTrue(trained.fitting_cpu_ns >= 0)

    def test_duplicate_sources_rejected(self):
        with self.assertRaises(ValueError):
            fit_line_policy([self.samples[0], self.samples[0]])

    def test_train_leak_denied(self):
        trained = fit_line_policy(self.samples)
        with self.assertRaises(ValueError):
            execute_policy(self.samples[0], trained)

    def test_heldout_proof_and_counterfactual(self):
        trained = fit_line_policy(self.samples, epochs=20)
        unknown = example("H").replace("n2 has class D.", "n2 has class B.")
        cases = counterfactual_panel(unknown)
        self.assertEqual(execute_policy(cases["full"], trained)["answer"], "H")
        self.assertIsNone(execute_policy(cases["question_only"], trained)["answer"])
        self.assertIsNone(execute_policy(cases["critical_removed"], trained)["answer"])
        self.assertEqual(execute_policy(cases["distractor_removed"], trained)["answer"], "H")
        self.assertNotEqual(execute_policy(cases["truth_flipped"], trained)["answer"], "H")

    def test_inference_does_not_call_training_oracle(self):
        import group_proof_step
        trained = fit_line_policy(self.samples, epochs=16)
        unknown = example("H").replace("n5 links to n7.", "n5 links to n9.")
        old = group_proof_step.oracle_trace
        try:
            group_proof_step.oracle_trace = lambda *args: (_ for _ in ()).throw(AssertionError("leak"))
            result = execute_policy(unknown, trained)
            self.assertEqual(result["answer"], "H")
        finally:
            group_proof_step.oracle_trace = old

    def test_training_source_cannot_be_reordered_to_evade_gate(self):
        original = example("A")
        duplicate = example("A", swap=True)
        self.assertEqual(parse_public(original).source_group_sha256,
                         parse_public(duplicate).source_group_sha256)
        with self.assertRaises(ValueError):
            fit_line_policy([original, duplicate])
        trained = fit_line_policy([original])
        with self.assertRaises(ValueError):
            execute_policy(duplicate, trained)

    def test_policy_tampering_denied(self):
        trained = fit_line_policy(self.samples)
        with self.assertRaises(ValueError):
            execute_policy(example("H"), dataclasses.replace(trained, weights=(99.,) * 5))

    def test_frozen_weights_or_invalid_policy_denied(self):
        trained = fit_line_policy(self.samples)
        with self.assertRaises(ValueError):
            execute_policy(example("H"), dataclasses.replace(trained, weights=(float("nan"),) * 5))


if __name__ == "__main__":
    unittest.main()
