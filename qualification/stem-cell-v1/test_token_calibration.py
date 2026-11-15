"""Actual token trajectories, offline target order and source isolation."""
from dataclasses import replace
from hashlib import sha256
import unittest
from unittest.mock import patch

import torch

from multirc_data import ReaderCase
from token_calibration import collect_token_critic_rows, fit_token_critic_metered
from token_execution import execute_token_reader
from token_protocol import build_binding_cases
from token_reader import TokenReader


def case(index, label=0):
    return ReaderCase(str(index), "q", "a", "A public question", "A public answer",
                      ("First fact", "Second fact"), label, "train",
                      sha256(f"source/{index}".encode()).hexdigest())


class RecordingReader(TokenReader):
    def __init__(self, source):
        super().__init__(8, 8, max_hops=3)
        self.training_source_groups = (source,)
        self.calls = 0

    def step_prepared(self, *args, **kwargs):
        self.calls += 1
        return super().step_prepared(*args, **kwargs)


class Bank:
    def __init__(self):
        self.calls = []
        self.features = dict(facts=torch.randn(1, 2, 3, 8), question=torch.randn(1, 4, 8),
            candidate=torch.randn(1, 2, 8), fact_mask=torch.ones(1, 2, 3, dtype=torch.bool),
            question_mask=torch.ones(1, 4, dtype=torch.bool), candidate_mask=torch.ones(1, 2, dtype=torch.bool),
            sentence_indices=torch.tensor([[0, 1]]), feature_sha256="a" * 64)

    def public(self, item):
        self.calls.append(item.case_id)
        return dict(self.features, source_sha256=item.source_hash)


class GuardedOutcome:
    def __init__(self, item, check):
        self.item, self.check = item, check

    def __getattr__(self, key):
        if key == "label":
            self.check()
        return getattr(self.item, key)


class TokenCalibrationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(51)
        self.model = RecordingReader("reader").eval().requires_grad_(False)
        self.verifier = RecordingReader("verifier").eval().requires_grad_(False)
        self.bank = Bank()

    def collect(self, cases=None, **kwargs):
        return collect_token_critic_rows(self.model, self.verifier, self.bank,
            [case(1), case(2, 1)] if cases is None else cases, **kwargs)

    def test_all_public_trajectories_precede_labels_and_targets_are_exact_next_hop(self):
        def finished():
            self.assertEqual((self.model.calls, self.verifier.calls), (6, 6))
        guarded = [GuardedOutcome(case(i), finished) for i in (1, 2)]
        rows, receipt = self.collect(guarded)
        self.assertEqual((len(rows), receipt["cases"], receipt["gradient_updates"]), (4, 2, 0))
        for index, trajectory in enumerate(receipt["trajectories"]):
            for hop, record in enumerate(trajectory["steps"][:-1]):
                row = rows[index * 2 + hop]
                self.assertEqual((row["features"], row["stop_success"], row["continue_success"]),
                    (record["critic_features"], record["prediction"] == trajectory["offline_label"],
                     trajectory["steps"][hop+1]["prediction"] == trajectory["offline_label"]))
                self.assertGreaterEqual(row["observed_at_ns"], receipt["public_trajectories_finished_at_ns"])
        self.assertEqual(receipt["model_digests_before"], receipt["model_digests_after"])
        self.assertTrue(receipt["all_public_trajectories_precede_any_label"])
        self.assertGreater(receipt["formula_flops"], 0)
        self.assertGreaterEqual(receipt["cpu_ns"], receipt["execution_cpu_ns"])
        self.assertGreater(receipt["callback_empirical_maxima"]["proposer"]["formula_flops"], 0)
        self.assertFalse(receipt["future_support_guaranteed"])

    def test_poisoned_labels_change_only_offline_success(self):
        rows, receipt = self.collect([case(1)])
        poisoned, second = self.collect([case(1, 1)])
        def observable(result):
            return [{key: value for key, value in record.items() if key != "callback_costs"}
                    for record in result["trajectories"][0]["steps"]]
        self.assertEqual(observable(receipt), observable(second))
        for left, right in zip(rows, poisoned):
            self.assertEqual(left["features"], right["features"])
            self.assertEqual((left["stop_success"], left["continue_success"]),
                             (not right["stop_success"], not right["continue_success"]))

    def test_final_synthetic_duplicate_and_fit_overlap_reject_before_bank(self):
        invalid = ([replace(case(1), source_split="validation")], build_binding_cases(groups=1),
                   [case(1), case(1)], [case(9)])
        self.model.training_source_groups = (case(9).source_hash,)
        for cases in invalid:
            with self.assertRaises(ValueError):
                self.collect(cases)
        self.assertEqual(self.bank.calls, [])
        self.model.train()
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.collect()
        self.model.eval()
        with self.assertRaises(ValueError):
            self.collect(max_steps=2)

    def test_incomplete_formula_profile_stays_unknown(self):
        def unknown(*args, **kwargs):
            result = execute_token_reader(*args, **kwargs)
            result["work_observation"]["unknown_operators"] = {"unmodeled": 1}
            result["request_costs"]["complete_formula_flops"] = None
            return result
        with patch("token_calibration.execute_token_reader", side_effect=unknown):
            _, receipt = self.collect([case(1)])
        self.assertIsNone(receipt["formula_flops"])
        self.assertIsNone(receipt["empirical_next_hop_maximum"]["formula_flops"])

    def test_actual_frozen_critic_fit_and_source_overlap(self):
        fit, _ = self.collect([case(1)], split="fit")
        calibration, _ = self.collect([case(2)], split="calibration")
        critic, receipt = fit_token_critic_metered(fit, calibration, steps=2)
        critic.assert_frozen()
        self.assertEqual(receipt["schema"], "hepta.token-reader.metered-critic-fit.v1")
        self.assertGreater(receipt["work_observation"]["phase_flops"]["train"], 0)
        with self.assertRaisesRegex(ValueError, "overlap"):
            fit_token_critic_metered(fit, [dict(row, source_group=fit[0]["source_group"]) for row in calibration], steps=1)


if __name__ == "__main__":
    unittest.main()
