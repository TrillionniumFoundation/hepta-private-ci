"""Fresh tiny fixtures test replay barriers and numerical checkpoint bridges.

No production campaign is opened and no fit_step is performed. Mock training
receipts in this file are test fixtures, not claims of completed optimization.
"""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from . import cached_replay as R
from .crossed_design import canonical, registered_config
from .preparation import evaluate_development_preparations


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value))


class CachedReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def terminal_fixture(self):
        args = SimpleNamespace(
            campaign=self.root / "training" / "campaign",
            execution_receipt=self.root / "training" / "execution.json",
            training_freeze=self.root / "training-freeze.json",
            registered_config=self.root / "registered.json",
            replay_freeze=self.root / "replay-freeze.json",
            output=self.root / "replay",
        )
        cfg = registered_config()
        for index, factor in enumerate(("data", "init", "order")):
            cfg[factor + "_seeds"] = [9915100 + index * 100 + n for n in (1, 2, 3)]
        sources = R.source_hashes()
        original = {name: sha256(value).hexdigest() for name, value in R._source().items()}
        shared = {
            "config_sha256": sha256(canonical(cfg).encode()).hexdigest(),
            "confirmation_data_read": False,
            "confirmation_samples_generated": 0,
        }
        training = {
            **shared,
            "base_commit": cfg["base_commit"],
            "source_files": original,
            "fit_count": 189,
            "factor_cells": 27,
            "original_qualification": "HOLD_UNCHANGED",
            "frozen_at_utc": "2000-01-01T00:00:00+00:00",
        }
        write(args.training_freeze, training)
        write(args.registered_config, cfg)
        write(args.campaign / "config.json", cfg)
        for name, content in R._source().items():
            path = args.campaign / "source" / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
        common = {
            **shared,
            "source_sha256": original,
            "registration_commit": "a" * 40,
            "execution_source_commit": "b" * 40,
            "argv": ["python", "--config", str(args.registered_config), "--output", str(args.campaign)],
        }
        started = {**common, "started_at_utc": "2000-01-01T00:00:01+00:00"}
        write(args.campaign.parent / "EXECUTION_STARTED.json", started)
        write(
            args.campaign / "attempt.json",
            {
                **shared,
                "source_sha256": original,
                "base_commit": cfg["base_commit"],
                "environment": {"numpy": np.__version__},
                "started_at": "2000-01-01T00:00:02+00:00",
            },
        )
        logs = {}
        for name in ("stdout.log", "stderr.log"):
            path = args.campaign.parent / name
            path.write_text("")
            logs[name] = {"sha256": R.digest(path), "bytes": 0}
        receipt = {
            **common,
            "status": "EXITED",
            "exit_code": 0,
            "result_present": True,
            "logs": logs,
            "finished_at_utc": "2000-01-01T00:00:03+00:00",
        }
        write(args.execution_receipt, receipt)
        result = {
            **shared,
            "status": "COMPLETE",
            "qualification": "HOLD_UNCHANGED",
            "completed_fits": 189,
            "expected_fits": 189,
            "failed_fits": 0,
            "unstarted_fits": 0,
            "failures": [],
            "source_unchanged": True,
        }
        write(args.campaign / "RESULT.json", result)
        freeze = {
            **shared,
            "schema": "pred1-cached-replay-freeze-v1",
            "frozen_at_utc": "2000-01-01T00:00:04+00:00",
            "training_freeze_sha256": R.digest(args.training_freeze),
            "source_files": sources,
            "fit_count": 189,
            "factor_cells": 27,
            "panels": {k: list(v) for k, v in R.PANELS.items()},
            "new_fits": 0,
            "outcomes_read_before_registration": False,
            "training_registration_commit": "a" * 40,
            "training_execution_source_commit": "b" * 40,
        }
        write(args.replay_freeze, freeze)
        (args.campaign / "fits").mkdir()
        for d, i, o in R.design_cells(cfg):
            for variant in cfg["variants"]:
                for suffix in (".json", ".started.json", ".npz"):
                    (args.campaign / "fits" / f"{variant}-d{d}-i{i}-o{o}{suffix}").touch()
        return args, cfg, receipt, result, freeze

    def test_no_fit_reads_before_two_terminal_gates_and_identity_checks(self):
        args, _, receipt, result, freeze = self.terminal_fixture()
        reader = R.read

        def guarded(path):
            self.assertNotIn("fits", Path(path).parts, "gate opened a fit outcome")
            return reader(path)

        with (
            patch.object(R, "read", side_effect=guarded),
            patch.object(R.Model, "load", side_effect=AssertionError("checkpoint opened during gate")),
        ):
            self.assertEqual(len(R.gate(args)[3]), 189)
            for status, code, result_status in (
                ("RUNNING", 0, "COMPLETE"),
                ("EXITED", 1, "COMPLETE"),
                ("EXITED", False, "COMPLETE"),
                ("EXITED", 0, "INCOMPLETE"),
            ):
                write(args.execution_receipt, {**receipt, "status": status, "exit_code": code})
                write(args.campaign / "RESULT.json", {**result, "status": result_status})
                with self.assertRaises(R.Incomplete):
                    R.run(args)
                self.assertFalse(args.output.exists())
            write(args.execution_receipt, receipt)
            write(args.campaign / "RESULT.json", result)
            wrong = deepcopy(freeze)
            wrong["source_files"]["cached_replay.py"] = "0" * 64
            write(args.replay_freeze, wrong)
            with self.assertRaisesRegex(ValueError, "source changed"):
                R.run(args)
            write(args.replay_freeze, freeze)
            next((args.campaign / "fits").glob("*.npz")).unlink()
            with self.assertRaisesRegex(ValueError, "exact grid"):
                R.run(args)
            args.execution_receipt.unlink()
            with self.assertRaises(R.Incomplete):
                R.run(args)

    def checkpoint_fixture(self):
        cfg = registered_config()
        cfg.update(train_episodes=8, dev_episodes=4, history_length=4, epochs=1, batch_size=8, target_parameters=128)
        identity = dict(variant="gru", data_seed=9915401, init_seed=9915501, order_seed=9915601)
        name = "gru-d9915401-i9915501-o9915601"
        directory = self.root / "tiny" / "fits"
        directory.mkdir(parents=True)
        hidden = {"gru": R.matched_hidden_dim("gru", R.INPUT_DIM, R.ACTION_DIM, 32, cfg["target_parameters"])}
        model = R.Model("gru", R.INPUT_DIM, R.ACTION_DIM, 32, hidden["gru"], identity["init_seed"])
        dev = R.generate_dataset(4, identity["data_seed"], "dev", 4)
        expanded = replace(dev, remaining_budget=np.full(4, 16.0), deadline=np.full(4, 20.0))
        panels = {
            name: evaluate_development_preparations(
                model, data, fixed1_tariff=R.PreparationTariff(**cfg["cost_profile"])
            )
            for name, data in (("original_resources", dev), ("expanded_resources", expanded))
        }
        record = {
            **identity,
            "status": "COMPLETE",
            "epochs_consumed": 1,
            "fit_step_calls_consumed": 1,
            "training_examples_consumed": 8,
            "checkpoint": name + ".npz",
            "checkpoint_sha256": model.save(directory / (name + ".npz")),
            "hidden_dim": hidden["gru"],
            "parameters": model.parameter_count,
            "initial_parameter_sha256": R.model_digest(model),
            "selected_parameter_sha256": R.model_digest(model),
            "selected_optimizer_state_sha256": R.model_digest(model, optimizer=True),
            "selected_checkpoint_steps": 0,
            "optimizer_steps_consumed": 0,
            "resource_panels": panels,
        }
        write(directory / (name + ".json"), record)
        write(directory / (name + ".started.json"), identity)
        return directory.parent, name, identity, cfg, dev, hidden, record

    def test_real_checkpoint_bridge_preserves_every_formal_oldcheap_episode(self):
        with patch.object(R.Model, "fit_step", side_effect=AssertionError("replay must not train")):
            campaign, name, identity, cfg, dev, hidden, original = self.checkpoint_fixture()
            record = R.replay_checkpoint(campaign, name, identity, cfg, dev, hidden)
            for resource, panel in record["resource_panels"].items():
                self.assertTrue(panel["formal_oldcheap_parity"])
                self.assertTrue(panel["old_cheap_bridge"]["parity"])
                self.assertEqual(
                    panel["arms"]["matched_cached_fixed1"]["per_episode"],
                    original["resource_panels"][resource]["arms"]["fixed_1_cheap"]["per_episode"],
                )
                for arm, horizons in R.PANELS.items():
                    meter = panel["policy_meters"][arm]
                    expected = int(dev.legal_actions.sum()) * len(horizons) if resource == "expanded_resources" else 0
                    self.assertEqual(meter["prediction_rows"], expected)
                    self.assertEqual(meter["planning_candidate_rows"], expected)
            bad = deepcopy(original)
            bad["resource_panels"]["expanded_resources"]["arms"]["fixed_1_cheap"]["per_episode"]["status"][0] = (
                "tampered"
            )
            write(campaign / "fits" / (name + ".json"), bad)
            with self.assertRaisesRegex(ValueError, "episode/aggregate parity"):
                R.replay_checkpoint(campaign, name, identity, cfg, dev, hidden)
            write(campaign / "fits" / (name + ".json"), original)
            with (campaign / "fits" / (name + ".npz")).open("ab") as stream:
                stream.write(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checkpoint byte identity"):
                R.replay_checkpoint(campaign, name, identity, cfg, dev, hidden)

    def test_failed_replay_retains_incomplete_receipt_and_refuses_overwrite(self):
        args, _, _, _, _ = self.terminal_fixture()
        with (
            patch.object(R, "generate_dataset", side_effect=RuntimeError("fixture data failure")),
            patch.object(R.Model, "load", side_effect=AssertionError("checkpoint must remain unopened")),
        ):
            result = R.run(args)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["replayed_checkpoints"], 0)
            self.assertEqual(result["new_fits"], 0)
            self.assertIsNone(result["summary"])
            self.assertEqual(result["failure"]["message"], "fixture data failure")
            self.assertEqual(R.read(args.output / "RESULT.json"), result)
            self.assertTrue((args.output / "attempt.json").exists())
            with self.assertRaises(FileExistsError):
                R.run(args)

    def test_aggregate_pairs_by_factor_identity_and_refuses_missing_cell(self):
        cfg = registered_config()
        cfg.update(
            data_seeds=[9915701, 9915702],
            init_seeds=[9915801, 9915802],
            order_seeds=[9915901, 9915902],
            variants=["gru"],
        )
        records = []
        for index, (d, i, o) in enumerate(R.design_cells(cfg)):
            arms = {
                name: {
                    metric: index + 0.25 * arm
                    for metric in (
                        "expected_net_utility",
                        "realized_net_utility",
                        "complete_environment_cost",
                        "stop_rate",
                    )
                }
                for arm, name in enumerate(R.PANELS)
            }
            records.append(
                dict(
                    variant="gru",
                    data_seed=d,
                    init_seed=i,
                    order_seed=o,
                    resource_panels={
                        resource: {"arms": arms} for resource in ("original_resources", "expanded_resources")
                    },
                )
            )
        summary = R.summarize(cfg, records[::-1])["gru"]["expanded_resources"]
        self.assertEqual(
            summary["paired_factor_cell_differences"]["cached_short13_minus_matched_cached_fixed1"][
                "expected_net_utility"
            ]["grand_mean"],
            0.25,
        )
        self.assertEqual(
            summary["paired_factor_cell_differences"]["cached_adaptive136_minus_matched_cached_fixed1"][
                "expected_net_utility"
            ]["finite_grid_variance"],
            0,
        )
        with self.assertRaisesRegex(ValueError, "incomplete or repeated"):
            R.summarize(cfg, records[:-1])


if __name__ == "__main__":
    unittest.main()
