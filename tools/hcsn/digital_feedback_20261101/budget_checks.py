"""Adversarial interruption and optimizer-equation checks for the CPU contract."""
import json
import signal
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np
import torch

from ..digital_read_before_20261031.task import initial, legal
from .factors import FactorPolicy, candidates
from .training import CpuExpired, HeadAdamW, cpu_deadline, encode_rows, fit_candidate


def fixture():
    public = dict(schema="digital-read-before-public-v1", id="budget_fixture", deadline=6,
                  initial_budget=3, duration=[.5] * 6, reliability=[.85] * 6,
                  read_price=[.03] * 6, read_delay=[1] * 6, latency_price=.025,
                  repair_price=.03, failure_probability=.08,
                  packets=[f"packet_{i}.json" for i in range(6)], packet_sha256=["0" * 64] * 6)
    state = initial(public)
    row = dict(public=public, state=state, prefix=[], legal=legal(public, state),
               q=[0., .2, .3, 0., 0., 0.], posterior=.5, world="budget_fixture")
    data = dict(train=dict(rows=[row]), train_cohort=dict(records=[dict(id="budget_fixture")]),
                confusion=[[.95, .05], [.05, .95]])
    protocol = dict(training_cpu_seconds=.4, cpu_tolerance_seconds=.08,
                    cpu_finalize_reserve_seconds=.015, feedback_round_fractions=[.1, .4, .7],
                    feedback_worlds_total=3, max_visits=64, batch_seed_base=1900000,
                    occupancy_seed_base=1900000000, learning_rate=.005, weight_decay=.0001,
                    belief_loss_weight=1., gradient_clip=5., batch_states=8)
    return data, protocol


class BudgetChecks(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_cpu_interruption_preserves_signal_owner(self):
        handler = signal.getsignal(signal.SIGPROF)
        start = time.process_time()
        with self.assertRaises(CpuExpired):
            with cpu_deadline(.035):
                while True:
                    sum(i * i for i in range(100))
        self.assertLess(time.process_time() - start, .15)
        self.assertEqual(signal.getitimer(signal.ITIMER_PROF), (0., 0.))
        self.assertEqual(signal.getsignal(signal.SIGPROF), handler)

    def test_explicit_adamw_matches_library(self):
        rng = np.random.default_rng(731)
        p = torch.nn.Parameter(torch.tensor(rng.normal(size=(3, 7)), dtype=torch.float64))
        reference = torch.nn.Parameter(p.detach().clone())
        ours, library = HeadAdamW([p], .006, .0001), torch.optim.AdamW([reference], lr=.006, weight_decay=.0001)
        for _ in range(9):
            gradient = torch.tensor(rng.normal(size=p.shape), dtype=torch.float64)
            p.grad, reference.grad = gradient, gradient.clone()
            ours.step()
            library.step()
        torch.testing.assert_close(p, reference, rtol=1e-13, atol=1e-13)

    def test_partial_second_update_rolls_back_complete_first(self):
        data, protocol = fixture()
        spec = next(s for s in candidates() if s["id"] == "acc_structured_off")
        original_step, snapshots = HeadAdamW.step, []

        def interrupted(optimizer):
            if snapshots:
                with torch.no_grad():
                    optimizer.parameters[0].fill_(999.)
                raise CpuExpired("injected partial optimizer write")
            original_step(optimizer)
            snapshots.append([p.detach().clone() for p in optimizer.parameters])

        with patch.object(HeadAdamW, "step", interrupted):
            policy, _, receipt = fit_candidate(spec, 17, data, None, protocol)
        self.assertEqual(receipt["optimizer_updates"], 1)
        self.assertFalse(receipt["cpu_compliant"])
        self.assertEqual(receipt["interruptions"][0]["last_complete_update"], 1)
        self.assertEqual(receipt["behavior_supervised_update_counts"], [1])
        for actual, expected in zip([p for p in policy.parameters() if p.requires_grad], snapshots[0]):
            torch.testing.assert_close(actual, expected, rtol=0., atol=0.)

    def test_failed_attempt_is_retained_and_not_admitted(self):
        data, protocol = fixture()
        spec = next(s for s in candidates() if s["id"] == "acc_structured_off")
        before = FactorPolicy.from_spec(spec, 19).export()
        with patch.object(HeadAdamW, "step", side_effect=FloatingPointError("injected bad gradient")):
            _, artifact, receipt = fit_candidate(spec, 19, data, None, protocol)
        self.assertEqual(artifact, before)
        self.assertEqual(receipt["failures"][0]["kind"], "FloatingPointError")
        self.assertEqual(receipt["optimizer_updates"], 0)
        self.assertFalse(receipt["training_valid"])
        self.assertEqual(receipt["behavior_rows_with_support"], [])

    def test_whole_cohort_slow_call_cannot_consume_unbounded_budget(self):
        data, protocol = fixture()
        spec = next(s for s in candidates() if s["id"] == "acc_structured_multi")

        def slow_collect(*args, **kwargs):
            while True:
                sum(i ** 2 for i in range(100))

        with patch("tools.hcsn.digital_feedback_20261101.training.run_episode", slow_collect):
            _, _, receipt = fit_candidate(spec, 23, data, None, protocol)
        self.assertTrue(receipt["cpu_compliant"], receipt)
        self.assertEqual(receipt["interruptions"][0]["phase"], "collection")
        self.assertGreater(receipt["optimizer_updates"], 0)
        self.assertEqual(receipt["visit_rounds"][0]["status"], "interrupted")
        self.assertFalse(receipt["training_valid"])
        self.assertEqual(receipt["visit_rounds"][0]["attempted_world"], "budget_fixture")

    def test_collected_but_unused_rows_are_not_supervised_support(self):
        data, protocol = fixture()
        spec = next(s for s in candidates() if s["id"] == "acc_structured_multi")
        original_encode, calls = encode_rows, []

        def interrupt_encoding(policy, rows, cache):
            if calls:
                raise CpuExpired("injected before collected rows participate in an update")
            calls.append(True)
            return original_encode(policy, rows, cache)

        result = (dict(world="budget_fixture"), [dict(data["train"]["rows"][0], latent_index=0)])
        with patch("tools.hcsn.digital_feedback_20261101.training.run_episode", return_value=result):
            with patch("tools.hcsn.digital_feedback_20261101.training.encode_rows", interrupt_encoding):
                _, _, receipt = fit_candidate(spec, 29, data, None, protocol)
        self.assertEqual(receipt["realized_visit_records"], 1)
        self.assertEqual(receipt["visit_supervised_update_counts"], [0])
        self.assertEqual(receipt["visit_rounds"][0]["supervised_rows"], [])
        self.assertEqual(len(receipt["visit_rounds"][0]["rows"]), 1)

    def test_realized_indices_are_not_prefix_reweighted(self):
        data, _ = fixture()
        policy = FactorPolicy.from_spec(next(s for s in candidates() if s["id"] == "fpt_base_multi"), 31)
        policy.cell.raw.requires_grad_(False)
        row = data["train"]["rows"][0]
        encoded, support = encode_rows(policy, [row, dict(row, latent_index=2)], {})
        self.assertEqual(support[0]["latent_support"], [7])
        self.assertEqual(support[1]["latent_support"], [2])
        self.assertEqual(torch.argmax(encoded["mass"], dim=1).tolist(), [7, 2])

    def test_collection_receipt_boundaries_survive_interruption(self):
        for boundary in ("episode_commit", "round_complete"):
            with self.subTest(boundary=boundary):
                data, protocol = fixture()
                spec = next(s for s in candidates() if s["id"] == "acc_structured_multi")
                result = (dict(world="budget_fixture"), [dict(data["train"]["rows"][0], latent_index=0)])
                triggered = []

                def interrupt_at_boundary(frame, event, arg):
                    if event == "line" and frame.f_code is fit_candidate.__code__:
                        state = frame.f_locals
                        record = state.get("record", {})
                        committed_episode = (record.get("complete_worlds") == 1
                                             and len(state.get("visits", [])) == 0)
                        complete_round = record.get("status") == "complete"
                        if ((boundary == "episode_commit" and committed_episode)
                                or (boundary == "round_complete" and complete_round)):
                            triggered.append(boundary)
                            sys.settrace(None)
                            raise CpuExpired("injected at collection receipt boundary")
                    return interrupt_at_boundary

                previous = sys.gettrace()
                try:
                    with patch("tools.hcsn.digital_feedback_20261101.training.run_episode", return_value=result):
                        sys.settrace(interrupt_at_boundary)
                        _, _, receipt = fit_candidate(spec, 37, data, None, protocol)
                finally:
                    sys.settrace(previous)
                self.assertEqual(triggered, [boundary])
                self.assertEqual(receipt["realized_visit_records"], 1)
                self.assertEqual(receipt["visit_supervised_update_counts"], [0])
                record = receipt["visit_rounds"][0]
                self.assertEqual(record["complete_worlds"], 1)
                self.assertEqual(len(record["rows"]), 1)
                self.assertEqual(len(record["episodes"]), 1)
                self.assertEqual(record["supervised_rows"], [])
                self.assertIn("end_cpu_seconds", record)
                self.assertIn("end_update", record)
                self.assertEqual(record["status"], "interrupted" if boundary == "episode_commit" else "complete")

    def test_uncommitted_update_record_does_not_commit_model_or_support(self):
        data, protocol = fixture()
        spec = next(s for s in candidates() if s["id"] == "acc_structured_off")
        before = FactorPolicy.from_spec(spec, 41).export()
        triggered = []

        def interrupt_at_commit(frame, event, arg):
            if event == "line" and frame.f_code is fit_candidate.__code__:
                state = frame.f_locals
                committed = state.get("committed")
                if committed is not None and len(state.get("updates", [])) > committed[1]:
                    triggered.append(True)
                    sys.settrace(None)
                    raise CpuExpired("injected between record append and atomic model commit")
            return interrupt_at_commit

        previous = sys.gettrace()
        try:
            sys.settrace(interrupt_at_commit)
            _, artifact, receipt = fit_candidate(spec, 41, data, None, protocol)
        finally:
            sys.settrace(previous)
        self.assertEqual(triggered, [True])
        self.assertEqual(artifact, before)
        self.assertEqual(receipt["optimizer_updates"], 0)
        self.assertEqual(receipt["updates"], [])
        self.assertEqual(receipt["behavior_supervised_update_counts"], [0])
        self.assertEqual(receipt["behavior_rows_with_support"], [])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BudgetChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps(dict(tests_run=result.testsRun, failures=len(result.failures),
                          errors=len(result.errors), successful=result.wasSuccessful())))
    raise SystemExit(0 if result.wasSuccessful() else 1)
