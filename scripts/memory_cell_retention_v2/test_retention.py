"""Real source-owner replay and accounting boundaries without pretrained reads."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch

from retention_common import CAMPAIGN, digest, read_json, remaining_timeout, retain
from retention_protocol import prepare_sources, trial_order
from retention_read import summarize
from train_worker import ForwardAudit


class SourcePreparationTests(unittest.TestCase):
    def test_all_terminal_source_states_and_unchanged_retention_denominators(self):
        campaign = read_json(CAMPAIGN)
        for seed in (24019, 24023, 24029):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                service, current, previous = prepare_sources(
                    directory, campaign["streams"][str(seed)]
                )
                facts = {f["entity"]: f for f in current["facts"]}
                old = {f["entity"]: f for f in previous["facts"]}
                self.assertEqual(
                    set(facts),
                    {
                        "long_00",
                        "long_01",
                        "long_02",
                        "long_04",
                        "long_06",
                        "long_07",
                        "long_08",
                        "long_09",
                        "long_10",
                        "long_11",
                    },
                )
                self.assertEqual(
                    {
                        key: facts[key]["value"]
                        for key in (
                            "long_00",
                            "long_02",
                            "long_06",
                            "long_07",
                            "long_08",
                            "long_09",
                            "long_10",
                            "long_11",
                        )
                    },
                    dict(
                        long_00="orange",
                        long_02="silver",
                        long_06="cyan",
                        long_07="green",
                        long_08="silver",
                        long_09="yellow",
                        long_10="white",
                        long_11="black",
                    ),
                )
                retained = [
                    f
                    for key, f in facts.items()
                    if key in old and f["value"] == old[key]["value"]
                ]
                self.assertEqual(len(retained), 8)
                self.assertEqual(
                    service.read("long_03", "color").status.value, "revoked"
                )
                self.assertEqual(
                    service.read("long_05", "color").status.value, "revoked"
                )
                self.assertEqual(
                    service.read("long_04", "color").status.value, "answered"
                )
                self.assertFalse(
                    set(current["revoked"])
                    & {f["source_digest"] for f in facts.values()}
                )
                self.assertIsNone(service.parameter_binding())
                self.assertEqual(list(service.artifacts.iterdir()), [])
                rounds = read_json(directory / "source-rounds.json")
                self.assertEqual(
                    [len(s["facts"]) for s in rounds], [8, 9, 10, 10, 10, 10]
                )
                self.assertEqual(rounds[4]["conflicts"][0]["entity"], "long_04")
                self.assertEqual(current["conflicts"], [])

    def test_equal_forward_reservations_and_counterbalanced_complete_order(self):
        trials = trial_order()
        self.assertEqual(len(trials), 9)
        self.assertEqual(len(set((seed, arm["name"]) for seed, arm in trials)), 9)
        self.assertEqual(
            [trials[i * 3][1]["name"] for i in range(3)],
            ["ce_001", "ce_01", "margin_01"],
        )
        self.assertEqual(sum(arm["steps"] for _, arm in trials), 1920)
        self.assertTrue(
            all(
                arm["steps"]
                * (2 if arm["objective"] == "source_value_margin_v2" else 1)
                == 256
                for _, arm in trials
            )
        )


class AccountingTests(unittest.TestCase):
    def test_each_dispatch_recomputes_remaining_whole_screen_budget(self):
        with patch("retention_common.time.monotonic", side_effect=[100, 398, 400]):
            self.assertEqual(remaining_timeout(400, 300), 300)
            self.assertEqual(remaining_timeout(400, 300), 2)
            with self.assertRaisesRegex(ValueError, "before dispatch"):
                remaining_timeout(400, 300)

    def test_entered_completed_and_refused_forwards_are_distinct(self):
        class Probe(torch.nn.Module):
            def forward(self, input_ids, fail=False):
                if fail:
                    raise RuntimeError("failure within forward")
                return input_ids + 1

        model, audit = Probe(), ForwardAudit(2)
        before = model.register_forward_pre_hook(audit.before, with_kwargs=True)
        after = model.register_forward_hook(audit.after, with_kwargs=True)
        try:
            model(input_ids=torch.tensor([[1, 2, 3]]))
            with self.assertRaisesRegex(RuntimeError, "within forward"):
                model(input_ids=torch.tensor([[1, 2]]), fail=True)
            with self.assertRaisesRegex(ValueError, "reservation exhausted"):
                model(input_ids=torch.tensor([[1]]))
        finally:
            before.remove()
            after.remove()
        self.assertEqual(
            audit.receipt(),
            dict(
                entered_model_forwards=2,
                completed_model_forwards=1,
                entered_input_tokens=5,
                input_tokens_per_entered_forward=[3, 2],
                over_budget_calls=1,
            ),
        )

    def test_rejected_worker_retains_failure_and_does_not_refund_reserved_budget(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            request = dict(schema="deliberately-invalid-no-model-request")
            retain(directory / "train-request.json", request)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("train_worker.py")),
                    "--request",
                    str(directory / "train-request.json"),
                    "--request-sha256",
                    digest(request),
                ],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            receipt = read_json(directory / "train-result.json")
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["charged_training_forwards"], 256)
            self.assertEqual(receipt["budget_refund"], 0)
            self.assertIn("closed retention training request", receipt["error"])
            self.assertFalse((directory / "checkpoint").exists())


def completed(seed, arm, accuracy, retention, diagnostic):
    control = dict(source_both_wordings=dict(accuracy=0))
    return dict(
        seed=seed,
        arm=arm,
        status="complete",
        scores=dict(
            adapter=dict(
                source_both_wordings=dict(accuracy=accuracy),
                unchanged_retention=dict(accuracy=retention),
                corrected_sources=dict(all_exact=True),
            ),
            base=control,
            shuffled=control,
            training_diagnostic=dict(source_both_wordings=dict(accuracy=diagnostic)),
        ),
    )


class FrozenSelectionTests(unittest.TestCase):
    def setUp(self):
        self.protocol = dict(
            seeds=[24019, 24023, 24029], tie_order=["ce_001", "ce_01", "margin_01"]
        )

    def test_worst_seed_rule_uses_heldout_retention_not_training_wordings(self):
        trials = []
        for seed in self.protocol["seeds"]:
            trials.extend(
                [
                    completed(seed, "ce_001", 1, 0.5, 1),
                    completed(seed, "ce_01", 0.9, 0.875, 0),
                    completed(seed, "margin_01", 1, 0.75, 1),
                ]
            )
        result = summarize(self.protocol, trials)
        self.assertEqual(result["selected_arm"], "ce_01")
        self.assertFalse(
            any(arm["exposed_development_quality_gate"] for arm in result["arms"])
        )
        self.assertFalse(result["future_gate_satisfied"])

    def test_ties_and_missing_attempts_cannot_selectively_drop_bad_arms(self):
        trials = [
            completed(seed, arm, 1, 1, 0)
            for seed in self.protocol["seeds"]
            for arm in self.protocol["tie_order"]
        ]
        self.assertEqual(summarize(self.protocol, trials)["selected_arm"], "ce_001")
        trials[-1] = dict(seed=24029, arm="margin_01", status="failed")
        self.assertIsNone(summarize(self.protocol, trials)["selected_arm"])


if __name__ == "__main__":
    unittest.main()
