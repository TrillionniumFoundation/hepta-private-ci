"""Local tiny-model wiring check; artifact delivery and runner identities mocked.

This test is not a multi-host result. The independent hosted experiment retains
its own 256-update/32-request protocol and actual Actions transport evidence.
"""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
for name in (
    "memory_cell",
    "memory_cell_service",
    "memory_cell_network",
    "memory_cell_system",
):
    sys.path.insert(0, str(SCRIPTS / name))

import relay_evaluate
import relay_trial
from relay_protocol import PROTOCOL, read
import test_parametric_model as tiny


class RelayCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny.SourceMemoryCellTests.setUpClass()
        cls.addClassCleanup(tiny.SourceMemoryCellTests.tearDownClass)

    def test_relay_phases_with_actual_tiny_decoder_and_simulated_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            source.mkdir()
            target.mkdir()
            secret = root / "secrets" / "source.key"
            model = tiny.SourceMemoryCellTests.base
            env = dict(SOURCE_SHA="a" * 40, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1")
            identities = [
                dict(boot_id_sha256="a" * 64, job="source", simulated=True),
                dict(boot_id_sha256="b" * 64, job="target", simulated=True),
            ]

            def delivery(stage, output):
                owner = source if stage in ("offer", "withdrawal") else target
                output.mkdir()
                dest = output / (stage + ".json")
                shutil.copyfile(owner / ("out-" + stage) / (stage + ".json"), dest)
                return dest

            with (
                patch.dict(os.environ, env),
                patch.dict(
                    PROTOCOL,
                    dict(train_updates=12, load_requests=2, target_decoder_queries=5),
                ),
                patch("relay_trial.identity", return_value=identities[0]),
                patch("relay_trial.await_artifact", side_effect=delivery),
                patch("relay_evaluate.await_artifact", side_effect=delivery),
            ):
                relay_trial.source_prepare(source, model, secret)
                with patch("relay_trial.identity", return_value=identities[1]):
                    relay_trial.target_read(target, model)
                relay_trial.source_withdraw(source, model, secret)
                relay_trial.target_withdraw(target, model)
                with patch("relay_trial.identity", return_value=identities[1]):
                    relay_trial.target_replay(target, model)
                self.assertEqual(relay_evaluate.evaluate(source, model), 0)
            report = read(source / "report.json")
            self.assertTrue(report["mechanism_passed"])
            self.assertEqual(report["raw_accuracy"]["target_load"]["total"], 2)
            self.assertEqual(
                read(target / "target-restart-replay-refusal.json")["callbacks_after"],
                3,
            )
            self.assertFalse(any(target.rglob("sources.sqlite")))


if __name__ == "__main__":
    unittest.main()
