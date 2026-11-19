"""Original V4 generator TRAIN/TUNE only; never opens FINAL or V5 fresh domains."""
from collections import defaultdict
import unittest

from token_protocol import build_binding_cases
from structural_null_v8 import infer_case, infer_public, run_panel, RejectGrammar


class NativeSourceNull(unittest.TestCase):
    def test_old_train_and_tune_not_a_hard_reasoning_benchmark(self):
        for split, groups in (("train", 32), ("tune", 16)):
            with self.subTest(split=split):
                cases = build_binding_cases(split, groups=groups, seed=41)
                self.assertEqual(len(cases), groups * 4)
                self.assertEqual(run_panel(cases)["correct"], len(cases))
                self.assertTrue(all(infer_case(c)[0] == c.label for c in cases))

    def test_actual_counterfactual_world_pair_trace(self):
        cases = build_binding_cases("train", groups=8, seed=41)
        by_candidate = defaultdict(list)
        for case in cases:
            prefix, _ = case.paragraph_id.rsplit('/world-', 1)
            by_candidate[(prefix, case.question, case.candidate)].append(case)
        self.assertEqual(len(by_candidate), 16)
        for left, right in by_candidate.values():
            self.assertNotEqual(left.label, right.label)
            self.assertEqual({infer_case(left)[0], infer_case(right)[0]}, {0, 1})
            for case in (left, right):
                pred, proof = infer_case(case)
                self.assertEqual(pred, case.label)
                self.assertEqual(len(proof), 2)
                # As a diagnostic only, original support is never passed to the solver.
                self.assertEqual(proof, case.evidence_sentence_indices)

    def test_source_wording_mutation_rejected(self):
        case = build_binding_cases("train", groups=1, seed=41)[0]
        corrupted = tuple(case.facts[:-1]) + ("An unrelated clause.",)
        with self.assertRaises(RejectGrammar):
            infer_public(corrupted, case.question, case.candidate)


if __name__ == '__main__':
    unittest.main()
