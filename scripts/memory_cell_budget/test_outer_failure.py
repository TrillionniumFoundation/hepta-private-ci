"""Stdlib failure-boundary tests; no pretrained model is imported or run."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from budget_ledger import digest
from cohort_contract import file_sha
from model_budget import ledger_for
from prepare_budget_study import common_budget
import run_budget_models as runner


class OuterFailureTests(unittest.TestCase):
    def setup_case(self, root):
        study = root / "study"
        study.mkdir()
        protocol = dict(common_budget=common_budget(), implementation_base="4" * 40)
        (study / "protocol.json").write_text(json.dumps(protocol))
        args = SimpleNamespace(
            output=root / "result",
            study=study,
            implementation=root,
            model=root / "model",
            runtime_component=None,
            model_lane_authorized=True,
        )
        return args, protocol

    def test_outer_timeout_preserves_partial_and_charges_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, protocol = self.setup_case(Path(tmp))
            args.output.mkdir()

            def broken(arm, args, protocol, *unused):
                ledger = ledger_for(
                    args.output / arm / "budget.sqlite3",
                    arm,
                    protocol,
                    file_sha(args.study / "protocol.json"),
                )
                ledger.reserve(
                    "inflight",
                    "train",
                    dict(decoder_updates=5),
                    request_sha256="a" * 64,
                )
                (args.output / (arm + ".result.json")).write_text('{"partial":true}')
                raise TimeoutError(
                    "after partial write, before final result completion"
                )

            with patch.object(runner, "_arm_run", broken):
                result = runner.arm_run(
                    "single",
                    args,
                    protocol,
                    args.output / "shared",
                    dict(actual=dict(wall_ns=0)),
                )
            self.assertEqual(result["status"], "outer_arm_failure")
            self.assertEqual(
                result["budget"]["uncertain_work_charged"]["decoder_updates"], 5
            )
            self.assertEqual(result["budget"]["executed_used"]["decoder_updates"], 0)
            self.assertEqual(
                (args.output / "single.result.json").read_text(), '{"partial":true}'
            )
            self.assertTrue((args.output / "single.outer-failure.json").exists())

    def test_parent_failure_records_all_four_unexecuted(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, protocol = self.setup_case(Path(tmp))

            def fail(ledger, event, *unused, **kwargs):
                ledger.reserve(
                    event, "train", dict(decoder_updates=5), request_sha256="a" * 64
                )
                raise ValueError("no completed parent measurement")

            with (
                patch.object(runner, "validate_seal"),
                patch.object(runner.subprocess, "check_output", return_value="4" * 40),
                patch.object(runner, "model_call", fail),
            ):
                result = runner.run(args)
            self.assertEqual(len(result["arms"]), 4)
            self.assertTrue(
                all(
                    r["status"] == "unexecuted_shared_dependency_failure"
                    and r["model_arm_attempted"] is False
                    for r in result["arms"]
                )
            )
            self.assertEqual(
                result["shared_physical_budget"]["executed_used"]["decoder_updates"], 0
            )
            self.assertEqual(
                result["shared_physical_budget"]["uncertain_work_charged"][
                    "decoder_updates"
                ],
                5,
            )

    def test_remaining_arms_stop_if_shared_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, protocol = self.setup_case(Path(tmp))

            def parent(*unused, **kwargs):
                shared = args.output / "shared/state"
                shared.mkdir(parents=True)
                (shared / "pin.txt").write_text("original")
                return dict(actual=dict(wall_ns=0))

            def arm(name, args, protocol, shared, parent):
                (shared / "pin.txt").write_text("changed")
                return dict(arm=name, status="unit-fake-complete")

            with (
                patch.object(runner, "validate_seal"),
                patch.object(runner.subprocess, "check_output", return_value="4" * 40),
                patch.object(runner, "model_call", parent),
                patch.object(runner, "arm_run", arm),
            ):
                result = runner.run(args)
            self.assertEqual(result["arms"][0]["status"], "unit-fake-complete")
            self.assertTrue(
                all(
                    r["status"] == "unexecuted_shared_dependency_failure"
                    for r in result["arms"][1:]
                )
            )
            self.assertFalse(result["final_shared_and_source_integrity"])


if __name__ == "__main__":
    unittest.main()
