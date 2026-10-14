"""Pause boundaries are execution boundaries, not new reasoning or training."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from system2_ablation import model_digest
from system2_budget_control import (
    ARMS as BUDGET_ARMS,
    LIMITS,
    UNIT_COST,
    episode,
    make_head,
)
from system2_resumable_search import SearchSession
from system2_resume_trial import restart_ceiling, run
from system2_verified_search import ARMS, ExactLabels, digest, search, verify


def model():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(17)
        return torch.nn.Sequential(torch.nn.Linear(12, 1)).eval().requires_grad_(False)


def comparison(receipt):
    return {k: receipt[k] for k in ("found", "proof", "costs")}


class ResumeTests(unittest.TestCase):
    def test_all_policies_keep_identical_decisions_across_irregular_splits(self):
        for arm in ARMS:
            critic = model()
            single = SearchSession((1, 3, 4, 6), 24, arm, critic).advance(1024)
            session = SearchSession((1, 3, 4, 6), 24, arm, critic)
            for limit in (1, 7, 35, 36, 37, 64, 256, 1024):
                part = session.advance(limit)
                self.assertLessEqual(part["costs"]["generated_successors"], limit)
            self.assertEqual(comparison(single), comparison(part))

    def test_one_successor_chunks_do_not_rescore_partial_batches(self):
        for arm in ("heuristic_search", "value_search"):
            critic = model()
            session = SearchSession((1, 3, 4, 6), 24, arm, critic)
            for limit in range(1, 257):
                actual = session.advance(limit)
            expected = SearchSession((1, 3, 4, 6), 24, arm, critic).advance(256)
            self.assertEqual(comparison(actual), comparison(expected))

    def test_legacy_eager_proofs_and_successor_sequence_match(self):
        for numbers in ((1, 2, 3, 4), (1, 3, 4, 6), (1, 1, 1, 1)):
            for arm in ARMS:
                critic = model()
                for limit in (32, 256, 1024):
                    old = search(
                        numbers,
                        24,
                        arm,
                        8192,
                        critic,
                        terminal_policy="eager",
                        successor_limit=limit,
                    )
                    new = SearchSession(numbers, 24, arm, critic).advance(limit)
                    self.assertEqual(
                        (
                            old["found"],
                            old["proof"],
                            old["costs"]["generated_successors"],
                        ),
                        (
                            new["found"],
                            new["proof"],
                            new["costs"]["generated_successors"],
                        ),
                    )

    def test_partial_node_cursor_is_reused(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
        first = session.advance(1)
        pending = session.pending
        second = session.advance(2)
        self.assertIs(session.pending, pending)
        self.assertEqual(first["partial_child_cursor"], 1)
        self.assertEqual(second["partial_child_cursor"], 2)
        self.assertEqual(second["costs"]["popped_states"], 1)

    def test_search_does_not_call_reachability_oracle(self):
        with patch.object(
            ExactLabels, "_solve", side_effect=AssertionError("oracle leakage")
        ):
            result = SearchSession((1, 3, 4, 6), 24, "heuristic_search").advance(1024)
        self.assertTrue(result["found"])
        self.assertTrue(verify((1, 3, 4, 6), 24, result["proof"]))

    def test_restart_can_lose_a_proof_that_resume_preserves(self):
        numbers = (1, 3, 4, 6)
        session = SearchSession(numbers, 24, "heuristic_search")
        self.assertFalse(session.advance(256)["found"])
        resumed = session.advance(1024)
        restarted = search(
            numbers,
            24,
            "heuristic_search",
            8192,
            terminal_policy="eager",
            successor_limit=768,
        )
        self.assertTrue(resumed["found"])
        self.assertFalse(restarted["found"])
        self.assertEqual(resumed["costs"]["generated_successors"], 934)

    def test_allowances_are_bounded_monotone_and_not_boolean(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
        session.advance(64)
        for bad in (0, 32, True, 65537):
            with self.assertRaises(ValueError):
                session.advance(bad)

    def test_detached_cost_receipts_cannot_mutate_state(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
        result = session.advance(7)
        result["costs"]["generated_successors"] = 100000
        self.assertEqual(session.receipt()["costs"]["generated_successors"], 7)

    def test_changed_critic_invalidates_cursor(self):
        critic = model()
        session = SearchSession((1, 3, 4, 6), 24, "value_search", critic)
        session.advance(7)
        with torch.no_grad():
            next(critic.parameters()).add_(1)
        with self.assertRaisesRegex(ValueError, "critic changed"):
            session.advance(64)
        self.assertEqual(session.receipt()["status"], "failed")
        with self.assertRaises(ValueError):
            session.advance(1024)

    def test_changed_training_mode_is_not_hidden_by_same_weights(self):
        for training_mode in (True, False):
            critic = model()
            session = SearchSession((1, 3, 4, 6), 24, "value_search", critic)
            if training_mode:
                critic.train()
            else:
                critic.requires_grad_(True)
            with self.assertRaises(ValueError):
                session.advance(64)

    def test_nonfinite_model_failure_retains_attempted_work(self):
        class Bad(torch.nn.Module):
            def forward(self, x):
                return torch.full((len(x), 1), float("nan"))

        session = SearchSession((1, 3, 4, 6), 24, "value_search", Bad().eval())
        with self.assertRaises(ValueError):
            session.advance(128)
        receipt = session.receipt()
        self.assertEqual(receipt["status"], "failed")
        self.assertGreater(receipt["costs"]["critic_examples"], 0)
        self.assertGreater(receipt["costs"]["generated_successors"], 0)

    def test_popped_bound_survives_pause(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search", popped_ceiling=1)
        session.advance(1)
        result = session.advance(1024)
        self.assertEqual(result["costs"]["popped_states"], 1)
        self.assertFalse(result["found"])

    def test_solved_session_does_not_repeat_work(self):
        session = SearchSession((1, 3, 4, 6), 24, "heuristic_search")
        result = session.advance(1024)
        self.assertEqual(comparison(result), comparison(session.advance(2048)))

    def test_exhaustion_does_not_claim_certified_impossibility(self):
        result = SearchSession((1, 1, 1, 1), 24, "heuristic_search").advance(8192)
        self.assertFalse(result["found"])
        self.assertFalse(result["certified_impossible"])

    def test_menu_ceiling_keeps_missing_outcomes_unknown(self):
        rows = [
            dict(
                group="fixture",
                query_id="q",
                budget=1024,
                numbers=[1, 3, 4, 6],
                arm=a,
                status="completed",
                found=a == "direct_heuristic",
                utility=float(a == "direct_heuristic"),
            )
            for a in (
                "direct_heuristic",
                "learned",
                "probe_stop",
                "probe_heuristic",
                "probe_value",
            )
        ]
        result = restart_ceiling(rows)[0]
        self.assertEqual(result["restart_menu_proofs"], 0)
        self.assertEqual(len(result["structurally_lost"]), 1)
        self.assertEqual(restart_ceiling(rows[:-1])[0]["unknown"], 1)
        with self.assertRaises(ValueError):
            restart_ceiling(rows + rows[:1])

    def test_actual_runner_census_seal_and_failure_preservation(self):
        critic = model()
        head = make_head().eval().requires_grad_(False)
        numbers = (1, 3, 4, 6)
        groups = {"fixture": [numbers]}
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "budget"
            old.mkdir()
            rows = [
                episode(numbers, b, a, critic, head)
                | dict(group="fixture", query_id=digest(numbers))
                for b in LIMITS
                for a in BUDGET_ARMS
            ]
            raw = "".join(json.dumps(r) + "\n" for r in rows).encode()
            (old / "predictions.jsonl").write_bytes(raw)
            (old / "prediction-seal.json").write_text(
                json.dumps(
                    dict(
                        sha256=hashlib.sha256(raw).hexdigest(),
                        rows=len(rows),
                        scoring_started=False,
                    )
                )
            )
            (old / "plan.json").write_text(
                json.dumps(
                    dict(
                        groups=groups,
                        frozen_child_model=model_digest(critic),
                        objective=dict(cost_per_generated_successor=UNIT_COST),
                        source_commit="a" * 40,
                    )
                )
            )
            with (
                patch(
                    "system2_resume_trial.read_parent",
                    return_value=({}, {"value": critic}, [], {}),
                ),
                patch("system2_resume_trial.cohort", return_value=([], groups)),
            ):
                result = run(
                    Path("fixture.zip"),
                    old,
                    Path(tmp) / "success",
                    source_commit="a" * 40,
                )
                self.assertEqual((result["recorded"], result["failed"]), (4, 0))
                with patch.object(
                    SearchSession,
                    "advance",
                    side_effect=RuntimeError("execution failure"),
                ):
                    with self.assertRaises(RuntimeError):
                        run(
                            Path("fixture.zip"),
                            old,
                            Path(tmp) / "failed",
                            source_commit="a" * 40,
                        )
                    failed = json.loads((Path(tmp) / "failed/summary.json").read_text())
                    self.assertEqual((failed["recorded"], failed["failed"]), (4, 4))
                (old / "predictions.jsonl").write_bytes(raw + b"\n")
                with self.assertRaisesRegex(ValueError, "seal"):
                    run(
                        Path("fixture.zip"),
                        old,
                        Path(tmp) / "tampered",
                        source_commit="a" * 40,
                    )


if __name__ == "__main__":
    unittest.main()
