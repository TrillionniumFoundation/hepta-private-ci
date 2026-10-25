"""Synthetic mechanism checks; these do not consume registered research tasks."""

from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from ..v6.data import EOS, Observation, SourceCorpus, SourceSplit, Target
from ..v6.observer import Recognizer, observe_tensors
from ..v7.data import make_batch
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .media import RawMediaArchive, reopen_archive_records
from .output_training import fit_arm, training_seeds
from .runtime import initialize, transition


class OutputTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        rng = torch.Generator().manual_seed(62)
        source = SourceSplit(torch.randint(256, (32, 1, 28, 28), generator=rng, dtype=torch.uint8),
                             torch.arange(32) % 10, tuple(f"unit:{i}" for i in range(32)),
                             tuple(f"unit-hash:{i}" for i in range(32)))
        self.corpus = SourceCorpus({"train": source}, {"manifest_sha256": "unit-fixture-only"})
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(8)
            self.model = SlotPortfolio()
            self.observer = Recognizer().eval().requires_grad_(False)
        self.warm = Snapshot(self.model, {"source_manifest_sha256": "unit-fixture-only"})
        self.protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        self.protocol.update({"study": "synthetic-unit-fixture-only", "training_seeds": [17]})
        self.protocol["training"].update({"fine_tuning_steps": 1, "fine_tuning_conditions_per_step": 2,
                                          "fine_tuning_scenarios_per_condition": 2, "checkpoint_interval": 1})

    def fit(self, path, arm, warm=None):
        with redirect_stdout(io.StringIO()):
            return fit_arm(warm or self.warm, self.corpus, self.observer, path, 17, arm, self.protocol)

    def rows(self, path):
        with gzip.open(path / "training-outputs.jsonl.gz", "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]

    def batch(self):
        batch = make_batch(self.corpus, "train", 2, training_seeds(17, 0)[0])
        observation = Observation(*(value.repeat_interleave(2, 0) for value in
                                  (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
        target = Target(*(value.repeat_interleave(2, 0) for value in
                         (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
        return observation, target

    def test_actual_media_scores_deployment_parity_and_separate_output_gradients(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs, reports, snapshots, rows = {}, {}, {}, {}
            for arm in self.protocol["training"]["arms"]:
                outputs[arm] = Path(directory) / arm
                # An outer read-only caller must not create inference tensors
                # that break the registered score-function backward program.
                with torch.inference_mode():
                    snapshots[arm], reports[arm] = self.fit(outputs[arm], arm)
                rows[arm] = self.rows(outputs[arm])
            first = rows["sft_continuation"]
            self.assertEqual(rows["output_mean"], first)
            self.assertEqual(rows["output_ndu"], first)
            self.assertEqual(len({report["schedule_sha256"] for report in reports.values()}), 1)
            pixels, captions = reopen_archive_records(outputs["output_ndu"] / "raw-media.zip",
                                                      [row["raw"] for row in first])
            observation, target = self.batch()
            rescored = observe_tensors(self.observer, pixels, captions, target.pixels, target.labels)
            self.assertEqual([row["metric"] for row in first], rescored)
            for row in first:
                self.assertEqual(row["actual_observed_loss"], -row["metric"]["utility"])
                self.assertAlmostEqual(row["actual_observed_loss"], 2 * row["metric"]["joint_loss"] - 1)
                self.assertNotEqual(row["actual_observed_loss"], row["metric"]["joint_loss"])
            with torch.no_grad():
                rng = torch.Generator().manual_seed(training_seeds(17, 0)[1])
                run = initialize(self.model.eval(), observation, generator=rng)
                for action in self.protocol["fixed_policy"]:
                    run = transition(self.model, run, action, generator=rng)
            self.assertTrue(torch.equal(pixels, run.pixels))
            self.assertEqual([row["sampled_tokens"] for row in first], run.tokens.tolist())
            self.assertEqual([row["terminal_log_probability"] for row in first],
                             run.terminal_log_probability.tolist())
            self.assertEqual(reports["sft_continuation"]["output_score_gradient_abs_sum_max"], {})
            for arm, report in reports.items():
                self.assertEqual(report["terminal_output_rows"], 4)
                self.assertEqual(report["work"]["emission_calls"], 3)
                self.assertEqual(report["work"]["state_transition_calls"], 4)
                self.assertEqual(report["work"]["primary_scored_output_pairs"], 4)
                self.assertEqual(report["work"]["sampled_bernoulli_variables"], 3 * 4 * 28 * 56)
                self.assertEqual([entry["step"] for entry in report["optimizer_checkpoints"]], [0, 1])
                checkpoint = torch.load(report["optimizer_checkpoints"][-1]["path"], weights_only=True)
                self.assertEqual(checkpoint["parameter_sha256"], snapshots[arm].parameter_sha256)
                self.assertTrue(checkpoint["optimizer_state_dict"]["state"])
                self.assertEqual(checkpoint["metadata"]["next_generation_seed"], training_seeds(17, 1)[1])
                self.assertGreater(report["nested_phases"]["physical_media_write_fsync_reopen"]["wall_ns"], 0)
                if arm != "sft_continuation":
                    self.assertEqual(report["work"]["output_score_gradient_probe_backwards"], 1)
                    for module in ("pixel_encoder", "semantic_cell", "pixel_decoder", "text_decoder", "text_projection"):
                        self.assertGreater(report["output_score_gradient_abs_sum_max"][module], 0, (arm, module))
                history = json.loads((outputs[arm] / "history.json").read_text())[0]
                self.assertAlmostEqual(history["actual_utility_mean"], sum(row["utility"] for row in rescored) / 4,
                                       places=6)
                self.assertEqual(report["native_auxiliary_weight"], 1. if arm == "sft_continuation" else .05)
            self.assertEqual(len({snapshot.parameter_sha256 for snapshot in snapshots.values()}), 3)
            prior = hashlib.sha256((outputs["output_ndu"] / "summary.json").read_bytes()).hexdigest()
            with self.assertRaises(FileExistsError):
                self.fit(outputs["output_ndu"], "output_ndu")
            self.assertEqual(hashlib.sha256((outputs["output_ndu"] / "summary.json").read_bytes()).hexdigest(), prior)

    def test_early_eos_is_retained_as_empty_failed_output_without_resampling(self):
        with torch.no_grad():
            self.model.text_projection.weight.zero_()
            self.model.text_projection.bias.fill_(-80.)
            self.model.text_projection.bias[EOS] = 80.
        warm = Snapshot(self.model, {"source_manifest_sha256": "unit-fixture-only"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "empty-caption"
            _, report = self.fit(output, "output_mean", warm)
            rows = self.rows(output)
            _, captions = reopen_archive_records(output / "raw-media.zip", [row["raw"] for row in rows])
            self.assertEqual(captions, [""] * 4)
            self.assertEqual(report["terminal_output_rows"], 4)
            self.assertEqual(report["work"]["emission_calls"], 3)
            for row in rows:
                self.assertFalse(row["raw"]["required_output_complete"])
                self.assertFalse(row["metric"]["caption_valid"])
                self.assertEqual(row["metric"]["text_fact"], 1.)
                self.assertEqual(row["metric"]["relation"], 1.)
                self.assertEqual(row["actual_observed_loss"], -row["metric"]["utility"])

    def test_failed_io_retains_costs_and_initial_checkpoint_without_completion_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed"
            with patch.object(RawMediaArchive, "append", side_effect=OSError("unit I/O failure")):
                with self.assertRaisesRegex(OSError, "unit I/O failure"):
                    self.fit(output, "output_ndu")
            failure = json.loads((output / "failure.json").read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["completed_steps"], 0)
            self.assertEqual(failure["known_completed_work"]["emission_calls"], 3)
            self.assertEqual([item["step"] for item in failure["checkpoints"]], [0])
            self.assertGreater(failure["nested_phases"]["physical_media_write_fsync_reopen"]["wall_ns"], 0)
            self.assertFalse((output / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
