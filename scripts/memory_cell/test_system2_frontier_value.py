"""Resumed-return mechanics; tiny runner fixtures are not model efficacy evidence."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from torch import nn

from system2_ablation import model_digest
from system2_frontier_value import (
    advance_logged,
    choose,
    collect_training,
    episode,
    fit,
    make_head,
    observe,
)
from system2_frontier_trial import analyze, run, task_plan
from system2_resumable_search import SearchSession
from system2_verified_search import ExactLabels, digest


class Fixed(nn.Module):
    def __init__(self, logits):
        super().__init__()
        self.logits = logits
        self.eval()

    def forward(self, x):
        return x.new_tensor([self.logits]).repeat(len(x), 1)


def context():
    session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
    session.advance(1)
    return observe(session, 256)


class FrontierTests(unittest.TestCase):
    def test_observation_does_not_advance_or_call_oracle(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
        session.advance(1)
        before = session.receipt()
        with (
            patch.object(session, "advance", side_effect=AssertionError("advanced")),
            patch.object(ExactLabels, "_solve", side_effect=AssertionError("oracle")),
        ):
            first, second = observe(session, 256), observe(session, 256)
        self.assertEqual(first, second)
        self.assertEqual(before, session.receipt())
        self.assertEqual(len(first), 32)

    def test_completed_frontier_is_not_a_continuation_context(self):
        session = SearchSession((1, 1, 1, 1), 24, "heuristic_search")
        session.advance(65536)
        with self.assertRaises(ValueError):
            observe(session, 256)

    def test_training_reuses_the_same_cursor_without_oracle(self):
        sessions, rows, events = [], [], []

        def factory(*args, **kwargs):
            session = SearchSession(*args, **kwargs)
            sessions.append(session)
            return session

        with (
            patch("system2_frontier_value.SearchSession", side_effect=factory),
            patch.object(
                ExactLabels, "_solve", side_effect=AssertionError("training oracle")
            ),
        ):
            x, y = collect_training([(1, 3, 4, 6)], rows, events.append)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(rows), 2)
        self.assertGreater(len(x), 0)
        for row, session in zip(rows, sessions, strict=True):
            if "continued" in row:
                before = row["probe"]["costs"]["generated_successors"]
                after = row["continued"]["costs"]["generated_successors"]
                self.assertEqual(session.calls, 2)
                self.assertAlmostEqual(
                    row["target"][1], (after - before) / (row["budget"] - before)
                )
        self.assertEqual(tuple(y.shape), (len(x), 2))
        self.assertTrue(
            all("target" not in e for e in events if e["event"] == "context_observed")
        )

    def test_second_advance_failure_preserves_prior_work(self):
        original = SearchSession.advance
        rows, events = [], []
        calls = 0

        def failure(session, ceiling):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("tail failure")
            return original(session, ceiling)

        with patch.object(SearchSession, "advance", failure):
            with self.assertRaisesRegex(RuntimeError, "tail failure"):
                collect_training([(1, 3, 4, 6)], rows, events.append)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["probe"]["costs"], rows[0]["last_receipt"]["costs"])
        self.assertNotIn("target", rows[0])
        self.assertEqual(events[-1]["event"], "advance_failed")

    def test_interruption_propagates_with_caller_owned_ledger(self):
        rows, events = [], []
        with patch.object(SearchSession, "advance", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                collect_training([(1, 3, 4, 6)], rows, events.append)
        self.assertEqual(rows[0]["error_type"], "KeyboardInterrupt")
        self.assertEqual(events[-1]["error_type"], "KeyboardInterrupt")

    def test_logging_failure_prevents_unrecorded_work(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
        with patch.object(session, "advance") as work:
            with self.assertRaises(OSError):
                advance_logged(
                    session, 64, lambda _: (_ for _ in ()).throw(OSError("disk"))
                )
        work.assert_not_called()

    def test_event_snapshots_do_not_mutate_session_accounting(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")

        def mutate(event):
            event["receipt"]["costs"]["generated_successors"] = 99999

        result = advance_logged(session, 1, mutate)
        self.assertEqual(result["costs"]["generated_successors"], 1)
        self.assertEqual(session.costs["generated_successors"], 1)

    def test_controls_share_initialization_targets_and_step_budget(self):
        rng = torch.Generator().manual_seed(1)
        x = torch.randn(6, 32, generator=rng)
        y = torch.tensor(
            [[0.0, 1.0], [1.0, 0.2], [0.0, 0.8], [1.0, 0.3], [0.0, 0.9], [1.0, 0.5]]
        )
        before = x.clone(), y.clone()
        receipts = {}
        for mode in ("frontier", "root_only", "shuffled"):
            model, receipts[mode] = fit(x, y, mode, steps=4)
            self.assertFalse(any(p.requires_grad for p in model.parameters()))
            self.assertNotEqual(receipts[mode]["before"], receipts[mode]["after"])
        self.assertEqual(len({r["before"] for r in receipts.values()}), 1)
        self.assertEqual(
            receipts["frontier"]["target_digest"],
            receipts["root_only"]["target_digest"],
        )
        self.assertNotEqual(
            receipts["frontier"]["input_digest"], receipts["root_only"]["input_digest"]
        )
        self.assertEqual(
            receipts["frontier"]["input_digest"], receipts["shuffled"]["input_digest"]
        )
        self.assertTrue(torch.equal(x, before[0]) and torch.equal(y, before[1]))

    def test_cost_can_stop_without_altering_success_prediction(self):
        model = Fixed([-5.0, 20.0])
        aware = choose(model, context(), 192, "frontier")
        blind = choose(model, context(), 192, "cost_blind")
        self.assertEqual(aware["probability"], blind["probability"])
        self.assertEqual((aware["action"], blind["action"]), ("stop", "resume"))

    def test_root_only_masks_only_frontier_input(self):
        model = Fixed([0.0, 0.0])
        original = context()
        changed = list(original)
        changed[20] += 1
        a = choose(model, original, 192, "root_only")
        b = choose(model, changed, 192, "root_only")
        self.assertEqual(a["model_input_digest"], b["model_input_digest"])
        self.assertNotEqual(a["observed_digest"], b["observed_digest"])

    def test_model_schema_training_mode_and_nonfinite_rejected(self):
        for model in (make_head(), Fixed([float("nan"), 0.0]), Fixed([0.0] * 4)):
            with self.assertRaises(ValueError):
                choose(model, context(), 192, "frontier")
        with self.assertRaises(ValueError):
            choose(Fixed([0.0, 0.0]), [float("inf")] * 32, 192, "frontier")

    def test_resume_matches_uninterrupted_and_freezes_head(self):
        model = Fixed([20.0, -20.0])
        before = model_digest(model)
        direct = episode((1, 3, 4, 6), 1024, "direct", event_sink=lambda _: None)
        learned = episode(
            (1, 3, 4, 6), 1024, "frontier", model, event_sink=lambda _: None
        )
        self.assertEqual(direct["status"], "completed")
        self.assertEqual(learned["status"], "completed")
        self.assertEqual(
            {k: direct[k] for k in ("found", "proof", "costs")},
            {k: learned[k] for k in ("found", "proof", "costs")},
        )
        self.assertEqual(before, model_digest(model))

    def test_decision_precedes_tail_and_stop_keeps_probe_cost(self):
        events = []
        continued = episode(
            (1, 3, 4, 6),
            256,
            "frontier",
            Fixed([20.0, -20.0]),
            event_sink=events.append,
        )
        names = [e["event"] for e in events]
        self.assertLess(names.index("decision"), len(names) - 2)
        self.assertEqual(names[-2:], ["advance_start", "advance_completed"])
        stopped = episode(
            (1, 3, 4, 6),
            256,
            "frontier",
            Fixed([-20.0, 20.0]),
            event_sink=lambda _: None,
        )
        self.assertEqual(stopped["final"]["calls"], 1)
        self.assertEqual(stopped["costs"], stopped["probe"]["costs"])
        self.assertLess(stopped["utility"], 0)
        self.assertEqual(continued["status"], "completed")

    def test_runner_seals_before_analysis_and_retains_failed_denominators(self):
        groups = {"exposed_96": [(1, 1, 1, 1)], "next_48_tasks": [(1, 2, 3, 4)]}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"

            def guarded(rows, selected):
                self.assertTrue((output / "prediction-seal.json").is_file())
                self.assertTrue((output / "freeze.json").is_file())
                return analyze(rows, selected)

            with (
                patch(
                    "system2_frontier_trial.read_parent", return_value=({}, {}, [], {})
                ),
                patch(
                    "system2_frontier_trial.task_plan",
                    return_value=([(1, 3, 4, 6)], groups),
                ),
                patch("system2_frontier_trial.analyze", side_effect=guarded),
            ):
                result = run(Path("fixture.zip"), output, source_commit="a" * 40)
            self.assertEqual((result["recorded"], result["failed"]), (28, 0))
            records = [
                json.loads(line)
                for line in (output / "predictions.jsonl").read_text().splitlines()
            ]
            failed = deepcopy(records)
            failed[0]["status"] = "failed"
            failed[0]["utility"] = None
            report = analyze(failed, groups)
            self.assertEqual(
                (report["planned"], report["recorded"], report["failed"]), (28, 28, 1)
            )
            with self.assertRaises(ValueError):
                analyze(records[:-1], groups)
            records[0]["utility"] += 0.1
            with self.assertRaises(ValueError):
                analyze(records, groups)

    def test_runner_preserves_training_ledger_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "failed"

            def fail(tasks, ledger, sink):
                ledger.append(dict(status="failed", prior_work=123))
                raise RuntimeError("injected")

            with (
                patch(
                    "system2_frontier_trial.read_parent", return_value=({}, {}, [], {})
                ),
                patch(
                    "system2_frontier_trial.task_plan",
                    return_value=([(1, 3, 4, 6)], {}),
                ),
                patch("system2_frontier_trial.collect_training", side_effect=fail),
            ):
                with self.assertRaises(RuntimeError):
                    run(Path("fixture.zip"), output, source_commit="a" * 40)
            self.assertEqual(
                json.loads((output / "training-rollouts.json").read_text())[0][
                    "prior_work"
                ],
                123,
            )
            self.assertFalse((output / "freeze.json").exists())

    def test_new_tasks_are_fixed_before_outcome_selection(self):
        import itertools

        catalogue = sorted(
            itertools.combinations_with_replacement(range(1, 10), 4),
            key=lambda n: digest(("verified-search-v1", n)),
        )
        with patch.object(
            ExactLabels, "_solve", side_effect=AssertionError("selection oracle")
        ):
            training, groups = task_plan(
                dict(training=catalogue[:12], evaluation=catalogue[12:36])
            )
        self.assertEqual(groups["next_48_tasks"], catalogue[108:156])
        self.assertFalse(set(training) & set(groups["next_48_tasks"]))
        self.assertFalse(set(groups["exposed_96"]) & set(groups["next_48_tasks"]))


if __name__ == "__main__":
    unittest.main()
