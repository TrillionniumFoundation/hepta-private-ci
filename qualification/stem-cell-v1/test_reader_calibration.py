"""Continuation target alignment, outcome isolation and strict actual work."""

import copy
from dataclasses import replace
from hashlib import sha256
import unittest

import torch

from group_reader import Reader
from multirc_data import ReaderCase
from reader_calibration import collect_critic_rows, fit_critic_metered


def case(index, label=0, source_split="train"):
    return ReaderCase(str(index), "question", "candidate", "Public question", "Public answer",
                      ("First fact", "Second fact"), label, source_split,
                      sha256(f"source/{index}".encode()).hexdigest())


class Bank:
    def __init__(self):
        self.calls = []
        self.facts = torch.arange(24, dtype=torch.float32).reshape(1, 3, 8) / 24
        self.query = torch.arange(8, dtype=torch.float32).reshape(1, 8) / 8

    def public(self, item):
        self.calls.append(item.case_id)
        return dict(facts=self.facts, query=self.query, mask=torch.ones(1, 3, dtype=torch.bool),
                    feature_sha256=sha256(b"public snapshot").hexdigest(), source_sha256=item.source_hash)


class RecordingReader(Reader):
    def __init__(self):
        super().__init__(8, 8, max_hops=3)
        self.recorded = []

    def step(self, facts, query, state=None, feedback=None, mask=None):
        self.recorded.append(dict(state_none=state is None,
                                  feedback=None if feedback is None else feedback.detach().tolist()))
        return super().step(facts, query, state, feedback, mask)


class ReaderCalibrationTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(19)
        torch.set_num_threads(1)
        self.model = RecordingReader().eval().requires_grad_(False)
        self.verifier = RecordingReader().eval().requires_grad_(False)
        self.bank = Bank()

    def collect(self, cases=None, **kwargs):
        return collect_critic_rows(self.model, self.verifier, self.bank,
                                   cases if cases is not None else [case(1), case(2, 1)], **kwargs)

    def test_exact_next_target_feedback_and_full_strict_callback_work(self):
        before = copy.deepcopy(self.model.state_dict())
        rows, receipt = self.collect()
        self.assertEqual((len(rows), receipt["cases"], receipt["rows"]), (4, 2, 4))
        offset = 0
        for trajectory in receipt["trajectories"]:
            for i, step in enumerate(trajectory["steps"][:-1]):
                self.assertEqual((rows[offset]["features"], rows[offset]["stop_success"], rows[offset]["continue_success"]),
                                 (step["features"], step["prediction"] == trajectory["offline_label"],
                                  trajectory["steps"][i + 1]["prediction"] == trajectory["offline_label"]))
                self.assertEqual(len(rows[offset]["features"]), 6)
                offset += 1
        self.assertEqual(self.model.recorded[1]["feedback"], receipt["trajectories"][0]["steps"][0]["feedback"])
        self.assertTrue(all(call["state_none"] and call["feedback"] is None for call in self.verifier.recorded))
        scopes = {row["component"]: row for row in receipt["work_observation"]["scopes"] if row["phase"] == "search"}
        self.assertEqual({name: row["calls"] for name, row in scopes.items()}, {"proposer": 6, "verifier": 6, "value": 4})
        self.assertEqual(receipt["work_observation"]["unknown_operators"], {})
        self.assertGreater(receipt["empirical_next_hop_maximum"]["formula_flops"], 0)
        self.assertEqual(receipt["empirical_next_hop_maximum"]["observed_segments"], 4)
        self.assertFalse(receipt["future_support_guaranteed"])
        self.assertEqual(receipt["model_digests_before"], receipt["model_digests_after"])
        self.assertTrue(all(torch.equal(before[key], value) for key, value in self.model.state_dict().items()))

    def test_label_poisoning_changes_only_offline_targets_not_trajectory(self):
        original = [case(1)]
        rows, receipt = self.collect(original)
        poisoned_rows, poisoned_receipt = self.collect([replace(original[0], label=1)])
        def public_steps(result):
            return [(r["prediction"], r["features"], r["feedback"], r["verifier"])
                    for r in result["trajectories"][0]["steps"]]
        self.assertEqual(public_steps(receipt), public_steps(poisoned_receipt))
        for original, poisoned in zip(rows, poisoned_rows):
            self.assertEqual(original["features"], poisoned["features"])
            self.assertEqual((original["stop_success"], original["continue_success"]),
                             (not poisoned["stop_success"], not poisoned["continue_success"]))

    def test_refuses_final_sources_duplicate_candidates_and_unfrozen_models(self):
        for invalid in ([case(1, source_split="validation")], [case(1), case(1)]):
            with self.assertRaises(ValueError):
                self.collect(invalid)
        self.assertEqual(self.bank.calls, [])
        self.model.train()
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.collect()
        self.model.eval()
        with self.assertRaises(ValueError):
            self.collect(max_steps=1)
        with self.assertRaises(ValueError):
            self.collect(threshold=.8)

    def test_detects_parameter_mutation_even_when_requires_grad_false(self):
        original_step = self.model.step
        def mutating(*args, **kwargs):
            with torch.no_grad():
                self.model.head[-1].bias.add_(.1)
            return original_step(*args, **kwargs)
        self.model.step = mutating
        with self.assertRaisesRegex(ValueError, "mutated a selected frozen artifact"):
            self.collect([case(1)])

    def test_fit_meter_includes_sgd_freezing_and_calibration_and_rejects_overlap(self):
        fit_rows, _ = self.collect([case(1)], split="validation_fit")
        calibration_rows, _ = self.collect([case(2)], split="validation_calibration")
        critic, receipt = fit_critic_metered(fit_rows, calibration_rows, steps=3, seed=4)
        critic.assert_frozen()
        self.assertEqual(receipt["work_observation"]["unknown_operators"], {})
        self.assertGreater(receipt["work_observation"]["phase_flops"]["train"], 0)
        self.assertFalse(receipt["future_support_guaranteed"])
        self.assertEqual(receipt["fit_rows"], 2)
        overlap = [dict(row, source_group=fit_rows[0]["source_group"]) for row in calibration_rows]
        with self.assertRaisesRegex(ValueError, "overlap"):
            fit_critic_metered(fit_rows, overlap, steps=1)


if __name__ == "__main__":
    unittest.main()
